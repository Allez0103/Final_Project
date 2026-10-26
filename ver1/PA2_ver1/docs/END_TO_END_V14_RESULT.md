# v14 전체 초안·영상 실행 결과

초안 64/64단계, 순서 생성 42분 45.75초. 편집용 초안 64/64단계 생성. 볼트·너트 축방향 배치 41개, 해결되지 않은 일반 부품 16개. 사용자 지정 예외 1개를 분해 선두에 배치했습니다.

| 항목 | 이전 완료 실행 v12 | 이번 v14 |
|---|---:|---:|
| 초안 단계 수 | 32/64 | 64/64 |
| 순서 생성 시간 | 51분 36.15초 | 42분 45.75초 |
| 실제/체결부 임시 제거 상태 후보 기록 | 2773 | 540 |
| 전체 체결부 제외 초안 후보 기록 | 749 | 270 |
| 후보 기록 합계 | 3522 | 810 |
| 신규 CAD 경로 요청 | 1247 | 216 |
| 부품 쌍 계산 | 1038 | 403 |
| BREP Common 호출 | 30003 | 38309 |

이번 초안 구성: 경로 PASS 6개, 상세 경로 검사를 생략한 볼트·너트 41개, LV CONT 예외 1개, 해결되지 않은 일반 부품 16개.
이전 v12는 모든 채택 단계에서 경로를 검사했다. 검사 범위가 달라진 단일 실행 비교이므로 같은 정확도의 단순 속도 향상으로 해석하지 않는다.
입력 그룹·바디·경계·분류 일치: True. 수치 설정 일치: True. 신규 데이터 루트의 차가운 입력 캐시로 실행했다.
입력·그룹화·접촉 준비: 4분 31.14초. 순서 생성과 별도 계측.
입력 준비 구간에 EXE 재빌드를 병행했다. 순서 생성 비교는 준비 시간과 구분하며 단일 실행의 환경 부하 차이를 포함한다.
방향 힌트 99회/150.85초. 후보와 별도이며 순서 생성 시간에 포함.
탐색 종료: limited_search_blocked_or_unknown. 초안 전체 포함: True. 모든 경로 검증 완료: False.

가상 초안 예산 배분: 전체의 35%, 배분 한도 도달: True. 남은 전체 예산은 실제 상태 검사에 사용했다.

## 해결되지 않은 일반 부품

