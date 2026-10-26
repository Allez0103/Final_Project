import copy
import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from test_mentor_visuals import editor


def setup_page(p):
    p.plan.steps[0].process_text='bolt process'
    p.plan.steps[1].process_text='cover process'
    p.plan.steps[1].travel_mm=20
    p.set_plan(p.plan,'selection test');p.thumbnail_timer.stop()
    p.resize(1440,960);p.show();QApplication.processEvents()


def click_card(p,row,modifiers=Qt.NoModifier):
    item=p.order.item(row);p.order.scrollToItem(item);QApplication.processEvents()
    QTest.mouseClick(p.order.viewport(),Qt.LeftButton,modifiers,p.order.visualItemRect(item).center())
    QApplication.processEvents()


@pytest.mark.parametrize('row',[0,1])
def test_base_then_card_restores_visible_edit_model_and_bound_fields(editor,row):
    p=editor;setup_page(p);before=copy.deepcopy(p.plan.to_dict())
    p.base_card.click();assert p.base_card.isChecked()
    assert not p.vtk_scene.actors['bolt'].GetVisibility()
    click_card(p,row);gid=('bolt','cover')[row]
    assert {i.data(Qt.UserRole) for i in p.order.selectedItems()}=={gid}
    assert p.vtk_scene.actors[gid].GetVisibility(),'Selected part stayed hidden by base-step playback'
    assert all(a.GetVisibility() for a in p.vtk_scene.actors.values())
    assert p.vtk_scene.actors[gid].GetProperty().GetColor()==pytest.approx((1,0,0))
    assert not p.base_card.isChecked() and p.apply_button.isEnabled()
    assert p.process.toPlainText()==f'{gid} process'
    assert p.distance.value()==(10 if row==0 else 20)
    assert not p.has_pending_fields() and p.plan.to_dict()==before


def test_reclick_same_current_card_after_base_reloads_fields(editor):
    p=editor;setup_page(p);click_card(p,1)
    p.process.setPlainText('unapplied value');assert p.has_pending_fields()
    p.base_card.click();assert p.order.currentRow()==1
    click_card(p,1)
    assert p.process.toPlainText()=='cover process'
    assert not p.has_pending_fields() and p.vtk_scene.actors['cover'].GetVisibility()


def test_base_exit_restores_user_hidden_parts_and_multi_selection(editor):
    p=editor;setup_page(p);p.order.clearSelection();p.vtk_scene.clear_selection()
    p.vtk_scene.actors['base'].SetVisibility(False)
    p.base_card.click();assert p.vtk_scene.actors['base'].GetVisibility()
    click_card(p,0);click_card(p,1,Qt.ControlModifier)
    assert len(p.order.selectedItems())==2
    assert not p.vtk_scene.actors['base'].GetVisibility()
    assert all(p.vtk_scene.actors[g].GetVisibility() for g in ('bolt','cover'))
    assert not p.apply_button.isEnabled() and not p.base_card.isChecked()


def test_base_exit_by_part_list_and_repeated_clicks_never_change_plan(editor,monkeypatch):
    from pa2.cad.path_check import ConservativePathChecker
    from pa2.jobs.isolated import IsolatedCadWorker
    def forbidden(*_,**__):pytest.fail('Selection invoked CAD checks')
    monkeypatch.setattr(IsolatedCadWorker,'call',forbidden);monkeypatch.setattr(ConservativePathChecker,'check',forbidden)
    p=editor;setup_page(p);before=copy.deepcopy(p.plan.to_dict())
    for _ in range(3):
        p.base_card.click()
        target=next(p.parts.item(i) for i in range(p.parts.count()) if p.parts.item(i).data(Qt.UserRole)=='cover')
        p.parts.scrollToItem(target);QApplication.processEvents()
        QTest.mouseClick(p.parts.viewport(),Qt.LeftButton,Qt.NoModifier,p.parts.visualItemRect(target).center())
        assert p.vtk_scene.actors['cover'].GetVisibility()
        assert p.process.toPlainText()=='cover process'
        assert not p.base_card.isChecked()
    assert p.plan.to_dict()==before


@pytest.mark.parametrize('entry',['scrub','play','next'])
def test_leaving_timeline_restores_edit_positions_without_changing_camera(editor,entry):
    p=editor;setup_page(p);p.order.clearSelection();p.vtk_scene.clear_selection()
    before=copy.deepcopy(p.plan.to_dict())
    if entry=='scrub':p._seek(0)
    elif entry=='play':
        p.play_time=0;p._toggle_play();p._play_tick();p.play_timer.stop()
    else:p.base_card.click();p._neighbor(1)
    assert p._timeline_edit_state is not None
    cam=p.vtk_scene.renderer.GetActiveCamera()
    pose=(cam.GetPosition(),cam.GetFocalPoint(),cam.GetViewUp(),cam.GetViewAngle(),cam.GetParallelScale())
    click_card(p,1)
    assert p._timeline_edit_state is None and not p._timeline_focus
    assert all(a.GetVisibility() for a in p.vtk_scene.actors.values())
    assert p.vtk_scene.actors['cover'].GetPosition()==(0,0,0)
    assert pose==(cam.GetPosition(),cam.GetFocalPoint(),cam.GetViewUp(),cam.GetViewAngle(),cam.GetParallelScale())
    assert p.plan.to_dict()==before


def test_same_card_can_start_property_preview_after_base(editor):
    p=editor;setup_page(p);click_card(p,0);p.base_card.click();click_card(p,0)
    assert p.step_preview_button.isEnabled() and not p.has_pending_fields()
    p.step_preview_button.click();assert p._step_preview is not None
    assert p.vtk_scene.actors['bolt'].GetVisibility()
    p._stop_preview()
    assert all(a.GetVisibility() for a in p.vtk_scene.actors.values())
