from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

from .layout import DataLayout


@dataclass(frozen=True, slots=True)
class ManagedAsset:
    sha256: str
    original_name: str
    original_path: str
    relative_path: str
    byte_size: int
    kind: str


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


class AssetStore:
    def __init__(self, layout: DataLayout) -> None:
        self.layout = layout
        layout.ensure()

    def ingest(self, source: Path, kind: str) -> ManagedAsset:
        source = source.resolve(strict=True)
        if not source.is_file() or not os.access(source, os.R_OK):
            raise OSError(f"읽을 수 없는 입력 파일입니다: {source}")
        if source.suffix.lower() not in {".stp", ".step", ".png", ".mp4"}:
            raise ValueError(f"지원하지 않는 입력 형식입니다: {source.suffix}")
        checksum = sha256_file(source)
        target_dir = self.layout.assets / checksum
        target_dir.mkdir(parents=True, exist_ok=True)
        safe_suffix = source.suffix.lower()
        payload = target_dir / f"source{safe_suffix}"
        manifest = target_dir / "manifest.json"
        if not payload.exists():
            temp = target_dir / f".{uuid.uuid4().hex}.tmp"
            shutil.copyfile(source, temp)
            if sha256_file(temp) != checksum:
                temp.unlink(missing_ok=True)
                raise IOError("관리 사본의 해시 검증에 실패했습니다.")
            temp.replace(payload)
        asset = ManagedAsset(
            sha256=checksum,
            original_name=source.name,
            original_path=str(source),
            relative_path=payload.relative_to(self.layout.root).as_posix(),
            byte_size=source.stat().st_size,
            kind=kind,
        )
        if not manifest.exists():
            temp_manifest = manifest.with_suffix(".tmp")
            temp_manifest.write_text(json.dumps(asdict(asset), ensure_ascii=False, indent=2), encoding="utf-8")
            temp_manifest.replace(manifest)
        return asset

    def resolve(self, relative_path: str) -> Path:
        candidate = (self.layout.root / relative_path).resolve()
        root = self.layout.root.resolve()
        if root not in candidate.parents:
            raise ValueError("관리 영역 밖의 자산 경로입니다.")
        return candidate

