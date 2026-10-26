from __future__ import annotations

from pa2.domain.models import AssemblyGroup, GeometryDecision


def _xy_overlap(a: AssemblyGroup, b: AssemblyGroup) -> float:
    width = max(0.0, min(a.bounds.xmax, b.bounds.xmax) - max(a.bounds.xmin, b.bounds.xmin))
    height = max(0.0, min(a.bounds.ymax, b.bounds.ymax) - max(a.bounds.ymin, b.bounds.ymin))
    return width * height


def support_check(groups: list[AssemblyGroup], base_group_id: str, gap_mm: float, enabled: bool = True,
                  support_edges: list[tuple[str,str]] | None = None, floor_z: float | None = None) -> tuple[GeometryDecision, dict[str, object]]:
    if not enabled:
        return GeometryDecision.PASS, {"support_check": "disabled"}
    if not groups:
        return GeometryDecision.PASS, {"support_check": "enabled", "supported": []}
    floor_z = min(group.bounds.zmin for group in groups) if floor_z is None else floor_z
    supported = {base_group_id}
    on_table = {group.id for group in groups if abs(group.bounds.zmin - floor_z) <= gap_mm}
    supported.update(on_table)
    changed = True
    while changed:
        changed = False
        for upper in groups:
            if upper.id in supported:
                continue
            for lower in groups:
                if lower.id not in supported:
                    continue
                if support_edges is not None:
                    if (upper.id,lower.id) in support_edges:
                        supported.add(upper.id)
                        changed=True
                        break
                    continue
                vertical_gap = upper.bounds.zmin - lower.bounds.zmax
                if -gap_mm <= vertical_gap <= gap_mm and _xy_overlap(upper, lower) > gap_mm * gap_mm:
                    supported.add(upper.id)
                    changed = True
                    break
    missing = sorted(group.id for group in groups if group.id not in supported)
    if missing:
        return GeometryDecision.UNKNOWN, {"support_check": "enabled", "unsupported": missing, "reason": "geometric-support-path-not-proven"}
    return GeometryDecision.PASS, {"support_check": "enabled", "supported": sorted(supported), "on_table": sorted(on_table)}

