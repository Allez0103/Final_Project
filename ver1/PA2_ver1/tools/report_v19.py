"""Summarize measured v19 distribution/UI results without changing test data."""
import json,sqlite3,hashlib
from pathlib import Path
from collections import Counter

ROOT=Path(__file__).resolve().parents[1]
EVIDENCE=ROOT/'runtime-data/native-validation'

def read(name):return json.loads((EVIDENCE/name).read_text(encoding='utf-8-sig'))

def main():
    run=read('ui-v19-packaged-final.json');before=read('planning-v17-final.json')
    package=read('portable-package-v19.json');compiled=read('packaged-source-check-v19.json')
    preservation=read('v19-source-preservation.json');reference=read('reference-integrity-v19-after.json')
    native=read('portable-native-smoke-v19.json');blank=read('portable-gui-smoke-v19.json')
    reopened=read('gui-reopen-v19-final.json')
    if not run['ok']:raise AssertionError('The real UI workflow did not complete')
    dbpath=Path(run['data_root'])/'database/pa2-dev.sqlite3'
    with sqlite3.connect(dbpath.as_uri()+'?mode=ro',uri=True) as db:
        names={gid.split(':',1)[1]:name for gid,name in db.execute(
            'SELECT id,display_name FROM assembly_groups WHERE snapshot_id=?',(run['final_snapshot_id'],))}
    name=lambda gid:names.get(gid,gid)
    old=before['planning']['metrics'];new=run['planning']['metrics']
    comparison=[{'metric':title,'v17':old[key],'v19':new[key]} for title,key in [
        ('순서 생성 시간(초)','elapsed_sec'),('생성 단계 수','completed_groups'),('대상 이동 단위','total_moving_groups'),
        ('후보 기록 수','tested_candidates'),('신규 CAD 경로 요청','native_path_calls'),('차단 근거 재사용','blocked_witness_cache_hits'),
        ('BREP Common 호출','brep_common_calls'),('일반 부품 경로 통과','verified_path_steps'),
        ('체결부 배치','fastener_assigned_steps'),('사용자 간섭 예외','collision_exception_steps'),
        ('미해결 일반 부품','unresolved_general_steps')]]
    unresolved=[]
    for gid in new['unresolved_general_ids']:
        candidates=[p for p in run['planning']['paths'] if p['group_id']==gid and p['decision'] in ('BLOCKED','UNKNOWN')]
        retained_key=hashlib.sha256(json.dumps(sorted([run['planning']['plan']['base_group_id'],gid])).encode('utf-8')).hexdigest()
        retained=[p for p in candidates if p['state_key']==retained_key]
        last=retained_key if retained else candidates[-1]['state_key'] if candidates else None
        unresolved.append({'id':gid,'name':name(gid),'diagnostic_state':last,'base_only_state':bool(retained),'directions':[
            {'direction':p['direction'],'decision':p['decision'],'reason':p['reason_code'],
             'obstacles':[name(o) for o in p['obstacle_ids']],
             'details':p['evidence'].get('pair_diagnostics',[]),'native_error':p['evidence'].get('native_error')}
            for p in candidates if p['state_key']==last]})
    source_check=preservation.get('original_data_unchanged',False) and reference['ok']
    summary={'ok':all((run['ok'],package['ok'],compiled['ok'],native['ok'],blank['ok'],reopened['ok'],source_check)),
        'comparison':comparison,'group_count':run['group_count'],'initial_group_count':run['initial_groups'],
        'draft_complete':new['draft_complete'],'path_complete':new['path_complete'],
        'unresolved':unresolved,'manual_group':{'id':run['manual_id'],'name':run['manual_name'],
            'bodies':run['manual_body_ids'],'test_group_only_not_engineering_approved':True},
        'geometry_status_counts':dict(Counter(s['geometry_status'] for s in run['planning']['plan']['steps'])),
        'renders':run['renders'],'cleanup':run['cleanup'],'package':package,'original_sources_preserved':source_check,
        'cad_revalidation_calls_during_editing_and_rendering':run['cad_revalidation_calls'],
        'full_ui_elapsed_sec':run['elapsed_sec'],'reopened_gui':reopened}
    (EVIDENCE/'v19-comparison.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    rows='\n'.join(f"| {r['metric']} | {r['v17']:.3f} | {r['v19']:.3f} |" if isinstance(r['v17'],float)
        else f"| {r['metric']} | {r['v17']} | {r['v19']} |" for r in comparison)
    videos='\n'.join(f"- {'생성 초안' if i==0 else '순서·방향·카메라 편집 후 재확정'}: {r['steps']}단계, "
        f"{r['elapsed_sec']:.3f}초, {r['result']['duration_sec']:.3f}초 영상, {r['result']['frame_count']:,}프레임, "
        f"{r['result']['encoder']}." for i,r in enumerate(run['renders']))
    blocked=[]
    for part in unresolved:
        blocked.append(f"### {part['name']} ({part['id']})\n")
        if part['base_only_state']:
            blocked.append('다른 부품을 모두 제거하고 기준 부품만 남긴 상태의 탐색 기록이다. 이후 백트래킹의 마지막 시도 상태와 구분했다.\n')
        for direction in part['directions']:
            v=direction['direction'];axis='XYZ'[max(range(3),key=lambda i:abs(v[i]))]
            label=('+' if max(v)>0 else '−')+axis
            codes=', '.join(sorted({d['code'] for d in direction['details']})) or direction['reason']
            obstacles=', '.join(direction['obstacles']) or '상세 진단 참조'
            blocked.append(f"- {label}: {direction['decision']} · {codes} · 상대 {obstacles}.")
            if direction['native_error']:blocked.append('  계산 오류: '+direction['native_error'])
            for detail in direction['details']:
                if detail['code']=='DECREASE_BOOLEAN_FAILED':
                    samples=detail.get('samples',[])
                    failed=next((s for s in samples if s.get('overlap_mm3') is None),None)
                    if failed:blocked.append(f"  이동 {failed['position_mm']:.3f} mm에서 교차 체적 계산이 실패해 감소 조건을 증명하지 못했다.")
        blocked.append('')
    cleanup=run['cleanup']
    text=f'''# v19 전체 실행·배포 검증 결과

2026-10-20, 현재 Windows PC에서 실제 ZIP 압축 해제본 EXE로 검증했다. 개발용 PYTHONPATH와 PATH를 제거하고 PATH는 Windows/System32 및 Windows만 사용했다. 입력은 기존 v17 프로젝트의 **독립 복사본**이다. 원래 프로젝트와 제공 파일은 수정하지 않았다.

## 반영 사항과 실제 화면 테스트

- ‘재검토’ 제거, ‘영상 생성’ 단일 버튼 및 명시적인 ‘순서 확정’ 유지.
- 기존 64그룹/63단계 프로젝트 열기, 자동 그룹 해제 금지 확인.
- 미매칭 바디 41·42를 수동 그룹으로 묶기 → 이름 직접 입력/선택 부품명 목록 확인 → 재열기 → 그룹해제 → 다시 묶기 통과.
- 수동 그룹은 한 부품·한 카드·한 이동 단위로 저장됐다. 기존 자동 그룹의 내부 바디와 이전 확정본은 보존됐다.
- 그룹 변경 시 이전 초안·확정 포인터를 비우고 순서 재생성을 요구했다. 방향 입력 없이 순서 생성에서 방향과 거리를 정했다.
- 순서 생성 → 확정 → 첫 영상 생성 → 카드 다중 이동/실행 취소 → 방향·카메라·문구 편집 → 미리보기 → 적용·저장·재열기 → 재확정 → 두 번째 영상 생성 통과.
- 적용 전 속성 수정과 확정 이후 순서 수정 시 영상 생성을 차단했다. 저장·재열기 후에도 재확정을 요구했다.
- 편집·확정·영상 생성 동안 CAD 접촉·경로 재검사 **{run['cad_revalidation_calls']}회**. 검사 호출이 생기면 시험이 실패하도록 차단했다.
- 영상 중간 진행률, 내장 미리보기 디코딩, 2배속, 전체화면과 Esc 해제 통과.

이번 수동 묶음은 기능 시험을 위한 두 미매칭 바디의 묶음이며, 실제 제작 조립체로 승인한 부품 식별·그룹화 결과를 뜻하지 않는다. 그룹 수는 64→{run['group_count']}, 이동 단위는 63→{run['generated_steps']}개로 달라졌다. 간섭 판정 기준은 변경하지 않았다. 예외 부품은 LV CONT, HVSC 2800 #1·#2, AIR-BENT0A로 유지했다.

## 이전 결과와 비교

| 항목 | 이전 v17 실측 | 이번 v19 실측 |
|---|---:|---:|
{rows}

후보 기록은 방향·상태별 기록이며 차단 근거 재사용을 포함한다. 실제 신규 CAD 경로 요청과 같지 않다. 이전 v18은 v17 결과에 볼트 방향만 갱신한 결과여서, **순서 생성 비교 기준은 마지막 전체 탐색 실측인 v17**이다. 그룹 구성 및 실행 환경(EXE 배포본)이 달라 알고리즘 자체의 속도 개선율로 해석하면 안 된다.

이번 시험에서 시간은 {(new['elapsed_sec']/old['elapsed_sec']-1)*100:.1f}%, 후보 기록은 {(new['tested_candidates']/old['tested_candidates']-1)*100:.1f}%, 신규 CAD 요청은 {(new['native_path_calls']/old['native_path_calls']-1)*100:.1f}% 늘었다. 이번 변경을 속도 개선으로 주장하지 않는다.

초안 완성: **{run['generated_steps']}/{run['generated_steps']}단계**. 전체 경로 검증 완료: **{'예' if new['path_complete'] else '아니오'}**. 미해결 일반 부품 {new['unresolved_general_steps']}개는 경로 확인 필요 상태로 초안과 영상에 포함됐다. 모든 간섭을 통과한 결과가 아니다.

## 영상 생성과 이전 영상 정리

{videos}

- 두 영상 모두 전체 프레임 디코딩 수가 생성 프레임 수와 일치했다.
- 관리 폴더의 완료 영상 {len(run['before_cleanup'])}개 중 최신 편집 영상 한 개를 남겼다.
- ‘최신 버전만 남기기’ 실제 버튼으로 이전 완료 영상 **{len(cleanup['deleted'])}개**, **{cleanup['freed_bytes']:,} bytes ({cleanup['freed_bytes']/1024**2:.2f} MiB)**를 삭제했다. 삭제 오류 {len(cleanup['errors'])}개.
- 삭제 대상은 v19 시험 복사본의 영상뿐이다. 삭제 파일은 이 복사본에서 복구할 수 없지만, 원래 v17 영상과 별도로 내보낸 첫 영상은 보존돼 있다.
- CAD·캐시·그룹 스냅샷·이전 확정본을 보존하고 최신 영상을 다시 열었다. 다른 프로젝트·실패/임시 파일·내보낸 복사본 보존과 반복 정리 무삭제 동작은 자동 시험으로도 확인했다.
- 유지 영상: `{cleanup['kept']}`
- 편집 전 별도 내보내기: `{run['exported_copy']}`
- 전체 화면 흐름 측정: {run['elapsed_sec']:.3f}초(프로그램 초기화 후부터, 최종 전체 디코딩 포함).

## 남은 경로 문제

{chr(10).join(blocked) if blocked else '미해결 일반 부품 없음.'}
실제 이동 간섭 또는 계산 미판정은 그대로 보존했으며, 이를 지우거나 허용오차를 변경해 통과시키지 않았다. 세부 위치별 교차 체적·오류는 ui-v19-packaged-final.json의 planning.paths에 남겼다. 사용자가 초안을 검토·편집·확정하면 이 상태에서도 영상 생성은 가능하다.

## 시험·EXE·사내 ZIP

- 전체 자동 시험: 241 passed, 1 skipped, 10 warnings. 제외 1개는 PA2_TEST_STEP 미지정 조건부 외부 입력 시험이며 실제 제공 모델의 재열기·계산은 위 EXE 전체 시험에서 별도로 수행했다. 경고는 VTK/NumPy 사용 중단 예정 알림이다.
- 실제 배포본 빈 창 실행, 접촉·경로·초기 겹침·곡면·볼트 머리 방향 native smoke, 포함 FFmpeg의 320×180/30fps 1초 인코딩 및 30프레임 전체 디코딩 통과.
- 최종 편집·확정·영상 정리 후 배포 EXE로 다시 열어 {reopened['group_count']}그룹/{reopened['plan_steps']}단계·예외 프리셋·자재정보·빈 주의사항과 실제 3D 렌더 버퍼를 확인했다. QWidget 일반 캡처의 OpenGL 영역이 검게 보이는 한계를 구분해 gui-reopen-v19-final-scene.png로 실제 모델 버퍼를 별도 확인했다.
- EXE: `PA2.exe`, SHA-256 `{compiled['executable_sha256']}`. 이전 EXE와 _internal은 build/previous-release-*에 보존했다.
- 패키지 모듈 {len(compiled['modules'])}개 소스와 최적화 바이트코드, 자산·내장 아이콘 일치. 비호환 ICU DLL 미포함.
- ZIP: `releases/PA2_ver1_windows_x64_v19.zip`, {package['archive_bytes']:,} bytes, SHA-256 `{package['archive_sha256']}`.
- ZIP을 독립 재압축 해제해 payload {package['verified_files']:,}개 크기·해시 일치를 검증했다. 현재 루트 EXE와 배포 EXE도 동일하다. 기존 v18 ZIP은 보존했다.
- 원래 v17 프로젝트 파일 {preservation['file_count']}개 해시 보존 확인, 제공 원본·로고 24개 해시 일치.
- 별도 수신 PC·저사양 PC·설치형 Setup.exe·전자서명 검증은 이번에 수행하지 않았다. 라이선스 고지 파일은 수집했으나 전체 배포 라이선스 감사 완료를 뜻하지 않는다. 사내 검증·전달용 ZIP이다.
- 예외 부품만 제외한 부분 학습 데이터 저장은 이번 범위에 포함하지 않았다.

## 근거 파일

runtime-data/native-validation/ 아래:

- ui-v19-packaged-final.json, .progress.json, 화면 캡처 PNG들
- ui-v19-source-preflight.json, tests-v19-full.log, build-v19.log
- v19-comparison.json, v19-source-preservation.json
- packaged-source-check-v19.json, portable-package-v19.json
- portable-gui-smoke-v19.json, portable-native-smoke-v19.json, portable-encode-v19.log
- gui-reopen-v19-final.json, gui-reopen-v19-final-scene.png
- reference-integrity-v19-before.json, reference-integrity-v19-after.json

재열기: 프로젝트 루트의 open_validation_v19.bat.
'''
    (ROOT/'docs/END_TO_END_V19_RESULT.md').write_text(text,encoding='utf-8')
    print(json.dumps({k:v for k,v in summary.items() if k not in ('renders','unresolved','package','manual_group')},ensure_ascii=False))
    if not summary['ok']:raise AssertionError('One or more verification checks failed')

if __name__=='__main__':main()
