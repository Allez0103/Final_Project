"""Read-only comparison and retained-chain audit of recorded planner runs."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path

from pa2.cad.path_check import state_key


def candidate_key(path):
    return path['state_key'], path['group_id'], tuple(path['direction']), path['travel_mm']


def summarize(report):
    run = report['planning']
    keys = [candidate_key(p) for p in run['paths']]
    return {
        'planner_version': report['planner_version'],
        'path_policy_version': report['path_policy_version'],
        'status': run['status'],
        'steps': len(run['removal_order']),
        'elapsed_sec': run['metrics']['elapsed_sec'],
        'candidate_records': len(keys),
        'unique_state_candidates': len(set(keys)),
        'duplicate_records': len(keys)-len(set(keys)),
        'state_count_in_paths': len({p['state_key'] for p in run['paths']}),
        'evaluation_sources': dict(Counter(p.get('evidence', {}).get('evaluation_source', 'not_instrumented') for p in run['paths'])),
        'virtual_candidate_records': len(run['metrics'].get('virtual_paths', [])),
        'metrics': {k:v for k,v in run['metrics'].items() if k!='virtual_paths'},
    }


def audit(report):
    run = report['planning']
    paths = {candidate_key(p): p for p in run['paths']}
    assert len(paths) == len(run['paths']), 'duplicate state+motion records'
    assert len(paths) == run['metrics']['tested_candidates']
    sources = Counter(p['evidence']['evaluation_source'] for p in paths.values())
    virtual=run['metrics'].get('virtual_paths', [])
    all_sources=sources+Counter(p['evidence']['evaluation_source'] for p in virtual)
    assert all_sources['native'] == run['metrics']['native_path_calls']
    assert all_sources['blocked_witness'] == run['metrics']['blocked_witness_cache_hits']
    assert all(not p['evidence'].get('virtual_probe') for p in paths.values())
    assert all(p['evidence']['virtual_probe'] for p in virtual)
    for p in paths.values():
        if p['evidence']['evaluation_source'] == 'blocked_witness':
            origin = (p['evidence']['witness_source_state'], p['group_id'], tuple(p['direction']), p['travel_mm'])
            original = paths[origin]
            assert original['evidence']['evaluation_source'] == 'native'
            assert original['decision'] == p['decision'] == 'BLOCKED'
            assert original['obstacle_ids'] == p['obstacle_ids']
            assert original['policy_version'] == p['policy_version']
            assert p['elapsed_sec'] == 0
            assert p['evidence']['calculation_metrics']['pair_calculations'] == 0
    plan = run['plan']
    remaining = set(plan['group_ids'])
    steps = {s['group_id']: s for s in plan['steps']}
    decrease_pairs = 0
    for gid in run['removal_order']:
        step = steps[gid]
        key = state_key(remaining), gid, tuple(step['removal_direction']), step['travel_mm']
        p = paths[key]
        assert p['decision'] == 'PASS' and p['evidence']['evaluation_source'] == 'native'
        evidence = p['evidence']
        if evidence.get('review_required'):
            assert '지지 미검증' in step['caution_text']
        for exception in evidence.get('initial_decrease_exceptions', []):
            assert exception['pair_decision'] == 'PASS'
            assert exception['obstacle_id'] in remaining
            assert '초기 겹침 감소 예외' in step['caution_text']
            detail = next(d for d in evidence['pair_diagnostics']
                          if d['obstacle_id'] == exception['obstacle_id'] and d['code'] == 'INITIAL_DECREASE_SAMPLED')
            assert detail['continuous_tail_decision'] == 'PASS'
            assert detail['continuous_monotonicity_proven'] is False
            low = detail['initial_overlap_mm3']
            previous = 0
            for sample in detail['samples']:
                volume = sample['overlap_mm3']
                assert volume is not None and volume <= low+detail['volume_tolerance_mm3']+1e-12
                assert 0 <= sample['position_mm']-previous <= .5+1e-12
                low = min(low, volume)
                previous = sample['position_mm']
            decrease_pairs += 1
        remaining.remove(gid)
    assert [s['group_id'] for s in plan['steps']] == list(reversed(run['removal_order']))
    assert len(steps) == run['metrics']['completed_groups']
    return {'ok': True, 'retained_steps': len(steps), 'decreasing_pairs': decrease_pairs,
            'remaining_moving': len(remaining)-1,
            'note': 'Recorded evidence audit; not a proof of physical assembly feasibility or maximum sequence length.'}


def calculation_costs(report):
    """Deduplicate old records; v11 can also exclude parent-level witness hits."""
    unique = {(False,*candidate_key(p)): p for p in report['planning']['paths']}
    unique.update({(True,*candidate_key(p)):p for p in report['planning']['metrics'].get('virtual_paths',[])})
    costs = Counter()
    counts = Counter()
    for p in unique.values():
        if p.get('evidence', {}).get('evaluation_source', 'native') != 'native':
            continue
        costs[p['group_id']] += p['elapsed_sec']
        counts[p['group_id']] += 1
    return costs, counts


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--current', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    before = json.loads(args.baseline.read_text(encoding='utf-8'))
    after = json.loads(args.current.read_text(encoding='utf-8'))
    changes = {k: [before['settings'].get(k), after['settings'].get(k)]
               for k in before['settings'].keys() | after['settings'].keys()
               if before['settings'].get(k) != after['settings'].get(k)}
    assert not changes, changes
    assert before['path_policy_version'] == after['path_policy_version']
    assert set(before['planning']['plan']['group_ids']) == set(after['planning']['plan']['group_ids'])
    assert before['planning']['plan']['base_group_id'] == after['planning']['plan']['base_group_id']
    old, new = summarize(before), summarize(after)
    old_costs, old_counts = calculation_costs(before)
    new_costs, new_counts = calculation_costs(after)
    costs = [{'group_id': gid, 'before_recorded_sec': old_costs[gid],
              'after_recorded_sec': new_costs[gid], 'delta_sec': new_costs[gid]-old_costs[gid],
              'before_unique_requests_inferred': old_counts[gid], 'after_native_requests': new_counts[gid]}
             for gid in old_costs.keys() | new_costs.keys()]
    output = {'baseline': old, 'current': new, 'settings_changes': changes, 'audit': audit(after),
              'elapsed_reduction_percent': 100*(1-new['elapsed_sec']/old['elapsed_sec']),
              'candidate_record_reduction_percent': 100*(1-new['candidate_records']/old['candidate_records']),
              'added_groups': sorted(set(after['planning']['removal_order'])-set(before['planning']['removal_order'])),
              'missing_previous_groups': sorted(set(before['planning']['removal_order'])-set(after['planning']['removal_order'])),
              'largest_recorded_cost_increases': sorted(costs, key=lambda row: row['delta_sec'], reverse=True)[:12],
              'largest_recorded_cost_decreases': sorted(costs, key=lambda row: row['delta_sec'])[:12],
              'note': 'Baseline has no native request counters. Its unique state+motion keys are not a measured Boolean-operation count.'}
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
