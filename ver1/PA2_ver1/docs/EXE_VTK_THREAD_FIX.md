# 실제 프로젝트 GUI 재열기 종료 오류

v14 EXE의 빈 창 실행은 통과했지만 실제 65그룹 프로젝트를 다시 열 때 접근 위반으로 종료되는 별도 문제를 발견했다. 원본 STEP이나 간섭 허용값 문제는 아니다.

`TaskWorker.finished`에 연결한 일반 Python 완료 함수는 QObject 수신 스레드가 없어 작업 스레드에서 실행됐다. 재열기 완료 함수가 그 상태에서 `ModelPage.set_result()`를 호출하여 VTK/OpenGL 장면을 만들고, 이후 UI 스레드의 `QVTKRenderWindowInteractor.paintEvent()`가 같은 창을 그리면서 충돌했다.

수정 전 재현:

- `gui-reopen-before-thread-fix.thread.json`: `ui_update_on_main_thread=false`.
- `gui-reopen-before-thread-fix.fault.log`: Windows 접근 위반, VTK Qt 위젯의 `paintEvent` 스택.
- 위 파일은 `runtime-data/native-validation`에 보존한다.

완료·진행·실패·취소 신호를 MainWindow의 명시적 Qt 슬롯에 QueuedConnection으로 연결했다. 완료 함수 자체는 UI 슬롯 안에서 실행한다. 작업 스레드는 CAD/파일 작업만 수행하며 QWidget/VTK 위젯 상태를 직접 변경하지 않는다. 모델 표시에도 UI 스레드 검사를 추가했다.

수정 후 소스 재현은 UI 스레드에서의 갱신을 확인했고, 실제 65그룹·64단계·LV CONT 예외를 복원했다. 회귀시험은 작업 함수와 UI 완료 함수가 서로 다른 스레드이고 UI 완료 함수가 QApplication 스레드인지 확인한다. 최종 EXE의 동일 검증은 `gui-reopen-v14-final.json`에 기록한다.

일반 QWidget 캡처는 native OpenGL 자식 영역을 검게 저장할 수 있으므로 실제 VTK 렌더 버퍼도 별도로 캡처한다. 렌더된 형상 수와 RGB의 공간적 표준편차를 확인하며, 검은 화면이나 균일 배경만 있으면 자체 점검을 실패 처리한다. 실제 버퍼 이미지는 `gui-reopen-v14-final-scene.png`다.

이 수정은 UI 작업 전달만 변경한다. 최종 순서 생성과 영상의 CAD 판정·시간축·경로는 변경하지 않았다. 이전 QtWidgets DLL 배포 수정도 유지한다.
