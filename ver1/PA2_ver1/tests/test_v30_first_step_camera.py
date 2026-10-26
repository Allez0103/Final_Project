import copy
from dataclasses import replace
import pytest
from pa2.domain.models import Bounds,Plan,PlanStep,PlanningStatus
from pa2.rendering.scene import (MANUAL_DIRECTIONS,build_timeline,scene_at,camera_pose_angle,
    camera_for_step,projected_model_size)
from pa2.settings.config import AppSettings
from test_mentor_visuals import editor


def make_plan(mode,roll=0):
    steps=[PlanStep('a',1,(0,0,1),(0,0,-1),10,camera_mode=mode,camera_roll_deg=roll),
           PlanStep('b',2,(0,0,1),(0,0,-1),20,camera_mode=mode,camera_roll_deg=roll)]
    return Plan('p','q',1,'base',['base','a','b'],steps,PlanningStatus.COMPLETE)


@pytest.mark.parametrize('mode',['TOP','BOTTOM','FRONT','BACK','LEFT','RIGHT','AUTO'])
@pytest.mark.parametrize('roll',[0,90,180,270])
def test_start_uses_first_view_landscape_and_exactly_matches_first_assembly(mode,roll):
    plan=make_plan(mode,roll);bounds=Bounds(0,0,0,10,40,25);settings=AppSettings()
    before=copy.deepcopy(plan.to_dict());timeline=build_timeline(plan,settings,bounds)
    first=timeline.segments[0]
    assert first.camera_start==first.camera_end==timeline.base_end
    initial=scene_at(plan,0,settings,timeline)
    assert initial.camera.view_direction==(MANUAL_DIRECTIONS.get(mode) or (0,0,-1))
    width,height=projected_model_size(initial.camera,bounds);assert width>=height-1e-8
    for t in (0,timeline.base_end-1e-8,timeline.base_end,timeline.base_end+1e-8,
              first.highlight_end,first.highlight_end+.1,first.move_end-1e-8):
        frame=scene_at(plan,t,settings,timeline)
        assert camera_pose_angle(frame.camera,initial.camera)==pytest.approx(0,abs=1e-6)
        assert frame.translations['base']==(0,0,0)
    assert timeline.step_cameras[0]==timeline.step_cameras[1]
    assert plan.to_dict()==before


def test_first_view_correction_applies_to_matching_auto_only_not_other_directions():
    plan=make_plan('FRONT');plan.steps[1].camera_mode='AUTO';plan.steps[1].assembly_direction=(0,1,0)
    plan.steps.append(PlanStep('c',3,(0,0,1),(0,0,-1),20,camera_mode='TOP'));plan.group_ids.append('c')
    bounds=Bounds(0,0,0,10,20,40);timeline=build_timeline(plan,AppSettings(),bounds)
    assert timeline.first_view_landscape_roll_deg==90
    assert timeline.step_cameras[0].view_up==timeline.step_cameras[1].view_up
    assert timeline.step_cameras[2]==camera_for_step(plan.steps[2],timeline.top_view_roll_deg,plan.camera_rolls)


def test_nonaxis_auto_and_zero_bounds_and_no_moving_parts():
    plan=make_plan('AUTO');plan.steps[0].assembly_direction=(1,2,3)
    bounds=Bounds(0,0,0,10,80,25);settings=AppSettings();timeline=build_timeline(plan,settings,bounds)
    assert timeline.start_camera==timeline.step_cameras[0]
    w,h=projected_model_size(timeline.start_camera,bounds);assert w>=h-1e-8
    # A different AUTO direction is not the same view and must not be corrected.
    assert timeline.step_cameras[1]==camera_for_step(plan.steps[1],timeline.top_view_roll_deg,plan.camera_rolls)
    zero=build_timeline(plan,settings,Bounds(0,0,0,0,0,0));assert zero.first_view_landscape_roll_deg==0
    missing=build_timeline(plan,settings);assert missing.start_camera==camera_for_step(plan.steps[0])
    plan.steps=[];plan.group_ids=['base'];empty=build_timeline(plan,settings,bounds)
    assert empty.start_camera.view_direction==(0,0,-1) and empty.step_cameras==[]
    assert scene_at(plan,0,settings,empty).active_group_id=='base'


def test_reordering_recomputes_initial_view_without_modifying_persistent_rolls():
    plan=make_plan('TOP');plan.camera_rolls={'TOP':90,'FRONT':180};plan.steps[1].camera_mode='FRONT'
    bounds=Bounds(0,0,0,10,40,25);settings=AppSettings()
    assert build_timeline(plan,settings,bounds).start_camera.view_direction==(0,0,-1)
    plan.steps.reverse();plan.validate();before=copy.deepcopy(plan.to_dict())
    timeline=build_timeline(plan,settings,bounds)
    assert timeline.start_camera.view_direction==(0,1,0)
    assert plan.to_dict()==before


def test_first_part_motion_is_stationary_until_highlight_then_continuous():
    plan=make_plan('FRONT');settings=AppSettings();timeline=build_timeline(plan,settings,Bounds(0,0,0,10,20,40))
    segment=timeline.segments[0]
    for t in (segment.camera_start,segment.highlight_end):
        assert scene_at(plan,t,settings,timeline).translations['a']==(0,0,10)
    positions=[scene_at(plan,segment.highlight_end+(segment.move_end-segment.highlight_end)*i/100,
                       settings,timeline).translations['a'][2] for i in range(101)]
    assert positions[0]==10 and positions[-1]==0
    assert all(a>=b for a,b in zip(positions,positions[1:]))
    assert max(abs(a-b) for a,b in zip(positions,positions[1:]))<.16


def test_editor_preview_seek_and_reordered_start_share_exact_pose(editor):
    p=editor;p.camera.setCurrentText('FRONT');p.apply_button.click()
    timeline=p._timeline();p._seek(0)
    camera=p.vtk_scene.renderer.GetActiveCamera()
    before=(camera.GetPosition(),camera.GetFocalPoint(),camera.GetViewUp(),camera.GetViewAngle())
    p.order.setCurrentRow(0);p._preview_step();preview=p._step_preview
    assert preview['timeline'].start_camera==timeline.start_camera
    segment=preview['timeline'].segments[0];preview['time']=segment.highlight_end+.2;p._preview_tick()
    assert (camera.GetPosition(),camera.GetFocalPoint(),camera.GetViewUp(),camera.GetViewAngle())==before
    p._stop_preview()
