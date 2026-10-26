"""Independent breadth-first diagnosis at a retained prefix's exact final state.

This never adds unproved removal steps to the saved plan. Per-direction limits
and limited directions are explicitly recorded as UNKNOWN/untested coverage.
"""
from __future__ import annotations
import argparse
from collections import Counter
from dataclasses import asdict
import json
import multiprocessing
from pathlib import Path
import time

from pa2.cli import _runtime
from pa2.cad.isolated import NativeCadSession
from pa2.cad.path_check import exit_distance, state_key
from pa2.cad.directions import GLOBALS
from pa2.jobs.isolated import NativeCallError
from pa2.planning.priority import ExteriorPriorityProvider
from pa2.settings.config import AppSettings


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--report',type=Path,required=True)
    p.add_argument('--root',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--budget',type=int,default=1200)
    p.add_argument('--directions',type=int,default=2)
    p.add_argument('--candidate-timeout',type=int,default=30)
    args=p.parse_args()
    report=json.loads(args.report.read_text(encoding='utf-8')); run=report['planning']; plan=run['plan']
    layout,db,projects,imports=_runtime(args.root)
    imported=imports.reopen(report['project_id'])
    groups={g.id:g for g in imported.snapshot.groups}
    remaining=set(plan['group_ids'])-set(run['removal_order']); key=state_key(remaining)
    settings=AppSettings(**report['settings']); provider=ExteriorPriorityProvider()
    resolved=settings.resolved_for_diagonal(imported.assembly_scene.bounds.diagonal)
    started=time.monotonic(); deadline=started+args.budget
    output={'source_report':str(args.report),'state_key':key,'remaining_ids':sorted(remaining),
        'budget_sec':args.budget,'directions_per_group':args.directions,
        'candidate_timeout_sec':args.candidate_timeout,'groups':[],
        'recorded_results_reused':0,'new_path_requests':0,
        'note':'Final-state breadth audit. Existing conclusive same-state+motion records are reused; untested/UNKNOWN paths are probed with the stated shorter budget. No support proof or extra sequence steps. Untested directions are not BLOCKED.'}
    recorded={(q['group_id'],tuple(q['direction']),q['travel_mm']):q for q in run['paths'] if q['state_key']==key}
    def save():
        output['elapsed_sec']=time.monotonic()-started
        args.output.write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
    with NativeCadSession(imported.snapshot.groups,imported.assembly_scene.shapes,
                          native_timeout=args.candidate_timeout,jobs_dir=layout.jobs) as worker:
        # Cheap groups first to retain broad coverage before expensive curves.
        ranked=sorted(remaining-{plan['base_group_id']}, key=lambda gid:(len(groups[gid].body_ids),groups[gid].display_name))
        for i,gid in enumerate(ranked,1):
            row={'group_id':gid,'name':groups[gid].display_name,'paths':[]}
            output['groups'].append(row)
            if time.monotonic()>=deadline:
                row['coverage']='NOT_TESTED_BUDGET'; save(); continue
            obstacles=[groups[o] for o in sorted(remaining-{gid})]
            try:
                directions=worker.call('directions',{'group_id':gid,'max_directions':settings.max_directions,
                    'merge_angle_deg':settings.direction_merge_angle_deg},deadline=deadline)
            except NativeCallError:
                directions=GLOBALS
            directions=provider.ordered_directions(groups[gid],obstacles,directions)
            row['available_directions']=len(directions)
            for direction in directions[:args.directions]:
                if time.monotonic()>=deadline: break
                travel=exit_distance(groups[gid].bounds,[o.bounds for o in obstacles],direction,resolved['exit_clearance_mm'])
                previous=recorded.get((gid,tuple(direction),travel))
                if previous and previous['decision']!='UNKNOWN':
                    row['paths'].append(previous)
                    output['recorded_results_reused']+=1
                    continue
                output['new_path_requests']+=1
                try:
                    result=worker.call('path',{'moving':groups[gid],'obstacles':obstacles,
                        'direction':direction,'travel':travel,'remaining':remaining,
                        'epsilon':resolved['geometry_epsilon_mm'],'min_interval':resolved['path_min_interval_mm'],
                        'bolt_initial_overlap_enabled':settings.bolt_initial_overlap_enabled,
                        'initial_overlap_region_enabled':settings.initial_overlap_region_enabled,
                        'initial_overlap_decrease_enabled':settings.initial_overlap_decrease_enabled,
                        'timeout':args.candidate_timeout},deadline=min(deadline,time.monotonic()+args.candidate_timeout))
                    row['paths'].append(asdict(result))
                except NativeCallError as exc:
                    row['paths'].append({'group_id':gid,'state_key':key,'direction':direction,'travel_mm':travel,
                        'decision':'UNKNOWN','reason_code':'DIAGNOSTIC_NATIVE_ERROR','obstacle_ids':[],
                        'evidence':{'error':str(exc)}})
            row['coverage']='LIMITED_DIRECTIONS'
            print(f"AUDIT {i}/{len(ranked)} {row['name']} {dict(Counter(q['decision'] for q in row['paths']))}",flush=True)
            save()
    save()


if __name__=='__main__':
    multiprocessing.freeze_support(); main()
