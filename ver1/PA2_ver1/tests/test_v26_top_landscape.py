import copy
from dataclasses import replace
from pathlib import Path
import pytest
from pa2.domain.models import Bounds,Plan,PlanStep,PlanningStatus
from pa2.rendering.scene import (landscape_top_roll,camera_for_step,build_timeline,scene_at,cross)
from pa2.settings.config import AppSettings
from test_mentor_visuals import editor


@pytest.mark.parametrize('size,expected',[( (10,40,5),90),((40,10,5),0),((20,20,5),0),((0,0,0),0),((20,20+1e-10,5),0)])
def test_original_xy_bounds_choose_stable_landscape(size,expected):
    bounds=Bounds(100,-200,5,100+size[0],-200+size[1],5+size[2])
    assert landscape_top_roll(bounds)==expected
    step=PlanStep('a',1,(0,0,1),(0,0,-1),10,camera_mode='TOP')
    pose=camera_for_step(step,expected);right=cross(pose.view_direction,pose.view_up)
    w=sum(abs(v)*n for v,n in zip(right,size));h=sum(abs(v)*n for v,n in zip(pose.view_up,size))
    assert w>=h-1e-8
    assert landscape_top_roll(None)==0


@pytest.mark.parametrize('mode',['TOP','AUTO','BOTTOM','FRONT','LEFT','RIGHT','BACK'])
def test_top_only_auto_and_manual_roll_remains_additive(mode):
    step=PlanStep('a',1,(0,0,1),(0,0,-1),10,camera_mode=mode)
    auto=camera_for_step(step,90)
    if mode in ('TOP','AUTO'):
        assert auto.view_up==pytest.approx((-1,0,0))
        for roll in (0,90,180,270):
            assert camera_for_step(replace(step,camera_roll_deg=roll),90).view_up==pytest.approx(
                camera_for_step(replace(step,camera_roll_deg=(roll+90)%360)).view_up)
    else:assert auto==camera_for_step(step)
    if mode=='AUTO':
        assert camera_for_step(replace(step,assembly_direction=(0,0,1)),90)==camera_for_step(replace(step,assembly_direction=(0,0,1)))


def test_timeline_initial_top_transition_and_no_camera_snap():
    bounds=Bounds(0,0,0,10,40,5);settings=AppSettings()
    plan=Plan('p','q',1,'base',['base','a','b','c'],[
        PlanStep(g,i,(0,0,1),(0,0,-1),10,camera_mode=mode)
        for i,(g,mode) in enumerate([('a','TOP'),('b','FRONT'),('c','TOP')],1)],PlanningStatus.COMPLETE)
    before=copy.deepcopy(plan.to_dict());timeline=build_timeline(plan,settings,bounds)
    assert timeline.top_view_roll_deg==90
    assert timeline.segments[0].camera_end==timeline.base_end==settings.highlight_sec
    assert scene_at(plan,0,settings,timeline).camera.view_up==pytest.approx((-1,0,0))
    assert scene_at(plan,timeline.duration,settings,model_bounds=bounds).camera.view_up==pytest.approx((-1,0,0))
    from pa2.rendering.scene import camera_pose_angle
    for segment in timeline.segments[1:]:
        start,end=segment.camera_start,segment.camera_end
        poses=[scene_at(plan,start+(end-start)*i/100,settings,timeline).camera for i in range(101)]
        assert all(camera_pose_angle(a,b)<4 for a,b in zip(poses,poses[1:]))
    assert plan.to_dict()==before


