"""Assign extraction signs using cached geometry and existing contact edges."""
from pa2.cad.directions import GLOBALS
from pa2.domain.models import PartType


def assigned_direction(group, target, hint, connected_bolts=()):
    axis = hint.get('axis')
    if group.part_type == PartType.BOLT and hint.get('head_direction'):
        return tuple(hint['head_direction']), 'bolt_head_axis', None
    center = group.centroid or group.bounds.center
    if group.part_type == PartType.NUT and axis:
        # Only already-connected bolts are eligible; no new connection tests.
        for bolt, bolt_hint in sorted(connected_bolts,
                key=lambda pair:sum((a-b)**2 for a,b in zip(center,
                    pair[0].centroid or pair[0].bounds.center))):
            head = bolt_hint.get('head_center')
            bolt_axis = bolt_hint.get('axis')
            if head is None or not bolt_axis or abs(sum(a*b for a,b in zip(axis,bolt_axis))) < .98:
                continue
            projection = sum(a*(b-c) for a,b,c in zip(axis,center,head))
            if abs(projection) > 1e-6:
                return tuple((1 if projection > 0 else -1)*a for a in axis), 'nut_away_from_bolt_head', bolt.id
    away = tuple(a-b for a,b in zip(center,target.centroid or target.bounds.center))
    candidates = [tuple(axis),tuple(-v for v in axis)] if axis else GLOBALS
    # A tied axial projection uses model +Z, then +Y, then +X deterministically.
    projection = sum(a*b for a,b in zip(candidates[0],away)) if axis else None
    if axis and abs(projection) <= 1e-6:
        direction = max(candidates,key=lambda d:(d[2],d[1],d[0]))
    else:
        direction = max(candidates,key=lambda d:(sum(a*b for a,b in zip(d,away)),d[2],d[1],d[0]))
    return direction, 'axis_away_from_target' if axis else 'position_away_fallback', None
