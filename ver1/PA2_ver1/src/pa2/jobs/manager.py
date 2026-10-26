from __future__ import annotations

import importlib
import multiprocessing as mp
import queue
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from pa2.domain.models import JobStatus


def _worker_entry(target: str, args: tuple[Any, ...], kwargs: dict[str, Any], events, cancel) -> None:
    try:
        module_name, function_name = target.rsplit(":", 1)
        function = getattr(importlib.import_module(module_name), function_name)
        events.put(("RUNNING", {"stage": "started"}))
        result = function(*args, cancel_event=cancel, event_queue=events, **kwargs)
        events.put(("SUCCEEDED", result))
    except BaseException as exc:
        events.put(("FAILED", {"type": type(exc).__name__, "message": str(exc)}))


@dataclass(slots=True)
class ProcessJob:
    id: str
    target: str
    process: mp.Process
    events: Any
    cancel_event: Any
    deadline: datetime
    status: JobStatus = JobStatus.QUEUED


class ProcessJobManager:
    """Spawn-isolated jobs with cooperative cancellation and a 5-second hard-stop boundary."""

    def __init__(self) -> None:
        self.context = mp.get_context("spawn")
        self.jobs: dict[str, ProcessJob] = {}

    def start(self, target: str, args: tuple[Any, ...] = (), kwargs: dict[str, Any] | None = None, timeout_sec: int = 3600) -> ProcessJob:
        events = self.context.Queue()
        cancel = self.context.Event()
        process = self.context.Process(target=_worker_entry, args=(target, args, kwargs or {}, events, cancel), daemon=True)
        job = ProcessJob(str(uuid.uuid4()), target, process, events, cancel, datetime.now(UTC)+timedelta(seconds=timeout_sec))
        self.jobs[job.id] = job
        process.start()
        job.status = JobStatus.RUNNING
        return job

    def poll(self, job_id: str) -> list[tuple[str, Any]]:
        job = self.jobs[job_id]
        result = []
        while True:
            try:
                event = job.events.get_nowait()
            except queue.Empty:
                break
            result.append(event)
            if event[0] in {"SUCCEEDED", "FAILED", "CANCELLED"}:
                job.status = JobStatus(event[0])
        if datetime.now(UTC) >= job.deadline and job.process.is_alive():
            self.cancel(job_id, timed_out=True)
        return result

    def cancel(self, job_id: str, *, timed_out: bool = False) -> None:
        job = self.jobs[job_id]
        if not job.process.is_alive():
            return
        job.status = JobStatus.CANCELLING
        job.cancel_event.set()
        job.process.join(timeout=5)
        if job.process.is_alive():
            job.process.terminate()
            job.process.join(timeout=2)
        job.status = JobStatus.TIMED_OUT if timed_out else JobStatus.CANCELLED

