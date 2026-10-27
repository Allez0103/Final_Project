# PA² — ver1_06 전체 소스

현재 저장소는 요청에 따라 이전의 펼쳐진 파일 구성을 **최신 전체 소스 ZIP**으로 교체했습니다. 이전 내용은 Git 커밋 이력에 남아 있습니다.

- [전체 소스 ZIP 다운로드](PA2_ver1_06_full_source.zip?raw=true)
- [SHA256](PA2_ver1_06_full_source.zip.sha256)
- [포장 검증 결과](PA2_ver1_06_full_source.zip.report.json)

ZIP을 풀고 `PA2_ver1_06_source/SOURCE_README_KO.txt`부터 확인하세요. Windows x64 개발용이며 Python 3.13 x64 및 `requirements-lock.txt` 의존성이 필요합니다. 이 ZIP은 Python 없이 실행하는 EXE 배포본이 아닙니다.

## 포함 범위

전체 Python 소스, 테스트, 빌드 설정, 스키마, 문서, 필수 이미지/템플릿, 승인된 순서·방향 모델과 고정 학습/평가 참조 자산을 포함합니다. 실제 사용자 CAD/STEP, 프로젝트 DB, 로그, 영상, 가상환경, EXE와 빌드 결과는 포함하지 않습니다. 모델 및 고정 BREP·JSON 자산을 포함하므로 사내 개발 전달용이며 외부 공개 권한을 뜻하지 않습니다.

이번 변경: 작업 속성 2탭, 미리보기 & 적용 통합, 좌/우 드래그 전환, 프로젝트별 사용자 지정 시점, 생성 전·후 부품 표시명 편집. 기존 알고리즘과 간섭 판정 기준은 유지합니다. 세부 사항은 ZIP 내부 `docs/RELEASE_VER1_06.md`, `docs/V32_EDITOR_CUSTOM_CAMERA.md`를 참고하세요.

## 무결성 및 검증

- ZIP SHA256: `a61c18e48f7519a32d3a9fb406b2e617c45cc838f02b9d774d1bce6a121015ee`
- 크기: 4,586,550 bytes / 2,034 files / 애플리케이션 97개 모듈.
- 소스 ZIP 압축 해제 후 회귀검사: 498개 통과, 2개 건너뜀, 실패 0개.
- 대응 실행 파일: 실제 Windows UI·저장·영상 확인 33개 항목 통과.

ZIP 내부 `SOURCE_MANIFEST.json`에 파일별 해시와 대응 실행 파일/배포 ZIP 해시가 있습니다. 개발·시험 시 업무 데이터와 분리된 `PA2_DATA_ROOT`, `PA2_INSTALL_ROOT`를 지정하세요. 알려진 한글 설치 경로 LightGBM 문제 등은 ZIP 내부 안내를 확인하세요.
