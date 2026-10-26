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
    from pa2.domain.models import AssemblyGroup,Bounds,PartType
    from pa2.cad.importer import CadScene
    from pa2.settings.config import AppSettings
    app=QApplication.instance() or QApplication([])
    groups=[AssemblyGroup(gid,gid,[gid],PartType.BLOCK,Bounds(x,0,0,x+1,1,1),1,(x+.5,.5,.5),True)
        for gid,x in [('base',0),('a',2),('b',4),('c',6)]]
    scene=CadScene(Path('synthetic'),'hash','source','mm',[SimpleNamespace(bounds=g.bounds) for g in groups],
        {g.id:BRepPrimAPI_MakeBox(gp_Pnt(g.bounds.xmin,0,0),1,1,1).Shape() for g in groups})
    result=SimpleNamespace(snapshot=SimpleNamespace(groups=groups,contacts=[]),assembly_scene=scene,cache_hits=0,cache_misses=0)
    page=ModelPage();page.set_result(result,AppSettings());page.base.setCurrentIndex(page.base.findData('base'))
    def forbidden(*args,**kwargs):pytest.fail('Selection called CAD validation')
    from pa2.jobs.isolated import IsolatedCadWorker
    from pa2.cad.path_check import ConservativePathChecker
    monkeypatch.setattr(IsolatedCadWorker,'call',forbidden)
    monkeypatch.setattr(ConservativePathChecker,'check',forbidden)
    yield page,result
    page.play_timer.stop();page.thumbnail_timer.stop();page.close();page.vtk_scene.render_window.Finalize()
    if page.vtk_scene._thumbnail_window:page.vtk_scene._thumbnail_window.Finalize()


def select(page,ids):
    from PySide6.QtCore import Qt
    page.parts.blockSignals(True)
    try:
        for i in range(page.parts.count()):page.parts.item(i).setSelected(page.parts.item(i).data(Qt.UserRole) in ids)
    finally:page.parts.blockSignals(False)
    page._select_group()


def visible(page):return {gid for gid,actor in page.vtk_scene.actors.items() if actor.GetVisibility()}


def test_parts_multi_selection_context_and_restore_without_camera_change(editor):
    page,_=editor;camera=page.vtk_scene.renderer.GetActiveCamera()
    pose=(camera.GetPosition(),camera.GetFocalPoint(),camera.GetViewUp(),camera.GetParallelScale(),camera.GetViewAngle())
    select(page,{'a','b'});assert visible(page)=={'base','a','b','c'}
    assert page.vtk_scene.actors['c'].GetProperty().GetOpacity()==pytest.approx(.1)
    assert page.group_button.isEnabled() and page.selection_label.text()=='2개 선택'
    select(page,{'b','c'});assert visible(page)=={'base','a','b','c'}
    select(page,{'b'});assert visible(page)=={'base','a','b','c'}
    select(page,{'a','c'});select(page,set());assert visible(page)=={'base','a','b','c'}
    assert (camera.GetPosition(),camera.GetFocalPoint(),camera.GetViewUp(),camera.GetParallelScale(),camera.GetViewAngle())==pose


def test_previous_manual_visibility_and_show_all_override(editor):
    page,_=editor
    page.vtk_scene.actors['c'].SetVisibility(False)
    select(page,{'a','c'});assert visible(page)=={'base','a','b'}
    select(page,set());assert visible(page)=={'base','a','b'}
    select(page,{'a','b'});page._show_all()
    assert visible(page)=={'base','a','b','c'} and page._part_isolation_snapshot is None
    select(page,set());assert visible(page)=={'base','a','b','c'}
    select(page,{'a','b'});page._hide();assert visible(page)=={'base','c'}
    page._show_all();select(page,{'a','b'});page._solo();select(page,set())
    assert visible(page)=={'a','b'}  # Explicit manual solo remains user-owned.


