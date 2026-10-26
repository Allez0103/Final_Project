"""Audit the retained path chain and review evidence of the completed v10 run."""
import json
from pathlib import Path
from pa2.cad.path_check import state_key


if __name__=='__main__':
    root=Path('runtime-data/native-validation')
    report=json.loads((root/'planning-decrease-v10.json').read_text(encoding='utf-8'))
    run=report['planning']; plan=run['plan']
    previous=json.loads((root/'planning-binary-final.json').read_text(encoding='utf-8'))['planning']
    remaining=set(plan['group_ids'])
    steps={s['group_id']:s for s in plan['steps']}
    indexed={}
    for p in run['paths']:
        if p['decision']=='PASS':
            indexed[(p['state_key'],p['group_id'],tuple(p['direction']),p['travel_mm'])]=p
    pairs=0; reviewed_steps=0
    for gid in run['removal_order']:
        step=steps[gid]
        result=indexed[(state_key(remaining),gid,tuple(step['removal_direction']),step['travel_mm'])]
        exceptions=result['evidence'].get('initial_decrease_exceptions',[])
        if exceptions:
            reviewed_steps+=1
            assert '초기 겹침 감소 예외' in step['caution_text']
        for exception in exceptions:
            assert exception['pair_decision']=='PASS'
            detail=next(d for d in result['evidence']['pair_diagnostics']
                        if d['obstacle_id']==exception['obstacle_id'] and d['code']=='INITIAL_DECREASE_SAMPLED')
            assert detail['continuous_tail_decision']=='PASS'
            assert detail['continuous_monotonicity_proven'] is False
            low=detail['initial_overlap_mm3']; last=0
            for sample in detail['samples']:
                assert sample['overlap_mm3'] is not None
                assert sample['overlap_mm3']<=low+detail['volume_tolerance_mm3']+1e-12
                assert 0<=sample['position_mm']-last<=.5+1e-12
                low=min(low,sample['overlap_mm3']); last=sample['position_mm']
            assert detail['samples'][-1]['overlap_mm3']<=1e-9+1e-15
            pairs+=1
        remaining.remove(gid)
    assert [s['group_id'] for s in plan['steps']]==list(reversed(run['removal_order']))
    assert reviewed_steps==run['metrics']['initial_decrease_exception_steps']
    assert plan['status']=='REVIEW_REQUIRED' and not run['metrics']['path_complete']
    assert set(previous['removal_order'])<=set(run['removal_order'])
    output={'ok':True,'retained_steps':len(steps),'reviewed_decrease_steps':reviewed_steps,
            'audited_decreasing_pairs':pairs,'remaining_moving':len(remaining)-1,
            'added_group_ids':[gid for gid in run['removal_order'] if gid not in previous['removal_order']],
            'note':'Audits recorded samples and continuous-tail decisions, not continuous monotonicity or physical feasibility.'}
    (root/'decrease-v10-retained-audit.json').write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(output,ensure_ascii=False,indent=2))
