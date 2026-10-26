"""One reusable spawn worker; all messages contain paths/IDs/structured data only."""
from __future__ import annotations

import multiprocessing as mp
import time
import json
from pathlib import Path


class NativeCallError(RuntimeError):
    pass


class NativeTimeout(NativeCallError):
    pass


def _serve(connection, cancel, files):
    # Import inside the child: no native CAD objects cross the process boundary.
    from pa2.cad.native_worker import CadDispatcher

    status_path = Path(next(iter(files.values()))).parent / "native-status.json" if files else None
    last_status = [None, 0.0]
    def activity(name):
        if cancel.is_set():
            raise InterruptedError("작업을 취소했습니다.")
        now=time.monotonic()
        if status_path is not None and (name != last_status[0] or now-last_status[1] >= 0.5):
            status_path.write_text(json.dumps({"operation":name,"started":time.time()}),encoding="utf-8")
            last_status[:]=[name,now]
        connection.send(("operation", name))

    dispatcher = CadDispatcher(files, activity)
    try:
        while True:
            request = connection.recv()
            if request is None:
                return
            try:
                result = dispatcher.execute(*request)
                connection.send(("result", result))
            except InterruptedError:
                connection.send(("cancelled", None))
            except Exception as exc:
                connection.send(("error", f"{type(exc).__name__}: {exc}"))
    except (EOFError, BrokenPipeError, OSError):
        return
    finally:
        connection.close()


class IsolatedCadWorker:
    def __init__(self, files, native_timeout=120, cancel_check=lambda: False):
        self.files = files
        self.native_timeout = native_timeout
        self.cancel_check = cancel_check
        self.context = mp.get_context("spawn")
        self.process = None
        self.connection = None
        self.cancel = None

    def _start(self):
        parent, child = self.context.Pipe()
        self.cancel = self.context.Event()
        self.process = self.context.Process(target=_serve, args=(child, self.cancel, self.files), daemon=True)
        self.process.start()
        child.close()
        self.connection = parent

    def call(self, operation, payload, *, deadline=None):
        if self.cancel_check():
            raise InterruptedError("작업을 취소했습니다.")
        if deadline is not None and time.monotonic() >= deadline:
            raise NativeTimeout("전체 또는 후보 시간 제한을 초과했습니다.")
        if self.process is None:
            self._start()
        stage = "worker startup"
        operation_deadline = time.monotonic() + self.native_timeout
        try:
            self.connection.send((operation, payload))
            while True:
                if self.cancel_check():
                    # Request cooperation, then stop unresponsive C++ within five seconds.
                    self.cancel.set()
                    self.close(grace=0.5)
                    raise InterruptedError("작업을 취소했습니다.")
                now = time.monotonic()
                if now >= operation_deadline or (deadline is not None and now >= deadline):
                    self.close(grace=0)
                    raise NativeTimeout(f"시간 제한 초과: {stage}")
                if self.connection.poll(0.025):
                    kind, value = self.connection.recv()
                    if kind == "operation":
                        stage = value
                        operation_deadline = time.monotonic() + self.native_timeout
                    elif kind == "result":
                        return value
                    elif kind == "cancelled":
                        raise InterruptedError("작업을 취소했습니다.")
                    else:
                        raise NativeCallError(value)
                elif not self.process.is_alive():
                    raise NativeCallError(f"CAD 작업 프로세스 종료 (code={self.process.exitcode})")
        except InterruptedError:
            self.close(grace=0)
            raise
        except (EOFError, BrokenPipeError, OSError) as exc:
            self.close(grace=0)
            raise NativeCallError(f"CAD 작업 프로세스 통신 실패: {exc}") from exc
        except BaseException:
            self.close(grace=0)
            raise

    def close(self, grace=0.25):
        process, connection = self.process, self.connection
        self.process = self.connection = None
        if process is None:
            return
        try:
            if connection is not None:
                try:
                    connection.send(None)
                except (BrokenPipeError, OSError):
                    pass
            process.join(timeout=grace)
            if process.is_alive():
                process.terminate()
                process.join(timeout=1)
            if process.is_alive():
                process.kill()
                process.join(timeout=1)
        finally:
            if connection is not None:
                connection.close()
            if not process.is_alive():
                process.close()
