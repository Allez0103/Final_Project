from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from OCP.Bnd import Bnd_Box
from OCP.BRep import BRep_Tool
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepGProp import BRepGProp
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.GProp import GProp_GProps
from OCP.IFSelect import IFSelect_RetDone
from OCP.STEPControl import STEPControl_Reader
from OCP.TopAbs import TopAbs_FACE, TopAbs_SOLID
from OCP.TopExp import TopExp_Explorer
from OCP.TopLoc import TopLoc_Location
from OCP.TopoDS import TopoDS, TopoDS_Shape
from OCP.collections import Sequence_TCollection_AsciiString

from pa2.domain.models import AtomicBody, Bounds, ErrorCode


Progress = Callable[[str, str], None]


class CadImportError(RuntimeError):
    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(slots=True)
class CadScene:
    source_path: Path
    source_hash: str
    source_relative_path: str
    unit_name: str
    bodies: list[AtomicBody]
    shapes: dict[str, TopoDS_Shape] = field(repr=False)
    non_solid_count: int = 0
    elapsed_sec: float = 0.0
    original_name: str = ""

    @property
    def bounds(self) -> Bounds:
        return Bounds.union(body.bounds for body in self.bodies)


def _bounds(shape: TopoDS_Shape) -> Bounds:
    box = Bnd_Box()
    BRepBndLib.AddOptimal_s(shape, box, False, False)
    low, high = box.CornerMin(), box.CornerMax()
    return Bounds(low.X(), low.Y(), low.Z(), high.X(), high.Y(), high.Z())


def _properties(shape: TopoDS_Shape) -> tuple[float | None, float | None, tuple[float, float, float] | None]:
    volume_props, area_props = GProp_GProps(), GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, volume_props)
    BRepGProp.SurfaceProperties_s(shape, area_props)
    volume = float(volume_props.Mass())
    area = float(area_props.Mass())
    center = volume_props.CentreOfMass()
    centroid = (float(center.X()), float(center.Y()), float(center.Z())) if volume > 0 else None
    return (volume if volume > 0 else None, area if area > 0 else None, centroid)


def _file_units(reader: STEPControl_Reader) -> str | None:
    length_names = Sequence_TCollection_AsciiString()
    angle_names = Sequence_TCollection_AsciiString()
    solid_angle_names = Sequence_TCollection_AsciiString()
    reader.FileUnits(length_names, angle_names, solid_angle_names)
    names = [length_names.Value(i).ToCString().strip().lower() for i in range(1, length_names.Length() + 1)]
    if not names:
        return None
    canonical = {"millimetre": "mm", "millimeter": "mm", "mm": "mm", "inch": "inch", "in": "inch"}
    values = {canonical.get(name, name) for name in names}
    return values.pop() if len(values) == 1 else None