| 부품 | 기록된 판정 | 이유 | 차단/미판정 상대 |
|---|---|---|---|
| BLK-KD000 | {'BLOCKED': 35, 'UNKNOWN': 1} | {'PATH_BLOCKED': 35, 'TIME_BUDGET_EXCEEDED': 1} / {'OVERLAP_REINCREASE': 18, 'SWEEP_UNRESOLVED': 6, 'DECREASE_BOOLEAN_FAILED': 1} | COV-KD000, BUS-KD200, MBD-KD000, BLT-WASM620R #22 |
| HVSC 2800 #1 | {'BLOCKED': 36} | {'PATH_BLOCKED': 36} / {'OVERLAP_REINCREASE': 26, 'SWEEP_UNRESOLVED': 12} | COV-KD000, BUS-KD200, MBD-KD000 |
| HVSC 2800 #2 | {'BLOCKED': 36} | {'PATH_BLOCKED': 36} / {'OVERLAP_REINCREASE': 30} | COV-KD000, BUS-KD200, MBD-KD000 |
| source · 바디 2 | {'BLOCKED': 18} | {'PATH_BLOCKED': 18} / {'OVERLAP_REINCREASE': 17} | COV-KD000, MBD-KD000 |
| source · 바디 1 | {'BLOCKED': 18} | {'PATH_BLOCKED': 18} / {'OVERLAP_REINCREASE': 9, 'SWEEP_UNRESOLVED': 3} | COV-KD000, MBD-KD000, source · 바디 2 |
| source · 바디 42 | {'BLOCKED': 34, 'UNKNOWN': 2} | {'PATH_BLOCKED': 34, 'PATH_UNKNOWN': 2} / {'SWEEP_UNRESOLVED': 2} | COV-KD000, MBD-KD000, BLT-WASM620R #18, source · 바디 40 |
| source · 바디 41 | {'BLOCKED': 34, 'UNKNOWN': 2} | {'PATH_BLOCKED': 34, 'PATH_UNKNOWN': 2} / {'SWEEP_UNRESOLVED': 2} | COV-KD000, MBD-KD000, BLT-WASM620R #19, source · 바디 40 |
| source · 바디 43 | {'BLOCKED': 34, 'UNKNOWN': 2} | {'PATH_BLOCKED': 34, 'PATH_UNKNOWN': 2} / {'SWEEP_UNRESOLVED': 2} | COV-KD000, MBD-KD000, BLT-WASM620R #21, source · 바디 40 |
| source · 바디 40 | {'BLOCKED': 48} | {'PATH_BLOCKED': 48} / {'SWEEP_UNRESOLVED': 8} | NUT-FLGM5A #3, BUS-KD200, MBD-KD000, BLT-WASM620R #18, BLT-WASM620R #19, BLT-WASM620R #20, BLT-WASM620R #21, RLY-KET400 #1 |
| RLY-KET400 #2 | {'UNKNOWN': 2, 'BLOCKED': 22} | {'PATH_UNKNOWN': 2, 'PATH_BLOCKED': 22} / {'SWEEP_UNRESOLVED': 14} | COV-KD000, NUT-FLGM5A #3, BUS-KD200, MBD-KD000 |
| RLY-KET400 #1 | {'BLOCKED': 23, 'UNKNOWN': 1} | {'PATH_BLOCKED': 23, 'PATH_UNKNOWN': 1} / {'SWEEP_UNRESOLVED': 13} | NUT-FLGM5A #3, BUS-KD200, MBD-KD000 |
| source · 바디 44 | {'BLOCKED': 23, 'UNKNOWN': 1} | {'PATH_BLOCKED': 23, 'PATH_UNKNOWN': 1} / {'SWEEP_UNRESOLVED': 1} | COV-KD000, BUS-KD200, MBD-KD000, BLT-WASM620R #20, source · 바디 40 |
| source · 바디 45 | {'BLOCKED': 18} | {'PATH_BLOCKED': 18} / {} | MBD-KD000, RLY-KET400 #1 |
| source · 바디 48 | {'BLOCKED': 18} | {'PATH_BLOCKED': 18} / {} | MBD-KD000, RLY-KET400 #2 |
| source · 바디 46 | {'BLOCKED': 24} | {'PATH_BLOCKED': 24} / {'OVERLAP_REINCREASE': 10, 'INITIAL_DECREASE_SAMPLED': 4} | NUT-FLGM5A #3, MBD-KD000, RLY-KET400 #1 |
| source · 바디 47 | {'BLOCKED': 18} | {'PATH_BLOCKED': 18} / {} | MBD-KD000, RLY-KET400 #2 |

이 표는 검사한 직선 방향과 제한 시간 내 기록이다. 물리적으로 가능한 모든 분해 방법의 불가능 판정은 아니다.
표의 판정은 탐색 중 과거 상태에서 관측한 결과이며, 미해결 단계를 순차 보충한 뒤의 상태에서 모두 재검사했다는 뜻은 아니다. 상태 해시는 JSON에 보존한다.
미해결 단계는 NOT_TESTED/DRAFT_UNRESOLVED로 보존하고 화면에서 경로 확인 필요로 표시한다. 볼트·너트는 NOT_TESTED/FASTENER_AXIS_ASSIGNED를 내부 보존하되 화면 경고는 표시하지 않는다.
LV CONT는 노출도 1순위 방향으로 분해 선두에 두고 이후 장애물·지지 검사에서 제외했다.

## 주요 계산 비용

