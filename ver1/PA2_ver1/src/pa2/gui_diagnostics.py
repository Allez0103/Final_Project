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
