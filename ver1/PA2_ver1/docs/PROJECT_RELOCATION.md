# 프로젝트 경로 정리

- 기존 프로젝트 루트: `C:\Users\Win11Pro\Documents\15_ai_data\_Final_Project\ver1`
- 새 프로젝트 루트: `C:\Users\Win11Pro\Documents\15_ai_data\_Final_Project\ver1\PA2_ver1`
- 기본 실행 파일: 새 프로젝트 루트의 `PA2.exe`
- 의존 파일: 같은 위치의 `_internal`

기존 ver1의 최상위 항목 68개를 모두 새 프로젝트 안으로 이동했다. 소스, 개발 가상환경, 문서, 기존 시험 캐시, 프로젝트 데이터, 영상, 예전 dist 배포본도 보존했다. 현재 배포본의 PA2/PA2.exe와 PA2/_internal은 새 프로젝트 루트로 배치했다. 비어 있는 이전 PA2 폴더는 build/previous-empty-release-folder로 옮겼다. 파일 삭제는 하지 않았다. ver1 바로 아래에는 PA2_ver1만 남는다.

실행·검증 배치 파일, 패키지 확인 도구, 설치 프로그램 입력, README의 현재 경로를 수정했다. 빌드는 build/distribution에서 완료한 뒤 루트에 EXE와 의존 파일을 배치하도록 변경했다. 가상환경의 editable 소스 참조를 상대 경로로 바꾸고 빌드는 python -m PyInstaller로 호출해 이전 위치에 고정된 런처를 사용하지 않도록 했다.

기존 실행 당시의 절대 경로가 들어 있는 과거 로그·보고서는 원 기록으로 보존했다. 앞으로 도구를 실행하면 새 위치를 기준으로 기록한다. 바탕화면의 제공 원본 폴더와 프로젝트 밖 원래 명세는 이동하거나 수정하지 않았다.

## 이동 후 확인

- EXE SHA-256은 이동 전후 동일: `3f1602b93cd7e0c40bc4dfd3cb7731a19d2aa584a4b9679e99f601c0e2c4caa4`.
- 이동된 .venv Python이 새 위치의 src/pa2를 불러오는 것과 PyInstaller 모듈 접근을 확인했다.
- 실행 파일의 코드·자산·아이콘이 현재 소스와 일치했다: runtime-data/native-validation/packaged-source-check-relocated.json.
- 실제 PA2.exe 창 실행·기존 프로젝트 재열기 통과: gui-smoke-relocated.json. 그룹 64개, 단계 63개, 예외 4개 및 실제 3D 렌더링 확인.
- 관련 회귀시험 27개 통과: tests-relocated.log.
- PowerShell 빌드 스크립트 구문과 모든 검증 배치 파일의 새 EXE 대상 존재를 확인했다. 위치 이동만으로 EXE 내용이 바뀌지 않으므로 이번에는 전체 재빌드를 다시 수행하지 않았다.
