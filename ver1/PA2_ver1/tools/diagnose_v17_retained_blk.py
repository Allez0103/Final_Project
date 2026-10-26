"""Read-only final-state BLK probe after all other general parts are removed.

This is separate from measured planning and does not replace the saved draft.
"""
import json,time
from pathlib import Path
from dataclasses import asdict
from collections import Counter
from diagnose_unknowns import load_inputs
from pa2.cad.brep_io import read_shape
from pa2.cad.isolated import NativeCadSession
from pa2.cad.path_check import exit_distance
from pa2.cad.directions import GLOBALS
from pa2.settings.config import AppSettings

def main():
    root=Path('runtime-data/native-validation'); report=json.loads((root/'planning-v17-final.json').read_text(encoding='utf-8'))
    groups,files=load_inputs(report,Path('runtime-data/end-to-end-v17-final'))
    blk=next(g for g in groups.values() if g.display_name=='BLK-KD000')
    base=groups[report['planning']['plan']['base_group_id']]
    settings=AppSettings(**report['settings']); params=settings.resolved_for_diagonal(base.bounds.union(g.bounds for g in groups.values()).diagonal)
    shapes={bid:read_shape(files[bid]) for g in (blk,base) for bid in g.body_ids}
    rows=[]; started=time.monotonic()
    with NativeCadSession([blk,base],shapes,jobs_dir=Path('runtime-data/end-to-end-v17-final/jobs'),native_timeout=settings.native_operation_timeout_sec) as worker:
        for direction in GLOBALS:
            travel=exit_distance(blk.bounds,[base.bounds],direction,params['exit_clearance_mm'])
            result=worker.call('path',{'moving':blk,'obstacles':[base],'direction':direction,'travel':travel,
                'remaining':{blk.id,base.id},'epsilon':params['geometry_epsilon_mm'],'min_interval':params['path_min_interval_mm'],
                'timeout':settings.candidate_timeout_sec,'initial_overlap_region_enabled':settings.initial_overlap_region_enabled,
                'initial_overlap_decrease_enabled':settings.initial_overlap_decrease_enabled,'cad_boolean_threads':settings.cad_boolean_threads},
                deadline=time.monotonic()+settings.candidate_timeout_sec)
            rows.append(asdict(result)); print(json.dumps({'direction':direction,'decision':result.decision,'codes':[d['code'] for d in result.evidence.get('pair_diagnostics',[])]}),flush=True)
    output={'ok':True,'scope':'Post-planning diagnostic only; all other groups absent; saved plan unchanged',
            'moving':blk.display_name,'obstacle':base.display_name,'paths':rows,'elapsed_sec':time.monotonic()-started,
            'criteria_unchanged':True,'settings':asdict(settings)}
    (root/'blk-final-state-v17.json').write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')

if __name__=='__main__':main()
