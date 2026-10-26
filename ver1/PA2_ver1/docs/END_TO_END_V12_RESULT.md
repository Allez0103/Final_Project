# v12 실제 모델 전체 흐름 검증 결과

생성 결과: **32/64단계**, `REVIEW_REQUIRED`. 순서 생성 시간 **51분 36초** (3096.146초).

입력부터 저장·부분 확정·재열기·영상 생성·내보내기·전체 프레임 디코딩까지 완료했다. 전체 분해 순서는 완성하지 못했다. v11보다 **8분 24초(14.0%) 단축**했으나, v10보다 **4분 02초(8.5%) 증가**했다. 이번 변경으로 큰 폭의 전체 시간 단축이나 단계 수 증가를 달성했다고 평가하지 않는다.

진행 관측에서는 32단계를 탐색 전 보고서 기록 후 23분 48초 이내에 확인했다. 이는 정확한 최종 개선 시각 계측이 아닌 관측 상한이다(`exterior-v12-observations.json`). 공식 전체 시간은 추가 방향·대안 탐색을 포함한 위의 계측값이다.

## 실행 범위

별도 데이터 루트 `runtime-data\end-to-end-v12-final`에서 제공 원본 STEP 19개를 새로 읽었다. 형상 캐시 hit 0/miss 19, 176바디/65그룹, 근접 243쌍, 접촉 121개, 접촉 미판정 0개. 입력·대응·접촉 총 4분 27초. 외부 원본은 수정하지 않았다.

앱과 동일한 입력·탐색·계획 저장·미리보기·확정·재열기·영상·내보내기 서비스를 호출했다. 전체 장시간 탐색은 검증 도구에서 수행했으며 GUI의 모든 버튼을 마우스로 반복 조작한 시험은 아니다.

## 알고리즘과 시간 비교

외부 노출 우선, 실제 유망 2방향, 접촉/차단 체결부 가상 제거 2방향, 가상 통과 시 실제 체결부 개별 제거와 대상 재검사, 전체 후보·방향 후순위 탐색을 적용했다. 지지·초기 겹침 감소·새 간섭 정책과 3600초 탐색 예산은 이전과 같다. 단순 접촉은 체결 관계의 대리 정보이며 실제 나사 연결 의미는 미확인이다.

| 실행 | 단계 | 순서 생성 시간 | 실제 후보 기록 | 신규 경로 요청 |
|---|---:|---:|---:|---:|
| v10 | 32/64 | 47분 34초 | 9871 | 직접 계측 없음 |
| v11 | 32/64 | 60분 00초 | 2652 | 783 |
| v12 | 32/64 | 51분 36초 | 2773 | 1247 |

v12 신규 요청은 실제 833회 + 가상 414회다. 가상 후보 기록 749개는 실제 후보 기록과 별개다. 차단 근거 재사용 2275회, 부품 쌍 계산 1038회, BREP_COMMON 30003회다. 강제 종료된 호출은 부분 연산 수를 보고할 수 없다. 후보 기록 감소를 같은 비율의 정밀 연산 절감으로 해석하지 않는다.

단일 실행 비교이며 기계 부하 변동이 포함된다. 새 입력/접촉 처리 중 자동 시험·배포 빌드·패키지 검증을 병행했고, 탐색 중 실제 형상의 짧은 영상 사전 검증을 실행했다. 엄격히 격리된 성능 벤치마크는 아니다.

65그룹의 바디 구성·경계 위치·분류는 이전 스냅샷과 모두 일치한다. 생성된 32개 부품 집합도 이전과 같으며 순서만 바뀌었다. 커버는 분해 11번째, 씰은 12번째다. 원본 실행 기록의 각 단계 실제 상태·방향·거리와 PASS 근거, 역순 조립 계획, 감소 예외 30쌍의 기록 감사를 통과했다(`exterior-v12-comparison.json`).

## 시간이 남은 이유