| 부품 | 신규 경로 요청 | 반환 결과 계산시간 합계 |
|---|---:|---:|
| RLY-KET400 #2 | 12 | 397.37초 |
| HVSC 2800 #2 | 8 | 372.72초 |
| HVSC 2800 #1 | 10 | 255.82초 |
| RLY-KET400 #1 | 12 | 217.73초 |
| BLK-KD000 | 12 | 207.03초 |
| source · 바디 40 | 18 | 193.23초 |
| SEL-KD000 | 8 | 163.88초 |
| COV-KD000 | 8 | 111.83초 |
| source · 바디 42 | 13 | 88.67초 |
| source · 바디 43 | 11 | 88.26초 |

## 최장 제거열 끝의 직접·체결부 임시 제거 검사

최장 제거열 31단계 끝의 실제 잔여 상태를 복원했다. 해당 상태에서 기록된 직접 검사와 관련 체결부 임시 제거 검사를 대조했다. 부품별 마지막 기록 상태 기준 분류: {'HAS_UNKNOWN': 7, 'ALL_SIX_BLOCKED': 9}.

| 부품 | 분류 | 마지막 검사 판정 | 원인 코드 | 상대 |
|---|---|---|---|---|
| BLK-KD000 | HAS_UNKNOWN | {'BLOCKED': 5, 'UNKNOWN': 1} | {'OVERLAP_REINCREASE': 5} ['시간 제한 초과: BREP_COMMON'] | MBD-KD000 |
| HVSC 2800 #1 | ALL_SIX_BLOCKED | {'BLOCKED': 6} | {'OVERLAP_REINCREASE': 6} [] | MBD-KD000 |
| HVSC 2800 #2 | ALL_SIX_BLOCKED | {'BLOCKED': 6} | {'OVERLAP_REINCREASE': 6} [] | MBD-KD000 |
| source · 바디 2 | ALL_SIX_BLOCKED | {'BLOCKED': 6} | {'OVERLAP_REINCREASE': 6} [] | MBD-KD000 |
| source · 바디 1 | ALL_SIX_BLOCKED | {'BLOCKED': 6} | {'OVERLAP_REINCREASE': 3} [] | MBD-KD000, source · 바디 2 |
| source · 바디 42 | HAS_UNKNOWN | {'UNKNOWN': 1, 'BLOCKED': 5} | {'SWEEP_UNRESOLVED': 1} [] | MBD-KD000, source · 바디 40 |
| source · 바디 41 | HAS_UNKNOWN | {'UNKNOWN': 1, 'BLOCKED': 5} | {'SWEEP_UNRESOLVED': 1} [] | MBD-KD000, source · 바디 40 |
| source · 바디 43 | HAS_UNKNOWN | {'UNKNOWN': 1, 'BLOCKED': 5} | {'SWEEP_UNRESOLVED': 1} [] | MBD-KD000, source · 바디 40 |
| source · 바디 40 | ALL_SIX_BLOCKED | {'BLOCKED': 6} | {} [] | MBD-KD000, RLY-KET400 #1 |
| RLY-KET400 #2 | HAS_UNKNOWN | {'UNKNOWN': 1, 'BLOCKED': 5} | {'SWEEP_UNRESOLVED': 1} [] | MBD-KD000 |
| RLY-KET400 #1 | HAS_UNKNOWN | {'UNKNOWN': 1, 'BLOCKED': 5} | {'SWEEP_UNRESOLVED': 1} [] | MBD-KD000 |
| source · 바디 44 | HAS_UNKNOWN | {'UNKNOWN': 1, 'BLOCKED': 5} | {'SWEEP_UNRESOLVED': 1} [] | MBD-KD000, source · 바디 40 |
| source · 바디 45 | ALL_SIX_BLOCKED | {'BLOCKED': 6} | {} [] | MBD-KD000, RLY-KET400 #1 |
| source · 바디 48 | ALL_SIX_BLOCKED | {'BLOCKED': 6} | {} [] | MBD-KD000, RLY-KET400 #2 |
| source · 바디 46 | ALL_SIX_BLOCKED | {'BLOCKED': 6} | {} [] | MBD-KD000, RLY-KET400 #1 |
| source · 바디 47 | ALL_SIX_BLOCKED | {'BLOCKED': 6} | {} [] | MBD-KD000, RLY-KET400 #2 |

