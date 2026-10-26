# v20 보완사항·자동/수동 생성·영상·EXE 검증 결과

2026-10-22, 현재 Windows PC. 실제 패키징된 EXE에서 버튼을 눌러 수행한 자동 시험이다. 기존 v19 관리 프로젝트의 독립 복사본을 사용했다. 별도 수신 PC 시험은 아니다.

## 결과

- 전체 흐름 성공: True. 63그룹, 기준 제외 62단계.
- STEP 바디 176개 대표 색상 복원. 단일 빨강/주변 회색 불투명도 25%, 다중 선택 격리 및 복원, 카메라/계획 불변 확인.
- 색상 캐시 갱신 전후 BREP 176개 바이트 동일(상이 파일 0개), 색상을 제외한 체적/경계/중심/기타 바디 메타데이터 동일: True.
- 자동·수동생성 → 최초 초안 자동 보존 → 순서 묶음 이동/방향·시점·문구 편집 → 속성 미리보기 → 확정 → 전체 1920×1080/30fps 영상 생성 → 전 프레임 디코딩 → 최종 프로젝트 재열기 통과.
- 입력만 한 속성/미확정 수정은 영상 생성 차단. 적용된 편집값 자동 저장, 최초 생성 원본과 이전 확정본 보존.
- 수동생성·편집·미리보기·확정·영상에서 금지한 native CAD 재검사 호출: 0회. 자동생성 중의 정상 검사는 별도 집계했다.
- 예외 유지: LV CONT, AIR-BENT0A, HVSC 2800 #1, HVSC 2800 #2.
- 기존 수동 그룹은 이전 기능 시험용 미매칭 바디 묶음이며 엔지니어링상 승인된 실제 조립체라는 뜻은 아니다. 이전 v19와 동일한 그룹 구성으로 비교했다.

## 이전 결과 비교

| 항목 | 이전 v19 자동 | 이번 자동 | 이번 수동 |
|---|---:|---:|---:|
| 계산 시간(초) | 935.932 | 952.046 | 0.113 |
| 후보 기록 수 | 768 | 768 | 0 |
| 신규 CAD 경로 요청 | 191 | 191 | 0 |
| BREP Common 호출 | 19841 | 19841 | 0 |
| 생성 단계 | 62 | 62 | 62 |
| 대상 이동 단위 | 62 | 62 | 62 |
| 경로 확인 일반 부품 | 16 | 16 | 0 |
| 체결부 배치 | 41 | 41 | 41 |
| 사용자 예외 | 4 | 4 | 4 |
| 미해결 일반 부품 | 1 | 1 | 0 |

- 이번 버튼 실행부터 결과 표시까지(폴링 오차 포함): 자동 953.624초, 수동 0.423초. 위 계산 시간과 구분한다.
- 후보 기록 수에는 차단 근거 재사용이 포함된다. 신규 CAD 경로 요청 및 BREP Common 호출과 같은 숫자가 아니다.
- 수동생성의 0회 검사는 물리 검증을 생략한 기능의 결과이며, 자동 알고리즘의 동등 검증 속도 향상이 아니다.
- 수동 모드의 미해결 일반 부품 0은 검사를 시도하지 않았다는 뜻이며, 전부 통과했다는 뜻이 아니다.
- 자동 계산 시간은 이전 대비 1.72% 증가했다. 후보/신규 CAD/Common/단계 수는 이전과 동일하며 이번 자동생성의 속도 개선을 주장하지 않는다.
- 자동 초안 완성: True; 경로 증명 완료: False. 수동 초안은 경로 검증을 하지 않는다. 단계 수가 전체라고 모든 부품이 간섭 없이 이동한다는 뜻은 아니다.
- 모델 불러오기/캐시 준비는 위 순서 계산 시간에서 제외했다. 새 색상 캐시가 없는 구버전 프로젝트의 최초 열기는 관리 STEP에서 캐시를 한 번 재생성한다. 최종 EXE 시험은 사전 검증에서 생성한 색상 캐시를 재사용했다.

