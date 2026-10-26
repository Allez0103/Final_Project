from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from OCP.BRep import BRep_Builder
from OCP.BRepTools import BRepTools
from OCP.TopoDS import TopoDS_Shape

from pa2.domain.models import AtomicBody, Bounds

from .importer import CadScene
from .brep_io import read_shape,write_shape


def save_scene(scene: CadScene, directory: Path) -> None:
    body_dir = directory / "bodies"
    body_dir.mkdir(parents=True, exist_ok=True)
    body_rows = []
    for body in scene.bodies:
        filename = f"{body.solid_index:06d}.binbrep"
        write_shape(scene.shapes[body.id],body_dir / filename)
        row = asdict(body)
        row["brep_file"] = f"bodies/{filename}"
        body_rows.append(row)
    manifest = {
        "schema_version": 2,
        "brep_format": "binary",
        "source_path": str(scene.source_path),
        "source_hash": scene.source_hash,
        "source_relative_path": scene.source_relative_path,
        "unit_name": scene.unit_name,
        "non_solid_count": scene.non_solid_count,
        "elapsed_sec": scene.elapsed_sec,
        "bodies": body_rows,
    }
    (directory / "scene.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def load_scene(directory: Path, managed_source: Path) -> CadScene:
    manifest = json.loads((directory / "scene.json").read_text(encoding="utf-8"))
    bodies: list[AtomicBody] = []
    shapes: dict[str, TopoDS_Shape] = {}
    for row in manifest["bodies"]:
        brep_file = row.pop("brep_file")
        row["bounds"] = Bounds(**row["bounds"])
        row["centroid"] = tuple(row["centroid"]) if row.get("centroid") else None
        row["color_rgb"] = tuple(row["color_rgb"]) if row.get("color_rgb") else None
        row["world_transform"] = tuple(row["world_transform"])
        body = AtomicBody(**row)
        shape = read_shape(directory / brep_file)
        bodies.append(body)
        shapes[body.id] = shape
    return CadScene(
        source_path=managed_source,
        source_hash=manifest["source_hash"],
        source_relative_path=manifest["source_relative_path"],
        unit_name=manifest["unit_name"],
        bodies=bodies,
        shapes=shapes,
        non_solid_count=manifest["non_solid_count"],
        elapsed_sec=0.0,
    )

