"""Try exact surface patches on the first failed prism of representative pairs."""
from __future__ import annotations
import json
from pathlib import Path
from collections import Counter
from diagnose_unknowns import load_inputs
import diagnose_remaining as source
from OCP.BRep import BRep_Tool
from OCP.BRepTools import BRepTools
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.TopExp import TopExp_Explorer
from OCP.TopAbs import TopAbs_FACE
from OCP.TopoDS import TopoDS
from OCP.gp import gp_Vec


def main():
    report=json.loads(Path('runtime-data/native-validation/planning-all-initial-region-cached.json').read_text(encoding='utf-8'))
    groups,files=load_inputs(report,Path('runtime-data/real-model')); source.initialize(groups,files)
    baseline=json.loads(Path('runtime-data/native-validation/unknown-35-before.json').read_text(encoding='utf-8'))
    rows=[]; seen=set()
    for p in baseline['probes']:
        job=p['job']; g=groups[job['moving']]
        if g.display_name.split(' #')[0] in seen:continue
        seen.add(g.display_name.split(' #')[0])
        shape=source.shape(g.id); ex=TopExp_Explorer(shape,TopAbs_FACE)
        d=job['direction']; length=job['travel_mm']; vector=gp_Vec(*(v*length for v in d))
        while ex.More():
            f=TopoDS.Face(ex.Current()); surface=BRepAdaptor_Surface(f,True)
            kind=str(surface.GetType())
            if not any(s in kind for s in ('Cone','Cylinder','Torus')):
                ex.Next();continue
            try:
                prism=BRepPrimAPI_MakePrism(f,vector,True,True)
                valid=prism.IsDone() and BRepCheck_Analyzer(prism.Shape()).IsValid()
                if valid:ex.Next();continue
                u0,u1,v0,v1=BRepTools.UVBounds_s(f)
                s=BRep_Tool.Surface_s(f); stats={}
                for nu,nv in ((2,1),(4,1),(4,4)):
                    flags=[]
                    for i in range(nu):
                        for j in range(nv):
                            patch=BRepBuilderAPI_MakeFace(s,u0+(u1-u0)*i/nu,u0+(u1-u0)*(i+1)/nu,
                                v0+(v1-v0)*j/nv,v0+(v1-v0)*(j+1)/nv,1e-7).Face()
                            sweep=BRepPrimAPI_MakePrism(patch,vector,True,True)
                            flags.append(sweep.IsDone() and BRepCheck_Analyzer(sweep.Shape()).IsValid())
                    stats[f'{nu}x{nv}']=dict(Counter(flags))
                row={'name':g.display_name,'kind':kind,'uv':[u0,u1,v0,v1],'direction':d,'stats':stats}
                rows.append(row);print(json.dumps(row,ensure_ascii=False),flush=True);break
            except Exception as e:
                print(str(e),flush=True);break
    Path('runtime-data/native-validation/patch-probe.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')


if __name__=='__main__':main()
