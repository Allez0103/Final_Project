from __future__ import annotations

import math

from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps
from OCP.GeomAbs import GeomAbs_Cylinder, GeomAbs_Plane
from OCP.TopAbs import TopAbs_FACE
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS, TopoDS_Shape

from pa2.domain.models import Vector3, normalize


GLOBALS: list[Vector3] = [(1,0,0),(-1,0,0),(0,1,0),(0,-1,0),(0,0,1),(0,0,-1)]


def _angle(a: Vector3, b: Vector3) -> float:
    dot = max(-1.0, min(1.0, sum(x*y for x, y in zip(a, b))))
    return math.degrees(math.acos(dot))


def _dedupe(vectors: list[Vector3], tolerance_deg: float, max_count: int) -> list[Vector3]:
    if max_count <= 0:
        return []
    result: list[Vector3] = []
    for vector in vectors:
        value = normalize(vector)
        if all(_angle(value, old) > tolerance_deg for old in result):
            result.append(value)
        if len(result) >= max_count:
            break
    return result


def direction_candidates(shape: TopoDS_Shape, max_directions: int = 24, merge_angle_deg: float = 3.0) -> list[Vector3]:
    evidence: list[tuple[int, float, Vector3]] = []
    explorer = TopExp_Explorer(shape, TopAbs_FACE)
    while explorer.More():
        face = TopoDS.Face(explorer.Current())
        try:
            adaptor = BRepAdaptor_Surface(face, True)
            props = GProp_GProps()
            BRepGProp.SurfaceProperties_s(face, props)
            area = float(props.Mass())
            kind = adaptor.GetType()
            if kind == GeomAbs_Cylinder:
                direction = adaptor.Cylinder().Axis().Direction()
                v = (direction.X(), direction.Y(), direction.Z())
                evidence.extend([(0, -area, v), (0, -area, tuple(-x for x in v))])
            elif kind == GeomAbs_Plane:
                direction = adaptor.Plane().Axis().Direction()
                v = (direction.X(), direction.Y(), direction.Z())
                evidence.extend([(1, -area, v), (1, -area, tuple(-x for x in v))])
        except Exception:
            pass
        explorer.Next()
    evidence.sort(key=lambda item: (item[0], item[1], tuple(round(x, 12) for x in item[2])))
    geometry_limit = max(0, max_directions - 6)
    geometry = _dedupe([value for _, _, value in evidence], merge_angle_deg, geometry_limit)
    return _dedupe(geometry + GLOBALS, merge_angle_deg, max_directions)

