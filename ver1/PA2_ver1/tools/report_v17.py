"""Write the final measured comparison, unresolved directions and test evidence."""
from pathlib import Path
import json
from collections import Counter
from diagnose_unknowns import load_inputs

ROOT=Path('runtime-data/native-validation')

def read(name):return json.loads((ROOT/name).read_text(encoding='utf-8'))

def main():
    before=read('planning-v16-final.json'); after=read('planning-v17-final.json'); fresh=read('import-v17-final.json')
    old=before['planning']['metrics']; new=after['planning']['metrics']
    groups,_=load_inputs(after,Path('runtime-data/end-to-end-v17-final'))
    name=lambda gid:groups[gid].display_name if gid in groups else gid
    video=read('video-v17-final/video-validation.json'); old_video=read('video-v16-final/video-validation.json')
    ui=read('ui-review-v17-final.json'); package=read('packaged-source-check-v17-final.json')
    integrity=read('reference-integrity-v17-after.json'); hardware=read('hardware-v17.json')
    final_blk=read('blk-final-state-v17.json')
    reopened=read('gui-reopen-v17-final.json'); persistence=read('draft-persistence-v17.json'); native=read('native-smoke-v17-final.json')
    rows=[('그룹 수',before['group_count'],after['group_count']),
          ('원본 입력·그룹화·접촉 준비 (초)',before['contact_elapsed_sec'],fresh['contact_elapsed_sec']),
          ('순서 생성 (초)',old['elapsed_sec'],new['elapsed_sec']),
          ('생성 초안 단계',old['completed_groups'],new['completed_groups']),
          ('이동 대상 단계',old['total_moving_groups'],new['total_moving_groups']),
          ('후보 기록 수',old['tested_candidates'],new['tested_candidates']),
          ('신규 CAD 경로 요청',old['native_path_calls'],new['native_path_calls']),
          ('차단 근거 재사용',old['blocked_witness_cache_hits'],new['blocked_witness_cache_hits']),
          ('부품 쌍 계산',old['pair_calculations'],new['pair_calculations']),
          ('BREP Common 호출',old['brep_common_calls'],new['brep_common_calls']),
          ('일반 부품 경로 통과',old['verified_path_steps'],new['verified_path_steps']),
          ('체결부 배치',old['fastener_assigned_steps'],new['fastener_assigned_steps']),
          ('사용자 예외',old['collision_exception_steps'],new['collision_exception_steps']),
          ('미해결 일반 부품',old['unresolved_general_steps'],new['unresolved_general_steps']),
          ('기본 영상 생성 (초)',old_video['render_elapsed_sec'],video['render_elapsed_sec']),
          ('기본 영상 프레임',old_video['frames'],video['frames'])]
    unresolved=[]
    paths=after['planning']['paths']
    for gid in new.get('unresolved_general_ids',[]):
        tested=[p for p in paths if p['group_id']==gid and p['decision'] in ('BLOCKED','UNKNOWN')]
        state=tested[-1]['state_key'] if tested else None
        last=[p for p in tested if p['state_key']==state]
        unresolved.append({'group_id':gid,'name':name(gid),'last_state':state,
            'directions':[{'direction':p['direction'],'decision':p['decision'],'reason':p['reason_code'],
                           'obstacles':[name(o) for o in p['obstacle_ids']],
                           'diagnostics':p['evidence'].get('pair_diagnostics',[]),
                           'common_retries':p['evidence'].get('common_retries',[]),
                           'native_error':p['evidence'].get('native_error')} for p in last]})
    order=after['planning']['removal_order']; positions={g:i for i,g in enumerate(order)}
    fasteners=[]
    for gid,relation in new['fastener_attachments'].items():
        owners=[g for g in relation['targets'] if g in positions]
        valid=not owners or positions[gid]<min(positions[g] for g in owners)
        fasteners.append({'name':name(gid),'targets':[name(g) for g in owners],'before_targets':valid})
    if not all(r['before_targets'] for r in fasteners):raise AssertionError('Fastener ordering mismatch')
    if len(order)!=len(set(order)) or len(order)!=after['group_count']-1:raise AssertionError('Draft partition mismatch')
    stages=Counter(s['geometry_status'] for s in after['planning']['plan']['steps'])
    improvements={label:100*(1-b/a) for label,a,b in rows if label in ('순서 생성 (초)','신규 CAD 경로 요청','BREP Common 호출','기본 영상 생성 (초)')}
    result={'ok':all(x.get('ok') for x in (video,ui,package,integrity,reopened,persistence,native)),'comparison':[
        {'metric':label,'v16':a,'v17':b} for label,a,b in rows],'reductions_percent':improvements,
        'draft_complete':new['draft_complete'],'path_complete':new['path_complete'],
        'unresolved':unresolved,'fastener_audit':fasteners,'geometry_status_counts':dict(stages),
        'volume_cache_hits':new.get('brep_common_cache_hits',sum(p['evidence'].get('calculation_metrics',{}).get('activity_counts',{}).get('BREP_COMMON_CACHE_HIT',0) for p in paths if p['evidence'].get('evaluation_source')=='native')),
        'video':video,'edited_video':ui,'package':package,'reference_integrity':integrity,
        'post_planning_blk_diagnostic':final_blk,
        'reopened_gui':reopened,'draft_and_confirmation_persistence':persistence,'packaged_native_smoke':native,
        'settings_changes':{k:{'v16':before['settings'].get(k),'v17':v} for k,v in after['settings'].items() if before['settings'].get(k)!=v}}
    (ROOT/'v17-comparison.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    lines=['# v17 전체 실행·편집·영상·배포 검증','',
        '원본 STEP 19개를 새 데이터 폴더에서 불러온 뒤, 저장된 동일 스냅샷으로 순서를 생성하고 전체 영상을 만들었다. 배포 EXE에서 순서·방향을 수정하고 단계 미리보기와 재검토 영상도 시험했다.',
        '', '예외 부품: LV CONT, HVSC 2800 #1/#2, AIR-BENT0A. 기준 부품: '+name(after['planning']['plan']['base_group_id'])+'.',
        '', '| 항목 | 이전 v16 | 이번 v17 |','|---|---:|---:|']
    for label,a,b in rows:lines.append(f'| {label} | {a:.2f} | {b:.2f} |' if isinstance(a,float) else f'| {label} | {a} | {b} |')
    lines+=['',f"순서 생성 시간 변화: {improvements['순서 생성 (초)']:.1f}% 감소. 실제 체적 계산 재사용: {result['volume_cache_hits']}회.",
        '',f"전체 편집 가능 초안은 {new['completed_groups']}/{new['total_moving_groups']}단계다. 자동 경로 확인 완료={new['path_complete']}. 상태별 단계 수={dict(stages)}.",
        '', 'AIR-BENT 두 익명 바디를 하나로 묶어 그룹 수와 이동 단계 수가 각각 1 감소했다. 기존 단계 누락이 아니다. 예외가 3→4개로 바뀌었으며 CPU 4스레드·계산 재사용·입력 변환 방식도 함께 달라졌다. 단일 요소만의 성능 효과로 해석할 수 없다. 실행 중 회귀시험·패키징 부하가 포함됐다.',
        '', '입력 준비 시간은 최초 원본 실행(import-v17-final.json)의 값이다. 계획 보고서의 contact_elapsed_sec는 저장된 스냅샷을 재열고 확인한 시간이므로 최초 입력 시간으로 사용하지 않았다.',
        '', '원본 STEP 불러오기 로그의 GeometricSet B-spline 곡선 Poles/degree mismatch 경고는 이전 v16과 이번 v17에서 각각 2건으로 동일하다. 이번에도 176솔리드를 불러왔다. 해당 원본 경고와 릴레이의 경로 형상 생성·교집합 오류는 단계가 다른 기록이며, 이번 채택 순서에서 릴레이 두 개는 경로를 통과했다.',
        '', '검사 수에서 후보 기록은 신규 CAD 요청과 차단 근거 재사용 등을 포함한다. Common 수는 결과를 반환한 native 요청의 집계이며, 중단된 요청의 부분 호출은 포함되지 않을 수 있다.',
        '', f"이번 체적 캐시 적중은 {result['volume_cache_hits']}회다. 시간 감소를 이 캐시만의 효과로 볼 수 없다. 일반 부품 경로 통과 수는 17개로 동일하며, 미해결 3→1 감소에는 AIR-BENT 두 바디의 그룹화·예외 지정이 반영됐다.",
        '', f"되돌아가기 집계={new['backtracks']}, 고유 잔여 상태={new['unique_states']}, native 시간 초과={new['native_timeout_count']}. 되돌아가기 상한에 도달한 후 호출 복귀 집계가 더해질 수 있다. 전체 시간 제한이 끝나서 초안을 중단한 결과는 아니다.",
        '', '## 남은 부품·방향별 원인','']
    if not unresolved:lines+=['미해결 일반 부품이 없다. 예외·체결부 배치의 경로 검증 생략 정책은 그대로 적용됐다.']
    for row in unresolved:
        lines+=['### '+row['name'],'','아래 표는 탐색에서 마지막으로 검사한 잔여 상태다. 최장 채택 순서의 마지막 상태와 다를 수 있다.','', '| 분해 방향 | 판정 | 관련 부품 | 상세 코드 |','|---|---|---|---|']
        for d in row['directions']:
            codes=[v.get('code') for v in d['diagnostics']]
            lines.append(f"| {d['direction']} | {d['decision']} | {', '.join(d['obstacles'])} | {codes} {d['native_error'] or ''} |")
        lines+=['','각 위치별 체적, Boolean 재시도와 보정 거부 근거는 v17-comparison.json과 planning-v17-final.json에 포함한다. 이는 검사한 직선 경로의 결과이며 모든 분해 방법의 불가능 증명은 아니다.']
    lines+=['','### BLK의 기준 부품만 남긴 최종 상태 추가 진단','',
        f"{final_blk['moving']}와 {final_blk['obstacle']}만 남겨 6축을 별도로 검사했다. 이 진단 {final_blk['elapsed_sec']:.2f}초와 6회 요청은 위 순서 생성 시간·검사 수에 포함하지 않으며 저장된 초안을 변경하지 않았다.",
        '', '| 방향 | 판정 | 상세 |','|---|---|---|']
    for p in final_blk['paths']:
        details=p['evidence'].get('pair_diagnostics',[])
        codes=[d['code'] for d in details]
        last=[d.get('samples',[])[-1] for d in details if d.get('samples')]
        lines.append(f"| {p['direction']} | {p['decision']} | {codes}; 마지막 표본 {last} |")
    lines+=['', '−X 14.5mm에서는 입력 BLK가 아니라 새로 계산한 교집합 결과가 유효하지 않다. 인자 역순·기존 제한의 보정 재시도도 통과하지 못했다. 나머지 5축은 겹침 체적 재증가로 차단됐다. blk-final-state-v17.json에 위치별 체적과 재시도 근거를 보존했다.']
    lines+=['','## 카메라·영상·사용자 편집','',
        f"기본 영상: {video['path']}. {video['frames']}프레임 전체 디코딩 확인, {video['duration_sec']:.2f}초, 인코더 {video['encoder']}.",
        f"카메라 프레임 간 최대 회전: {video['camera_orientation_audit']['maximum_frame_rotation_deg']:.4f}도. 고정 초점·거리·화각, 이동 전 점멸·이동 중 하이라이트를 확인했다.",
        f"실제 EXE에서 수정 후 재검토: {ui.get('render_elapsed_sec',0):.2f}초, {ui.get('decoded_frame_count')}프레임 전체 디코딩. 단계 미리보기 입력값·복귀={ui.get('step_preview_pending_edits_and_restore')}, CAD 재검사={ui.get('cad_revalidation_calls')}회.",
        f"영상 진행도·배속·탐색·Esc 전체화면 해제={ui.get('progress_observed')}/{ui.get('playback_rate')}/{ui.get('seek_supported')}/{ui.get('fullscreen_escape')}.",
        f"EXE 종료 후 재열기={reopened['ok']}, 편집 순서·방향 저장 및 이전 확정본 보존={persistence['ok']}. 두 확정본을 저장소에서 다시 읽어 비교했다.",
        '', '동일 90프레임의 CPU/GPU 인코딩 시간·파일 크기·복호화 PSNR은 video-encoder-v17.json에 기록했다. 인코더별 품질 설정 척도가 다르므로 동일 화질의 엄밀한 속도 비교는 아니다. 전체 렌더 시간과 인코딩 단독 시간을 구분한다.',
        '', '동일한 2단계 실제 CAD 짧은 영상의 전체 렌더도 CPU 약 12.66초, NVIDIA 약 13.01초로 모두 통과했다. video-v17-preflight 및 video-v17-gpu-preflight 기록을 참조한다. 전체 렌더에는 메시 준비·장면·템플릿 생성·인코딩·검증이 포함된다.',
        '', '## 시험 환경·배포·원본 보존','',
        f"CPU: Intel Core Ultra 7 255H, 논리 {hardware['logical_cpus']}개, RAM {hardware['ram_bytes']/1024**3:.1f}GiB. VTK 장치는 hardware-v17.json의 OpenGL renderer를 따른다.",
        '', '배포: ver1/PA2/PA2.exe, 의존 파일은 PA2/_internal. 검증 데이터 열기: open_validation_v17.bat. 새 노란색 위첨자 아이콘의 PNG/ICO도 번들 일치를 확인했다.',
        '',f"배포 코드·자산 일치={package['ok']}, EXE SHA-256={package['executable_sha256']}.",
        f"제공 원본·원본 로고 해시 {integrity['checked']}개 보존 확인={integrity['ok']}.",
        '', '회귀시험 결과는 tests-v17-delivery.log 및 tests-v17-build.log에 기록했다. 실제 제공 STEP은 별도 전체 입력 실행으로 확인했다. 개발 도구가 없는 별도 PC 검증은 수행하지 않았다.',
        '', '## 보완 중 시험 기록','',
        '썸네일 순차 생성으로 바꾼 뒤 즉시 아이콘 생성을 가정하던 기존 시험의 대기 조건을 수정했다. 인코더 정지 시험은 외부 인코더 경로 탐지까지 가로채던 시험 코드와 빈 합성 장면을 수정하고 다시 검증했다.',
        '', '형상 체적 캐시의 실제 동일성 검증을 보강하기 위해 예비 순서 탐색을 중단했다. 해당 로그는 planning-v17-preflight.*에 보존하며 최종 성능 비교에서 제외했다.',
        '', 'BLK의 일반 ShapeFix 교집합은 유효해졌지만 체적이 약 0.333277→0.334026mm³로 바뀌었다. 입력 보정과 간섭 기준을 완화해 채택하지 않았다. 최종 자동 경로 미완료가 남으면 위 방향별 기록을 기준으로 사용자 편집 또는 별도 계산 개선이 필요하다.',
        '', '상세 수정 목록: CHANGES_V17.md.']
    Path('docs/END_TO_END_V17_RESULT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps({'ok':result['ok'],'steps':new['completed_groups'],'elapsed_sec':new['elapsed_sec'],'unresolved':[r['name'] for r in unresolved]},ensure_ascii=False))

if __name__=='__main__':main()
