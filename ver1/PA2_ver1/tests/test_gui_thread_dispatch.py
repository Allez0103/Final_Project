import threading
import time
from pathlib import Path


def test_task_result_and_progress_are_dispatched_to_ui_thread(monkeypatch,tmp_path):
    monkeypatch.setenv('QT_QPA_PLATFORM','offscreen')
    monkeypatch.setenv('PA2_DATA_ROOT',str(tmp_path/'data'))
    from PySide6.QtCore import QThread
    from PySide6.QtWidgets import QApplication
    from pa2.ui.main_window import MainWindow
    app=QApplication.instance() or QApplication([])
    window=MainWindow(Path(__file__).resolve().parents[1])
    received=[]
    main_id=threading.get_ident()
    def work(progress):
        progress('test','background progress')
        return threading.get_ident()
    def done(worker_id):
        received.append((worker_id,threading.get_ident(),QThread.currentThread()==app.thread()))
    try:
        window._task(work,done)
        assert not window.project_page.isEnabled()
        deadline=time.monotonic()+5
        while time.monotonic()<deadline and (not received or window.thread.isRunning() or window.cancel_action.isEnabled()):
            app.processEvents(); time.sleep(.005)
        assert received and received[0][0]!=main_id
        assert received[0][1]==main_id and received[0][2]
        assert window.statusBar().currentMessage()=='background progress'
        assert not window.cancel_action.isEnabled()
        assert window.project_page.isEnabled()
    finally:
        if window.thread and window.thread.isRunning():
            window.cancel_event.set(); window.thread.quit(); window.thread.wait(5000)
        window.model_page.vtk_scene.render_window.Finalize()
        window.close()
