# v23 팀원 UI 통합·전체 구동 검증 결과

2026-10-22, 현재 Windows PC. 현재 v22 기능과 알고리즘을 유지하면서 팀원 UI v7을 이식했다. 별도 수신 PC 시험은 아니다.

## 결과

- 패키징된 EXE 전체 흐름 성공: True. 63그룹, 기준 제외 62단계.
- 기존 프로젝트 독립 복사본 → 수동생성 → 편집·속성 미리보기·확정 → 전체 영상 → 자동생성 → 편집·확정 → 전체 영상 → 최종 프로젝트 재열기 통과.
- 최초 생성 원본 보존, 적용 편집값 자동 저장, 미적용 속성/미확정 순서의 영상 생성 차단을 확인했다.
- 수동생성·선택·편집·미리보기·영상 중 금지한 CAD 재검사 호출: 0회.
- 예외 부품 LV CONT, AIR-BENT0A, HVSC 2800 #1·#2 유지. 자동/수동 초안의 전체 단계 생성은 물리 검증 완료를 뜻하지 않는다.

## UI 변경과 기존 기능 유지

- 파란 테마, THN 로고, 좌측 부품·중앙 3D·우측 속성·하단 카드 배치.
- 카드 다중 드래그·삽입 미리보기·가장자리 스크롤·현재 재생 카드 강조.
- 회전/이동/맞춤/시점/확대·축소/숨김 도구, 지연 누적 없는 카메라 조작, 최대 4배속 3D 재생.
- 빨간 면 선택, 단일 선택 시 주변 회색·25% 불투명도, 가림 보완 표시층, 작은 부품의 복원 가능한 표시용 돌출.
- STEP 대표색을 기본·해제·썸네일·영상에 유지. 이동 전 점멸/이동 중 빨강/완료 원래색을 유지.
- 편집용 돌출·가림 보완·주변 반투명 효과는 영상에 넣지 않는다. 영상은 정확한 이동 좌표와 기존 불투명도를 사용한다.
- 반복 속성 미리보기 후 카메라·가시성·투명도·색상·표시용 위치·선택 표시층을 복원한다.
- 수동생성, 자동 저장, 기준/예외 지정, 수동 그룹화 보호, 학습 현황·설정·모델 연결 유지. 모델 학습/평가/자동 적용 시험은 하지 않았다.

## 이전 v20 실제 제품 결과와 비교

v21/v22에는 동일 제품 전체 벤치마크가 없으므로 마지막 전체 구동 기록 v20을 비교 기준으로 사용했다. 동일 관리 프로젝트·그룹 구성·설정이며, 모델 열기 시간은 순서 계산 시간에 포함하지 않는다.

| 항목 | 이전 자동 | 이번 자동 | 이전 수동 | 이번 수동 |
|---|---:|---:|---:|---:|
| 계산 시간(초) | 952.046 | 932.540 | 0.113 | 0.114 |
| 후보 기록 | 768 | 768 | 0 | 0 |
| 신규 CAD 경로 요청 | 191 | 191 | 0 | 0 |
| BREP Common 호출 | 19841 | 19841 | 0 | 0 |
| 생성 단계 | 62 | 62 | 62 | 62 |
| 경로 확인 일반 부품 | 16 | 16 | 0 | 0 |
| 체결부 배치 | 41 | 41 | 41 | 41 |
| 사용자 예외 | 4 | 4 | 4 | 4 |
| 미해결 일반 부품 | 1 | 1 | 0 | 0 |

후보 기록에는 차단 근거 재사용이 포함된다. 신규 경로 요청/Common 호출과 구분한다. UI 이식에 따른 알고리즘 속도 개선을 주장하지 않는다. 수동생성의 검사 0회는 검증 생략 정책이며 간섭 통과를 뜻하지 않는다.

## 영상 생성

- manual: 62단계, 생성 184.440초, 영상 231.000초 / 6,930프레임, h264_nvenc/yuv420p.
  - `C:\Users\Win11Pro\Documents\15_ai_data\_Final_Project\ver1\PA2_ver1\runtime-data\end-to-end-v23-ui\projects\7ff36dbc-4826-455d-9a14-2d99f2572641\videos\87c269f6-a7dd-4581-b2a5-592cf942b5ed-c79792e1.mp4`
- auto: 62단계, 생성 196.211초, 영상 247.500초 / 7,425프레임, h264_nvenc/yuv420p.
  - `C:\Users\Win11Pro\Documents\15_ai_data\_Final_Project\ver1\PA2_ver1\runtime-data\end-to-end-v23-ui\projects\7ff36dbc-4826-455d-9a14-2d99f2572641\videos\cdf3cc9f-a9eb-4f34-995d-336349c1ea81-da82d404.mp4`

