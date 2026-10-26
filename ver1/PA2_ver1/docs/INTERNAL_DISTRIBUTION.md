# 사내 전달용 ZIP

대상은 사내 사용자다. 기본 전달 파일은 releases/PA2_ver1_01_windows_x64.zip이며 전체 개발 프로젝트 폴더를 전달할 필요는 없다. ZIP을 모두 푼 뒤 PA2_ver1/PA2.exe를 실행한다. Python 설치 없이 사용하도록 묶은 Windows x64 패키지다. 최신 ver1_01의 상단 아이콘 변경은 [검증 기록](TOOLBAR_ICON_VER1_01.md)을 참조한다. v19.1의 부품 목록 다중선택 시 선택 부품만 표시하는 기능도 유지한다.

## 포함·제외

PA2.exe, _internal, 사용안내.txt, THIRD_PARTY_NOTICES, release-manifest.json, SHA256SUMS.txt를 포함한다. 개발 소스 src, 개발용 .venv, tests, 기존 runtime-data의 사용자 CAD·프로젝트·영상은 넣지 않는다. 필요한 라이브러리의 Python 파일과 실행 코드·자산은 _internal 안에 포함된다.

받는 직원의 작업 데이터는 기본적으로 그 계정의 %LOCALAPPDATA%/THN/PA2에 저장한다. 배포 담당자의 시험 프로젝트를 받는 직원 계정으로 복제하지 않는다. PA2_DATA_ROOT 또는 PA2_DATABASE_URL 환경 변수를 별도로 지정한 PC는 해당 설정이 우선한다.

## 전달 방법

1. ZIP과 같은 이름의 .zip.sha256 파일을 함께 전달한다.
2. 받는 직원은 ZIP 전체를 로컬의 쓸 수 있는 폴더에 압축 해제한다.
3. PA2_ver1 폴더 안의 PA2.exe를 실행한다. _internal을 분리하지 않는다.
4. 수신 PC에서 빈 프로젝트 화면, 자체 STEP 입력, 순서 편집, 짧은 영상 생성까지 확인한다.

현재 설치형 Setup.exe는 만들지 않았다. Inno Setup 컴파일러가 이 빌드 환경에 확인되지 않아 ZIP 형식으로 준비했다. 현재 EXE는 전자서명되지 않았다.

## 패키지 생성·검증

프로젝트 루트에서 .venv/Scripts/python.exe tools/package_portable.py를 실행한다. 이미 같은 이름의 ZIP이 있으면 덮어쓰지 않는다. 새 산출물 이름은 --output으로 지정할 수 있다.

현재 실행 파일과 _internal만 별도 staging 폴더로 복사하고, 사용 안내와 확보된 라이선스 고지 파일을 추가한다. 각 파일 SHA-256을 기록한 뒤 ZIP을 만든다. 별도 경로로 다시 압축 해제하고 모든 payload 파일의 크기·해시를 검사한다. ZIP 자체의 SHA-256도 별도 파일에 기록한다.

생성 기록: runtime-data/native-validation/portable-package-ver1_01.json 및 .log. 실행 점검은 압축을 푼 패키지의 EXE를 사용하며, PYTHONPATH와 개발 경로가 있는 PATH를 제외하고 PA2_DATA_ROOT를 지정한다. 이는 현재 PC에서 개발 경로 의존성을 줄여 수행한 시험이며 별도 Windows PC 검증을 대신하지 않는다. v19의 실제 전체 흐름 결과는 [검증 보고서](END_TO_END_V19_RESULT.md)에 보존하고, 최신 상단 아이콘 검증은 TOOLBAR_ICON_VER1_01.md에 기록한다.

## 현재 ver1_01 패키지

- 파일명: PA2_ver1_01_windows_x64.zip, 318,347,483 bytes.
- ZIP SHA-256 `a4058b39d7c682af1b0f2d1d7354a6d257e95204140a349515e57cb1a2195b7e`.
- 루트 및 ZIP EXE SHA-256 `df8601f87ce7db3ab9b1704cb83417781610537ae8923b3067aeb66e4bd485bf`.
- 독립 압축 해제본 payload 2,478개 파일 크기·해시 일치. 상단 PA² 글자를 기존 프로그램 아이콘으로 교체하고 프로그램명 및 기존 기능은 유지한다.
- 개발 환경 변경에 따라 내부 런타임 파일 수는 이전 묶음과 다르다. 소스 일치·실행 및 CAD 기본 시험은 TOOLBAR_ICON_VER1_01.md에 기록한다.

