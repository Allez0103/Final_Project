"""Opt-in real Qt button workflow, on a marked isolated managed-data copy only."""
def verify_ui(output):
    import copy
    import json
    import os
    import subprocess
    import sys
    import time
    import traceback
    from dataclasses import asdict, replace
    from pathlib import Path
    from PySide6.QtCore import QTimer, Qt
    from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton
    from PIL import Image
    from .ui.main_window import MainWindow
    from .cad.path_check import ConservativePathChecker
    from .jobs.isolated import IsolatedCadWorker
    from .learning.collection import learning_status
    from .rendering.scene import build_timeline, scene_at
    from .settings.config import AppSettings
    from .video.renderer import VideoRenderer
    from .planning.priority import is_fastener
    import imageio_ffmpeg

    root = Path(os.environ['PA2_DATA_ROOT']).resolve()
    if not (root/'v23-isolated-copy.json').is_file():
        raise ValueError('Use a marked independent v23 validation copy')
    destination = Path(output).resolve(); destination.parent.mkdir(parents=True, exist_ok=True)
    if os.environ.get('PA2_DISABLE_BACKGROUND_LEARNING') != '1':
        raise ValueError('Disable background learning for this UI regression run')
    app = QApplication([])
    app_root = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[2]))
    window = MainWindow(app_root); window.show()
    window.settings = AppSettings(**json.loads((app_root/'assets/v20_validation_settings.json').read_text(encoding='utf-8'))) if (app_root/'assets/v20_validation_settings.json').exists() else AppSettings()
    if os.environ.get('PA2_SMOKE_SETTINGS'):
        window.settings=AppSettings(**json.loads(Path(os.environ['PA2_SMOKE_SETTINGS']).read_text(encoding='utf-8'))['settings'])
    window.settings=replace(window.settings,auto_learning_enabled=False,auto_model_apply_enabled=False)
    started = time.monotonic(); phase = ['opening']; faults = []; cad_calls = []
    report = dict(data_root=str(root), executable=sys.executable,
                  frozen=bool(getattr(sys,'frozen',False)), settings=asdict(window.settings),
                  plans={}, renders=[], progress_samples=[], finished=False)
    native = IsolatedCadWorker.call; path_check = ConservativePathChecker.check
    render = VideoRenderer.render
    messages = {name: getattr(QMessageBox, name) for name in ('critical','warning','information')}
    def require(value, message):
        if not value: raise AssertionError(message)
    def message(_parent, title, text, *_args, **_kwargs):
        faults.append(f'{title}: {text}'); return QMessageBox.Ok
    for name in messages: setattr(QMessageBox, name, message)
    def counted(self, operation, *args, **kwargs):
        if phase[0] != 'auto-generating':
            cad_calls.append({'phase': phase[0], 'operation': operation})
            raise AssertionError('Manual generation/editing/render called native CAD')
        return native(self, operation, *args, **kwargs)
    def no_path(*args, **kwargs):
        if phase[0] != 'auto-generating':
            cad_calls.append({'phase':phase[0], 'operation':'path_check'})
            raise AssertionError('Manual/editing/render called CAD path check')
        return path_check(*args, **kwargs)
    IsolatedCadWorker.call = counted; ConservativePathChecker.check = no_path
    def measured_render(self, *args, **kwargs):
        begin = time.monotonic(); result = render(self, *args, **kwargs)
        report['renders'].append(dict(mode=report['mode'], elapsed_sec=time.monotonic()-begin,
            steps=len(args[0].steps), result=asdict(result), path=str(result.path)))
        return result
    VideoRenderer.render = measured_render
    original_planned = window._planned
    def planned(result):
        mode = 'manual' if result.assembly_plan.source_algorithm.startswith('manual-') else 'auto'
        report['plans'][mode] = asdict(result)
        original_planned(result)
    window._planned = planned
    def checkpoint():
        sample=dict(phase=phase[0],status=window.video_page.progress_label.text())
        if not report['progress_samples'] or report['progress_samples'][-1]!=sample:
            report['progress_samples'].append(sample)
        destination.with_suffix('.progress.json').write_text(json.dumps(dict(
            phase=phase[0], elapsed_sec=time.monotonic()-started,
            status=window.statusBar().currentMessage(), progress=window.video_page.progress_label.text()),
            ensure_ascii=False), encoding='utf-8')
    def finish(ok, error=None):
        report.update(ok=ok, finished=True, phase=phase[0], elapsed_sec=time.monotonic()-started,
            forbidden_cad_calls=cad_calls, faults=faults,
            learning_status=learning_status(window.database,window.settings))
        if error: report.update(error=str(error), traceback=traceback.format_exc())
        destination.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
        IsolatedCadWorker.call = native; ConservativePathChecker.check = path_check
        VideoRenderer.render = render
        for name, method in messages.items(): setattr(QMessageBox, name, method)
        window.close(); app.quit()
    def button(text):
        return next(b for b in window.model_page.findChildren(QPushButton) if b.text() == text)
    def edit_and_confirm(mode):
        page = window.model_page; plan = page.plan
        generation = window.plans.load_original(plan.id).to_dict()
        require(not any(b.text() == '초안 저장' for b in page.findChildren(QPushButton)), 'Save draft button remains')
        require(not window.video_page.generate.isEnabled(), 'Unconfirmed generated draft can render')
        button('순서 확정').click()
        require(window.confirmation_id and window.video_page.generate.isEnabled(), 'Initial confirmation failed')
        groups = {g.id:g for g in window.import_result.snapshot.groups}
        index = next(i for i,s in enumerate(plan.steps) if not is_fastener(groups[s.group_id])
                     and s.geometry_status.value != 'USER_COLLISION_EXCEPTION')
        page.order.setCurrentRow(index); page._single()
        current = plan.steps[index]
        page.direction.setCurrentText('-X' if current.removal_direction != (-1,0,0) else '+X')
        page.camera.setCurrentText('RIGHT'); page.material.setPlainText(groups[current.group_id].display_name)
        page.caution.setPlainText(''); page.process.setPlainText('순서·방향 편집 후 영상 검증')
        require(not window.video_page.generate.isEnabled(), 'Pending property values can render')
        # Preview is a copy; it must restore opacity as well as camera/visibility.
        before = plan.to_dict(); opacity = {gid:a.GetProperty().GetOpacity() for gid,a in page.vtk_scene.actors.items()}
        page.step_preview_button.click(); page._preview_tick(); page.step_preview_button.click()
        require(plan.to_dict() == before, 'Preview modified stored plan')
        require(opacity == {gid:a.GetProperty().GetOpacity() for gid,a in page.vtk_scene.actors.items()}, 'Preview did not restore opacity')
        page._apply_step()
        page.order.clearSelection(); page.order.item(0).setSelected(True); page.order.item(1).setSelected(True)
        page.order.move_selection(min(4,page.order.count()-2))
        require(not window.video_page.generate.isEnabled(), 'Reordered plan can render before reconfirmation')
        require(window.plans.load_original(plan.id).to_dict() == generation, 'Original overwritten by edits')
        require(window.plans.load_current_draft(plan.project_id).to_dict() == plan.to_dict(), 'Applied edit not autosaved')
        button('순서 확정').click()
        require(window.video_page.generate.isEnabled(), 'Reconfirmation failed')
        report[mode+'_comparison'] = window.last_collection['comparison']
        report[mode+'_confirmation_id'] = window.confirmation_id
        report[mode+'_edited_plan'] = copy.deepcopy(plan.to_dict())
        timeline = build_timeline(plan, window.settings)
        segment = timeline.segments[0]
        frames = []
        for title,t in [('blink-on', segment.camera_end+.01), ('blink-off',segment.camera_end+.26),
                        ('moving',segment.highlight_end+.1), ('final',timeline.duration)]:
            state=scene_at(plan,t,window.settings,timeline);page.vtk_scene.apply(state)
            Image.fromarray(page.vtk_scene.rgb_array()).save(destination.with_name(destination.stem+f'-{mode}-{title}.png'))
            frames.append(dict(phase=title,highlight=state.highlight_alpha,
                opacities=sorted({a.GetProperty().GetOpacity() for a in page.vtk_scene.actors.values()})))
        report[mode+'_frames'] = frames
        window.tabs.setCurrentWidget(page)
        window.grab().save(str(destination.with_name(destination.stem+f'-{mode}-editor.png')))
        window.tabs.setCurrentWidget(window.video_page)
        return plan
    def decode(path):
        process=subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-v','error','-i',str(path),
            '-map','0:v:0','-f','null','-','-progress','pipe:1','-nostats'],capture_output=True,
            timeout=180,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        require(process.returncode == 0, 'Full video decode failed')
        frames=[int(line.split('=')[1]) for line in process.stdout.decode().splitlines() if line.startswith('frame=')]
        return max(frames)
    project = next(p for p in window.projects.list() if p.id == os.environ['PA2_SMOKE_PROJECT'])
    window._reopen(project)
    def poll():
        try:
            checkpoint()
            if faults: raise RuntimeError('; '.join(faults))
            if time.monotonic()-started > 7200: raise TimeoutError('v23 workflow exceeded 2 hours')
            if window.thread and window.thread.isRunning():
                QTimer.singleShot(400,poll); return
            if not window.model_page.isEnabled():
                QTimer.singleShot(400,poll); return
            page=window.model_page
            if phase[0] == 'opening':
                require(window.import_result is not None, 'Project reopen failed')
                report.update(group_count=len(window.import_result.snapshot.groups),
                    snapshot_id=window.import_result.snapshot.id,
                    exception_ids=list(page.exception_ids),
                    colored_bodies=sum(b.color_rgb is not None for b in window.import_result.assembly_scene.bodies),
                    import_wall_sec=time.monotonic()-started)
                from .ui_verify_selection import verify_selection
                report['selection'] = verify_selection(window,destination)
                require(report['selection']['ok'], 'Selection test failed')
                report['ui_contracts'] = dict(manual_button=page.manual_generate.isVisible(),
                    auto_button=page.auto_generate.isVisible(),thn_logo=not window.thn_logo.pixmap().isNull(),
                    learning_action=any(a.text()=='학습 현황' for a in window.findChildren(__import__('PySide6.QtGui',fromlist=['QAction']).QAction)),
                    viewport_tools=sorted(page.viewport_buttons),speed_4x=page.speed.findText('4')>=0)
                require(all(report['ui_contracts'][k] for k in ('manual_button','auto_button','thn_logo','learning_action','speed_4x')), 'Integrated UI feature missing')
                report['mode']='manual';phase[0]='manual-generating';report['manual_started']=time.monotonic()
                page.manual_generate.click()
            elif phase[0] == 'manual-generating':
                require('manual' in report['plans'], 'Manual generation failed')
                report['manual_wall_sec']=time.monotonic()-report.pop('manual_started')
                plan=edit_and_confirm('manual')
                require(len(plan.steps)==report['group_count']-1, 'Manual draft incomplete')
                require(report['plans']['manual']['metrics']['native_path_calls']==0, 'Manual path tests ran')
                if os.environ.get('PA2_V23_PREFLIGHT') == '1': finish(True); return
                phase[0]='manual-rendering'; window.video_page.generate.click()
            elif phase[0] == 'manual-rendering':
                require(len(report['renders'])==1, 'Manual video missing')
                rendered=report['renders'][-1]
                rendered['decoded_frames']=decode(rendered['path'])
                require(rendered['decoded_frames']==rendered['result']['frame_count'], 'Manual frame mismatch')
                report['mode']='auto';phase[0]='auto-generating';report['auto_started']=time.monotonic()
                window.tabs.setCurrentWidget(page);page.auto_generate.click()
            elif phase[0] == 'auto-generating':
                require('auto' in report['plans'], 'Auto generation failed')
                report['auto_wall_sec']=time.monotonic()-report.pop('auto_started')
                plan=edit_and_confirm('auto')
                require(len(plan.steps)==report['group_count']-1, 'Auto draft incomplete')
                phase[0]='auto-rendering';window.video_page.generate.click()
            elif phase[0] == 'auto-rendering':
                require(len(report['renders'])==2, 'Auto edited video missing')
                rendered=report['renders'][-1];rendered['decoded_frames']=decode(rendered['path'])
                require(rendered['decoded_frames']==rendered['result']['frame_count'], 'Auto frame mismatch')
                report['full_resolution']=all(r['decoded_frames']>0 for r in report['renders'])
                window.video_page.rate.setCurrentText('2×')
                report['video_playback_rate']=window.video_page.player.playbackRate()
                report['final_confirmation_preserved']=window.plans.matches_confirmation(window.current_plan,window.confirmation_id)
                phase[0]='reopening-final';window._reopen(project)
            elif phase[0] == 'reopening-final':
                require(window.plans.matches_confirmation(window.current_plan,window.confirmation_id), 'Reopen lost confirmation')
                report['reopened_final_steps']=len(window.current_plan.steps)
                require(not cad_calls, 'Unexpected additional CAD calls')
                finish(True);return
            QTimer.singleShot(400,poll)
        except Exception as exc:
            finish(False,exc)
    QTimer.singleShot(400,poll);app.exec()
    return 0 if report.get('ok') else 1
