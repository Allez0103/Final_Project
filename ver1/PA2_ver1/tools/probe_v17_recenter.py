"""Test exact rigid recentering of both Boolean operands, with no fuzzy increase."""
import json,time
from pathlib import Path
from diagnose_unknowns import load_inputs
from pa2.cad.brep_io import read_shape
from pa2.cad.shapes import compound,translated
from pa2.cad.path_check import _boolean
from pa2.cad.sweep import bounds
from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps
from OCP.gp import gp_Trsf,gp_Vec

def main():
    report=json.loads(Path('runtime-data/native-validation/planning-v16-final.json').read_text(encoding='utf-8'))
    groups,files=load_inputs(report,Path('runtime-data/end-to-end-v16-final'))
    blk=next(g for g in groups.values() if g.display_name=='BLK-KD000'); base=groups[report['planning']['plan']['base_group_id']]
    a=translated(compound([read_shape(files[b]) for b in blk.body_ids]),(-14.5,0,0))
    b=compound([read_shape(files[x]) for x in base.body_ids])
    center=bounds(compound([a,b])).center
    rows=[]
    for offset in (tuple(-v for v in center),tuple(-v for v in base.bounds.center),(0,0,0),(100,100,100),(-100,-100,-100)):
        tr=gp_Trsf(); tr.SetTranslation(gp_Vec(*offset))
        aa=BRepBuilderAPI_Transform(a,tr,True).Shape(); bb=BRepBuilderAPI_Transform(b,tr,True).Shape()
        q=_boolean(BRepAlgoAPI_Common,aa,bb); props=GProp_GProps()
        valid=q.IsDone() and BRepCheck_Analyzer(q.Shape(),True).IsValid()
        if valid:BRepGProp.VolumeProperties_s(q.Shape(),props)
        row={'offset':offset,'valid':valid,'volume':abs(props.Mass()) if valid else None}; rows.append(row); print(json.dumps(row),flush=True)
    Path('runtime-data/native-validation/boolean-v17-recenter.json').write_text(json.dumps(rows,indent=2),encoding='utf-8')

if __name__=='__main__':main()