def test_ui_all_preview_seek_paths_share_assembly_bounds(editor,monkeypatch):
    from pa2.cad.importer import CadScene
    # Replace only the size provider to exercise every UI call site; actual
    # tall-shape mesh/export coverage is the separate video test below.
    monkeypatch.setattr(CadScene,'bounds',property(lambda _:Bounds(0,0,0,10,40,5)))
    p=editor;p.camera.setCurrentText('TOP');p._camera_roll_deg=0;p.apply_button.click()
    before=copy.deepcopy(p.plan.to_dict());assert p._timeline().top_view_roll_deg==90
    p._preview_step();timeline=p._step_preview['timeline'];seg=timeline.segments[0]
    p._step_preview['time']=seg.camera_end+.05;p._preview_tick()
    assert p.vtk_scene.renderer.GetActiveCamera().GetViewUp()==pytest.approx((-1,0,0))
    p._stop_preview()
    for step in p.plan.steps:step.camera_mode='TOP';step.camera_roll_deg=0
    p._seek(10000)
    assert p.vtk_scene.renderer.GetActiveCamera().GetViewUp()==pytest.approx((-1,0,0))
    p.preview();assert p.vtk_scene.renderer.GetActiveCamera().GetViewUp()==pytest.approx((-1,0,0))


def test_real_tall_mesh_export_matches_landscape_preview_without_cad_checks(tmp_path,monkeypatch):
    import imageio_ffmpeg,numpy as np
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from pa2.cad.importer import CadScene
    from pa2.domain.models import AssemblyGroup,AtomicBody,PartType
    from pa2.rendering.vtk_scene import VtkScene
    from pa2.video.renderer import VideoRenderer
    from pa2.jobs.isolated import IsolatedCadWorker
    from pa2.cad.path_check import ConservativePathChecker
    def forbidden(*_,**__):pytest.fail('Landscape called collision/path checks')
    monkeypatch.setattr(IsolatedCadWorker,'call',forbidden);monkeypatch.setattr(ConservativePathChecker,'check',forbidden)
    bounds=Bounds(0,0,0,10,40,5)
    body=AtomicBody('body','hash','source.step',0,'/box','box',bounds,2000,1300,bounds.center,True)
    group=AssemblyGroup('base','기준',['body'],PartType.BODY,bounds,2000,bounds.center,True)
    scene=CadScene(Path('synthetic'),'hash','source.step','mm',[body],{'body':BRepPrimAPI_MakeBox(10,40,5).Shape()})
    plan=Plan('p','q',1,'base',['base'],[],PlanningStatus.COMPLETE)
    settings=replace(AppSettings(),final_hold_sec=.2,video_fps=10)
    timeline=build_timeline(plan,settings,scene.bounds);vtk=VtkScene(offscreen=True)
    try:
        vtk.load(scene,[group],.1);vtk.apply(scene_at(plan,0,settings,timeline),800,450)
        camera=vtk.renderer.GetActiveCamera();pose=(camera.GetPosition(),camera.GetFocalPoint(),camera.GetViewAngle(),camera.GetParallelScale())
        rgb=vtk.rgb_array();mask=rgb.min(axis=2)<190;ys,xs=np.nonzero(mask)
        assert xs.max()-xs.min()>2*(ys.max()-ys.min())
        rotated=scene_at(plan,0,settings,timeline)
        from pa2.rendering.scene import CameraPose
        rotated.camera=CameraPose((0,0,-1),'TOP',(0,1,0));vtk.apply(rotated)
        assert pose==(camera.GetPosition(),camera.GetFocalPoint(),camera.GetViewAngle(),camera.GetParallelScale())
    finally:vtk.render_window.Finalize()
    root=Path(__file__).resolve().parents[1]
    result=VideoRenderer(settings,root/'assets/video_template_v1.json').render(plan,scene,[group],tmp_path/'landscape.mp4',
        vehicle_name='test',product_name='test',project_name='자동 가로 정렬')
    frames=imageio_ffmpeg.read_frames(str(result.path));meta=next(frames);rgb=np.frombuffer(next(frames),np.uint8).reshape(1080,1920,3)
    roi=rgb[114:975,30:1445];mask=roi.min(axis=2)<180;ys,xs=np.nonzero(mask)
    assert xs.max()-xs.min()>2*(ys.max()-ys.min())
    frames.close();assert result.frame_count==round((settings.highlight_sec+settings.final_hold_sec)*settings.video_fps)
