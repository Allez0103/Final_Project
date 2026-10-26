"""Immutable, family-separated preference data. No CAD operations in this module.

Confirmed choices (including explicit exceptions) are preference labels only.
Neither UNKNOWN nor an untested user choice is converted into a collision label.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from dataclasses import fields
from pathlib import Path

from pa2.cad.directions import GLOBALS
from pa2.domain.models import AssemblyGroup, Bounds, ContactEdge, MatchingStatus, PartType
from pa2.planning.priority import ExteriorPriorityProvider, is_fastener
from pa2.storage.database import ConfirmationRecord, GenerationRecord, ImportSnapshotRecord, LearningObservation
from .features import FeatureBuilder

DIRECTION_SCHEMA = 'direction-features-v1'
DATA_SCHEMA = 'shared-preferences-v21'


def atomic_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2,
                                    allow_nan=False), encoding='utf-8')
    temporary.replace(path)


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode()).hexdigest()


def unpack(case):
    payload = case['payload']
    allowed = {f.name for f in fields(AssemblyGroup)}
    groups = []
    for source in payload['groups']:
        row = {k: v for k, v in source.items() if k in allowed}
        row['bounds'] = Bounds(**row['bounds'])
        row['part_type'] = PartType(row['part_type'])
        row['matching_status'] = MatchingStatus(row['matching_status'])
        row['centroid'] = tuple(row['centroid']) if row.get('centroid') else None
        groups.append(AssemblyGroup(**row))
    contacts = [ContactEdge(**row) for row in payload['contacts']]
    return groups, contacts, payload['base_group_id']


def direction_rows(builder, remaining, gid, directions=GLOBALS):
    """Six cheap AABB/contact features, identical at capture and inference time."""
    common = builder.rows(remaining)[gid]
    group = builder.groups[gid]
    obstacles = [builder.groups[x] for x in sorted(remaining - {gid})]
    neighbors = {e.group_b if e.group_a == gid else e.group_a for e in builder.contacts
                 if gid in (e.group_a, e.group_b)} & (remaining - {gid})
    center = group.centroid or group.bounds.center
    d = max(builder.d, 1e-9)
    output = []
    for direction in directions:
        coverage, count = ExteriorPriorityProvider().direction_score(group, obstacles, direction)
        away = [sum((center[i] - builder.groups[n].bounds.center[i]) * direction[i]
                    for i in range(3)) / d for n in neighbors]
        row = dict(common, direction_x=direction[0], direction_y=direction[1],
                   direction_z=direction[2], exposure_coverage=coverage,
                   exposure_obstacles=count, contact_away_mean=sum(away)/len(away) if away else None,
                   contact_away_min=min(away) if away else None,
                   directed_size=sum(abs(direction[i])*group.bounds.size[i] for i in range(3))/d)
        output.append(row)
    return output


def ranking_states(case):
    """State identities/counts need no candidate feature matrix."""
    groups, _, base = unpack(case)
    remaining = {g.id for g in groups if not is_fastener(g)} | {base}
    for step in reversed(case['payload']['steps']):
        gid = step['group_id']
        if gid not in remaining or gid == base:
            continue
        if len(remaining-{base}) >= 2:
            yield dict(gid=gid, remaining=sorted(remaining))
        remaining.remove(gid)


def choice_groups(case, role):
    groups, contacts, base = unpack(case)
    builder = FeatureBuilder(groups, contacts, base, case['product_type'])
    general = {g.id for g in groups if not is_fastener(g)} | {base}
    remaining = set(general)
    if case.get('label_operations'):
        # Preserve unordered, simultaneous source operations as tied positives.
        for op in reversed(case['label_operations']):
            selected=set(op['group_ids'])&remaining-{base}
            if not selected:continue
            if role=='ranking':
                rows=builder.rows(remaining);ids=sorted(rows)
                if len(ids)>=2 and len(selected)<len(ids):
                    yield dict(ids=ids,rows=[rows[x] for x in ids],labels=[int(x in selected) for x in ids],remaining=sorted(remaining))
            else:
                vector=op['removal_direction'];length=math.sqrt(sum(float(v)**2 for v in vector))
                dots=[sum(float(a)*b for a,b in zip(vector,d))/length if length else -1 for d in GLOBALS]
                axis=max(range(6),key=dots.__getitem__)
                if dots[axis]>=math.cos(math.radians(1)):
                    for gid in sorted(selected):
                        yield dict(gid=gid,ids=list(range(6)),rows=direction_rows(builder,remaining,gid),
                                   labels=[int(i==axis) for i in range(6)],axis=axis,remaining=sorted(remaining))
            remaining-=selected
        return
    for step in reversed(case['payload']['steps']):
        gid = step['group_id']
        if gid not in remaining or gid == base:
            continue
        if role == 'ranking':
            rows = builder.rows(remaining)
            if len(rows) >= 2:
                ids = sorted(rows)
                yield dict(gid=gid, ids=ids, rows=[rows[x] for x in ids],
                           labels=[int(x == gid) for x in ids], remaining=sorted(remaining))
        else:
            vector = step['removal_direction']
            length = math.sqrt(sum(float(v)**2 for v in vector))
            dots = [sum(float(a)*b for a, b in zip(vector, axis))/length if length else -1
                    for axis in GLOBALS]
            label = max(range(6), key=dots.__getitem__)
            # Arbitrary user directions are retained in observations, not rounded
            # into a false six-axis teaching label.
            if dots[label] >= math.cos(math.radians(1.0)):
                yield dict(gid=gid, ids=list(range(6)),
                           rows=direction_rows(builder, remaining, gid),
                           labels=[int(i == label) for i in range(6)],
                           axis=label, remaining=sorted(remaining))
        remaining.remove(gid)


def recorded_snapshot(database):
    """Latest complete confirmation per project; identical observations once only."""
    with database.session() as session:
        records = session.query(LearningObservation, ConfirmationRecord).join(
            ConfirmationRecord, LearningObservation.confirmation_id == ConfirmationRecord.id
        ).order_by(ConfirmationRecord.created_at.desc(), LearningObservation.id.desc()).all()
        generations = {g.plan_id: g for g in session.query(GenerationRecord).all()}
        imports = {s.id: s for s in session.query(ImportSnapshotRecord).all()}
    seen_projects, seen_signatures, cases = set(), set(), []
    for observation, confirmation in records:
        p = observation.payload_json
        ids = {g['id'] for g in p.get('groups', [])}
        if (not ids or {s['group_id'] for s in p.get('steps', [])} != ids - {p.get('base_group_id')}
                or p.get('base_group_id') not in ids):
            continue
        if confirmation.project_id in seen_projects:
            continue
        case = dict(id=observation.id, project_id=confirmation.project_id,
                    confirmation_id=confirmation.id, family=observation.family_id,
                    signature=observation.signature, product_type=observation.product_type,
                    payload=p, confirmed_plan=confirmation.plan_snapshot_json)
        generation = generations.get(confirmation.plan_id)
        case['source_settings'] = generation.settings_json if generation else {}
        imported = imports.get(p['snapshot_id'])
        case['contact_ready'] = bool(imported and imported.calculation_ready)
        case['contact_graph'] = next((d for d in imported.diagnostics_json
            if d.get('code') == 'CONTACT_GRAPH'), {}) if imported else {}
        # Validate the cheap features now, before freezing a malformed snapshot.
        choices = list(ranking_states(case))
        # A complete confirmed project counts once even if it has only one
        # movable general part (no ranking query); its direction is still useful.
        seen_projects.add(confirmation.project_id)
        seen_signatures.add(observation.signature)
        cases.append(case)
    families = sorted({c['family'] for c in cases})
    heldout = families[::5]
    state_ids = {digest(dict(family=c['family'], base=c['payload']['base_group_id'], gid=s['gid'],
                            members=sorted((g['id'], sorted(g['body_ids'])) for g in c['payload']['groups']),
                            remaining=s['remaining']))
                 for c in cases for s in ranking_states(c)}
    return dict(schema=DATA_SCHEMA, cases=sorted(cases, key=lambda c: c['id']),project_ids=sorted(seen_projects),
                families=families, heldout_families=heldout,
                state_ids=sorted(state_ids),
                counts=dict(families=len(families), states=len(state_ids), projects=len(cases)))


def direction_readiness(cases, settings):
    axes = Counter(s['axis'] for c in cases for s in choice_groups(c, 'direction'))
    usable_axes = sum(count >= settings.direction_min_per_axis for count in axes.values())
    ready = sum(axes.values()) >= settings.direction_min_samples and usable_axes >= settings.direction_min_axes
    return ready, dict(samples=sum(axes.values()), axes=dict(axes),
                       reason='학습 가능' if ready else '방향 선호 사례 또는 축별 다양성 부족: 방향 모델만 보류')
