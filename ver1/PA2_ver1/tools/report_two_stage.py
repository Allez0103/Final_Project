"""Compare recorded v13 with v12 and name final-state blockers, without rerunning CAD."""
import argparse,json
from collections import Counter
from pathlib import Path
from diagnose_unknowns import load_inputs
from pa2.cad.path_check import state_key


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--report',type=Path,required=True)
    p.add_argument('--root',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--markdown',type=Path,required=True)
    p.add_argument('--label',default='v13')
    args=p.parse_args()
    report=json.loads(args.report.read_text(encoding='utf-8')); run=report['planning'];m=run['metrics'];plan=run['plan']
    groups,_=load_inputs(report,args.root);name=lambda gid:groups[gid].display_name
    previous=json.loads((args.report.parent/'planning-exterior-v12-final.json').read_text(encoding='utf-8'))
    old=previous['planning'];om=old['metrics']
    oldgroups,_=load_inputs(previous,args.root.parent/'end-to-end-v12-final')
    same=groups.keys()==oldgroups.keys() and all(
        (g.body_ids,g.bounds,g.part_type)==(oldgroups[gid].body_ids,oldgroups[gid].bounds,oldgroups[gid].part_type)
        for gid,g in groups.items())
    # Accepted steps must match actual-state records, never a virtual PASS.
    state=set(plan['group_ids']);steps={s['group_id']:s for s in plan['steps']};audit=[]
    for gid in run['removal_order']:
        step=steps[gid]
        paths=[q for q in run['paths'] if q['group_id']==gid and q['state_key']==state_key(state)
            and max(abs(a-b) for a,b in zip(q['direction'],step['removal_direction']))<1e-10
            and abs(q['travel_mm']-step['travel_mm'])<1e-8]
        exceptional=gid in m['collision_exception_ids']
        matched=any(q['decision']==('NOT_TESTED' if exceptional else 'PASS')
            and bool(q['evidence'].get('user_collision_exception'))==exceptional
            and not q['evidence'].get('virtual_probe') for q in paths)
        assert matched,(gid,step,paths)
        assert exceptional==(step['geometry_status']=='USER_COLLISION_EXCEPTION')
        audit.append(dict(group_id=gid,name=name(gid),state_key=state_key(state),exception=exceptional,actual_record_matches=True))
        state.remove(gid)
    assert [q['group_id'] for q in plan['steps']]==list(reversed(run['removal_order']))
    assert run['removal_order'][:len(m['collision_exception_ids'])]==m['collision_exception_ids']
    remaining=set(plan['group_ids'])-set(run['removal_order']);key=state_key(remaining)
    rows=[]
    for gid in sorted(remaining-{plan['base_group_id']},key=name):
        paths=[q for q in run['paths'] if q['state_key']==key and q['group_id']==gid]
        decisions=Counter(q['decision'] for q in paths)
        codes=Counter(d['code'] for q in paths for d in q['evidence'].get('pair_diagnostics',[]) if d.get('decision')==q['decision'])
        blocked={x for q in paths if q['decision']=='BLOCKED' for x in q['obstacle_ids']}
        unknown={x for q in paths if q['decision']=='UNKNOWN' for x in q['obstacle_ids']}
        category='UNTESTED_FINAL_STATE' if not paths else 'HAS_UNKNOWN' if decisions['UNKNOWN'] else 'HAS_PASS' if decisions['PASS'] else 'OBSERVED_DIRECTIONS_BLOCKED'
        rows.append(dict(group_id=gid,name=name(gid),category=category,decisions=dict(decisions),codes=dict(codes),
            blocked_by=[name(x) for x in sorted(blocked)],unknown_by=[name(x) for x in sorted(unknown)],paths=paths))
    comparison={
        'previous':dict(steps=len(old['removal_order']),elapsed_sec=om['elapsed_sec'],actual_records=om['tested_candidates'],
            virtual_records=om['virtual_candidate_records'],native_path_calls=om['native_path_calls']),
        'current':dict(steps=len(run['removal_order']),elapsed_sec=m['elapsed_sec'],actual_records=m['tested_candidates'],
            virtual_records=m['virtual_candidate_records'],native_path_calls=m['native_path_calls'],
            direction_hint_calls=m['direction_hint_calls'],exception_steps=m['collision_exception_steps']),
        'same_input_groups_bodies_bounds_types':same,'same_settings':report['settings']==previous['settings'],
        'elapsed_change_percent':(m['elapsed_sec']/om['elapsed_sec']-1)*100,
        'actual_record_change_percent':(m['tested_candidates']/om['tested_candidates']-1)*100,
        'native_path_change_percent':(m['native_path_calls']/om['native_path_calls']-1)*100}
    auto=set(run['removal_order'])-set(m['collision_exception_ids']);before=set(old['removal_order'])
    comparison['new_automatic_removals']=[name(x) for x in sorted(auto-before)]
    comparison['missing_previous_removals']=[name(x) for x in sorted(before-auto)]
    comparison['automatic_steps']=len(auto)
    termination='complete' if m['path_complete'] else 'time_budget' if m['elapsed_sec']>=report['settings']['generation_timeout_sec'] else 'backtrack_budget' if m['backtracks']>=report['settings']['backtrack_count'] else 'limited_directions_blocked_or_unknown'
    output=dict(comparison=comparison,status=run['status'],reason=run['reason'],termination=termination,
        repair_policy=report.get('repair_policy'),retained_chain_audit=audit,
        metrics={k:v for k,v in m.items() if k not in ('virtual_paths','direction_hints')},
        removal_order_names=[name(g) for g in run['removal_order']],
        skeleton_order_names=[name(g) for g in m['skeleton_order']],
        skeleton_remaining_names=[name(g) for g in m['skeleton_remaining']],
        final_state_key=key,remaining_categories=dict(Counter(q['category'] for q in rows)),remaining=rows)
    args.output.write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
    def duration(t):return f'{int(t//60)}분 {t%60:.1f}초'
    lines=[f'# {args.label} LV CONT 예외 실행 결과','',f"생성 단계 **{len(run['removal_order'])}/64**. 순서 생성 시간 **{duration(m['elapsed_sec'])}**.",
        '',run['reason'],'',
        f'| 항목 | v12 | {args.label} |','|---|---:|---:|',
        f"| 생성 단계 | {len(old['removal_order'])}/64 | {len(run['removal_order'])}/64 |",
        f"| 순서 생성 시간 | {duration(om['elapsed_sec'])} | {duration(m['elapsed_sec'])} |",
        f"| 실제 상태 경로 후보 기록 | {om['tested_candidates']} | {m['tested_candidates']} |",
        f"| 가상 상태 경로 후보 기록 | {om['virtual_candidate_records']} | {m['virtual_candidate_records']} |",
        f"| 신규 정밀 경로 요청(실제+가상) | {om['native_path_calls']} | {m['native_path_calls']} |",
        f"| 사용자 지정 무검사 예외 단계 | 0 | {m['collision_exception_steps']} |",'',
        f"v13 생성 단계에는 LV CONT 사용자 지정 예외 {m['collision_exception_steps']}단계가 포함된다. 이 단계는 경로 통과가 아닌 NOT_TESTED이며 경로 후보 수에서 제외한다.",
        f"v13 방향 힌트 계산 {m['direction_hint_calls']}회, {m['direction_hint_elapsed_sec']:.2f}초는 신규 경로 요청 수와 별도로 계측하며 전체 생성 시간에 포함한다.",
        f"실제 상태 신규 요청 {m['actual_native_path_calls']}회, 가상 상태 신규 요청 {m['virtual_native_path_calls']}회. 후보 기록에는 차단 근거 재사용이 포함되므로 후보 수를 실제 정밀 계산 횟수로 읽으면 안 된다.",
        f"입력 그룹·바디·경계·분류 동일: {same}. 설정 동일: {comparison['same_settings']}. 사용자 지정 예외와 탐색·방향 정책이 달라진 단일 실행 비교다.",
        '',f"일반 부품 초안: {len(m['skeleton_order'])}개, {duration(m['skeleton_elapsed_sec'])}. 모든 볼트·너트를 임시 제외했으며 실제 제거 단계로 인정하지 않았다.",
        '초안 순서: '+', '.join(output['skeleton_order_names']),
        '',f"탐색 종료 조건: {termination}. 최장 순서 끝에서 남은 이동 부품 {len(rows)}개.",
        '검사 범위는 생성된 직선 방향과 시간·역추적 예산 내이며, 실제 분해 방법 전체에 대한 불가능 증명이 아니다.',
        '', '| 잔여 부품 | 최장 순서 끝 판정 | 차단 상대 | 미판정 상대 |', '|---|---|---|---|']
    for row in rows:
        lines.append('| '+row['name']+' | '+str(row['decisions'])+' | '+', '.join(row['blocked_by'])+' | '+', '.join(row['unknown_by'])+' |')
    lines+=['','분해 순서: '+', '.join(output['removal_order_names']),
            '', '세부 방향·거리·상태 해시·판정 근거는 실행 JSON 및 요약 JSON에 보존한다. 최장 순서 끝에서 검사하지 않은 부품은 차단으로 분류하지 않는다.']
    args.markdown.write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps({'comparison':comparison,'termination':termination,'remaining_categories':output['remaining_categories']},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
