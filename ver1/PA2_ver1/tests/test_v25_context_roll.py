import copy
import math
from dataclasses import replace
from pathlib import Path
import pytest
from test_mentor_visuals import editor


def test_parts_cards_multi_context_hidden_and_restore(editor):
    from PySide6.QtCore import Qt
    p=editor;s=p.vtk_scene
    p.parts.clearSelection();p.order.clearSelection();s.clear_selection()
    before=copy.deepcopy(p.plan.to_dict());cam=s.renderer.GetActiveCamera()
    pose=(cam.GetPosition(),cam.GetFocalPoint(),cam.GetParallelScale(),cam.GetViewAngle())
    s.actors['base'].SetVisibility(False)
    for source in (p.parts,p.order):
        source.clearSelection()
        for i in range(source.count()):source.item(i).setSelected(source.item(i).data(Qt.UserRole) in {'bolt','cover'})
        assert not s.actors['base'].GetVisibility()
        assert s.actors['base'].GetProperty().GetColor()==pytest.approx((.65,)*3)
        assert s.actors['base'].GetProperty().GetOpacity()==pytest.approx(.10)
        for gid in ('bolt','cover'):
            assert s.actors[gid].GetVisibility()
            assert s.actors[gid].GetProperty().GetColor()==pytest.approx((1,0,0))
            assert s.actors[gid].GetProperty().GetOpacity()==1
        source.clearSelection()
        assert all(a.GetProperty().GetOpacity()==1 for a in s.actors.values())
        assert not s.actors['base'].GetVisibility()
    p._picked('cover');assert s.actors['bolt'].GetProperty().GetOpacity()==pytest.approx(.25)
    p._picked('cover');assert all(a.GetProperty().GetOpacity()==1 for a in s.actors.values())
    assert before==p.plan.to_dict()
    assert pose==(cam.GetPosition(),cam.GetFocalPoint(),cam.GetParallelScale(),cam.GetViewAngle())


def test_roll_buttons_pending_preview_apply_undo_redo(editor):
    from pa2.rendering.scene import camera_for_step,scene_at
    p=editor;p.camera.setCurrentText('TOP')
    original=copy.deepcopy(p.plan.to_dict());direction=p.plan.steps[0].removal_direction
    p.camera_roll_right.click();assert p._camera_roll_deg==90 and p.has_pending_fields()
    assert p.plan.to_dict()==original
    p._preview_step();snapshot=p._step_preview
    step=snapshot['plan'].steps[0];assert step.camera_roll_deg==90
    seg=snapshot['timeline'].segments[0]
    frame=scene_at(snapshot['plan'],seg.camera_end+.01,p.settings,snapshot['timeline'])
    p.vtk_scene.apply(frame)
    assert p.vtk_scene.renderer.GetActiveCamera().GetViewUp()==pytest.approx(camera_for_step(step).view_up)
    p._stop_preview();assert p.plan.to_dict()==original
    p.apply_button.click();assert p.plan.steps[0].camera_roll_deg==90 and not p.has_pending_fields()
    assert p.plan.steps[0].removal_direction==direction
    p._history(False);assert p.plan.steps[0].camera_roll_deg==0
    p._history(True);assert p.plan.steps[0].camera_roll_deg==90
    for _ in range(4):p.camera_roll_left.click()
    assert p._camera_roll_deg==90
    p.order.item(1).setSelected(True)
    assert not p.camera_roll_left.isEnabled() and not p.camera_roll_right.isEnabled()


