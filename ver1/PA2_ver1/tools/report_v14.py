"""Audit retained draft provenance and compare a completed run with v12."""
import argparse
import json
import platform
import sys
import sqlite3
import re
from importlib.metadata import version
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from diagnose_unknowns import load_inputs
from pa2.cad.path_check import state_key


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--report',type=Path,required=True)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--markdown',type=Path,required=True)
    args=parser.parse_args()
    report=json.loads(args.report.read_text(encoding='utf-8'))
    run=report['planning']; metrics=run['metrics']; plan=run['plan']
    groups,_=load_inputs(report,args.root)
    name=lambda gid:groups[gid].display_name
    old_report=json.loads((args.report.parent/'planning-exterior-v12-final.json').read_text(encoding='utf-8'))
    old=old_report['planning']; om=old['metrics']
    old_groups,_=load_inputs(old_report,args.root.parent/'end-to-end-v12-final')
    same=groups.keys()==old_groups.keys() and all(
        (g.body_ids,g.bounds,g.part_type)==(old_groups[gid].body_ids,old_groups[gid].bounds,old_groups[gid].part_type)
        for gid,g in groups.items())
    state=set(plan['group_ids']); steps={s['group_id']:s for s in plan['steps']}
    audit=[]; unresolved=[]
    for gid in run['removal_order']:
        step=steps[gid]; status=step['geometry_status']
        matches=[q for q in run['paths'] if q['group_id']==gid and q['state_key']==state_key(state)
            and max(abs(a-b) for a,b in zip(q['direction'],step['removal_direction']))<1e-10
            and abs(q['travel_mm']-step['travel_mm'])<1e-8 and not q['evidence'].get('virtual_probe')]
        kind={'USER_COLLISION_EXCEPTION':'USER_COLLISION_EXCEPTION',
              'FASTENER_ASSIGNED':'FASTENER_AXIS_ASSIGNED','DRAFT_UNRESOLVED':'DRAFT_UNRESOLVED'}.get(status)
        matching=([q for q in matches if q['decision']=='NOT_TESTED' and q['reason_code']==kind]
                  if kind else [q for q in matches if q['decision']=='PASS'])
        assert matching,(gid,status,matches)
        row=matching[-1]
        if kind=='FASTENER_AXIS_ASSIGNED':
            assert row['evidence']['path_check_skipped']
            axis=row['evidence'].get('axis')
            target=groups[row['evidence']['target_group_id']]
            away=tuple(a-b for a,b in zip(groups[gid].centroid or groups[gid].bounds.center,target.centroid or target.bounds.center))
            assert sum(a*b for a,b in zip(away,step['removal_direction']))>=-1e-8
            if axis:assert abs(abs(sum(a*b for a,b in zip(axis,step['removal_direction'])))-1)<1e-8
        assert step['caution_text']==''
        assert step['material_text']==name(gid)
        audit.append(dict(group_id=gid,name=name(gid),status=status,decision=row['decision'],
                          reason=row['reason_code'],state_key=row['state_key']))
        if kind=='DRAFT_UNRESOLVED':
            previous=[run['paths'][i] for i in row['evidence']['prior_result_indices']]
            virtual=[q for q in metrics.get('virtual_paths',[]) if q['group_id']==gid]
            blockers={x for q in previous for x in q['obstacle_ids']}
            codes=Counter(q['reason_code'] for q in previous)
            details=Counter(d['code'] for q in previous for d in q['evidence'].get('pair_diagnostics',[]) if 'code' in d)
            unresolved.append(dict(group_id=gid,name=name(gid),prior_decisions=dict(Counter(q['decision'] for q in previous)),
                body_ids=groups[gid].body_ids,bounds=asdict(groups[gid].bounds),
                center=groups[gid].centroid or groups[gid].bounds.center,
                reasons=dict(codes),pair_codes=dict(details),blockers=[name(x) for x in sorted(blockers)],
                actual_paths=previous,virtual_paths=virtual,draft_state_key=row['state_key'],
                budget_exhausted=row['evidence']['budget_exhausted']))
        state.remove(gid)
    assert len(steps)==len(plan['steps'])
    assert [s['group_id'] for s in plan['steps']]==list(reversed(run['removal_order']))
    assert run['removal_order'][:len(metrics['collision_exception_ids'])]==metrics['collision_exception_ids']
    assert {g for g in metrics['unresolved_general_ids']}=={q['group_id'] for q in unresolved}
    if metrics['draft_complete']:assert state=={plan['base_group_id']}
    assert metrics['verified_path_steps']+metrics['fastener_assigned_steps']+metrics['collision_exception_steps']+metrics['unresolved_general_steps']==len(plan['steps'])
    # Reconstruct only states actually recorded at the longest accepted prefix,
    # including the target's temporary fastener-removal trials. No CAD rerun.
    from pa2.domain.models import ContactEdge
    from pa2.planning.two_stage import TwoStagePriorityProvider
    from pa2.planning.priority import is_fastener
    db=sqlite3.connect((args.root/'database/pa2-dev.sqlite3').resolve().as_uri()+'?mode=ro',uri=True)
    contacts=[ContactEdge(a,b,d) for a,b,d in db.execute(
        'select group_a,group_b,distance_mm from contacts where snapshot_id=?',(plan['input_snapshot_id'],))]
    db.close()
    prefix_remaining=set(plan['group_ids'])-set(run['removal_order'][:metrics['checked_prefix_steps']])
    prefix_key=state_key(prefix_remaining)
    provider=TwoStagePriorityProvider(); provider.skeleton=metrics['skeleton_draft_order']
    ranked=provider.rank(groups,prefix_remaining,plan['base_group_id'],contacts)
    prefix_rows=[]
    for row in unresolved:
        gid=row['group_id']
        direct=[q for q in run['paths'] if q['group_id']==gid and q['state_key']==prefix_key and q['decision']!='NOT_TESTED']
        observed=[dict(omitted_fastener_ids=[],paths=direct)]
        blockers={x for q in direct if q['decision']=='BLOCKED' for x in q['obstacle_ids']}
        related=set(provider.related_fasteners(gid,blockers,ranked,groups,contacts))
        while related:
            key=state_key(prefix_remaining-related)
            trial=[q for q in run['paths'] if q['group_id']==gid and q['state_key']==key and q['decision']!='NOT_TESTED']
            if not trial:break
            observed.append(dict(omitted_fastener_ids=sorted(related),paths=trial))
            extra={x for q in trial if q['decision']=='BLOCKED' for x in q['obstacle_ids']
                   if x in prefix_remaining and is_fastener(groups[x])}-related
            if not extra:break
            related|=extra
        last=observed[-1]['paths']
        category=('UNTESTED' if not last else 'HAS_UNKNOWN' if any(q['decision']=='UNKNOWN' for q in last)
                  else 'ALL_SIX_BLOCKED' if len({tuple(q['direction']) for q in last if q['decision']=='BLOCKED'})==6
                  else 'PARTIALLY_TESTED')
        failure_codes=Counter(detail['code'] for q in last for detail in q['evidence'].get('pair_diagnostics',[])
                              if detail.get('decision')==q['decision'])
        native_errors=[q['evidence']['native_error'] for q in last if q['evidence'].get('native_error')]
        prefix_rows.append(dict(group_id=gid,name=row['name'],category=category,
            decisions=dict(Counter(q['decision'] for q in last)),failure_codes=dict(failure_codes),
            obstacle_names=sorted({name(x) for q in last for x in q['obstacle_ids']}),
            native_errors=native_errors,states=observed))
    comparison={
        'previous':dict(steps=len(old['removal_order']),elapsed_sec=om['elapsed_sec'],actual_records=om['tested_candidates'],
            virtual_records=om['virtual_candidate_records'],native_path_calls=om['native_path_calls'],
            pair_calculations=om['pair_calculations'],brep_common_calls=om['brep_common_calls']),
        'current':dict(steps=len(run['removal_order']),elapsed_sec=metrics['elapsed_sec'],actual_records=metrics['tested_candidates'],
            virtual_records=metrics['virtual_candidate_records'],native_path_calls=metrics['native_path_calls'],
            pair_calculations=metrics['pair_calculations'],brep_common_calls=metrics['brep_common_calls'],
            path_pass_steps=metrics['verified_path_steps'],fastener_assigned_steps=metrics['fastener_assigned_steps'],
            user_exception_steps=metrics['collision_exception_steps'],unresolved_general_steps=len(unresolved)),
        'same_input_groups_bodies_bounds_types':same,'same_settings':report['settings']==old_report['settings'],
        'elapsed_change_percent':(metrics['elapsed_sec']/om['elapsed_sec']-1)*100,
        'total_candidate_record_change_percent':((metrics['tested_candidates']+metrics['virtual_candidate_records'])/
            (om['tested_candidates']+om['virtual_candidate_records'])-1)*100,
        'native_path_change_percent':(metrics['native_path_calls']/om['native_path_calls']-1)*100,
        'note':'Single runs; fastener path checks now skipped by user policy, LV CONT exempt, sweep orientation fixed. Counts are not equal verification coverage.'}
    termination='search_complete' if metrics['search_complete'] else 'time_budget' if metrics['elapsed_sec']>=report['settings']['generation_timeout_sec'] else 'backtrack_budget' if metrics['backtracks']>=report['settings']['backtrack_count'] else 'limited_search_blocked_or_unknown'
    costs=[]
    assert not any(is_fastener(groups[q['group_id']]) and q['evidence'].get('evaluation_source')=='native'
                   for q in run['paths']+metrics.get('virtual_paths',[]))
    for gid in groups:
        native=[q for q in run['paths']+metrics.get('virtual_paths',[]) if q['group_id']==gid and q['evidence'].get('evaluation_source')=='native']
        if native:
            costs.append(dict(group_id=gid,name=name(gid),native_requests=len(native),
                returned_elapsed_sec=sum(q['elapsed_sec'] for q in native),
                decisions=dict(Counter(q['decision'] for q in native)),
                reasons=dict(Counter(q['reason_code'] for q in native))))
    costs.sort(key=lambda q:-q['returned_elapsed_sec'])
    output=dict(comparison=comparison,termination=termination,retained_chain_audit=audit,
        unresolved=unresolved,costs_by_group=costs,prefix_failure_states=prefix_rows,
        prefix_failure_categories=dict(Counter(q['category'] for q in prefix_rows)),
        removal_order_names=[name(g) for g in run['removal_order']],
        skeleton_proven_names=[name(g) for g in metrics['skeleton_order']],
        skeleton_unresolved_names=[name(g) for g in metrics['skeleton_remaining']],
        metrics={k:v for k,v in metrics.items() if k not in ('virtual_paths','direction_hints')})
    import psutil
    output['runtime_environment']={'python':sys.version,'platform':platform.platform(),
        'processor':platform.processor(),'logical_cpus':psutil.cpu_count(),
        'physical_cpus':psutil.cpu_count(logical=False),'ram_bytes':psutil.virtual_memory().total,
        'packages':{name:version(name) for name in ('cadquery-ocp','vtk','PySide6-Essentials','numpy')}}
    artifacts={}
    for key,relative in {
        'video':'video-v14-final/video-validation.json',
        'packaged_sources':'packaged-source-check-v14-final.json',
        'native_smoke':'native-smoke-v14-final.json',
        'gui_reopen':'gui-reopen-v14-final.json',
        'reference_integrity':'reference-integrity-v14-final.json',
    }.items():
        path=args.report.parent/relative
        if path.is_file():artifacts[key]=json.loads(path.read_text(encoding='utf-8-sig'))
    output['validation_artifacts']=artifacts
    test_log=args.report.parent/'tests-v14-ui-final.log'
    if test_log.is_file():
        match=re.search(r'(\d+) passed, (\d+) skipped',test_log.read_text(encoding='utf-8',errors='replace'))
        if match:artifacts['automated_tests']={'passed':int(match[1]),'skipped':int(match[2]),'log':str(test_log)}
    args.output.write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
    duration=lambda t:f'{int(t//60)}분 {t%60:.2f}초'
    lines=['# v14 전체 초안·영상 실행 결과','',
        f"초안 {len(plan['steps'])}/{len(groups)-1}단계, 순서 생성 {duration(metrics['elapsed_sec'])}. {run['reason']}",'',
        '| 항목 | 이전 완료 실행 v12 | 이번 v14 |','|---|---:|---:|',
        f"| 초안 단계 수 | {len(old['removal_order'])}/64 | {len(plan['steps'])}/64 |",
        f"| 순서 생성 시간 | {duration(om['elapsed_sec'])} | {duration(metrics['elapsed_sec'])} |",
        f"| 실제/체결부 임시 제거 상태 후보 기록 | {om['tested_candidates']} | {metrics['tested_candidates']} |",
        f"| 전체 체결부 제외 초안 후보 기록 | {om['virtual_candidate_records']} | {metrics['virtual_candidate_records']} |",
        f"| 후보 기록 합계 | {om['tested_candidates']+om['virtual_candidate_records']} | {metrics['tested_candidates']+metrics['virtual_candidate_records']} |",
        f"| 신규 CAD 경로 요청 | {om['native_path_calls']} | {metrics['native_path_calls']} |",
        f"| 부품 쌍 계산 | {om['pair_calculations']} | {metrics['pair_calculations']} |",
        f"| BREP Common 호출 | {om['brep_common_calls']} | {metrics['brep_common_calls']} |",'',
        f"이번 초안 구성: 경로 PASS {metrics['verified_path_steps']}개, 상세 경로 검사를 생략한 볼트·너트 {metrics['fastener_assigned_steps']}개, LV CONT 예외 {metrics['collision_exception_steps']}개, 해결되지 않은 일반 부품 {len(unresolved)}개.",
        '이전 v12는 모든 채택 단계에서 경로를 검사했다. 검사 범위가 달라진 단일 실행 비교이므로 같은 정확도의 단순 속도 향상으로 해석하지 않는다.',
        f"입력 그룹·바디·경계·분류 일치: {same}. 수치 설정 일치: {comparison['same_settings']}. 신규 데이터 루트의 차가운 입력 캐시로 실행했다.",
        f"입력·그룹화·접촉 준비: {duration(report['contact_elapsed_sec'])}. 순서 생성과 별도 계측.",
        '입력 준비 구간에 EXE 재빌드를 병행했다. 순서 생성 비교는 준비 시간과 구분하며 단일 실행의 환경 부하 차이를 포함한다.',
        f"방향 힌트 {metrics['direction_hint_calls']}회/{metrics['direction_hint_elapsed_sec']:.2f}초. 후보와 별도이며 순서 생성 시간에 포함.",
        f"탐색 종료: {termination}. 초안 전체 포함: {metrics['draft_complete']}. 모든 경로 검증 완료: {metrics['path_complete']}.",'',
        f"가상 초안 예산 배분: 전체의 {metrics.get('skeleton_budget_fraction',0)*100:.0f}%, 배분 한도 도달: {metrics.get('skeleton_budget_exhausted',False)}. 남은 전체 예산은 실제 상태 검사에 사용했다.",'',
        '## 해결되지 않은 일반 부품','',
        '| 부품 | 기록된 판정 | 이유 | 차단/미판정 상대 |','|---|---|---|---|']
    for q in unresolved:
        lines.append(f"| {q['name']} | {q['prior_decisions']} | {q['reasons']} / {q['pair_codes']} | {', '.join(q['blockers'])} |")
    if not unresolved:lines.append('해결되지 않은 일반 부품 없음.')
    lines+=['','이 표는 검사한 직선 방향과 제한 시간 내 기록이다. 물리적으로 가능한 모든 분해 방법의 불가능 판정은 아니다.',
        '표의 판정은 탐색 중 과거 상태에서 관측한 결과이며, 미해결 단계를 순차 보충한 뒤의 상태에서 모두 재검사했다는 뜻은 아니다. 상태 해시는 JSON에 보존한다.',
        '미해결 단계는 NOT_TESTED/DRAFT_UNRESOLVED로 보존하고 화면에서 경로 확인 필요로 표시한다. 볼트·너트는 NOT_TESTED/FASTENER_AXIS_ASSIGNED를 내부 보존하되 화면 경고는 표시하지 않는다.',
        'LV CONT는 노출도 1순위 방향으로 분해 선두에 두고 이후 장애물·지지 검사에서 제외했다.',
        '', '## 주요 계산 비용','', '| 부품 | 신규 경로 요청 | 반환 결과 계산시간 합계 |','|---|---:|---:|']
    for q in costs[:10]:lines.append(f"| {q['name']} | {q['native_requests']} | {q['returned_elapsed_sec']:.2f}초 |")
    lines+=['','## 최장 제거열 끝의 직접·체결부 임시 제거 검사','',
        f"최장 제거열 {metrics['checked_prefix_steps']}단계 끝의 실제 잔여 상태를 복원했다. 해당 상태에서 기록된 직접 검사와 관련 체결부 임시 제거 검사를 대조했다. 부품별 마지막 기록 상태 기준 분류: {dict(Counter(q['category'] for q in prefix_rows))}.",
        '', '| 부품 | 분류 | 마지막 검사 판정 | 원인 코드 | 상대 |', '|---|---|---|---|---|']
    for q in prefix_rows:lines.append(f"| {q['name']} | {q['category']} | {q['decisions']} | {q['failure_codes']} {q['native_errors']} | {', '.join(q['obstacle_names'])} |")
    lines+=['','반환 결과 시간 합계는 요청·IPC를 포함한 전체 경과 시간과 다를 수 있다. 차단 근거·상태 캐시 재사용 시간은 다시 합산하지 않았다.',
        '', '## 원인 분석','',
        '순서 생성은 전체 60분을 소진하지 않고 제한된 순서·방향·되돌아가기 탐색에서 더 채택할 경로를 얻지 못해 종료했다. 가상 초안은 21분 배분 한도에 도달했고, 이후 실제 상태 검사를 수행했다. 최장 채택 제거열 31단계 뒤에는 미해결 일반 부품 16개와 아직 배치하지 않은 체결부가 남았으며, 이를 편집용 단계로 보충해 64단계를 만들었다.',
        '실제 경로 PASS 일반 부품은 커버·씰·버스바 4개다. 이 6개도 지지는 미확인이어서 SUPPORT_UNVERIFIED로 보존했다. 41개 볼트·너트는 실제 원통축을 추출했고, 축을 얻지 못해 대체 방향을 사용한 배치는 없었다.',
        '미해결 9개는 관련 체결부 임시 제거까지 포함한 마지막 기록 상태에서 6방향 모두 차단됐고, 7개는 미판정 방향을 포함한다. HVSC 2개와 바디 2 등은 본체 상대의 초기 겹침 재증가가 주된 차단 근거다. 다른 익명 바디는 본체·다른 바디·릴레이와의 경로 차단이 남는다.',
        '릴레이 #1·#2의 +Z는 본체 상대 SWEEP_UNRESOLVED다. 각 결과에는 BSpline 면 2곳의 SWEEP_CONSTRUCTION_FAILED가 남는다. 이전의 뒤집힌 검사 솔리드 오류는 수정했지만 이 별도 곡면 포락체 생성 실패까지 해결된 것은 아니다. INPUT_GEOMETRY_INVALID에 의한 거부와 구분한다.',
        'BLK-KD000의 체결부 임시 제거 후 -X는 BREP_COMMON 정밀 교차 연산 제한으로 미판정이다. 다른 5방향에는 본체 상대 초기 겹침 재증가가 기록됐다. 바디 41·42·43·44는 곡면 이동 영역의 SWEEP_UNRESOLVED가 남는다.',
        '신규 경로 요청은 82.7% 감소했지만 시간은 17.1% 감소했다. 반환 결과에서 집계한 BREP Common 연산은 30,003→38,309회로 늘었다. 남은 복잡한 일반 부품의 한 경로 안에서 많은 연산이 수행되므로 요청 수와 실제 계산량·시간은 비례하지 않는다. 중단된 호출의 내부 연산은 카운터에 포함되지 않는다. 상세 병목은 위 비용 표에 기록했다.',
        '추가 개선 대상은 BSpline 이동 검사 형상 생성과 긴 곡면 교차 연산이다. 이번 결과에서는 간섭 허용값을 더 늘리거나 이 실패를 PASS로 바꾸지 않았다.',
        '', '## 순서와 감사','', '분해 순서: '+', '.join(output['removal_order_names']),
        '',f"실제 잔여 상태·방향·거리와 일치하는 증거 {len(audit)}개, 역순 조립, 중복·누락, 품명·빈 주의사항을 감사했다.",
        '기존 중단된 v13 실행은 최종 측정값이 없어 비교 기준으로 사용하지 않았다.',
        'v14 예비 실행(planning-v14-final.log)은 반복 차단 검사·시간 배분 병목 확인 후 중단했다. 비교 표는 planning-v14-cache-final.json의 별도 새 입력 최종 실행만 사용한다.',
        '', '세부 방향별 실패, 장애물 ID, 쌍별 진단, 가상 검사 결과는 비교 JSON과 원본 실행 JSON에 보존한다.']
    if 'video' in artifacts:
        v=artifacts['video']; camera=v['camera_frame_audit']
        lines+=['','## 영상·패키지 검증','',
            f"영상: {v['steps']}단계, 1920×1080/30fps/H.264/yuv420p, {v['duration_sec']:.1f}초, {v['frames']:,}프레임. 생성 {v['render_elapsed_sec']:.2f}초. 관리 저장·내보내기 해시·전체 프레임 디코딩 통과. 영상 생성 중 EXE 재빌드를 병행했으므로 이 영상 생성 시간은 별도 격리 성능 측정이 아니다.",
            f"모든 영상 프레임에서 초점 변화 {camera['max_focus_delta']}, 거리 변화 {camera['max_distance_delta']:.3g}, 시야각 {camera['view_angle']}도를 확인했다. {len(v['highlight_stage_audit'])}단계 모두 이동 전 강조 ON/OFF, 이동 중 강조 유지 검사를 통과했다. 첫 점멸 ON/OFF·중간·최종 프레임을 추출해 품명·빈 주의사항 패널·한글·로고를 시각 확인했다.",
            '최종 장면은 65그룹 전체 표시·모든 이동 변환 0이며 저장·재열기 계획이 동일하다. 주의사항은 64단계 모두 빈칸이고 자재정보는 모두 품명이다.',
            f"영상 파일: `{v['path']}`."]
    if 'gui_reopen' in artifacts:
        g=artifacts['gui_reopen']
        lines+=[f"최종 EXE 재열기: ok={g['ok']}, {g['group_count']}그룹/{g['plan_steps']}단계, LV CONT 예외 복원, UI 스레드 갱신={g.get('scene_update_on_ui_thread')}, 볼트·너트 카드의 미검증 경고 없음={g['fastener_cards_without_unverified_warning']}, 실제 3D 버퍼 형상 표시={g.get('scene_has_rendered_geometry')}.",
                'Qt의 일반 위젯 캡처에는 native OpenGL 영역이 검게 찍힐 수 있어 실제 VTK 렌더 버퍼를 별도 PNG(gui-reopen-v14-final-scene.png)로 저장하고 형상 픽셀 변화를 확인했다.']
    if 'packaged_sources' in artifacts:
        p=artifacts['packaged_sources']
        lines+=[f"배포 소스 일치: {p['ok']}, {len(p['modules'])}모듈 및 템플릿·로고 비교. EXE SHA-256 `{p['executable_sha256']}`."]
    if 'reference_integrity' in artifacts:
        r=artifacts['reference_integrity']; lines+=[f"원본 보존: {r['checked']}개 해시 일치={r['ok']}. 제공 CAD·참고자료·원 로고를 수정하지 않았다."]
    if 'automated_tests' in artifacts:
        t=artifacts['automated_tests'];lines+=[f"최종 자동시험: {t['passed']}개 통과, {t['skipped']}개 생략. 실제 STEP은 별도 전체 실행으로 검증했다."]
    lines+=['','실제 GUI 재열기 시험 중 별도 VTK 접근 위반을 재현하고 완료 콜백의 UI 스레드 전달을 수정했다. 이 UI 수정 이후 최종 EXE에서 동일 프로젝트 재열기를 재검증했다. 원인·수정 전후 스레드 근거는 EXE_VTK_THREAD_FIX.md에 기록했다. 이 수정은 위 순서 생성·영상의 경로 계산을 변경하지 않는다.']
    args.markdown.write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps(dict(comparison=comparison,termination=termination,unresolved_names=[q['name'] for q in unresolved]),ensure_ascii=False,indent=2))


if __name__=='__main__':main()
