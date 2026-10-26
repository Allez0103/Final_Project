"""Read-only CAD diagnosis of the retained 44 groups; no application policy edits.

Only diagnostic JSON is written. SQLite is opened mode=ro and cached BREP is read.
Native probes run in a disposable child with a parent-enforced timeout.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
import json
import linecache
import multiprocessing as mp
from pathlib import Path
import sqlite3
import sys
import time

from pa2.cad.path_check import ConservativePathChecker, state_key
from pa2.domain.models import AssemblyGroup, Bounds, PartType, MatchingStatus
from pa2.storage.cache import cache_key
from pa2.cad.importer import StepImporter


def initialize(groups, files):
    global GROUPS, FILES, SHAPES
    GROUPS,FILES,SHAPES=groups,files,{}


def shape(gid):
    from OCP.BRep import BRep_Builder
    from OCP.BRepTools import BRepTools
    from OCP.TopoDS import TopoDS_Shape
    from pa2.cad.shapes import compound
    from pa2.cad.brep_io import read_shape
    if gid not in SHAPES:
        solids=[]
        for body in GROUPS[gid].body_ids:
            solid=read_shape(FILES[body])
            solids.append(solid)
        SHAPES[gid]=compound(solids)
    return SHAPES[gid]


def probe(job):
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    from OCP.GeomAbs import GeomAbs_Cylinder
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopoDS import TopoDS
    started=time.monotonic()
    moving=shape(job['moving'])
    moving_valid_before=BRepCheck_Analyzer(moving).IsValid()
    if job['kind']=='axis':
        axes=[]
        ex=TopExp_Explorer(moving,TopAbs_FACE)
        while ex.More():
            face=TopoDS.Face(ex.Current()); surf=BRepAdaptor_Surface(face,True)
            if surf.GetType()==GeomAbs_Cylinder:
                props=GProp_GProps(); BRepGProp.SurfaceProperties_s(face,props)
                cylinder=surf.Cylinder(); axis=cylinder.Axis().Direction()
                axes.append({'area_mm2':abs(float(props.Mass())), 'axis':[axis.X(),axis.Y(),axis.Z()], 'radius_mm':cylinder.Radius()})
            ex.Next()
        return {'cylinders':sorted(axes,key=lambda a:-a['area_mm2'])}
    obstacle=shape(job['obstacle'])
    checker=ConservativePathChecker(.001,.001,100,bolt_initial_overlap_enabled=True,
        initial_overlap_region_enabled=job.get('initial_overlap_region_enabled',False))
    if job['kind']=='overlap':
        volume=checker._common_volume(moving,obstacle,(0,0,1),0)
        return {'common_volume_mm3':volume,'moving_percent':100*volume/GROUPS[job['moving']].volume_mm3 if volume is not None else None,
                'obstacle_percent':100*volume/GROUPS[job['obstacle']].volume_mm3 if volume is not None else None,'elapsed_sec':time.monotonic()-started}
    events=[]
    def trace(frame,event,arg):
        if not frame.f_code.co_filename.endswith('path_check.py'):
            return None
        fn=frame.f_code.co_name
        if event=='exception' and len(events)<150:
            events.append({'function':fn,'line':frame.f_lineno,'exception':f'{arg[0].__name__}: {arg[1]}'})
        if event=='return' and len(events)<150:
            value=arg.value if hasattr(arg,'value') else arg
            if fn in {'_check_pair','_check_pair_uncached','_swept_check','_initial_region_extraction'} or (fn=='_common_volume' and (value is None or value>1e-9)):
                row={'function':fn,'line':frame.f_lineno,'code':linecache.getline(frame.f_code.co_filename,frame.f_lineno).strip(),'return':value}
                loc=frame.f_locals
                for name in ('position','initial_volume','overlap','end_distance'):
                    if name in loc:row[name]=loc[name]
                if 'adaptor' in loc:row['surface_type']=str(loc['adaptor'].GetType())
                if 'prism' in loc:row['prism_done']=loc['prism'].IsDone()
                if 'solids' in loc:row['has_solid']=loc['solids'].More()
                if 'swept' in loc:
                    analyzer=BRepCheck_Analyzer(loc['swept']); row['sweep_valid']=analyzer.IsValid()
                    if not row['sweep_valid']:
                        from OCP.TopAbs import TopAbs_SOLID,TopAbs_SHELL,TopAbs_WIRE,TopAbs_EDGE
                        errors=set()
                        for kind in (TopAbs_SOLID,TopAbs_SHELL,TopAbs_FACE,TopAbs_WIRE,TopAbs_EDGE):
                            ex=TopExp_Explorer(loc['swept'],kind)
                            while ex.More():
                                try:
                                    check=analyzer.Result(ex.Current())
                                    errors.update(str(s) for s in check.Status() if str(s)!='BRepCheck_Status.BRepCheck_NoError')
                                    check.InitContextIterator()
                                    while check.MoreShapeInContext():
                                        errors.update(str(s) for s in check.StatusOnShape() if str(s)!='BRepCheck_Status.BRepCheck_NoError')
                                        check.NextShapeInContext()
                                except Exception:pass
                                ex.Next()
                        row['sweep_errors']=sorted(errors)
                events.append(row)
        return trace
    sys.settrace(trace)
    try:
        result=checker.check(GROUPS[job['moving']],moving,[(GROUPS[job['obstacle']],obstacle)],
            tuple(job['direction']),job['travel_mm'],{job['moving'],job['obstacle']})
    finally:
        sys.settrace(None)
    return {'result':asdict(result),'trace':events,'elapsed_sec':time.monotonic()-started,
            'moving_valid_before':moving_valid_before,'moving_valid':BRepCheck_Analyzer(moving).IsValid(),'obstacle_valid':BRepCheck_Analyzer(obstacle).IsValid()}


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--report',type=Path,default=Path('runtime-data/native-validation/planning-fastener-review.json'))
    p.add_argument('--root',type=Path,default=Path('runtime-data/real-model'))
    p.add_argument('--output',type=Path,default=Path('runtime-data/native-validation/remaining-diagnosis.json'))
    args=p.parse_args()
    source=json.loads(args.report.read_text(encoding='utf-8')); plan=source['planning']; sid=plan['plan']['input_snapshot_id']
    db=sqlite3.connect((args.root/'database/pa2-dev.sqlite3').resolve().as_uri()+'?mode=ro',uri=True)
    db.row_factory=sqlite3.Row
    snapshot=dict(db.execute('select * from import_snapshots where id=?',(sid,)).fetchone())
    group_rows=list(db.execute('select * from assembly_groups where snapshot_id=?',(sid,)))
    members={}
    for r in db.execute('select * from group_members where group_id like ?',(sid+':%',)):
        members.setdefault(r['group_id'].split(':',1)[1],[]).append(r['body_id'].split(':',1)[1])
    db.close()
    groups={r['id'].split(':',1)[1]:AssemblyGroup(r['id'].split(':',1)[1],r['display_name'],members[r['id'].split(':',1)[1]],
        PartType(r['part_type']),Bounds(**json.loads(r['bounds_json'])),r['volume_mm3'],json.loads(r['centroid_json']),
        bool(r['geometry_valid']),MatchingStatus(r['matching_status']),r['part_definition_id']) for r in group_rows}
    cached=args.root/'cache/shape'/cache_key('shape',[snapshot['assembly_asset_hash']],source.get('shape_cache_version','step-import-v1'),{'unit':'file'})
    manifest=json.loads((cached/'scene.json').read_text(encoding='utf-8'))
    files={b['id']:str((cached/b['brep_file']).resolve()) for b in manifest['bodies']}
    remaining=set(plan['plan']['group_ids'])-set(plan['removal_order']); final_key=state_key(remaining)
    unique={}
    for q in plan['paths']:
        if q['state_key']==final_key:unique.setdefault((q['group_id'],tuple(q['direction']),q['travel_mm']),q)
    rows=[]
    for gid in sorted(remaining-{plan['plan']['base_group_id']},key=lambda g:groups[g].display_name):
        candidates=[q for q in unique.values() if q['group_id']==gid]
        counts=Counter(q['reason_code'] for q in candidates)
        category='INITIAL_OVERLAP' if counts['INITIAL_OVERLAP'] else 'PATH_UNKNOWN' if counts['PATH_UNKNOWN'] else 'PATH_BLOCKED'
        rows.append({'group':asdict(groups[gid]),'category':category,'reason_counts':dict(counts),'candidates':candidates})
    output={'input_report':str(args.report),'final_state_key':final_key,'remaining_moving':len(rows),'unique_candidates':len(unique),
        'category_counts':dict(Counter(r['category'] for r in rows)),'names':{g.id:g.display_name for g in groups.values()},'groups':rows,'probes':[]}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    def save():args.output.write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
    save()
    pool=mp.get_context('spawn').Pool(1,initializer=initialize,initargs=(groups,files))
    def run(job):
        nonlocal pool
        print(json.dumps({'probe':job,'moving_name':groups[job['moving']].display_name},ensure_ascii=False),flush=True)
        try:result=pool.apply_async(probe,(job,)).get(120)
        except mp.TimeoutError:
            result={'error':'diagnostic timeout 120s'}; pool.terminate(); pool.join()
            pool=mp.get_context('spawn').Pool(1,initializer=initialize,initargs=(groups,files))
        except Exception as e:result={'error':f'{type(e).__name__}: {e}'}
        output['probes'].append({'job':job,**result}); save()
        return result
    try:
        pairs=set()
        for row in rows:
            gid=row['group']['id']
            for q in row['candidates']:
                if q['reason_code']=='INITIAL_OVERLAP':
                    for obstacle in q['obstacle_ids']:
                        pair=tuple(sorted((gid,obstacle)))
                        if pair not in pairs:
                            pairs.add(pair); run({'kind':'overlap','moving':gid,'obstacle':obstacle})
        for row in rows:
            gid=row['group']['id']; candidates=row['candidates']
            if row['group']['part_type']=='BOLT':
                axes=run({'kind':'axis','moving':gid}).get('cylinders',[])
                if axes:
                    axis=axes[0]['axis']; row['dominant_axis']=axis
                    for q in candidates:q['axial']=abs(sum(x*y for x,y in zip(axis,q['direction'])))>=1-1e-10
                    for q in candidates:
                        if q['axial'] and q['obstacle_ids']:
                            run({'kind':'pair','moving':gid,'obstacle':q['obstacle_ids'][0],
                                 'direction':q['direction'],'travel_mm':q['travel_mm'],'original_reason':q['reason_code']})
            elif row['category']=='PATH_UNKNOWN':
                candidates=sorted((q for q in candidates if q['reason_code']=='PATH_UNKNOWN'),key=lambda q:-q['direction'][2])
                if candidates and candidates[0]['obstacle_ids']:
                    q=candidates[0]
                    run({'kind':'pair','moving':gid,'obstacle':q['obstacle_ids'][0],
                         'direction':q['direction'],'travel_mm':q['travel_mm'],'original_reason':q['reason_code']})
        save()
    finally:pool.close(); pool.join()
    print(json.dumps({'categories':output['category_counts'],'probes':len(output['probes']),'output':str(args.output)},ensure_ascii=False),flush=True)


if __name__=='__main__':
    mp.freeze_support(); main()
