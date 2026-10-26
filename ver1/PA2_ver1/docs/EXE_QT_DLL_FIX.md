# EXE QtWidgets 시작 오류 수정

사용자 화면의 `DLL load failed while importing QtWidgets: 지정된 프로시저를 찾을 수 없습니다` 오류를 배포 DLL의 실제 import/export와 비교했다.

기존 배포의 `_internal/icuuc.dll`은 Windows 시스템 DLL이 아니라 개발 환경 PATH에 있던 Poppler의 ICU 78 DLL이었다. 기존 `build/pa2/Analysis-00.toc`에서 원본 경로가 `.../dependencies/native/poppler/Library/bin/icuuc.dll`로 확인됐다. Qt6Core는 `ucnv_open`, `ucnv_close` 등 Windows ICU API의 비접미사 함수를 요구하지만 해당 DLL에는 대응 export가 없었다. 파일명은 같아도 교체 가능한 DLL이 아니었다.

패키징에서 이 `icuuc.dll`과 `icuin.dll`을 제외하고, 런타임 훅에서 System32의 ICU와 패키지 PySide6의 Qt6Core/Gui/Widgets를 명시적으로 불러오도록 했다. Qt가 제공하는 VC 런타임도 배포 루트에 한 버전으로 맞췄다. 외부 설치 파일이나 시스템 DLL은 변경하지 않았다.

일반 GUI 시작 경로를 사용하는 `--gui-smoke`에서 실제 창 표시, 이벤트 루프, 3개 탭과 예외 설정 컨트롤 생성, 창 이미지 저장 후 정상 종료를 확인한다. 별도의 `--native-smoke`에서 패키지의 격리 CAD 프로세스, 접촉·경로·초기 겹침 감소·곡면 검사 및 로고 자산을 확인한다. 최종 실행 결과와 이미지 파일은 `runtime-data/native-validation/gui-smoke-v13-final.*`, `native-smoke-v13-final.json`에 남긴다. 실제 프로젝트 재열기 검증은 별도 결과 파일에 남긴다.
