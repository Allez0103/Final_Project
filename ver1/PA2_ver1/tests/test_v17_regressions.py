import math
from types import SimpleNamespace
import pytest
from pa2.rendering.scene import CameraPose,camera_up,interpolate_camera,cross


@pytest.mark.parametrize('direction',[(1,0,0),(-1,0,0),(0,1,0),(0,-1,0),(0,0,1),(0,0,-1)])
def test_full_camera_orientation_has_continuous_roll_and_exact_endpoints(direction):
    a=CameraPose((0,0,-1),'AUTO',(0,1,0)); b=CameraPose(direction,'AUTO',camera_up(direction))
    previous=None
    for i in range(121):
        pose=interpolate_camera(a,b,i/120)
        assert abs(sum(x*y for x,y in zip(pose.view_direction,pose.view_up)))<1e-9
        basis=[cross(pose.view_direction,pose.view_up),pose.view_up,pose.view_direction]
        if previous:
            trace=sum(sum(x*y for x,y in zip(v,w)) for v,w in zip(previous,basis))
            angle=math.degrees(math.acos(max(-1,min(1,(trace-1)/2))))
            assert angle<3
        previous=basis
    assert interpolate_camera(a,b,0).view_direction==pytest.approx(a.view_direction)
    assert pose.view_direction==pytest.approx(b.view_direction)
    assert pose.view_up==pytest.approx(b.view_up)


def test_new_confirmation_clears_old_video_and_export(monkeypatch,tmp_path):
    monkeypatch.setenv('QT_QPA_PLATFORM','offscreen')
    from PySide6.QtWidgets import QApplication
    from pa2.ui.video_page import VideoPage
    app=QApplication.instance() or QApplication([])
    page=VideoPage(); page.rendered(tmp_path/'old.mp4'); page.confirmed('new')
    assert page.player.source().isEmpty() and page.video_path is None
    assert not page.export.isEnabled() and page.generate.isEnabled()
    page.stopped('실패'); assert page.generate.isEnabled()
    page.reset(); page.stopped('불러오기 실패')
    assert not page.generate.isEnabled() and not hasattr(page,'review')
    page.close()


def test_busy_reopen_preserves_project(monkeypatch):
    from pa2.ui.main_window import MainWindow
    window=SimpleNamespace(current_project='A',_busy=lambda:True)
    MainWindow._reopen(window,'B')
    assert window.current_project=='A'
    MainWindow._analyze(window,'B',None,[])
    assert window.current_project=='A'


def test_reopen_does_not_switch_project_before_success():
    from pa2.ui.main_window import MainWindow
    callbacks=[]
    window=SimpleNamespace(current_project='A',_busy=lambda:False,_task=lambda work,done:callbacks.append(done))
    MainWindow._reopen(window,SimpleNamespace(id='B'))
    assert callbacks and window.current_project=='A'


def test_cached_common_uses_position_and_keeps_source_unchanged():
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from pa2.cad.path_check import ConservativePathChecker
    from pa2.cad.sweep import bounds
    shape=BRepPrimAPI_MakeBox(1,1,1).Shape(); events=[]
    checker=ConservativePathChecker(.001,.001,30,activity=events.append)
    original=bounds(shape)
    assert checker._common_volume(shape,shape,(1,0,0),0)==pytest.approx(1)
    assert checker._common_volume(shape,shape,(1,0,0),.5)==pytest.approx(.5)
    count=events.count('BREP_COMMON')
    assert checker._common_volume(shape,shape,(1,0,0),.5)==pytest.approx(.5)
    assert events.count('BREP_COMMON')==count and 'BREP_COMMON_CACHE_HIT' in events
    assert bounds(shape)==original


def test_brep_write_checks_invalid_directory_before_native_call(tmp_path):
    from pa2.cad.brep_io import write_shape
    blocked=tmp_path/'file'; blocked.write_text('occupied',encoding='utf-8')
    with pytest.raises(OSError,match='STORAGE_FAILED'):
        write_shape(None,blocked/'shape.binbrep')


def test_common_cache_hash_collision_cannot_reuse_another_shape(monkeypatch):
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    import pa2.cad.path_check as module
    monkeypatch.setattr(module,'hash',lambda shape:17,raising=False)
    a=BRepPrimAPI_MakeBox(1,1,1).Shape(); b=BRepPrimAPI_MakeBox(2,2,2).Shape()
    checker=module.ConservativePathChecker(.001,.001,30)
    assert checker._common_volume(a,a,(1,0,0),0)==pytest.approx(1)
    assert checker._common_volume(b,b,(1,0,0),0)==pytest.approx(8)
