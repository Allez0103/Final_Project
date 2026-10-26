# v16 전체 실행 및 영상 검증

볼트·너트를 제외한 일반 부품을 한 번 탐색한 뒤 체결부를 삽입했다. LV CONT, HVSC 2800 #1/#2를 예외로 지정했다.

| 항목 | 이전 v14 | 이번 v16 |
|---|---:|---:|
| 입력·그룹화·접촉 준비 (초) | 271.14 | 275.53 |
| 순서 생성 시간 (초) | 2565.75 | 1142.08 |
| 초안 단계 수 | 64 | 64 |
| 후보 기록 수 | 810 | 896 |
| 신규 CAD 경로 요청 | 216 | 192 |
| 부품 쌍 계산 | 403 | 235 |
| BREP Common 호출 | 38309 | 21135 |
| 일반 부품 경로 통과 단계 | 6 | 17 |
| 체결부 배치 단계 | 41 | 41 |
| 사용자 예외 단계 | 1 | 3 |
| 미해결 일반 부품 | 16 | 3 |
| 기본 영상 생성 시간 (초) | 267.43 | 252.32 |
| 기본 영상 재생 길이 (초) | 305.50 | 278.50 |

순서 생성 시간 감소 55.5%, 신규 경로 요청 감소 11.1%.

입력 그룹·구성 바디·경계·부품 분류 일치=True. 후보 896건 중 차단 근거 재사용 704건이며, 동일 상태의 부품 판정 재사용은 176회다.

이전 v14와 후보 제한(180→240초), 예외 부품 수(1→3), 탐색 구조가 다르다. 모두 새 입력 캐시 실행이며, 단일 실행 중 UI 시험·EXE 빌드 부하가 포함되므로 동일 조건의 반복 성능시험은 아니다.

영상 생성 시간은 영상 길이·프레임 수도 함께 달라진 단일 실행 수치다.

전체 초안 64/64단계. 모든 경로 검증 완료=False. 일반 부품의 경로 통과는 전체 체결부를 제외한 상태의 결과이며, 체결부는 상세 경로 검사 없이 축방향 배치한다.

부품 쌍/Common 호출 수는 결과를 반환한 네이티브 요청의 집계다. 시간 초과로 종료한 요청의 부분 호출 수는 반환되지 않을 수 있으므로 신규 요청 수·시간 초과 수와 함께 해석한다.

## 막힌 부품과 원인

| 부품 | 마지막 검사 상태의 판정 | 상세 원인 | 상대 부품 |
|---|---|---|---|
| BLK-KD000 | {'BLOCKED': 5, 'UNKNOWN': 1} | {'OVERLAP_REINCREASE': 83, 'SWEEP_UNRESOLVED': 24, 'DECREASE_BOOLEAN_FAILED': 13} [] | BUS-KD200, COV-KD000, MBD-KD000, RLY-KET400 #1 |
| source · 바디 2 | {'BLOCKED': 6} | {'OVERLAP_REINCREASE': 107} [] | COV-KD000, MBD-KD000 |
| source · 바디 1 | {'BLOCKED': 6} | {'OVERLAP_REINCREASE': 54, 'SWEEP_UNRESOLVED': 18} [] | COV-KD000, MBD-KD000, source · 바디 2 |

위 판정은 기록된 직선 방향과 잔여 상태에 대한 결과다. 미해결 단계를 보충한 뒤 다시 검사한 결과나 모든 분해 방법의 불가능 증명이 아니다.

채택된 일반 부품 20개의 잔여 상태·방향·거리와 검사 기록을 대조했다. 두 릴레이는 이번 자동 순서에서 경로 통과 단계로 채택됐다.

## 체결부 삽입

41개 체결부를 중복 없이 삽입했다. 연결된 이동 부품들 중 첫 제거 부품보다 먼저 배치한 것을 감사했다. 연결 대상이 고정 부품뿐이거나 접촉 근거가 없는 체결부는 말미에 배치하고 JSON에 근거를 보존했다.

## 영상 및 UI 검증

영상 생성·수동 편집 후 재검토·플레이어·EXE 검증 수치는 아래 후속 검증 결과를 함께 확인한다.

### video-v16-final/video-validation.json

성공=True, 단계=64, 생성 시간=252.32초, 영상=C:\Users\Win11Pro\Documents\15_ai_data\_Final_Project\ver1\runtime-data\native-validation\video-v16-final\PA2_assembly_v16.mp4, CAD 재검사=0회.

### ui-review-v16-final.json

성공=True, 단계=64, 생성 시간=238.62초, 영상=C:\Users\Win11Pro\Documents\15_ai_data\_Final_Project\ver1\runtime-data\native-validation\PA2_assembly_ui-review-v16-final.mp4, CAD 재검사=0회.

실제 재검토 버튼 렌더=True, 미리보기 디코딩 프레임=75, 배속=2.0, Esc 전체화면 해제=True, 전체 디코딩 프레임=8400.

## 배포·원본 보존

- packaged-source-check-v16-final.json: 성공=True. EXE SHA-256=58b1542ed4d70ef8bdb4795ada641333cdd24721adc3d809663f34db5d9e9cba
- reference-integrity-v16.json: 성공=True.
- native-smoke-v16-final.json: 성공=True.
- gui-reopen-v16-final.json: 성공=True.

회귀시험: tests-v16-delivery.log의 201개 통과, 외부 실제 STEP 시험 1개는 별도 전체 실행으로 수행했다. 설치 개발환경이 없는 별도 PC의 검증은 이번 실행 범위에 포함하지 않았다.

## 검증 도구 보완 기록

첫 영상 검증은 감시 대상 클래스의 진입점 이름 오류로 렌더 시작 전에 종료했다. 실제 IsolatedCadWorker.call을 감시하도록 수정한 뒤 기본 영상을 완성했다. 예비 EXE 시험에서는 다중선택이 유지돼 방향 적용이 생략된 것을 발견했다. 단일선택을 명시하고 최적화된 EXE에서 생략되는 assert 대신 명시적 조건 검사를 사용했으며 Qt Flow 열거형 접근도 바로잡았다. 예비 ui-review-v16.json은 순서 변경만 확인한 기록이며, 최종 판단은 ui-review-v16-final.json을 사용한다.

최종 GUI 검증은 실제 재검토 버튼을 사용하고 진행률 중간값을 수집했다. QWidget 캡처의 native OpenGL 영역이 검게 찍힐 수 있어 ui-review-v16-final-scene.png에 VTK 렌더 버퍼를 따로 저장하고 형상을 확인했다. Qt 위젯 HWND와 VTK의 HWND도 일치함을 확인했다.

실행: open_validation_v16.bat. 사용자 편집·재검토·영상 생성은 간섭 검사를 생략하며 형식 검사만 유지한다.
