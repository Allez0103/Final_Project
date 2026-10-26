"""Exercise the shipped editor, review button and native video preview."""
def verify_ui(output):
    import json, os, sys, time, traceback, subprocess
    from pathlib import Path
    from PySide6.QtCore import QTimer, Qt
    from PySide6.QtWidgets import QApplication, QListView
    from PySide6.QtTest import QTest
    import imageio_ffmpeg
    from pa2.ui.main_window import MainWindow
    from pa2.jobs.isolated import IsolatedCadWorker
    from pa2.cad.path_check import ConservativePathChecker
    destination=Path(output).resolve(); destination.parent.mkdir(parents=True,exist_ok=True)
    app=QApplication([]); root=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parents[2]))
    window=MainWindow(root); window.show(); started=time.monotonic(); report={}; phase=['opening']; cad_calls=[]; progress_samples=[]
    def require(condition,message):
        # PyInstaller uses optimize=1, which removes Python assert statements.
        if not condition:raise AssertionError(message)
    native_call=IsolatedCadWorker.call; path_check=ConservativePathChecker.check
    def forbidden(*args,**kwargs):
        cad_calls.append('revalidation'); raise AssertionError('Manual review invoked CAD checks')
    project=next(p for p in window.projects.list() if p.id==os.environ['PA2_SMOKE_PROJECT'])
    window._reopen(project)
    def fail(error):
        report.update(ok=False,error=str(error),traceback=traceback.format_exc(),phase=phase[0]); finish()
    def finish():
        IsolatedCadWorker.call=native_call; ConservativePathChecker.check=path_check
        destination.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        window.close(); app.quit()
    def poll():
        try:
            sample=(window.video_page.progress_bar.value(),window.video_page.progress_bar.maximum())
            if phase[0]=='rendering' and (not progress_samples or sample!=progress_samples[-1]):progress_samples.append(sample)
            destination.with_suffix('.progress.json').write_text(json.dumps({'phase':phase[0],'elapsed_sec':time.monotonic()-started,'progress':sample,'message':window.video_page.progress_label.text()}),encoding='utf-8')
            if time.monotonic()-started>1800:raise TimeoutError('GUI end-to-end timeout')
            if phase[0]=='opening':
                if window.thread and window.thread.isRunning():QTimer.singleShot(300,poll); return
                page=window.model_page
                require(window.current_plan and len(window.current_plan.steps)>0,'No editable plan')
                require(page.order.flow()==QListView.Flow.LeftToRight,'Cards are not horizontal')
                if any(page.order.item(i).icon().isNull() for i in range(page.order.count())):
                    QTimer.singleShot(200,poll); return
                require(all(not page.order.item(i).icon().isNull() for i in range(page.order.count())),'Missing shape thumbnails')
                original=[s.group_id for s in page.plan.steps]
                page.order.clearSelection(); page.order.item(1).setSelected(True); page.order.item(3).setSelected(True)
                page.order.move_selection(0)
                require([s.group_id for s in page.plan.steps][:2]==[original[1],original[3]],'Group move order differs')
                require(len(page.order.selectedItems())==2,'Group selection lost')
                page._history(False); require([s.group_id for s in page.plan.steps]==original,'Undo differs')
                page.order.clearSelection(); page.order.item(1).setSelected(True); page.order.item(3).setSelected(True); page.order.move_selection(0)
                page.order.setCurrentRow(0)
                page._single()
                require(len(page.order.selectedItems())==1,'Direction edit needs a single selected card')
                old_direction=page.plan.steps[0].removal_direction
                name=page._direction_text(old_direction); page.direction.setCurrentText('-'+name[1:] if name.startswith('+') else '+'+name[1:] if name.startswith('-') else '+X')
                page._apply_step(); require(page.plan.steps[0].removal_direction!=old_direction,'Direction was not applied')
                expected=[s.group_id for s in page.plan.steps]
                IsolatedCadWorker.call=forbidden; ConservativePathChecker.check=forbidden
                before_preview=page.plan.to_dict()
                camera=page.vtk_scene.renderer.GetActiveCamera()
                before_camera=(camera.GetPosition(),camera.GetFocalPoint(),camera.GetViewUp())
                saved_mode=page.camera.currentText(); page.camera.setCurrentText('TOP')
                page.step_preview_button.click()
                require(page._step_preview is not None,'Step preview did not start')
                require(page._step_preview['plan'].steps[0].camera_mode=='TOP','Pending camera edit absent from preview')
                QTest.qWait(500)
                page.vtk_scene.rgb_array()
                page.step_preview_button.click()
                require(page._step_preview is None,'Step preview did not stop')
                require(page.plan.to_dict()==before_preview,'Preview changed saved plan')
                require((camera.GetPosition(),camera.GetFocalPoint(),camera.GetViewUp())==before_camera,'Preview did not restore camera')
                page.camera.setCurrentText(saved_mode)
                report['step_preview_pending_edits_and_restore']=True
                render_started=time.monotonic(); report.update(original_order=original,edited_order=expected,
                    changed_group=page.plan.steps[0].group_id,old_direction=old_direction,new_direction=page.plan.steps[0].removal_direction,
                    render_started_monotonic=render_started,steps=len(expected),cards_with_real_thumbnails=True,multi_move_and_undo=True)
                if os.environ.get('PA2_UI_VERIFY_PREFLIGHT')=='1':
                    report.pop('render_started_monotonic'); report.update(ok=True,preflight_only=True,direction_edit_verified=True)
                    finish(); return
                window.tabs.setCurrentWidget(page); app.processEvents(); window.grab().save(str(destination.with_name(destination.stem+'-editor.png')))
                from PIL import Image
                Image.fromarray(page.vtk_scene.rgb_array()).save(destination.with_name(destination.stem+'-scene.png'))
                window.tabs.setCurrentWidget(window.video_page)
                window._confirm(page.plan); window.video_page.generate.click(); phase[0]='rendering'
            elif phase[0]=='rendering':
                if window.thread and window.thread.isRunning():QTimer.singleShot(500,poll); return
                require(window.video_path and Path(window.video_path).is_file(),'No rendered video')
                require(not cad_calls,'CAD revalidation was called')
                loaded=window.plans.load_confirmation(window.confirmation_id)
                require([s.group_id for s in loaded.steps]==report['edited_order'],'Rendered confirmation order differs')
                require(loaded.steps[0].removal_direction==tuple(report['new_direction']),'Confirmed direction differs')
                require(any(0<done<total for done,total in progress_samples),'No intermediate render progress observed')
                report['render_elapsed_sec']=time.monotonic()-report.pop('render_started_monotonic')
                report['managed_path']=str(window.video_path)
                export=destination.parent/f'PA2_assembly_{destination.stem}.mp4'
                from pa2.video.renderer import VideoRenderer
                VideoRenderer(window.settings,root/'assets/video_template_v1.json',root/'assets/thn_logo.png').export(Path(window.video_path),export)
                report['path']=str(export); window.video_page.decoded_preview_frames=0; window.video_page.player.play(); phase[0]='preview'; QTimer.singleShot(2500,poll); return
            elif phase[0]=='preview':
                video=window.video_page
                require(video.player.duration()>0,'No media duration: '+video.player.errorString())
                require(video.decoded_preview_frames>0,'Preview decoded no frames: '+video.player.errorString())
                video.rate.setCurrentText('2×'); require(video.player.playbackRate()==2,'Playback rate differs')
                video.player.setPosition(3000); video.player.pause()
                QTest.qWait(200); require(abs(video.player.position()-3000)<200,'Seek did not reach requested time')
                video.video.setFullScreen(True); app.processEvents(); require(video.video.isFullScreen(),'Fullscreen did not open')
                QTest.keyClick(video.video,Qt.Key_Escape); require(not video.video.isFullScreen(),'Escape did not exit fullscreen')
                window.grab().save(str(destination.with_name(destination.stem+'-video.png')))
                frame=video.video.videoSink().videoFrame()
                if frame.isValid():frame.toImage().save(str(destination.with_name(destination.stem+'-preview.png')))
                metadata=imageio_ffmpeg.read_frames(report['path']); info=next(metadata); metadata.close()
                ffmpeg=imageio_ffmpeg.get_ffmpeg_exe()
                result=subprocess.run([ffmpeg,'-hide_banner','-loglevel','error','-nostats','-progress','pipe:1','-i',report['path'],'-f','null','-'],capture_output=True,text=True,timeout=600,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                require(result.returncode==0,'Decode failed: '+result.stderr)
                frames=[int(line.split('=',1)[1]) for line in result.stdout.splitlines() if line.startswith('frame=')]
                require(frames and frames[-1]==round(video.player.duration()/1000*30),'Decoded frame count differs')
                report.update(ok=True,cad_revalidation_calls=len(cad_calls),review_button_actual_render=True,
                    video_metadata=info,decoded_frame_count=frames[-1],preview_frames=video.decoded_preview_frames,
                    playback_rate=video.player.playbackRate(),fullscreen_escape=True,seek_supported=True,
                    progress_value=video.progress_bar.value(),progress_maximum=video.progress_bar.maximum(),progress_samples=progress_samples,progress_observed=True,
                    elapsed_sec=time.monotonic()-started)
                finish(); return
            QTimer.singleShot(300,poll)
        except Exception as exc:fail(exc)
    QTimer.singleShot(400,poll); app.exec()
    return 0 if report.get('ok') else 1
