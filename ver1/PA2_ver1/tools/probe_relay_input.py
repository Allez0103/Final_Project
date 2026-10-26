"""Compare fresh STEP relay solids with managed BREP, without editing either."""
import json
from pathlib import Path
from OCP.STEPControl import STEPControl_Reader
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.TopAbs import TopAbs_SOLID
from OCP.TopExp import TopExp_Explorer
from OCP.BRep import BRep_Builder
from OCP.BRepTools import BRepTools
from OCP.TopoDS import TopoDS_Shape
from OCP.BinTools import BinTools
from diagnose_unknowns import load_inputs


def main():
    root=Path('runtime-data/native-validation')
    report=json.loads((root/'planning-unknown-fixed-final.json').read_text(encoding='utf-8'))
    groups,files=load_inputs(report,Path('runtime-data/real-model'))
    target={bid for g in groups.values() if g.display_name.startswith('RLY') for bid in g.body_ids}
    reader=STEPControl_Reader()
    source=Path(r'C:\Users\Win11Pro\Desktop\제공 파일\제공 파일\3D DATA\STP\KD1_HVJB_91958-KD000.stp')
    print('Reading original STEP (read only)',flush=True)
    reader.ReadFile(str(source));reader.SetSystemLengthUnit(1.0);reader.TransferRoots()
    ex=TopExp_Explorer(reader.OneShape(),TopAbs_SOLID);index=0;rows=[]
    while ex.More():
        bid=f'body-3048cab7cc1d-{index:06d}'
        if bid in target:
            cached=TopoDS_Shape();BRepTools.Read_s(cached,files[bid],BRep_Builder())
            row={'body_id':bid,'fresh_topology_valid':BRepCheck_Analyzer(ex.Current(),False).IsValid(),
                 'fresh_geometry_valid':BRepCheck_Analyzer(ex.Current(),True).IsValid(),
                 'cached_topology_valid':BRepCheck_Analyzer(cached,False).IsValid(),
                 'cached_geometry_valid':BRepCheck_Analyzer(cached,True).IsValid()}
            if not row['cached_topology_valid']:
                folder=root/'relay-roundtrip';folder.mkdir(exist_ok=True)
                for label,writer in [('ascii',BRepTools),('binary',BinTools)]:
                    path=folder/f'{index:06d}.{label}.brep';writer.Write_s(ex.Current(),str(path))
                    restored=TopoDS_Shape()
                    if label=='ascii':BRepTools.Read_s(restored,str(path),BRep_Builder())
                    else:BinTools.Read_s(restored,str(path))
                    row[label+'_topology_valid']=BRepCheck_Analyzer(restored,False).IsValid()
                    row[label+'_geometry_valid']=BRepCheck_Analyzer(restored,True).IsValid()
            rows.append(row);print(json.dumps(row),flush=True)
        index+=1;ex.Next()
    (root/'relay-input-probe.json').write_text(json.dumps(rows,indent=2),encoding='utf-8')


if __name__=='__main__':main()
