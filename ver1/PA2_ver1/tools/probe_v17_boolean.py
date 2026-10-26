"""Reproduce BLK's failing common and compare exact, unchanged-tolerance retries."""
import json, time
from pathlib import Path
from diagnose_unknowns import load_inputs
from pa2.cad.brep_io import read_shape
from pa2.cad.shapes import compound, translated
from pa2.cad.path_check import _boolean
from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps
from OCP.TopAbs import TopAbs_SOLID
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS
from OCP.ShapeFix import ShapeFix_Shape
from OCP.BRepBuilderAPI import BRepBuilderAPI_Copy
from OCP.collections import List_TopoDS_Shape
from OCP.BOPAlgo import BOPAlgo_GlueEnum
from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
from OCP.BRepLib import BRepLib
from pa2.cad.prepare import prepare
from OCP.ShapeFix import ShapeFix_Wireframe, ShapeFix_Solid

def pieces(shape):
    ex=TopExp_Explorer(shape,TopAbs_SOLID); result=[]
    while ex.More():result.append(ex.Current()); ex.Next()
    return result or [shape]

def main():
    report=json.loads(Path('runtime-data/native-validation/planning-v16-final.json').read_text(encoding='utf-8'))
    groups,files=load_inputs(report,Path('runtime-data/end-to-end-v16-final'))
    blk=next(g for g in groups.values() if g.display_name=='BLK-KD000')
    base=groups[report['planning']['plan']['base_group_id']]
    a=translated(compound([read_shape(files[b]) for b in blk.body_ids]),(-14.5,0,0))
    b=compound([read_shape(files[x]) for x in base.body_ids])
    rows=[]
    for label,pairs in [('whole',[(a,b)]),('reverse',[(b,a)]),('solids',[(x,y) for x in pieces(a) for y in pieces(b)]),('solids_reverse',[(y,x) for x in pieces(a) for y in pieces(b)])]:
        started=time.perf_counter(); values=[]
        for x,y in pairs:
            q=_boolean(BRepAlgoAPI_Common,x,y); valid=q.IsDone() and BRepCheck_Analyzer(q.Shape()).IsValid()
            props=GProp_GProps()
            if q.IsDone():BRepGProp.VolumeProperties_s(q.Shape(),props)
            values.append({'valid':valid,'volume':abs(props.Mass())})
        row={'method':label,'results':values,'elapsed':time.perf_counter()-started}; rows.append(row); print(json.dumps(row),flush=True)
    for method in ('destructive_copy','obb','no_inverted','simplify','fix'):
        q=BRepAlgoAPI_Common(); args=List_TopoDS_Shape(); args.Append(BRepBuilderAPI_Copy(a).Shape()); tools=List_TopoDS_Shape(); tools.Append(BRepBuilderAPI_Copy(b).Shape()); q.SetArguments(args); q.SetTools(tools)
        q.SetNonDestructive(method!='destructive_copy')
        if method=='obb':q.SetUseOBB(True)
        if method=='no_inverted':q.SetCheckInverted(False)
        q.Build(); result=q.Shape()
        if method=='simplify':q.SimplifyResult(True,True); result=q.Shape()
        if method=='fix':
            fixer=ShapeFix_Shape(result); fixer.SetPrecision(1e-7); fixer.SetMinTolerance(1e-7); fixer.SetMaxTolerance(.001); fixer.Perform(); result=fixer.Shape()
        props=GProp_GProps(); BRepGProp.VolumeProperties_s(result,props)
        row={'method':method,'valid':BRepCheck_Analyzer(result,True).IsValid(),'volume':abs(props.Mass())}; rows.append(row); print(json.dumps(row),flush=True)
    for i,x in enumerate(pieces(a)):
        common=_boolean(BRepAlgoAPI_Common,x,b)
        if BRepCheck_Analyzer(common.Shape()).IsValid():continue
        for label,first,second in [('cut_moving',x,b),('cut_obstacle',b,x)]:
            q=_boolean(BRepAlgoAPI_Cut,first,second); props=GProp_GProps(); BRepGProp.VolumeProperties_s(q.Shape(),props)
            original=GProp_GProps(); BRepGProp.VolumeProperties_s(first,original)
            row={'method':label,'valid':BRepCheck_Analyzer(q.Shape(),True).IsValid(),'overlap_difference':abs(original.Mass())-abs(props.Mass())}; rows.append(row); print(json.dumps(row),flush=True)
    for method in ('same_parameter','fix_precision_1e7','fix_wire','fix_solid'):
        q=_boolean(BRepAlgoAPI_Common,a,b); result=q.Shape()
        if method=='same_parameter':BRepLib.SameParameter_s(result,1e-7,True)
        elif method=='fix_wire':
            fixer=ShapeFix_Wireframe(result); fixer.SetPrecision(1e-7); fixer.SetMaxTolerance(1e-7); fixer.FixSmallEdges(); fixer.FixWireGaps(); result=fixer.Shape()
        elif method=='fix_solid':
            fixer=ShapeFix_Solid(); fixer.Init(TopoDS.Solid(pieces(result)[0])); fixer.Perform(); result=fixer.Solid()
        else:
            fixer=ShapeFix_Shape(result); fixer.SetPrecision(1e-7); fixer.SetMinTolerance(1e-7); fixer.SetMaxTolerance(1e-7); fixer.Perform(); result=fixer.Shape()
        props=GProp_GProps(); BRepGProp.VolumeProperties_s(result,props)
        row={'method':method,'valid':BRepCheck_Analyzer(result,True).IsValid(),'volume':abs(props.Mass())}; rows.append(row); print(json.dumps(row),flush=True)
    Path('runtime-data/native-validation/boolean-v17-probe.json').write_text(json.dumps(rows,indent=2),encoding='utf-8')

if __name__=='__main__':main()
