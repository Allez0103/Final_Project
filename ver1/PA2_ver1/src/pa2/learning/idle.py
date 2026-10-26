"""App-lifetime, opt-in idle scheduler. No service and no training on import."""
from __future__ import annotations

import multiprocessing as mp
import os
import threading
import time
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QTimer
from PySide6.QtWidgets import QApplication


def stop_tree(process):
    """Only descendants of our own multiprocessing child are eligible targets."""
    import psutil
    if process is None or process.pid is None:
        return
    try:
        parent = psutil.Process(process.pid)
        # A joined child PID may have been reused; never target a replacement.
        if not process.is_alive():
            process.join(timeout=0); return
        children = parent.children(recursive=True)
        for child in reversed(children):
            try:
                child.kill()
            except psutil.Error:
                pass
        process.terminate(); process.join(timeout=.3)
        if process.is_alive():
            process.kill(); process.join(timeout=.3)
    except (psutil.Error, OSError):
        if process.is_alive():
            process.terminate(); process.join(timeout=.3)


def _idle_worker(data_root, database_url, raw_settings, cancel, host_pid, host_created):
    # This process has no GUI. Its children inherit one-core affinity and the
    # single-thread numerical settings before any estimator is imported.
    for name in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
        os.environ[name] = '1'
    import psutil
    current = psutil.Process()
    try:
        if os.name == 'nt':
            current.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
        else:
            current.nice(10)
        if hasattr(current, 'cpu_affinity'):
            allowed = current.cpu_affinity()
            if allowed:
                current.cpu_affinity([allowed[-1]])
    except psutil.Error:
        pass

    def parent_guard():
        while not cancel.wait(1.):
            try:
                if psutil.Process(host_pid).create_time() == host_created:
                    continue
            except psutil.Error:
                pass
            for child in current.children(recursive=True):
                try:
                    child.kill()
                except psutil.Error:
                    pass
            os._exit(0)
    threading.Thread(target=parent_guard, daemon=True).start()
    from pa2.settings.config import AppSettings
    from pa2.storage.database import Database
    from pa2.storage.layout import DataLayout
    from .data import atomic_json
    from .pipeline import LearningPipeline
    layout = DataLayout(Path(data_root))
    lock_path = layout.learning/'idle-worker.lock'
    layout.learning.mkdir(parents=True, exist_ok=True)
    # OS lock automatically releases on cancellation/crash; coordinates multiple
    # windows without trusting stale PID files or deleting another window's lock.
    with lock_path.open('a+b') as lock:
        if lock.seek(0, 2) == 0:
            lock.write(b'0'); lock.flush()
        lock.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return
        database = Database(layout, url=database_url)
        database.initialize()
        pipeline=LearningPipeline(database, AppSettings(**raw_settings), cancel.is_set)
        result = pipeline.run()
        if getattr(pipeline,'log_warning',None):result['log_warning']=pipeline.log_warning
        atomic_json(layout.learning/'last-idle-result.json', result)
        database.engine.dispose()


