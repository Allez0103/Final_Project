import os
from types import SimpleNamespace
from pathlib import Path
import json


def test_editor_group_move_undo_direction_and_real_thumbnails(monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM','offscreen')
    from PySide6.QtWidgets import QApplication
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from pa2.ui.main_window import ModelPage
    from pa2.settings.config import AppSettings
    from pa2.domain.models import AssemblyGroup,Bounds,PartType,Plan,PlanStep,PlanningStatus
    from pa2.cad.importer import CadScene
    app=QApplication.instance() or QApplication([])
    groups=[AssemblyGroup(g,g,[g],PartType.BLOCK,Bounds(x,0,0,x+1,1,1),1,(x+.5,.5,.5),True)
            for g,x in [('base',0),('a',2),('b',4),('c',6)]]
    scene=CadScene(Path('test'),'hash','source','mm',[SimpleNamespace(bounds=g.bounds) for g in groups],
                   {g.id:BRepPrimAPI_MakeBox(1,1,1).Shape() for g in groups})
    result=SimpleNamespace(snapshot=SimpleNamespace(groups=groups,contacts=[]),assembly_scene=scene,cache_hits=0,cache_misses=0)
    page=ModelPage()
    try:
        page.set_result(result,AppSettings())
        plan=Plan('p','proj',1,'base',[g.id for g in groups],
                  [PlanStep(g.id,i,(0,0,1),(0,0,-1),10+i) for i,g in enumerate(groups[1:],1)],PlanningStatus.REVIEW_REQUIRED)
        page.set_plan(plan,'test')
        assert page.distance.value()==11
        page.order.item(0).setSelected(True); page.order.item(2).setSelected(True); page.order.move_selection(1)
        assert [s.group_id for s in plan.steps]==['b','a','c']
        assert len(page.order.selectedItems())==2
        page._history(False); assert [s.group_id for s in plan.steps]==['a','b','c']
        page.order.setCurrentRow(1); page.direction.setCurrentText('-X'); page._apply_step()
        assert plan.steps[1].removal_direction==(-1,0,0)
        assert page.direction.currentText()=='-X'
        from PySide6.QtTest import QTest
        for _ in range(50):
            if all(not page.order.item(i).icon().isNull() for i in range(3)):break
            QTest.qWait(20)
        assert all(not page.order.item(i).icon().isNull() for i in range(3))
        page.order.setCurrentRow(1); page._single()
        before=plan.to_dict(); camera=page.vtk_scene.renderer.GetActiveCamera()
        before_camera=(camera.GetPosition(),camera.GetViewUp(),camera.GetFocalPoint())
        page.direction.setCurrentText('+Y'); page.camera.setCurrentText('RIGHT')
        page.step_preview_button.click()
        assert page._step_preview is not None
        assert page._step_preview['plan'].steps[1].removal_direction==(0,1,0)
        assert page._step_preview['plan'].steps[1].camera_mode=='RIGHT'
        for _ in range(4):page._preview_tick()
        page.step_preview_button.click()
        assert page._step_preview is None and plan.to_dict()==before
        assert (camera.GetPosition(),camera.GetViewUp(),camera.GetFocalPoint())==before_camera
        page.process.setPlainText('일괄 문구'); page._apply_forward()
        assert page.undo_button.isEnabled()
        page._history(False)
        assert plan.to_dict()==before
    finally:
        page.close(); page.vtk_scene.render_window.Finalize()
        if page.vtk_scene._thumbnail_window:page.vtk_scene._thumbnail_window.Finalize()


def test_confirmation_snapshot_is_not_changed_by_later_edits(tmp_path):
    from pa2.storage.database import Database
    from pa2.storage.layout import DataLayout
    from pa2.application.project_service import ProjectService
    from pa2.application.plan_service import PlanService
    from pa2.domain.models import Plan,PlanStep,PlanningStatus
    db=Database(DataLayout(tmp_path/'data')); db.initialize()
    project=ProjectService(db).create('test','KD1','HVJB'); service=PlanService(db)
    plan=Plan('plan',project.id,1,'base',['base','part'],[PlanStep('part',1,(0,0,1),(0,0,-1),12)],PlanningStatus.REVIEW_REQUIRED)
    confirmation=service.confirm(plan)
    plan.steps[0].travel_mm=99; service.save_draft(plan)
    assert service.load_confirmation(confirmation).steps[0].travel_mm==12
    assert service.load_current_draft(project.id).steps[0].travel_mm==99


def test_legacy_default_candidate_budget_migrates_to_240(tmp_path):
    from pa2.settings.config import SettingsStore
    path=tmp_path/'settings.json'; path.write_text(json.dumps({'version':'settings-v1','candidate_timeout_sec':180}),encoding='utf-8')
    assert SettingsStore(path).load().candidate_timeout_sec==240