## 영상

- manual: 62단계 · 생성 183.235초 · 영상 231.000초 / 6,930프레임 · libx264/yuv420p
  - C:\Users\Win11Pro\Documents\15_ai_data\_Final_Project\ver1\PA2_ver1\runtime-data\end-to-end-v20-packaged\projects\7ff36dbc-4826-455d-9a14-2d99f2572641\videos\e94420cc-0f9a-4b3f-9940-01689a8b1aab-c2e6eaa0.mp4
- auto: 62단계 · 생성 215.110초 · 영상 247.500초 / 7,425프레임 · libx264/yuv420p
  - C:\Users\Win11Pro\Documents\15_ai_data\_Final_Project\ver1\PA2_ver1\runtime-data\end-to-end-v20-packaged\projects\7ff36dbc-4826-455d-9a14-2d99f2572641\videos\c3abf6fa-f0cc-45b3-b106-b48e3a647dfc-ff32183f.mp4

두 영상 모두 생성 프레임 수와 실제 전체 디코딩 프레임 수가 일치했다. 빨간 점멸/이동 중 빨강/완료 대표색 장면을 별도 PNG로 저장했다. 수동으로 수정한 경로를 간섭 재검사로 보정하지 않는다.
수동 영상은 기본 방향에 따른 시점 전환이 적어 자동 영상보다 짧다. 두 영상의 생성 시간을 동일 길이 영상의 인코딩 성능 비교로 해석하지 않는다. 임의 순서·방향 변경은 편집 기능 시험이며 실제 작업 절차 승인본이 아니다.

## 미해결 자동 경로

### BLK-KD000

기준 부품만 남긴 상태 기록: True.

- [0.0, 1.0, 0.0]: BLOCKED / PATH_BLOCKED / OVERLAP_REINCREASE / 상대 MBD-KD000
- [0.0, -1.0, 0.0]: BLOCKED / PATH_BLOCKED / OVERLAP_REINCREASE / 상대 MBD-KD000
- [0.0, 0.0, 1.0]: BLOCKED / PATH_BLOCKED / OVERLAP_REINCREASE / 상대 MBD-KD000
- [0.0, 0.0, -1.0]: BLOCKED / PATH_BLOCKED / OVERLAP_REINCREASE / 상대 MBD-KD000
- [1.0, 0.0, 0.0]: BLOCKED / PATH_BLOCKED / OVERLAP_REINCREASE / 상대 MBD-KD000
  - 캐시의 과거 상태 부가 진단에 다른 상대의 미판정이 남아 있지만, 현재 상태의 차단 근거와 구분했다. 원시 JSON에는 모두 보존했다.
- [-1.0, 0.0, 0.0]: UNKNOWN / PATH_UNKNOWN / DECREASE_BOOLEAN_FAILED / 상대 MBD-KD000
  - 초기 겹침 139.846936 mm³. 14.000 mm 이동에서 15.254987 mm³까지 감소했지만, 14.500 mm 이동 위치에서 교차 체적을 계산하지 못해 미판정이다. 시간 초과로 기록된 결과가 아니다.

기존 간섭·형상 보정 허용 기준은 변경하지 않았다. 자세한 이동 위치별 체적과 오류는 ui-v20-packaged.json의 plans.auto.path_results에 보존했다. 미해결 부품도 편집용 초안과 사용자 확정 영상에는 포함된다.

## 자동 수집·학습

- 저장 테이블 건수: {"plan_generations": 3, "confirmation_analyses": 4, "learning_observations": 4, "training_cases": 3, "ranking_states": 60, "ranking_candidates": 690}.
- 수집 현황: {"family_count": 1, "case_count": 3, "state_count": 60, "observation_count": 4, "ready": false, "reason": "학습 보류: 독립 형상 계열 1/30, ranking state 60/1000", "note": "기본 형상 특징·바디 간 거리로 중복 계열을 억제합니다. 제품 변형의 완전한 계열 분류는 아니며, 학습 가능은 자동 적용을 뜻하지 않습니다."}.
- 예외 포함 전체 확정 선호, 원래 검사 상태, 원본 방향, 당시 주변 상태를 저장했다. 볼트/너트는 일반 부품 순서 학습 후보에서 제외했다.
- 최초 초안–확정 비교는 전체/일반/일반 중 예외 제외로 분리했다. 원본 예외 부품은 삭제하지 않는다.

