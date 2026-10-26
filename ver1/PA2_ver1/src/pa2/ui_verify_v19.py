"""Drive the real Qt application through the v19 workflow on an isolated copy.

Explicit --ui-v19-smoke opt-in only. It never changes external STEP sources.
PA2_DATA_ROOT must contain a disposable copy of the selected project.
"""
def verify_ui(output):
    import copy,json,os,sys,time,traceback,subprocess
    from dataclasses import asdict
    from pathlib import Path
    from PySide6.QtCore import QTimer,Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication,QMessageBox,QPushButton
    from pa2.ui.main_window import MainWindow
    from pa2.ui.group_dialog import ManualGroupDialog
    from pa2.application.video_library import VideoLibrary
    from pa2.jobs.isolated import IsolatedCadWorker
    from pa2.cad.path_check import ConservativePathChecker
    from pa2.video.renderer import VideoRenderer
    from pa2.settings.config import AppSettings
    import imageio_ffmpeg

    destination=Path(output).resolve();destination.parent.mkdir(parents=True,exist_ok=True)
    data_root=Path(os.environ['PA2_DATA_ROOT']).resolve()
    if 'v19' not in data_root.name.lower():raise ValueError('Use an isolated v19 test data copy')
    app=QApplication([]);root=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parents[2]))
    window=MainWindow(root);window.show()
    if os.environ.get('PA2_SMOKE_SETTINGS'):
        raw=json.loads(Path(os.environ['PA2_SMOKE_SETTINGS']).read_text(encoding='utf-8'))
        window.settings=AppSettings(**raw['settings'])
    started=time.monotonic();phase=['opening'];faults=[];cad_calls=[];samples=[[],[]]
    report={'data_root':str(data_root),'settings':asdict(window.settings),'renders':[]}
    old_native=IsolatedCadWorker.call;old_check=ConservativePathChecker.check;old_render=VideoRenderer.render
    old_messages={key:getattr(QMessageBox,key) for key in ('critical','warning','information')}
    def require(condition,message):
        if not condition:raise AssertionError(message)
    def message(parent,title,text,*args,**kwargs):
        faults.append(f'{title}: {text}');return QMessageBox.Ok
    for key in old_messages:setattr(QMessageBox,key,message)
    def forbidden(*args,**kwargs):
        cad_calls.append(phase[0]);raise AssertionError('Editing/rendering called CAD validation')
    def measured_render(self,*args,**kwargs):
        begin=time.monotonic();result=old_render(self,*args,**kwargs)
        report['renders'].append({'path':str(result.path),'elapsed_sec':time.monotonic()-begin,
            'result':asdict(result),'steps':len(args[0].steps)})
        report['renders'][-1]['result']['path']=str(result.path)
        return result
    VideoRenderer.render=measured_render
    project_id=os.environ['PA2_SMOKE_PROJECT']
    def current_project():return next(p for p in window.projects.list() if p.id==project_id)
    def finish(ok,error=None):
        report.update(ok=ok,phase=phase[0],elapsed_sec=time.monotonic()-started,cad_revalidation_calls=len(cad_calls),
            progress_samples=samples,message_boxes=faults)
        if error:report.update(error=str(error),traceback=traceback.format_exc())
        destination.write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
        IsolatedCadWorker.call=old_native;ConservativePathChecker.check=old_check;VideoRenderer.render=old_render
        for key,value in old_messages.items():setattr(QMessageBox,key,value)
        window.close();app.quit()
    def button(page,text):return next(b for b in page.findChildren(QPushButton) if b.text()==text)
    def select_parts(ids):
        page=window.model_page;page.order.clearSelection();page.parts.clearSelection()
        for i in range(page.parts.count()):page.parts.item(i).setSelected(page.parts.item(i).data(Qt.UserRole) in ids)
        page._select_group()
    def group(name):
        select_parts(report['selected_ids']);page=window.model_page
        require(page.group_button.isEnabled(),'Group button is disabled')
        def accept():
            dialog=app.activeModalWidget()
            try:
                require(isinstance(dialog,ManualGroupDialog),'Manual group dialog did not open')
                choices=[dialog.name.itemText(i) for i in range(dialog.name.count())]
                expected=[g.display_name for g in window.import_result.snapshot.groups if g.id in report['selected_ids']]
                require(choices==list(dict.fromkeys(expected)),'Name choices include unselected parts')
                dialog.name.setCurrentIndex(0);require(dialog.group_name()==choices[0],'Selected name was not used')
                dialog.name.setEditText(name)
                require(dialog.group_name()==name,'Direct name input failed')
                dialog.grab().save(str(destination.with_name(destination.stem+'-group-dialog.png')))
                report['name_options_selected_only']=True;report['direct_and_selected_name_input']=True
                dialog.accept()
            except Exception as exc:
                faults.append(str(exc))
                if dialog:dialog.reject()
        QTimer.singleShot(150,accept);page.group_button.click()
    def manual_group():return next(g for g in window.import_result.snapshot.groups if g.id.startswith('manual-'))
    def reopen(next_phase):
        phase[0]=next_phase;window._reopen(current_project())
    original_planned=window._planned
    def planned(result):
        report['planning']={'status':result.status.value,'reason':result.reason,'metrics':result.metrics,
                            'removal_order':result.removal_order,
                            'paths':[asdict(p) for p in result.path_results],
                            'plan':result.assembly_plan.to_dict()}
        original_planned(result)
    window._planned=planned
    window._reopen(current_project())
    def poll():
        try:
            sample=[window.video_page.progress_bar.value(),window.video_page.progress_bar.maximum()]
            if phase[0] in ('render-first','render-edited'):
                index=int(phase[0]=='render-edited')
                if not samples[index] or samples[index][-1]!=sample:samples[index].append(sample)
            destination.with_suffix('.progress.json').write_text(json.dumps({'phase':phase[0],
                'elapsed_sec':time.monotonic()-started,'progress':sample,'status':window.statusBar().currentMessage(),
                'message':window.video_page.progress_label.text()},ensure_ascii=False),encoding='utf-8')
            if faults:raise RuntimeError('; '.join(faults))
            if time.monotonic()-started>5400:raise TimeoutError('v19 end-to-end exceeded 90 minutes')
            if (window.thread and window.thread.isRunning()) or not window.model_page.isEnabled():
                QTimer.singleShot(500,poll);return
            page=window.model_page
            if phase[0]=='opening':
                require(window.current_plan and len(window.current_plan.steps)==63,'Existing project/draft not restored')
                groups=window.import_result.snapshot.groups
                require(len(groups)==64,'Unexpected baseline group count')
                report.update(initial_groups=len(groups),initial_steps=len(window.current_plan.steps),
                    initial_snapshot_id=window.import_result.snapshot.id,old_confirmation_id=window.confirmation_id,
                    old_confirmed_plan=window.plans.load_confirmation(window.confirmation_id).to_dict(),
                    selected_ids=[g.id for g in groups if len(g.body_ids)==1 and g.body_ids[0].endswith(('000040','000041'))])
                require(len(report['selected_ids'])==2,'Test raw bodies 41/42 were not uniquely found')
                auto=next(g for g in groups if len(g.body_ids)>1 and g.matching_status.value=='MATCHED')
                report['automatic_group_id']=auto.id;report['automatic_body_ids']=list(auto.body_ids)
                select_parts([auto.id]);require(not page.ungroup_button.isEnabled(),'Automatic group can be ungrouped')
                report['automatic_group_locked']=True
                expected=['LV CONT','HVSC 2800 #1','HVSC 2800 #2','AIR-BENT0A']
                exceptions=[g.id for g in groups if g.display_name in expected]
                require(len(exceptions)==4,'Expected exceptions were not found')
                page.set_exceptions(exceptions);window._save_preset()
                phase[0]='grouped';group('검증용 수동 그룹 · 바디41·42')
            elif phase[0]=='grouped':
                g=manual_group();require(len(g.body_ids)==2,'Manual group did not combine two bodies')
                require(window.current_plan is None and window.confirmation_id is None,'Old sequence was not invalidated')
                report['manual_id']=g.id;report['manual_name']=g.display_name
                reopen('group-reopened')
            elif phase[0]=='group-reopened':
                g=manual_group();require(g.id==report['manual_id'] and g.display_name==report['manual_name'],'Manual group persistence failed')
                require(page.parts.count()==63 and page.order.count()==0,'Manual group is not one unit')
                select_parts([g.id]);require(page.ungroup_button.isEnabled(),'Manual ungroup is disabled')
                phase[0]='ungrouped';page.ungroup_button.click()
            elif phase[0]=='ungrouped':
                require(page.parts.count()==64,'Ungroup did not restore part count')
                auto=next(g for g in window.import_result.snapshot.groups if g.id==report['automatic_group_id'])
                require(auto.body_ids==report['automatic_body_ids'],'Automatic group internals changed')
                select_parts([auto.id]);require(not page.ungroup_button.isEnabled(),'Auto lock was lost')
                report['manual_ungroup_verified']=True
                phase[0]='grouped-final';group(report['manual_name'])
            elif phase[0]=='grouped-final':
                g=manual_group();report['manual_id']=g.id;report['group_count']=page.parts.count()
                report['manual_body_ids']=g.body_ids;report['final_snapshot_id']=window.import_result.snapshot.id
                require(page.parts.count()==63,'Final manual partition differs')
                require(window.plans.load_confirmation(report['old_confirmation_id']).to_dict()==report['old_confirmed_plan'],'Old confirmation changed')
                report['old_confirmation_preserved']=True
                window.grab().save(str(destination.with_name(destination.stem+'-grouped.png')))
                if os.environ.get('PA2_UI_VERIFY_PREFLIGHT')=='1':finish(True);return
                phase[0]='planning';report['planning_started_monotonic']=time.monotonic()
                button(page,'순서 생성').click()
            elif phase[0]=='planning':
                require(window.current_plan is not None,'No generated draft')
                report['planning_wall_sec']=time.monotonic()-report.pop('planning_started_monotonic')
                require(len(window.current_plan.steps)==62,'Not all 62 moving units were included in the draft')
                require(sum(s.group_id==report['manual_id'] for s in window.current_plan.steps)==1,'Manual unit did not get one step')
                require(not window.video_page.generate.isEnabled(),'Unconfirmed draft can render')
                report['generated_steps']=len(window.current_plan.steps)
                report['generated_signature']=window.plans.content_signature(window.current_plan)
                IsolatedCadWorker.call=forbidden;ConservativePathChecker.check=forbidden
                page.order.setCurrentRow(0);page._single()
                button(page,'순서 확정').click()
                require(window.confirmation_id and window.video_page.generate.isEnabled(),'Explicit confirmation failed')
                report['first_confirmation_id']=window.confirmation_id
                phase[0]='render-first';window.video_page.generate.click()
            elif phase[0]=='render-first':
                require(window.video_path and Path(window.video_path).is_file(),'First movie missing')
                report['first_video']=str(window.video_path)
                require(any(0<a<b for a,b in samples[0]),'First render progress was not visible')
                export=destination.with_name('PA2_v19_before_edit_export.mp4')
                VideoRenderer(window.settings,root/'assets/video_template_v1.json',root/'assets/thn_logo.png').export(window.video_path,export)
                report['exported_copy']=str(export)
                window.tabs.setCurrentWidget(page)
                old_order=[s.group_id for s in page.plan.steps]
                page.order.clearSelection();page.order.item(1).setSelected(True);page.order.item(3).setSelected(True)
                page.order.move_selection(0)
                require([s.group_id for s in page.plan.steps][:2]==[old_order[1],old_order[3]],'Multi-card move failed')
                require(not window.video_page.generate.isEnabled(),'Order edit did not require confirmation')
                page._history(False);require([s.group_id for s in page.plan.steps]==old_order,'Undo failed')
                require(window.video_page.generate.isEnabled(),'Exact undo did not restore confirmation')
                page.order.clearSelection();page.order.item(1).setSelected(True);page.order.item(3).setSelected(True);page.order.move_selection(0)
                page.order.setCurrentRow(0);page._single();old=page.direction.currentText()
                page.direction.setCurrentText('-'+old[1:] if old.startswith('+') else '+'+old[1:])
                page.camera.setCurrentText('TOP');page.process.setPlainText('사용자 수정 시험 · 묶음 순서와 방향 확인')
                require(page.has_pending_fields() and not window.video_page.generate.isEnabled(),'Pending fields can render')
                before=page.plan.to_dict();page.step_preview_button.click();require(page._step_preview is not None,'Pending-field preview failed')
                for _ in range(4):page._preview_tick()
                page.step_preview_button.click();require(page.plan.to_dict()==before,'Preview mutated draft')
                page.apply_button.click();require(not page.has_pending_fields(),'Applied fields remain pending')
                page._save();report['edited_signature']=window.plans.content_signature(page.plan)
                report['edited_order']=[s.group_id for s in page.plan.steps]
                window.grab().save(str(destination.with_name(destination.stem+'-editor.png')))
                reopen('edited-reopened')
            elif phase[0]=='edited-reopened':
                require(window.plans.content_signature(page.plan)==report['edited_signature'],'Saved edits changed on reopen')
                require(not window.video_page.generate.isEnabled(),'Reopened changed draft can render old confirmation')
                require(window.confirmation_id==report['first_confirmation_id'],'Previous immutable confirmation lost')
                button(page,'순서 확정').click()
                require(window.confirmation_id!=report['first_confirmation_id'],'Reconfirmation was not created')
                report['edited_confirmation_id']=window.confirmation_id
                phase[0]='render-edited';window.video_page.generate.click()
            elif phase[0]=='render-edited':
                require(window.video_path and str(window.video_path)!=report['first_video'],'Edited movie missing')
                require(any(0<a<b for a,b in samples[1]),'Second progress not observed')
                report['edited_video']=str(window.video_path)
                require(window.plans.matches_confirmation(page.plan,window.confirmation_id),'Rendered confirmation differs from edited plan')
                window.video_page.decoded_preview_frames=0;window.video_page.player.play()
                phase[0]='preview';QTimer.singleShot(2500,poll);return
            elif phase[0]=='preview':
                video=window.video_page
                require(video.player.duration()>0 and video.decoded_preview_frames>0,'Native movie preview decoded no frames')
                video.rate.setCurrentText('2×');require(video.player.playbackRate()==2,'Playback rate failed')
                video.fullscreen.click();app.processEvents();require(video.video.isFullScreen(),'Fullscreen failed')
                QTest.keyClick(video.video,Qt.Key_Escape);require(not video.video.isFullScreen(),'Esc did not exit fullscreen')
                video.player.pause();window.grab().save(str(destination.with_name(destination.stem+'-video.png')))
                frame=video.video.videoSink().videoFrame()
                if frame.isValid():frame.toImage().save(str(destination.with_name(destination.stem+'-preview.png')))
                report['preview_frames']=video.decoded_preview_frames;report['fullscreen_escape_and_rate']=True
                library=VideoLibrary(window.database,window.layout)
                report['before_cleanup']=[{'path':str(p),'bytes':size} for p,_,size in library.completed(project_id)]
                require(len(report['before_cleanup'])>=4,'Expected copied old movies plus two new movies')
                phase[0]='cleaned';video.cleanup.click()
            elif phase[0]=='cleaned':
                result=window.last_cleanup_result;report['cleanup']=result
                require(result['kept']==str(Path(report['edited_video']).resolve()),'Latest edited movie was not retained')
                require(len(result['deleted'])==len(report['before_cleanup'])-1 and not result['errors'],'Older movies were not deleted')
                require(not Path(report['first_video']).exists() and Path(report['exported_copy']).exists(),'Export/cleanup isolation failed')
                report['remaining_completed']=[str(p) for p,_,_ in VideoLibrary(window.database,window.layout).completed(project_id)]
                require(len(report['remaining_completed'])==1,'Not exactly one completed movie')
                require(window.plans.load_confirmation(report['old_confirmation_id']).to_dict()==report['old_confirmed_plan'],'Cleanup changed old sequence')
                report['cad_and_plans_retained']=True
                window.grab().save(str(destination.with_name(destination.stem+'-cleaned.png')))
                # Decode every frame of both newly rendered versions: the first
                # remains available as the independently exported copy.
                report['decoded_movies']=[]
                for path in (report['exported_copy'],report['edited_video']):
                    decoded=subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-hide_banner','-loglevel','error',
                        '-nostats','-progress','pipe:1','-i',path,'-f','null','-'],capture_output=True,text=True,
                        timeout=600,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                    frames=[int(s.split('=',1)[1]) for s in decoded.stdout.splitlines() if s.startswith('frame=')]
                    expected=next(r['result']['frame_count'] for r in report['renders'] if r['path']==(report['first_video'] if path==report['exported_copy'] else path))
                    require(decoded.returncode==0 and frames and frames[-1]==expected,'Full movie decode failed')
                    report['decoded_movies'].append({'path':path,'frames':frames[-1],'ok':True})
                finish(True);return
            QTimer.singleShot(500,poll)
        except Exception as exc:finish(False,exc)
    QTimer.singleShot(500,poll);app.exec()
    return 0 if report.get('ok') else 1
