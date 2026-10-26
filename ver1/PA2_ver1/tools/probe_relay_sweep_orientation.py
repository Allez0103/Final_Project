"""Reproduce a recorded offending sweep and test orientation on a private copy."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import multiprocessing as mp
from diagnose_unknowns import load_inputs


def inspect(group,base,files,witness,travel,connection):
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepClass3d import BRepClass3d_SolidClassifier
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS
    from pa2.cad.brep_io import read_shape
    from pa2.cad.shapes import compound
    from pa2.cad.prepare import prepare
    from pa2.cad.sweep import bounds,enclosures
    from pa2.cad.path_check import _boolean
    try:
        moving,_,valid=prepare(compound([read_shape(files[b]) for b in group.body_ids]),.001,lambda _:None)
        obstacle=compound([read_shape(files[b]) for b in base.body_ids])
        target=witness['source_face_bounds']
        explorer=TopExp_Explorer(moving,TopAbs_FACE)
        selected=None
        while explorer.More():
            face=TopoDS.Face(explorer.Current())
            box=asdict(bounds(face))
            if max(abs(box[k]-target[k]) for k in target)<1e-6:
                selected=face;break
            explorer.Next()
        if selected is None:raise ValueError('Recorded face could not be found')
        records=enclosures(selected,BRepAdaptor_Surface(selected,True),(0,0,1),travel,lambda _:None)
        prism=records[0][1]
        def properties(shape):
            props=GProp_GProps();BRepGProp.VolumeProperties_s(shape,props)
            classifier=BRepClass3d_SolidClassifier(shape)
            classifier.PerformInfinitePoint(1e-7)
            operation=_boolean(BRepAlgoAPI_Common,shape,obstacle)
            common=operation.Shape()
            overlap=GProp_GProps();BRepGProp.VolumeProperties_s(common,overlap)
            return {'geometry_valid':BRepCheck_Analyzer(shape,True).IsValid(),
                'signed_volume_mm3':props.Mass(),'infinite_point_state':str(classifier.State()),
                'common_volume_mm3':abs(overlap.Mass()),'shape_bounds':asdict(bounds(shape))}
        connection.send({'name':group.display_name,'prepared_geometry_valid':valid,
            'source_face_orientation':str(selected.Orientation()),
            'source_face_bounds':asdict(bounds(selected)),
            'travel_mm':travel,'original_sweep':properties(prism),
            'reversed_copy_sweep':properties(prism.Reversed()),
            'note':'original_sweep is the current application generator output; reversed_copy_sweep deliberately flips it for comparison.'})
    except Exception as exc:connection.send({'name':group.display_name,'error':f'{type(exc).__name__}: {exc}'})
    finally:connection.close()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--report',type=Path,required=True)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--diagnosis',type=Path,required=True)
    parser.add_argument('--sweep-report',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    report=json.loads(args.report.read_text(encoding='utf-8'))
    diagnosis=json.loads(args.diagnosis.read_text(encoding='utf-8'))
    report['planning']={'plan':{'input_snapshot_id':diagnosis['snapshot_id']}}
    groups,files=load_inputs(report,args.root)
    base=next(g for g in groups.values() if g.display_name=='MBD-KD000')
    sweep=json.loads(args.sweep_report.read_text(encoding='utf-8'))
    from pa2.cad.path_check import ConservativePathChecker
    output={'scope':'Read-only regression of the recorded +Z sweep using the current generator; no CAD asset changes.',
            'path_policy_version':ConservativePathChecker.VERSION,'results':[]}
    context=mp.get_context('spawn')
    for row in sweep['results']:
        group=next(g for g in groups.values() if g.display_name==row['name'])
        witness=row['sweep_witnesses'][0]
        receive,send=context.Pipe(duplex=False)
        process=context.Process(target=inspect,args=(group,base,files,witness,row['path']['travel_mm'],send))
        process.start();send.close()
        if receive.poll(120):
            try:result=receive.recv()
            except EOFError:result={'name':row['name'],'error':'native process exited'}
        else:result={'name':row['name'],'error':'timeout at 120 seconds'}
        if 'error' in result and process.is_alive():process.terminate()
        process.join(5)
        if process.is_alive():process.terminate();process.join()
        receive.close();output['results'].append(result)
        args.output.write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(result,ensure_ascii=False),flush=True)


if __name__=='__main__':
    mp.freeze_support();main()
