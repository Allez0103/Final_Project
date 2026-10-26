# v19 전체 실행·배포 검증 결과

2026-10-20, 현재 Windows PC에서 실제 ZIP 압축 해제본 EXE로 검증했다. 개발용 PYTHONPATH와 PATH를 제거하고 PATH는 Windows/System32 및 Windows만 사용했다. 입력은 기존 v17 프로젝트의 **독립 복사본**이다. 원래 프로젝트와 제공 파일은 수정하지 않았다.

## 반영 사항과 실제 화면 테스트

- ‘재검토’ 제거, ‘영상 생성’ 단일 버튼 및 명시적인 ‘순서 확정’ 유지.
- 기존 64그룹/63단계 프로젝트 열기, 자동 그룹 해제 금지 확인.
- 미매칭 바디 41·42를 수동 그룹으로 묶기 → 이름 직접 입력/선택 부품명 목록 확인 → 재열기 → 그룹해제 → 다시 묶기 통과.
- 수동 그룹은 한 부품·한 카드·한 이동 단위로 저장됐다. 기존 자동 그룹의 내부 바디와 이전 확정본은 보존됐다.
- 그룹 변경 시 이전 초안·확정 포인터를 비우고 순서 재생성을 요구했다. 방향 입력 없이 순서 생성에서 방향과 거리를 정했다.
- 순서 생성 → 확정 → 첫 영상 생성 → 카드 다중 이동/실행 취소 → 방향·카메라·문구 편집 → 미리보기 → 적용·저장·재열기 → 재확정 → 두 번째 영상 생성 통과.
- 적용 전 속성 수정과 확정 이후 순서 수정 시 영상 생성을 차단했다. 저장·재열기 후에도 재확정을 요구했다.
- 편집·확정·영상 생성 동안 CAD 접촉·경로 재검사 **0회**. 검사 호출이 생기면 시험이 실패하도록 차단했다.
- 영상 중간 진행률, 내장 미리보기 디코딩, 2배속, 전체화면과 Esc 해제 통과.

이번 수동 묶음은 기능 시험을 위한 두 미매칭 바디의 묶음이며, 실제 제작 조립체로 승인한 부품 식별·그룹화 결과를 뜻하지 않는다. 그룹 수는 64→63, 이동 단위는 63→62개로 달라졌다. 간섭 판정 기준은 변경하지 않았다. 예외 부품은 LV CONT, HVSC 2800 #1·#2, AIR-BENT0A로 유지했다.

## 이전 결과와 비교

| 항목 | 이전 v17 실측 | 이번 v19 실측 |
|---|---:|---:|
| 순서 생성 시간(초) | 893.614 | 935.932 |
| 생성 단계 수 | 63 | 62 |
| 대상 이동 단위 | 63 | 62 |
| 후보 기록 수 | 725 | 768 |
| 신규 CAD 경로 요청 | 180 | 191 |
| 차단 근거 재사용 | 545 | 577 |
| BREP Common 호출 | 18538 | 19841 |
| 일반 부품 경로 통과 | 17 | 16 |
| 체결부 배치 | 41 | 41 |
| 사용자 간섭 예외 | 4 | 4 |
| 미해결 일반 부품 | 1 | 1 |

후보 기록은 방향·상태별 기록이며 차단 근거 재사용을 포함한다. 실제 신규 CAD 경로 요청과 같지 않다. 이전 v18은 v17 결과에 볼트 방향만 갱신한 결과여서, **순서 생성 비교 기준은 마지막 전체 탐색 실측인 v17**이다. 그룹 구성 및 실행 환경(EXE 배포본)이 달라 알고리즘 자체의 속도 개선율로 해석하면 안 된다.

이번 시험에서 시간은 4.7%, 후보 기록은 5.9%, 신규 CAD 요청은 6.1% 늘었다. 이번 변경을 속도 개선으로 주장하지 않는다.

초안 완성: **62/62단계**. 전체 경로 검증 완료: **아니오**. 미해결 일반 부품 1개는 경로 확인 필요 상태로 초안과 영상에 포함됐다. 모든 간섭을 통과한 결과가 아니다.

## 영상 생성과 이전 영상 정리

- 생성 초안: 62단계, 205.855초, 247.500초 영상, 7,425프레임, libx264/yuv420p.
- 순서·방향·카메라 편집 후 재확정: 62단계, 197.941초, 247.500초 영상, 7,425프레임, libx264/yuv420p.

- 두 영상 모두 전체 프레임 디코딩 수가 생성 프레임 수와 일치했다.
- 관리 폴더의 완료 영상 4개 중 최신 편집 영상 한 개를 남겼다.
- ‘최신 버전만 남기기’ 실제 버튼으로 이전 완료 영상 **3개**, **23,023,386 bytes (21.96 MiB)**를 삭제했다. 삭제 오류 0개.
- 삭제 대상은 v19 시험 복사본의 영상뿐이다. 삭제 파일은 이 복사본에서 복구할 수 없지만, 원래 v17 영상과 별도로 내보낸 첫 영상은 보존돼 있다.
- CAD·캐시·그룹 스냅샷·이전 확정본을 보존하고 최신 영상을 다시 열었다. 다른 프로젝트·실패/임시 파일·내보낸 복사본 보존과 반복 정리 무삭제 동작은 자동 시험으로도 확인했다.
- 유지 영상: `C:\Users\Win11Pro\Documents\15_ai_data\_Final_Project\ver1\PA2_ver1\runtime-data\end-to-end-v19-final\projects\7ff36dbc-4826-455d-9a14-2d99f2572641\videos\961c42f1-6142-41a0-961f-8985cde3d6bb-c0db0da9.mp4`
- 편집 전 별도 내보내기: `C:\Users\Win11Pro\Documents\15_ai_data\_Final_Project\ver1\PA2_ver1\runtime-data\native-validation\PA2_v19_before_edit_export.mp4`
- 전체 화면 흐름 측정: 1406.312초(프로그램 초기화 후부터, 최종 전체 디코딩 포함).

