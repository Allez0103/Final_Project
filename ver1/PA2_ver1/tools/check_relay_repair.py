"""Check relay input preparation only, against read-only managed snapshot files."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
import multiprocessing as mp
from pathlib import Path
import sqlite3
import time

from diagnose_unknowns import load_inputs


def check_group(group, files, epsilon, connection):
    from OCP.BRepCheck import BRepCheck_Analyzer
    from pa2.cad.brep_io import read_shape
    from pa2.cad.path_check import ConservativePathChecker
    from pa2.cad.prepare import _properties
    from pa2.cad.shapes import compound

    try:
        started=time.monotonic()
        shape=compound([read_shape(files[bid]) for bid in group.body_ids])
        before=_properties(shape)
        events=[]
        checker=ConservativePathChecker(epsilon,epsilon,120,activity=events.append)
        prepared_group,prepared,evidence,accepted=checker._prepare_group(group,shape)
        after=_properties(prepared)
        source_after=_properties(shape)
        old_limits_pass=(BRepCheck_Analyzer(prepared,True).IsValid()
            and after[1]<=epsilon
            and abs(after[0]-before[0])<=max(1e-9,before[0]*1e-8))
        connection.send({'group_id':group.id,'name':group.display_name,'body_count':len(group.body_ids),
            'preparation_passed':accepted,
            'prepared_geometry_valid':BRepCheck_Analyzer(prepared,True).IsValid(),
            'old_strict_limits_pass':old_limits_pass,
            'source_properties_unchanged':source_after==before,
            'calculation_group_bounds':asdict(prepared_group.bounds),
            'collision_epsilon_mm':checker.epsilon,
            'evidence':evidence,'activity_counts':{k:events.count(k) for k in set(events)},
            'elapsed_sec':time.monotonic()-started})
    except Exception as exc:
        connection.send({'group_id':group.id,'name':group.display_name,'error':f'{type(exc).__name__}: {exc}'})
    finally:
        connection.close()


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--report',type=Path,required=True)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    report=json.loads(args.report.read_text(encoding='utf-8'))
    if not report.get('planning'):
        database=args.root/'database/pa2-dev.sqlite3'
        with sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True) as db:
            snapshot_id=db.execute('select current_snapshot_id from projects where id=?',
                                   (report['project_id'],)).fetchone()[0]
        report['planning']={'plan':{'input_snapshot_id':snapshot_id}}
    groups,files=load_inputs(report,args.root)
    relays=sorted((g for g in groups.values() if g.display_name.startswith('RLY-KET400')),key=lambda g:g.id)
    if len(relays)!=2:raise ValueError(f'Expected two relay groups, found {len(relays)}')
    selected={bid:files[bid] for g in relays for bid in g.body_ids}
    before_hashes={bid:digest(path) for bid,path in selected.items()}
    output={'scope':'Relay input preparation only; no collision checks or sequence generation.',
            'source_report':str(args.report.resolve()),'source_root':str(args.root.resolve()),
            'snapshot_id':report['planning']['plan']['input_snapshot_id'],
            'collision_epsilon_mm':.001,'results':[]}
    context=mp.get_context('spawn')
    for group in relays:
        receive,send=context.Pipe(duplex=False)
        process=context.Process(target=check_group,args=(group,files,.001,send))
        process.start();send.close()
        if receive.poll(120):
            try:row=receive.recv()
            except EOFError:row={'name':group.display_name,'error':'native worker exited without result'}
        else:row={'name':group.display_name,'error':'native worker timed out at 120 seconds'}
        if 'error' in row and process.is_alive():process.terminate()
        process.join(5)
        if process.is_alive():process.terminate();process.join()
        receive.close()
        row['worker_exitcode']=process.exitcode
        output['results'].append(row)
        print(json.dumps(row,ensure_ascii=False),flush=True)
    output['cached_input_files_unchanged']=all(digest(path)==before_hashes[bid] for bid,path in selected.items())
    output['cached_input_sha256']=before_hashes
    output['all_relays_prepared']=all(row.get('preparation_passed',False) for row in output['results'])
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f"all_relays_prepared={output['all_relays_prepared']}",flush=True)


if __name__=='__main__':
    mp.freeze_support()
    main()
