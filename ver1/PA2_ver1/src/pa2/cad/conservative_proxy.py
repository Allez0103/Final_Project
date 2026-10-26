"""Selective, non-destructive spatial proxies for expensive BREP obstacles.

No mesh, face deletion, volume estimate, or sampled path establishes PASS.
A connected query box is outside a valid bounded solid iff it meets no boundary
and one point is OUT. Conservative face bounds establish the first condition;
OCCT's original-solid classifier establishes the second. Everything unresolved
falls back to the original Boolean/sweep. Cavities and through holes survive.
"""
from __future__ import annotations

import math
import os
import time
from collections import Counter, OrderedDict
from dataclasses import dataclass

from OCP.BRepAdaptor import BRepAdaptor_Surface, BRepAdaptor_Curve
from OCP.BRep import BRep_Tool
from OCP.BRepClass import BRepClass_FaceClassifier
from OCP.BRepTools import BRepTools
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
from OCP.BndLib import BndLib_Add3dCurve
from OCP.Bnd import Bnd_Box
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepClass3d import BRepClass3d_SolidClassifier
from OCP.GeomAbs import GeomAbs_Plane, GeomAbs_Line, GeomAbs_Circle, GeomAbs_Ellipse
from OCP.TopAbs import TopAbs_FACE, TopAbs_SOLID, TopAbs_OUT, TopAbs_EDGE
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS
from OCP.gp import gp_Pnt

from pa2.domain.models import Bounds
from . import sweep


def acceleration_enabled():
    # Diagnostic opt-out only; no GUI/user collision-policy setting is changed.
    return os.environ.get("PA2_CAD_ACCELERATION", "1") != "0"


@dataclass(frozen=True)
class ComplexityPolicy:
    high_faces: int = 1000
    medium_faces: int = 500
    curved_fraction: float = .20

    def eligible(self, count, curved):
        return count >= self.high_faces or (
            count >= self.medium_faces and curved / max(1, count) >= self.curved_fraction)


@dataclass
class _Node:
    bounds: Bounds
    children: tuple = ()
    boxes: tuple = ()

    def intersects(self, query, epsilon=0, activity=lambda _:None):
        if not self.bounds.intersects(query):
            return False
        if self.children:
            return any(child.intersects(query,epsilon,activity) for child in self.children)
        return any(box.intersects(query) if isinstance(box,Bounds) else
                   box.intersects(query,epsilon,activity) for box in self.boxes)


def _tree(boxes):
    getbox=lambda item:item if isinstance(item,Bounds) else item.bounds
    whole = Bounds.union([getbox(b) for b in boxes])
    if len(boxes) <= 8:
        return _Node(whole, boxes=tuple(boxes))
    axis = max(range(3), key=lambda i: whole.size[i])
    ordered = sorted(boxes, key=lambda b: getbox(b).center[axis])
    middle = len(ordered)//2
    return _Node(whole, (_tree(ordered[:middle]), _tree(ordered[middle:])))


class _FaceBoundary:
    """Tighten loose face AABBs without deleting any original boundary."""
    def __init__(self, face):
        self.face=TopoDS.Face(face)
        self.bounds=sweep.bounds(face)
        self.surface=BRepAdaptor_Surface(self.face,True)
        self.refined=None

    def intersects(self,query,epsilon,activity):
        if not self.bounds.intersects(query):return False
        try:
            if self.surface.GetType()==GeomAbs_Plane:
                plane=self.surface.Plane(); normal=plane.Axis().Direction(); origin=plane.Location()
                n=(normal.X(),normal.Y(),normal.Z()); p=(origin.X(),origin.Y(),origin.Z())
                projected=[]
                for x in (query.xmin,query.xmax):
                    for y in (query.ymin,query.ymax):
                        for z in (query.zmin,query.zmax):
                            point=(x,y,z); distance=sum(n[i]*(point[i]-p[i]) for i in range(3))
                            projected.append(tuple(point[i]-distance*n[i] for i in range(3)))
                footprint=Bounds(*(min(v[i] for v in projected) for i in range(3)),
                                 *(max(v[i] for v in projected) for i in range(3))).expanded(epsilon)
                if self.refined is None:
                    activity('PROXY_PLANAR_BOUNDARY_BUILD')
                    boxes=[];edges=TopExp_Explorer(self.face,TopAbs_EDGE)
                    while edges.More():
                        edge=TopoDS.Edge(edges.Current()); curve=BRepAdaptor_Curve(edge)
                        low,high=curve.FirstParameter(),curve.LastParameter()
                        if curve.GetType() in (GeomAbs_Line,GeomAbs_Circle,GeomAbs_Ellipse) and all(math.isfinite(v) for v in (low,high)):
                            cuts=1 if curve.GetType()==GeomAbs_Line else 16
                            for j in range(cuts):
                                box=Bnd_Box()
                                BndLib_Add3dCurve.Add_s(curve,low+(high-low)*j/cuts,low+(high-low)*(j+1)/cuts,
                                                     BRep_Tool.Tolerance_s(edge),box)
                                a,b=box.CornerMin(),box.CornerMax()
                                boxes.append(Bounds(a.X(),a.Y(),a.Z(),b.X(),b.Y(),b.Z()))
                        else:boxes.append(sweep.bounds(edge))
                        edges.Next()
                    if not boxes:return True
                    self.refined=_tree(boxes)
                if self.refined.intersects(footprint):return True
                center=query.center
                distance=sum(n[i]*(center[i]-p[i]) for i in range(3))
                projected_center=tuple(center[i]-distance*n[i] for i in range(3))
                # Connected planar footprint has no trim-boundary crossing.
                # OUT proves a hole/outside; IN/ON/UNKNOWN always fall back.
                classifier=BRepClass_FaceClassifier(self.face,gp_Pnt(*projected_center),epsilon)
                return classifier.State()!=TopAbs_OUT
            if self.refined is None:
                activity('PROXY_CURVED_BOUNDARY_BUILD')
                u0,u1,v0,v1=BRepTools.UVBounds_s(self.face)
                if not all(math.isfinite(v) for v in (u0,u1,v0,v1)) or u1<=u0 or v1<=v0:return True
                surface=BRep_Tool.Surface_s(self.face);boxes=[]
                for i in range(8):
                    for j in range(4):
                        maker=BRepBuilderAPI_MakeFace(surface,u0+(u1-u0)*i/8,u0+(u1-u0)*(i+1)/8,
                                                     v0+(v1-v0)*j/4,v0+(v1-v0)*(j+1)/4,1e-7)
                        if not maker.IsDone() or not BRepCheck_Analyzer(maker.Face()).IsValid():return True
                        boxes.append(sweep.bounds(maker.Face()))
                # Rectangles cover the WHOLE UV domain, including trim holes;
                # their boxes are supersets, not sampled surface approximations.
                self.refined=_tree(boxes)
            return self.refined.intersects(query)
        except InterruptedError:raise
        except Exception:return True


