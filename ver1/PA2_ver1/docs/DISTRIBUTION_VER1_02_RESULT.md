# PA² ver1_02 사내 배포 ZIP

2026-10-22, v26 탑뷰 자동 가로 정렬까지 반영한 실행 파일 기준.

- 파일: `C:\Users\Win11Pro\Documents\15_ai_data\_Final_Project\ver1\PA2_ver1\releases\PA2_ver1_02_windows_x64.zip`
- 크기: 318,556,951 bytes (303.8 MiB)
- ZIP SHA-256: `45d3336aefb4aa424317972803d6fb654b03ebb34bf94e2ba3ae561f3f0df247`
- EXE SHA-256: `ec2000a27365c6bdc19c2d1a4f6968083155febcc9d4ae3423e8692d9b18332f`
- 루트 폴더: PA2_ver1. PA2.exe, _internal, 사용안내, 라이브러리 고지, 파일별 체크섬 및 배포 명세 포함.
- 자체 개발 소스·가상환경·CAD·프로젝트 DB·시험 영상은 제외. 실행에 필요한 제3자 라이브러리 파일은 포함.
- 압축 생성 후 독립 폴더에 해제하고 2,478개 파일의 크기/SHA-256 일치 확인.
- 압축 해제본에서 Python 경로 제거/Windows PATH만으로 GUI 및 격리 CAD/순서 smoke 시험: True.
- 포함된 FFmpeg로 CPU 인코딩 및 전체 디코딩: 30/30프레임. 추적 소스 61개·자산·아이콘 일치: True.
- 종합 검증: True. 별도 수신 PC 시험은 아님. 모델 학습/평가/승격은 실행하지 않음.
- 기존 ZIP은 그대로 보존했고 새 버전명으로 생성함. 프로그램 기능 코드는 변경하지 않았고 사용안내만 최신화함.
- 최종 실행 파일의 62단계 조립 영상 생성/재생/탑뷰 정렬 검증은 `docs/UI_V26_TOP_LANDSCAPE_RESULT.md`에 기록되어 있음. 압축 해제본 EXE는 그 파일과 바이트 동일.

## 전달 및 실행

ZIP 전체를 전달하고, 받는 PC에서 전부 압축 해제한 후 PA2_ver1/PA2.exe를 실행한다. Python 별도 설치는 필요 없다. EXE만 따로 복사하지 말고 _internal을 같은 위치에 유지한다. 직원별 작업 데이터는 기본적으로 해당 직원의 LOCALAPPDATA/THN/PA2에 저장한다.

이 패키지는 사내 전달용이며 전자서명은 없다. 라이브러리 고지를 포함했으나 외부 공개/납품을 위한 라이선스 검토 완료나 배포 인증을 뜻하지 않는다. 자세한 고지는 압축 내 THIRD_PARTY_NOTICES에 있다.

근거: `runtime-data/native-validation/portable-package-ver1_02.json`, `portable-runtime-ver1_02.json`, `build/ver1_02-unpacked-source-check.json`.
