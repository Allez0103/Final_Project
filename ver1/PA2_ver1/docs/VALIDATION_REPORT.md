# 2026-10-17 검증 보고

이 문서는 초기 구현 당시의 기록입니다. 접촉 계산 제한 제거 이후의 최신 검증은 [2026-10-18 수정 보고](NATIVE_FIX_REPORT.md)를 참조하십시오.

## 환경

- Windows x64, Python 3.13.14
- PySide6 Essentials 6.12.0
- OCP 8.0.1.1.0, VTK 9.6.2
- SQLAlchemy 2.0.55, LightGBM 4.7.0
- FFmpeg 7.1 (`imageio-ffmpeg` 번들)

## 자동 시험

- 결과: 34 passed, 1 skipped, 2 warnings (실제 STEP 선택 시험은 환경 변수 미설정 시 skip)
- 포함: 분류, 좌표, 계획 형식, 자산 불변, 캐시 원자성, 그룹 분할, BREP 얇은 장애물, 접촉 UNKNOWN, 지지, 탐색 역산, 시간축, 저장소, 학습 행, 오프스크린 MP4
- GUI headless 생성: 3개 화면 정상 생성/종료
- MP4 smoke: VTK 합성 box → 실제 H.264/yuv420p 파일 생성 성공
- PyInstaller directory bundle: 3,241개 파일, 약 886MiB
- 패키징된 `PA2.exe`: offscreen 환경에서 8초 이상 정상 기동 후 시험 종료

## 제공 CAD

### 작은 실제 STEP — BLT-WASM520A.STP

- atomic body: 3
- contact edge: 2
- 최초 import: 약 0.16초
- 동일 파일 새 프로젝트: BREP cache hit, 약 0.11초
- 보수 탐색(지지 검사 해제): 14 후보, UNKNOWN 9, BLOCKED 5, 5.51초, `PARTIAL`
- 초기 접촉을 관통/경계 접촉으로 분리 증명하지 못해 COMPLETE로 올리지 않음

### 대표 실제 입력 — 완제품 + 부품 18개

- 완제품 크기: 49,446,616 bytes
- 완제품 atomic body: 176
- 개별 부품 정의: 18, 각 1~17 솔리드
- assembly group: 65
- 확정 대응 그룹이 소유한 body: 165
- 미대응 body: 11
- 중복 소유/누락: 없음
- 19개 형상 캐시 복원 후 그룹화/안전 진단: 약 2.25초
- 접촉 broad phase 후보: 243쌍
- 접촉 정밀 그래프: 미완료. 네이티브 호출 시간 제한을 현재 UI 작업에서 안전하게 강제할 수 없어 243쌍을 UNKNOWN으로 저장하고 `calculation_ready=false` 처리

이 상태에서는 실제 완제품의 순서 생성·확정·대표 영상 생성을 시작하지 않습니다. 검사기를 약하게 하거나 접촉 edge를 없는 것으로 취급하지 않았습니다.

## 참고 영상/로고

- 참고 영상: 1920×1080, 30fps, H.264 High, yuv420p, 125.87초
- 템플릿은 명세 정규화 좌표를 사용하고 우측 상단 로고·우측 정보 패널·하단 과정 문구를 구현
- 로고는 원본 SHA-256 확인 뒤 좌측 상단 THN lockup을 `(64,0,330,76)`로 무보간 crop; 원색/alpha 유지
- PPT는 열거나 공정 규칙/라벨로 사용하지 않음

## 원본 보존

`tools/verify_reference_integrity.py` 결과: 24 checked, `ok=true`. 제공 폴더와 Downloads 로고 원본은 수정하지 않았습니다.

## 배포 잔여 검증

- Inno Setup 설치 프로그램 생성 및 개발 도구가 없는 별도 Windows 10/11 PC의 설치·실행 시험은 미수행
- MariaDB 서버 런타임은 번들에 포함하지 않음. 현재 개발 실행은 SQLite fallback, 운영 연결은 `PA2_DATABASE_URL`로 지원

