"""Conservative face-sweep enclosures; failed geometry is never a clear path.

Analytic cylinder/cone patches are split at projection silhouettes. UV rectangles
cover the trimmed face (possibly more), so hits on these enclosures are UNKNOWN,
not collision proofs. A zero intersection for every patch is a clearance proof.
"""
from __future__ import annotations
import math

from OCP.Bnd import Bnd_Box
from OCP.BRep import BRep_Tool
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepClass3d import BRepClass3d_SolidClassifier
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox,BRepPrimAPI_MakePrism
from OCP.BRepTools import BRepTools
from OCP.GeomAbs import GeomAbs_Cylinder,GeomAbs_Cone
from OCP.TopAbs import TopAbs_SOLID, TopAbs_OUT, TopAbs_IN
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS
from OCP.gp import gp_Pnt,gp_Vec

from pa2.domain.models import Bounds


def bounds(shape):
    box=Bnd_Box(); BRepBndLib.Add_s(shape,box,False)
    a,b=box.CornerMin(),box.CornerMax()
    return Bounds(a.X(),a.Y(),a.Z(),b.X(),b.Y(),b.Z())


def swept_bounds(box,d,travel):
    return Bounds.union([box,box.translated(tuple(v*travel for v in d))])


def valid_prism(face,d,travel,activity=lambda _:None):
    prism=BRepPrimAPI_MakePrism(face,gp_Vec(*(v*travel for v in d)),True,True)
    if not prism.IsDone():return None
    result=prism.Shape()
    if not BRepCheck_Analyzer(result).IsValid():return None
    # Valid BREP can represent the unbounded complement of the intended solid.
    # Normalize only the newly constructed prism, never the input face.
    explorer=TopExp_Explorer(result,TopAbs_SOLID)
    solids=[]
    while explorer.More():
        solids.append(TopoDS.Solid(explorer.Current()))
        explorer.Next()
    if len(solids)!=1:return None
    classifier=BRepClass3d_SolidClassifier(solids[0])
    classifier.PerformInfinitePoint(1e-7)
    if classifier.State()==TopAbs_IN:
        result=result.Reversed()
        solid=TopoDS.Solid(solids[0].Reversed())
    else:
        solid=solids[0]
    classifier=BRepClass3d_SolidClassifier(solid)
    classifier.PerformInfinitePoint(1e-7)
    props=GProp_GProps(); BRepGProp.VolumeProperties_s(result,props)
    volume=props.Mass()
    if classifier.State()!=TopAbs_OUT or not math.isfinite(volume) or volume<=0:
        # Some spline sweeps classify infinity as OUT in BOTH orientations,
        # although their signed volume is negative. Flipping by mass alone
        # does not certify the swept region. Use conservative UV enclosures.
        activity('BREP_SWEEP_ORIENTATION_UNRESOLVED')
        return None
    return result if BRepCheck_Analyzer(result).IsValid() else None


def _u_cuts(adaptor,d,low,high):
    cuts=[low,high]
    analytic=adaptor.GetType() in (GeomAbs_Cylinder,GeomAbs_Cone)
    # Only cylinder/cone U is treated as an angle here. Spline UV scales are
    # arbitrary; subdivide their entire domain by fractions, not radians.
    # Coarse rectangles remain conservative: an intersecting box is UNKNOWN.
    count=max(2,math.ceil((high-low)/(math.pi/2))) if analytic else 4
    cuts.extend(low+(high-low)*i/count for i in range(1,count))
    if adaptor.GetType() in (GeomAbs_Cylinder,GeomAbs_Cone):
        analytic=adaptor.Cylinder() if adaptor.GetType()==GeomAbs_Cylinder else adaptor.Cone()
        axes=analytic.Position(); x,y,z=axes.XDirection(),axes.YDirection(),axes.Direction()
        dot=lambda a:a.X()*d[0]+a.Y()*d[1]+a.Z()*d[2]
        angle=0 if adaptor.GetType()==GeomAbs_Cylinder else analytic.SemiAngle()
        a,b,c=math.cos(angle)*dot(x),math.cos(angle)*dot(y),-math.sin(angle)*dot(z)
        radius=math.hypot(a,b)
        if radius>1e-14 and abs(c)<=radius:
            phase=math.atan2(b,a); delta=math.acos(max(-1,min(1,-c/radius)))
            for root in (phase-delta,phase+delta):
                for k in range(math.floor((low-root)/(2*math.pi)),math.ceil((high-root)/(2*math.pi))+1):
                    value=root+2*math.pi*k
                    if low+1e-10<value<high-1e-10:cuts.append(value)
    return sorted(set(cuts))


def enclosures(face,adaptor,d,travel,activity):
    """Return (bounds, solid, exact) records, or None for construction failure."""
    activity('BREP_SWEEP_FACE')
    original=valid_prism(face,d,travel,activity)
    if original is not None:return [(bounds(original),original,True)]
    activity('BREP_SWEEP_PATCHES')
    u0,u1,v0,v1=BRepTools.UVBounds_s(face)
    if not all(math.isfinite(v) for v in (u0,u1,v0,v1)) or u1<=u0 or v1<=v0:return None
    surface=BRep_Tool.Surface_s(face)
    us=_u_cuts(adaptor,d,u0,u1)
    analytic=adaptor.GetType() in (GeomAbs_Cylinder,GeomAbs_Cone)
    vs=[v0,v1] if analytic else [v0+(v1-v0)*i/4 for i in range(5)]
    if (len(us)-1)*(len(vs)-1)>128:
        activity('BREP_SWEEP_PATCH_LIMIT')
        return None
    records=[]
    for a,b in zip(us,us[1:]):
        for c,e in zip(vs,vs[1:]):
            activity('BREP_SWEEP_PATCH')
            maker=BRepBuilderAPI_MakeFace(surface,a,b,c,e,1e-7)
            if not maker.IsDone():return None
            patch=maker.Face()
            if not BRepCheck_Analyzer(patch).IsValid():return None
            solid=valid_prism(patch,d,travel,activity) if analytic else None
            if solid is None:
                # A box is a conservative fallback for an invalid patch prism,
                # including arbitrary torus/spline silhouette curves.
                box=swept_bounds(bounds(patch),d,travel)
                dx,dy,dz=box.size
                if min(dx,dy,dz)<=0:return None
                solid=BRepPrimAPI_MakeBox(gp_Pnt(box.xmin,box.ymin,box.zmin),dx,dy,dz).Shape()
            records.append((bounds(solid),solid,False))
    return records
