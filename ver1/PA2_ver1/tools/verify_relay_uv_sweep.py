"""Replay only the two recorded relay +Z UNKNOWN paths, preserving their state.

Reads v14 project/cache; writes diagnostic reports only. No plan or video edits.
"""
import argparse
from collections import Counter
from dataclasses import asdict
import hashlib
import json
import multiprocessing
from pathlib import Path
import time

from diagnose_unknowns import load_inputs
from pa2.cad import sweep
from pa2.cad.brep_io import read_shape
from pa2.cad.isolated import NativeCadSession
from pa2.cad.path_check import ConservativePathChecker, state_key
from pa2.cad.prepare import prepare
from pa2.cad.shapes import compound
from pa2.domain.models import Bounds
from pa2.jobs.isolated import NativeCallError
from pa2.settings.config import AppSettings


def audit_faces(group,shapes,epsilon,travel):
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS
    moving,repair,valid=prepare(compound([shapes[b] for b in group.body_ids]),epsilon,lambda _:None)
    assert valid
    ex=TopExp_Explorer(moving,TopAbs_FACE);index=0;rows=[]
    while ex.More():
        face=TopoDS.Face(ex.Current());index+=1;ex.Next()
        if index not in (22,1378):continue
        adaptor=BRepAdaptor_Surface(face,True)
        assert 'BSpline' in str(adaptor.GetType())
        counts=Counter()
        records=sweep.enclosures(face,adaptor,(0,0,1),travel,lambda name:counts.update([name]))
        rows.append(dict(face_index=index,bounds=asdict(sweep.bounds(face)),
            uv=list(sweep.BRepTools.UVBounds_s(face)),constructed=records is not None,
            enclosure_count=len(records) if records else 0,
            exact_count=sum(exact for _,_,exact in records) if records else 0,
            activity_counts=dict(counts)))
    return dict(input_valid=valid,repair=repair,faces=rows)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,default=Path('runtime-data/native-validation/relay-uv-v15.json'))
    parser.add_argument('--diagnostic-timeout-sec',type=float,
                        help='Diagnostic-only candidate budget; application settings remain unchanged.')
    args=parser.parse_args()
    report_path=Path('runtime-data/native-validation/planning-v14-cache-final.json')
    comparison_path=Path('runtime-data/native-validation/v14-comparison.json')
    report=json.loads(report_path.read_text(encoding='utf-8'))
    comparison=json.loads(comparison_path.read_text(encoding='utf-8'))
    root=Path('runtime-data/end-to-end-v14-cache-final')
    groups,files=load_inputs(report,root)
    run=report['planning'];prefix=set(run['plan']['group_ids'])-set(run['removal_order'][:run['metrics']['checked_prefix_steps']])
    settings=AppSettings(**report['settings'])
    candidate_timeout=args.diagnostic_timeout_sec or settings.candidate_timeout_sec
    resolved=settings.resolved_for_diagonal(Bounds.union([g.bounds for g in groups.values()]).diagonal)
    tasks=[]
    for target in comparison['prefix_failure_states']:
        if not target['name'].startswith('RLY-KET400'):continue
        observed=target['states'][-1]
        old=next(p for p in observed['paths'] if p['decision']=='UNKNOWN' and p['direction']==[0,0,1])
        remaining=prefix-set(observed['omitted_fastener_ids'])
        assert state_key(remaining)==old['state_key']
        assert not any(groups[g].display_name=='LV CONT' for g in remaining)
        tasks.append((target,old,remaining,observed['omitted_fastener_ids']))
    assert len(tasks)==2
    monitored=[report_path,comparison_path,root/'database/pa2-dev.sqlite3']+[Path(p) for p in files.values()]
    hashes=lambda:{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in monitored}
    before=hashes()
    shapes={b:read_shape(p) for b,p in files.items()}
    output=dict(scope='Two recorded relay +Z paths only, all remaining obstacles; no planning/support/video rerun.',
        source_report=str(report_path),path_policy_version=ConservativePathChecker.VERSION,
        unchanged_settings=report['settings'],resolved_settings=resolved,
        effective_diagnostic_candidate_timeout_sec=candidate_timeout,results=[])
    args.output.parent.mkdir(parents=True,exist_ok=True)
    save=lambda:args.output.write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
    save()
    for target,old,remaining,omitted in tasks:
        group=groups[target['group_id']]
        audit=audit_faces(group,shapes,resolved['geometry_epsilon_mm'],old['travel_mm'])
        row=dict(name=group.display_name,old_path=old,remaining_group_ids=sorted(remaining),
            omitted_fastener_names=[groups[g].display_name for g in omitted],face_audit=audit)
        output['results'].append(row);save()
        print(f"CHECK {group.display_name}: {len(remaining)-1} obstacles; faces {[f['enclosure_count'] for f in audit['faces']]}",flush=True)
        started=time.monotonic()
        # Separate worker for each relay: no cross-case native cache reuse.
        with NativeCadSession(list(groups.values()),shapes,native_timeout=settings.native_operation_timeout_sec,
                              jobs_dir=args.output.parent/'relay-uv-v15-jobs') as worker:
            try:
                result=worker.call('path',dict(moving=group,obstacles=[groups[g] for g in sorted(remaining-{group.id})],
                    direction=tuple(old['direction']),travel=old['travel_mm'],remaining=remaining,
                    epsilon=resolved['geometry_epsilon_mm'],min_interval=resolved['path_min_interval_mm'],
                    bolt_initial_overlap_enabled=settings.bolt_initial_overlap_enabled,
                    initial_overlap_region_enabled=settings.initial_overlap_region_enabled,
                    initial_overlap_decrease_enabled=settings.initial_overlap_decrease_enabled,
                    timeout=candidate_timeout),deadline=time.monotonic()+candidate_timeout)
                row['new_path']=asdict(result)
                assert result.state_key==old['state_key']
            except NativeCallError as exc:
                row['new_path']=dict(decision='UNKNOWN',reason_code='NATIVE_ERROR',error=str(exc))
        row['wall_elapsed_sec']=time.monotonic()-started
        save();print(json.dumps(dict(name=row['name'],result=row['new_path']),ensure_ascii=False),flush=True)
    output['inputs_and_existing_results_unchanged']=hashes()==before
    assert output['inputs_and_existing_results_unchanged']
    save()


if __name__=='__main__':
    multiprocessing.freeze_support()
    main()
