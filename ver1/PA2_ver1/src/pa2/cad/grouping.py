from __future__ import annotations

import itertools
import math
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from pa2.domain.classification import classify_part, normalized_stem
from pa2.domain.models import AssemblyGroup, AtomicBody, Bounds, MatchingStatus, PartType

from .importer import CadScene


@dataclass(slots=True)
class PartDefinitionData:
    id: str
    source_hash: str
    original_name: str
    part_type: PartType
    bodies: list[AtomicBody]


@dataclass(slots=True)
class GroupingResult:
    groups: list[AssemblyGroup]
    definitions: list[PartDefinitionData]
    unresolved_body_ids: list[str]
    ambiguous: list[dict[str, object]] = field(default_factory=list)
    fallback_matches: list[dict[str, object]] = field(default_factory=list)
    rotation_matches: list[dict[str, object]] = field(default_factory=list)
    anchor_matches: list[dict[str, object]] = field(default_factory=list)
    relaxed_matches: list[dict[str, object]] = field(default_factory=list)

    def assert_partition(self, all_body_ids: Iterable[str]) -> None:
        expected = set(all_body_ids)
        actual = [body_id for group in self.groups for body_id in group.body_ids]
        if len(actual) != len(set(actual)):
            raise AssertionError("atomic_body가 둘 이상의 assembly_group에 포함되었습니다.")
        if set(actual) != expected:
            raise AssertionError("assembly_group 분할에 누락 또는 알 수 없는 body가 있습니다.")


def _distance(a: tuple[float, float, float] | None, b: tuple[float, float, float] | None) -> float | None:
    if a is None or b is None:
        return None
    return math.sqrt(sum((x-y)**2 for x, y in zip(a, b)))


def _volume_match(a: float | None, b: float | None, relative_tolerance: float) -> bool:
    if a is None or b is None:
        return False
    return abs(a-b) <= max(abs(a), abs(b), 1.0) * relative_tolerance


def _volume_area_match(a: AtomicBody, b: AtomicBody, relative_tolerance: float) -> bool:
    if not _volume_match(a.volume_mm3, b.volume_mm3, relative_tolerance):
        return False
    if a.area_mm2 is None or b.area_mm2 is None:
        return False
    if abs(a.area_mm2-b.area_mm2) > max(abs(a.area_mm2), abs(b.area_mm2), 1.0) * relative_tolerance:
        return False
    return True


def _body_match(a: AtomicBody, b: AtomicBody, relative_tolerance: float) -> bool:
    if not _volume_area_match(a,b,relative_tolerance):
        return False
    source_sizes = sorted(a.bounds.size)
    target_sizes = sorted(b.bounds.size)
    return all(abs(x-y) <= max(abs(x), abs(y), 1.0) * relative_tolerance for x, y in zip(source_sizes, target_sizes))


def _make_group(group_id: str, name: str, bodies: list[AtomicBody], part_type: PartType, status: MatchingStatus, definition_id: str | None) -> AssemblyGroup:
    valid_volumes = [(body.volume_mm3, body.centroid) for body in bodies if body.volume_mm3 and body.centroid]
    total = sum(volume for volume, _ in valid_volumes)
    centroid = None
    if total > 0:
        centroid = tuple(sum(volume * center[i] for volume, center in valid_volumes) / total for i in range(3))
    return AssemblyGroup(
        id=group_id,
        display_name=name,
        body_ids=[body.id for body in bodies],
        part_type=part_type,
        bounds=Bounds.union(body.bounds for body in bodies),
        volume_mm3=total if total > 0 else None,
        centroid=centroid,  # type: ignore[arg-type]
        geometry_valid=all(body.geometry_valid for body in bodies),
        matching_status=status,
        part_definition_id=definition_id,
    )


