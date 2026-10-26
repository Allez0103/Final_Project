from dataclasses import replace

import pytest
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
from OCP.gp import gp_Pnt

from pa2.cad.path_check import ConservativePathChecker
from pa2.cad.shapes import compound
from pa2.domain.models import AssemblyGroup, Bounds, GeometryDecision, GeometryStatus, PartType
from pa2.planning.engine import Planner
from pa2.settings.config import AppSettings, SettingsStore


def fixture(kind=PartType.SEAL):
    moving=AssemblyGroup("moving","moving",["moving"],kind,Bounds(0,0,0,1,1,1),1,(.5,.5,.5),True)
    other=AssemblyGroup("other","other",["other"],PartType.UNKNOWN,Bounds(.5,0,0,1.5,1,1),1,(1,.5,.5),True)
    return moving,other,BRepPrimAPI_MakeBox(1,1,1).Shape(),BRepPrimAPI_MakeBox(gp_Pnt(.5,0,0),1,1,1).Shape()


def check(kind=PartType.SEAL,direction=(-1,0,0),travel=3):
    moving,other,a,b=fixture(kind)
    return ConservativePathChecker(.001,.001,20,initial_overlap_region_enabled=True).check(moving,a,[(other,b)],direction,travel,{"moving","other"})


@pytest.mark.parametrize("kind",list(PartType))
def test_every_part_type_gets_fixed_region_exception(kind):
    result=check(kind)
    assert result.decision==GeometryDecision.PASS
    assert result.reason_code=="INITIAL_REGION_ALLOWED"
    assert not result.evidence["fastener_exceptions"]
    assert result.evidence["initial_region_exceptions"][0]["initial_overlap_mm3"]==pytest.approx(.5)


def test_new_volume_in_same_counterpart_is_blocked():
    assert check(direction=(1,0,0)).decision==GeometryDecision.BLOCKED


@pytest.mark.parametrize("same_part",[True,False])
def test_thin_new_interference_is_blocked(same_part):
    moving,other,a,b=fixture()
    thin=BRepPrimAPI_MakeBox(gp_Pnt(-2,0,0),.01,1,1).Shape()
    if same_part:
        b=compound([b,thin]); other.bounds=Bounds(-2,0,0,1.5,1,1)
        obstacles=[(other,b)]
    else:
        third=replace(other,id="third",body_ids=["third"],bounds=Bounds(-2,0,0,-1.99,1,1))
        obstacles=[(other,b),(third,thin)]
    result=ConservativePathChecker(.001,.001,20,initial_overlap_region_enabled=True).check(moving,a,obstacles,(-1,0,0),3,{g.id for g,_ in obstacles}|{"moving"})
    assert result.decision==GeometryDecision.BLOCKED


def test_original_endpoint_still_must_be_separated():
    assert check(travel=.1).decision==GeometryDecision.UNKNOWN


@pytest.mark.parametrize("travel,expected",[(3,GeometryDecision.PASS),(.1,GeometryDecision.UNKNOWN)])
def test_valid_empty_remainder_still_checks_original_endpoint(travel,expected):
    moving,other,a,_=fixture()
    other.bounds=Bounds(.2,.2,.2,.8,.8,.8)
    b=BRepPrimAPI_MakeBox(gp_Pnt(.2,.2,.2),.6,.6,.6).Shape()
    result=ConservativePathChecker(.001,.001,20,initial_overlap_region_enabled=True).check(moving,a,[(other,b)],(-1,0,0),travel,{"moving","other"})
    assert result.decision==expected


def test_boolean_failure_is_not_accepted(monkeypatch):
    import pa2.cad.path_check as module
    def fail(*args):
        raise RuntimeError("failed")
    monkeypatch.setattr(module,"BRepAlgoAPI_Cut",fail)
    assert check().decision==GeometryDecision.UNKNOWN


