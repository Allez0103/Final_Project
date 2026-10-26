from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_data_dir


def ensure_writable_directory(path: Path) -> None:
    path=Path(path)
    try:
        path.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=path) as probe:
            probe.write(b'PA2'); probe.flush()
    except OSError as exc:
        raise OSError(f'STORAGE_FAILED: 저장 경로에 쓸 수 없습니다: {path}') from exc


@dataclass(frozen=True, slots=True)
class DataLayout:
    root: Path

    @classmethod
    def default(cls) -> "DataLayout":
        override = os.environ.get("PA2_DATA_ROOT")
        return cls(Path(override) if override else Path(user_data_dir("PA2", "THN")))

    @property
    def projects(self) -> Path: return self.root / "projects"
    @property
    def assets(self) -> Path: return self.root / "assets"
    @property
    def cache(self) -> Path: return self.root / "cache"
    @property
    def jobs(self) -> Path: return self.root / "jobs"
    @property
    def learning(self) -> Path: return self.root / "learning"
    @property
    def database(self) -> Path: return self.root / "database"
    @property
    def logs(self) -> Path: return self.root / "logs"

    def ensure(self) -> None:
        for path in (self.projects, self.assets, self.cache, self.jobs, self.learning, self.database, self.logs):
            path.mkdir(parents=True, exist_ok=True)

