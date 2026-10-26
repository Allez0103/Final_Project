"""Assess bounded parameter repair on private copies; never changes app inputs."""
import json
from pathlib import Path
from diagnose_unknowns import load_inputs
import diagnose_remaining as source
from OCP.BRepBuilderAPI import BRepBuilderAPI_Copy
from OCP.BRepLib import BRepLib
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRep import BRep_Tool
from OCP.TopExp import TopExp_Explorer
from OCP.TopAbs import TopAbs_EDGE,TopAbs_VERTEX,TopAbs_FACE
from OCP.TopoDS import TopoDS
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps
from pa2.cad.sweep import bounds
from dataclasses import asdict


def properties(shape):
    values=[]
    for kind,cast in ((TopAbs_EDGE,TopoDS.Edge),(TopAbs_VERTEX,TopoDS.Vertex),(TopAbs_FACE,TopoDS.Face)):
        ex=TopExp_Explorer(shape,kind)
        while ex.More():
            values.append(BRep_Tool.Tolerance_s(cast(ex.Current())));ex.Next()
    props=GProp_GProps();BRepGProp.VolumeProperties_s(shape,props)
    return {'valid':BRepCheck_Analyzer(shape,True).IsValid(),'max_tolerance':max(values),
            'volume':props.Mass(),'bounds':asdict(bounds(shape))}


def main():
    report=json.loads(Path('runtime-data/native-validation/planning-all-initial-region-cached.json').read_text(encoding='utf-8'))
    groups,files=load_inputs(report,Path('runtime-data/real-model'));source.initialize(groups,files)
    output=[]
    for g in groups.values():
        if not g.display_name.startswith('BLT-WASM612A'):continue
        original=source.shape(g.id);copy=BRepBuilderAPI_Copy(original,True,False).Shape()
        row={'name':g.display_name,'before':properties(original)}
        BRepLib.SameParameter_s(copy,1e-7,True)
        row['after']=properties(copy);row['source_after']=properties(original)
        output.append(row);print(json.dumps(row,ensure_ascii=False),flush=True)
    Path('runtime-data/native-validation/input-repair-probe.json').write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')


if __name__=='__main__':main()