반환 결과 시간 합계는 요청·IPC를 포함한 전체 경과 시간과 다를 수 있다. 차단 근거·상태 캐시 재사용 시간은 다시 합산하지 않았다.

## 원인 분석

순서 생성은 전체 60분을 소진하지 않고 제한된 순서·방향·되돌아가기 탐색에서 더 채택할 경로를 얻지 못해 종료했다. 가상 초안은 21분 배분 한도에 도달했고, 이후 실제 상태 검사를 수행했다. 최장 채택 제거열 31단계 뒤에는 미해결 일반 부품 16개와 아직 배치하지 않은 체결부가 남았으며, 이를 편집용 단계로 보충해 64단계를 만들었다.
실제 경로 PASS 일반 부품은 커버·씰·버스바 4개다. 이 6개도 지지는 미확인이어서 SUPPORT_UNVERIFIED로 보존했다. 41개 볼트·너트는 실제 원통축을 추출했고, 축을 얻지 못해 대체 방향을 사용한 배치는 없었다.
미해결 9개는 관련 체결부 임시 제거까지 포함한 마지막 기록 상태에서 6방향 모두 차단됐고, 7개는 미판정 방향을 포함한다. HVSC 2개와 바디 2 등은 본체 상대의 초기 겹침 재증가가 주된 차단 근거다. 다른 익명 바디는 본체·다른 바디·릴레이와의 경로 차단이 남는다.
릴레이 #1·#2의 +Z는 본체 상대 SWEEP_UNRESOLVED다. 각 결과에는 BSpline 면 2곳의 SWEEP_CONSTRUCTION_FAILED가 남는다. 이전의 뒤집힌 검사 솔리드 오류는 수정했지만 이 별도 곡면 포락체 생성 실패까지 해결된 것은 아니다. INPUT_GEOMETRY_INVALID에 의한 거부와 구분한다.
BLK-KD000의 체결부 임시 제거 후 -X는 BREP_COMMON 정밀 교차 연산 제한으로 미판정이다. 다른 5방향에는 본체 상대 초기 겹침 재증가가 기록됐다. 바디 41·42·43·44는 곡면 이동 영역의 SWEEP_UNRESOLVED가 남는다.
신규 경로 요청은 82.7% 감소했지만 시간은 17.1% 감소했다. 반환 결과에서 집계한 BREP Common 연산은 30,003→38,309회로 늘었다. 남은 복잡한 일반 부품의 한 경로 안에서 많은 연산이 수행되므로 요청 수와 실제 계산량·시간은 비례하지 않는다. 중단된 호출의 내부 연산은 카운터에 포함되지 않는다. 상세 병목은 위 비용 표에 기록했다.
추가 개선 대상은 BSpline 이동 검사 형상 생성과 긴 곡면 교차 연산이다. 이번 결과에서는 간섭 허용값을 더 늘리거나 이 실패를 PASS로 바꾸지 않았다.

## 순서와 감사

분해 순서: LV CONT, BLT-WASM620R #7, BLT-WASM620R #4, BLT-WASM620R #6, BLT-WASM620R #10, BLT-WASM620R #9, BLT-WASM620R #1, BLT-WASM620R #3, BLT-WASM620R #5, BLT-WASM620R #8, BLT-WASM620R #2, COV-KD000, SEL-KD000, BLT-WASM620R #15, BLT-WASM620R #14, BLT-WASM612A #2, NUT-FLGM5A #2, BUS-KD000, BLT-WASM620R #13, BLT-WASM612A #4, NUT-FLGM5A #4, BUS-KD300, BLT-WASM620R #11, BLT-WASM620R #16, BLT-WASM612A #1, NUT-FLGM5A #1, BUS-KD100, BLT-WASM620R #17, BLT-WASM612A #3, BLT-WASM620R #12, BUS-KD200, BLT-WASM620R #23, BLT-WASM620R #22, BLK-KD000, BLT-WASM520A #2, BLT-WASM520A #1, BLT-WASM520A #3, BLT-WASM520A #4, HVSC 2800 #1, BLT-WASM520A #7, BLT-WASM520A #8, BLT-WASM520A #5, BLT-WASM520A #6, HVSC 2800 #2, source · 바디 2, source · 바디 1, BLT-WASM620R #18, source · 바디 42, BLT-WASM620R #19, source · 바디 41, BLT-WASM620R #21, source · 바디 43, source · 바디 40, RLY-KET400 #2, NUT-FLGM5A #3, RLY-KET400 #1, BLT-WASM620R #20, source · 바디 44, source · 바디 45, source · 바디 48, source · 바디 46, source · 바디 47, BLT-WASM412B #1, BLT-WASM412B #2

