"""Isolated validation of the new cover/seal +Z pair policy; no source writes."""
import json
import multiprocessing as mp
import sys
from pathlib import Path
from dataclasses import asdict
from diagnose_unknowns import load_inputs
from diagnose_remaining import initialize, shape
from pa2.cad.path_check import ConservativePathChecker


def run_pair(job):
    import diagnose_remaining as inputs
    moving, obstacle = job
    checker=ConservativePathChecker(.001,.001,180,activity=lambda stage:print(stage,flush=True),initial_overlap_region_enabled=True,initial_overlap_decrease_enabled=True)
    result=checker.check(inputs.GROUPS[moving],shape(moving),[(inputs.GROUPS[obstacle],shape(obstacle))],
                         (0,0,1),40,{moving,obstacle})
    return asdict(result)


if __name__=='__main__':
    mp.freeze_support()
    report=json.loads(Path('runtime-data/native-validation/planning-binary-final.json').read_text(encoding='utf-8'))
    groups, files=load_inputs(report,Path('runtime-data/real-model'))
    jobs=[('group-1584ffc67b-0001','group-1d291d7b99-0001'),('group-1d291d7b99-0001','group-3c66381834-0001')]
    if '--seal-only' in sys.argv:jobs=jobs[1:]
    results=[]
    with mp.get_context('spawn').Pool(1,initializer=initialize,initargs=(groups,files)) as pool:
        for job in jobs:
            result=pool.apply_async(run_pair,(job,)).get(190)
            results.append({'moving':groups[job[0]].display_name,'obstacle':groups[job[1]].display_name,'result':result})
            print(results[-1]['moving'],result['decision'],result['elapsed_sec'],flush=True)
            Path('runtime-data/native-validation/decrease-pairs-v10.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
