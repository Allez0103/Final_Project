"""Persist/reopen a recorded draft, render it, export and decode the entire MP4."""
from __future__ import annotations

import argparse
from dataclasses import asdict, replace
import json
from pathlib import Path
import subprocess
import time

import imageio_ffmpeg

from pa2.application.plan_service import PlanService
from pa2.cli import _runtime
from pa2.domain.models import Plan, PlanStep, PlanningStatus, GeometryStatus
from pa2.rendering.scene import build_timeline, scene_at
from pa2.settings.config import AppSettings
from pa2.video.renderer import VideoRenderer
from pa2.rendering.vtk_scene import VtkScene


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--report', type=Path, required=True)
    p.add_argument('--root', type=Path, required=True)
    p.add_argument('--output-dir', type=Path, required=True)
    p.add_argument('--probe', action='store_true', help='Short render preflight without saving or confirming the source project')
    p.add_argument('--no-save', action='store_true', help='Full render without changing the source draft or confirmation')
    p.add_argument('--version-label',default='v12')
    p.add_argument('--encoder',choices=['auto','libx264','h264_nvenc','h264_qsv','h264_amf'])
    p.add_argument('--edit-case',action='store_true',help='Swap general stages and reverse one direction before rendering, without CAD revalidation')
    args=p.parse_args()
    args.output_dir.mkdir(parents=True,exist_ok=True)
    report=json.loads(args.report.read_text(encoding='utf-8'))
    raw=report['planning']['plan']
    steps=[]
    for item in raw['steps']:
        item=dict(item); item['geometry_status']=GeometryStatus(item['geometry_status'])
        item['final_transform']=tuple(item['final_transform'])
        steps.append(PlanStep(**item))
    raw=dict(raw); raw['steps']=steps; raw['status']=PlanningStatus(raw['status'])
    plan=Plan(**raw)
    edit_details=None
    if args.edit_case:
        import uuid
        before=[s.group_id for s in plan.steps]
        indices=[i for i,s in enumerate(plan.steps) if s.geometry_status not in (GeometryStatus.FASTENER_ASSIGNED,GeometryStatus.USER_COLLISION_EXCEPTION)]
        if len(indices)<2:raise ValueError('순서 변경 시험에 필요한 일반 부품이 부족합니다.')
        first,last=indices[0],indices[-1]
        plan.steps[first],plan.steps[last]=plan.steps[last],plan.steps[first]
        changed=plan.steps[first]; old_direction=changed.removal_direction
        changed.removal_direction=tuple(-v for v in changed.removal_direction)
        changed.assembly_direction=tuple(-v for v in changed.removal_direction)
        plan.id=str(uuid.uuid4()); plan.user_modified=True
        for i,s in enumerate(plan.steps,1):s.step_index=i
        edit_details={'original_order':before,'edited_order':[s.group_id for s in plan.steps],
                      'direction_changed_group':changed.group_id,'old_removal_direction':old_direction,
                      'new_removal_direction':changed.removal_direction}
    if args.probe:
        plan.steps=plan.steps[:2]
        plan.status=PlanningStatus.REVIEW_REQUIRED
    partial=len(plan.steps)<len(plan.group_ids)-1
    plan.validate(allow_partial=partial)
    layout,db,projects,imports=_runtime(args.root)
    imported=imports.reopen(plan.project_id)
    if args.probe or args.no_save:
        loaded=plan
        confirmation='render-preflight' if args.probe else 'read-only-render'
    else:
        plans=PlanService(db)
        plans.save_draft(plan)
        preview=plans.refresh_preview(plan)
        confirmation=plans.confirm(preview,allow_partial=partial)
        loaded=plans.load_current_draft(plan.project_id)
        assert loaded.to_dict()==preview.to_dict()
    settings=AppSettings(**report['settings'])
    if args.encoder:settings=replace(settings,video_encoder=args.encoder)
    if args.probe:
        settings=replace(settings,highlight_sec=.1,assembly_move_sec=.2,camera_180_sec=.3,final_hold_sec=.2)
    timeline=build_timeline(loaded,settings)
    final=scene_at(loaded,timeline.duration,settings)
    assert final.visible_group_ids==set(plan.group_ids)
    assert all(v==(0,0,0) for v in final.translations.values())
    root=Path(__file__).resolve().parents[1]
    renderer=VideoRenderer(settings,root/'assets/video_template_v1.json',root/'assets/thn_logo.png')
    # A manual video render must not invoke either the native path worker or
    # the in-process checker. Fail this run if a future refactor adds one.
    from pa2.jobs.isolated import IsolatedCadWorker
    from pa2.cad.path_check import ConservativePathChecker
    cad_calls=[]
    old_native_call=IsolatedCadWorker.call
    old_check=ConservativePathChecker.check
    def forbidden_check(*values,**kwargs):
        cad_calls.append('path_check'); raise AssertionError('Video rendering invoked CAD revalidation')
    IsolatedCadWorker.call=forbidden_check
    ConservativePathChecker.check=forbidden_check
    managed=args.output_dir/'managed-preflight.mp4' if args.probe or args.no_save else layout.projects/plan.project_id/'videos'/f'{confirmation}.mp4'
    started=time.monotonic()
    framing=[]; highlights=[]
    orientation_audit={'maximum_frame_rotation_deg':0.0}; previous_basis=[None]
    original_apply=VtkScene.apply
    def observed_apply(scene,frame,*args,**kwargs):
        original_apply(scene,frame,*args,**kwargs)
        camera=scene.renderer.GetActiveCamera()
        framing.append((camera.GetFocalPoint(),camera.GetDistance(),camera.GetViewAngle()))
        highlights.append((frame.time_sec,frame.step_index,frame.highlight_alpha,frame.active_group_id))
        import math
        from pa2.rendering.scene import cross
        direction=frame.camera.view_direction; up=frame.camera.view_up
        basis=(cross(direction,up),up,direction)
        if previous_basis[0] is not None:
            trace=sum(sum(a*b for a,b in zip(x,y)) for x,y in zip(previous_basis[0],basis))
            angle=math.degrees(math.acos(max(-1,min(1,(trace-1)/2))))
            orientation_audit['maximum_frame_rotation_deg']=max(orientation_audit['maximum_frame_rotation_deg'],angle)
        previous_basis[0]=basis
    VtkScene.apply=observed_apply
    try:
        result=renderer.render(loaded,imported.assembly_scene,imported.snapshot.groups,managed,
            vehicle_name='KD1',product_name='HVJB',project_name='부분 조립 초안' if partial else '전체 조립 초안',
            progress=lambda a,b: print(f'VIDEO {a}/{b} elapsed={time.monotonic()-started:.1f}s',flush=True))
    finally:
        VtkScene.apply=original_apply
        IsolatedCadWorker.call=old_native_call
        ConservativePathChecker.check=old_check
    assert framing
    reference=framing[0]
    max_focus_delta=max(max(abs(a-b) for a,b in zip(row[0],reference[0])) for row in framing)
    max_distance_delta=max(abs(row[1]-reference[1]) for row in framing)
    assert max_focus_delta<1e-9 and max_distance_delta<1e-8
    assert max(abs(row[2]-reference[2]) for row in framing)<1e-9
    if settings.camera_mode=='smooth' and not args.probe:assert orientation_audit['maximum_frame_rotation_deg']<15
    highlight_audit=[]
    for step,segment in zip(loaded.steps,timeline.segments):
        before=[alpha for t,index,alpha,active in highlights if index==step.step_index and active==step.group_id
                and segment.camera_end<t<segment.highlight_end]
        motion=[alpha for t,index,alpha,active in highlights if index==step.step_index and active==step.group_id
                and segment.highlight_end<t<segment.move_end]
        if settings.highlight_sec>=.5:assert before and min(before)==0 and max(before)>0
        assert motion and min(motion)>0
        highlight_audit.append(dict(step_index=step.step_index,pre_move_on_off=bool(before and min(before)==0 and max(before)>0),
                                    motion_highlight_maintained=min(motion)>0))
    elapsed=time.monotonic()-started
    exported=renderer.export(result.path,args.output_dir/(f'PA2_partial_assembly_{args.version_label}.mp4' if partial else f'PA2_assembly_{args.version_label}.mp4'))
    ffmpeg=imageio_ffmpeg.get_ffmpeg_exe()
    metadata=imageio_ffmpeg.read_frames(str(exported))
    info=next(metadata); metadata.close()
    assert tuple(info['size'])==(1920,1080) and abs(info['fps']-30)<.001
    decoded=subprocess.run([ffmpeg,'-hide_banner','-loglevel','error','-nostats','-progress','pipe:1',
        '-i',str(exported),'-f','null','-'],
        capture_output=True,text=True,timeout=600,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    assert decoded.returncode==0, decoded.stderr
    decoded_frames=[int(line.split('=',1)[1]) for line in decoded.stdout.splitlines() if line.startswith('frame=')]
    assert decoded_frames and decoded_frames[-1]==result.frame_count, (decoded_frames,result.frame_count)
    assert abs(info['duration']-result.duration_sec)<.05
    samples=[0., result.duration_sec*.5,max(0,(result.frame_count-1)/settings.video_fps)]
    for i,position in enumerate(samples):
        subprocess.run([ffmpeg,'-hide_banner','-loglevel','error','-ss',str(position),'-i',str(exported),
            '-frames:v','1',str(args.output_dir/f'frame_{i}.png')],check=True,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        assert (args.output_dir/f'frame_{i}.png').is_file()
    if timeline.segments and not args.probe:
        segment=timeline.segments[0]
        visual_samples={'highlight_on':segment.camera_end+.1,'highlight_off':segment.camera_end+.3,
                        'moving':(segment.highlight_end+segment.move_end)/2,'seated':segment.move_end+.02}
        for label,position in visual_samples.items():
            subprocess.run([ffmpeg,'-hide_banner','-loglevel','error','-ss',str(position),'-i',str(exported),
                '-frames:v','1',str(args.output_dir/f'{label}.png')],check=True,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    output={'ok':True,'partial':partial,'steps':len(loaded.steps),'moving_groups':len(plan.group_ids)-1,
        'confirmation_id':confirmation,'render_elapsed_sec':elapsed,'path':str(exported.resolve()),
        'managed_path':str(managed.resolve()),'bytes':exported.stat().st_size,
        'checksum':result.checksum,'duration_sec':result.duration_sec,'frames':result.frame_count,
        'encoder':result.encoder,'decoded_metadata':info,'full_decode_exit_code':decoded.returncode,
        'encoder_benchmarks':result.encoder_benchmarks,'camera_orientation_audit':orientation_audit,
        'encoder_fallback':result.encoder_fallback,
        'decoded_frame_count':decoded_frames[-1],
        'final_scene_all_groups_visible':True,'final_scene_all_transforms_zero':True,
        'plan_save_reopen_equal':None if args.no_save else not args.probe,'preflight_only':args.probe,
        'source_draft_not_saved':args.no_save,
        'planning_elapsed_sec':report['planning']['metrics']['elapsed_sec'],
        'planning_status':report['planning']['status'],
        'verified_path_steps':report['planning']['metrics'].get('verified_path_steps'),
        'unresolved_general_steps':report['planning']['metrics'].get('unresolved_general_steps'),
        'fixed_base_camera':True,'blink_highlight_before_motion':True,'highlight_during_motion':True,
        'empty_cautions':all(not s.caution_text for s in loaded.steps),
        'materials_present':all(s.material_text for s in loaded.steps)}
    output['manual_edit']=edit_details
    output['cad_revalidation_calls']=len(cad_calls)
    output['rendered_order']=[s.group_id for s in loaded.steps]
    output['camera_frame_audit']={'frames':len(framing),'focal_point':reference[0],
        'distance':reference[1],'view_angle':reference[2],'max_focus_delta':max_focus_delta,
        'max_distance_delta':max_distance_delta}
    output['highlight_stage_audit']=highlight_audit
    (args.output_dir/'video-validation.json').write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(output,ensure_ascii=False,indent=2),flush=True)


if __name__=='__main__':
    main()
