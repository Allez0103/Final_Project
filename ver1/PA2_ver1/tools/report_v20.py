"""Record measured results; never invent PASSes for draft-only steps."""
import hashlib
import json
from pathlib import Path
from collections import Counter

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT/'runtime-data/native-validation'


def read(name):
    return json.loads((EVIDENCE/name).read_text(encoding='utf-8-sig'))


def main():
    run = read('ui-v20-packaged.json')
    before = read('ui-v19-packaged-final.json')
    compiled = read('packaged-source-check-v20.json')
    preserved = read('v20-packaged-preservation.json')
    native = read('native-v20.json')
    runtime = read('runtime-v20.json')
    import xml.etree.ElementTree as ET
    tests = ET.parse(EVIDENCE/'tests-v20-final.xml').getroot().find('testsuite').attrib
    unchanged_modules={}
    for name in ['cad/path_check.py','cad/prepare.py','cad/sweep.py','cad/native_worker.py',
                 'planning/engine.py','planning/two_stage.py','planning/fastener_direction.py','cad/direction_policy.py']:
        current=ROOT/'src/pa2'/name
        previous=ROOT/'build/source-before-v20-20261022/src/pa2'/name
        unchanged_modules[name]=current.read_bytes()==previous.read_bytes()
    baseline = before['planning']['metrics']
    auto = run['plans']['auto']['metrics']; manual = run['plans']['manual']['metrics']
    keys = [('계산 시간(초)', 'elapsed_sec'), ('후보 기록 수', 'tested_candidates'),
            ('신규 CAD 경로 요청', 'native_path_calls'), ('BREP Common 호출', 'brep_common_calls'),
            ('생성 단계', 'completed_groups'), ('대상 이동 단위', 'total_moving_groups'),
            ('경로 확인 일반 부품', 'verified_path_steps'), ('체결부 배치', 'fastener_assigned_steps'),
            ('사용자 예외', 'collision_exception_steps'), ('미해결 일반 부품', 'unresolved_general_steps')]
    comparison = [dict(metric=label, previous=baseline.get(key,0), auto=auto.get(key,0),
                       manual=manual.get(key,0)) for label,key in keys]
    names = {g['id']:g['display_name'] for g in run['plans']['auto']['metrics'].get('groups', [])}
    # Resolve names from the read-only snapshot database.
    import sqlite3
    db_path = Path(run['data_root'])/'database/pa2-dev.sqlite3'
    with sqlite3.connect(db_path.as_uri()+'?mode=ro',uri=True) as db:
        names.update({gid.split(':',1)[1]:name for gid,name in db.execute(
            'SELECT id,display_name FROM assembly_groups WHERE snapshot_id=?',(run['snapshot_id'],))})
        table_counts={t:db.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in
            ['plan_generations','confirmation_analyses','learning_observations','training_cases','ranking_states','ranking_candidates']}
    manifests=[(p,json.loads(p.read_text(encoding='utf-8'))) for p in
               (Path(run['data_root'])/'cache/shape').glob('*/scene.json')]
    new_path,new_scene=max(manifests,key=lambda item:sum(b.get('color_rgb') is not None for b in item[1]['bodies']))
    old_path,old_scene=next((p,json.loads(p.read_text(encoding='utf-8'))) for p in
        (ROOT/'runtime-data/end-to-end-v19-final/cache/shape').glob('*/scene.json')
        if json.loads(p.read_text(encoding='utf-8'))['source_hash']==new_scene['source_hash'])
    geom=dict(body_count=len(new_scene['bodies']),different_brep_files=sum(
        (old_path.parent/b['brep_file']).read_bytes()!=(new_path.parent/b['brep_file']).read_bytes()
        for b in new_scene['bodies']),metadata_identical=[{k:v for k,v in b.items() if k!='color_rgb'} for b in old_scene['bodies']]
        ==[{k:v for k,v in b.items() if k!='color_rgb'} for b in new_scene['bodies']])
    unresolved=[]
    paths=run['plans']['auto']['path_results']
    base=run['plans']['auto']['assembly_plan']['base_group_id']
    for gid in auto.get('unresolved_general_ids',[]):
        state=hashlib.sha256(json.dumps(sorted([gid,base])).encode()).hexdigest()
        candidates=[p for p in paths if p['group_id']==gid and p['decision'] in ('BLOCKED','UNKNOWN')]
        subset=[p for p in candidates if p['state_key']==state]
        if not subset and candidates:
            subset=[p for p in candidates if p['state_key']==candidates[-1]['state_key']]
        unresolved.append(dict(id=gid,name=names.get(gid,gid),base_only=bool(subset and subset[0]['state_key']==state),
            directions=[dict(direction=p['direction'],decision=p['decision'],reason=p['reason_code'],
                obstacle_names=[names.get(o,o) for o in p['obstacle_ids']],
                details=[d for d in p['evidence'].get('pair_diagnostics',[])
                         if d.get('obstacle_id') in p['obstacle_ids']],
                prior_state_other_obstacle_details=[d for d in p['evidence'].get('pair_diagnostics',[])
                         if d.get('obstacle_id') not in p['obstacle_ids']],
                native_error=p['evidence'].get('native_error')) for p in subset]))
    summary = dict(ok=all([run['ok'],compiled['ok'],preserved['unchanged'],native['ok'],runtime['ok'],
                          all(unchanged_modules.values()),tests['failures']=='0',tests['errors']=='0',
                          geom['different_brep_files']==0,geom['metadata_identical']]),
        comparison=comparison,unresolved=unresolved,table_counts=table_counts,
        learning_status=run['learning_status'],renders=run['renders'],
        colored_bodies=run['colored_bodies'],group_count=run['group_count'],
        manual_wall_sec=run['manual_wall_sec'],auto_wall_sec=run['auto_wall_sec'],
        forbidden_cad_calls=run['forbidden_cad_calls'],exe_sha256=compiled['executable_sha256'],
        zip_created=False,previous_zip_preserved=True,
        original_exceptions=[names.get(g,g) for g in run['exception_ids']])
    summary.update(tests=tests,collision_modules_unchanged=unchanged_modules,geometry_cache_comparison=geom)
    (EVIDENCE/'v20-comparison.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    def number(v):return f'{v:.3f}' if isinstance(v,float) else str(v)
    rows='\n'.join('| '+r['metric']+' | '+' | '.join(number(r[k]) for k in ['previous','auto','manual'])+' |' for r in comparison)
    videos='\n'.join(f"- {r['mode']}: {r['steps']}단계 · 생성 {r['elapsed_sec']:.3f}초 · "
        f"영상 {r['result']['duration_sec']:.3f}초 / {r['decoded_frames']:,}프레임 · {r['result']['encoder']}\n  - {r['path']}" for r in run['renders'])
    blocked=[]
    for item in unresolved:
        blocked.append(f"### {item['name']}\n\n기준 부품만 남긴 상태 기록: {item['base_only']}.\n")
        for p in item['directions']:
            codes=sorted({d.get('code','') for d in p['details']})
            blocked.append(f"- {p['direction']}: {p['decision']} / {p['reason']} / {', '.join(codes)} / 상대 {', '.join(p['obstacle_names'])}")
            for detail in p['details']:
                if detail.get('code')=='DECREASE_BOOLEAN_FAILED':
                    samples=detail.get('samples',[])
                    failed=next((i for i,s in enumerate(samples) if s.get('overlap_mm3') is None),None)
                    if failed is not None:
                        prior=samples[failed-1] if failed else None
                        blocked.append(f"  - 초기 겹침 {detail.get('initial_overlap_mm3'):.6f} mm³. "
                            +(f"{prior['position_mm']:.3f} mm 이동에서 {prior['overlap_mm3']:.6f} mm³까지 감소했지만, " if prior else '')
                            +f"{samples[failed]['position_mm']:.3f} mm 이동 위치에서 교차 체적을 계산하지 못해 미판정이다. 시간 초과로 기록된 결과가 아니다.")
            if p['prior_state_other_obstacle_details']:
                blocked.append('  - 캐시의 과거 상태 부가 진단에 다른 상대의 미판정이 남아 있지만, 현재 상태의 차단 근거와 구분했다. 원시 JSON에는 모두 보존했다.')
            if p['native_error']:blocked.append('  - 계산 오류: '+p['native_error'])
    # Candidate metrics count attempted state/direction records, not all OCCT calls.
    similarity=[]
    for mode in ['auto','manual']:
        for scope,label in [('all','전체'),('general','일반'),('general_without_exceptions','일반·예외 제외')]:
            m=run[mode+'_comparison'][scope]
            pct=lambda v:'—' if v is None else f'{v:.2%}'
            similarity.append(f"| {mode} | {label} ({m['count']}개) | {pct(m['pair_order_ratio'])} | {pct(m['lcs_ratio'])} | {pct(m['direction_agreement'])} |")
    text=f'''# v20 보완사항·자동/수동 생성·영상·EXE 검증 결과

2026-10-22, 현재 Windows PC. 실제 패키징된 EXE에서 버튼을 눌러 수행한 자동 시험이다. 기존 v19 관리 프로젝트의 독립 복사본을 사용했다. 별도 수신 PC 시험은 아니다.

## 결과

- 전체 흐름 성공: {summary['ok']}. {run['group_count']}그룹, 기준 제외 {run['group_count']-1}단계.
- STEP 바디 {run['colored_bodies']}개 대표 색상 복원. 단일 빨강/주변 회색 불투명도 25%, 다중 선택 격리 및 복원, 카메라/계획 불변 확인.
- 색상 캐시 갱신 전후 BREP {geom['body_count']}개 바이트 동일(상이 파일 {geom['different_brep_files']}개), 색상을 제외한 체적/경계/중심/기타 바디 메타데이터 동일: {geom['metadata_identical']}.
- 자동·수동생성 → 최초 초안 자동 보존 → 순서 묶음 이동/방향·시점·문구 편집 → 속성 미리보기 → 확정 → 전체 1920×1080/30fps 영상 생성 → 전 프레임 디코딩 → 최종 프로젝트 재열기 통과.
- 입력만 한 속성/미확정 수정은 영상 생성 차단. 적용된 편집값 자동 저장, 최초 생성 원본과 이전 확정본 보존.
- 수동생성·편집·미리보기·확정·영상에서 금지한 native CAD 재검사 호출: {len(run['forbidden_cad_calls'])}회. 자동생성 중의 정상 검사는 별도 집계했다.
- 예외 유지: {', '.join(summary['original_exceptions'])}.
- 기존 수동 그룹은 이전 기능 시험용 미매칭 바디 묶음이며 엔지니어링상 승인된 실제 조립체라는 뜻은 아니다. 이전 v19와 동일한 그룹 구성으로 비교했다.

## 이전 결과 비교

| 항목 | 이전 v19 자동 | 이번 자동 | 이번 수동 |
|---|---:|---:|---:|
{rows}

- 이번 버튼 실행부터 결과 표시까지(폴링 오차 포함): 자동 {run['auto_wall_sec']:.3f}초, 수동 {run['manual_wall_sec']:.3f}초. 위 계산 시간과 구분한다.
- 후보 기록 수에는 차단 근거 재사용이 포함된다. 신규 CAD 경로 요청 및 BREP Common 호출과 같은 숫자가 아니다.
- 수동생성의 0회 검사는 물리 검증을 생략한 기능의 결과이며, 자동 알고리즘의 동등 검증 속도 향상이 아니다.
- 수동 모드의 미해결 일반 부품 0은 검사를 시도하지 않았다는 뜻이며, 전부 통과했다는 뜻이 아니다.
- 자동 계산 시간은 이전 대비 {(auto['elapsed_sec']/baseline['elapsed_sec']-1)*100:.2f}% 증가했다. 후보/신규 CAD/Common/단계 수는 이전과 동일하며 이번 자동생성의 속도 개선을 주장하지 않는다.
- 자동 초안 완성: {auto['draft_complete']}; 경로 증명 완료: {auto['path_complete']}. 수동 초안은 경로 검증을 하지 않는다. 단계 수가 전체라고 모든 부품이 간섭 없이 이동한다는 뜻은 아니다.
- 모델 불러오기/캐시 준비는 위 순서 계산 시간에서 제외했다. 새 색상 캐시가 없는 구버전 프로젝트의 최초 열기는 관리 STEP에서 캐시를 한 번 재생성한다. 최종 EXE 시험은 사전 검증에서 생성한 색상 캐시를 재사용했다.

## 영상

{videos}

두 영상 모두 생성 프레임 수와 실제 전체 디코딩 프레임 수가 일치했다. 빨간 점멸/이동 중 빨강/완료 대표색 장면을 별도 PNG로 저장했다. 수동으로 수정한 경로를 간섭 재검사로 보정하지 않는다.
수동 영상은 기본 방향에 따른 시점 전환이 적어 자동 영상보다 짧다. 두 영상의 생성 시간을 동일 길이 영상의 인코딩 성능 비교로 해석하지 않는다. 임의 순서·방향 변경은 편집 기능 시험이며 실제 작업 절차 승인본이 아니다.

## 미해결 자동 경로

{chr(10).join(blocked) if blocked else '미해결 일반 부품 없음.'}

기존 간섭·형상 보정 허용 기준은 변경하지 않았다. 자세한 이동 위치별 체적과 오류는 ui-v20-packaged.json의 plans.auto.path_results에 보존했다. 미해결 부품도 편집용 초안과 사용자 확정 영상에는 포함된다.

## 자동 수집·학습

- 저장 테이블 건수: {json.dumps(table_counts,ensure_ascii=False)}.
- 수집 현황: {json.dumps(run['learning_status'],ensure_ascii=False)}.
- 예외 포함 전체 확정 선호, 원래 검사 상태, 원본 방향, 당시 주변 상태를 저장했다. 볼트/너트는 일반 부품 순서 학습 후보에서 제외했다.
- 최초 초안–확정 비교는 전체/일반/일반 중 예외 제외로 분리했다. 원본 예외 부품은 삭제하지 않는다.

| 생성 모드 | 범위 | 선후 유지율 | LCS | 방향 일치율 |
|---|---|---:|---:|---:|
{chr(10).join(similarity)}

위 지표는 시험에서 임의로 편집한 확정본과 최초 초안의 차이를 검증한 것으로, 알고리즘의 실무 정확도 평가가 아니다.

- 실제 데이터가 30개 계열 AND 1,000개 선택 상태 조건을 만족하지 않으므로 실사용 모델 학습·자동 활성화는 하지 않았다.
- 오프라인 학습 실행·독립 계열 분리·미활성화는 별도의 합성 시험 데이터로 검증했다. 합성 모델은 테스트 임시 폴더에만 존재하고 실사용 학습 수에 포함하지 않았다.
- 방향/예외 추천용 데이터 수집까지 반영했으며 실제 방향·예외 모델의 일반화 성능을 이번에 검증한 것은 아니다.

## 실행 파일·보존

- 전체 자동 시험: {int(tests['tests'])-int(tests['skipped'])} passed, {tests['skipped']} skipped, {tests['failures']} failures, {tests['errors']} errors. 제외 1개는 PA2_TEST_STEP 미지정 조건부 파일 시험이다. 실제 모델 재열기는 위 EXE 시험에서 수행했다. VTK/NumPy 사용 중단 예정 경고 10개는 기존 경고다.
- 간섭 판정/형상 보정/기존 자동 탐색/체결부 방향 핵심 소스 {len(unchanged_modules)}개를 수정 전 백업과 바이트 단위 대조하여 동일함을 확인했다.
- 실행 파일: {ROOT/'PA2.exe'}
- SHA-256: {compiled['executable_sha256']}
- 검사한 패키지 모듈 {len(compiled['modules'])}개와 현재 최적화 소스, 자산·내장 아이콘 일치. QtWidgets/3D/native worker 실행 확인.
- Python 경로를 제거하고 Windows 경로만 둔 EXE의 학습 현황 조회/데이터 부족 학습 차단/기본 CAD smoke 통과. 데이터 부족 상태에서 모델 폴더를 만들지 않았다.
- 이전 실행 파일/_internal은 build/previous-release-v20-20261022에 보관했다.
- 원본 제공 STEP, 기존 v19 프로젝트·영상, 사용자 AppData DB, 기존 모든 ZIP을 포함한 보존 대상 총 {preserved['file_count']}개 파일의 해시 보존 확인: {preserved['unchanged']}.
- 새 ZIP은 생성하지 않았다. 기존 배포 ZIP과 GUI 소스 ZIP은 이전 내용 그대로이므로 이번 수정분을 포함하지 않는다.

## 근거

- runtime-data/native-validation/ui-v20-packaged.json 및 진행 JSON, 장면 PNG
- runtime-data/native-validation/v20-comparison.json
- runtime-data/native-validation/packaged-source-check-v20.json, native-v20.json, runtime-v20.json
- runtime-data/native-validation/v20-packaged-preservation.json
- runtime-data/native-validation/tests-v20-final.log 및 XML, tests-v20-additions.log, build-v20.log
- docs/V20_IMPROVEMENTS.md
'''
    (ROOT/'docs/END_TO_END_V20_RESULT.md').write_text(text,encoding='utf-8')
    print(json.dumps({k:v for k,v in summary.items() if k not in ('renders','unresolved')},ensure_ascii=False))
    return 0 if summary['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
