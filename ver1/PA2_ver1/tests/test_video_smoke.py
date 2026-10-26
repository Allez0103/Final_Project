from dataclasses import replace
from pathlib import Path

from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox

from pa2.cad.importer import CadScene
from pa2.domain.models import AssemblyGroup, AtomicBody, Bounds, MatchingStatus, PartType, Plan, PlanningStatus, PlanStep
from pa2.settings.config import AppSettings
from pa2.video.renderer import VideoRenderer


def test_offscreen_mp4_pipeline(tmp_path):
    shape = BRepPrimAPI_MakeBox(10, 10, 10).Shape()
    body = AtomicBody("body", "hash", "assets/hash/source.step", 0, "/box", "box", Bounds(0,0,0,10,10,10), 1000, 600, (5,5,5), True)
    group = AssemblyGroup("base", "기준", ["body"], PartType.BODY, body.bounds, 1000, (5,5,5), True, MatchingStatus.UNMATCHED)
    scene = CadScene(Path("synthetic.step"), "hash", body.source_relative_path, "mm", [body], {"body": shape})
    plan = Plan("plan","project",1,"base",["base"],[],PlanningStatus.COMPLETE)
    settings = replace(AppSettings(), video_width=320, video_height=180, video_fps=10, final_hold_sec=0.2)
    root = Path(__file__).resolve().parents[1]
    result = VideoRenderer(settings, root/"assets/video_template_v1.json", root/"assets/thn_logo.png").render(
        plan, scene, [group], tmp_path/"smoke.mp4", vehicle_name="KD1", product_name="HVJB", project_name="검증"
    )
    assert result.path.exists() and result.path.stat().st_size > 1024
    assert result.frame_count == round((settings.highlight_sec+settings.final_hold_sec)*settings.video_fps)


def test_partial_multi_body_mp4_with_review_text_and_cancel(tmp_path):
    import imageio_ffmpeg
    import threading
    import pytest
    shape = BRepPrimAPI_MakeBox(10, 10, 10).Shape()
    bodies = [AtomicBody(gid, 'hash', 'source.step', i, '/'+gid, gid,
                         Bounds(0,0,0,10,10,10), 1000, 600, (5,5,5), True)
              for i, gid in enumerate(('base','part','unplanned'))]
    groups = [AssemblyGroup(b.id, b.id, [b.id], PartType.BODY, b.bounds, 1000, b.centroid, True)
              for b in bodies]
    scene = CadScene(Path('synthetic.step'), 'hash', 'source.step', 'mm', bodies, {b.id:shape for b in bodies})
    caution = '사용자 입력: 체결 위치를 확인하세요.'
    plan = Plan('p','project',1,'base',[b.id for b in bodies],
                [PlanStep('part',1,(0,0,1),(0,0,-1),10,caution_text=caution)], PlanningStatus.REVIEW_REQUIRED)
    settings = replace(AppSettings(), highlight_sec=.03, assembly_move_sec=.07, final_hold_sec=.03)
    root = Path(__file__).resolve().parents[1]
    renderer = VideoRenderer(settings, root/'assets/video_template_v1.json', root/'assets/thn_logo.png')
    result = renderer.render(plan,scene,groups,tmp_path/'partial.mp4',vehicle_name='KD1',product_name='HVJB',project_name='검증')
    frames = imageio_ffmpeg.read_frames(str(result.path))
    info=next(frames)
    assert info['size']==(1920,1080) and info['fps']==30
    assert sum(1 for _ in frames)==result.frame_count
    assert plan.steps[0].caution_text==caution
    cancelled=threading.Event(); cancelled.set()
    with pytest.raises(InterruptedError):
        renderer.render(plan,scene,groups,tmp_path/'cancelled.mp4',vehicle_name='KD1',product_name='HVJB',project_name='검증',cancel_event=cancelled)
    assert not (tmp_path/'cancelled.mp4').exists()
    assert not list(tmp_path.glob('*.tmp.mp4'))

