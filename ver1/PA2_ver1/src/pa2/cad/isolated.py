from __future__ import annotations

import tempfile
from pathlib import Path

from OCP.BRepTools import BRepTools

from pa2.jobs.isolated import IsolatedCadWorker
from pa2.storage.layout import DataLayout
from .shapes import compound
from .brep_io import write_shape


class NativeCadSession:
    """Own a private BREP snapshot and its reusable native worker."""
    def __init__(self, groups, shapes_by_body, *, native_timeout=120, cancel_check=lambda: False, jobs_dir=None):
        self.groups = groups
        self.shapes_by_body = shapes_by_body
        self.cancel_check = cancel_check
        self.jobs_dir = Path(jobs_dir) if jobs_dir else DataLayout.default().jobs
        self.native_timeout = native_timeout
        self.worker = None
        self.directory = None

    def __enter__(self):
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self.directory = tempfile.TemporaryDirectory(prefix="native-", dir=self.jobs_dir)
        try:
            files = {}
            for index, group in enumerate(self.groups):
                if self.cancel_check():
                    raise InterruptedError("작업을 취소했습니다.")
                path = Path(self.directory.name) / f"{index:06d}.binbrep"
                shape = compound([self.shapes_by_body[body_id] for body_id in group.body_ids])
                write_shape(shape,path)
                files[group.id] = str(path)
            self.worker = IsolatedCadWorker(files, self.native_timeout, self.cancel_check)
            return self.worker
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, *_):
        if self.worker is not None:
            self.worker.close()
        if self.directory is not None:
            self.directory.cleanup()
