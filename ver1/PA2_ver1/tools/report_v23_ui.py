"""Summarize evidence from the real packaged UI workflow, not inferred claims."""
import hashlib
import json
import sqlite3
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]


def read(name):return json.loads((ROOT/name).read_text(encoding='utf-8'))


def main():
    old=read('runtime-data/native-validation/ui-v20-packaged.json')
    now=read('build/v23-packaged.json')
    package=read('build/v23-installed-source-check.json')
    preservation=read('build/v23-preservation.json')
    runtime=read('build/v23-installed-runtime.json')
    assert now['ok'] and package['ok'] and preservation['unchanged'] and runtime['ok']
    backup=ROOT/'build/source-before-v23-ui-20261022/src/pa2'
    allowed={'ui/main_window.py','ui/model_editor.py','ui/theme.py','rendering/vtk_scene.py'}
    sources=[]
    for p in backup.rglob('*.py'):
        rel=p.relative_to(backup).as_posix();target=ROOT/'src/pa2'/rel
        sources.append(dict(path=rel,identical=p.read_bytes()==target.read_bytes(),ui_change=rel in allowed))
    assert all(r['identical'] or r['ui_change'] for r in sources)
    metrics=['elapsed_sec','tested_candidates','native_path_calls','brep_common_calls',
             'verified_path_steps','fastener_assigned_steps','collision_exception_steps','unresolved_general_steps']
    compare={}
    for mode in ('auto','manual'):
        compare[mode]={tag:{k:result['plans'][mode]['metrics'].get(k,0) for k in metrics}
                       for tag,result in [('previous',old),('current',now)]}
        for tag,result in [('previous',old),('current',now)]:
            compare[mode][tag]['steps']=len(result['plans'][mode]['assembly_plan']['steps'])
    suites=[]
    for name in ('v23-regression','v23-retained'):
        suite=ET.parse(ROOT/f'build/{name}.xml').getroot()[0]
        suites.append({**suite.attrib,'name':name})
    summary=dict(ok=True,comparison=compare,tests=suites,sources=sources,
        unchanged_non_ui_sources=all(r['identical'] or r['ui_change'] for r in sources),
        package=package,runtime=runtime,preservation={k:v for k,v in preservation.items() if k!='files'},
        videos=now['renders'],ui_contracts=now['ui_contracts'],
        forbidden_cad_calls=now['forbidden_cad_calls'],model_training_performed=False)
    (ROOT/'build/v23-summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    lines=['# v23 팀원 UI 통합·전체 구동 검증 결과','',
        '2026-10-22, 현재 Windows PC. 현재 v22 기능과 알고리즘을 유지하면서 팀원 UI v7을 이식했다. 별도 수신 PC 시험은 아니다.','',
        '## 결과','',
        f"- 패키징된 EXE 전체 흐름 성공: {now['ok']}. {now['group_count']}그룹, 기준 제외 {len(now['plans']['auto']['assembly_plan']['steps'])}단계.",
        '- 기존 프로젝트 독립 복사본 → 수동생성 → 편집·속성 미리보기·확정 → 전체 영상 → 자동생성 → 편집·확정 → 전체 영상 → 최종 프로젝트 재열기 통과.',
        '- 최초 생성 원본 보존, 적용 편집값 자동 저장, 미적용 속성/미확정 순서의 영상 생성 차단을 확인했다.',
        f"- 수동생성·선택·편집·미리보기·영상 중 금지한 CAD 재검사 호출: {len(now['forbidden_cad_calls'])}회.",
        '- 예외 부품 LV CONT, AIR-BENT0A, HVSC 2800 #1·#2 유지. 자동/수동 초안의 전체 단계 생성은 물리 검증 완료를 뜻하지 않는다.','',
        '## UI 변경과 기존 기능 유지','',
        '- 파란 테마, THN 로고, 좌측 부품·중앙 3D·우측 속성·하단 카드 배치.',
        '- 카드 다중 드래그·삽입 미리보기·가장자리 스크롤·현재 재생 카드 강조.',
        '- 회전/이동/맞춤/시점/확대·축소/숨김 도구, 지연 누적 없는 카메라 조작, 최대 4배속 3D 재생.',
        '- 빨간 면 선택, 단일 선택 시 주변 회색·25% 불투명도, 가림 보완 표시층, 작은 부품의 복원 가능한 표시용 돌출.',
        '- STEP 대표색을 기본·해제·썸네일·영상에 유지. 이동 전 점멸/이동 중 빨강/완료 원래색을 유지.',
        '- 편집용 돌출·가림 보완·주변 반투명 효과는 영상에 넣지 않는다. 영상은 정확한 이동 좌표와 기존 불투명도를 사용한다.',
        '- 반복 속성 미리보기 후 카메라·가시성·투명도·색상·표시용 위치·선택 표시층을 복원한다.',
        '- 수동생성, 자동 저장, 기준/예외 지정, 수동 그룹화 보호, 학습 현황·설정·모델 연결 유지. 모델 학습/평가/자동 적용 시험은 하지 않았다.','',
        '## 이전 v20 실제 제품 결과와 비교','',
        'v21/v22에는 동일 제품 전체 벤치마크가 없으므로 마지막 전체 구동 기록 v20을 비교 기준으로 사용했다. 동일 관리 프로젝트·그룹 구성·설정이며, 모델 열기 시간은 순서 계산 시간에 포함하지 않는다.','',
        '| 항목 | 이전 자동 | 이번 자동 | 이전 수동 | 이번 수동 |',
        '|---|---:|---:|---:|---:|']
    for key,label in [('elapsed_sec','계산 시간(초)'),('tested_candidates','후보 기록'),
        ('native_path_calls','신규 CAD 경로 요청'),('brep_common_calls','BREP Common 호출'),
        ('steps','생성 단계'),('verified_path_steps','경로 확인 일반 부품'),
        ('fastener_assigned_steps','체결부 배치'),('collision_exception_steps','사용자 예외'),
        ('unresolved_general_steps','미해결 일반 부품')]:
        values=[compare[m][t][key] for m,t in [('auto','previous'),('auto','current'),('manual','previous'),('manual','current')]]
        texts=[f'{v:.3f}' if key=='elapsed_sec' else str(v) for v in values]
        lines.append('| '+label+' | '+' | '.join(texts)+' |')
    lines+=['','후보 기록에는 차단 근거 재사용이 포함된다. 신규 경로 요청/Common 호출과 구분한다. UI 이식에 따른 알고리즘 속도 개선을 주장하지 않는다. 수동생성의 검사 0회는 검증 생략 정책이며 간섭 통과를 뜻하지 않는다.','',
        '## 영상 생성','']
    for r in now['renders']:
        v=r['result'];assert r['decoded_frames']==v['frame_count']
        lines += [f"- {r['mode']}: {r['steps']}단계, 생성 {r['elapsed_sec']:.3f}초, 영상 {v['duration_sec']:.3f}초 / {v['frame_count']:,}프레임, {v['encoder']}.",
                  f"  - `{r['path']}`"]
    lines+=['','두 영상 모두 1920×1080/30fps 전체 생성 후 전 프레임 디코딩 수가 일치했다. 순서 묶음·방향·카메라·문구를 임의 변경한 기능 시험이며 실제 작업 절차 승인본이 아니다.',
        '이번에는 기존 자동 인코더 선택 기능이 NVENC를 선택했다. 이전 v20은 libx264였으므로 영상 생성 시간의 차이를 동일 인코더 성능이나 UI 이식에 따른 최적화 효과로 해석하지 않는다.','',
        '## 남은 자동 경로 문제','']
    auto=now['plans']['auto'];ids=auto['metrics'].get('unresolved_general_ids',[])
    with sqlite3.connect((Path(now['data_root'])/'database/pa2-dev.sqlite3').as_uri()+'?mode=ro',uri=True) as db:
        names={gid.split(':',1)[1]:name for gid,name in db.execute(
            'SELECT id,display_name FROM assembly_groups WHERE snapshot_id=?',(now['snapshot_id'],))}
    for gid in ids:
        lines += [f"### {names.get(gid,gid)}",'',f'그룹 ID: `{gid}`. 미해결 단계도 검토·편집용 초안에 포함되며, 통과로 변경하지 않는다.','']
        paths=[p for p in auto['path_results'] if p['group_id']==gid]
        base=auto['assembly_plan']['base_group_id']
        key=hashlib.sha256(json.dumps(sorted([gid,base])).encode()).hexdigest()
        subset=[p for p in paths if p['state_key']==key and p['decision'] in ('BLOCKED','UNKNOWN')]
        base_only=bool(subset)
        if not subset and paths:subset=[p for p in paths if p['state_key']==paths[-1]['state_key']]
        lines.append(f'기준 부품만 남긴 상태의 검사 기록: {base_only}.')
        for p in subset:
            evidence=p.get('evidence',{})
            details=[d for d in evidence.get('pair_diagnostics',[]) if d.get('obstacle_id') in p['obstacle_ids']]
            codes=sorted({d.get('code','') for d in details})
            lines.append(f"- 방향 {p.get('direction')}: {p.get('decision')} / {p.get('reason_code')} / {', '.join(codes)} / 상대 {', '.join(names.get(g,g) for g in p['obstacle_ids'])}")
            for d in details:
                if d.get('code')=='DECREASE_BOOLEAN_FAILED':
                    samples=d.get('samples',[])
                    failed=next((i for i,s in enumerate(samples) if s.get('overlap_mm3') is None),None)
                    if failed is not None:
                        prior=samples[failed-1] if failed else None
                        lines.append(f"  - 초기 겹침 {d.get('initial_overlap_mm3'):.6f} mm³. "+
                            (f"{prior['position_mm']:.3f} mm에서 {prior['overlap_mm3']:.6f} mm³로 감소했으나, " if prior else '')+
                            f"{samples[failed]['position_mm']:.3f} mm에서 교차 체적 계산이 실패해 미판정. 시간 초과로 기록된 것이 아니다.")
            if evidence.get('native_error'):lines.append('  - 계산 오류: '+str(evidence['native_error']))
        lines.append('')
    if not ids:lines.append('이번 실행에서 미해결 일반 부품은 없다.')
    lines+=['','세부 체적·이동 위치·오류는 `build/v23-packaged.json`의 `plans.auto.path_results`에 보존했다. 기존 간섭 판정/형상 보정/탐색/체결부 방향 기준은 수정하지 않았다.','',
        '## 회귀·실행 파일·보존','']
    for s in suites:
        passed=int(s['tests'])-int(s['failures'])-int(s['errors'])-int(s['skipped'])
        lines.append(f"- {s['name']}: {passed}통과 / {s['skipped']}건너뜀 / {s['failures']}실패 / {s['errors']}오류, {float(s['time']):.2f}초.")
    lines += ['- 추가 시험 5개 중 통합 계약 2개는 일반 회귀 시험과 중복이다. 조건부 건너뜀은 PA2_TEST_STEP 미지정 시험이다.',
        '- 학습 실행 시험 파일은 제외했다. 실제 프로젝트 시험 중 확정 데이터 수집은 복사본 DB에만 저장했고, 모델 학습/평가/승격은 하지 않았다.',
        f"- 수정 전 Python 소스 {len(sources)}개 중 UI/표시 파일 4개만 변경. 나머지 {sum(r['identical'] for r in sources)}개는 바이트 단위 동일하다.",
        f"- 최종 EXE 패키지 주요 소스 {len(package['modules'])}개, 자산·내장 아이콘 일치. 충돌 ICU DLL 미포함.",
        '- 최종 설치 경로 EXE에서 Python 경로 제거·Windows PATH만 사용한 프로젝트/3D/선택/창 아이콘 재열기 및 native CAD smoke 통과.',
        f"- EXE: `{ROOT/'PA2.exe'}`",f"- SHA-256: `{package['executable_sha256']}`",
        '- 이전 실행 파일과 의존 파일: `build/previous-release-v23-ui-20261022/`에 복구 가능하게 보관.',
        '- 수정 전 소스: `build/source-before-v23-ui-20261022/`.',
        f"- 제공 원본·팀원 전달본·이전 프로젝트/영상·사용자 DB/설정·기존 ZIP 등 {preservation['file_count']}개 파일 보존 확인: {preservation['unchanged']}.",
        '- 새 ZIP은 만들지 않았으며 기존 ZIP에는 이번 변경이 포함되지 않는다.','',
        '## 주요 근거','',
        '- `build/v23-packaged.json`, `.progress.json`, 편집 화면/선택/점멸·이동·완료 장면 PNG',
        '- `build/v23-summary.json`, `build/v23-preservation.json`',
        '- `build/v23-regression.xml`, `build/v23-retained.xml`, `build/v23-build.log`',
        '- `build/v23-staged-source-check.json`, `build/v23-installed-source-check.json`, `build/v23-installed-runtime.json`','']
    (ROOT/'docs/UI_V23_INTEGRATION_RESULT.md').write_text('\n'.join(lines),encoding='utf-8')
    print(json.dumps(dict(ok=True,comparison=compare,videos=len(now['renders'])),ensure_ascii=False))


if __name__=='__main__':main()