## 남은 경로 문제

### BLK-KD000 (group-6f966deb84-0001)

다른 부품을 모두 제거하고 기준 부품만 남긴 상태의 탐색 기록이다. 이후 백트래킹의 마지막 시도 상태와 구분했다.

- +Y: BLOCKED · OVERLAP_REINCREASE · 상대 MBD-KD000.
- −Y: BLOCKED · OVERLAP_REINCREASE · 상대 MBD-KD000.
- +Z: BLOCKED · OVERLAP_REINCREASE · 상대 MBD-KD000.
- −Z: BLOCKED · OVERLAP_REINCREASE · 상대 MBD-KD000.
- +X: BLOCKED · OVERLAP_REINCREASE, SWEEP_UNRESOLVED · 상대 MBD-KD000.
- −X: UNKNOWN · DECREASE_BOOLEAN_FAILED · 상대 MBD-KD000.
  이동 14.500 mm에서 교차 체적 계산이 실패해 감소 조건을 증명하지 못했다.

실제 이동 간섭 또는 계산 미판정은 그대로 보존했으며, 이를 지우거나 허용오차를 변경해 통과시키지 않았다. 세부 위치별 교차 체적·오류는 ui-v19-packaged-final.json의 planning.paths에 남겼다. 사용자가 초안을 검토·편집·확정하면 이 상태에서도 영상 생성은 가능하다.

## 시험·EXE·사내 ZIP

- 전체 자동 시험: 241 passed, 1 skipped, 10 warnings. 제외 1개는 PA2_TEST_STEP 미지정 조건부 외부 입력 시험이며 실제 제공 모델의 재열기·계산은 위 EXE 전체 시험에서 별도로 수행했다. 경고는 VTK/NumPy 사용 중단 예정 알림이다.
- 실제 배포본 빈 창 실행, 접촉·경로·초기 겹침·곡면·볼트 머리 방향 native smoke, 포함 FFmpeg의 320×180/30fps 1초 인코딩 및 30프레임 전체 디코딩 통과.
- 최종 편집·확정·영상 정리 후 배포 EXE로 다시 열어 63그룹/62단계·예외 프리셋·자재정보·빈 주의사항과 실제 3D 렌더 버퍼를 확인했다. QWidget 일반 캡처의 OpenGL 영역이 검게 보이는 한계를 구분해 gui-reopen-v19-final-scene.png로 실제 모델 버퍼를 별도 확인했다.
- EXE: `PA2.exe`, SHA-256 `2eba852cb4db155e76f46249afe47c78ce8778c20459608c3613d579739fb400`. 이전 EXE와 _internal은 build/previous-release-*에 보존했다.
- 패키지 모듈 35개 소스와 최적화 바이트코드, 자산·내장 아이콘 일치. 비호환 ICU DLL 미포함.
- ZIP: `releases/PA2_ver1_windows_x64_v19.zip`, 322,108,322 bytes, SHA-256 `5a9fd7dadee05327930dc9b05f25dcd1bdd81cd09d7cdae7ec925d34ed4aff51`.
- ZIP을 독립 재압축 해제해 payload 3,409개 크기·해시 일치를 검증했다. 현재 루트 EXE와 배포 EXE도 동일하다. 기존 v18 ZIP은 보존했다.
- 원래 v17 프로젝트 파일 387개 해시 보존 확인, 제공 원본·로고 24개 해시 일치.
- 별도 수신 PC·저사양 PC·설치형 Setup.exe·전자서명 검증은 이번에 수행하지 않았다. 라이선스 고지 파일은 수집했으나 전체 배포 라이선스 감사 완료를 뜻하지 않는다. 사내 검증·전달용 ZIP이다.
- 예외 부품만 제외한 부분 학습 데이터 저장은 이번 범위에 포함하지 않았다.

## 근거 파일

runtime-data/native-validation/ 아래:

- ui-v19-packaged-final.json, .progress.json, 화면 캡처 PNG들
- ui-v19-source-preflight.json, tests-v19-full.log, build-v19.log
- v19-comparison.json, v19-source-preservation.json
- packaged-source-check-v19.json, portable-package-v19.json
- portable-gui-smoke-v19.json, portable-native-smoke-v19.json, portable-encode-v19.log
- gui-reopen-v19-final.json, gui-reopen-v19-final-scene.png
- reference-integrity-v19-before.json, reference-integrity-v19-after.json

재열기: 프로젝트 루트의 open_validation_v19.bat.
