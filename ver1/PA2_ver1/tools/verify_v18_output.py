"""Check saved edits were preserved and the new movie approaches from head side."""
import json,subprocess
from pathlib import Path
import imageio_ffmpeg
from pa2.storage.database import Database
from pa2.storage.layout import DataLayout
from pa2.application.plan_service import PlanService
from pa2.application.project_service import ProjectService
from pa2.domain.models import Plan,PlanStep,PlanningStatus,GeometryStatus
from pa2.rendering.scene import build_timeline,scene_at
from pa2.settings.config import AppSettings


def main():
    folder=Path('runtime-data/native-validation')
    read=lambda name:json.loads((folder/name).read_text(encoding='utf-8'))
    source=read('planning-v17-final.json'); report=read('planning-v18-fastener-directions.json')
    ui=read('ui-review-v17-final.json'); video=read('video-v18-fastener-directions/video-validation.json')
    directions=read('fastener-direction-v18.json')
    db=Database(DataLayout(Path('runtime-data/end-to-end-v17-final')))
    plans=PlanService(db)
    project=next(p for p in ProjectService(db).list() if p.id==source['project_id'])
    draft=plans.load_current_draft(project.id)
    original=plans.load_confirmation(read('video-v17-final/video-validation.json')['confirmation_id'])
    checks=dict(saved_manual_order_unchanged=[s.group_id for s in draft.steps]==ui['edited_order'],
        saved_manual_direction_unchanged=list(draft.steps[0].removal_direction)==ui['new_direction'],
        original_confirmation_unchanged=all(list(s.removal_direction)==p['removal_direction'] and s.group_id==p['group_id']
            for s,p in zip(original.steps,source['planning']['plan']['steps'])),
        rendered_all_steps=video['steps']==63 and video['decoded_frame_count']==video['frames'],
        no_video_cad_revalidation=video['cad_revalidation_calls']==0,
        no_contact_or_path_checks=directions['contact_or_boolean_calls']==directions['native_path_calls']==0)
    raw=dict(report['planning']['plan'])
    raw['steps']=[PlanStep(**{**s,'geometry_status':GeometryStatus(s['geometry_status'])}) for s in raw['steps']]
    raw['status']=PlanningStatus(raw['status']); plan=Plan(**raw)
    settings=AppSettings(**report['settings']); timeline=build_timeline(plan,settings)
    bolts={r['group_id']:r for r in directions['rows'] if r['type']=='BOLT'}
    audit=[]
    for step,segment in zip(plan.steps,timeline.segments):
        if step.group_id not in bolts:continue
        row=bolts[step.group_id]; head=row['hint']['head_direction']
        t0=segment.highlight_end+(segment.move_end-segment.highlight_end)*.25
        t1=segment.highlight_end+(segment.move_end-segment.highlight_end)*.75
        p0=scene_at(plan,t0,settings,timeline=timeline).translations[step.group_id]
        p1=scene_at(plan,t1,settings,timeline=timeline).translations[step.group_id]
        assert sum(a*b for a,b in zip(p0,head))>0
        assert sum((a-b)*c for a,b,c in zip(p0,p1,head))>0
        assert sum(a*b for a,b in zip(step.assembly_direction,head))<-.999999
        audit.append(dict(name=row['name'],head_side_start=True,moves_toward_assembled_position=True))
    checks['all_37_bolts_approach_from_head_side']=len(audit)==37
    changed=next(r for r in directions['rows'] if r['changed'])
    index=next(i for i,s in enumerate(plan.steps) if s.group_id==changed['group_id'])
    segment=timeline.segments[index]
    for label,position in [('head-side-motion',(segment.highlight_end+segment.move_end)/2),
                           ('head-side-seated',segment.move_end-.01)]:
        destination=folder/'video-v18-fastener-directions'/(label+'.png')
        subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-hide_banner','-loglevel','error','-y',
            '-ss',str(position),'-i',video['path'],'-frames:v','1',str(destination)],
            check=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    result=dict(ok=all(checks.values()),checks=checks,bolt_motion_audit=audit,
        inspected_changed_bolt=changed['name'])
    (folder/'saved-plan-and-motion-v18.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='bolt_motion_audit'},ensure_ascii=False))
    if not result['ok']:raise AssertionError('v18 verification failed')


if __name__=='__main__':main()
