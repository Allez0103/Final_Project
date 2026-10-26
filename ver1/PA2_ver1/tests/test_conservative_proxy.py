from collections import Counter

import pytest
from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder
from OCP.gp import gp_Pnt

from pa2.cad.conservative_proxy import ComplexityPolicy, ProxyStore
from pa2.cad import sweep
from pa2.cad.path_check import ConservativePathChecker
from pa2.cad.shapes import compound
from pa2.domain.models import AssemblyGroup, GeometryDecision, PartType, Bounds


def force_proxy():
    return ProxyStore(ComplexityPolicy(high_faces=0, medium_faces=0))


def box(x,y,z,dx,dy,dz):
    return BRepPrimAPI_MakeBox(gp_Pnt(x,y,z),dx,dy,dz).Shape()


def test_simple_parts_not_simplified():
    store=ProxyStore()
    assert not store.certifies_empty(box(0,0,0,10,10,10),Bounds(20,20,20,21,21,21),.001)
    assert store.profiles[0]['eligible'] is False
    assert store.stats['built']==0


def test_cavity_is_outside_but_material_inside_never_clear():
    outer=box(0,0,0,10,10,10)
    cavity=box(2,2,2,6,6,6)
    hollow=BRepAlgoAPI_Cut(outer,cavity).Shape()
    store=force_proxy()
    assert store.certifies_empty(hollow,Bounds(3,3,3,4,4,4),.001)
    assert not store.certifies_empty(hollow,Bounds(.2,.2,.2,.4,.4,.4),.001)
    assert not store.certifies_empty(hollow,Bounds(1.9,3,3,2.1,4,4),.001)


def test_through_hole_kept_and_thin_crossing_not_lost():
    outer=box(-5,-5,0,10,10,10)
    hole=BRepPrimAPI_MakeCylinder(2,10).Shape()
    ring=BRepAlgoAPI_Cut(outer,hole).Shape()
    store=force_proxy()
    assert store.certifies_empty(ring,Bounds(-.2,-.2,-1,.2,.2,15),.001)
    assert not store.certifies_empty(ring,Bounds(-3,-.1,5,3,.1,5.001),.001)


def test_disconnected_solids_and_endpoint_inside():
    obstacle=compound([box(0,0,0,1,1,1),box(3,0,0,1,1,1)])
    store=force_proxy()
    assert store.certifies_empty(obstacle,Bounds(1.5,.2,.2,2.5,.8,.8),.001)
    assert not store.certifies_empty(obstacle,Bounds(.2,.2,.2,.8,.8,.8),.001)
    assert not store.certifies_empty(obstacle,Bounds(-1,.2,.2,5,.8,.8),.001)


def test_contact_within_original_epsilon_not_pruned():
    obstacle=box(0,0,0,1,1,1)
    store=force_proxy()
    assert not store.certifies_empty(obstacle,Bounds(1.0005,.2,.2,2,.8,.8),.001)


def _group(name,shape):
    return AssemblyGroup(name,name,[name],PartType.UNKNOWN,sweep.bounds(shape),1,None,True)


@pytest.mark.parametrize('direction',[(0,0,1),(1,0,0),(-1,0,0),(0,0,-1)])
def test_path_same_as_original_for_hole_and_wall(direction):
    wall=BRepAlgoAPI_Cut(box(-5,-5,0,10,10,4),BRepPrimAPI_MakeCylinder(2,4).Shape()).Shape()
    moving=BRepPrimAPI_MakeCylinder(.5,1).Shape()
    results=[]
    for enabled in (False,True):
        checker=ConservativePathChecker(.001,.001,30)
        checker.acceleration_enabled=enabled
        checker.proxies=force_proxy()
        result=checker.check(_group('m',moving),moving,[(_group('o',wall),wall)],direction,10,{'m','o'})
        results.append(result.decision)
    assert results[0]==results[1]
    assert results[0] in (GeometryDecision.PASS,GeometryDecision.BLOCKED)


def test_open_shell_proxy_falls_back():
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopAbs import TopAbs_FACE
    source=box(0,0,0,1,1,1)
    face=TopExp_Explorer(source,TopAbs_FACE).Current()
    store=force_proxy()
    assert not store.certifies_empty(face,Bounds(2,2,2,3,3,3),.001)


def test_certified_boxes_have_no_exact_overlap():
    import random
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    from pa2.cad.path_check import _boolean
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
    outer=box(-5,-5,0,10,10,10)
    ring=BRepAlgoAPI_Cut(outer,BRepPrimAPI_MakeCylinder(2,10).Shape()).Shape()
    store=force_proxy();rng=random.Random(20261023);clears=0
    for _ in range(100):
        x,y,z=(rng.uniform(-7,7),rng.uniform(-7,7),rng.uniform(-2,12))
        query=Bounds(x,y,z,x+.25,y+.25,z+.25)
        if store.certifies_empty(ring,query,.001):
            clears+=1
            common=_boolean(BRepAlgoAPI_Common,ring,box(x,y,z,.25,.25,.25))
            assert common.IsDone()
            props=GProp_GProps();BRepGProp.VolumeProperties_s(common.Shape(),props)
            assert abs(props.Mass())<1e-12
    assert clears>20


def test_direction_hint_cache_does_not_change_choice(monkeypatch):
    from pa2.cad.native_worker import CadDispatcher
    from pa2.cad.direction_policy import policy_hint
    dispatcher=CadDispatcher({},lambda _:None)
    dispatcher.shapes={'a':box(0,0,1,1,1,1),'b':box(0,0,0,1,1,1),
                       'c':box(1,0,1,1,1,1)}
    monkeypatch.setenv('PA2_CAD_ACCELERATION','0')
    original=policy_hint(dispatcher,'a',['b','c'],.001,.05)
    monkeypatch.setenv('PA2_CAD_ACCELERATION','1')
    assert policy_hint(dispatcher,'a',['b','c'],.001,.05)==original
    assert policy_hint(dispatcher,'a',['b'],.001,.05)['normal']==original['normal']
    assert policy_hint(dispatcher,'a',['b','c'],.001,.05)==original