## 이전 v19.1 패키지(보존 기록)

- ZIP 322,112,724 bytes, SHA-256 `a020523f1671dd3043e7a146d95dc29398dbd0d692b168c7247bceff09fe9742`.
- 루트 및 ZIP EXE SHA-256 `2e59343dd2cd42b3e3cf51d0dfdd3960efad2b1aa92a71954077d41bb0373b81`.
- 독립 압축 해제본 3,409개 파일의 크기·해시 일치. 부품 목록 다중선택 시 선택 부품만 표시하는 기능을 포함한다.
- 기존 v18·v19 ZIP과 이전 실행 파일 보관본은 보존한다. 이전 전체 순서·영상 생성 실측은 아래 기록이며, 이번 표시 기능 수정에서 긴 CAD 탐색과 영상 렌더링은 반복하지 않았다.

## 이전 v19 전체 흐름 검증 결과(보존 기록)

- ZIP 322,108,322 bytes, SHA-256 `5a9fd7dadee05327930dc9b05f25dcd1bdd81cd09d7cdae7ec925d34ed4aff51`.
- 독립 압축 해제본 3,409개 payload 파일 크기·해시 일치. 루트 EXE와 배포 EXE 동일.
- 개발 경로를 제거한 압축 해제 EXE에서 빈 창·native CAD·포함 FFmpeg 시험과 실제 프로젝트 전체 흐름 통과.
- 기존 프로젝트 열기 → 수동 그룹화·해제·재열기 → 62단계 초안 → 편집·확정 → 영상 2회 생성 → 최신 영상만 유지까지 확인했다. BLK-KD000 경로 미판정 1개는 검토 대상으로 보존했다.
- 두 영상 각 7,425프레임 전체 디코딩 통과. 시험 복사본의 이전 영상 3개 삭제, 원래 프로젝트·제공 원본과 별도 내보내기 영상 보존.
- 최종 재열기에서도 63그룹·62단계·4개 예외 프리셋 및 실제 3D 렌더링 확인.
- 상세 결과와 한계는 END_TO_END_V19_RESULT.md 참조. 별도 수신 PC 및 저사양 PC 시험은 수행하지 않았다.

## 이전 v18 생성 결과(보존 기록)

- ZIP 크기 322,068,208 bytes, SHA-256 `9ff2b76844e4648eb32ad9fdfd5898fafb9c8524c037f547ba16aae4ed593adc`.
- 독립적으로 다시 압축 해제한 payload 3,409개 파일의 크기·SHA-256 일치. 현재 소스 EXE와 배포 EXE의 해시도 일치.
- 실제 압축 해제본 EXE의 새 데이터 영역 창 실행 통과: portable-gui-smoke-v18.json. 예외 프리셋 0개로 시작했다.
- 실제 압축 해제본 EXE의 CAD 계산·초기 겹침·곡면 경로·볼트 머리 방향 계산 통과: portable-native-smoke-v18.json.
- 포함 FFmpeg의 libx264 320×180/30fps 1초 인코딩 및 전체 30프레임 디코딩 통과: portable-encode-v18.log.
- 위 실행은 개발용 PYTHONPATH를 없애고 PATH를 Windows/System32 및 Windows로 제한한 상태에서 수행했다.
- 별도 수신 PC 검증, 설치형 Setup.exe, 전자서명 및 전체 라이선스 감사는 이번 검증에 포함하지 않았다.

## 라이브러리 고지의 범위

설치된 wheel 및 실제 runtime에서 확보된 라이선스 원문은 변경 없이 모았다. dependency-inventory.json은 빌드 환경의 패키지 목록으로, 개발 전용 의존성을 포함할 수 있으며 실행 바이너리 전체의 라이선스 감사 결과는 아니다.

현재 포함 FFmpeg 7.1-essentials_build-www.gyan.dev는 실행 출력에서 --enable-gpl, --enable-version3 및 GPL 3 이상을 보고한다. 실제 구성과 -L 출력은 THIRD_PARTY_NOTICES/FFmpeg-build-and-license.txt에 보존했다. 상응 소스의 제공 방식, 모든 라이브러리의 고지·배포 조건 검토는 이 작업으로 완료했다고 주장하지 않는다. 외부 공개·납품용 패키지는 별도로 검토해야 한다.

공식 참고: https://ffmpeg.org/legal.html 및 https://doc.qt.io/qtforpython-6/licenses.html.