class ProxyStore:
    VERSION = "boundary-bvh-outside-proof-v1"

    def __init__(self, policy=None):
        self.policy = policy or ComplexityPolicy()
        self.entries = {}
        self.stats = Counter()
        self.profiles = []
        self.clear_cache = OrderedDict()

    def _entry(self, shape, activity):
        key = hash(shape)
        if key in self.entries and self.entries[key][0].IsEqual(shape):
            return self.entries[key][1]
        start = time.perf_counter()
        record = None
        count = curved = 0
        try:
            explorer = TopExp_Explorer(shape, TopAbs_FACE)
            while explorer.More():
                count += 1
                if BRepAdaptor_Surface(TopoDS.Face(explorer.Current()), True).GetType() != GeomAbs_Plane:
                    curved += 1
                explorer.Next()
            if self.policy.eligible(count, curved):
                activity("PROXY_BUILD")
                if not BRepCheck_Analyzer(shape, True).IsValid():
                    raise ValueError("invalid original: proxy disabled")
                records = []
                solids = TopExp_Explorer(shape, TopAbs_SOLID)
                covered_faces = 0
                while solids.More():
                    solid = TopoDS.Solid(solids.Current())
                    classifier = BRepClass3d_SolidClassifier(solid)
                    classifier.PerformInfinitePoint(1e-7)
                    if classifier.State() != TopAbs_OUT:
                        raise ValueError("unbounded or unresolved solid")
                    boxes = []
                    faces = TopExp_Explorer(solid, TopAbs_FACE)
                    while faces.More():
                        box = sweep.bounds(faces.Current())
                        if not all(math.isfinite(v) for v in (*box.center, *box.size)):
                            raise ValueError("nonfinite face bounds")
                        boxes.append(_FaceBoundary(faces.Current()))
                        faces.Next()
                    covered_faces += len(boxes)
                    if not boxes:
                        raise ValueError("solid without bounded faces")
                    records.append((sweep.bounds(solid), _tree(boxes), classifier))
                    solids.Next()
                # Reject mixed face/shell/solid shapes: no orphan face is ignored.
                if not records or covered_faces != count:
                    raise ValueError("incomplete solid coverage")
                record = records
                self.stats["built"] += 1
        except InterruptedError:
            raise
        except Exception:
            self.stats["build_fallback"] += 1
        elapsed = time.perf_counter()-start
        self.stats["build_seconds"] += elapsed
        self.profiles.append(dict(shape_key=str(key), faces=count, curved_faces=curved,
                                  eligible=self.policy.eligible(count, curved),
                                  built=record is not None, seconds=elapsed))
        # Retain the original handle as well as the classifier (hash reuse safe).
        self.entries[key] = (shape, record)
        return record

    def certifies_empty(self, shape, query, epsilon, activity=lambda _: None):
        """True means the entire expanded connected box is outside all solids."""
        start = time.perf_counter()
        self.stats["queries"] += 1
        try:
            records = self._entry(shape, activity)
            if records is None:
                self.stats["ineligible_or_invalid"] += 1
                return False
            query = query.expanded(epsilon)
            key = (hash(shape), query, epsilon)
            if key in self.clear_cache:
                self.clear_cache.move_to_end(key)
                self.stats["clear_cache_hits"] += 1
                return True
            for whole, boundary, classifier in records:
                if not whole.intersects(query):
                    continue
                if boundary.intersects(query,epsilon,activity):
                    self.stats["boundary_fallback"] += 1
                    return False
                activity("PROXY_ORIGINAL_CLASSIFY")
                self.stats["classifications"] += 1
                classifier.Perform(gp_Pnt(*query.center), epsilon)
                if classifier.State() != TopAbs_OUT:
                    self.stats["inside_or_unresolved_fallback"] += 1
                    return False
            self.clear_cache[key] = True
            if len(self.clear_cache) > 8192:
                self.clear_cache.popitem(last=False)
            self.stats["certified_empty"] += 1
            return True
        except InterruptedError:
            raise
        except Exception:
            self.stats["query_fallback"] += 1
            return False
        finally:
            self.stats["query_seconds"] += time.perf_counter()-start