def test_sequence_cards_do_not_isolate_and_preview_cannot_leave_hidden_actors(editor):
    from pa2.domain.models import Plan,PlanStep,PlanningStatus
    page,result=editor
    plan=Plan('p','proj',1,'base',[g.id for g in result.snapshot.groups],
        [PlanStep(gid,i,(0,0,1),(0,0,-1),10) for i,gid in enumerate(['a','b','c'],1)],PlanningStatus.REVIEW_REQUIRED)
    page.set_plan(plan,'test');before=plan.to_dict()
    page.order.item(0).setSelected(True);page.order.item(2).setSelected(True)
    assert visible(page)=={'base','a','b','c'}
    page.play_timer.start(10000);select(page,{'a','b'})
    assert not page.play_timer.isActive() and visible(page)=={'base','a','b','c'}
    page.order.clearSelection();page.order.item(2).setSelected(True)
    assert visible(page)=={'base','a','b','c'} and page._part_isolation_snapshot is None
    select(page,{'a','b'});page.preview()
    assert visible(page)=={'base','a','b','c'} and page._part_isolation_snapshot is None
    assert plan.to_dict()==before
    select(page,{'a','b'});page.set_result(result,page.settings)
    assert visible(page)=={'base','a','b','c'} and page._part_isolation_snapshot is None


def test_parts_missing_from_sequence_are_not_deselected_by_card_sync(editor):
    from PySide6.QtCore import Qt
    from pa2.domain.models import Plan,PlanStep,PlanningStatus
    page,result=editor
    plan=Plan('partial','proj',1,'base',[g.id for g in result.snapshot.groups],
        [PlanStep('a',1,(0,0,1),(0,0,-1),10)],PlanningStatus.REVIEW_REQUIRED)
    page.set_plan(plan,'partial')
    select(page,{'a','b'})
    assert {i.data(Qt.UserRole) for i in page.parts.selectedItems()}=={'a','b'}
    assert visible(page)=={'base','a','b','c'} and page.group_button.isEnabled()
    select(page,{'base','a','b'})
    assert {i.data(Qt.UserRole) for i in page.parts.selectedItems()}=={'base','a','b'}
    assert visible(page)=={'base','a','b','c'} and not page.group_button.isEnabled()
    assert not page.apply_button.isEnabled()

def test_eye_hides_batch_after_isolation_and_restores_previous_visibility(editor):
    page,_=editor;page.vtk_scene.actors['c'].SetVisibility(False)
    select(page,{'a','b'});assert visible(page)=={'base','a','b'}
    page.visibility_button.click()
    assert visible(page)=={'base'} and page._part_isolation_snapshot is None
    select(page,{'base','c'})
    assert visible(page)=={'base'}  # Changing selection cannot reveal the hidden batch.
    select(page,set());assert page.visibility_button.isEnabled()
    page.visibility_button.click()
    assert visible(page)=={'base','a','b'} and not page.visibility_button.isChecked()
    assert not page.visibility_button.isEnabled()


def test_eye_keeps_partial_plan_selection_and_playback_resets_toggle(editor):
    from pa2.domain.models import Plan,PlanStep,PlanningStatus
    page,result=editor
    plan=Plan('partial-eye','proj',1,'base',[g.id for g in result.snapshot.groups],
        [PlanStep('a',1,(0,0,1),(0,0,-1),10)],PlanningStatus.REVIEW_REQUIRED)
    page.set_plan(plan,'test');before=plan.to_dict()
    select(page,{'a','b'});page.visibility_button.click()
    assert visible(page)=={'base','c'}
    page._toggle_play();assert page.play_timer.isActive()
    assert page._visibility_restore is None and not page.visibility_button.isChecked()
    assert visible(page)=={'base','a','b','c'} and plan.to_dict()==before
    page._toggle_play();select(page,{'a'});page.visibility_button.click()
    page.set_result(result,page.settings)
    assert visible(page)=={'base','a','b','c'} and page._visibility_restore is None
