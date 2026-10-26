import pytest
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox,BRepPrimAPI_MakeCone,BRepPrimAPI_MakeCylinder
from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
from OCP.GeomAbs import GeomAbs_Cylinder
from OCP.gp import gp_Pnt

from pa2.cad.path_check import ConservativePathChecker,_boolean
from pa2.cad import sweep
from pa2.cad.shapes import compound
from pa2.domain.models import AssemblyGroup,Bounds,GeometryDecision,PartType


def group(name,shape):
    return AssemblyGroup(name,name,[name],PartType.UNKNOWN,sweep.bounds(shape),1,None,True)


def check(moving,obstacle,d,checker=None):
    checker=checker or ConservativePathChecker(.001,.001,30,initial_overlap_region_enabled=True)
    return checker.check(group('m',moving),moving,[(group('o',obstacle),obstacle)],d,3,{'m','o'})


def test_cone_can_move_away_from_touching_floor():
    cone=BRepPrimAPI_MakeCone(2,1,2).Shape()
    floor=BRepPrimAPI_MakeBox(gp_Pnt(-3,-3,-1),6,6,1).Shape()
    assert check(cone,floor,(0,0,1)).decision==GeometryDecision.PASS


def test_transverse_cylinder_prism_is_split_for_clear_corner():
    pin=BRepPrimAPI_MakeCylinder(1,1).Shape()
    corner=BRepPrimAPI_MakeBox(gp_Pnt(.8,.8,.2),.1,.1,.1).Shape()
    assert check(pin,corner,(-1,0,0)).decision==GeometryDecision.PASS


def test_transverse_cylinder_thin_collision_is_not_lost():
    pin=BRepPrimAPI_MakeCylinder(1,1).Shape()
    slab=BRepPrimAPI_MakeBox(gp_Pnt(-2,-2,0),.001,4,1).Shape()
    assert check(pin,slab,(-1,0,0)).decision==GeometryDecision.BLOCKED


def test_enclosure_intersection_is_not_misreported_as_actual_collision(monkeypatch):
    pin=BRepPrimAPI_MakeCylinder(1,1).Shape()
    corner=BRepPrimAPI_MakeBox(gp_Pnt(.8,.8,.2),.1,.1,.1).Shape()
    envelope=BRepPrimAPI_MakeBox(gp_Pnt(-2,-2,0),4,4,4).Shape()
    monkeypatch.setattr(sweep,'enclosures',lambda *a:[(sweep.bounds(envelope),envelope,False)])
    result=check(pin,corner,(0,0,1))
    assert result.decision==GeometryDecision.UNKNOWN
    assert result.evidence['pair_diagnostics'][0]['code']=='SWEEP_UNRESOLVED'


def test_irrelevant_curved_face_cannot_make_whole_path_unknown(monkeypatch):
    pin=BRepPrimAPI_MakeCylinder(1,1).Shape()
    block=BRepPrimAPI_MakeBox(gp_Pnt(10,0,0),1,1,1).Shape()
    floor=BRepPrimAPI_MakeBox(gp_Pnt(9,-1,-1),3,3,1).Shape()
    original=sweep.enclosures
    def fail_if_cylinder(face,adaptor,*args):
        assert adaptor.GetType()!=GeomAbs_Cylinder
        return original(face,adaptor,*args)
    monkeypatch.setattr(sweep,'enclosures',fail_if_cylinder)
    assert check(compound([pin,block]),floor,(0,0,1)).decision==GeometryDecision.PASS


def test_invalid_input_has_specific_reason_not_clear_path(monkeypatch):
    moving=BRepPrimAPI_MakeBox(1,1,1).Shape()
    other=BRepPrimAPI_MakeBox(gp_Pnt(.5,0,0),1,1,1).Shape()
    checker=ConservativePathChecker(.001,.001,30,initial_overlap_region_enabled=True)
    import pa2.cad.path_check as module
    original=module.prepare
    monkeypatch.setattr(module,'prepare',lambda s,*args:(s,{'code':'INPUT_GEOMETRY_INVALID'},False) if hash(s)==hash(moving) else original(s,*args))
    result=check(moving,other,(-1,0,0),checker)
    assert result.decision==GeometryDecision.UNKNOWN
    assert result.evidence['pair_diagnostics'][0]['code']=='INPUT_GEOMETRY_INVALID'


def test_boolean_uses_non_destructive_mode():
    a=BRepPrimAPI_MakeBox(1,1,1).Shape()
    b=BRepPrimAPI_MakeBox(gp_Pnt(.5,0,0),1,1,1).Shape()
    operation=_boolean(BRepAlgoAPI_Common,a,b)
    assert operation.IsDone() and operation.NonDestructive()


def test_continuous_distance_can_resolve_an_overlarge_sweep_enclosure(monkeypatch):
    pin=BRepPrimAPI_MakeCylinder(1,1).Shape()
    corner=BRepPrimAPI_MakeBox(gp_Pnt(2,-.8,.2),.1,.1,.1).Shape()
    envelope=BRepPrimAPI_MakeBox(gp_Pnt(-5,-5,0),10,10,4).Shape()
    monkeypatch.setattr(sweep,'enclosures',lambda *a:[(sweep.bounds(envelope),envelope,False)])
    result=check(pin,corner,(1,1,0))
    assert result.decision==GeometryDecision.PASS
    assert result.evidence['pair_diagnostics'][0]['code']=='CONTINUOUS_DISTANCE_PROOF'


def test_expired_distance_proof_is_unknown():
    import time
    checker=ConservativePathChecker(.001,.001,30)
    pin=BRepPrimAPI_MakeCylinder(1,1).Shape()
    assert checker._certify_interval(pin,pin,(1,0,0),0,3,time.perf_counter(),deadline=0)==GeometryDecision.UNKNOWN