가상 검사에서 통과한 대상은 커버 1개였다. 논리적인 가상 검사 시도 수 1,455회에는 재방문 캐시 사용이 포함되므로 새 CAD 계산 수가 아니다. 고유 가상 기록 749개 중 신규 경로 요청은 414회, 기록된 계산 시간 합계는 **80.92초**다. 가상 검사 자체보다 실제 경로 연산과 후속 탐색의 비용이 컸다.

실제 경로의 신규 요청은 833회였고 기록된 계산 시간 합계는 2,996.52초다. 실제 미판정 요청 259회의 시간은 514.13초이며, 가상 미판정까지 합하면 550.65초다. 특히 **source 바디 44가 701.87초(약 11분 42초)**를 사용했고, 그중 미판정 6건이 449.69초였다. 후보 시간 제한으로 종료된 2건도 포함된다. 이 부품은 v10의 331.55초보다 약 370초 늘어 전체 시간 증가에 크게 기여했다. 비용 합계는 원래 계산 시간을 반복 합산하지 않도록 새 native 결과만 집계했다(`exterior-v12-costs.json`).

상태 방문 119회/고유 잔여 상태 40개, 탐색 완료 상태 4개, 완료 상태 건너뛰기 5회, 부품 평가 캐시 2,416회를 기록했다. 정확히 같은 상태의 중복 계산 억제는 동작했지만, 서로 다른 잔여 상태에서 남아 있는 미판정 곡면을 재검사하는 비용까지 제거하지는 못했다. 미판정을 충돌 확정으로 바꾸거나 통과시키지는 않았다.

이번 초기 점검 실행은 후순위 일반부품의 전체 방향 검사가 볼트 검사를 늦추는 것을 확인한 뒤 중단했다. 후순위 체결부 우선으로 보완하고 **별도 새 데이터 루트에서 다시 처음부터 실행한 최종 결과만** 위 표에 사용했다. 초기 점검 로그는 `planning-exterior-v12.log`, 최종 측정은 `planning-exterior-v12-final.log`로 구분한다.

## 끝까지 생성되지 않은 원인과 검사 범위

탐색 종료 조건: **역추적 횟수 제한 도달**. 부분 검토용 초안 32/64단계입니다. 초기 영역 예외 0단계, 지지 미검증 32단계로 검토가 필요합니다. 초기 겹침 감소 예외 30단계(위치별 검사; 동일 상대의 국소 새 간섭 배제 불가). 충돌·경로 미판정 또는 탐색 예산으로 제외된 부품은 진단에서 확인하세요.

전체 3,600초를 소진한 것은 아니다. 설정상 되돌아가기 100회 제한에 도달했고, 재귀 복귀 중 증가한 계수까지 포함한 기록값은 118회다. 최장 순서 끝 상태의 **418개 방향에서 차단 374개·미판정 44개**가 기록됐다. 잔여 32개 부품 중 **23개는 검사한 생성 방향 모두 차단**, **9개는 미판정 방향 포함**이다.

핵심 원인은 MBD-KD000·BUS-KD200 등 잔여 부품과의 실제 경로 충돌 및 겹침 재증가다. 미판정은 RLY-KET400 2개의 정밀 형상 유효성 실패, 그 릴레이를 상대하는 BLT-WASM612A 4개의 경로, 바디 41·42·44의 곡면 이동 영역과 시간 제한에 집중됐다. 고정 부품은 제거 후보에서만 제외했으므로 MBD-KD000은 충돌 상대에 계속 포함한다. 단순 직선 후보의 실패를 회전·다단 이동을 포함한 모든 분해 방법의 불가능 판정으로 해석하지 않는다.

최장 순서 끝의 잔여 이동 부품 32개를 아래에 정리했다. 탐색 기록과 별도 제한 방향 진단(부품당 최대 2방향, 방향당 30초)을 합쳤다. 진단 시간 1분 24초. 검증하지 않은 방향을 차단으로 분류하지 않았다. 최장 단계 수가 물리적으로 가능한 최대치라는 뜻은 아니다.