def test_invalid_group_cannot_receive_exception():
    moving,other,a,b=fixture(); other.geometry_valid=False
    result=ConservativePathChecker(.001,.001,20,initial_overlap_region_enabled=True).check(moving,a,[(other,b)],(-1,0,0),3,{"moving","other"})
    assert result.decision!=GeometryDecision.PASS


def test_default_planner_records_review_even_with_support_pass(tmp_path):
    moving,other,a,b=fixture()
    args=("p",1,"s",[moving,other],[],{"moving":a,"other":b},"other")
    result=Planner(AppSettings(initial_overlap_decrease_enabled=False)).generate(*args,jobs_dir=tmp_path)
    assert result.status.value=="REVIEW_REQUIRED"
    assert result.removal_order==["moving"]
    assert result.metrics["path_complete"] is True
    assert result.metrics["initial_region_exception_steps"]==1
    assert result.metrics["support_unverified_steps"]==0
    step=result.assembly_plan.steps[0]
    assert step.geometry_status==GeometryStatus.INITIAL_REGION_EXCEPTION
    assert step.caution_text==''
    result.assembly_plan.validate()
    from pa2.application.plan_service import PlanService
    from pa2.application.project_service import ProjectService
    from pa2.storage.database import Database
    from pa2.storage.layout import DataLayout
    db=Database(DataLayout(tmp_path/"data")); db.initialize()
    project=ProjectService(db).create("region","test","test")
    result.assembly_plan.project_id=project.id
    service=PlanService(db); service.save_draft(result.assembly_plan)
    restored=service.load_current_draft(project.id)
    assert restored.steps[0].geometry_status==GeometryStatus.INITIAL_REGION_EXCEPTION
    strict=Planner(AppSettings(initial_overlap_region_enabled=False,bolt_initial_overlap_enabled=False)).generate(*args,jobs_dir=tmp_path)
    assert strict.metrics['unresolved_general_ids']==['moving']
    assert not strict.metrics['path_complete']


def test_setting_legacy_default_roundtrip_and_type(tmp_path):
    store=SettingsStore(tmp_path/"settings.json")
    store.path.write_text('{"bolt_initial_overlap_enabled":true}',encoding="utf-8")
    assert store.load().initial_overlap_region_enabled is True
    store.save(AppSettings(initial_overlap_region_enabled=False))
    assert store.load().initial_overlap_region_enabled is False
    with pytest.raises(ValueError):
        AppSettings(initial_overlap_region_enabled="false").validate()


def test_worker_cache_does_not_mix_strict_and_region_policies():
    from pa2.cad.native_worker import CadDispatcher
    moving,other,a,b=fixture()
    dispatcher=CadDispatcher({},lambda _:None)
    dispatcher.shapes={"moving":a,"other":b}
    payload={"moving":moving,"obstacles":[other],"direction":(-1,0,0),"travel":3,
             "remaining":{"moving","other"},"epsilon":.001,"min_interval":.001,"timeout":20,
             "initial_overlap_region_enabled":True}
    assert dispatcher.execute("path",payload).decision==GeometryDecision.PASS
    payload["initial_overlap_region_enabled"]=False
    assert dispatcher.execute("path",payload).reason_code=="INITIAL_OVERLAP"
    payload["initial_overlap_region_enabled"]=True
    assert dispatcher.execute("path",payload).decision==GeometryDecision.PASS


def test_region_and_support_warnings_are_both_preserved(tmp_path):
    moving,other,a,b=fixture()
    floating=AssemblyGroup("floating","floating",["floating"],PartType.BLOCK,Bounds(10,0,3,11,1,4),1,(10.5,.5,3.5),True)
    class MovingFirst:
        name="test"
        def rank(self,groups,remaining,base,contacts):
            return [g for g in ("moving","floating") if g in remaining]
    result=Planner(AppSettings(initial_overlap_decrease_enabled=False)).generate("p",1,"s",[moving,other,floating],[],
        {"moving":a,"other":b,"floating":BRepPrimAPI_MakeBox(gp_Pnt(10,0,3),1,1,1).Shape()},
        "other",MovingFirst(),jobs_dir=tmp_path)
    step=next(s for s in result.assembly_plan.steps if s.group_id=="moving")
    assert step.geometry_status==GeometryStatus.SUPPORT_UNVERIFIED
    assert step.caution_text==''
    assert result.metrics["initial_region_exception_steps"]==1
    assert result.metrics["support_unverified_steps"]==1


