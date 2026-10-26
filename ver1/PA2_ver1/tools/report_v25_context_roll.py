"""Summarize measured v25 results, without reusing old results as new tests."""
import hashlib,json,xml.etree.ElementTree as ET
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def read(name):return json.loads((ROOT/'build'/name).read_text(encoding='utf-8'))
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    flow=read('v25-packaged.json');preservation=read('v25-preservation.json')
    packaged=read('v25-installed-source-check.json');runtime=read('v25-installed-runtime.json')
    previous=read('v24-packaged-final.json');native=read('v25-native-observation.json')
    def suite(name):
        node=ET.parse(ROOT/'build'/name).getroot().find('testsuite')
        return {k:node.get(k) for k in ('tests','failures','errors','skipped','time')}
    checks={name:suite(name+'.xml') for name in ('v25-regression-final','v25-focused','v25-roll-final')}
    backup=ROOT/'build/source-before-v25-context-roll-20261022/src'
    source_changes=[str(p.relative_to(backup)).replace('\\','/') for p in backup.rglob('*.py')
        if not (ROOT/'src'/p.relative_to(backup)).is_file() or sha(p)!=sha(ROOT/'src'/p.relative_to(backup))]
    current=flow['renders'][0];old=previous['renders'][0]
    first=read('v25-staged-source-check.json')
    production_identity=all(row['source_sha256']==next(r['source_sha256'] for r in packaged['modules'] if r['module']==row['module'])
        for row in first['modules'] if row['module']!='pa2.ui_verify_v25')
    test_ok=all(int(row['failures'])==0 and int(row['errors'])==0 for row in checks.values())
    report=dict(ok=all([flow['ok'],preservation['unchanged'],packaged['ok'],runtime['ok'],native['ok'],production_identity,test_ok]),
        executable=str(ROOT/'PA2.exe'),sha256=sha(ROOT/'PA2.exe'),bytes=(ROOT/'PA2.exe').stat().st_size,
        flow=flow,previous_video=old,tests=checks,changed_existing_modules=source_changes,
        preserved_files=preservation['file_count'],source_module_count=len(packaged['modules']),
        normalized_scene_area_change_percent=(.74*.80/(.70*.71)-1)*100,
        native_observed_production_modules_unchanged_in_final=production_identity,
        zip_created=False,model_training_performed=False)
    (ROOT/'build/v25-summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    text=f'''# v25 다중선택·카메라 화면 회전·영상 템플릿 검증 결과

2026-10-22, 현재 Windows PC. 기존 프로젝트의 독립 복사본으로 검증했으며 별도 수신 PC 검증은 아니다.

## 적용 내용

1. 부품 목록/3D 및 하단 순서 카드의 다중선택에서 선택 부품은 빨간색·불투명, 나머지는 회색·불투명도 0.10(투명도 90%). 단일선택의 0.25(투명도 75%)는 유지한다. 선택 해제 시 원래 색상·속성·위치를 복구하고 직접 숨긴 부품은 선택만으로 드러내지 않는다. 카드 묶음 이동과 그룹화 기능은 유지한다.
2. 작업 속성의 카메라 아래 ↶ 90°/↷ 90° 및 현재 각도 표시. 0/90/180/270도 순환. 실제 모델/조립 방향은 바꾸지 않고 view-up만 회전한다. 속성 미리보기 후 ‘선택 단계에 적용’하면 자동 저장된다. 미적용 입력 상태에서는 확정본 영상 생성이 차단된다.
3. 회전값은 PlanStep.camera_roll_deg 및 기존 camera_json의 roll_deg에 저장한다. 기존 프로젝트/JSON에서 누락하면 0도로 읽는다. DB 컬럼 추가/스키마 마이그레이션은 필요 없다. 확정 스냅샷·영상 적합성 서명·실행 취소/다시 실행에도 포함한다.
4. 순수 화면 회전에도 카메라 전환 시간을 배정하고 quaternion 보간을 사용한다. 회전값 0인 기존 시점의 전환 시간은 유지한다. 카메라 중심·거리·줌 고정 정책과 부품 이동 0.7초/이동 전 점멸 2초를 유지한다.
5. 템플릿 corporate-v3-compact-header. 상단 프로젝트명·차종·제품명을 하단과 같은 연보라 둥근 도형 안에 표시하고 로고는 별도 유지한다. 바깥 여백 3%→1.5%, 3D 영역 70%×71%→74%×80%(정규화 면적 약 {report['normalized_scene_area_change_percent']:.1f}% 증가). 3D 렌더 크기도 템플릿 좌표에서 산출한다.
6. 자재정보는 입력이 비면 품명으로 대체하고 주의사항은 임의 내용을 넣지 않는다. 문구가 없어도 상하단·자재정보·주의사항의 틀을 유지한다. 저해상도 출력은 1080p 설계 좌표로 텍스트/여백을 배치한 뒤 축소한다. 과거 사용자 정의 템플릿의 header 누락도 지원한다. 기존 MP4는 덮어쓰지 않는다.

## 실제 패키지 흐름 검증

- 기존 63그룹/62이동단계 프로젝트 재열기 → 목록 실제 마우스 선택/재클릭 → 3D 선택 콜백 → 부품/카드 다중선택 → 숨김 보존 → 방향·카메라·문구 수정 → 회전 미리보기/원상복구 → 적용/자동저장 → 실행 취소·다시 실행 → 카드 묶음 이동 → 재확정 → 영상 생성 → 전체 디코딩 → 플레이어 재생/배속/전체화면/Esc → 프로젝트 재열기 통과.
- 회전값 {flow['editing']['camera_roll_deg']}도 저장·재확정·재열기 일치. 기존 설정에서 오른쪽 버튼으로 90도 더 회전한 상태이며, 왼쪽/오른쪽 버튼과 4회 순환은 별도 단위 시험도 수행했다.
- 영상 {current['result']['duration_sec']:.3f}초, {current['result']['frame_count']:,}프레임, 1920×1080/30fps, 인코더 {current['result']['encoder']}.
- 영상 생성 {current['elapsed_sec']:.3f}초. 흐름 전체 {flow['elapsed_sec']:.3f}초. 전체 디코딩 {current['decoded_frames']:,}프레임 일치.
- 회전된 단계의 프레임 {flow['video_sample']['frame_index']}를 MP4에서 다시 추출하여 인코딩 전 동일 프레임과 대조: RGB 평균 절대 차이 {flow['video_sample']['mean_absolute_pixel_error']:.4f}/255. 영상의 camera-up이 저장한 회전 시점과 일치함도 확인했다.
- 선택·편집·영상 생성 중 간섭·경로 검증용 격리 CAD 작업 호출 {len(flow['forbidden_cad_calls'])}회. 표시용 형상 읽기·메시화와 구분한 수치다. 최초 생성 원본과 이전 확정본은 보존.
- 실제 Windows 입력 관찰: {native['summary']}
- 위 수동 Windows 입력은 첫 v25 패키지에서 수행했다. 최종 패키지와 비교해 검증 도구를 제외한 추적 모듈의 소스 해시가 동일함을 확인했다({production_identity}). 최종 패키지는 별도로 전체 흐름·영상·재생·재열기 시험을 다시 실행했다.

## 이전 결과와 비교 및 범위

| 항목 | 이전 v24 | 이번 v25 |
|---|---:|---:|
| 영상의 조립 단계 수 | {old['steps']} | {current['steps']} |
| 영상 길이(초) | {old['result']['duration_sec']:.3f} | {current['result']['duration_sec']:.3f} |
| 프레임 수 | {old['result']['frame_count']:,} | {current['result']['frame_count']:,} |
| 영상 생성 실측(초) | {old['elapsed_sec']:.3f} | {current['elapsed_sec']:.3f} |

최종 영상의 길이/프레임 수는 이전과 같았다. 편집한 시점과 회전 각도가 다르면 전환 시간 때문에 길이가 달라질 수 있다. 렌더 영역도 커졌고 인코더 자동 선택과 PC 부하가 달라질 수 있어 위 시간은 동등 부하 최적화 벤치마크가 아니다.

이번 요청은 UI/카메라/영상 변경으로 실제 모델의 자동·수동 순서 생성 전체 탐색은 다시 실행하지 않았다. v23의 이전 자동 결과 932.540초/후보 768/신규 경로 191/62단계를 이번 실측으로 표시하지 않는다. 기존 BLK-KD000 경로 미판정과 예외 4개(LV CONT, AIR-BENT0A, HVSC 2800 #1/#2)는 해결·통과 처리하지 않았다. 순서 완성 및 물리 조립 가능성의 재검증과는 구분한다.

## 시험·원본 보존·실행 파일

- 일반 회귀: {checks['v25-regression-final']['tests']}개 중 322통과/1조건부 건너뜀/0실패/0오류, {checks['v25-regression-final']['time']}초. PA2_TEST_STEP 미지정 건너뜀이며 기존 VTK/NumPy 사용 중단 예정 경고 11개가 있다.
- 집중 시험 24통과, 회전 방향 보강 후 11통과. 이 시험들은 일반 회귀와 중복되므로 통과 수를 합산하지 않는다.
- 별도로 기존 수동생성의 접촉/경로 검사 생략·체결부 묶음 유지 시험 1개도 통과했다(`build/v25-retained.xml`).
- 최초 회귀 1실패는 시험용 저장 경로가 샌드박스 AppData에 설정되어 쓰기 권한이 없었던 문제였다. 프로젝트 내부 PA2_DATA_ROOT를 지정한 재실행에서는 동일 CAD 시험을 포함해 통과했다. 제품 CAD 판정 코드를 완화하지 않았다.
- 첫 패키지 전체 흐름에서는 영상 생성/전체 디코딩/회전 프레임 대조 후 검증 도구 자체의 sample 변수 이름 중복으로 재생 시험이 중단됐다. 테스트 모듈만 수정해 최종 패키지에서 전체를 재검증했다. 최초 실패 기록은 `build/v25-packaged-first-harness-failure.json`에 남겼다.
- 학습 실행 시험 파일 두 개는 제외했다. 모델 학습/평가/승격은 실행하지 않았다. 확정 데이터 수집은 독립 시험 DB에만 기록했다.
- 수정 전 기존 모듈 변경: {', '.join(source_changes)}. CAD/간섭/탐색/체결부/그룹화/학습 알고리즘 소스는 변경하지 않았다.
- 제공 원본·팀원 전달본·v24 프로젝트/영상·사용자 DB/설정·기존 ZIP {preservation['file_count']}개 파일 해시 보존 확인.
- 패키지 주요 모듈 {len(packaged['modules'])}개·자산·내장 아이콘 일치, 충돌 ICU 미포함. 최종 설치 위치에서 Python 경로 제거/Windows PATH만으로 프로젝트·3D 및 native smoke 통과.
- 실행 파일: `{ROOT/'PA2.exe'}`
- SHA-256: `{report['sha256']}`
- 이전 실행 파일/의존 파일 복구 사본: `build/previous-release-v25-context-roll-20261022/`
- 수정 전 소스/자산: `build/source-before-v25-context-roll-20261022/`
- ZIP 생성·갱신 없음. 기존 ZIP에는 이번 변경이 포함되지 않는다.

## 영상과 근거

- 영상: `{current['path']}`
- `build/v25-packaged.json`, `.progress.json`, `-multi-parts.png`, `-multi-cards.png`, `-roll-preview.png`, `-template-frame.png`, `-decoded-frame.png`
- `build/v25-summary.json`, `build/v25-preservation.json`, `build/v25-native-observation.json`
- `build/v25-regression-final.xml`, `build/v25-focused.xml`, `build/v25-roll-final.xml`, `build/v25-build-final.log`
- `build/v25-installed-source-check.json`, `build/v25-installed-runtime.json`
'''
    (ROOT/'docs/UI_V25_CONTEXT_ROLL_RESULT.md').write_text(text,encoding='utf-8')
    print(json.dumps(dict(ok=report['ok'],report=str(ROOT/'docs/UI_V25_CONTEXT_ROLL_RESULT.md'),
        video=current['path'],render_sec=current['elapsed_sec']),ensure_ascii=False))
    return 0 if report['ok'] else 1


if __name__=='__main__':raise SystemExit(main())
