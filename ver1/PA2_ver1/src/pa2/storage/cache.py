from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .layout import DataLayout


def cache_key(stage: str, ordered_input_hashes: list[str], stage_version: str, relevant_settings: dict[str, Any], schema_version: int = 1) -> str:
    payload = json.dumps({
        "stage": stage,
        "inputs": ordered_input_hashes,
        "stage_version": stage_version,
        "settings": relevant_settings,
        "schema_version": schema_version,
    }, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class CacheStore:
    def __init__(self, layout: DataLayout) -> None:
        self.layout = layout
        layout.ensure()

    def get(self, stage: str, key: str) -> Path | None:
        target = self.layout.cache / stage / key
        complete = target / "complete.json"
        return target if complete.is_file() else None

    @contextmanager
    def publisher(self, stage: str, key: str) -> Iterator[Path]:
        stage_dir = self.layout.cache / stage
        stage_dir.mkdir(parents=True, exist_ok=True)
        final = stage_dir / key
        if self.get(stage, key):
            yield final
            return
        temp = stage_dir / f".{key}.{uuid.uuid4().hex}.tmp"
        temp.mkdir(parents=False)
        try:
            yield temp
            (temp / "complete.json").write_text(json.dumps({"key": key, "stage": stage}), encoding="utf-8")
            try:
                temp.replace(final)
            except FileExistsError:
                shutil.rmtree(temp, ignore_errors=True)
        except BaseException:
            shutil.rmtree(temp, ignore_errors=True)
            raise

    def collect_unreferenced(self, referenced: set[tuple[str, str]]) -> list[Path]:
        removed: list[Path] = []
        if not self.layout.cache.exists():
            return removed
        for stage_dir in self.layout.cache.iterdir():
            if not stage_dir.is_dir():
                continue
            for entry in stage_dir.iterdir():
                if entry.is_dir() and not entry.name.startswith(".") and (stage_dir.name, entry.name) not in referenced:
                    shutil.rmtree(entry)
                    removed.append(entry)
        return removed

