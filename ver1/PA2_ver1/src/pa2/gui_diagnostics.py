"""Exercise the real GUI import, widget creation and event loop in the EXE."""
def gui_smoke(output):
    import json,sys,traceback,os,time
    from pathlib import Path
    destination=Path(output).resolve(); destination.parent.mkdir(parents=True,exist_ok=True)
    try:
        from PySide6.QtCore import QTimer, qVersion
        from PySide6.QtWidgets import QApplication
        from .ui.main_window import MainWindow
        app=QApplication([]); app.setApplicationName('PA2 GUI verification')
        root=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parents[2]))
        window=MainWindow(root); window.show()
        report={}
        project_id=os.environ.get('PA2_SMOKE_PROJECT')
        started=time.monotonic()
        if project_id:
            project=next(p for p in window.projects.list() if p.id==project_id)
            window._reopen(project)
        def finish():
            if project_id and ((window.thread and window.thread.isRunning()) or not window.model_page.isEnabled()):
                if time.monotonic()-started<60:
                    QTimer.singleShot(250,finish); return
                report.update(ok=False,error='reopen timeout')
                destination.write_text(json.dumps(report),encoding='utf-8')
                window._cancel_task(); app.quit(); return
            report.update(ok=window.isVisible() and window.tabs.count()==3,
                qt_version=qVersion(),title=window.windowTitle(),tabs=window.tabs.count(),
                exception_button=window.model_page.exception_button.text())
            icon=window.brand_icon.pixmap()
            report['header_icon_present']=not icon.isNull()
            report['header_icon_logical_size']=[icon.deviceIndependentSize().width(),icon.deviceIndependentSize().height()]
            report['header_title']=window.brand_title.text()
            report['ok']=report['ok'] and report['header_icon_present'] and report['header_title']=='Pilot Assembly Assistant'
            window.brand_icon.parentWidget().grab().save(str(destination.with_name(destination.stem+'-header.png')))
            if project_id:
                from collections import Counter
                report.update(project_id=project_id,exception_ids=window.model_page.exception_ids,
                    group_count=len(window.import_result.snapshot.groups) if window.import_result else 0,
                    plan_steps=len(window.current_plan.steps) if window.current_plan else 0,
                    scene_update_on_ui_thread=getattr(window.model_page,'scene_update_on_ui_thread',False),
                    preset_restored=bool(window.import_result and window.model_page.exception_ids))
                report['ok']=report['ok'] and report['preset_restored'] and report['group_count']>0 and report['plan_steps']>0 and report['scene_update_on_ui_thread']
                if window.current_plan:
                    steps=window.current_plan.steps
                    report['geometry_status_counts']=dict(Counter(s.geometry_status.value for s in steps))
                    report['fastener_cards_without_unverified_warning']=all(
                        '미검증' not in window.model_page.order.item(i).text()
                        for i,s in enumerate(steps) if s.geometry_status.value=='FASTENER_ASSIGNED')
                    report['empty_cautions']=all(not s.caution_text for s in steps)
                    report['materials_present']=all(s.material_text for s in steps)
                    report['ok']=report['ok'] and report['fastener_cards_without_unverified_warning']
                if os.environ.get('PA2_SMOKE_SELECTION_ISOLATION')=='1':
                    try:
                        from .ui_verify_selection import verify_selection
                        report['selection_isolation']=verify_selection(window,destination)
                    except Exception:
                        report['selection_isolation']={'ok':False,'error':traceback.format_exc()}
                    report['ok']=report['ok'] and report['selection_isolation']['ok']
                if os.environ.get('PA2_SMOKE_PRESENTATION')=='1':
                    from .cad.grouping import GroupingService
                    from .rendering.scene import scene_at,camera_pose_angle,projected_model_size
                    page=window.model_page;plan=window.current_plan;timeline=page._timeline()
                    page._show_base_step()
                    base=scene_at(plan,0,window.settings,timeline)
                    consistent=True
                    for index,(step,segment) in enumerate(zip(plan.steps,timeline.segments)):
                        frame=scene_at(plan,segment.camera_end+.001,window.settings,timeline)
                        expected=timeline.step_cameras[index]
                        consistent &= max(abs(a-b) for a,b in zip(frame.camera.view_up,expected.view_up))<1e-8
                    presentation=dict(grouping_version=GroupingService.VERSION,
                        grouping_extra_relative_tolerance=GroupingService.EXTENDED_RELATIVE_TOLERANCE,
                        base_card=page.base_card.text(),base_card_visible=page.base_card.isVisible(),
                        displayed_stages=page.order.count()+1,camera_rolls=plan.camera_rolls,
                        base_active=base.active_group_id==plan.base_group_id,
                        base_stationary=base.translations[plan.base_group_id]==(0,0,0),
                        common_views_consistent=consistent,
                        first_camera_transition_sec=(timeline.segments[0].camera_end-timeline.segments[0].camera_start) if plan.steps else 0,
                        initial_to_first_angle_deg=camera_pose_angle(base.camera,timeline.step_cameras[0]) if plan.steps else 0,
                        initial_projected_model_size=projected_model_size(base.camera,window.import_result.assembly_scene.bounds),
                        first_view_landscape_roll_deg=timeline.first_view_landscape_roll_deg)
                    w,h=presentation['initial_projected_model_size']
                    report['presentation']=presentation
                    report['ok'] &= (presentation['base_card_visible'] and presentation['base_active']
                        and presentation['base_stationary'] and consistent and len(plan.camera_rolls)==6
                        and presentation['first_camera_transition_sec']==0
                        and presentation['initial_to_first_angle_deg']<1e-6 and w>=h-1e-8)
                if os.environ.get('PA2_SMOKE_BASE_SELECTION')=='1':
                    import copy
                    from PySide6.QtCore import Qt
                    from PySide6.QtTest import QTest
                    from .cad.path_check import ConservativePathChecker
                    from .jobs.isolated import IsolatedCadWorker
                    page=window.model_page;page.thumbnail_timer.stop()
                    original=copy.deepcopy(page.plan.to_dict());cases=[];calls=[]
                    native,check=IsolatedCadWorker.call,ConservativePathChecker.check
                    def forbidden(*_,**__):
                        calls.append('CAD');raise AssertionError('Selection invoked CAD validation')
                    IsolatedCadWorker.call=forbidden;ConservativePathChecker.check=forbidden
                    try:
                        page._show_all()
                        for row in (0,min(1,page.order.count()-1),0):
                            page.order.setCurrentRow(row);QApplication.processEvents()
                            QTest.mouseClick(page.base_card,Qt.LeftButton)
                            item=page.order.item(row);gid=item.data(Qt.UserRole)
                            page.order.scrollToItem(item);QApplication.processEvents()
                            QTest.mouseClick(page.order.viewport(),Qt.LeftButton,Qt.NoModifier,
                                             page.order.visualItemRect(item).center())
                            QApplication.processEvents()
                            step=next(s for s in page.plan.steps if s.group_id==gid)
                            cases.append(dict(row=row,selected={i.data(Qt.UserRole) for i in page.order.selectedItems()}=={gid},
                                part_visible=bool(page.vtk_scene.actors[gid].GetVisibility()),
                                base_unchecked=not page.base_card.isChecked(),fields_enabled=page.apply_button.isEnabled(),
                                fields_match=(page.process.toPlainText()==step.process_text and page.camera.currentText()==step.camera_mode
                                    and abs(page.distance.value()-round(step.travel_mm,page.distance.decimals()))<1e-8),
                                pending_fields=page.has_pending_fields(),edit_display_restored=page._timeline_edit_state is None))
                        passed=all(c['selected'] and c['part_visible'] and c['base_unchecked'] and c['fields_enabled']
                            and c['fields_match'] and not c['pending_fields'] and c['edit_display_restored'] for c in cases)
                        unchanged=page.plan.to_dict()==original
                        report['base_card_selection']=dict(ok=passed and unchanged and not calls,cases=cases,
                            plan_unchanged=unchanged,cad_calls=calls)
                        report['ok'] &= report['base_card_selection']['ok']
                    finally:
                        IsolatedCadWorker.call=native;ConservativePathChecker.check=check
                # QWidget.grab may leave a native OpenGL child black. Capture
                # VTK's real render buffer separately instead of trusting it.
                scene=window.model_page.vtk_scene
                scene.render_window.Render()
                pixels=scene.rgb_array()
                spatial_variation=float(pixels.reshape(-1,3).std(axis=0).max())
                report['scene_has_rendered_geometry']=scene.renderer.GetNumberOfPropsRendered()>0 and spatial_variation>5
                report['scene_pixel_spatial_std']=spatial_variation
                report['scene_render_size']=[int(pixels.shape[1]),int(pixels.shape[0])]
                from PIL import Image
                Image.fromarray(pixels).save(destination.with_name(destination.stem+'-scene.png'))
                report['ok']=report['ok'] and report['scene_has_rendered_geometry']
            window.grab().save(str(destination.with_suffix('.png')))
            destination.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            window.close(); app.quit()
        QTimer.singleShot(1200,finish)
        app.exec()
        return 0 if report.get('ok') else 1
    except Exception:
        destination.write_text(json.dumps({'ok':False,'error':traceback.format_exc()},ensure_ascii=False,indent=2),encoding='utf-8')
        return 1
