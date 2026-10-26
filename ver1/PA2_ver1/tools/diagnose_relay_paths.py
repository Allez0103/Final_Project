"""Diagnose only relays after an interrupted first-branch run; never generates a plan."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import re
import sqlite3
import time
import multiprocessing

from diagnose_unknowns import load_inputs
from pa2.cad.brep_io import read_shape
from pa2.cad.directions import GLOBALS
from pa2.cad.isolated import NativeCadSession
from pa2.cad.path_check import exit_distance, state_key
from pa2.domain.models import Bounds
from pa2.jobs.isolated import NativeCallError
from pa2.planning.priority import ExteriorPriorityProvider, is_fastener
from pa2.settings.config import AppSettings


def reconstruct_prefix(lines, groups):
    by_name={g.display_name:g.id for g in groups.values()}
    removed=[by_name['LV CONT']]
    skeleton=[]
    candidate=None
    virtual=None
    for line in lines:
        match=re.match(r'\[planning\] 분해 경로 확인 · (\d+)/64개 · (.+) · 후보 (\d+)',line)
        if match:
            count,name,index=match.groups()
            if int(count)!=len(removed):
                raise ValueError('Log is not a simple first branch; cannot reconstruct actual state reliably')
            candidate=(int(index),by_name[name])
        match=re.match(r'\[planning\] 실제 후보 (\d+) · .* · 경로 확인 · ',line)
        if match:
            assert candidate and candidate[0]==int(match.group(1))
            assert candidate[1] not in removed
            removed.append(candidate[1])
        match=re.match(r'\[skeleton\] 일반 부품 초안\(체결물 제외\) · \d+/\d+개 · (.+) · 가상 후보 (\d+)',line)
        if match:virtual=(int(match.group(2)),by_name[match.group(1)])
        match=re.match(r'\[skeleton\] 가상 후보 (\d+) · .* · 경로 확인 · ',line)
        if match:
            assert virtual and virtual[0]==int(match.group(1))
            assert virtual[1] not in skeleton
            skeleton.append(virtual[1])
    return removed,skeleton


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--report',type=Path,required=True)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--log',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    report=json.loads(args.report.read_text(encoding='utf-8'))
    with sqlite3.connect((args.root/'database/pa2-dev.sqlite3').resolve().as_uri()+'?mode=ro',uri=True) as db:
        sid=db.execute('select current_snapshot_id from projects where id=?',(report['project_id'],)).fetchone()[0]
    report['planning']={'plan':{'input_snapshot_id':sid}}
    groups,files=load_inputs(report,args.root)
    removed,skeleton=reconstruct_prefix(args.log.read_text(encoding='utf-8').splitlines(),groups)
    names={gid:g.display_name for gid,g in groups.items()}
    settings=AppSettings(**report['settings'])
    resolved=settings.resolved_for_diagonal(Bounds.union([g.bounds for g in groups.values()]).diagonal)
    exceptions={gid for gid in groups if names[gid]=='LV CONT'}
    actual=set(groups)-set(removed)
    virtual={gid for gid,g in groups.items() if not is_fastener(g)}-exceptions-set(skeleton)
    output={'scope':'Relay-only diagnostic; full planning stopped by user; no further removal steps.',
        'snapshot_id':sid,'source_report':str(args.report),'source_log':str(args.log),
        'interrupted_prefix_steps':len(removed),'prefix_reconstruction':'First linear branch, checked for monotonic step counts; not a persisted final plan.',
        'removed_prefix_names':[names[g] for g in removed],
        'skeleton_names':[names[g] for g in skeleton],
        'repair_policy':report['repair_policy'],'collision_epsilon_mm':resolved['geometry_epsilon_mm'],
        'candidate_timeout_sec':180,'diagnostic_budget_sec':1200,'results':[]}
    shapes={bid:read_shape(path) for bid,path in files.items()}
    started=time.monotonic();deadline=started+1200
    def save():
        output['elapsed_sec']=time.monotonic()-started
        args.output.write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    save()
    relays=sorted((g for g in groups.values() if g.display_name.startswith('RLY-KET400')),key=lambda g:g.id)
    jobs=args.output.parent/'relay-diagnostic-jobs'
    with NativeCadSession(list(groups.values()),shapes,native_timeout=120,jobs_dir=jobs) as worker:
        for label,remaining in [('actual_interrupted_prefix',actual),('no_fasteners_after_skeleton',virtual)]:
            for relay in relays:
                obstacles=[groups[g] for g in sorted(remaining-{relay.id})]
                directions=ExteriorPriorityProvider().ordered_directions(relay,obstacles,GLOBALS)
                for direction in directions:
                    if time.monotonic()>=deadline:
                        output['diagnostic_budget_exhausted']=True;save();return
                    travel=exit_distance(relay.bounds,[g.bounds for g in obstacles],direction,resolved['exit_clearance_mm'])
                    print(f'CHECK {label} {relay.display_name} {direction}',flush=True)
                    try:
                        result=worker.call('path',{'moving':relay,'obstacles':obstacles,
                            'direction':direction,'travel':travel,'remaining':remaining,
                            'epsilon':resolved['geometry_epsilon_mm'],'min_interval':resolved['path_min_interval_mm'],
                            'bolt_initial_overlap_enabled':settings.bolt_initial_overlap_enabled,
                            'initial_overlap_region_enabled':settings.initial_overlap_region_enabled,
                            'initial_overlap_decrease_enabled':settings.initial_overlap_decrease_enabled,
                            'timeout':180},deadline=min(deadline,time.monotonic()+180))
                        row=asdict(result)
                    except NativeCallError as exc:
                        row={'group_id':relay.id,'direction':direction,'travel_mm':travel,'state_key':state_key(remaining),
                             'decision':'UNKNOWN','reason_code':'DIAGNOSTIC_NATIVE_ERROR','obstacle_ids':[],
                             'evidence':{'error':str(exc)}}
                    row.update(scenario=label,name=relay.display_name,
                        obstacle_names=[names[g] for g in row['obstacle_ids']])
                    for detail in row['evidence'].get('pair_diagnostics',[]):
                        detail['obstacle_name']=names.get(detail.get('obstacle_id'))
                    output['results'].append(row);save()
                    print(f"RESULT {row['decision']} {row['obstacle_names']} {row.get('elapsed_sec',0):.1f}s",flush=True)
    output['diagnostic_budget_exhausted']=False
    save()


if __name__=='__main__':
    multiprocessing.freeze_support()
    main()
