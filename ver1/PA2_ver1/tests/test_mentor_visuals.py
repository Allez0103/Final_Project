from pathlib import Path
from types import SimpleNamespace
import pytest


@pytest.fixture
def editor(monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM','offscreen')
    from PySide6.QtWidgets import QApplication
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.gp import gp_Pnt
    from pa2.ui.main_window import ModelPage
    from pa2.domain.models import AssemblyGroup,Bounds,PartType,Plan,PlanStep,PlanningStatus
    from pa2.cad.importer import CadScene
    from pa2.settings.config import AppSettings
    app=QApplication.instance() or QApplication([])
    specs=[('base',PartType.BODY,Bounds(0,0,0,20,20,20)),
           ('bolt',PartType.BOLT,Bounds(20,9,9,21,10,10)),
           ('cover',PartType.COVER,Bounds(0,0,20,20,20,22))]
    groups=[AssemblyGroup(g,g,[g],kind,b,1,b.center,True) for g,kind,b in specs]
    shapes={g.id:BRepPrimAPI_MakeBox(gp_Pnt(g.bounds.xmin,g.bounds.ymin,g.bounds.zmin),*g.bounds.size).Shape() for g in groups}
    scene=CadScene(Path('synthetic'),'hash','source','mm',[SimpleNamespace(bounds=g.bounds) for g in groups],shapes)
    result=SimpleNamespace(snapshot=SimpleNamespace(groups=groups,contacts=[]),assembly_scene=scene,cache_hits=0,cache_misses=0)
    page=ModelPage();page.set_result(result,AppSettings())
    plan=Plan('p','proj',1,'base',[g.id for g in groups],
        [PlanStep(gid,i,(0,0,1),(0,0,-1),10) for i,gid in enumerate(('bolt','cover'),1)],PlanningStatus.REVIEW_REQUIRED)
    page.set_plan(plan,'test');page.thumbnail_timer.stop()
    yield page
    page._stop_preview();page.play_timer.stop();page.thumbnail_timer.stop();page.close()
    page.vtk_scene.render_window.Finalize()
    if page.vtk_scene._thumbnail_window:page.vtk_scene._thumbnail_window.Finalize()


def test_red_faces_gray_context_and_original_color_restore_without_triangle_edges(editor):
    from pa2.rendering.vtk_scene import SELECTION_RED
    scene=editor.vtk_scene;scene.highlight(set())
    original={gid:a.GetProperty().GetColor() for gid,a in scene.actors.items()}
    scene.highlight({'bolt'})
    assert scene.actors['bolt'].GetProperty().GetColor()==pytest.approx(SELECTION_RED)
    assert scene.actors['base'].GetProperty().GetColor()==scene.actors['cover'].GetProperty().GetColor()
    assert all(not actor.GetProperty().GetEdgeVisibility() for actor in scene.actors.values())
    assert scene.actors['base'].GetProperty().GetOpacity()<1
    scene.highlight(set())
    assert {gid:a.GetProperty().GetColor() for gid,a in scene.actors.items()}==original
    assert all(actor.GetProperty().GetOpacity()==1 for actor in scene.actors.values())


def test_internal_selected_part_is_visible_through_silver_context(editor):
    scene=editor.vtk_scene;scene.highlight(set())
    # Put the bolt completely inside the opaque housing without changing CAD.
    scene.actors['bolt'].SetPosition(-10,0,0)
    scene.highlight({'bolt'})
    scene.actors['base'].GetProperty().SetOpacity(1)
    scene.actors['cover'].GetProperty().SetOpacity(1)
    scene.fit();pixels=scene.rgb_array().astype('int16')
    red=(pixels[:,:,0]>pixels[:,:,1]+20)&(pixels[:,:,0]>pixels[:,:,2]+20)
    assert red.sum()>5


def test_small_part_pop_is_reversible_and_never_changes_plan_or_geometry(editor):
    scene=editor.vtk_scene;before=editor.plan.to_dict();bounds=scene.group_bounds.copy()
    scene.highlight(set());origin=scene.actors['bolt'].GetPosition()
    for _ in range(12):
        scene.highlight({'bolt'});position=scene.actors['bolt'].GetPosition()
        distance=sum((a-b)**2 for a,b in zip(origin,position))**.5
        assert 0<distance<=bounds['bolt'].diagonal*.18+1e-9
        assert len(scene._selection_guides)==1 and not scene._selection_guides[0].GetPickable()
        scene.highlight(set());assert scene.actors['bolt'].GetPosition()==origin
        assert not scene._selection_guides
    assert editor.plan.to_dict()==before and scene.group_bounds==bounds


def test_animation_uses_exact_positions_and_preserves_original_camera_turn_color(editor):
    from pa2.rendering.scene import scene_at
    from pa2.rendering.vtk_scene import SELECTION_RED
    scene=editor.vtk_scene;scene.highlight({'bolt'})
    frame=scene_at(editor.plan,0,editor.settings);assert frame.highlight_alpha==0
    scene.apply(frame)
    assert scene.actors['bolt'].GetPosition()==frame.translations['bolt']
    assert scene.actors['bolt'].GetProperty().GetColor()==pytest.approx(scene.base_colors['bolt'])
    assert all(a.GetProperty().GetOpacity()==1 for a in scene.actors.values())
    assert not scene._selection_positions and not scene._selection_guides


def test_visible_red_overlay_click_selects_internal_part_in_list(editor):
    from PySide6.QtCore import Qt
    scene=editor.vtk_scene;scene.highlight(set());scene.actors['bolt'].SetPosition(-10,0,0)
    scene.highlight({'bolt'});scene.fit()
    point=tuple(a+b for a,b in zip(scene.group_bounds['bolt'].center,scene.actors['bolt'].GetPosition()))
    scene.renderer.SetWorldPoint(*point,1);scene.renderer.WorldToDisplay()
    x,y,_=scene.renderer.GetDisplayPoint();gid=scene.pick_group((round(x),round(y)))
    assert gid=='bolt'
    editor._picked(gid)
    assert editor.order.currentItem().data(Qt.UserRole)=='bolt'


def test_progress_card_tracks_seek_without_mutating_edit_selection(editor):
    from pa2.rendering.scene import build_timeline,scene_at
    from PySide6.QtCore import Qt
    before=editor.plan.to_dict();timeline=build_timeline(editor.plan,editor.settings)
    selected={item.data(Qt.UserRole) for item in editor.order.selectedItems()}
    current=editor.order.currentItem().data(Qt.UserRole)
    for segment in timeline.segments:
        value=round((segment.camera_start+.15)/timeline.duration*10000)
        editor._seek(value);frame=scene_at(editor.plan,editor.play_time,editor.settings)
        assert editor.order.active_step_id==frame.active_group_id
        assert {item.data(Qt.UserRole) for item in editor.order.selectedItems()}==selected
        assert editor.order.currentItem().data(Qt.UserRole)==current
    editor._seek(10000);assert editor.order.active_step_id is None
    assert editor.plan.to_dict()==before


def test_step_preview_tracks_card_and_repeated_stops_do_not_drift_small_part(editor):
    before=editor.plan.to_dict();origin=editor.vtk_scene.actors['bolt'].GetPosition()
    for _ in range(4):
        editor._preview_step();assert editor.order.active_step_id=='bolt'
        editor._preview_tick();assert editor.order.active_step_id=='bolt'
        editor._stop_preview();assert editor.order.active_step_id is None
        assert editor.vtk_scene.actors['bolt'].GetPosition()==pytest.approx(origin)
    assert editor.plan.to_dict()==before


def test_progress_marker_is_painted_red_and_editing_pauses_playback(editor):
    from PySide6.QtWidgets import QApplication
    editor.order.show();QApplication.processEvents();editor._seek(0)
    image=editor.order.viewport().grab().toImage()
    assert any(image.pixelColor(x,y).red()>180 and image.pixelColor(x,y).green()<100
               for y in range(image.height()) for x in range(image.width()))
    editor._toggle_play();assert editor.play_timer.isActive()
    editor.order.setCurrentRow(1)
    assert not editor.play_timer.isActive() and editor.order.active_step_id is None
