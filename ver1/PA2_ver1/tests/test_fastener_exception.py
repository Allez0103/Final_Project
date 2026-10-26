from dataclasses import replace

import pytest
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder
from OCP.gp import gp_Pnt

from pa2.cad.path_check import ConservativePathChecker
from pa2.cad.shapes import compound
from pa2.domain.models import AssemblyGroup, Bounds, ContactEdge, GeometryDecision, GeometryStatus, PartType
from pa2.planning.engine import Planner
from pa2.settings.config import AppSettings, SettingsStore


def fixture():
    bolt=AssemblyGroup("bolt","BLT-test",["bolt"],PartType.BOLT,Bounds(-1,-1,0,1,1,3),3*3.141592653589793,(0,0,1.5),True)
    body=AssemblyGroup("body","MBD-test",["body"],PartType.BODY,Bounds(-3,-3,-2,3,3,1),108,(0,0,-.5),True)
    return bolt,body,BRepPrimAPI_MakeCylinder(1,3).Shape(),BRepPrimAPI_MakeBox(gp_Pnt(-3,-3,-2),6,6,3).Shape()


def check(direction=(0,0,1),enabled=True,extra=None,kind=PartType.BOLT):
    bolt,body,moving,obstacle=fixture()
    bolt.part_type=kind
    obstacles=[(body,obstacle)]+(extra or [])
    return ConservativePathChecker(.001,.001,20,bolt_initial_overlap_enabled=enabled).check(
        bolt,moving,obstacles,direction,10,{bolt.id,*[g.id for g,_ in obstacles]})


def test_axial_bolt_withdrawal_allows_only_initial_region():
    result=check()
    assert result.decision==GeometryDecision.PASS
    assert result.reason_code=="FASTENER_INITIAL_OVERLAP_ALLOWED"
    evidence=result.evidence["fastener_exceptions"][0]
    assert evidence["obstacle_id"]=="body"
    assert evidence["initial_overlap_mm3"]==pytest.approx(3.141592653589793)
    assert evidence["moving_volume_percent"]==pytest.approx(100/3)
    assert result.evidence["thread_rotation_checked"] is False


@pytest.mark.parametrize("enabled,kind",[(False,PartType.BOLT),(True,PartType.UNKNOWN),(True,PartType.NUT),(True,PartType.SEAL)])
def test_strict_or_nonbolt_initial_overlap_stays_blocked(enabled,kind):
    result=check(enabled=enabled,kind=kind)
    assert result.decision==GeometryDecision.BLOCKED
    assert result.reason_code=="INITIAL_OVERLAP"


def test_transverse_direction_is_not_exempt_and_axial_direction_can_retry():
    assert check(direction=(1,0,0)).reason_code=="BOLT_NON_AXIAL"
    assert check().decision==GeometryDecision.PASS


def test_inward_axial_motion_still_blocks():
    result=check(direction=(0,0,-1))
    assert result.decision==GeometryDecision.BLOCKED
    assert result.reason_code=="PATH_BLOCKED"


def test_thin_new_obstacle_is_not_exempt():
    thin=AssemblyGroup("thin","thin",["thin"],PartType.BODY,Bounds(-2,-2,5,2,2,5.01),.16,(0,0,5),True)
    result=check(extra=[(thin,BRepPrimAPI_MakeBox(gp_Pnt(-2,-2,5),4,4,.01).Shape())])
    assert result.decision==GeometryDecision.BLOCKED
    assert result.obstacle_ids==["thin"]


def test_new_collision_in_same_mating_part_is_not_exempt():
    bolt,body,moving,obstacle=fixture()
    obstacle=compound([obstacle,BRepPrimAPI_MakeBox(gp_Pnt(-3,-3,5),6,6,.01).Shape()])
    body.bounds=Bounds(-3,-3,-2,3,3,5.01)
    result=ConservativePathChecker(.001,.001,20,bolt_initial_overlap_enabled=True).check(
        bolt,moving,[(body,obstacle)],(0,0,1),10,{"bolt","body"})
    assert result.decision==GeometryDecision.BLOCKED


def test_bolt_without_cylinder_axis_does_not_get_exception():
    bolt,body,_,obstacle=fixture()
    moving=BRepPrimAPI_MakeBox(gp_Pnt(-1,-1,0),2,2,3).Shape()
    result=ConservativePathChecker(.001,.001,20,bolt_initial_overlap_enabled=True).check(
        bolt,moving,[(body,obstacle)],(0,0,1),10,{"bolt","body"})
    assert result.reason_code=="INITIAL_OVERLAP"


def test_failed_relief_boolean_is_unknown(monkeypatch):
    import pa2.cad.path_check as module
    def fail(*args):
        raise RuntimeError("Boolean failure")
    monkeypatch.setattr(module,"BRepAlgoAPI_Cut",fail)
    assert check().decision==GeometryDecision.UNKNOWN


