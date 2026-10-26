"""Generate a measured result record for v24 UI controls and playback."""
import ast
import json
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
def read(name):return json.loads((ROOT/name).read_text(encoding='utf-8'))


def main():
    run=read('build/v24-packaged-final.json');package=read('build/v24-installed-source-check.json')
    runtime=read('build/v24-installed-runtime.json');preserved=read('build/v24-preservation.json')
    native=read('build/v24-native-observation.json')
    assert run['ok'] and package['ok'] and runtime['ok'] and preserved['unchanged']
    assert not run['forbidden_cad_calls'] and len(run['rates'])==7 and run['fullscreen_esc']
    assert native['executable_sha256']==package['executable_sha256'] and native['vtk_mouse_reclick_count']==0
    backup=ROOT/'build/source-before-v24-controls-20261022'
    allowed={'ui/main_window.py','ui/model_editor.py','ui/video_page.py','ui/settings_dialog.py','ui/theme.py','settings/config.py'}
    sources=[]
    for old in (backup/'src/pa2').rglob('*.py'):
        rel=old.relative_to(backup/'src/pa2').as_posix();new=ROOT/'src/pa2'/rel
        sources.append(dict(path=rel,identical=old.read_bytes()==new.read_bytes(),allowed=rel in allowed))
    assert all(r['identical'] or r['allowed'] for r in sources)
    def defaults(path):
        cls=next(c for c in ast.parse(path.read_text(encoding='utf-8')).body if isinstance(c,ast.ClassDef) and c.name=='AppSettings')
        return {n.target.id:ast.dump(n.value) for n in cls.body if isinstance(n,ast.AnnAssign) and n.value is not None}
    old_defaults=defaults(backup/'src/pa2/settings/config.py');new_defaults=defaults(ROOT/'src/pa2/settings/config.py')
    default_changes=[k for k in old_defaults.keys()|new_defaults.keys() if old_defaults.get(k)!=new_defaults.get(k)]
    assert default_changes==['assembly_move_sec']
    for name in ('pa2_icon.png','pa2_icon.ico','thn_logo.png'):
        assert (ROOT/'assets'/name).read_bytes()==(backup/'assets'/name).read_bytes()
    suites=[]
    for name in ('v24-regression','v24-controls','v24-retained'):
        a=ET.parse(ROOT/f'build/{name}.xml').getroot()[0].attrib
        assert a['failures']==a['errors']=='0'
        suites.append({**a,'name':name})
    video=run['renders'][0];assert video['decoded_frames']==video['result']['frame_count']
    summary=dict(ok=True,selection=run['selection'],editing=run['editing'],transport=run['transport'],
        rates=run['rates'],fullscreen_esc=run['fullscreen_esc'],timeline=run['timeline'],video=video,native=native,
        unchanged_sources=sources,default_changes=default_changes,tests=suites,package=package,runtime=runtime,
        preserved={k:v for k,v in preserved.items() if k!='files'},model_training_performed=False,zip_created=False)
    (ROOT/'build/v24-summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    lines=['# v24 선택·영상 재생·표시 설정 개선 검증 결과','',
        '2026-10-22, 현재 Windows PC. v23의 기존 기능과 CAD/순서 알고리즘을 유지하면서 합의한 UI 보완 6가지를 적용했다. 별도 수신 PC 시험은 아니다.','',
        '## 적용 내용','',
        '1. 일반 화면에서 순서 생성 진단 버튼 숨김. 내부 진단 수집/결과 JSON 저장과 판정 기준은 유지.',
        '2. 부품 목록과 3D 선택 콜백에서 단일선택을 일반 클릭으로 재클릭하면 해제. 강조·투명도·표시용 위치·임시 격리와 카드 선택 동기화 복원. Ctrl/Shift 다중선택과 순서 카드 조작은 유지.',
        '3. 영상 탭에 모델·순서 탭과 같은 아이콘 스타일의 처음/5초 뒤로/재생·일시정지/5초 앞으로/끝 버튼, 위치 막대·현재/전체 시간 배치. 시작/끝 범위 제한.',
        '4. 영상 탭 배속 0.25×/0.5×/1×/1.5×/2×/3×/4×. 전체화면과 Esc 해제 유지.',
        '5. 기본 이동 시간 0.7초, 기본 점멸 시간 2초. 설정에 부품 이동 시간/이동 전 점멸 시간과 초 단위를 명시. 모델 미리보기와 신규 영상이 같은 설정 사용. 이동 0.01~600초, 점멸 0~600초; 기존에 저장한 사용자 시간 값은 유지.',
        '6. 주요 버튼과 재생 버튼의 기본색 #2633C5, hover #202BA6. 요청한 PANTONE 2736 PC 브랜드용으로 기존 프로젝트 영상 템플릿의 화면색을 재사용했다. 공식 인쇄 색상 변환값을 새로 산출한 것은 아니다. PA² 아이콘과 노란 위첨자 ², THN 로고는 바이트 동일.','',
        '## 실제 EXE 흐름 시험','',
        '- 기존 v23 프로젝트의 독립 복사본을 열어 목록 마우스 클릭/재클릭, 3D 선택 콜백/재클릭, 다중선택과 해제를 시험했다. 선택 전후 계획·카메라·표시 상태 보존 확인. 미적용 속성 입력 후 단일선택을 해제하면 기존 확정본의 영상 생성 가능 상태가 즉시 복원되도록 알림도 보완했다.',
        '- 별도 Windows 실제 마우스 입력 시험에서도 목록 COV-KD000 클릭/재클릭과 3D 커버 면 클릭/재클릭 후 1개→0개 선택 및 원래 색상 복원을 확인했다. 기존 VTK 클릭 판정 경로는 수정하지 않았다. 생성 MP4 그림·템플릿·시간 진행과 Esc 후 내장 화면 복원도 직접 확인했다.',
        '- 기존 62단계 초안의 순서 묶음·방향·카메라·문구를 임의 변경. 속성 미리보기 복원, 실행 취소/다시 실행, 편집 자동 저장, 최초 생성 원본과 이전 확정본 보존, 미확정 영상 차단 및 재확정 통과.',
        '- 이동/점멸 설정의 한글 표시·저장/재열기·기본값 복원은 별도 시험에서 통과. 저장할 때 증가하는 revision은 편집 내용과 구분해 실행 취소/다시 실행을 비교했다.',
        f"- {run['timeline']['steps']}개 단계 모두 이동 {run['timeline']['move_sec']}초, 점멸 {run['timeline']['blink_sec']}초 확인.",
        f"- 실제 영상 생성: {video['elapsed_sec']:.3f}초, 영상 길이 {video['result']['duration_sec']:.3f}초 / {video['decoded_frames']:,}프레임, 1920×1080/30fps, {video['result']['encoder']}.",
        '- MP4 전체 프레임 디코딩 수가 생성 수와 일치. 실제 QMediaPlayer에서 위치 이동/재생·일시정지 아이콘/7개 배속/영상 프레임 수신/전체화면·Esc 해제를 확인했다.',
        '- 확정본과 영상을 재열어 62단계·확정 연결 보존 확인. 이번 시험의 임의 편집본은 실제 작업 절차 승인본이 아니다.',
        f"- 선택·편집·미리보기·확정·영상 과정에서 금지한 CAD 재검사: {len(run['forbidden_cad_calls'])}회.",'',
        '### 실제 배속 재생 관찰','',
        '| 요청/반영 배속 | 관찰 시간(초) | 재생 위치 증가(ms) | 관찰 배율 | 수신 프레임 |',
        '|---|---:|---:|---:|---:|']
    for r in run['rates']:
        lines.append(f"| {r['requested']}× / {r['actual']}× | {r['wall_sec']:.3f} | {r['position_delta_ms']} | {r['observed_ratio']:.2f}× | {r['decoded_frames']} |")
    lines += ['','위치는 QMediaPlayer 갱신 주기와 디코딩 지연 때문에 정확한 계측기가 아니다. 배속 설정 수용, 시간 진행, 실제 영상 프레임 수신 및 4배속의 가속을 함께 확인한 기능 시험이다.','',
        '## 기존 알고리즘·데이터 보존','',
        f"- 수정 전 Python 파일 {len(sources)}개 중 기존 UI/표시 설정 파일 6개만 변경했다. 나머지 {sum(r['identical'] for r in sources)}개는 바이트 동일. 부품 목록 전용 위젯과 이번 시험 모듈은 새 파일이다.",
        '- CAD 간섭·형상 보정·분해 탐색·체결부 배치/방향·수동생성·그룹화·저장/확정·학습 핵심 소스는 변경하지 않았다.',
        '- AppSettings의 기본값 변경은 assembly_move_sec 1개뿐이며, 다른 물리·탐색·학습 기본값은 AST 대조로 동일하다.',
        '- 자동·수동 순서 생성 전체 벤치마크는 이번에 재실행하지 않았다. 마지막 v23 자동 결과는 932.540초 / 후보 768 / 신규 경로 191 / 62단계이며, 이번 결과인 것처럼 재사용하지 않는다.',
        '- 기존 BLK-KD000 자동 경로 미판정은 해결·통과 처리하지 않았다. 기존 예외 4개와 사용자 검토 후 확정하는 정책을 유지했다.',
        f"- 제공 원본·팀원 전달본·이전 프로젝트/영상·사용자 DB/설정·기존 ZIP 등 {preserved['file_count']}개 파일의 해시 보존 확인: {preserved['unchanged']}.",
        '- 확정 시 데이터 수집은 시험 복사본에만 기록했다. 모델 학습/평가/승격 시험은 실행하지 않았다.','',
        '## 회귀·실행 파일','']
    for s in suites:
        passed=int(s['tests'])-int(s['skipped'])-int(s['failures'])-int(s['errors'])
        lines.append(f"- {s['name']}: {passed}통과 / {s['skipped']}건너뜀 / {s['failures']}실패 / {s['errors']}오류, {float(s['time']):.2f}초.")
    lines += ['- v24-controls 5개는 전체 일반 회귀에도 포함되는 중복 시험이다. 건너뜀 1개는 PA2_TEST_STEP 미지정 조건부 시험. 기존 VTK/NumPy 사용 중단 예정 경고는 남아 있다.',
        '- v24-retained 3개는 수동생성의 CAD 검사 생략, STEP 대표색/캐시, 선택 해제 색상 복원과 영상 점멸 유지의 추가 시험이다.',
        '- 학습 실행 시험 파일은 제외했다. 새 UI/설정 검증 외에 기존 선택·그룹화·편집·확정·영상 회귀를 유지했다.',
        f"- 최종 패키지 주요 소스 {len(package['modules'])}개와 자산·내장 아이콘 일치; 충돌 ICU DLL 미포함.",
        '- 최종 경로에서 Python 경로 제거·Windows PATH만 둔 프로젝트/3D 재열기와 native CAD smoke 통과.',
        f"- 실행 파일: `{ROOT/'PA2.exe'}`",f"- SHA-256: `{package['executable_sha256']}`",
        '- 이전 EXE/의존 파일 복구 사본: `build/previous-release-v24-controls-20261022/`.',
        '- 수정 전 소스/자산: `build/source-before-v24-controls-20261022/`.',
        '- 배포 ZIP은 생성·갱신하지 않았다. 기존 ZIP은 이번 변경을 포함하지 않는다.','',
        '## 생성 영상·근거','',f"- 영상: `{video['path']}`",
        '- `build/v24-packaged-final.json`, `.progress.json`, 편집/영상 화면과 점멸·이동 장면 PNG',
        '- `build/v24-summary.json`, `build/v24-preservation.json`',
        '- `build/v24-regression.xml`, `build/v24-controls.xml`, `build/v24-retained.xml`, `build/v24-build-final.log`',
        '- `build/v24-installed-source-check.json`, `build/v24-installed-runtime.json`, `build/v24-native-observation.json`','']
    (ROOT/'docs/UI_V24_CONTROLS_RESULT.md').write_text('\n'.join(lines),encoding='utf-8')
    print(json.dumps(dict(ok=True,video=video['path'],steps=run['editing']['step_count'],rates=len(run['rates'])),ensure_ascii=False))


if __name__=='__main__':main()
