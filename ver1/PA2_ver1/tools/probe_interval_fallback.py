"""Evaluate the existing continuous distance-bound proof on residual UNKNOWN pairs."""
import json
import time
from pathlib import Path
from diagnose_unknowns import load_inputs
import diagnose_remaining as source
from pa2.cad.path_check import ConservativePathChecker


def main():
    data=Path('runtime-data/native-validation')
    report=json.loads((data/'planning-all-initial-region-cached.json').read_text(encoding='utf-8'))
    probes=json.loads((data/'unknown-35-final.json').read_text(encoding='utf-8'))
    groups,files=load_inputs(report,Path('runtime-data/real-model'));source.initialize(groups,files)
    rows=[]
    for probe in probes['probes']:
        if probe['result']['decision']!='UNKNOWN':continue
        job=probe['job'];moving=source.shape(job['moving']);obstacle=source.shape(job['obstacle'])
        checker=ConservativePathChecker(.001,.001,30)
        start_distance=checker._distance(moving,obstacle,tuple(job['direction']),0)
        started=time.perf_counter()
        result=checker._certify_interval(moving,obstacle,tuple(job['direction']),0,job['travel_mm'],started)
        row={'name':groups[job['moving']].display_name,'job':job,'decision':result.value,'elapsed_sec':time.perf_counter()-started,'start_distance_mm':start_distance}
        rows.append(row);print(json.dumps(row,ensure_ascii=False),flush=True)
    (data/'interval-fallback-probe.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')


if __name__=='__main__':main()
