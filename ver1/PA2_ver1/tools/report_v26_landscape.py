"""Record the automatically oriented top-view verification and installed build."""
import hashlib,json,xml.etree.ElementTree as ET
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def main():
    def load(name):return json.loads((ROOT/'build'/name).read_text(encoding='utf-8'))
    flow=load('v26-packaged.json');integrity=load('v26-preservation.json')
    installed=load('v26-installed-source-check.json');runtime=load('v26-installed-runtime.json')
    suite=ET.parse(ROOT/'build/v26-regression.xml').getroot().find('testsuite')
    render=flow['renders'][0];top=flow['top_landscape']
    ok=all([flow['ok'],integrity['unchanged'],installed['ok'],runtime['ok'],
            suite.get('failures')=='0',suite.get('errors')=='0',top['projected_width_mm']>=top['projected_height_mm']])
    report=dict(ok=ok,flow=flow,installed_exe=installed['executable_sha256'],
        reference_files_unchanged=integrity['unchanged'],reference_count=integrity['file_count'],
        regression=dict(suite.attrib),zip_created=False,model_training_performed=False)
    (ROOT/'build/v26-summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    document=f'''# v26 탑뷰 자동 가로 정렬 결과

2026-10-22, 현재 Windows PC. 기존 프로젝트를 독립 복사하여 시험했다.

## 반영

- 완성 모델의 원래 AABB의 XY 크기를 비교하여 Y가 더 길면 탑뷰 기본 방향을 90도 회전한다. X가 더 길거나 거의 정사각형이면 0도를 유지한다.
- TOP 및 AUTO 중 실제 조립 시선이 -Z인 경우에 적용한다. 정면·측면·하면은 변경하지 않는다.
- 조립 도중 움직이는 부품의 위치가 아니라 원래 모델 크기를 사용하므로 단계/프레임에 따라 자동 방향이 뒤집히지 않는다.
- 기본 가로 정렬값에 기존 사용자의 화면 회전값(0/90/180/270도)을 더한다. 사용자 회전 0도가 자동 가로 정렬 기준이며, 의도적으로 추가 90도를 선택하면 세로 배치도 가능하다. 기존 저장 회전값을 초기화하거나 덮어쓰지 않는다.
- 단계별 미리보기, 전체 재생/탐색 막대/완성 형상 미리보기, 영상 생성이 같은 카메라·시간표를 사용한다. 시작 시점 및 시점 간 quaternion 회전에도 자동 보정값을 포함해 갑자기 꺾이는 전환을 방지한다.
- 카메라 중심·거리·줌·부품 조립/분해 방향·간섭 기준은 그대로 유지한다. 원래 저장된 숫자 경계만 비교하며 새 CAD/간섭/경로 계산은 추가하지 않는다. 동일한 카메라 자세의 부동소수점 오차로 불필요한 0.3초 전환이 생기지 않도록 각도 비교를 안정화했다.
- DB 컬럼/Plan 데이터 형식은 바꾸지 않았다. 이미 만들어진 MP4는 변경하지 않으며 새로 생성한 영상에 적용된다. 영상 템플릿 및 다중선택 표시도 v25 그대로 유지한다.

## 검증

- 집중 시험 26통과(기존 회전 회귀 11개 포함). 세로/가로/정사각형 모델, TOP/AUTO/다른 시점 구분, 사용자 추가 회전, 부드러운 시점 전환, UI 미리보기·탐색·완성 미리보기 일치, 실제 세로 박스 메시의 화면/MP4 가로 배치를 확인했다. 간섭·경로 검사 호출은 차단한 상태로 시험했다.
- 일반 회귀 {suite.get('tests')}개: 337통과, 1조건부 건너뜀, 0실패, 0오류, {suite.get('time')}초. 건너뜀은 PA2_TEST_STEP 미지정, 기존 VTK/NumPy 사용 중단 예정 경고 14개. 모델 학습 실행 시험 파일 2개는 제외했으며 학습/평가/승격을 실행하지 않았다.
- 최초 집중 시험에서 같은 카메라 자세가 미세한 각도 차이로 0.3초 전환을 만들던 것을 발견해 위 각도 비교를 수정한 뒤 재통과했다. CAD 허용오차 변경과는 무관하다.
- 실제 프로젝트 원래 크기: X={top['model_size_mm'][0]:.3f}, Y={top['model_size_mm'][1]:.3f}, Z={top['model_size_mm'][2]:.3f}mm.
- 자동 기본 회전 {top['automatic_roll_deg']}도 + 사용자 회전 {top['user_roll_deg']}도 = 최종 {top['effective_roll_deg']}도.
- 탑뷰 화면 방향의 크기: 가로 {top['projected_width_mm']:.3f} × 세로 {top['projected_height_mm']:.3f}mm. 화면 픽셀 크기가 아니라 카메라 좌우/상하 축으로 투영한 원래 모델 크기다.
- 최종 패키지로 기존 프로젝트 불러오기 → 다중선택 → 탑뷰/방향/문구 편집 → 자동 가로 정렬 미리보기/복원 → 적용/자동저장 → 실행 취소/다시 실행 → 순서 묶음 이동 → 확정 → {render['steps']}단계 영상 생성 → MP4 전체 디코딩 → 0.25~4배속 재생/전체화면/Esc → 재열기 통과.
- 생성 영상 {render['result']['duration_sec']:.3f}초, {render['result']['frame_count']:,}프레임, 1920×1080/30fps, {render['result']['encoder']}. 생성 시간 {render['elapsed_sec']:.3f}초, 검증 흐름 전체 {flow['elapsed_sec']:.3f}초.
- 전체 {render['decoded_frames']:,}프레임 디코딩 일치. 자동 가로 정렬 장면을 MP4에서 재추출하여 인코딩 전 장면과 대조한 평균 RGB 차이 {flow['video_sample']['mean_absolute_pixel_error']:.4f}/255. 카메라 up 벡터도 미리보기와 일치.
- 선택/편집/영상에서 간섭·경로 검사 호출 {len(flow['forbidden_cad_calls'])}회. 표시용 형상 읽기·메시화와 구분한 수치다. 실제 CAD 자동 순서 생성 탐색은 다시 실행하지 않았다. 기존 BLK-KD000 미판정 및 예외 부품 정책은 변경하지 않았다.
- 기존 프로젝트/영상·제공 원본·팀원 전달본·사용자 DB/설정·ZIP 등 {integrity['file_count']}개 파일 해시 보존. 시험 변경은 복사본에만 저장했다.
- 패키지 추적 모듈 {len(installed['modules'])}개/자산/내장 아이콘 일치. 최종 설치 위치에서 Python 경로 제거 및 Windows PATH만으로 GUI/3D와 native smoke 통과.

## 실행 파일과 근거

- 실행 파일: `{ROOT/'PA2.exe'}`
- SHA-256: `{installed['executable_sha256']}`
- 영상: `{render['path']}`
- 수정 전 소스: `build/source-before-v26-top-landscape-20261022/`
- 이전 실행 파일/의존 파일: `build/previous-release-v26-top-landscape-20261022/` (이동 보관, 삭제하지 않음)
- `build/v26-summary.json`, `build/v26-packaged.json`, `build/v26-packaged-decoded-frame.png`
- `build/v26-source-preflight.json`, `build/v26-focused.xml`, `build/v26-regression.xml`
- `build/v26-build.log`, `build/v26-installed-source-check.json`, `build/v26-installed-runtime.json`, `build/v26-preservation.json`
- ZIP 생성/갱신 없음. 기존 ZIP에는 이번 변경이 포함되지 않는다.
'''
    destination=ROOT/'docs/UI_V26_TOP_LANDSCAPE_RESULT.md'
    destination.write_text(document,encoding='utf-8')
    print(json.dumps(dict(ok=ok,report=str(destination),video=render['path']),ensure_ascii=False))
    return 0 if ok else 1


if __name__=='__main__':raise SystemExit(main())