추가 진단에서 동일 상태·이동의 기존 확정 판정 57건을 재사용하고, 미검사·미판정 경로 7건을 새로 요청했다. 추가 진단의 시간 제한은 주 탐색보다 짧으므로, 기존에 미판정인 경로가 여전히 미판정이면 기존의 더 넓은 검사 기록도 함께 보존한다.

| 잔여 부품 | 검사 방향 | 차단 | 미판정 | 경로 통과 | 차단 상대 | 근거 코드 |
|---|---:|---:|---:|---:|---|---|
| BLK-KD000 | 18 | 18 | 0 | 0 | NUT-FLGM5A #4, BUS-KD200, MBD-KD000 | PATH_BLOCKED, OVERLAP_REINCREASE |
| BLT-WASM612A #1 | 10 | 9 | 1 | 0 | BUS-KD200, MBD-KD000 | PATH_BLOCKED, INPUT_GEOMETRY_INVALID, EXACT_COLLISION_WITNESS |
| BLT-WASM612A #2 | 10 | 9 | 1 | 0 | BUS-KD200, MBD-KD000 | PATH_BLOCKED, INPUT_GEOMETRY_INVALID, EXACT_COLLISION_WITNESS |
| BLT-WASM612A #3 | 10 | 9 | 1 | 0 | BUS-KD200 | EXACT_COLLISION_WITNESS, PATH_BLOCKED, INPUT_GEOMETRY_INVALID |
| BLT-WASM612A #4 | 10 | 9 | 1 | 0 | BUS-KD200, MBD-KD000, BLT-WASM620R #13 | PATH_BLOCKED, INPUT_GEOMETRY_INVALID, EXACT_COLLISION_WITNESS |
| BLT-WASM620R #12 | 12 | 12 | 0 | 0 | BUS-KD200, BUS-KD100 | EXACT_COLLISION_WITNESS, PATH_BLOCKED |
| BLT-WASM620R #13 | 12 | 12 | 0 | 0 | BUS-KD200, MBD-KD000, BUS-KD000 | PATH_BLOCKED |
| BLT-WASM620R #21 | 12 | 12 | 0 | 0 | BUS-KD200, MBD-KD000, HVSC 2800 #2 | OVERLAP_REINCREASE, PATH_BLOCKED |
| BUS-KD000 | 6 | 6 | 0 | 0 | NUT-FLGM5A #2, BUS-KD200, BLT-WASM612A #2 | PATH_BLOCKED |
| BUS-KD100 | 6 | 6 | 0 | 0 | NUT-FLGM5A #1, BUS-KD200, BLT-WASM612A #1 | PATH_BLOCKED |
| BUS-KD200 | 6 | 6 | 0 | 0 | NUT-FLGM5A #2, NUT-FLGM5A #3, MBD-KD000, BLT-WASM620R #12 | PATH_BLOCKED |
| BUS-KD300 | 6 | 6 | 0 | 0 | NUT-FLGM5A #4, BUS-KD200, MBD-KD000, BLT-WASM620R #13 | PATH_BLOCKED |
| HVSC 2800 #1 | 18 | 18 | 0 | 0 | BUS-KD200 | PATH_BLOCKED |
| HVSC 2800 #2 | 18 | 18 | 0 | 0 | BUS-KD200, MBD-KD000 | PATH_BLOCKED, OVERLAP_REINCREASE |
| LV CONT | 18 | 18 | 0 | 0 | NUT-FLGM5A #1, NUT-FLGM5A #3, NUT-FLGM5A #4, BUS-KD200 | PATH_BLOCKED |
| NUT-FLGM5A #1 | 10 | 10 | 0 | 0 | BUS-KD200, MBD-KD000, BUS-KD100 | PATH_BLOCKED |
| NUT-FLGM5A #2 | 10 | 10 | 0 | 0 | BUS-KD200, MBD-KD000, BUS-KD000 | PATH_BLOCKED |
| NUT-FLGM5A #3 | 10 | 10 | 0 | 0 | BUS-KD200, MBD-KD000 | PATH_BLOCKED |
| NUT-FLGM5A #4 | 10 | 10 | 0 | 0 | BUS-KD200, MBD-KD000, BUS-KD300 | PATH_BLOCKED |
| RLY-KET400 #1 | 18 | 0 | 18 | 0 | — | INPUT_GEOMETRY_INVALID |
| RLY-KET400 #2 | 18 | 0 | 18 | 0 | — | INPUT_GEOMETRY_INVALID |
| source · 바디 1 | 20 | 20 | 0 | 0 | MBD-KD000, source · 바디 2 | OVERLAP_REINCREASE, PATH_BLOCKED |
| source · 바디 2 | 20 | 20 | 0 | 0 | MBD-KD000 | OVERLAP_REINCREASE |
| source · 바디 40 | 18 | 18 | 0 | 0 | NUT-FLGM5A #1, NUT-FLGM5A #2, MBD-KD000 | PATH_BLOCKED |
| source · 바디 41 | 22 | 21 | 1 | 0 | NUT-FLGM5A #1, BUS-KD200, MBD-KD000, HVSC 2800 #1 | PATH_BLOCKED, SWEEP_UNRESOLVED |
| source · 바디 42 | 22 | 21 | 1 | 0 | NUT-FLGM5A #1, MBD-KD000, BLK-KD000 | PATH_BLOCKED, SWEEP_UNRESOLVED |
| source · 바디 43 | 22 | 22 | 0 | 0 | NUT-FLGM5A #1, BUS-KD200, MBD-KD000, BLT-WASM620R #13, BLT-WASM620R #21 | PATH_BLOCKED |
| source · 바디 44 | 22 | 20 | 2 | 0 | NUT-FLGM5A #1, NUT-FLGM5A #3, NUT-FLGM5A #4, BUS-KD200, MBD-KD000, BUS-KD000 | PATH_BLOCKED, SWEEP_UNRESOLVED, TIME_BUDGET_EXCEEDED |
| source · 바디 45 | 6 | 6 | 0 | 0 | NUT-FLGM5A #4, MBD-KD000 | OVERLAP_REINCREASE, PATH_BLOCKED |
| source · 바디 46 | 6 | 6 | 0 | 0 | NUT-FLGM5A #3, MBD-KD000 | OVERLAP_REINCREASE, PATH_BLOCKED |
| source · 바디 47 | 6 | 6 | 0 | 0 | NUT-FLGM5A #2, MBD-KD000 | OVERLAP_REINCREASE, PATH_BLOCKED |
| source · 바디 48 | 6 | 6 | 0 | 0 | NUT-FLGM5A #1, MBD-KD000 | OVERLAP_REINCREASE, PATH_BLOCKED |

