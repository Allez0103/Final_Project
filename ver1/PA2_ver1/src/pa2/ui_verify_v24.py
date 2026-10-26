"""Opt-in selection/edit/render/real media playback test on a marked copy."""
def verify_ui(output):
    import copy,json,os,sys,time,traceback,subprocess
    from dataclasses import asdict
    from pathlib import Path
    from PySide6.QtCore import QTimer,Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication,QMessageBox,QPushButton
    from PySide6.QtMultimedia import QMediaPlayer
    from PIL import Image
    from .ui.main_window import MainWindow
    from .settings.config import AppSettings,SettingsStore
    from .cad.path_check import ConservativePathChecker
    from .jobs.isolated import IsolatedCadWorker
    from .rendering.scene import build_timeline,scene_at
    from .video.renderer import VideoRenderer
    import imageio_ffmpeg

    data=Path(os.environ['PA2_DATA_ROOT']).resolve()
    if not (data/'v24-isolated-copy.json').is_file() or os.environ.get('PA2_DISABLE_BACKGROUND_LEARNING')!='1':
        raise ValueError('Use marked independent data with background learning disabled')
    dest=Path(output).resolve();dest.parent.mkdir(parents=True,exist_ok=True)
    app=QApplication([]);app_root=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parents[2]))
    window=MainWindow(app_root);window.settings=AppSettings();window.settings_store=SettingsStore(data/'settings.json')
    window.show();started=time.monotonic();phase=['opening'];faults=[];calls=[]
    report=dict(data_root=str(data),frozen=bool(getattr(sys,'frozen',False)),executable=sys.executable,
        settings=asdict(window.settings),progress=[],rates=[],renders=[],model_training_performed=False)
    native=IsolatedCadWorker.call;check=ConservativePathChecker.check;render=VideoRenderer.render
    messages={k:getattr(QMessageBox,k) for k in ('critical','warning','information')}
    def require(ok,message):
        if not ok:raise AssertionError(message)
    def forbidden(*args,**kwargs):calls.append(phase[0]);raise AssertionError('Selection/edit/render called CAD checks')
    def message(parent,title,text,*args,**kwargs):faults.append(f'{title}: {text}');return QMessageBox.Ok
    IsolatedCadWorker.call=forbidden;ConservativePathChecker.check=forbidden
    for k in messages:setattr(QMessageBox,k,message)
    def measured(self,*args,**kwargs):
        begin=time.monotonic();result=render(self,*args,**kwargs)
        report['renders'].append(dict(elapsed_sec=time.monotonic()-begin,result=asdict(result),steps=len(args[0].steps)))
        return result
    VideoRenderer.render=measured
    def finish(ok,error=None):
        report.update(ok=ok,phase=phase[0],elapsed_sec=time.monotonic()-started,faults=faults,forbidden_cad_calls=calls)
        if error:report.update(error=str(error),traceback=traceback.format_exc())
        dest.write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
        IsolatedCadWorker.call=native;ConservativePathChecker.check=check;VideoRenderer.render=render
        for k,v in messages.items():setattr(QMessageBox,k,v)
        window.video_page.video.setFullScreen(False);window.close();app.quit()
    def checkpoint():
        sample=dict(phase=phase[0],text=window.video_page.progress_label.text())
        if not report['progress'] or report['progress'][-1]!=sample:report['progress'].append(sample)
        dest.with_suffix('.progress.json').write_text(json.dumps(dict(phase=phase[0],elapsed_sec=time.monotonic()-started,
            text=sample['text']),ensure_ascii=False),encoding='utf-8')
    def selected():return {i.data(Qt.UserRole) for i in window.model_page.parts.selectedItems()}
    def selection_and_edits():
        page=window.model_page;scene=page.vtk_scene;plan=page.plan
        before=copy.deepcopy(plan.to_dict());original=window.plans.load_original(plan.id).to_dict()
        cid=window.confirmation_id;confirmed=window.plans.load_confirmation(cid).to_dict()
        page.parts.clearSelection();page.order.clearSelection()
        group=next(g for g in window.import_result.snapshot.groups if g.display_name.startswith('COV-'))
        item=next(page.parts.item(i) for i in range(page.parts.count()) if page.parts.item(i).data(Qt.UserRole)==group.id)
        # Exercise the actual list widget mouse press/release path, not only its slot.
        page.parts.scrollToItem(item);QApplication.processEvents()
        point=page.parts.visualItemRect(item).center()
        QTest.mouseClick(page.parts.viewport(),Qt.LeftButton,Qt.NoModifier,point)
        require(selected()=={group.id},'List click did not select')
        page.process.setPlainText(page.process.toPlainText()+' · 미적용 입력 시험')
        require(not window.video_page.generate.isEnabled(),'Unapplied fields can render')
        QTest.mouseClick(page.parts.viewport(),Qt.LeftButton,Qt.NoModifier,point)
        require(not selected() and not page.order.selectedItems(),'List reclick did not clear both selections')
        require(window.video_page.generate.isEnabled(),'Clearing unapplied selection did not restore confirmed-video eligibility')
        baseline={g:(a.GetPosition(),a.GetProperty().GetColor(),a.GetProperty().GetOpacity(),a.GetVisibility()) for g,a in scene.actors.items()}
        camera=scene.renderer.GetActiveCamera();pose=(camera.GetPosition(),camera.GetFocalPoint(),camera.GetViewUp())
        page._picked(group.id);require(selected()=={group.id},'3D selection slot failed')
        page._picked(group.id);require(not selected(),'3D reclick did not clear')
        require(baseline=={g:(a.GetPosition(),a.GetProperty().GetColor(),a.GetProperty().GetOpacity(),a.GetVisibility()) for g,a in scene.actors.items()},'Clearing changed display baseline')
        other=next(g.id for g in window.import_result.snapshot.groups if g.id not in (group.id,plan.base_group_id))
        page._picked(group.id);page._picked(other,True);require(selected()=={group.id,other},'Multi-selection changed')
        require({g for g,a in scene.actors.items() if a.GetVisibility()}=={group.id,other},'Multi isolation lost')
        page._picked(other,True);require(selected()=={group.id,other},'Existing Ctrl semantics changed')
        page.parts.clearSelection();require(not selected(),'Multi clear failed')
        require(pose==(camera.GetPosition(),camera.GetFocalPoint(),camera.GetViewUp()),'Selection changed camera')
        require(plan.to_dict()==before,'Selection changed plan')
        require(not page.diagnostics_button.isVisible(),'Diagnostics button is visible')
        report['selection']=dict(list_reclick=True,model_pick_callback_reclick=True,multi_unchanged=True,
            display_restored=True,camera_and_plan_unchanged=True,diagnostics_hidden=True)
        window.grab().save(str(dest.with_name(dest.stem+'-editor.png')))
        Image.fromarray(scene.rgb_array()).save(dest.with_name(dest.stem+'-scene.png'))
        index=next(i for i,s in enumerate(plan.steps) if s.group_id==group.id)
        page.order.setCurrentRow(index);page._single()
        step=plan.steps[index];page.direction.setCurrentText('+X' if step.removal_direction!= (1,0,0) else '-X')
        page.camera.setCurrentText('LEFT');page.process.setPlainText('UI 보완 · 순서 편집 후 조립 영상 검증')
        page.material.setPlainText(group.display_name);page.caution.setPlainText('')
        require(not window.video_page.generate.isEnabled(),'Pending fields can render')
        snapshot=copy.deepcopy(plan.to_dict());display=scene.capture_selection_state()
        page.step_preview_button.click();page._preview_tick();page.step_preview_button.click()
        require(plan.to_dict()==snapshot,'Step preview changed plan')
        require({g:(a.GetVisibility(),a.GetPosition(),a.GetProperty().GetOpacity()) for g,a in scene.actors.items()}==
            {g:(v,pos,prop.GetOpacity()) for g,(v,pos,prop) in display['actors'].items()},'Step preview restore failed')
        page.apply_button.click()
        edited=copy.deepcopy(plan.to_dict());page._history(False);page._history(True)
        # Each automatic save advances the DB revision, including undo/redo.
        # Compare actual editing content, not this monotonic save counter.
        require({k:v for k,v in plan.to_dict().items() if k!='revision'}==
                {k:v for k,v in edited.items() if k!='revision'},'Undo/redo failed')
        page.order.clearSelection();page.order.item(0).setSelected(True);page.order.item(1).setSelected(True)
        page.order.move_selection(4)
        require(window.plans.load_current_draft(plan.project_id).to_dict()==plan.to_dict(),'Autosave lost edits')
        require(window.plans.load_original(plan.id).to_dict()==original,'Original overwritten')
        require(window.plans.load_confirmation(cid).to_dict()==confirmed,'Previous confirmation overwritten')
        require(not window.video_page.generate.isEnabled(),'Reordered plan can render without confirmation')
        next(b for b in page.findChildren(QPushButton) if b.text()=='순서 확정').click()
        require(window.confirmation_id!=cid and window.video_page.generate.isEnabled(),'Confirmation failed')
        report['editing']=dict(step_count=len(plan.steps),undo_redo=True,autosave=True,original_preserved=True,
            previous_confirmation_preserved=True,confirmation_required=True,preview_restored=True)
        report['edited_plan']=copy.deepcopy(plan.to_dict());report['confirmation_id']=window.confirmation_id
        timeline=build_timeline(plan,window.settings)
        require(all(abs(s.move_end-s.highlight_end-.7)<1e-8 for s in timeline.segments),'Movement duration is not .7s')
        require(all(abs(s.highlight_end-s.camera_end-2)<1e-8 for s in timeline.segments),'Blink duration changed')
        report['timeline']=dict(duration_sec=timeline.duration,move_sec=.7,blink_sec=2,steps=len(timeline.segments))
        first=timeline.segments[0]
        for name,t in [('blink-on',first.camera_end+.01),('blink-off',first.camera_end+.26),('moving',first.highlight_end+.1)]:
            frame=scene_at(plan,t,window.settings,timeline);scene.apply(frame)
            Image.fromarray(scene.rgb_array()).save(dest.with_name(dest.stem+'-'+name+'.png'))
        require(not calls,'Unexpected CAD')
        window.tabs.setCurrentWidget(window.video_page)
    project=next(p for p in window.projects.list() if p.id==os.environ['PA2_SMOKE_PROJECT'])
    window._reopen(project)
    rates=['0.25×','0.5×','1×','1.5×','2×','3×','4×'];rate_index=[0];sample=[None];phase_start=[time.monotonic()]
    def set_phase(value):phase[0]=value;phase_start[0]=time.monotonic()
    def poll():
        try:
            checkpoint()
            if faults:raise RuntimeError('; '.join(faults))
            if time.monotonic()-started>1200:raise TimeoutError('v24 workflow timed out')
            if window.thread and window.thread.isRunning():QTimer.singleShot(250,poll);return
            vp=window.video_page
            if phase[0]=='opening':
                require(window.current_plan is not None,'Project reopen failed')
                report['group_count']=len(window.import_result.snapshot.groups)
                selection_and_edits()
                if os.environ.get('PA2_V24_PREFLIGHT')=='1':finish(True);return
                set_phase('rendering');vp.generate.click()
            elif phase[0]=='rendering':
                require(len(report['renders'])==1 and window.video_path,'Video missing')
                item=report['renders'][0];item['path']=str(window.video_path)
                result=subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-v','error','-i',str(window.video_path),
                    '-map','0:v:0','-f','null','-','-progress','pipe:1','-nostats'],capture_output=True,timeout=180,
                    creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                require(result.returncode==0,'Full decode failed')
                item['decoded_frames']=max(int(s.split('=')[1]) for s in result.stdout.decode().splitlines() if s.startswith('frame='))
                require(item['decoded_frames']==item['result']['frame_count'],'Frame count mismatch')
                set_phase('loading-video')
            elif phase[0]=='loading-video':
                require(vp.player.error()==QMediaPlayer.NoError,vp.player.errorString())
                if vp.player.duration()>0 and vp.play.isEnabled():
                    require([vp.rate.itemText(i) for i in range(vp.rate.count())]==rates,'Rate choices differ')
                    vp.player.pause();vp.first_button.click();require(vp.player.position()<150,'First failed')
                    vp.next_button.click();require(abs(vp.player.position()-5000)<150,'Forward 5s failed')
                    vp.previous_button.click();require(vp.player.position()<150,'Back 5s failed')
                    vp.last_button.click();require(abs(vp.player.position()-vp.player.duration())<150,'Last failed')
                    vp.next_button.click();require(vp.player.position()<=vp.player.duration(),'End not clamped')
                    vp.first_button.click();vp.previous_button.click();require(vp.player.position()==0,'Start not clamped')
                    vp.seek.sliderMoved.emit(10000);require(abs(vp.player.position()-10000)<150,'Scrubber failed')
                    report['transport']=dict(first_last=True,back_forward_5sec=True,bounds=True,scrubber=True)
                    set_phase('start-rate')
                elif time.monotonic()-phase_start[0]>30:raise TimeoutError('MP4 load timed out')
            elif phase[0]=='start-rate':
                vp.player.pause();vp._seek_to(10000);vp.rate.setCurrentText(rates[rate_index[0]])
                vp.play.click();require(vp.play.accessibleName()=='일시정지','Play icon not updated')
                sample[0]=(time.monotonic(),vp.player.position(),vp.decoded_preview_frames)
                set_phase('playing-rate')
            elif phase[0]=='playing-rate':
                if time.monotonic()-sample[0][0]>=1.2:
                    begin,pos,frames=sample[0];elapsed=time.monotonic()-begin;delta=vp.player.position()-pos
                    require(vp.player.error()==QMediaPlayer.NoError,vp.player.errorString())
                    require(vp.player.position()>pos and vp.decoded_preview_frames>frames,'Playback did not advance/decode')
                    rate=float(rates[rate_index[0]].rstrip('×'))
                    require(vp.player.playbackRate()==rate,'Player rejected rate')
                    if rate==4:require(delta/1000/elapsed>1.5,'4x playback did not speed up')
                    report['rates'].append(dict(requested=rate,actual=vp.player.playbackRate(),position_delta_ms=delta,
                        wall_sec=elapsed,observed_ratio=delta/1000/elapsed,decoded_frames=vp.decoded_preview_frames-frames))
                    vp.play.click();require(vp.play.accessibleName()=='재생','Pause icon not updated')
                    rate_index[0]+=1
                    if rate_index[0]<len(rates):set_phase('start-rate')
                    else:
                        vp.fullscreen.click();require(vp.video.isFullScreen(),'Fullscreen failed')
                        set_phase('fullscreen')
            elif phase[0]=='fullscreen':
                QTest.keyClick(vp.video,Qt.Key_Escape);require(not vp.video.isFullScreen(),'Esc did not exit fullscreen')
                require(vp.fullscreen.text()=='전체화면','Fullscreen button not restored')
                report['fullscreen_esc']=True;vp.rate.setCurrentText('1×');vp.player.pause()
                window.grab().save(str(dest.with_name(dest.stem+'-video.png')))
                set_phase('reopening-final');window._reopen(project)
            elif phase[0]=='reopening-final':
                require(window.plans.matches_confirmation(window.current_plan,window.confirmation_id),'Reopen lost confirmation')
                require(len(window.current_plan.steps)==report['editing']['step_count'],'Reopen lost steps')
                require(not calls,'Unexpected CAD');report['reopened_confirmation']=True;finish(True);return
            QTimer.singleShot(250,poll)
        except Exception as exc:finish(False,exc)
    QTimer.singleShot(250,poll);app.exec()
    return 0 if report.get('ok') else 1
