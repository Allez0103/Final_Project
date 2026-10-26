import copy
from types import SimpleNamespace
import pytest

from test_mentor_visuals import editor


def selected(page):
    from PySide6.QtCore import Qt
    return {i.data(Qt.UserRole) for i in page.parts.selectedItems()}


def test_list_single_reclick_clear_sync_restore_and_keep_multi(editor):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    editor.show();QApplication.processEvents()
    page=editor;before=copy.deepcopy(page.plan.to_dict())
    item=page.parts.item(1);page.parts.scrollToItem(item);QApplication.processEvents()
    point=page.parts.visualItemRect(item).center()
    assert selected(page)=={'bolt'}
    QTest.mouseClick(page.parts.viewport(),Qt.LeftButton,Qt.NoModifier,point)
    assert not selected(page) and not page.order.selectedItems()
    assert page.selection_label.text()=='0개 선택' and not page.apply_button.isEnabled()
    assert not page.vtk_scene._selection_positions and not page.vtk_scene._selection_overlay_ids
    assert all(a.GetProperty().GetOpacity()==1 for a in page.vtk_scene.actors.values())
    QTest.mouseClick(page.parts.viewport(),Qt.LeftButton,Qt.NoModifier,point)
    assert selected(page)=={'bolt'}
    cover=page.parts.item(2);point2=page.parts.visualItemRect(cover).center()
    QTest.mouseClick(page.parts.viewport(),Qt.LeftButton,Qt.ControlModifier,point2)
    assert selected(page)=={'bolt','cover'}
    QTest.mouseClick(page.parts.viewport(),Qt.LeftButton,Qt.ControlModifier,point2)
    assert selected(page)=={'bolt'}  # Standard Qt Ctrl toggling is unchanged.
    assert page.plan.to_dict()==before


def test_3d_single_reclick_and_existing_multi_semantics(editor):
    changes=[];editor.edit_state_changed.connect(lambda:changes.append(True))
    editor.parts.clearSelection();editor._picked('bolt')
    assert selected(editor)=={'bolt'}
    before=len(changes)
    editor._picked('bolt');assert selected(editor)==set()
    assert len(changes)>before  # Host can restore video eligibility after clearing pending fields.
    editor._picked('bolt');editor._picked('cover',True)
    assert selected(editor)=={'bolt','cover'}
    editor._picked('bolt',True);assert selected(editor)=={'bolt','cover'}
    editor._picked('bolt');assert selected(editor)=={'bolt'}
    editor._picked('bolt');assert selected(editor)==set()


def test_diagnostic_button_is_not_on_user_screen(editor):
    from PySide6.QtWidgets import QApplication,QPushButton
    editor.show();editor.diagnostics_button.setEnabled(True);QApplication.processEvents()
    assert not editor.diagnostics_button.isVisible()
    assert not any(b.isVisible() and b.text()=='순서 생성 진단' for b in editor.findChildren(QPushButton))
    assert callable(editor.set_planning_diagnostics)


def test_video_transport_rates_and_bounded_five_second_seek(monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM','offscreen')
    from PySide6.QtCore import QUrl
    from PySide6.QtWidgets import QApplication
    from pa2.ui.video_page import VideoPage
    app=QApplication.instance() or QApplication([]);page=VideoPage()
    real_player=page.player
    state={'position':3000,'duration':12000}
    page.player=SimpleNamespace(position=lambda:state['position'],duration=lambda:state['duration'],
        setPosition=lambda n:state.update(position=n),source=lambda:QUrl.fromLocalFile('test.mp4'))
    try:
        page._sync_controls()
        page.previous_button.click();assert state['position']==0
        page.next_button.click();assert state['position']==5000
        page.next_button.click();assert state['position']==10000
        page.next_button.click();assert state['position']==12000
        page.first_button.click();assert state['position']==0
        page.last_button.click();assert state['position']==12000
        assert [page.rate.itemText(i) for i in range(page.rate.count())]==['0.25×','0.5×','1×','1.5×','2×','3×','4×']
        assert page.play.text()=='' and page.play.property('transport')
        assert page.previous_button.accessibleName()=='5초 뒤로'
        assert page.next_button.accessibleName()=='5초 앞으로'
        page._duration(12000);assert page.time_label.text()=='00:12 / 00:12'
    finally:
        page.player=real_player;page.reset();page.close()


def test_timing_settings_labels_persistence_defaults_and_timeline(monkeypatch,tmp_path):
    monkeypatch.setenv('QT_QPA_PLATFORM','offscreen')
    from PySide6.QtWidgets import QApplication
    from pa2.ui.settings_dialog import SettingsDialog
    from pa2.settings.config import AppSettings,SettingsStore
    from pa2.ui.theme import PRIMARY,PRIMARY_HOVER,STYLESHEET
    from pa2.domain.models import Plan,PlanStep,PlanningStatus
    from pa2.rendering.scene import build_timeline
    app=QApplication.instance() or QApplication([])
    settings=AppSettings();store=SettingsStore(tmp_path/'settings.json')
    dialog=SettingsDialog(store,settings)
    try:
        assert settings.assembly_move_sec==.7 and settings.highlight_sec==2
        for key,label in [('assembly_move_sec','부품 이동 시간'),('highlight_sec','이동 전 점멸 시간')]:
            widget=dialog.widgets[key]
            assert widget.parentWidget().layout().labelForField(widget).text()==label
            assert widget.suffix()==' 초'
        dialog.widgets['assembly_move_sec'].setValue(.9);dialog.widgets['highlight_sec'].setValue(1.2)
        dialog._save();saved=store.load()
        assert saved.assembly_move_sec==.9 and saved.highlight_sec==1.2
        dialog._defaults();assert dialog.widgets['assembly_move_sec'].value()==.7
        plan=Plan('p','pr',1,'base',['base','a'],[PlanStep('a',1,(0,0,1),(0,0,-1),10)],PlanningStatus.REVIEW_REQUIRED)
        for timing in [settings,saved]:
            seg=build_timeline(plan,timing).segments[0]
            assert seg.move_end-seg.highlight_end==pytest.approx(timing.assembly_move_sec)
            assert seg.highlight_end-seg.camera_end==pytest.approx(timing.highlight_sec)
        assert PRIMARY=='#2633C5' and PRIMARY_HOVER in STYLESHEET
        with pytest.raises(ValueError):SettingsStore.update(settings,assembly_move_sec=0)
        with pytest.raises(ValueError):SettingsStore.update(settings,highlight_sec=float('nan'))
    finally:dialog.close()