@pytest.mark.parametrize('mode',['AUTO','TOP','BOTTOM','FRONT','BACK','LEFT','RIGHT'])
def test_roll_geometry_timing_and_smooth_interpolation(mode):
    from pa2.domain.models import Plan,PlanStep,PlanningStatus
    from pa2.rendering.scene import camera_for_step,camera_pose_angle,build_timeline,scene_at
    from pa2.settings.config import AppSettings
    base=PlanStep('a',1,(0,0,1),(0,0,-1),10,camera_mode=mode)
    rolled=replace(base,camera_roll_deg=90)
    a,b=camera_for_step(base),camera_for_step(rolled)
    assert a.view_direction==b.view_direction
    # A world point formerly at screen-top must move to screen-right for ↷.
    from pa2.rendering.scene import cross
    right=cross(b.view_direction,b.view_up)
    assert sum(x*y for x,y in zip(right,a.view_up))==pytest.approx(1)
    assert sum(x*y for x,y in zip(a.view_up,b.view_up))==pytest.approx(0,abs=1e-8)
    assert camera_pose_angle(a,b)==pytest.approx(90)
    plan=Plan('p','q',1,'base',['base','a','b'],[base,replace(rolled,group_id='b',step_index=2)],PlanningStatus.COMPLETE)
    settings=AppSettings();timeline=build_timeline(plan,settings);seg=timeline.segments[1]
    assert seg.camera_end-seg.camera_start==pytest.approx(max(.3,settings.camera_180_sec/2))
    samples=[scene_at(plan,seg.camera_start+(seg.camera_end-seg.camera_start)*i/20,settings,timeline).camera for i in range(21)]
    for u,v in zip(samples,samples[1:]):assert camera_pose_angle(u,v)<10
    assert samples[-1].view_up==pytest.approx(b.view_up)
    for camera_mode in ('smooth','stepped_45'):
        sett=replace(settings,camera_mode=camera_mode)
        end=scene_at(plan,seg.camera_end+.01,sett,timeline)
        assert end.camera.view_up==pytest.approx(b.view_up)


def test_roll_db_confirm_json_legacy_and_signature(tmp_path):
    from pa2.cli import _runtime
    from pa2.application.plan_service import PlanService
    from pa2.domain.models import Plan,PlanStep,PlanningStatus
    layout,db,projects,_=_runtime(tmp_path/'data');project=projects.create('roll','KD1','HVJB');service=PlanService(db)
    plan=Plan('p',project.id,1,'base',['base','a'],[PlanStep('a',1,(0,0,1),(0,0,-1),10)],PlanningStatus.COMPLETE)
    service.save_draft(plan);old=service.confirm(plan)
    assert service.load_current_draft(project.id).steps[0].camera_roll_deg==0
    raw=copy.deepcopy(plan.to_dict());raw['steps'][0].pop('camera_roll_deg')
    assert service._from_dict(raw).steps[0].camera_roll_deg==0
    plan.steps[0].camera_roll_deg=270;service.save_draft(plan)
    assert not service.matches_confirmation(plan,old)
    assert service.load_current_draft(project.id).steps[0].camera_roll_deg==270
    new=service.confirm(plan);assert service.load_confirmation(new).steps[0].camera_roll_deg==270
    assert service.load_confirmation(old).steps[0].camera_roll_deg==0
    assert service.matches_confirmation(service.load_current_draft(project.id),new)
    for value in (-90,45,360,float('nan'),True):
        plan.steps[0].camera_roll_deg=value
        with pytest.raises(ValueError):plan.validate()


def test_compact_template_empty_panels_cache_and_low_resolution(tmp_path):
    import json
    import numpy as np
    from pa2.video.renderer import VideoRenderer
    from pa2.rendering.scene import SceneFrame,CameraPose
    from pa2.settings.config import AppSettings
    root=Path(__file__).resolve().parents[1]
    renderer=VideoRenderer(AppSettings(),root/'assets/video_template_v1.json',root/'assets/thn_logo.png')
    regions=renderer.template['regions'];assert regions['scene'][2]*regions['scene'][3]>.70*.71
    frame=SceneFrame(0,set(),{},None,0,CameraPose((0,0,-1),'TOP'))
    rgb=np.full((80,100,3),255,dtype=np.uint8)
    first=renderer._compose(rgb,frame,'KD1','HVJB','프로젝트',1920,1080)
    assert first.getpixel((40,30))!=(255,255,255)
    assert first.tobytes()==renderer._compose(rgb,frame,'KD1','HVJB','프로젝트',1920,1080).tobytes()
    assert renderer._compose(rgb,frame,'KD1','HVJB','프로젝트',320,180).size==(320,180)
    first.save(tmp_path/'template.png')
