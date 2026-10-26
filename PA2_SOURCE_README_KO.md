# PA² 최신 소스 전달 안내 — ver1_04

2026-10-26 기준 최신 프로그램의 소스 전용 사본이다. 원격 저장소의 기존 README와 로컬 원본은 수정하지 않았다. 이번 업로드는 프로그램 기능 수정이나 배포본 갱신이 아니다.

## 위치와 포함 범위

- `ver1/PA2_ver1/src`: PA² 프로그램 전체 Python 소스(93개 모듈).
- `ver1/PA2_ver1/tests`: 최신 테스트 코드(46개 Python 파일, conftest 포함).
- `ver1/PA2_ver1/packaging`, `scripts`, `migrations`, `schemas`: 빌드·개발 환경·DB 스키마 설정.
- `ver1/PA2_ver1/assets`: 아이콘, 로고, 영상 템플릿만 포함.
- `ver1/PA2_ver1/docs`, `Documents`: 구현 문서, 상세 기술 명세, 기술 설명과 ERD.
- 실행 스크립트, 의존성 잠금 파일, 프로젝트 설정과 원래 README도 그대로 포함한다.

CAD/STEP/BREP, 프로젝트 DB, 실제 실행 로그, 영상, 학습·평가 데이터, 배포 ZIP/EXE, 가상환경, 빌드 결과·백업은 포함하지 않는다. 문서 속 과거 실측 표·예제 파일명·로컬 경로는 기술 설명이며 그 데이터나 파일 자체를 업로드한 것이 아니다. 기존 문서의 로컬 절대 링크나 이전 배포 안내는 이 소스 전용 저장소에서 열리지 않을 수 있다.

## 학습 모델 번들 제외

`assets/pilot`에는 학습·평가 라벨, 장면 형상, 학습된 모델과 이를 연결하는 manifest가 함께 들어 있다. 데이터 제외 요청에 맞춰 이 번들 전체를 제외했다. 따라서 이 사본에는 초기 적용용 학습 모델도 없다.

학습·추론·자동 재학습·모델 관리 기능 코드는 변경 없이 보존했다. 새 개발 환경에서 별도 번들을 공급하지 않으면 앱은 초기 동봉 모델 없이 기존 규칙으로 실행한다. 기존 사용자 데이터 저장소의 활성 모델이나 프로젝트를 삭제하거나 초기화하지 않는다. 학습 모델이 포함된 사내 배포본과 이 저장소의 초기 실행 상태를 동일하게 해석하지 말아야 한다.

제외한 번들의 라벨/형상/모델을 임의로 다시 커밋하지 않는다. `.gitignore`에도 제외 규칙을 넣었다.

## 개발 실행

Windows x64 및 Python 3.13 x64가 필요하다. 소스 전용이므로 배포 ZIP과 달리 Python 개발 환경을 구성해야 한다.

```powershell
cd ver1/PA2_ver1
PowerShell -ExecutionPolicy Bypass -File .\scripts\setup.ps1
.\run_pa2.bat
```

설정은 `pyproject.toml`, 의존성 잠금은 `requirements-lock.txt`에 있다. 실행 시 별도 프로젝트에 필요한 STEP은 사용자가 로컬에서 선택한다. 기존 사용자 프로젝트와 완전히 분리하려면 실행 전에 `PA2_DATA_ROOT`를 새 로컬 폴더로 지정한다.

## 테스트와 빌드

테스트 소스는 원본과 동일하다. 제외한 외부 자료에 의존하는 테스트는 자료 없이 통과하는 것으로 위장하지 않았다.

```powershell
cd ver1/PA2_ver1
$env:PA2_DATA_ROOT = Join-Path (Get-Location) 'runtime-data\github-tests'
$env:PA2_INSTALL_ROOT = (Get-Location).Path
.\.venv\Scripts\python.exe -X utf8 -B -m pytest --deselect=tests/test_v28.py::test_bootstrap_is_once_only_common_models_and_rollback --deselect=tests/test_v28.py::test_fixed_eval_never_in_fit_and_ties_preserved --deselect=tests/test_v28.py::test_automatic_promotion_gate_and_exact_pair_rollback
```

위 세 테스트는 제외한 초기 모델/학습·평가 번들이 필요하다. 외부 STEP 통합 테스트도 별도 입력이 없으면 건너뛴다. 테스트 중 생성한 임시 DB·로그·형상·영상은 저장소 추적 대상이 아니다.

실행 파일 빌드는 기존 `scripts/build.ps1`, `packaging/pa2.spec`, `packaging/uninst.spec`을 사용한다. 번들을 추가 공급하지 않은 빌드는 초기 학습 모델을 동봉하지 않는다. 빌드 결과나 배포 ZIP은 이 저장소에 올리지 않는다.

## 현재 변경되지 않은 사항

간섭 판정, 추천·영상 기능과 기존 모델 경로 처리 코드는 이번 업로드에서 수정하지 않았다. 기준부품 단독 6축 검사 후 자동 예외를 적용하는 중단된 실험은 포함하지 않았다. 한글 설치 경로에서 보고된 배포본의 초기 모델 열기 오류 역시 해결 완료로 표시하지 않는다.

이 저장소에 포함된 과거 문서의 검증 결과를 이번 업로드에서 대형 CAD·영상·학습 시험을 새로 완료했다는 뜻으로 해석하지 않는다. 제공 원본과 사내 데이터의 별도 공개 권한을 부여하는 문서도 아니다.