def test_planner_and_worker_record_exception_and_strict_switch(tmp_path):
    bolt,body,moving,obstacle=fixture()
    settings=AppSettings(initial_overlap_region_enabled=False)
    args=("p",1,"s",[body,bolt],[ContactEdge("body","bolt",0)],{"body":obstacle,"bolt":moving},"body")
    from pa2.planning.priority import DefaultPriorityProvider
    result=Planner(settings).generate(*args,priority_provider=DefaultPriorityProvider(),jobs_dir=tmp_path)
    assert result.status.value=="COMPLETE"
    assert result.removal_order==["bolt"]
    assert result.assembly_plan.steps[0].geometry_status==GeometryStatus.FASTENER_EXCEPTION
    assert result.assembly_plan.steps[0].caution_text==''
    assert result.metrics["fastener_exception_steps"]==1
    result.assembly_plan.validate()
    strict=Planner(replace(settings,bolt_initial_overlap_enabled=False)).generate(*args,priority_provider=DefaultPriorityProvider(),jobs_dir=tmp_path)
    assert strict.removal_order==[]
    assert strict.status.value!="COMPLETE"


def test_setting_round_trip_and_legacy_default(tmp_path):
    store=SettingsStore(tmp_path/"settings.json")
    store.save(replace(AppSettings(),bolt_initial_overlap_enabled=False))
    assert store.load().bolt_initial_overlap_enabled is False
    store.path.write_text('{"schema_version":1,"version":"settings-v1"}',encoding="utf-8")
    assert store.load().bolt_initial_overlap_enabled is True
    with pytest.raises(ValueError):
        replace(AppSettings(),bolt_initial_overlap_enabled="false").validate()


def test_support_unknown_creates_review_draft_not_complete(tmp_path):
    bolt,body,moving,obstacle=fixture()
    floating=AssemblyGroup("floating","floating",["floating"],PartType.BLOCK,Bounds(10,0,3,11,1,4),1,(10.5,.5,3.5),True)
    shapes={"body":obstacle,"bolt":moving,"floating":BRepPrimAPI_MakeBox(gp_Pnt(10,0,3),1,1,1).Shape()}
    class BoltFirst:
        name="test"
        def rank(self,groups,remaining,base,contacts):
            return [g for g in ("bolt","floating") if g in remaining]
    args=("p",1,"s",[body,bolt,floating],[ContactEdge("body","bolt",0)],shapes,"body",BoltFirst())
    result=Planner(AppSettings(initial_overlap_region_enabled=False)).generate(*args,jobs_dir=tmp_path)
    assert result.status.value=="REVIEW_REQUIRED"
    assert result.metrics["path_complete"] is True
    assert result.metrics["support_unverified_steps"]==1
    assert result.removal_order==["bolt","floating"]
    step=next(s for s in result.assembly_plan.steps if s.group_id=="bolt")
    assert step.geometry_status==GeometryStatus.SUPPORT_UNVERIFIED
    assert step.caution_text==''
    result.assembly_plan.validate()
    strict=Planner(replace(AppSettings(initial_overlap_region_enabled=False),allow_support_unknown_draft=False)).generate(*args,jobs_dir=tmp_path)
    assert strict.removal_order==[]
    assert strict.status.value!="COMPLETE"


def test_support_draft_policy_does_not_allow_nonbolt_overlap(tmp_path):
    bolt,body,moving,obstacle=fixture()
    bolt.part_type=PartType.SEAL
    result=Planner(AppSettings(initial_overlap_region_enabled=False)).generate("p",1,"s",[body,bolt],[],{"body":obstacle,"bolt":moving},"body",jobs_dir=tmp_path)
    assert result.metrics['unresolved_general_ids']==['bolt']
    assert not result.metrics['path_complete']
    assert result.status.value!="COMPLETE"


def test_exception_and_review_status_survive_draft_storage(tmp_path):
    from pa2.application.plan_service import PlanService
    from pa2.application.project_service import ProjectService
    from pa2.domain.models import Plan,PlanStep,PlanningStatus
    from pa2.storage.database import Database
    from pa2.storage.layout import DataLayout
    db=Database(DataLayout(tmp_path/"data")); db.initialize()
    project=ProjectService(db).create("review","test","test")
    service=PlanService(db)
    plan=Plan("review",project.id,1,"body",["body","bolt"],[PlanStep("bolt",1,(0,0,1),(0,0,-1),10,
        geometry_status=GeometryStatus.SUPPORT_UNVERIFIED,caution_text="지지 미검증 · 체결 예외")],PlanningStatus.REVIEW_REQUIRED)
    service.save_draft(plan)
    restored=service.load_current_draft(project.id)
    assert restored.status==PlanningStatus.REVIEW_REQUIRED
    assert restored.steps[0].geometry_status==GeometryStatus.SUPPORT_UNVERIFIED
    assert restored.steps[0].caution_text==plan.steps[0].caution_text
