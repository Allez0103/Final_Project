from collections import Counter
from dataclasses import replace

import pytest
from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder
from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt

from pa2.cad.native_worker import CadDispatcher
from pa2.cad.shapes import compound
from pa2.domain.models import ContactEdge, PartType
from pa2.planning.engine import Planner
from pa2.planning.fastener_direction import assigned_direction
from pa2.settings.config import AppSettings
from test_target_search import PASS, group
from test_two_stage import HintWorker


def bolt_shape(direction):
    shank = BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(10,20,30),gp_Dir(*direction)),2,16).Shape()
    head = BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(*(a+16*b for a,b in
        zip((10,20,30),direction))),gp_Dir(*direction)),4,3).Shape()
    return compound([shank,head])


@pytest.mark.parametrize('axis',[(0,0,1),(0,0,-1),(1,0,0),(-1,0,0),(0,1,0),(0,-1,0)])
def test_head_side_uses_local_bolt_axis_without_contact_or_path_queries(monkeypatch,axis):
    import pa2.cad.direction_policy as policy
    monkeypatch.setattr(policy,'_boolean',lambda *a,**k:pytest.fail('Unexpected Boolean'))
    counts=Counter(); dispatcher=CadDispatcher({},lambda key:counts.update([key]))
    dispatcher.shapes['bolt']=bolt_shape(axis)
    payload=dict(gid='bolt',neighbors=['unused'],epsilon=.001,gap=.05,
                 fastener=True,fastener_kind='BOLT')
    hint=dispatcher.execute('direction_policy',payload)
    assert hint['head_direction']==pytest.approx(axis)
    assert hint['shaft_length_mm']==pytest.approx(16)
    count=counts.copy()
    assert dispatcher.execute('direction_policy',payload)==hint
    assert count==counts
    assert set(counts)<= {'BREP_FACE_BOUNDS','FASTENER_FACE_PROPERTIES'}


def test_symmetric_nut_and_plain_shank_do_not_invent_head():
    dispatcher=CadDispatcher({},lambda _:None)
    dispatcher.shapes['plain']=BRepPrimAPI_MakeCylinder(2,16).Shape()
    for kind in ('BOLT','NUT'):
        hint=dispatcher.execute('direction_policy',dict(gid='plain',neighbors=[],epsilon=.001,
            gap=.05,fastener=True,fastener_kind=kind))
        assert hint['axis'] and hint['head_direction'] is None


def test_bolt_head_overrides_opposite_target_center_and_assembly_is_inverse():
    class Worker(HintWorker):
        def call(self,op,payload,**kwargs):
            if op=='direction_policy' and payload['fastener']:
                return dict(axis=(0,0,1),head_direction=(0,0,-1),head_center=(0,0,-3))
            return super().call(op,payload,**kwargs)
    worker=Worker(lambda *_:(PASS,[]))
    result=Planner(replace(AppSettings(),support_enabled=False))._generate('p',1,'s',
        [group('base',0),group('bolt',20,PartType.BOLT)],[],{},'base',worker=worker)
    assert not worker.calls
    assert result.metrics['native_path_calls']==0
    step=result.assembly_plan.steps[0]
    assert step.removal_direction==(0,0,-1)
    assert step.assembly_direction==(0,0,1)


def test_nut_moves_away_from_connected_bolt_head_even_when_target_center_opposes():
    nut=replace(group('nut',0,PartType.NUT),centroid=(0,0,-2))
    target=replace(group('target',0),centroid=(0,0,-10))
    bolt=group('bolt',0,PartType.BOLT)
    direction,method,linked=assigned_direction(nut,target,{'axis':(0,0,1)},
        [(bolt,dict(axis=(0,0,1),head_center=(0,0,5)))])
    assert direction==(0,0,-1) and method=='nut_away_from_bolt_head' and linked=='bolt'


def test_nut_fetches_connected_bolt_hint_only_once_and_never_adds_path_calls():
    class Worker(HintWorker):
        def __init__(self):
            super().__init__(lambda *_:(PASS,[])); self.hints=Counter()
        def call(self,op,payload,**kwargs):
            if op=='direction_policy' and payload['fastener']:
                self.hints[payload['gid']]+=1
                return dict(axis=(0,0,1),head_direction=(0,0,1),head_center=(0,0,5))
            return super().call(op,payload,**kwargs)
    worker=Worker()
    result=Planner(replace(AppSettings(),support_enabled=False))._generate('p',1,'s',
        [group('base',0),group('a-nut',10,PartType.NUT),group('z-bolt',20,PartType.BOLT)],
        [ContactEdge('a-nut','z-bolt',0)],{},'base',worker=worker)
    assert worker.hints=={'a-nut':1,'z-bolt':1}
    assert not worker.calls and result.metrics['native_path_calls']==0
    assert len(result.assembly_plan.steps)==2


def test_unrecognized_head_and_missing_axis_fall_back_without_extra_queries():
    bolt=replace(group('bolt',0,PartType.BOLT),centroid=(0,0,-3))
    target=replace(group('base',0),centroid=(0,0,0))
    assert assigned_direction(bolt,target,{'axis':(0,0,1)})[:2]==((0,0,-1),'axis_away_from_target')
    assert assigned_direction(bolt,target,{})[:2]==((0,0,-1),'position_away_fallback')


def test_head_hint_survives_general_search_exhausting_time_budget():
    import time
    class Worker(HintWorker):
        def call(self,op,payload,**kwargs):
            if op=='direction_policy' and payload['fastener']:
                return dict(axis=(0,0,1),head_direction=(0,0,-1))
            return super().call(op,payload,**kwargs)
    def slow_general(*_):
        time.sleep(1.05)
        return PASS,[]
    worker=Worker(slow_general)
    result=Planner(replace(AppSettings(),support_enabled=False,generation_timeout_sec=1))._generate(
        'p',1,'s',[group('base',0),group('target',5),group('bolt',10,PartType.BOLT)],
        [ContactEdge('target','bolt',0)],{},'base',worker=worker)
    bolt=next(s for s in result.assembly_plan.steps if s.group_id=='bolt')
    assert bolt.removal_direction==(0,0,-1)
    assert all(gid!='bolt' for _,gid,_,_ in worker.calls)
