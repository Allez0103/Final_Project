"""Rotation/translation-invariant *recognition* features, never collision tests.

No tessellation, Boolean, healing, shape transform, or tolerance changes. These
features are additional evidence for otherwise-unmatched bodies, not a proof
that arbitrary solids are congruent. Ambiguous definitions must stay unmatched.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS


@dataclass(frozen=True)
class RotationSignature:
    moments: tuple[float, ...]
    faces: tuple[tuple[str, float], ...]
    edges: tuple[tuple[str, float], ...]


def signature(shape):
    import numpy as np
    props=GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    matrix=props.MatrixOfInertia()
    values=np.linalg.eigvalsh([[matrix.Value(i+1,j+1) for j in range(3)] for i in range(3)])
    moments=tuple(float(v) for v in values)
    profiles=[]
    for kind in (TopAbs_FACE, TopAbs_EDGE):
        rows=[]; explorer=TopExp_Explorer(shape,kind)
        while explorer.More():
            p=GProp_GProps()
            if kind==TopAbs_FACE:
                item=TopoDS.Face(explorer.Current())
                surface=BRepAdaptor_Surface(item,True).GetType().name
                BRepGProp.SurfaceProperties_s(item,p)
            else:
                item=TopoDS.Edge(explorer.Current())
                surface=BRepAdaptor_Curve(item).GetType().name
                BRepGProp.LinearProperties_s(item,p)
            rows.append((surface,abs(float(p.Mass()))))
            explorer.Next()
        profiles.append(tuple(sorted(rows)))
    result=RotationSignature(moments,*profiles)
    numbers=list(moments)+[v for rows in profiles for _,v in rows]
    if not profiles[0] or not all(math.isfinite(v) and v>=0 for v in numbers):
        raise ValueError('회전 매칭용 형상 특징을 계산할 수 없습니다.')
    return result


def equivalent(a, b, relative_tolerance):
    def close(x,y):
        return abs(x-y)<=max(abs(x),abs(y),1.)*relative_tolerance
    if len(a.moments)!=len(b.moments) or not all(close(x,y) for x,y in zip(a.moments,b.moments)):
        return False
    for source,target in ((a.faces,b.faces),(a.edges,b.edges)):
        if len(source)!=len(target):return False
        if any(k!=l or not close(x,y) for (k,x),(l,y) in zip(source,target)):return False
    return True