def test_pair_cache_survives_checker_eviction_but_not_changed_motion_or_policy(monkeypatch):
    from pa2.cad.native_worker import CadDispatcher
    moving,other,a,b=fixture()
    calls=[]
    original=ConservativePathChecker._check_pair_uncached
    def counted(self,*args,**kwargs):
        calls.append(1)
        return original(self,*args,**kwargs)
    monkeypatch.setattr(ConservativePathChecker,"_check_pair_uncached",counted)
    dispatcher=CadDispatcher({},lambda _:None); dispatcher.shapes={"moving":a,"other":b}
    payload={"moving":moving,"obstacles":[other],"direction":(-1,0,0),"travel":3,
        "remaining":{"moving","other","unrelated"},"epsilon":.001,"min_interval":.001,
        "timeout":20,"initial_overlap_region_enabled":True}
    first=dispatcher.execute("path",payload)
    assert first.decision==GeometryDecision.PASS
    assert first.evidence["calculation_metrics"]["pair_calculations"]==1
    dispatcher.checkers.clear(); payload["remaining"]={"moving","other"}
    second=dispatcher.execute("path",payload)
    assert second.decision==GeometryDecision.PASS
    assert second.evidence["calculation_metrics"]["pair_calculations"]==0
    assert second.evidence["calculation_metrics"]["pair_cache_hits"]==1
    assert not second.evidence["calculation_metrics"]["activity_counts"]
    assert len(calls)==1
    payload["initial_overlap_region_enabled"]=False
    assert dispatcher.execute("path",payload).reason_code=="INITIAL_OVERLAP"
    assert len(calls)==2
    payload["initial_overlap_region_enabled"]=True; payload["direction"]=(1,0,0)
    assert dispatcher.execute("path",payload).decision==GeometryDecision.BLOCKED
    assert len(calls)==3
    payload["direction"]=(-1,0,0); payload["travel"]=.1
    assert dispatcher.execute("path",payload).decision==GeometryDecision.UNKNOWN
    assert len(calls)==4


def test_unknown_pair_cache_does_not_block_after_that_obstacle_is_removed(monkeypatch):
    moving,other,a,b=fixture()
    extra=replace(other,id="extra",body_ids=["extra"],bounds=Bounds(-2,0,0,-1,1,1))
    c=BRepPrimAPI_MakeBox(gp_Pnt(-2,0,0),1,1,1).Shape()
    checker=ConservativePathChecker(.001,.001,20,initial_overlap_region_enabled=True)
    original=checker._check_pair_uncached
    def unknown_for_extra(mb,ms,ob,os,*args,**kwargs):
        if hash(os)==hash(c):
            return GeometryDecision.UNKNOWN
        return original(mb,ms,ob,os,*args,**kwargs)
    monkeypatch.setattr(checker,"_check_pair_uncached",unknown_for_extra)
    assert checker.check(moving,a,[(other,b),(extra,c)],(-1,0,0),3,{"moving","other","extra"}).decision==GeometryDecision.UNKNOWN
    assert checker.check(moving,a,[(other,b)],(-1,0,0),3,{"moving","other"}).decision==GeometryDecision.PASS


def test_timed_out_pair_is_not_cached(monkeypatch):
    import time
    moving,other,a,b=fixture()
    checker=ConservativePathChecker(.001,.001,1,initial_overlap_region_enabled=True)
    monkeypatch.setattr(checker,"_check_pair_uncached",lambda *args:GeometryDecision.UNKNOWN)
    checker._check_pair(moving.bounds,a,other.bounds,b,(-1,0,0),3,time.perf_counter()-2,True)
    assert not checker.pair_results