class GroupingService:
    VERSION = "grouping-v5-unique-unmatched-relaxation"
    FALLBACK_RELATIVE_TOLERANCE = 0.001  # 0.1%; grouping only, not collision epsilon.
    FALLBACK_POSITION_TOLERANCE_MM = 0.005
    ANCHOR_RETRY_NODE_LIMIT = 50000
    ANCHOR_RETRY_SECONDS = 2.0
    ANCHOR_RETRY_BODY_LIMIT = 128
    # Only after ALL previously successful matching stages; never collision tolerances.
    EXTENDED_RELATIVE_TOLERANCE = 0.002  # 0.2% volume/area/size
    EXTENDED_POSITION_TOLERANCE_MM = 0.01

    def __init__(self, volume_relative_tolerance: float = 1e-4, position_tolerance_mm: float = 0.05) -> None:
        self.volume_relative_tolerance = volume_relative_tolerance
        self.position_tolerance_mm = position_tolerance_mm

    def resolve(self, assembly: CadScene, part_scenes: list[CadScene]) -> GroupingResult:
        definitions = [
            PartDefinitionData(
                id=f"partdef-{scene.source_hash[:16]}",
                source_hash=scene.source_hash,
                original_name=scene.original_name or scene.source_path.name,
                part_type=classify_part(scene.original_name or scene.source_path.name),
                bodies=scene.bodies,
            )
            for scene in part_scenes
        ]
        definitions.sort(key=lambda item: (-len(item.bodies), item.original_name.upper()))
        remaining = {body.id: body for body in assembly.bodies}
        groups: list[AssemblyGroup] = []
        ambiguous: list[dict[str, object]] = []
        occurrence_counts: dict[str, int] = {}

        for definition in definitions:
            matches = self._find_matches(definition, list(remaining.values()))
            # Deterministically accept disjoint rigid matches; repeated single-body parts become distinct groups.
            accepted: list[tuple[AtomicBody, ...]] = []
            consumed: set[str] = set()
            for match in matches:
                ids = {body.id for body in match}
                if ids & consumed:
                    ambiguous.append({"part_definition": definition.id, "candidate_body_ids": sorted(ids), "reason": "overlapping-candidate"})
                    continue
                accepted.append(match)
                consumed.update(ids)
            for occurrence_index, match in enumerate(accepted, start=1):
                group_id = f"group-{definition.source_hash[:10]}-{occurrence_index:04d}"
                suffix = f" #{occurrence_index}" if len(accepted) > 1 else ""
                groups.append(_make_group(group_id, f"{Path(definition.original_name).stem}{suffix}", list(match), definition.part_type, MatchingStatus.MATCHED, definition.id))
                for body in match:
                    remaining.pop(body.id, None)
            occurrence_counts[definition.id] = len(accepted)

        # Finish ALL strict definitions before retrying only unclaimed bodies.
        # Gather candidates before accepting any, so definition order cannot
        # turn an ambiguous relaxed match into an apparently unique one.
        fallback = GroupingService(self.FALLBACK_RELATIVE_TOLERANCE, self.FALLBACK_POSITION_TOLERANCE_MM)
        retry_candidates = [(definition, fallback._find_matches(definition, list(remaining.values())))
                            for definition in definitions]
        claims: dict[str, set[str]] = {}
        for definition, matches in retry_candidates:
            for match in matches:
                for body in match:
                    claims.setdefault(body.id, set()).add(definition.id)
        fallback_matches: list[dict[str, object]] = []
        for definition, matches in retry_candidates:
            if not matches:
                continue
            if len(matches) != 1:
                ambiguous.append({"part_definition": definition.id, "reason": "fallback-multiple-candidates",
                                  "candidate_count": len(matches)})
                continue
            match = matches[0]
            ids = sorted(body.id for body in match)
            if any(len(claims[body_id]) != 1 for body_id in ids):
                ambiguous.append({"part_definition": definition.id, "candidate_body_ids": ids,
                                  "reason": "fallback-competing-definitions"})
                continue
            occurrence_index = occurrence_counts[definition.id] + 1
            group_id = f"group-{definition.source_hash[:10]}-{occurrence_index:04d}"
            suffix = f" #{occurrence_index}" if occurrence_index > 1 else ""
            groups.append(_make_group(group_id, f"{Path(definition.original_name).stem}{suffix}", list(match),
                                      definition.part_type, MatchingStatus.MATCHED, definition.id))
            for body_id in ids:
                remaining.pop(body_id)
            fallback_matches.append({"part_definition": definition.id, "group_id": group_id,
                                     "body_ids": ids, "relative_tolerance": self.FALLBACK_RELATIVE_TOLERANCE,
                                     "position_tolerance_mm": self.FALLBACK_POSITION_TOLERANCE_MM,
                                     "reason": "unique-unmatched-candidate"})
            occurrence_counts[definition.id] = occurrence_index

        # Rotation retry is separate from the existing widened AIR-BENT retry.
        # Existing accepted bodies/IDs/names are immutable. Repeated rotated
        # occurrences may match, but every body must have ONE definition owner.
        rotation_matches = self._rotation_retry(assembly, part_scenes, definitions,
            remaining, groups, ambiguous, occurrence_counts)

        # Only AFTER every legacy stage: never take a previously accepted body.
        anchor_matches = self._anchor_retry(definitions, remaining, groups,
            ambiguous, occurrence_counts, retry_candidates)

        extended = GroupingService(self.EXTENDED_RELATIVE_TOLERANCE,
                                   self.EXTENDED_POSITION_TOLERANCE_MM)
        relaxed_matches = self._anchor_retry(definitions, remaining, groups,
            ambiguous, occurrence_counts, retry_candidates,
            profiles=((extended, 'extended-unmatched-only'),), retry_all=True)

        for body in sorted(remaining.values(), key=lambda item: item.id):
            inferred = classify_part(body.display_name)
            groups.append(_make_group(f"group-{body.id}", body.display_name, [body], inferred, MatchingStatus.UNMATCHED, None))
        groups.sort(key=lambda item: item.id)
        result = GroupingResult(groups, definitions, sorted(remaining), ambiguous,
                                fallback_matches, rotation_matches, anchor_matches, relaxed_matches)
        result.assert_partition(body.id for body in assembly.bodies)
        return result

    def _anchor_retry(self, definitions, remaining, groups, ambiguous, occurrence_counts, legacy_candidates,
                      *, profiles=None, retry_all=False):
        """Bounded retry for Cartesian-overflow cases, with unchanged features/tolerances.

        Anchor the most selective (then largest) body; reject duplicate targets
        and incompatible pair distances before extending a partial assignment.
        Never accept a partial search or choose between distinct body sets.
        """
        if not remaining:
            return []
        started = time.monotonic()
        deadline = started + self.ANCHOR_RETRY_SECONDS
        targets = sorted(remaining.values(), key=lambda body: body.id)
        domains = []
        seen_definitions = set()
        owners: dict[str, set[str]] = {}
        relaxed = GroupingService(self.FALLBACK_RELATIVE_TOLERANCE, self.FALLBACK_POSITION_TOLERANCE_MM)
        profiles = profiles or ((self, 'existing-strict'), (relaxed, 'existing-unmatched-fallback'))
        # Widening cannot resolve proven multiple candidates or competitors.
        # Retain their ownership below, but do not repeat the same rejection.
        rejected={str(item['part_definition']) for item in ambiguous
                  if retry_all and item.get('reason') in {
                      'fallback-multiple-candidates','fallback-competing-definitions',
                      'anchor-multiple-body-sets','anchor-competing-definitions','anchor-search-budget'}}
        for definition in definitions:
            if definition.id in seen_definitions:
                continue
            seen_definitions.add(definition.id)
            for checker, profile in profiles:
                candidates = [[b for b in targets if _body_match(a, b, checker.volume_relative_tolerance)]
                              for a in definition.bodies]
                if not candidates or any(not items for items in candidates):
                    continue
                combinations = math.prod(len(items) for items in candidates)
                # Include potential owners in BOTH existing tolerance profiles.
                for items in candidates:
                    for body in items:
                        owners.setdefault(body.id, set()).add(definition.id)
                if definition.id not in rejected and (retry_all or (len(candidates) > 1 and combinations > 50000)):
                    domains.append((definition, candidates, combinations, checker, profile))
        # Also respect unresolved claims from the old relaxed/rotation stages.
        for definition, instances in legacy_candidates:
            for instance in instances:
                if all(b.id in remaining for b in instance):
                    for body in instance:
                        owners.setdefault(body.id, set()).add(definition.id)
        for item in ambiguous:
            for bid in item.get('candidate_body_ids', []):
                if bid in remaining:
                    owners.setdefault(bid, set()).add(str(item['part_definition']))

        nodes = 0
        found = []
        settled = set()
        attempts = {}
        for definition, candidates, combinations, checker, profile in domains:
            if definition.id in settled:
                continue
            before_nodes = nodes
            begin = time.monotonic()
            solutions: dict[tuple[str, ...], tuple[AtomicBody, ...]] = {}
            complete = True
            n = len(candidates)
            order = sorted(range(n), key=lambda i: (len(candidates[i]),
                -(definition.bodies[i].volume_mm3 or 0), i))
            assigned = {}; used = set()
            distances = ({(i, j): _distance(definition.bodies[i].centroid, definition.bodies[j].centroid)
                          for i in range(n) for j in range(i)}
                         if n <= self.ANCHOR_RETRY_BODY_LIMIT else {})

            def visit(depth):
                nonlocal nodes, complete
                if time.monotonic() >= deadline or nodes >= self.ANCHOR_RETRY_NODE_LIMIT:
                    complete = False
                    return
                if depth == n:
                    match = tuple(assigned[i] for i in range(n))
                    solutions.setdefault(tuple(sorted(b.id for b in match)), match)
                    return
                i = order[depth]
                for target in candidates[i]:
                    if time.monotonic() >= deadline or nodes >= self.ANCHOR_RETRY_NODE_LIMIT:
                        complete = False
                        return
                    nodes += 1
                    if target.id in used:
                        continue
                    compatible = True
                    for j, other in assigned.items():
                        expected = distances[max(i,j), min(i,j)]
                        actual = _distance(target.centroid, other.centroid)
                        if expected is None or actual is None or abs(expected-actual) > checker.position_tolerance_mm:
                            compatible = False
                            break
                    if not compatible:
                        continue
                    assigned[i] = target; used.add(target.id)
                    visit(depth+1)
                    used.remove(target.id); del assigned[i]
                    if not complete or len(solutions) > 1:
                        return  # Multiple body sets already prove ambiguity.

            if n > self.ANCHOR_RETRY_BODY_LIMIT:
                complete = False
            else:
                visit(0)
            info = dict(part_definition=definition.id, raw_combinations=combinations,
                attempted_nodes=nodes-before_nodes, elapsed_sec=time.monotonic()-begin,
                search_complete=complete and len(solutions) < 2, distinct_body_sets=len(solutions),
                ambiguity_proven=len(solutions) > 1,
                relative_tolerance=checker.volume_relative_tolerance,
                position_tolerance_mm=checker.position_tolerance_mm, tolerance_profile=profile,
                node_limit=self.ANCHOR_RETRY_NODE_LIMIT, stage_time_limit_sec=self.ANCHOR_RETRY_SECONDS)
            if not complete or len(solutions) > 1:
                settled.add(definition.id)
                ambiguous.append(dict(info, reason='anchor-search-budget' if not complete else 'anchor-multiple-body-sets'))
                continue
            if not solutions:
                attempts.setdefault(definition.id, []).append(info)
                continue
            ids, match = next(iter(solutions.items()))
            settled.add(definition.id)
            if any(owners[bid] != {definition.id} for bid in ids):
                ambiguous.append(dict(info, candidate_body_ids=list(ids), reason='anchor-competing-definitions'))
                continue
            info['previous_profile_attempts'] = attempts.get(definition.id, [])
            found.append((definition, match, info))

        # All ownership checks precede acceptance; input order cannot remove a
        # competing candidate and make a later definition appear unique.
        accepted = []
        for definition, match, info in found:
            index = occurrence_counts[definition.id] + 1
            gid = f'group-{definition.source_hash[:10]}-{index:04d}'
            suffix = f' #{index}' if index > 1 else ''
            groups.append(_make_group(gid, f'{Path(definition.original_name).stem}{suffix}', list(match),
                definition.part_type, MatchingStatus.MATCHED, definition.id))
            occurrence_counts[definition.id] = index
            for body in match:
                remaining.pop(body.id)
            accepted.append(dict(info, group_id=gid, body_ids=[b.id for b in match],
                reason='unique-unmatched-anchor-distance-pruning'))
        return accepted

    def _rotation_retry(self, assembly, part_scenes, definitions, remaining, groups, ambiguous, occurrence_counts):
        if not remaining:return []
        from .rotation_signature import signature, equivalent
        source_shapes={bid:shape for scene in part_scenes for bid,shape in scene.shapes.items()}
        fingerprints={}
        tolerance=min(self.volume_relative_tolerance,1e-4)
        def fingerprint(side, body, shape):
            key=(side,body.id)
            if key not in fingerprints:
                try:fingerprints[key]=signature(shape)
                except Exception:
                    fingerprints[key]=None  # No guess when native features fail.
            return fingerprints[key]
        def matches(a,b):
            if not _volume_area_match(a,b,tolerance):return False
            left,right=source_shapes.get(a.id),assembly.shapes.get(b.id)
            if left is None or right is None:return False
            x,y=fingerprint('part',a,left),fingerprint('assembly',b,right)
            return x is not None and y is not None and equivalent(x,y,tolerance)
        candidates=[(d,self._find_matches(d,list(remaining.values()),body_match=matches)) for d in definitions]
        claims={}
        for d,instances in candidates:
            for instance in instances:
                for body in instance:claims.setdefault(body.id,set()).add(d.id)
        tied={bid for bid,owners in claims.items() if len(owners)>1}
        name_resolved=set()
        if tied:
            from .step_name_hints import definition_hints
            try:hints=definition_hints(assembly,tied)
            except Exception:hints={}
            for bid in tied:
                owners={d.id for d in definitions if d.id in claims[bid]
                        and normalized_stem(d.original_name) in hints.get(bid,set())}
                if len(owners)==1:
                    claims[bid]=owners;name_resolved.add(bid)
        candidates=[(d,[instance for instance in instances if all(
            len(claims[b.id])!=1 or d.id in claims[b.id] for b in instance)]) for d,instances in candidates]
        accepted=[]
        for d,instances in candidates:
            counts={}
            for instance in instances:
                for body in instance:counts[body.id]=counts.get(body.id,0)+1
            for instance in instances:
                ids=sorted(b.id for b in instance)
                competing=any(len(claims[bid])!=1 for bid in ids)
                overlapping=any(counts[bid]!=1 for bid in ids)
                if competing or overlapping:
                    ambiguous.append(dict(part_definition=d.id,candidate_body_ids=ids,
                        reason='rotation-competing-definitions' if competing else 'rotation-overlapping-candidates'))
                    continue
                index=occurrence_counts[d.id]+1
                gid=f'group-{d.source_hash[:10]}-{index:04d}'
                suffix=f' #{index}' if index>1 or len(instances)>1 else ''
                groups.append(_make_group(gid,f'{Path(d.original_name).stem}{suffix}',list(instance),
                    d.part_type,MatchingStatus.MATCHED,d.id))
                occurrence_counts[d.id]=index
                for bid in ids:remaining.pop(bid)
                accepted.append(dict(part_definition=d.id,group_id=gid,body_ids=ids,
                    relative_tolerance=tolerance,position_tolerance_mm=self.position_tolerance_mm,
                    reason='unique-definition-rotation-invariant-features',
                    native_step_name_tie_break=any(bid in name_resolved for bid in ids),
                    features=['volume','surface_area','principal_inertia','face_types_areas','curve_types_lengths']))
        return accepted

    def _find_matches(self, definition: PartDefinitionData, assembly_bodies: list[AtomicBody], *, body_match=None) -> list[tuple[AtomicBody, ...]]:
        source = definition.bodies
        if not source:
            return []
        candidate_lists = [
            [target for target in assembly_bodies if (body_match(item,target) if body_match else _body_match(item, target, self.volume_relative_tolerance))]
            for item in source
        ]
        if any(not candidates for candidates in candidate_lists):
            return []
        if len(source) == 1:
            return [(item,) for item in sorted(candidate_lists[0], key=lambda body: body.id)]
        # Protect real projects from factorial explosion; unresolved is safer than a guessed group.
        combination_budget = 50000
        count = 1
        for candidates in candidate_lists:
            count *= len(candidates)
            if count > combination_budget:
                return []
        source_distances = {
            (i, j): _distance(source[i].centroid, source[j].centroid)
            for i in range(len(source)) for j in range(i + 1, len(source))
        }
        matches: list[tuple[AtomicBody, ...]] = []
        for candidate_tuple in itertools.product(*candidate_lists):
            if len({item.id for item in candidate_tuple}) != len(candidate_tuple):
                continue
            compatible = True
            for (i, j), expected in source_distances.items():
                actual = _distance(candidate_tuple[i].centroid, candidate_tuple[j].centroid)
                if expected is None or actual is None or abs(expected - actual) > self.position_tolerance_mm:
                    compatible = False
                    break
            if compatible:
                matches.append(candidate_tuple)
        unique: dict[tuple[str, ...], tuple[AtomicBody, ...]] = {}
        for match in matches:
            unique[tuple(sorted(body.id for body in match))] = match
        return [unique[key] for key in sorted(unique)]