두 영상 모두 1920×1080/30fps 전체 생성 후 전 프레임 디코딩 수가 일치했다. 순서 묶음·방향·카메라·문구를 임의 변경한 기능 시험이며 실제 작업 절차 승인본이 아니다.
이번에는 기존 자동 인코더 선택 기능이 NVENC를 선택했다. 이전 v20은 libx264였으므로 영상 생성 시간의 차이를 동일 인코더 성능이나 UI 이식에 따른 최적화 효과로 해석하지 않는다.

## 남은 자동 경로 문제

### BLK-KD000

그룹 ID: `group-6f966deb84-0001`. 미해결 단계도 검토·편집용 초안에 포함되며, 통과로 변경하지 않는다.

기준 부품만 남긴 상태의 검사 기록: True.
- 방향 [0.0, 1.0, 0.0]: BLOCKED / PATH_BLOCKED / OVERLAP_REINCREASE / 상대 MBD-KD000
- 방향 [0.0, -1.0, 0.0]: BLOCKED / PATH_BLOCKED / OVERLAP_REINCREASE / 상대 MBD-KD000
- 방향 [0.0, 0.0, 1.0]: BLOCKED / PATH_BLOCKED / OVERLAP_REINCREASE / 상대 MBD-KD000
- 방향 [0.0, 0.0, -1.0]: BLOCKED / PATH_BLOCKED / OVERLAP_REINCREASE / 상대 MBD-KD000
- 방향 [1.0, 0.0, 0.0]: BLOCKED / PATH_BLOCKED / OVERLAP_REINCREASE / 상대 MBD-KD000
- 방향 [-1.0, 0.0, 0.0]: UNKNOWN / PATH_UNKNOWN / DECREASE_BOOLEAN_FAILED / 상대 MBD-KD000
  - 초기 겹침 139.846936 mm³. 14.000 mm에서 15.254987 mm³로 감소했으나, 14.500 mm에서 교차 체적 계산이 실패해 미판정. 시간 초과로 기록된 것이 아니다.


세부 체적·이동 위치·오류는 `build/v23-packaged.json`의 `plans.auto.path_results`에 보존했다. 기존 간섭 판정/형상 보정/탐색/체결부 방향 기준은 수정하지 않았다.

## 회귀·실행 파일·보존

- v23-regression: 306통과 / 1건너뜀 / 0실패 / 0오류, 52.75초.
- v23-retained: 5통과 / 0건너뜀 / 0실패 / 0오류, 4.22초.
- 추가 시험 5개 중 통합 계약 2개는 일반 회귀 시험과 중복이다. 조건부 건너뜀은 PA2_TEST_STEP 미지정 시험이다.
- 학습 실행 시험 파일은 제외했다. 실제 프로젝트 시험 중 확정 데이터 수집은 복사본 DB에만 저장했고, 모델 학습/평가/승격은 하지 않았다.
- 수정 전 Python 소스 79개 중 UI/표시 파일 4개만 변경. 나머지 75개는 바이트 단위 동일하다.
- 최종 EXE 패키지 주요 소스 58개, 자산·내장 아이콘 일치. 충돌 ICU DLL 미포함.
- 최종 설치 경로 EXE에서 Python 경로 제거·Windows PATH만 사용한 프로젝트/3D/선택/창 아이콘 재열기 및 native CAD smoke 통과.
- EXE: `C:\Users\Win11Pro\Documents\15_ai_data\_Final_Project\ver1\PA2_ver1\PA2.exe`
- SHA-256: `a4844c34d9642310934737dcfb5da3a8560c3882f59efc3b14ed3da831d0820d`
- 이전 실행 파일과 의존 파일: `build/previous-release-v23-ui-20261022/`에 복구 가능하게 보관.
- 수정 전 소스: `build/source-before-v23-ui-20261022/`.
- 제공 원본·팀원 전달본·이전 프로젝트/영상·사용자 DB/설정·기존 ZIP 등 571개 파일 보존 확인: True.
- 새 ZIP은 만들지 않았으며 기존 ZIP에는 이번 변경이 포함되지 않는다.

## 주요 근거

- `build/v23-packaged.json`, `.progress.json`, 편집 화면/선택/점멸·이동·완료 장면 PNG
- `build/v23-summary.json`, `build/v23-preservation.json`
- `build/v23-regression.xml`, `build/v23-retained.xml`, `build/v23-build.log`
- `build/v23-staged-source-check.json`, `build/v23-installed-source-check.json`, `build/v23-installed-runtime.json`
