# PA² GUI 수정용 개발 소스 안내

- 기준: 현재 PA² ver1_01 소스, 2026-10-22
- 전달 파일: `PA2_ver1_01_gui_source.zip`
- 대상: 프로그램 화면을 수정할 팀원
- 실행 환경: Windows x64 / 일반 CPython 3.13 x64

## 1. 전달 범위

ZIP에는 `src/pa2` 전체 Python 소스, 아이콘·로고·영상 템플릿, 설정·데이터 스키마, 의존성 목록, 테스트와 빌드 관련 파일을 담았다. GUI가 CAD·저장·계획·영상 모듈을 import하므로 UI 파일만 떼지 않고 실행에 필요한 소스를 함께 제공한다.

기존 EXE, `_internal`, `.venv`, 빌드 산출물, 사용자 DB, CAD 원본·관리 사본, BREP 캐시, 생성 영상, 개발 로그, Git 이력은 포함하지 않는다. 필요한 시험용 CAD·프로젝트 데이터는 별도로 협의해 전달한다.

이 묶음은 일반 사용자를 위한 실행 파일 ZIP과 다르다. **개발자가 Python과 의존 라이브러리를 설치해야 소스를 수정·실행할 수 있다.**

## 2. 우선 볼 GUI 파일

| 파일 | 담당 기능 |
|---|---|
| `src/pa2/ui/main_window.py` | 메인 창, 프로젝트 탭, 서비스·작업 연결, 기존 모델 화면 기반 |
| `src/pa2/ui/model_editor.py` | 가로 순서 카드, 작업 속성, 선택·묶음 이동, 미리보기 |
| `src/pa2/ui/group_dialog.py` | 수동 그룹화 대화상자 |
| `src/pa2/ui/video_page.py` | 영상 생성 버튼·진행도·재생·배속·전체화면 |
| `src/pa2/ui/settings_dialog.py` | 설정 창 |
| `src/pa2/ui/theme.py` | Qt 스타일시트 |
| `src/pa2/rendering/vtk_scene.py` | 3D Actor, 선택 강조, 카메라, 썸네일 |
| `src/pa2/rendering/scene.py` | 미리보기·영상이 공유하는 시간축·위치·카메라 계산 |
| `assets/` | 프로그램 아이콘, 로고, 영상 템플릿 |

현재 모델 화면은 `main_window.py`의 기반 클래스를 `model_editor.py`에서 확장하는 구조다. 한쪽 파일만 보면 실제 사용 화면과 다르게 판단할 수 있으므로 연결을 함께 확인한다.

## 3. 개발 환경 설치

일반 Python 3.13 x64를 설치한 뒤 ZIP을 전부 압축 해제한다. 아래 명령은 **압축을 푼 `PA2_ver1_gui_source` 폴더 안**에서 PowerShell로 실행한다. 최초 의존성 설치에는 인터넷 또는 사내 패키지 저장소가 필요하다.

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip "setuptools>=84" wheel
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
.\.venv\Scripts\python.exe -m pip install --no-deps --no-build-isolation -e .
```

`py -3.13`을 찾지 못하면 설치된 Python 3.13의 `python.exe` 절대 경로로 첫 명령을 실행한다. ZIP에는 기존 개발 PC의 가상환경이나 Python 런타임을 넣지 않았다.

## 4. 소스 실행

```powershell
$env:PA2_DATA_ROOT = Join-Path (Get-Location) "runtime-data\gui-dev"
$env:PYTHONPATH = Join-Path (Get-Location) "src"
.\.venv\Scripts\python.exe -m pa2
```

`PA2_DATA_ROOT`를 지정하면 프로젝트 DB·CAD 자산·캐시는 개발 폴더 아래에 생성된다. `PA2_DATABASE_URL`이 별도로 설정된 PC에서는 해당 DB 연결 설정이 우선하므로, 팀의 개발용 연결 설정을 확인한다. 사용자 설정 JSON은 별도의 기본 사용자 설정 경로를 사용한다.

**소스 수정 확인에는 위 Python 명령을 사용한다.** 기존 `run_pa2.bat`은 같은 폴더에 `PA2.exe`가 있으면 EXE를 먼저 실행하므로, EXE를 복사해 넣은 뒤 이 BAT로 실행하면 수정한 소스가 반영되지 않을 수 있다.

## 5. 변경 후 확인

```powershell
$env:PYTHONPATH = Join-Path (Get-Location) "src"
$env:PA2_DATA_ROOT = Join-Path (Get-Location) "runtime-data\gui-tests"
.\.venv\Scripts\python.exe -m pytest
```

일반 창 열기·프로젝트 생성·모델 표시·카드 선택·속성 적용·미리보기를 실제 화면에서도 확인한다. 외부 CAD를 쓰는 통합 시험은 별도 입력이 없으면 건너뛸 수 있다. 원본 CAD와 기존 사용자 데이터는 전달하지 않았으므로 새 PC에서는 빈 프로젝트 목록으로 시작한다.

UI 변경 시 기존의 다음 처리 연결을 유지한다.

- 계산 결과를 UI 스레드에서 반영하는 Qt Signal/Slot 연결.
- 카드·부품·계획을 그룹 ID로 연결하는 규칙.
- 방향·순서 편집 중 CAD 간섭 재검사를 수행하지 않는 정책.
- 수정 내용 적용·순서 확정과 영상 생성 사이의 연결.

## 6. EXE 재빌드

GUI 수정 결과를 EXE로 다시 배포하려면 먼저 테스트와 소스 실행을 확인한다.

```powershell
PowerShell -ExecutionPolicy Bypass -File .\scripts\build.ps1
```

빌드 스크립트는 테스트 후 PyInstaller로 패키징하며, 이 개발 폴더의 루트에 `PA2.exe`와 `_internal`을 배치한다. 이전 산출물이 있으면 `build/previous-release-*`에 보존한다. 변경한 소스가 기존 사용자용 ZIP에 자동 반영되지는 않는다. EXE 검증 후 배포 ZIP을 별도로 갱신한다.

## 7. 현재 소스와 미반영 요구사항

이 소스는 현재 배포본과 같은 ver1_01 기준이다. 최근 논의한 아래 요구는 아직 적용하지 않았다.

- STEP 부품당 대표 색상 적용.
- 인터페이스의 빨간 선택 강조와 단일 선택 시 비선택 부품 회색·반투명 표시.
- 영상의 빨간 점멸·이동 강조.
- 초안 저장 버튼 제거, 최초 원본 초안 보존 기준 정리.
- 초안·확정본 유사도 계산 및 학습 데이터 수집 고도화.
- 자동생성 옆 수동생성 버튼과 계산을 최소화한 초기 순서 구성.

세부 UI 변경 범위는 프로젝트 담당자와 맞춘다. 머신러닝 방향 추천은 검토 단계이며 현재 기본 동작은 규칙·기하 기반이다.

## 8. 팀원에게 전달하는 방법

`PA2_ver1_01_gui_source.zip` 하나를 사내 메신저·공유 폴더 등으로 전달하면 된다. 이 문서도 ZIP의 `README.md`로 들어 있다. 화면을 수정한 뒤에는 변경한 파일 목록과 수정 내용을 함께 돌려받거나, 사내 비공개 Git 저장소에서 브랜치로 관리할 수 있다.

ZIP의 `SOURCE_MANIFEST.json`에는 원본 파일별 SHA-256을 넣었다. 기존 소스를 기준으로 어떤 파일이 수정됐는지 비교할 때 사용할 수 있다.