실제 잔여 상태·방향·거리와 일치하는 증거 64개, 역순 조립, 중복·누락, 품명·빈 주의사항을 감사했다.
기존 중단된 v13 실행은 최종 측정값이 없어 비교 기준으로 사용하지 않았다.
v14 예비 실행(planning-v14-final.log)은 반복 차단 검사·시간 배분 병목 확인 후 중단했다. 비교 표는 planning-v14-cache-final.json의 별도 새 입력 최종 실행만 사용한다.

세부 방향별 실패, 장애물 ID, 쌍별 진단, 가상 검사 결과는 비교 JSON과 원본 실행 JSON에 보존한다.

## 영상·패키지 검증

영상: 64단계, 1920×1080/30fps/H.264/yuv420p, 305.5초, 9,165프레임. 생성 267.43초. 관리 저장·내보내기 해시·전체 프레임 디코딩 통과. 영상 생성 중 EXE 재빌드를 병행했으므로 이 영상 생성 시간은 별도 격리 성능 측정이 아니다.
모든 영상 프레임에서 초점 변화 0.0, 거리 변화 2.27e-13, 시야각 30.0도를 확인했다. 64단계 모두 이동 전 강조 ON/OFF, 이동 중 강조 유지 검사를 통과했다. 첫 점멸 ON/OFF·중간·최종 프레임을 추출해 품명·빈 주의사항 패널·한글·로고를 시각 확인했다.
최종 장면은 65그룹 전체 표시·모든 이동 변환 0이며 저장·재열기 계획이 동일하다. 주의사항은 64단계 모두 빈칸이고 자재정보는 모두 품명이다.
영상 파일: `C:\Users\Win11Pro\Documents\15_ai_data\_Final_Project\ver1\runtime-data\native-validation\video-v14-final\PA2_assembly_v14.mp4`.
최종 EXE 재열기: ok=True, 65그룹/64단계, LV CONT 예외 복원, UI 스레드 갱신=True, 볼트·너트 카드의 미검증 경고 없음=True, 실제 3D 버퍼 형상 표시=True.
Qt의 일반 위젯 캡처에는 native OpenGL 영역이 검게 찍힐 수 있어 실제 VTK 렌더 버퍼를 별도 PNG(gui-reopen-v14-final-scene.png)로 저장하고 형상 픽셀 변화를 확인했다.
배포 소스 일치: True, 15모듈 및 템플릿·로고 비교. EXE SHA-256 `c767148a1d6b2d81f0c5108877ecc2a078099c1ad6518474783daf962643da40`.
원본 보존: 24개 해시 일치=True. 제공 CAD·참고자료·원 로고를 수정하지 않았다.
최종 자동시험: 191개 통과, 1개 생략. 실제 STEP은 별도 전체 실행으로 검증했다.

실제 GUI 재열기 시험 중 별도 VTK 접근 위반을 재현하고 완료 콜백의 UI 스레드 전달을 수정했다. 이 UI 수정 이후 최종 EXE에서 동일 프로젝트 재열기를 재검증했다. 원인·수정 전후 스레드 근거는 EXE_VTK_THREAD_FIX.md에 기록했다. 이 수정은 위 순서 생성·영상의 경로 계산을 변경하지 않는다.
