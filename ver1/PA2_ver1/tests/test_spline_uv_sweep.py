"""UV reparameterization must not exhaust a sweep's subdivision budget."""
import pytest
from OCP.Geom import Geom_BSplineSurface
from OCP.collections import Array2_gp_Pnt as TColgp_Array2OfPnt
from OCP.collections import Array1_double as TColStd_Array1OfReal, Array1_int as TColStd_Array1OfInteger
from OCP.gp import gp_Pnt
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
from pa2.cad import sweep
from pa2.cad.path_check import ConservativePathChecker
from pa2.domain.models import AssemblyGroup, PartType, GeometryDecision


def spline_face(u_span):
    poles=TColgp_Array2OfPnt(1,2,1,2)
    for i in (1,2):
        for j in (1,2):poles.SetValue(i,j,gp_Pnt(i-1,j-1,0))
    u=TColStd_Array1OfReal(1,2);v=TColStd_Array1OfReal(1,2)
    u.SetValue(1,0);u.SetValue(2,u_span);v.SetValue(1,0);v.SetValue(2,1)
    mult=TColStd_Array1OfInteger(1,2);mult.SetValue(1,2);mult.SetValue(2,2)
    surface=Geom_BSplineSurface(poles,u,v,mult,mult,1,1)
    return BRepBuilderAPI_MakeFace(surface,0,u_span,0,1,1e-7).Face()


@pytest.mark.parametrize('span',[1,61.25402185732377,1000000])
def test_spline_fallback_covers_same_region_independent_of_uv_scale(monkeypatch,span):
    face=spline_face(span)
    # Exercise the fallback used when a full sweep has ambiguous orientation.
    monkeypatch.setattr(sweep,'valid_prism',lambda *args:None)
    records=sweep.enclosures(face,BRepAdaptor_Surface(face,True),(0,0,1),3,lambda _:None)
    assert records is not None and len(records)==16
    assert all(not exact for _,_,exact in records)
    # Every point on the full unit square's travel must remain enclosed.
    for x in (0,.125,.5,.875,1):
        for y in (0,.125,.5,.875,1):
            for z in (0,1.5,3):
                assert any(b.xmin<=x<=b.xmax and b.ymin<=y<=b.ymax and b.zmin<=z<=b.zmax
                           for b,_,_ in records)


def test_spline_fallback_does_not_certify_thin_intermediate_collision(monkeypatch):
    face=spline_face(61.25402185732377)
    blocker=BRepPrimAPI_MakeBox(gp_Pnt(.2,.2,1.234),.6,.6,.001).Shape()
    monkeypatch.setattr(sweep,'valid_prism',lambda *args:None)
    checker=ConservativePathChecker(.001,.001,30)
    group=lambda name,shape:AssemblyGroup(name,name,[name],PartType.UNKNOWN,sweep.bounds(shape),1,None,True)
    result=checker.check(group('moving',face),face,[(group('blocker',blocker),blocker)],(0,0,1),3,{'moving','blocker'})
    assert result.decision!=GeometryDecision.PASS


def test_negative_mass_with_outside_classifier_uses_conservative_fallback(monkeypatch):
    from OCP.TopAbs import TopAbs_OUT
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    from OCP.gp import gp_Vec
    face=spline_face(61.25402185732377)
    raw=sweep.BRepPrimAPI_MakePrism(face,gp_Vec(0,0,3),True,True).Shape()
    props=GProp_GProps();BRepGProp.VolumeProperties_s(raw,props)
    if props.Mass()>0:raw=raw.Reversed()
    class NegativePrism:
        def IsDone(self):return True
        def Shape(self):return raw
    class AmbiguousClassifier:
        def __init__(self,*args):pass
        def PerformInfinitePoint(self,*args):pass
        def State(self):return TopAbs_OUT
    monkeypatch.setattr(sweep,'BRepClass3d_SolidClassifier',AmbiguousClassifier)
    monkeypatch.setattr(sweep,'BRepPrimAPI_MakePrism',lambda *args:NegativePrism())
    activity=[]
    assert sweep.valid_prism(face,(0,0,1),3,activity.append) is None
    assert 'BREP_SWEEP_ORIENTATION_UNRESOLVED' in activity
    records=sweep.enclosures(face,BRepAdaptor_Surface(face,True),(0,0,1),3,activity.append)
    assert len(records)==16 and all(not exact for _,_,exact in records)
