from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol

from pa2.domain.models import AssemblyGroup, ContactEdge, PartType


class PriorityProvider(Protocol):
    name: str
    def rank(self, groups: dict[str, AssemblyGroup], remaining: set[str], base_group_id: str, contacts: list[ContactEdge]) -> list[str]: ...


@dataclass(slots=True)
class DefaultPriorityProvider:
    name: str = "default"

    def rank(self, groups: dict[str, AssemblyGroup], remaining: set[str], base_group_id: str, contacts: list[ContactEdge]) -> list[str]:
        base = groups[base_group_id]
        neighbors: dict[str, set[str]] = {group_id: set() for group_id in remaining}
        for edge in contacts:
            if edge.group_a in remaining and edge.group_b in remaining:
                neighbors[edge.group_a].add(edge.group_b)
                neighbors[edge.group_b].add(edge.group_a)

        def distance(group: AssemblyGroup) -> float:
            a = group.centroid or group.bounds.center
            b = base.centroid or base.bounds.center
            return math.sqrt(sum((x-y)**2 for x, y in zip(a, b)))

        candidates = [groups[group_id] for group_id in remaining if group_id != base_group_id and groups[group_id].geometry_valid]
        candidates.sort(key=lambda group: (len(neighbors[group.id]), -distance(group), group.id))
        return [group.id for group in candidates]


def is_fastener(group: AssemblyGroup) -> bool:
    return group.part_type in {PartType.BOLT, PartType.NUT}


@dataclass(slots=True)
class TargetFastenerPriorityProvider:
    """Far targets first; related fasteners are scheduled by the search engine."""

    name: str = "target-fastener-v1"

    def rank(self, groups, remaining, base_group_id, contacts):
        base = groups[base_group_id]
        origin = base.centroid or base.bounds.center
        degree = {gid: 0 for gid in remaining}
        for edge in contacts:
            if edge.group_a in remaining and edge.group_b in remaining:
                degree[edge.group_a] += 1
                degree[edge.group_b] += 1

        def key(gid):
            group = groups[gid]
            center = group.centroid or group.bounds.center
            distance2 = sum((a-b)**2 for a, b in zip(center, origin))
            return is_fastener(group), -distance2, degree[gid], gid

        return sorted((gid for gid in remaining if gid != base_group_id
                       and groups[gid].geometry_valid), key=key)

    def related_fasteners(self, target, blockers, ranked, groups, contacts):
        neighbors = set()
        for edge in contacts:
            if edge.group_a == target:
                neighbors.add(edge.group_b)
            elif edge.group_b == target:
                neighbors.add(edge.group_a)
        related = [gid for gid in ranked if is_fastener(groups[gid])
                   and gid in (neighbors | blockers)]
        # Stable sort preserves distance ranking inside each tier.
        return sorted(related, key=lambda gid: gid not in blockers)


@dataclass(slots=True)
class ExteriorPriorityProvider(TargetFastenerPriorityProvider):
    """Cheap bounding-box exposure is a ranking hint, never a collision proof."""

    name: str = "exterior-virtual-fastener-v1"

    @staticmethod
    def direction_score(group, obstacles, direction):
        # Project AABBs onto the direction and an orthogonal screen plane.
        d = tuple(direction)
        seed = (0, 0, 1) if abs(d[2]) < .9 else (0, 1, 0)
        u = (d[1]*seed[2]-d[2]*seed[1], d[2]*seed[0]-d[0]*seed[2], d[0]*seed[1]-d[1]*seed[0])
        length = math.sqrt(sum(v*v for v in u))
        u = tuple(v/length for v in u)
        v = (d[1]*u[2]-d[2]*u[1], d[2]*u[0]-d[0]*u[2], d[0]*u[1]-d[1]*u[0])

        def interval(bounds, axis):
            mid = sum(a*b for a, b in zip(bounds.center, axis))
            radius = sum(abs(a)*b/2 for a, b in zip(axis, bounds.size))
            return mid-radius, mid+radius

        ahead = interval(group.bounds, d)
        screen = [interval(group.bounds, axis) for axis in (u, v)]
        area = max(1e-12, math.prod(b-a for a, b in screen))
        coverage = 0.0
        count = 0
        for obstacle in obstacles:
            if interval(obstacle.bounds, d)[1] <= ahead[0]+1e-7:
                continue
            overlap = math.prod(max(0., min(b, y)-max(a, x)) for (a, b), (x, y)
                                in zip(screen, [interval(obstacle.bounds, axis) for axis in (u, v)]))
            if overlap > 1e-9:
                coverage += overlap/area
                count += 1
        return coverage, count

    def ordered_directions(self, group, obstacles, directions, preferred=()):
        preferred = [tuple(d) for d in preferred]
        return sorted(directions, key=lambda d: (
            preferred.index(tuple(d)) if tuple(d) in preferred else len(preferred),
            *self.direction_score(group, obstacles, d)))

    def rank(self, groups, remaining, base_group_id, contacts):
        axes = ((0, 0, 1), (0, 0, -1), (1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0))
        def key(gid):
            scores = [self.direction_score(groups[gid], [groups[o] for o in sorted(remaining-{gid})], d) for d in axes]
            # Recomputed for every remaining set; fixed base remains an obstacle.
            # Equal exterior exposure favors an uncovered upper face, avoiding
            # removal of a lower supporting layer before an exposed upper one.
            return is_fastener(groups[gid]), min(scores), scores[0], sum(s[0] for s in scores), gid
        return sorted((gid for gid in remaining if gid != base_group_id and groups[gid].geometry_valid), key=key)