class StepImporter:
    VERSION = "step-import-v3-part-color"

    def read(
        self,
        path: Path,
        source_hash: str,
        source_relative_path: str,
        *,
        assumed_unit: str | None = None,
        progress: Progress | None = None,
    ) -> CadScene:
        started = time.perf_counter()
        path = path.resolve(strict=True)
        if path.suffix.lower() not in {".stp", ".step"}:
            raise CadImportError(ErrorCode.INPUT_UNREADABLE, "STEP(.stp/.step) 파일만 불러올 수 있습니다.")
        callback = progress or (lambda _stage, _message: None)
        callback("reading", f"{path.name} 읽는 중")
        reader = STEPControl_Reader()
        try:
            status = reader.ReadFile(str(path))
        except Exception as exc:
            raise CadImportError(ErrorCode.INPUT_UNREADABLE, f"STEP 파일을 읽지 못했습니다: {path.name}") from exc
        if status != IFSelect_RetDone:
            raise CadImportError(ErrorCode.INPUT_UNREADABLE, f"STEP 파서가 파일을 거부했습니다: {path.name}")
        unit_name = _file_units(reader) or assumed_unit
        if unit_name not in {"mm", "inch"}:
            raise CadImportError(ErrorCode.UNIT_UNKNOWN, "STEP 길이 단위를 확인할 수 없습니다. mm 또는 inch를 지정하세요.")
        # STEPControl converts to the configured system unit (millimetres in this verified runtime).
        reader.SetSystemLengthUnit(1.0)
        callback("displaying", "형상과 배치를 변환하는 중")
        if reader.TransferRoots() <= 0:
            raise CadImportError(ErrorCode.NO_SHAPE, "STEP 파일에서 변환 가능한 형상을 찾지 못했습니다.")
        root = reader.OneShape()
        if root.IsNull():
            raise CadImportError(ErrorCode.NO_SHAPE, "STEP 파일에 표시 가능한 형상이 없습니다.")

        bodies: list[AtomicBody] = []
        shapes: dict[str, TopoDS_Shape] = {}
        explorer = TopExp_Explorer(root, TopAbs_SOLID)
        index = 0
        callback("validating", "솔리드 유효성과 기본 특징을 확인하는 중")
        while explorer.More():
            shape = explorer.Current()
            body_id = f"body-{source_hash[:12]}-{index:06d}"
            try:
                bounds = _bounds(shape)
                volume, area, centroid = _properties(shape)
                valid = bool(BRepCheck_Analyzer(shape, False).IsValid()) and volume is not None
            except Exception:
                bounds = Bounds(0, 0, 0, 0, 0, 0)
                volume = area = centroid = None
                valid = False
            body = AtomicBody(
                id=body_id,
                source_hash=source_hash,
                source_relative_path=source_relative_path,
                solid_index=index,
                occurrence_path=f"/{path.stem}/solid[{index}]",
                display_name=f"{path.stem} · 바디 {index + 1}",
                bounds=bounds,
                volume_mm3=volume,
                area_mm2=area,
                centroid=centroid,
                geometry_valid=valid,
                unit="mm",
            )
            bodies.append(body)
            shapes[body_id] = shape
            index += 1
            explorer.Next()
        if not bodies:
            raise CadImportError(ErrorCode.NO_SHAPE, "계산 대상 솔리드가 없습니다. 열린 셸/곡면만 있는지 확인하세요.")

        callback('colors', 'STEP 부품 대표 색상을 읽는 중')
        try:
            from .step_colors import apply_step_colors
            apply_step_colors(reader, bodies, shapes)
        except Exception as exc:
            # Color metadata is optional; never turn an otherwise usable CAD
            # model into a failed import, nor change any collision tolerance.
            callback('colors', f'색상 정보 복원 생략 · 기본 색상 사용: {type(exc).__name__}: {exc}')

        faces = 0
        face_explorer = TopExp_Explorer(root, TopAbs_FACE)
        while face_explorer.More():
            faces += 1
            face_explorer.Next()
        non_solid_count = 0 if faces else 1
        return CadScene(
            source_path=path,
            source_hash=source_hash,
            source_relative_path=source_relative_path,
            unit_name=unit_name,
            bodies=bodies,
            shapes=shapes,
            non_solid_count=non_solid_count,
            elapsed_sec=time.perf_counter() - started,
        )


def tessellate_shape(shape: TopoDS_Shape, deflection_mm: float = 0.2) -> tuple[list[tuple[float, float, float]], list[tuple[int, int, int]]]:
    """Return world-coordinate triangles without serializing an OCP object."""
    BRepMesh_IncrementalMesh(shape, deflection_mm, False, 0.5, True)
    points: list[tuple[float, float, float]] = []
    triangles: list[tuple[int, int, int]] = []
    explorer = TopExp_Explorer(shape, TopAbs_FACE)
    while explorer.More():
        face = TopoDS.Face(explorer.Current())
        location = TopLoc_Location()
        triangulation = BRep_Tool.Triangulation_s(face, location)
        if triangulation is not None and triangulation.NbNodes() > 0:
            transform = location.Transformation()
            offset = len(points)
            for node_index in range(1, triangulation.NbNodes() + 1):
                point = triangulation.Node(node_index).Transformed(transform)
                points.append((point.X(), point.Y(), point.Z()))
            reverse = face.Orientation().name == "TopAbs_REVERSED"
            for triangle_index in range(1, triangulation.NbTriangles() + 1):
                a, b, c = triangulation.Triangle(triangle_index).Get()
                if reverse:
                    b, c = c, b
                triangles.append((offset + a - 1, offset + b - 1, offset + c - 1))
        explorer.Next()
    return points, triangles


def stable_shape_signature(bodies: list[AtomicBody]) -> str:
    values = []
    for body in bodies:
        values.append((round(body.volume_mm3 or -1, 6), tuple(round(x, 6) for x in body.bounds.size)))
    return hashlib.sha256(repr(sorted(values)).encode("utf-8")).hexdigest()

