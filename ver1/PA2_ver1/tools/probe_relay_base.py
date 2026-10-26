"""Independent +Z point witnesses and closed-solid volume checks, no policy edits."""
from __future__ import annotations
import argparse
from dataclasses import asdict
import json
import multiprocessing as mp
from pathlib import Path
import time
from diagnose_unknowns import load_inputs


def probe(group,base,files,connection):
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    from OCP.TopAbs import TopAbs_SOLID,TopAbs_FACE
    from OCP.TopExp import TopExp_Explorer
    from pa2.cad.brep_io import read_shape
    from pa2.cad.shapes import compound,translated
    from pa2.cad.prepare import prepare
    from pa2.cad.path_check import _boolean
    from pa2.cad.sweep import bounds
    def count(shape,kind):
        ex=TopExp_Explorer(shape,kind);total=0
        while ex.More():total+=1;ex.Next()
        return total
    try:
        started=time.monotonic()
        moving,evidence,valid=prepare(compound([read_shape(files[b]) for b in group.body_ids]),.001,lambda _:None)
        obstacle,_,base_valid=prepare(compound([read_shape(files[b]) for b in base.body_ids]),.001,lambda _:None)
        row={'name':group.display_name,'geometry_valid':valid,'base_valid':base_valid,
             'relay_bounds':asdict(bounds(moving)),'base_bounds':asdict(bounds(obstacle)),
             'input_repair':evidence,'samples':[]}
        for position in (0,.01,.1,1,2,5,10,20,30,40,50,60,70,80,90,100,110,120,130,140,150):
            operation=_boolean(BRepAlgoAPI_Common,translated(moving,(0,0,position)) if position else moving,obstacle)
            sample={'position_mm':position,'done':operation.IsDone()}
            if operation.IsDone():
                intersection=operation.Shape()
                raw=GProp_GProps();closed=GProp_GProps()
                BRepGProp.VolumeProperties_s(intersection,raw)
                BRepGProp.VolumeProperties_s(intersection,closed,OnlyClosed=True)
                sample.update(valid=BRepCheck_Analyzer(intersection,True).IsValid(),
                    raw_volume_mm3=abs(raw.Mass()),closed_volume_mm3=abs(closed.Mass()),
                    solids=count(intersection,TopAbs_SOLID),faces=count(intersection,TopAbs_FACE))
                if sample['faces']:
                    sample['intersection_bounds']=asdict(bounds(intersection))
            row['samples'].append(sample)
            print(json.dumps({'name':group.display_name,**sample},ensure_ascii=False),flush=True)
        row['elapsed_sec']=time.monotonic()-started
        connection.send(row)
    except Exception as exc:
        connection.send({'name':group.display_name,'error':f'{type(exc).__name__}: {exc}'})
    finally:connection.close()


def probe_sweep(group,base,files,connection):
    """Observe existing checker decisions without changing its return values."""
    import sys
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    from OCP.TopAbs import TopAbs_SOLID,TopAbs_FACE
    from OCP.TopExp import TopExp_Explorer
    from pa2.cad.brep_io import read_shape
    from pa2.cad.shapes import compound,translated
    from pa2.cad.path_check import ConservativePathChecker,_boolean,exit_distance
    from pa2.cad.sweep import bounds
    def count(shape,kind):
        ex=TopExp_Explorer(shape,kind);total=0
        while ex.More():total+=1;ex.Next()
        return total
    try:
        checker=ConservativePathChecker(.001,.001,180,initial_overlap_region_enabled=True,
                                        initial_overlap_decrease_enabled=True)
        moving=compound([read_shape(files[b]) for b in group.body_ids])
        obstacle=compound([read_shape(files[b]) for b in base.body_ids])
        original_common=checker._common_volume
        witnesses=[]
        def observed_common(a,b,d,position):
            value=original_common(a,b,d,position)
            if value is not None and value>1e-9:
                frame=sys._getframe(1)
                operation=_boolean(BRepAlgoAPI_Common,translated(a,tuple(v*position for v in d)) if position else a,b)
                intersection=operation.Shape()
                closed=GProp_GProps();BRepGProp.VolumeProperties_s(intersection,closed,OnlyClosed=True)
                witness={'caller':frame.f_code.co_name,'position_mm':position,
                    'raw_volume_mm3':value,'closed_volume_mm3':abs(closed.Mass()),
                    'solids':count(intersection,TopAbs_SOLID),'faces':count(intersection,TopAbs_FACE),
                    'intersection_bounds':asdict(bounds(intersection)),
                    'sweep_bounds':asdict(bounds(a))}
                if 'exact' in frame.f_locals:witness['sweep_marked_exact']=frame.f_locals['exact']
                if 'face_bounds' in frame.f_locals:witness['source_face_bounds']=asdict(frame.f_locals['face_bounds'])
                if 'adaptor' in frame.f_locals:witness['surface_type']=str(frame.f_locals['adaptor'].GetType())
                witnesses.append(witness)
                print(json.dumps({'name':group.display_name,'sweep_witness':witness},ensure_ascii=False),flush=True)
            return value
        checker._common_volume=observed_common
        travel=exit_distance(group.bounds,[base.bounds],(0,0,1),1)
        result=checker.check(group,moving,[(base,obstacle)],(0,0,1),travel,{group.id,base.id})
        connection.send({'name':group.display_name,'path':asdict(result),'sweep_witnesses':witnesses})
    except Exception as exc:
        connection.send({'name':group.display_name,'error':f'{type(exc).__name__}: {exc}'})
    finally:connection.close()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--report',type=Path,required=True)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--diagnosis',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--sweep',action='store_true')
    args=parser.parse_args()
    report=json.loads(args.report.read_text(encoding='utf-8'))
    diagnosis=json.loads(args.diagnosis.read_text(encoding='utf-8'))
    report['planning']={'plan':{'input_snapshot_id':diagnosis['snapshot_id']}}
    groups,files=load_inputs(report,args.root)
    base=next(g for g in groups.values() if g.display_name=='MBD-KD000')
    context=mp.get_context('spawn')
    output={'scope':'Observe sweep collision volume without changing checker decisions.' if args.sweep else
                    'Point witnesses only; zero samples do not certify an entire continuous path.',
            'direction':[0,0,1],'collision_epsilon_mm':.001,'results':[]}
    for group in sorted((g for g in groups.values() if g.display_name.startswith('RLY-KET400')),key=lambda g:g.id):
        receive,send=context.Pipe(duplex=False)
        process=context.Process(target=probe_sweep if args.sweep else probe,args=(group,base,files,send));process.start();send.close()
        if receive.poll(180):
            try:row=receive.recv()
            except EOFError:row={'name':group.display_name,'error':'native process exited'}
        else:row={'name':group.display_name,'error':'point probe timeout at 180 seconds'}
        if 'error' in row and process.is_alive():process.terminate()
        process.join(5)
        if process.is_alive():process.terminate();process.join()
        receive.close()
        output['results'].append(row)
        args.output.write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')


if __name__=='__main__':
    mp.freeze_support();main()
