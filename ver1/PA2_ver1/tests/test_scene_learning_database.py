from dataclasses import replace

from pa2.application.project_service import ProjectService
from pa2.domain.models import AssemblyGroup, Bounds, MatchingStatus, PartType, Plan, PlanningStatus, PlanStep
from pa2.learning.ranker import LearningService
from pa2.rendering.scene import build_timeline, scene_at
from pa2.settings.config import AppSettings
from pa2.storage.database import Database, RankingCandidate, RankingState, TrainingCase
from pa2.storage.layout import DataLayout


def test_scene_timeline_starts_disassembled_and_finishes_assembled():
    plan = Plan("p","project",1,"base",["base","part"],[PlanStep("part",1,(1,0,0),(-1,0,0),10)],PlanningStatus.COMPLETE)
    settings = AppSettings()
    start = scene_at(plan, 0, settings)
    end = scene_at(plan, build_timeline(plan, settings).duration, settings)
    assert start.visible_group_ids == {"base","part"}
    assert start.translations["part"] == (10,0,0)
    assert end.visible_group_ids == {"base","part"}
    assert end.translations["part"] == (0,0,0)


def test_partial_review_preview_keeps_unplanned_parts_assembled():
    plan=Plan("p","project",1,"base",["base","part","unplanned"],
        [PlanStep("part",1,(1,0,0),(-1,0,0),10)],PlanningStatus.REVIEW_REQUIRED)
    settings=AppSettings()
    for time in (0,build_timeline(plan,settings).duration):
        frame=scene_at(plan,time,settings)
        assert "unplanned" in frame.visible_group_ids
        assert frame.translations["unplanned"]==(0,0,0)


def test_camera_half_turn_is_continuous_and_keeps_part_stationary():
    import math
    plan=Plan('p','project',1,'base',['base','part'],
              [PlanStep('part',1,(0,0,-1),(0,0,1),10)],PlanningStatus.COMPLETE)
    settings=AppSettings()
    start=scene_at(plan,0,settings)
    middle=scene_at(plan,settings.camera_180_sec/2,settings)
    end=scene_at(plan,settings.camera_180_sec,settings)
    assert start.camera.view_direction==(0,0,-1)
    assert end.camera.view_direction==(0,0,1)
    assert abs(middle.camera.view_direction[2]) < 1e-9
    assert math.isclose(sum(x*x for x in middle.camera.view_direction),1)
    assert start.translations['part']==middle.translations['part']==end.translations['part']


def test_learning_thresholds_do_not_create_fake_model():
    ready, reason = LearningService.training_ready(2, 40)
    assert not ready and "학습 보류" in reason
    assert LearningService.training_ready(30, 1000)[0]


def test_project_crud_and_soft_delete(tmp_path):
    database = Database(DataLayout(tmp_path / "data")); database.initialize()
    service = ProjectService(database)
    project = service.create("프로젝트", "KD1", "HVJB")
    assert service.list()[0].id == project.id
    service.update(project.id, "수정")
    assert service.list()[0].name == "수정"
    service.delete(project.id)
    assert service.list() == []


def test_confirmation_capture_builds_teacher_forced_rows(tmp_path):
    database = Database(DataLayout(tmp_path / "data")); database.initialize()
    groups = [
        AssemblyGroup(name, name, [name], PartType.UNKNOWN, Bounds(i*2,0,0,i*2+1,1,1), 1, (i*2+.5,.5,.5), True, MatchingStatus.UNMATCHED)
        for i, name in enumerate(("base","a","b"))
    ]
    plan = Plan("p","project",1,"base",["base","a","b"],[
        PlanStep("b",1,(1,0,0),(-1,0,0),2), PlanStep("a",2,(1,0,0),(-1,0,0),2)
    ],PlanningStatus.COMPLETE)
    case_id = LearningService().capture(database, confirmation_id="c", family_id="family", plan=plan, groups=groups, contacts=[], product_type="HVJB")
    with database.session() as session:
        assert session.get(TrainingCase, case_id) is not None
        states = session.query(RankingState).filter_by(case_id=case_id).all()
        assert len(states) == 1 and states[0].group_size == 2
        rows = session.query(RankingCandidate).filter_by(state_id=states[0].id).all()
        assert sum(row.relevance for row in rows) == 1

