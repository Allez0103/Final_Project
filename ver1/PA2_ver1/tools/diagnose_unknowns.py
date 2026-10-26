"""Reproduce one UNKNOWN direction for each retained group, from read-only BREP."""
from __future__ import annotations
import argparse
from collections import Counter
import json
import multiprocessing as mp
from pathlib import Path
import sqlite3

from diagnose_remaining import initialize,probe
from pa2.cad.importer import StepImporter
from pa2.domain.models import AssemblyGroup,Bounds,PartType,MatchingStatus
from pa2.storage.cache import cache_key


def load_inputs(report,root):
    sid=report['planning']['plan']['input_snapshot_id']
    db=sqlite3.connect((root/'database/pa2-dev.sqlite3').resolve().as_uri()+'?mode=ro',uri=True)
    db.row_factory=sqlite3.Row
    snapshot=dict(db.execute('select * from import_snapshots where id=?',(sid,)).fetchone())
    rows=list(db.execute('select * from assembly_groups where snapshot_id=?',(sid,)))
    members={}
    for r in db.execute('select * from group_members where group_id like ?',(sid+':%',)):
        members.setdefault(r['group_id'].split(':',1)[1],[]).append(r['body_id'].split(':',1)[1])
    db.close()
    groups={r['id'].split(':',1)[1]:AssemblyGroup(r['id'].split(':',1)[1],r['display_name'],members[r['id'].split(':',1)[1]],
        PartType(r['part_type']),Bounds(**json.loads(r['bounds_json'])),r['volume_mm3'],json.loads(r['centroid_json']),
        bool(r['geometry_valid']),MatchingStatus(r['matching_status']),r['part_definition_id']) for r in rows}
    cached=root/'cache/shape'/cache_key('shape',[snapshot['assembly_asset_hash']],report.get('shape_cache_version','step-import-v1'),{'unit':'file'})
    manifest=json.loads((cached/'scene.json').read_text(encoding='utf-8'))
    files={b['id']:str((cached/b['brep_file']).resolve()) for b in manifest['bodies']}
    return groups,files


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--report',type=Path,default=Path('runtime-data/native-validation/planning-all-initial-region-cached.json'))
    parser.add_argument('--summary',type=Path,default=Path('runtime-data/native-validation/initial-region-summary.json'))
    parser.add_argument('--root',type=Path,default=Path('runtime-data/real-model'))
    parser.add_argument('--output',type=Path,default=Path('runtime-data/native-validation/unknown-35-before.json'))
    args=parser.parse_args()
    report=json.loads(args.report.read_text(encoding='utf-8'))
    summary=json.loads(args.summary.read_text(encoding='utf-8'))
    groups,files=load_inputs(report,args.root)
    jobs=[]
    for row in summary['remaining']:
        candidates=[c for c in row['candidates'] if c['reason_code']=='PATH_UNKNOWN' and c['obstacle_ids']]
        if candidates:
            q=max(candidates,key=lambda c:c['direction'][2])
            jobs.append({'kind':'pair','moving':row['group_id'],'obstacle':q['obstacle_ids'][0],
                'direction':q['direction'],'travel_mm':q['travel_mm'],'initial_overlap_region_enabled':True})
    output={'source_report':str(args.report),'scope':'One representative UNKNOWN pair per retained group; not all directions.',
            'names':{g.id:g.display_name for g in groups.values()},'probes':[]}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    pool=mp.get_context('spawn').Pool(1,initializer=initialize,initargs=(groups,files))
    try:
        for i,job in enumerate(jobs,1):
            print(f"[{i}/{len(jobs)}] {groups[job['moving']].display_name}",flush=True)
            try:result=pool.apply_async(probe,(job,)).get(120)
            except mp.TimeoutError:
                result={'error':'diagnostic timeout 120s'}; pool.terminate(); pool.join()
                pool=mp.get_context('spawn').Pool(1,initializer=initialize,initargs=(groups,files))
            output['probes'].append({'job':job,**result})
            args.output.write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
    finally:pool.close();pool.join()
    print(json.dumps(dict(Counter(p.get('result',{}).get('decision','ERROR') for p in output['probes'])),ensure_ascii=False),flush=True)


if __name__=='__main__':
    mp.freeze_support();main()