코드 해석: OVERLAP_REINCREASE=초기 겹침의 허용 오차 이상 재증가; DECREASE_TAIL_BLOCKED=겹침 해소 후 경로 충돌; INPUT_GEOMETRY_INVALID=입력 정밀 유효성 실패; SWEEP_UNRESOLVED=곡면 이동 영역 판정 미해결; DIAGNOSTIC_NATIVE_ERROR/시간 제한=진단 예산 또는 native 호출 실패로 미판정. 상세 수치·상대 ID·원문은 요약 JSON과 원본 경로 기록에 보존한다.

## 영상과 내보내기

생성한 32단계를 역순 조립 영상으로 출력했다. 미계획 부품은 조립된 상태로 유지하고 모든 프레임에 부분 단계 수를 표시한다. 길이 129.00초, 3870프레임, 1920×1080/30fps/H.264/yuv420p. 렌더링 2분 22초, 크기 5,038,188바이트.

영상: `C:\Users\Win11Pro\Documents\15_ai_data\_Final_Project\ver1\runtime-data\native-validation\video-v12-final\PA2_partial_assembly_v12.mp4`

저장·재열기 내용 일치, 영상 내보내기 SHA-256 일치, 전체 MP4 디코딩 종료 코드 0, 마지막 장면의 전 부품 표시 및 모든 이동 변환 0을 확인했다. 시작·중간·마지막 프레임 PNG도 추출했다. 초기 겹침 감소 예외와 지지 미확인 경고는 계획 JSON에 원문으로 유지하며 영상에는 읽기 쉬운 요약을 표시한다.

