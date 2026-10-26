from __future__ import annotations

import math
from collections import deque

from pa2.domain.models import AssemblyGroup, ContactEdge, PartType


FEATURE_SCHEMA_VERSION = "features-v1"
PART_TYPES = [item.value for item in PartType]


class FeatureBuilder:
    def __init__(self, initial_groups: list[AssemblyGroup], contacts: list[ContactEdge], base_group_id: str, product_type: str) -> None:
        self.groups = {group.id: group for group in initial_groups}
        self.contacts = contacts
        self.base_group_id = base_group_id
        self.product_type = product_type
        union = initial_groups[0].bounds.union(group.bounds for group in initial_groups)
        self.d = union.diagonal
        self.v = sum(group.volume_mm3 or 0.0 for group in initial_groups)
        self.n = len(initial_groups)
        self.initial_center = union.center

    def rows(self, remaining: set[str]) -> dict[str, dict[str, object]]:
        adjacency = {group_id: set() for group_id in remaining}
        for edge in self.contacts:
            if edge.group_a in remaining and edge.group_b in remaining:
                adjacency[edge.group_a].add(edge.group_b)
                adjacency[edge.group_b].add(edge.group_a)
        hops = self._hops(adjacency)
        remaining_volume = sum(self.groups[group_id].volume_mm3 or 0 for group_id in remaining)
        result: dict[str, dict[str, object]] = {}
        base = self.groups[self.base_group_id]
        for group_id in sorted(remaining - {self.base_group_id}):
            group = self.groups[group_id]
            sizes = sorted(group.bounds.size, reverse=True)
            center = group.centroid or group.bounds.center
            base_center = base.centroid or base.bounds.center
            row: dict[str, object] = {
                "part_type": group.part_type.value,
                "product_type": self.product_type or "UNKNOWN",
                "bbox_x": sizes[0] / self.d if self.d else None,
                "bbox_y": sizes[1] / self.d if self.d else None,
                "bbox_z": sizes[2] / self.d if self.d else None,
                "volume": group.volume_mm3 / self.v if group.volume_mm3 is not None and self.v else None,
                "area": None,
                "center_x": (center[0]-self.initial_center[0]) / self.d if self.d else None,
                "center_y": (center[1]-self.initial_center[1]) / self.d if self.d else None,
                "center_z": (center[2]-self.initial_center[2]) / self.d if self.d else None,
                "aspect_max_mid": sizes[0] / sizes[1] if sizes[1] else None,
                "aspect_mid_min": sizes[1] / sizes[2] if sizes[2] else None,
                "axis_abs_x": None, "axis_abs_y": None, "axis_abs_z": None, "has_axis": 0,
                "planar_area_ratio": None,
                "base_distance": math.dist(center, base_center) / self.d if self.d else None,
                "touches_base": int(self.base_group_id in adjacency[group_id]),
                "base_hops": hops.get(group_id),
                "base_reachable": int(group_id in hops),
                "contact_count": len(adjacency[group_id]),
                "contact_ratio": len(adjacency[group_id]) / max(self.n-1, 1),
                "remaining_ratio": len(remaining) / self.n if self.n else None,
                "removed_ratio": (self.n-len(remaining)) / self.n if self.n else None,
                "remaining_volume_ratio": remaining_volume / self.v if self.v else None,
                "supporter_count": None, "on_table": None, "has_support_path": None,
                "volume_valid": int(group.volume_mm3 is not None),
                "geometry_valid": int(group.geometry_valid),
            }
            for part_type in PART_TYPES:
                row[f"neighbors_{part_type}"] = sum(self.groups[neighbor].part_type.value == part_type for neighbor in adjacency[group_id]) / max(self.n-1, 1)
            result[group_id] = row
        return result

    def _hops(self, adjacency: dict[str, set[str]]) -> dict[str, int]:
        if self.base_group_id not in adjacency:
            return {}
        values = {self.base_group_id: 0}
        queue = deque([self.base_group_id])
        while queue:
            current = queue.popleft()
            for neighbor in adjacency[current]:
                if neighbor not in values:
                    values[neighbor] = values[current] + 1
                    queue.append(neighbor)
        return values