| 생성 모드 | 범위 | 선후 유지율 | LCS | 방향 일치율 |
|---|---|---:|---:|---:|
| auto | 전체 (62개) | 99.58% | 96.77% | 98.39% |
| auto | 일반 (21개) | 99.05% | 95.24% | 95.24% |
| auto | 일반·예외 제외 (17개) | 98.53% | 94.12% | 94.12% |
| manual | 전체 (62개) | 99.58% | 96.77% | 98.39% |
| manual | 일반 (21개) | 100.00% | 100.00% | 95.24% |
| manual | 일반·예외 제외 (17개) | 100.00% | 100.00% | 94.12% |

위 지표는 시험에서 임의로 편집한 확정본과 최초 초안의 차이를 검증한 것으로, 알고리즘의 실무 정확도 평가가 아니다.

- 실제 데이터가 30개 계열 AND 1,000개 선택 상태 조건을 만족하지 않으므로 실사용 모델 학습·자동 활성화는 하지 않았다.
- 오프라인 학습 실행·독립 계열 분리·미활성화는 별도의 합성 시험 데이터로 검증했다. 합성 모델은 테스트 임시 폴더에만 존재하고 실사용 학습 수에 포함하지 않았다.
- 방향/예외 추천용 데이터 수집까지 반영했으며 실제 방향·예외 모델의 일반화 성능을 이번에 검증한 것은 아니다.

## 실행 파일·보존

- 전체 자동 시험: 252 passed, 1 skipped, 0 failures, 0 errors. 제외 1개는 PA2_TEST_STEP 미지정 조건부 파일 시험이다. 실제 모델 재열기는 위 EXE 시험에서 수행했다. VTK/NumPy 사용 중단 예정 경고 10개는 기존 경고다.
- 간섭 판정/형상 보정/기존 자동 탐색/체결부 방향 핵심 소스 8개를 수정 전 백업과 바이트 단위 대조하여 동일함을 확인했다.
- 실행 파일: C:\Users\Win11Pro\Documents\15_ai_data\_Final_Project\ver1\PA2_ver1\PA2.exe
- SHA-256: 059e2874e863e806fcf964df58a71257f4ae95a0af83196d938b7f66023c1d24
- 검사한 패키지 모듈 43개와 현재 최적화 소스, 자산·내장 아이콘 일치. QtWidgets/3D/native worker 실행 확인.
- Python 경로를 제거하고 Windows 경로만 둔 EXE의 학습 현황 조회/데이터 부족 학습 차단/기본 CAD smoke 통과. 데이터 부족 상태에서 모델 폴더를 만들지 않았다.
- 이전 실행 파일/_internal은 build/previous-release-v20-20261022에 보관했다.
- 원본 제공 STEP, 기존 v19 프로젝트·영상, 사용자 AppData DB, 기존 모든 ZIP을 포함한 보존 대상 총 412개 파일의 해시 보존 확인: True.
- 새 ZIP은 생성하지 않았다. 기존 배포 ZIP과 GUI 소스 ZIP은 이전 내용 그대로이므로 이번 수정분을 포함하지 않는다.

## 근거

- runtime-data/native-validation/ui-v20-packaged.json 및 진행 JSON, 장면 PNG
- runtime-data/native-validation/v20-comparison.json
- runtime-data/native-validation/packaged-source-check-v20.json, native-v20.json, runtime-v20.json
- runtime-data/native-validation/v20-packaged-preservation.json
- runtime-data/native-validation/tests-v20-final.log 및 XML, tests-v20-additions.log, build-v20.log
- docs/V20_IMPROVEMENTS.md