class IdleLearningController(QObject):
    def __init__(self, database, settings_getter, busy_getter, parent=None):
        super().__init__(parent)
        self.database, self.settings_getter, self.busy_getter = database, settings_getter, busy_getter
        self.last_input = time.monotonic()
        self.next_attempt, self.started = 0., 0.
        self.process = self.cancel = None
        self.closed = False
        self.message = '자동 학습 꺼짐 · 고객 데이터 학습·검증 미실행'
        self._signature = None
        self.timer = QTimer(self)
        self.timer.setInterval(500); self.timer.timeout.connect(self.tick)
        app = QApplication.instance()
        app.installEventFilter(self)
        app.aboutToQuit.connect(self.close)
        self.timer.start()

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.KeyPress, QEvent.Type.MouseButtonPress,
                            QEvent.Type.Wheel, QEvent.Type.TouchBegin, QEvent.Type.MouseMove):
            self.user_activity()
        return False

    def user_activity(self):
        self.last_input = time.monotonic()
        if self.process:
            self.pause('사용자 작업: 다음 유휴 시간에 재개')

    def pause(self, reason):
        if self.cancel:
            self.cancel.set()
        if self.process:
            # No wait for a long C++ or tree-fitting call on the UI thread.
            self.process.join(timeout=.05)
            stop_tree(self.process)
            self.process.close()
        self.process = self.cancel = None
        self.message = reason
        self.next_attempt = max(self.next_attempt, time.monotonic()+60)

    def tick(self):
        if self.closed:
            return
        if os.environ.get('PA2_DISABLE_BACKGROUND_LEARNING') == '1':
            if self.process:
                self.pause('실행 환경에서 백그라운드 학습 차단')
            self.message = '실행 환경에서 백그라운드 학습 차단'
            return
        from dataclasses import asdict
        settings = self.settings_getter()
        signature = tuple(sorted(asdict(settings).items()))
        if self._signature != signature:
            self.pause('설정 변경 · 다음 유휴 시간에 확인')
            self._signature = signature
        if self.busy_getter():
            if self.process:
                self.pause('프로그램 작업 중 · 학습 보류')
            return
        if not settings.auto_learning_enabled and not settings.auto_model_apply_enabled:
            if self.process:
                self.pause('자동 학습 꺼짐')
            self.message = '자동 학습·적용 꺼짐 · 학습 검증은 별도 진행 예정'
            return
        now = time.monotonic()
        if self.process:
            if not self.process.is_alive():
                self.process.join(timeout=0); self.process.close()
                self.process = self.cancel = None
                self.message = '유휴 작업 종료 · 학습 현황에서 결과 확인'
                result_path=self.database.layout.learning/'last-idle-result.json'
                if result_path.exists():
                    import json
                    result=json.loads(result_path.read_text(encoding='utf-8'))
                    if result.get('log_warning'):self.message=result['log_warning']
                self.next_attempt = now+60
            else:
                import psutil
                try:
                    parent = psutil.Process(self.process.pid)
                    memory = sum(p.memory_info().rss for p in [parent]+parent.children(recursive=True))
                    if memory > settings.learning_memory_mb*1024**2 or now-self.started > settings.learning_budget_sec+5:
                        self.pause('학습 자원·시간 한도 · 다음 유휴 시간에 재개')
                        self.next_attempt = now+600
                except psutil.Error:
                    pass
                return
        if now-self.last_input < settings.learning_idle_sec or now < self.next_attempt:
            return
        from .registry import ModelRegistry
        from .pipeline import policy_signature
        from pa2.storage.database import LearningCycle
        registry = ModelRegistry(self.database)
        try:
            with self.database.session() as session:
                ready = session.query(LearningCycle).filter_by(status='READY').order_by(LearningCycle.created_at.desc()).first()
            if ready and settings.auto_model_apply_enabled:
                from pa2.settings.config import AppSettings
                if policy_signature(AppSettings(**ready.settings_json)) == policy_signature(settings):
                    registry.promote(ready.id)
                    self.message = '평가 통과 모델 적용 · 다음 자동 생성부터 사용'
                else:
                    self.message = '대기 모델의 설정이 변경되어 적용 보류'
                    from pa2.storage.database import utcnow
                    with self.database.session() as session:
                        stale=session.get(LearningCycle, ready.id)
                        if stale.status == 'READY':
                            stale.status='STALE'; stale.updated_at=utcnow(); stale.completed_at=utcnow()
                            stale.error_detail='평가 이후 설정 변경: 적용 금지'
                self.next_attempt = now+60
                return
        except Exception as exc:
            self.message = '모델 적용 보류: '+str(exc)
            self.next_attempt = now+60
            return
        if not settings.auto_learning_enabled:
            self.next_attempt = now+60
            return
        from pa2.storage.database import LearningProgress,LearningObservation,ConfirmationRecord,TrainingCase,RankingState
        with self.database.session() as session:
            progress=session.get(LearningProgress,'common')
            if progress:
                ids={p[0] for p in session.query(ConfirmationRecord.project_id).join(LearningObservation,
                    LearningObservation.confirmation_id==ConfirmationRecord.id).distinct()}
                count=len(ids-set(progress.baseline_json.get('project_ids',[])))
                ready=count>=settings.retrain_new_projects
                reason=f'신규 확정 프로젝트 {count}/{settings.retrain_new_projects} · 유효 데이터는 학습 작업에서 확인'
            else:
                ready=session.query(TrainingCase.family_id).distinct().count()>=settings.training_min_families and session.query(RankingState).count()>=settings.training_min_states
                reason='최초 학습 데이터 기준 확인'
        if not ready:
            self.message=reason
            self.next_attempt=now+60
            return
        import psutil
        parent = psutil.Process()
        context = mp.get_context('spawn')
        self.cancel = context.Event()
        self.process = context.Process(target=_idle_worker,
            args=(str(self.database.layout.root.resolve()), str(self.database.engine.url.render_as_string(hide_password=False)),
                  asdict(settings), self.cancel, parent.pid, parent.create_time()), daemon=False)
        try:
            self.process.start()
        except Exception as exc:
            self.process = self.cancel = None
            self.message = '학습 작업 시작 보류: '+str(exc)
            self.next_attempt = now+600
            return
        self.started = now
        self.message = '유휴 시간 공통 주기 확인·순차 학습·평가 중'

    def close(self):
        if self.closed:
            return
        self.closed = True; self.timer.stop()
        QApplication.instance().removeEventFilter(self)
        self.pause('프로그램 종료: 학습 프로세스 종료')
