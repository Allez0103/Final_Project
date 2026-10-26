"""Compare one, two and four OCCT threads on unchanged real geometry."""
import json,time,os
from pathlib import Path
from diagnose_unknowns import load_inputs
from pa2.cad.brep_io import read_shape
from pa2.cad.shapes import compound,translated
from pa2.cad.path_check import _boolean
from pa2.cad.boolean_options import configure
from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps

def main():
    report=json.loads(Path('runtime-data/native-validation/planning-v16-final.json').read_text(encoding='utf-8'))
    groups,files=load_inputs(report,Path('runtime-data/end-to-end-v16-final'))
    base=groups[report['planning']['plan']['base_group_id']]
    obstacle=compound([read_shape(files[b]) for b in base.body_ids])
    jobs=[]
    for name in ('BLK-KD000','RLY-KET400 #1'):
        g=next(g for g in groups.values() if g.display_name==name)
        shape=compound([read_shape(files[b]) for b in g.body_ids])
        for position in (0.,.5,14.5):jobs.append((name,position,translated(shape,(-position,0,0))))
    rows=[]
    for threads in (1,2,4,4,2,1):
        if threads>(os.cpu_count() or 1):continue
        configure(threads); started=time.perf_counter(); results=[]
        for name,position,shape in jobs:
            q=_boolean(BRepAlgoAPI_Common,shape,obstacle); valid=q.IsDone() and BRepCheck_Analyzer(q.Shape(),True).IsValid()
            p=GProp_GProps()
            if valid:BRepGProp.VolumeProperties_s(q.Shape(),p)
            results.append({'part':name,'position':position,'valid':valid,'volume':abs(p.Mass()) if valid else None})
        rows.append({'threads':threads,'elapsed_sec':time.perf_counter()-started,'results':results})
        print(json.dumps(rows[-1]),flush=True)
    import statistics
    medians={threads:statistics.median(r['elapsed_sec'] for r in rows if r['threads']==threads) for threads in (1,2,4)}
    reference=rows[0]['results']
    identical=all(all(a['valid']==b['valid'] and (a['volume'] is None or abs(a['volume']-b['volume'])<1e-8)
                      for a,b in zip(reference,r['results'])) for r in rows)
    output={'rows':rows,'median_seconds':medians,'results_agree':identical,
            'selected_threads':min(medians,key=medians.get) if identical else 1,
            'reason':'Two runs per setting; representative exact geometry only, not an isolated full-planning benchmark.'}
    Path('runtime-data/native-validation/cad-parallel-v17.json').write_text(json.dumps(output,indent=2),encoding='utf-8')

if __name__=='__main__':main()
