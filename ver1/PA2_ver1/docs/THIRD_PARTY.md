# 의존성 및 배포 확인 메모

고정 버전은 `requirements-lock.txt`에 있습니다. 배포 전 각 패키지와 포함 바이너리의 라이선스 원문/고지를 수집해 설치물에 포함해야 합니다.

- PySide6 Essentials / Shiboken6 — LGPL/GPL/commercial 조건 확인
- VTK — BSD-3-Clause
- Open CASCADE Technology via cadquery-ocp — LGPL-2.1 with exception
- SQLAlchemy, Alembic, PyMySQL — 각 프로젝트 라이선스
- LightGBM, scikit-learn, NumPy, SciPy — 각 프로젝트 라이선스
- Pillow — HPND
- FFmpeg — 실제 포함 빌드의 configure flags에 따른 LGPL/GPL 여부 확인 필수
- PyInstaller — GPL with bootloader exception
- MariaDB — 서버/connector 배포 조건 및 고지 확인 필요

`imageio-ffmpeg`가 제공하는 실제 FFmpeg 바이너리의 codec/configuration을 릴리스 빌드마다 다시 기록해야 합니다. 하드웨어 encoder는 작은 실제 인코딩을 통과한 경우에만 활성화하며 현재 구현은 소프트웨어 `libx264`를 사용합니다.

