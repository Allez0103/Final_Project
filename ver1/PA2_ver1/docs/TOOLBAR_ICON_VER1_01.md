# 상단 아이콘 교체 — ver1_01

2026-10-20. 상단 툴바의 텍스트 PA²를 기존 프로그램 아이콘으로 교체했다. 흰색 PA·노란 위첨자 2가 있는 둥근 정사각형 아이콘을 그대로 재사용한다. 옆의 Pilot Assembly Assistant 이름, 창 제목, 작업 취소·설정과 기존 기능은 유지한다. 아이콘은 논리 크기 32×32이며 화면 배율에 맞는 ICO 해상도를 사용한다.

순서 생성, 간섭 기준, 영상, 프로젝트 저장 형식과 원본 CAD는 변경하지 않았다. 기존 아이콘 자산과 영상 템플릿도 수정하지 않았다. 이전 실행 파일은 빌드 스크립트의 build/previous-release-* 보관본에, 이전 ZIP은 releases 안에 보존한다.

## 검증

- 관련 테스트 6개 통과. 아이콘 원본과 표시 픽셀 일치, 툴바 순서·이름·접근성 이름·창 아이콘 유지 확인.
- 전체 회귀 테스트 246 passed, 1 skipped, 10 warnings. 마지막 실행 49.82초. 외부 STEP 통합 시험은 입력 환경 변수 미지정으로 건너뛰었고, 경고는 기존 VTK/NumPy deprecation이다.
- EXE 안의 36개 핵심 모듈이 현재 최적화 소스와 일치하며 아이콘·로고·영상 템플릿 자산 및 EXE 내장 아이콘도 일치한다.
- 루트 EXE의 실제 Qt 창 실행 통과: 탭 3개, 아이콘 32×32, 옆 제목 유지. gui-header-ver1_01-root.json 및 -header.png에 기록.
- 루트 EXE의 native smoke 통과: 접촉·경로, 초기 겹침 감소 정책, 곡면 경로, 볼트 머리 방향과 추가 경로 호출 0회 확인. native-ver1_01/smoke.json에 기록.
- ZIP을 독립 경로로 압축 해제하여 payload 2,478개 파일의 크기·SHA-256 일치, 루트 EXE와 배포 EXE 동일 확인.
- 압축 해제 EXE도 개발용 PYTHONPATH를 제거하고 PATH를 Windows 경로로 제한한 상태에서 실제 Qt 창 실행·아이콘 표시 통과. gui-header-ver1_01-packaged.json 및 -header.png에 기록하고 화면을 확인했다.

이번 변경은 상단 표시 변경이므로 전체 제공 모델의 장시간 순서 탐색·완편 영상 렌더링은 반복하지 않았다. 이전 기능 전체 흐름 시험은 END_TO_END_V19_RESULT.md와 SELECTION_ISOLATION_V19_1.md에 보존한다. 별도 PC 시험·전자서명은 수행하지 않았다.

## 산출물

- 실행 파일: 프로젝트 루트 PA2.exe. _internal 폴더와 함께 사용한다.
- ZIP: releases/PA2_ver1_01_windows_x64.zip, 318,347,483 bytes.
- ZIP SHA-256: `a4058b39d7c682af1b0f2d1d7354a6d257e95204140a349515e57cb1a2195b7e`.
- EXE SHA-256: `df8601f87ce7db3ab9b1704cb83417781610537ae8923b3067aeb66e4bd485bf`.
- 파일 무결성 기록: runtime-data/native-validation/portable-package-ver1_01.json.
- 빌드 기록: runtime-data/native-validation/build-ver1_01-retry.log.

개발용 Python 설치가 제거된 환경에서는 프로젝트 내부에 복원해 둔 CPython 3.13.14를 사용했다. 첫 빌드는 사용자 site-packages 접근 권한으로 중단되어 기존 실행 파일을 교체하지 않았다. 재시도는 PYTHONUSERBASE를 프로젝트 내부 build/python-user-base-ver1_01로 지정해 통과했다. 테스트 임시 폴더도 기존 권한 제한 폴더 대신 별도 build/tests-full-ver1_01-retry를 사용했다. 시스템 Python·권한·PATH 설정은 변경하지 않았으며 배포 사용자는 Python을 설치할 필요가 없다.
