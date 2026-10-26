from dataclasses import replace
import time

import pytest
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
from OCP.gp import gp_Pnt

from test_initial_region_exception import fixture
from pa2.cad.path_check import ConservativePathChecker
from pa2.cad.shapes import compound
from pa2.domain.models import GeometryDecision, GeometryStatus, PartType
from pa2.planning.engine import Planner
from pa2.settings.config import AppSettings, SettingsStore


def checker():
    return ConservativePathChecker(.001,.001,30,initial_overlap_region_enabled=True,initial_overlap_decrease_enabled=True)


@pytest.mark.parametrize('kind',list(PartType))
def test_decreasing_initial_pair_is_review_only_for_all_parts(kind):
    m,o,a,b=fixture(kind)
    result=checker().check(m,a,[(o,b)],(-1,0,0),3,{'moving','other'})
    assert result.decision==GeometryDecision.PASS
    assert result.reason_code=='INITIAL_DECREASE_ALLOWED'
    assert result.evidence['initial_decrease_exceptions']
    assert not result.evidence['initial_region_exceptions']
    detail=result.evidence['pair_diagnostics'][0]
    assert detail['continuous_monotonicity_proven'] is False
    assert detail['continuous_tail_decision']=='PASS'
    assert detail['samples'][-1]['overlap_mm3']<1e-9


def test_increase_is_blocked():
    m,o,a,b=fixture()
    result=checker().check(m,a,[(o,b)],(1,0,0),3,{'moving','other'})
    assert result.decision==GeometryDecision.BLOCKED
    assert result.evidence['pair_diagnostics'][0]['code']=='OVERLAP_REINCREASE'


@pytest.mark.parametrize('volumes',[[.4,.3,.35],[.4,.4000004,.4000008]])
def test_rebound_below_initial_and_cumulative_tolerance_are_blocked(monkeypatch,volumes):
    m,o,a,b=fixture(); c=checker(); values=iter(volumes)
    c.pair_bounds=(m.bounds,o.bounds)
    monkeypatch.setattr(c,'_common_volume',lambda *args:next(values))
    result=c._decreasing_overlap_extraction(a,o.bounds,b,(-1,0,0),3,time.perf_counter(),.5)
    assert result==GeometryDecision.BLOCKED
    assert c.pair_issue['code']=='OVERLAP_REINCREASE'


@pytest.mark.parametrize('same_part',[True,False])
def test_new_obstacle_and_reentry_after_separation_are_blocked(same_part):
    m,o,a,b=fixture()
    thin=BRepPrimAPI_MakeBox(gp_Pnt(-2,0,0),.01,1,1).Shape()
    if same_part:
        obstacles=[(replace(o,bounds=replace(o.bounds,xmin=-2)),compound([b,thin]))]
    else:
        third=replace(o,id='third',body_ids=['third'],bounds=replace(o.bounds,xmin=-2,xmax=-1.99))
        obstacles=[(o,b),(third,thin)]
    result=checker().check(m,a,obstacles,(-1,0,0),3,{m.id}|{g.id for g,_ in obstacles})
    assert result.decision==GeometryDecision.BLOCKED


def test_endpoint_overlap_is_not_accepted():
    m,o,a,b=fixture()
    result=checker().check(m,a,[(o,b)],(-1,0,0),.1,{'moving','other'})
    assert result.decision==GeometryDecision.UNKNOWN
    assert result.evidence['pair_diagnostics'][0]['code']=='ORIGINAL_ENDPOINT_NOT_SEPARATED'


def test_boolean_failure_not_accepted(monkeypatch):
    m,o,a,b=fixture(); c=checker(); c.pair_bounds=(m.bounds,o.bounds)
    monkeypatch.setattr(c,'_common_volume',lambda *args:None)
    assert c._decreasing_overlap_extraction(a,o.bounds,b,(-1,0,0),3,time.perf_counter(),.5)==GeometryDecision.UNKNOWN


def test_uncertain_continuous_tail_is_not_accepted(monkeypatch):
    m,o,a,b=fixture(); c=checker(); c.pair_bounds=(m.bounds,o.bounds)
    monkeypatch.setattr(c,'_common_volume',lambda *args:0.0)
    monkeypatch.setattr(c,'_distance',lambda *args:1.0)
    monkeypatch.setattr(c,'_swept_check',lambda *args:GeometryDecision.UNKNOWN)
    assert c._decreasing_overlap_extraction(a,o.bounds,b,(-1,0,0),3,time.perf_counter(),.5)==GeometryDecision.UNKNOWN
    assert c.pair_bounds==(m.bounds,o.bounds)


