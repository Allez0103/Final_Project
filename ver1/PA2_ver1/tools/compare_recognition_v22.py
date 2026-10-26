"""Summarize recognition-only evidence; do not run the planner or learning."""
import argparse
import json
from collections import Counter
from pathlib import Path


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--before',type=Path,required=True)
    parser.add_argument('--after',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    before=json.loads(args.before.read_text(encoding='utf-8'))
    after=json.loads(args.after.read_text(encoding='utf-8'))
    old={r['sample']:r for r in before['samples']}
    rows=[]
    for row in after['samples']:
        previous=old[row['sample']]
        # Every previously accepted geometry correspondence keeps its ID/members.
        a={g['id']:g for g in previous['groups'] if g['part_definition_id']}
        b={g['id']:g for g in row['groups']}
        old_matches_preserved=all(gid in b and g['body_ids']==b[gid]['body_ids']
            and g['display_name']==b[gid]['display_name']
            and g['part_definition_id']==b[gid]['part_definition_id'] for gid,g in a.items())
        rows.append(dict(sample=row['sample'],bodies=row['body_count'],
            matched_before=previous['matched_groups'],matched_after=row['matched_groups'],
            unmatched_before=previous['unmatched_bodies'],unmatched_after=row['unmatched_bodies'],
            bolts=row['group_types'].get('BOLT',0),expected_bolts=row['expected_bolt_instances'],
            bolt_count_correct=row['group_types'].get('BOLT',0)==row['expected_bolt_instances'],
            unknown_general_parts=row['group_types'].get('UNKNOWN',0),
            ambiguous=len(row['ambiguous']),rotation_matches=len(row['rotation_matches']),
            native_name_ties=sum(r.get('native_step_name_tie_break',False) for r in row['rotation_matches']),
            previous_matches_preserved=old_matches_preserved,
            input_hashes_unchanged=row['input_hashes']==previous['input_hashes'] and row['source_files_unchanged']))
    reference=after['reference'];ref_before=before['reference']
    checks=dict(all_dummy_bodies_matched=all(r['unmatched_after']==0 for r in rows),
        all_dummy_bolt_counts_correct=all(r['bolt_count_correct'] for r in rows),
        all_previous_matches_preserved=all(r['previous_matches_preserved'] for r in rows),
        no_dummy_ambiguities=all(r['ambiguous']==0 for r in rows),
        all_dummy_inputs_unchanged=all(r['input_hashes_unchanged'] for r in rows),
        original_reference_groups_exactly_unchanged=reference['groups']==ref_before['groups'],
        original_reference_definitions_exactly_unchanged=reference['definition_types']==ref_before['definition_types'],
        original_reference_inputs_unchanged=reference['input_hashes']==ref_before['input_hashes'] and reference['source_files_unchanged'],
        collision_planning_learning_source_unchanged=before['protected_source_hashes']==after['protected_source_hashes'],
        settings_exactly_unchanged=before['settings']==after['settings'])
    result=dict(ok=all(checks.values()),scope=after['scope'],checks=checks,samples=rows,
        dummy_bodies=sum(r['bodies'] for r in rows),dummy_bolts=sum(r['bolts'] for r in rows),
        dummy_files=sum(r['part_files']+1 for r in after['samples']),
        reference=dict(bodies=reference['body_count'],groups=reference['group_count'],
            unmatched_before=ref_before['unmatched_bodies'],unmatched_after=reference['unmatched_bodies'],
            fasteners=reference['group_types'].get('BOLT',0)+reference['group_types'].get('NUT',0)))
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0 if result['ok'] else 1


if __name__=='__main__':raise SystemExit(main())
