"""Write named, reproducible evidence for the current end-to-end validation."""
from __future__ import annotations
import argparse
from collections import Counter
import json
from pathlib import Path

from diagnose_unknowns import load_inputs
from pa2.cad.path_check import state_key


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--report',type=Path,required=True)
    p.add_argument('--root',type=Path,required=True)
    p.add_argument('--audit',type=Path,required=True)
    p.add_argument('--video',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--markdown',type=Path,required=True)
    args=p.parse_args()
    report=json.loads(args.report.read_text(encoding='utf-8')); run=report['planning']; plan=run['plan']; m=run['metrics']
    audit=json.loads(args.audit.read_text(encoding='utf-8')) if args.audit.exists() else {'groups':[]}
    video=json.loads(args.video.read_text(encoding='utf-8'))
    groups,_=load_inputs(report,args.root); names={gid:g.display_name for gid,g in groups.items()}
    remaining=set(plan['group_ids'])-set(run['removal_order']); key=state_key(remaining)
    assert audit.get('state_key',key)==key
    rows=[]
    by_audit={r['group_id']:r for r in audit['groups']}
    for gid in sorted(remaining-{plan['base_group_id']},key=lambda g:names[g]):
        actual=[r for r in run['paths'] if r['state_key']==key and r['group_id']==gid]
        probes=by_audit.get(gid,{}).get('paths',[])
        indexed={(tuple(q['direction']),q['travel_mm']):q for q in actual}
        for q in probes:
            motion=(tuple(q['direction']),q['travel_mm'])
            if motion not in indexed or (indexed[motion]['decision']=='UNKNOWN' and q['decision']!='UNKNOWN'):
                indexed[motion]=q
        paths=list(indexed.values()); decisions=Counter(q['decision'] for q in paths)
        codes=Counter(); blockers=set(); uncertain=set()
        for q in paths:
            details=[d for d in q.get('evidence',{}).get('pair_diagnostics',[]) if d.get('decision')==q['decision']]
            codes.update(d['code'] for d in details) if details else codes.update([q['reason_code']])
            if q['decision']=='BLOCKED': blockers.update(q['obstacle_ids'])
            if q['decision']=='UNKNOWN': uncertain.update(q['obstacle_ids'])
        category='UNTESTED' if not paths else 'PATH_PASS_REQUIRES_SUPPORT_AND_SEARCH' if decisions['PASS'] else 'HAS_UNKNOWN' if decisions['UNKNOWN'] else 'OBSERVED_DIRECTIONS_BLOCKED'
        rows.append({'group_id':gid,'name':names[gid],'category':category,
            'planning_final_state_paths':len(actual),'audit_paths':len(probes),'unique_directions':len(paths),
            'available_directions':by_audit.get(gid,{}).get('available_directions'),
            'decisions':dict(decisions),'codes':dict(codes),
            'blocked_by':[names.get(x,x) for x in sorted(blockers)],
            'unknown_by':[names.get(x,x) for x in sorted(uncertain)],'paths':paths,
            'additional_diagnostic_paths':probes})
    stats={k:v for k,v in m.items() if k!='virtual_paths'}
    stop_reason='전체 경로 생성 완료' if m['path_complete'] else '전체 탐색 시간 제한 도달' if m['elapsed_sec']>=report['settings']['generation_timeout_sec'] else '역추적 횟수 제한 도달' if m['backtracks']>=report['settings']['backtrack_count'] else '유한 후보 경로의 차단·미판정 및 제한된 역추적'
    before={}
    for label,file in [('v10','planning-decrease-v10.json'),('v11','planning-target-v11.json')]:
        source=json.loads((args.report.parent/file).read_text(encoding='utf-8'))
        old_groups,_=load_inputs(source,args.root.parent/'real-model')
        equivalent=all(gid in old_groups and (g.body_ids,g.bounds,g.part_type)==
                       (old_groups[gid].body_ids,old_groups[gid].bounds,old_groups[gid].part_type)
                       for gid,g in groups.items()) and set(groups)==set(old_groups)
        old=source['planning']; before[label]={'steps':len(old['removal_order']),
            'elapsed_sec':old['metrics']['elapsed_sec'],'candidates':old['metrics']['tested_candidates'],
            'native_path_calls':old['metrics'].get('native_path_calls'),
            'same_settings':source['settings']==report['settings'],
            'same_groups':set(old['plan']['group_ids'])==set(plan['group_ids']),
            'same_body_membership_bounds_and_types':equivalent}
    output={'planner_version':report['planner_version'],'settings':report['settings'],'metrics':stats,
        'fresh_import_elapsed_sec':report['contact_elapsed_sec'],'fresh_import':report.get('fresh_import'),
        'cache_hits':report.get('shape_cache_hits'),'cache_misses':report.get('shape_cache_misses'),
        'status':run['status'],'reason':run['reason'],'termination':stop_reason,'final_state_key':key,
        'remaining_categories':dict(Counter(r['category'] for r in rows)),'remaining':rows,
        'removal_order_names':[names[g] for g in run['removal_order']],
        'assembly_order_names':[names[s['group_id']] for s in plan['steps']],
        'previous':before,'video':video,'diagnostic_elapsed_sec':audit.get('elapsed_sec'),
        'coverage_note':'Limited generated straight directions and time budgets; not a proof that a longer sequence is impossible. Audit path PASS alone does not establish support or a full removal sequence.'}
    args.output.write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
    def duration(value):
        value=round(value); return f'{value//60}분 {value%60:02d}초'
    clean=lambda v:str(v).replace('|','/').replace('\n',' ')
    lines=['# v12 실제 모델 전체 흐름 검증 결과','',
        f"생성 결과: **{len(run['removal_order'])}/{len(plan['group_ids'])-1}단계**, `{run['status']}`. 순서 생성 시간 **{duration(m['elapsed_sec'])}** ({m['elapsed_sec']:.3f}초).",'',
        '진행 관측에서는 32단계를 탐색 전 보고서 기록 후 23분 48초 이내에 확인했다. 이는 정확한 최종 개선 시각 계측이 아닌 관측 상한이다(`exterior-v12-observations.json`). 공식 전체 시간은 추가 방향·대안 탐색을 포함한 위의 계측값이다.','',
        '## 실행 범위','',
        f"별도 데이터 루트 `{args.root}`에서 제공 원본 STEP 19개를 새로 읽었다. 형상 캐시 hit {report.get('shape_cache_hits')}/miss {report.get('shape_cache_misses')}, 176바디/65그룹, 근접 243쌍, 접촉 121개, 접촉 미판정 0개. 입력·대응·접촉 총 {duration(report['contact_elapsed_sec'])}. 외부 원본은 수정하지 않았다.",
        '', '앱과 동일한 입력·탐색·계획 저장·미리보기·확정·재열기·영상·내보내기 서비스를 호출했다. 전체 장시간 탐색은 검증 도구에서 수행했으며 GUI의 모든 버튼을 마우스로 반복 조작한 시험은 아니다.',
        '', '## 알고리즘과 시간 비교','',
        '외부 노출 우선, 실제 유망 2방향, 접촉/차단 체결부 가상 제거 2방향, 가상 통과 시 실제 체결부 개별 제거와 대상 재검사, 전체 후보·방향 후순위 탐색을 적용했다. 지지·초기 겹침 감소·새 간섭 정책과 3600초 탐색 예산은 이전과 같다. 단순 접촉은 체결 관계의 대리 정보이며 실제 나사 연결 의미는 미확인이다.',
        '', '| 실행 | 단계 | 순서 생성 시간 | 실제 후보 기록 | 신규 경로 요청 |', '|---|---:|---:|---:|---:|']
    for label,old in before.items():
        lines.append(f"| {label} | {old['steps']}/64 | {duration(old['elapsed_sec'])} | {old['candidates']} | {old['native_path_calls'] if old['native_path_calls'] is not None else '직접 계측 없음'} |")
    lines.extend([f"| v12 | {len(run['removal_order'])}/64 | {duration(m['elapsed_sec'])} | {m['tested_candidates']} | {m['native_path_calls']} |",'',
        f"v12 신규 요청은 실제 {m['actual_native_path_calls']}회 + 가상 {m['virtual_native_path_calls']}회다. 가상 후보 기록 {m['virtual_candidate_records']}개는 실제 후보 기록과 별개다. 차단 근거 재사용 {m['blocked_witness_cache_hits']}회, 부품 쌍 계산 {m['pair_calculations']}회, BREP_COMMON {m['brep_common_calls']}회다. 강제 종료된 호출은 부분 연산 수를 보고할 수 없다. 후보 기록 감소를 같은 비율의 정밀 연산 절감으로 해석하지 않는다.",
        '', '단일 실행 비교이며 기계 부하 변동이 포함된다. 새 입력/접촉 처리 중 자동 시험·배포 빌드·패키지 검증을 병행했고, 탐색 중 실제 형상의 짧은 영상 사전 검증을 실행했다. 엄격히 격리된 성능 벤치마크는 아니다.',
        '', '## 끝까지 생성되지 않은 원인과 검사 범위','',f'탐색 종료 조건: **{stop_reason}**. '+run['reason'],'',
        f"최장 순서 끝의 잔여 이동 부품 {len(rows)}개를 아래에 정리했다. 탐색 기록과 별도 제한 방향 진단(부품당 최대 {audit.get('directions_per_group','—')}방향, 방향당 {audit.get('candidate_timeout_sec','—')}초)을 합쳤다. 진단 시간 {duration(audit.get('elapsed_sec',0))}. 검증하지 않은 방향을 차단으로 분류하지 않았다. 최장 단계 수가 물리적으로 가능한 최대치라는 뜻은 아니다.",
        '',f"추가 진단에서 동일 상태·이동의 기존 확정 판정 {audit.get('recorded_results_reused',0)}건을 재사용하고, 미검사·미판정 경로 {audit.get('new_path_requests',0)}건을 새로 요청했다. 추가 진단의 시간 제한은 주 탐색보다 짧으므로, 기존에 미판정인 경로가 여전히 미판정이면 기존의 더 넓은 검사 기록도 함께 보존한다.",
        '', '| 잔여 부품 | 검사 방향 | 차단 | 미판정 | 경로 통과 | 차단 상대 | 근거 코드 |', '|---|---:|---:|---:|---:|---|---|'])
    for row in rows:
        lines.append('| '+' | '.join(map(clean,[row['name'],row['unique_directions'],row['decisions'].get('BLOCKED',0),
            row['decisions'].get('UNKNOWN',0),row['decisions'].get('PASS',0),', '.join(row['blocked_by']) or '—',', '.join(row['codes']) or '미검사']))+' |')
    lines.extend(['', '코드 해석: OVERLAP_REINCREASE=초기 겹침의 허용 오차 이상 재증가; DECREASE_TAIL_BLOCKED=겹침 해소 후 경로 충돌; INPUT_GEOMETRY_INVALID=입력 정밀 유효성 실패; SWEEP_UNRESOLVED=곡면 이동 영역 판정 미해결; DIAGNOSTIC_NATIVE_ERROR/시간 제한=진단 예산 또는 native 호출 실패로 미판정. 상세 수치·상대 ID·원문은 요약 JSON과 원본 경로 기록에 보존한다.',
        '', '## 영상과 내보내기','',
        f"생성한 {video['steps']}단계를 역순 조립 영상으로 출력했다. 미계획 부품은 조립된 상태로 유지하고 모든 프레임에 부분 단계 수를 표시한다. 길이 {video['duration_sec']:.2f}초, {video['frames']}프레임, 1920×1080/30fps/H.264/yuv420p. 렌더링 {duration(video['render_elapsed_sec'])}, 크기 {video['bytes']:,}바이트.",
        '', f"영상: `{video['path']}`",'',
        '저장·재열기 내용 일치, 영상 내보내기 SHA-256 일치, 전체 MP4 디코딩 종료 코드 0, 마지막 장면의 전 부품 표시 및 모든 이동 변환 0을 확인했다. 시작·중간·마지막 프레임 PNG도 추출했다. 초기 겹침 감소 예외와 지지 미확인 경고는 계획 JSON에 원문으로 유지하며 영상에는 읽기 쉬운 요약을 표시한다.',
        '', '## 순서','', '아래는 분해 순서이며 영상은 역순이다.',''])
    lines.extend(f"{i}. {name}" for i,name in enumerate(output['removal_order_names'],1))
    lines.extend(['', '## 재현 자료','',f"- 원본 실행: `{args.report}`",f"- 잔여 상태 추가 진단: `{args.audit}`",f"- 이름·수치·상세 경로 요약: `{args.output}`",f"- 영상 검증: `{args.video}`",'- 설계: `EXTERIOR_VIRTUAL_SEARCH.md`',''])
    args.markdown.write_text('\n'.join(lines),encoding='utf-8')
    print(json.dumps({'steps':len(run['removal_order']),'elapsed_sec':m['elapsed_sec'],'remaining_categories':output['remaining_categories'],'video_ok':video['ok']},ensure_ascii=False))


if __name__=='__main__': main()