def test_sample_and_time_budgets_do_not_produce_pass(monkeypatch):
    m,o,a,b=fixture(); c=checker(); c.pair_bounds=(m.bounds,o.bounds)
    monkeypatch.setattr(c,'_common_volume',lambda *args:.5)
    assert c._decreasing_overlap_extraction(a,o.bounds,b,(-1,0,0),1000,time.perf_counter(),.5)==GeometryDecision.UNKNOWN
    assert c.pair_issue['code']=='DECREASE_SAMPLE_BUDGET'
    assert c._decreasing_overlap_extraction(a,o.bounds,b,(-1,0,0),3,time.perf_counter()-31,.5)==GeometryDecision.UNKNOWN
    assert c.pair_issue['code']=='CANDIDATE_TIME_BUDGET'


def test_initially_clear_pair_cannot_use_volume_decrease_exception():
    m,o,a,_=fixture()
    o=replace(o,bounds=replace(o.bounds,xmin=5,xmax=5.01))
    b=BRepPrimAPI_MakeBox(gp_Pnt(5,0,0),.01,1,1).Shape()
    result=checker().check(m,a,[(o,b)],(1,0,0),10,{'moving','other'})
    assert result.decision==GeometryDecision.BLOCKED
    assert not result.evidence['initial_decrease_exceptions']


def test_default_planner_and_saved_plan_are_review_only(tmp_path):
    m,o,a,b=fixture()
    result=Planner(AppSettings()).generate('p',1,'s',[m,o],[],{'moving':a,'other':b},'other',jobs_dir=tmp_path)
    assert result.status.value=='REVIEW_REQUIRED'
    assert result.metrics['path_complete'] is True
    assert result.metrics['initial_decrease_exception_steps']==1
    step=result.assembly_plan.steps[0]
    assert step.geometry_status==GeometryStatus.INITIAL_DECREASE_EXCEPTION
    assert step.caution_text==''
    result.assembly_plan.validate()
    from pa2.application.plan_service import PlanService
    from pa2.application.project_service import ProjectService
    from pa2.storage.database import Database
    from pa2.storage.layout import DataLayout
    db=Database(DataLayout(tmp_path/'data')); db.initialize()
    project=ProjectService(db).create('decrease','test','test')
    result.assembly_plan.project_id=project.id
    service=PlanService(db); service.save_draft(result.assembly_plan)
    restored=service.load_current_draft(project.id)
    assert restored.steps[0].geometry_status==GeometryStatus.INITIAL_DECREASE_EXCEPTION


def test_policy_is_in_worker_and_pair_cache_key():
    from pa2.cad.native_worker import CadDispatcher
    m,o,a,b=fixture(); dispatcher=CadDispatcher({},lambda _:None)
    dispatcher.shapes={'moving':a,'other':b}
    payload={'moving':m,'obstacles':[o],'direction':(-1,0,0),'travel':3,'remaining':{'moving','other'},
             'epsilon':.001,'min_interval':.001,'timeout':30,'initial_overlap_region_enabled':True}
    assert dispatcher.execute('path',payload).reason_code=='INITIAL_REGION_ALLOWED'
    payload['initial_overlap_decrease_enabled']=True
    assert dispatcher.execute('path',payload).reason_code=='INITIAL_DECREASE_ALLOWED'
    dispatcher.checkers.clear()
    assert dispatcher.execute('path',payload).reason_code=='INITIAL_DECREASE_ALLOWED'
    payload['initial_overlap_region_enabled']=False
    assert dispatcher.execute('path',payload).reason_code=='INITIAL_OVERLAP'


def test_settings_default_migration_roundtrip_and_validation(tmp_path):
    store=SettingsStore(tmp_path/'settings.json')
    store.path.write_text('{}',encoding='utf-8')
    assert store.load().initial_overlap_decrease_enabled is True
    store.save(AppSettings(initial_overlap_decrease_enabled=False))
    assert store.load().initial_overlap_decrease_enabled is False
    with pytest.raises(ValueError):AppSettings(initial_overlap_decrease_enabled='false').validate()