3,870프레임 전부 디코딩됐고 예상 프레임 수와 일치했다. 시작·중간·마지막 PNG를 직접 확인해 모델의 화면 맞춤, 한글·로고·부분 표시·주의사항이 영역 안에 표시되는 것을 확인했다. 미계획 부품을 유지하므로 마지막 화면에 완제품 전체가 보여도 전체 조립 순서를 증명한 영상은 아니다. 영상 길이는 **2분 09초**, 생성 시간은 **2분 22초**, 파일은 약 **5.04 MB**다.

카메라 전환 구간에서 시점이 즉시 바뀌던 부분에 실제 회전 보간과 180도 전환 처리를 추가했다. 부분 계획 전용 형식 검사, 부분 확정의 학습 제외, 취소·제한 시간 검사, 긴 자동 경고의 요약 표시와 원문 보존도 반영했다.

## 최종 검증과 열기

- 자동 시험: **167 통과, 1 생략**, 42.60초. 경고 6개는 VTK/NumPy 배열 변환의 deprecated API 경고다. `tests-exterior-v12-final-check.log`.
- 최종 실행 파일: `dist/PA2/PA2.exe`, 재빌드 137.43초, 패키지 native smoke `ok=true`/종료 코드 0. `packaged-exterior-v12-final-smoke.json`.
- 참고자료 및 원본 로고 **24개 모두 SHA-256 일치**. `reference-integrity-exterior-v12-final.json`.
- `ver1/open_validation_v12.bat`을 실행하고 검증 프로젝트를 열면 저장한 부분 순서를 확인할 수 있다. 기존 사용자 데이터 루트와 별도로 실행한다.
- 실제 영상: [부분 조립 MP4](../runtime-data/native-validation/video-v12-final/PA2_partial_assembly_v12.mp4).

후속 개선 후보로는 같은 부품 쌍·방향·거리에서 반복되는 미판정/시간 초과의 재시도 횟수 제한, 확보한 부분 순서의 조기 저장·영상화와 추가 탐색 분리, 곡면 경로 판정 보완이 있다. 이번에는 미판정을 통과시키는 정책이나 새로운 형상 완화 기준을 추가하지 않았다.

## 순서

아래는 분해 순서이며 영상은 역순이다.

1. BLT-WASM620R #1
2. BLT-WASM620R #7
3. BLT-WASM620R #4
4. BLT-WASM620R #6
5. BLT-WASM620R #10
6. BLT-WASM620R #9
7. BLT-WASM620R #3
8. BLT-WASM620R #8
9. BLT-WASM620R #5
10. BLT-WASM620R #2
11. COV-KD000
12. SEL-KD000
13. BLT-WASM412B #1
14. BLT-WASM412B #2
15. BLT-WASM620R #23
16. BLT-WASM520A #2
17. BLT-WASM520A #1
18. BLT-WASM520A #7
19. BLT-WASM520A #8
20. BLT-WASM520A #3
21. BLT-WASM520A #4
22. BLT-WASM520A #5
23. BLT-WASM520A #6
24. BLT-WASM620R #18
25. BLT-WASM620R #19
26. BLT-WASM620R #15
27. BLT-WASM620R #14
28. BLT-WASM620R #11
29. BLT-WASM620R #16
30. BLT-WASM620R #20
31. BLT-WASM620R #17
32. BLT-WASM620R #22

## 재현 자료

- 원본 실행: `runtime-data\native-validation\planning-exterior-v12-final.json`
- 잔여 상태 추가 진단: `runtime-data\native-validation\retained-exterior-v12-final.json`
- 이름·수치·상세 경로 요약: `runtime-data\native-validation\exterior-v12-summary.json`
- 영상 검증: `runtime-data\native-validation\video-v12-final\video-validation.json`
- 설계: `EXTERIOR_VIRTUAL_SEARCH.md`
