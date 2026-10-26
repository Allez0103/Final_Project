from dataclasses import replace
from pathlib import Path
import pytest
from pa2.video.renderer import VideoRenderer,VideoResult
from pa2.settings.config import AppSettings


def test_hardware_failure_retries_cpu_with_same_deadline(monkeypatch,tmp_path):
    renderer=object.__new__(VideoRenderer); renderer.settings=replace(AppSettings(),video_encoder='h264_nvenc')
    settings=renderer.settings; calls=[]
    def once(*args,**kwargs):
        calls.append((renderer.settings.video_encoder,kwargs['_deadline']))
        if len(calls)==1:
            renderer._last_encoder='h264_nvenc'; raise RuntimeError('ENCODE_FAILED: simulated device failure')
        return VideoResult(tmp_path/'test.mp4','hash',1,30,'libx264/yuv420p')
    monkeypatch.setattr(renderer,'_render_once',once)
    result=renderer.render(None,None,None,tmp_path/'test.mp4')
    assert [c[0] for c in calls]==['h264_nvenc','libx264']
    assert calls[0][1]==calls[1][1]
    assert result.encoder_fallback.startswith('h264_nvenc:')
    assert renderer.settings is settings


def test_render_failure_is_not_misreported_as_encoder_failure(monkeypatch,tmp_path):
    renderer=object.__new__(VideoRenderer); renderer.settings=AppSettings(); renderer._last_encoder='h264_nvenc'
    def failure(*args,**kwargs):raise RuntimeError('Scene failure')
    monkeypatch.setattr(renderer,'_render_once',failure)
    with pytest.raises(RuntimeError,match='Scene failure'):renderer.render(None,None,None,tmp_path/'test.mp4')


def test_cancel_unblocks_a_stalled_encoder_and_removes_temporary_file(monkeypatch,tmp_path):
    import sys,subprocess,threading,time
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from pa2.domain.models import Plan,PlanStep,PlanningStatus,AssemblyGroup,Bounds,PartType
    from pa2.cad.importer import CadScene
    import pa2.video.renderer as module
    group=AssemblyGroup('base','base',['body'],PartType.BODY,Bounds(0,0,0,1,1,1),1,(.5,.5,.5),True)
    from types import SimpleNamespace
    scene=CadScene(Path('test.step'),'hash','test.step','mm',[SimpleNamespace(bounds=group.bounds)],{'body':BRepPrimAPI_MakeBox(1,1,1).Shape()})
    # One stationary base is sufficient: a single 1080p frame fills a stalled pipe.
    plan=Plan('p','project',1,'base',['base'],[],PlanningStatus.COMPLETE)
    original=subprocess.Popen; children=[]
    def stalled(command,**kwargs):
        child=original([sys.executable,'-c','import time; time.sleep(30)'],**kwargs); children.append(child); return child
    monkeypatch.setattr(module,'select_encoder',lambda *a,**kw:('libx264',()))
    monkeypatch.setattr(module.imageio_ffmpeg,'get_ffmpeg_exe',lambda:'ffmpeg')
    monkeypatch.setattr(module.subprocess,'Popen',stalled)
    cancel=threading.Event(); timer=threading.Timer(.5,cancel.set); timer.start(); started=time.monotonic()
    try:
        renderer=VideoRenderer(AppSettings(),Path(__file__).resolve().parents[1]/'assets/video_template_v1.json')
        with pytest.raises(InterruptedError):
            renderer.render(plan,scene,[group],tmp_path/'cancel.mp4',vehicle_name='',product_name='',project_name='',cancel_event=cancel)
        assert time.monotonic()-started<5
        assert all(p.poll() is not None for p in children)
        assert not list(tmp_path.glob('*.mp4'))
    finally:
        timer.cancel()
        for child in children:
            if child.poll() is None:child.kill(); child.wait(timeout=5)
