from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from math import isfinite, sqrt
from typing import Any, Iterable


class PartType(StrEnum):
    BODY = "BODY"
    PLATE = "PLATE"
    BLOCK = "BLOCK"
    BUSBAR = "BUSBAR"
    RELAY = "RELAY"
    COVER = "COVER"
    SEAL = "SEAL"
    VENT = "VENT"
    BOLT = "BOLT"
    NUT = "NUT"
    HV_CONNECTOR = "HV_CONNECTOR"
    LV_CONNECTOR = "LV_CONNECTOR"
    UNKNOWN = "UNKNOWN"


class GeometryDecision(StrEnum):
    PASS = "PASS"
    BLOCKED = "BLOCKED"
    UNKNOWN = "UNKNOWN"
    NOT_TESTED = "NOT_TESTED"


class PlanningStatus(StrEnum):
    COMPLETE = "COMPLETE"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    PARTIAL = "PARTIAL"
    NO_SOLUTION_WITHIN_BUDGET = "NO_SOLUTION_WITHIN_BUDGET"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class JobStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    PARTIAL = "PARTIAL"
    TIMED_OUT = "TIMED_OUT"
    FAILED = "FAILED"
    CANCELLING = "CANCELLING"
    CANCELLED = "CANCELLED"


class MatchingStatus(StrEnum):
    MATCHED = "MATCHED"
    UNMATCHED = "UNMATCHED"
    AMBIGUOUS = "AMBIGUOUS"
    UNKNOWN = "UNKNOWN"


class GeometryStatus(StrEnum):
    MANUAL_ASSIGNED = "MANUAL_ASSIGNED"
    FASTENER_ASSIGNED = "FASTENER_ASSIGNED"
    DRAFT_UNRESOLVED = "DRAFT_UNRESOLVED"
    USER_COLLISION_EXCEPTION = "USER_COLLISION_EXCEPTION"
    AUTO_CHECKED = "AUTO_CHECKED"
    FASTENER_EXCEPTION = "FASTENER_EXCEPTION"
    INITIAL_REGION_EXCEPTION = "INITIAL_REGION_EXCEPTION"
    INITIAL_DECREASE_EXCEPTION = "INITIAL_DECREASE_EXCEPTION"
    GEOMETRY_REPAIRED = "GEOMETRY_REPAIRED"
    SUPPORT_UNVERIFIED = "SUPPORT_UNVERIFIED"
    USER_CONFIRMED_UNCHECKED = "USER_CONFIRMED_UNCHECKED"
    USER_CONFIRMED = "USER_CONFIRMED"


class ErrorCode(StrEnum):
    INPUT_UNREADABLE = "INPUT_UNREADABLE"
    UNIT_UNKNOWN = "UNIT_UNKNOWN"
    NO_SHAPE = "NO_SHAPE"
    INVALID_GEOMETRY = "INVALID_GEOMETRY"
    GROUP_AMBIGUOUS = "GROUP_AMBIGUOUS"
    INITIAL_OVERLAP = "INITIAL_OVERLAP"
    PATH_BLOCKED = "PATH_BLOCKED"
    PATH_UNKNOWN = "PATH_UNKNOWN"
    SUPPORT_UNKNOWN = "SUPPORT_UNKNOWN"
    TIME_BUDGET_EXCEEDED = "TIME_BUDGET_EXCEEDED"
    MEMORY_BUDGET_EXCEEDED = "MEMORY_BUDGET_EXCEEDED"
    MODEL_INCOMPATIBLE = "MODEL_INCOMPATIBLE"
    RENDER_FAILED = "RENDER_FAILED"
    ENCODE_FAILED = "ENCODE_FAILED"
    STORAGE_FAILED = "STORAGE_FAILED"


Vector3 = tuple[float, float, float]
Matrix4 = tuple[float, ...]


IDENTITY_4X4: Matrix4 = (
    1.0, 0.0, 0.0, 0.0,
    0.0, 1.0, 0.0, 0.0,
    0.0, 0.0, 1.0, 0.0,
    0.0, 0.0, 0.0, 1.0,
)


def normalize(v: Iterable[float]) -> Vector3:
    values = tuple(float(x) for x in v)
    if len(values) != 3 or not all(isfinite(x) for x in values):
        raise ValueError("방향은 유한한 3차원 벡터여야 합니다.")
    length = sqrt(sum(x * x for x in values))
    if length <= 1e-12:
        raise ValueError("영벡터는 방향으로 사용할 수 없습니다.")
    return tuple(x / length for x in values)  # type: ignore[return-value]


def translate_matrix(v: Vector3) -> Matrix4:
    x, y, z = v
    return (
        1.0, 0.0, 0.0, x,
        0.0, 1.0, 0.0, y,
        0.0, 0.0, 1.0, z,
        0.0, 0.0, 0.0, 1.0,
    )


@dataclass(frozen=True, slots=True)
class Bounds:
    xmin: float
    ymin: float
    zmin: float
    xmax: float
    ymax: float
    zmax: float

    @property
    def center(self) -> Vector3:
        return ((self.xmin + self.xmax) / 2, (self.ymin + self.ymax) / 2, (self.zmin + self.zmax) / 2)

    @property
    def size(self) -> Vector3:
        return (self.xmax - self.xmin, self.ymax - self.ymin, self.zmax - self.zmin)

    @property
    def diagonal(self) -> float:
        x, y, z = self.size
        return sqrt(x * x + y * y + z * z)

    def expanded(self, gap: float) -> "Bounds":
        return Bounds(self.xmin-gap, self.ymin-gap, self.zmin-gap, self.xmax+gap, self.ymax+gap, self.zmax+gap)

    def intersects(self, other: "Bounds") -> bool:
        return not (
            self.xmax < other.xmin or self.xmin > other.xmax or
            self.ymax < other.ymin or self.ymin > other.ymax or
            self.zmax < other.zmin or self.zmin > other.zmax
        )

    def translated(self, v: Vector3) -> "Bounds":
        x, y, z = v
        return Bounds(self.xmin+x, self.ymin+y, self.zmin+z, self.xmax+x, self.ymax+y, self.zmax+z)

    @classmethod
    def union(cls, values: Iterable["Bounds"]) -> "Bounds":
        vals = list(values)
        if not vals:
            raise ValueError("빈 경계 상자 집합입니다.")
        return cls(
            min(v.xmin for v in vals), min(v.ymin for v in vals), min(v.zmin for v in vals),
            max(v.xmax for v in vals), max(v.ymax for v in vals), max(v.zmax for v in vals),
        )


@dataclass(slots=True)
class AtomicBody:
    id: str
    source_hash: str
    source_relative_path: str
    solid_index: int
    occurrence_path: str
    display_name: str
    bounds: Bounds
    volume_mm3: float | None
    area_mm2: float | None
    centroid: Vector3 | None
    geometry_valid: bool
    unit: str = "mm"
    color_rgb: tuple[float, float, float] | None = None
    world_transform: Matrix4 = IDENTITY_4X4


@dataclass(slots=True)
class AssemblyGroup:
    id: str
    display_name: str
    body_ids: list[str]
    part_type: PartType
    bounds: Bounds
    volume_mm3: float | None
    centroid: Vector3 | None
    geometry_valid: bool
    matching_status: MatchingStatus = MatchingStatus.UNMATCHED
    part_definition_id: str | None = None
    hidden: bool = False


@dataclass(slots=True)
class ContactEdge:
    group_a: str
    group_b: str
    distance_mm: float | None
    evidence: dict[str, Any] = field(default_factory=dict)
    policy_version: str = "contact-v1"

    @property
    def pair_id(self) -> str:
        return "::".join(sorted((self.group_a, self.group_b)))


@dataclass(slots=True)
class PathCheckResult:
    group_id: str
    state_key: str
    direction: Vector3
    travel_mm: float
    decision: GeometryDecision
    reason_code: str
    obstacle_ids: list[str] = field(default_factory=list)
    elapsed_sec: float = 0.0
    policy_version: str = "path-v1"
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PlanStep:
    group_id: str
    step_index: int
    removal_direction: Vector3
    assembly_direction: Vector3
    travel_mm: float
    camera_mode: str = "AUTO"
    process_text: str = ""
    material_text: str = ""
    caution_text: str = ""
    geometry_status: GeometryStatus = GeometryStatus.AUTO_CHECKED
    source_run_id: str = ""
    final_transform: Matrix4 = IDENTITY_4X4
    camera_roll_deg: int = 0

    def validate(self) -> None:
        self.removal_direction = normalize(self.removal_direction)
        self.assembly_direction = normalize(self.assembly_direction)
        dot = sum(a*b for a, b in zip(self.removal_direction, self.assembly_direction))
        if dot > -0.999:
            raise ValueError("조립 방향은 분해 방향의 역방향이어야 합니다.")
        if not isfinite(self.travel_mm) or self.travel_mm <= 0:
            raise ValueError("이동 거리는 0보다 큰 유한값이어야 합니다.")
        valid_cameras = {"AUTO", "TOP", "BOTTOM", "FRONT", "BACK", "LEFT", "RIGHT"}
        if self.camera_mode not in valid_cameras:
            raise ValueError(f"알 수 없는 카메라 모드: {self.camera_mode}")
        if type(self.camera_roll_deg) is not int or self.camera_roll_deg not in (0, 90, 180, 270):
            raise ValueError("카메라 화면 회전은 0/90/180/270도여야 합니다.")

    @property
    def disassembly_end_transform(self) -> Matrix4:
        d = self.removal_direction
        return translate_matrix((d[0]*self.travel_mm, d[1]*self.travel_mm, d[2]*self.travel_mm))


@dataclass(slots=True)
class Plan:
    id: str
    project_id: str
    revision: int
    base_group_id: str
    group_ids: list[str]
    steps: list[PlanStep]
    status: PlanningStatus
    source_algorithm: str = "default"
    user_modified: bool = False
    input_snapshot_id: str = ""
    settings_version: str = "settings-v1"

    def validate(self, *, allow_partial: bool = False) -> None:
        expected = set(self.group_ids) - {self.base_group_id}
        actual = [step.group_id for step in self.steps]
        if len(actual) != len(set(actual)):
            raise ValueError("같은 이동 그룹이 계획에 두 번 이상 포함되어 있습니다.")
        if set(actual) != expected and not (allow_partial and self.status in {
                PlanningStatus.PARTIAL, PlanningStatus.REVIEW_REQUIRED,
                PlanningStatus.NO_SOLUTION_WITHIN_BUDGET} and set(actual) <= expected):
            missing = sorted(expected - set(actual))
            extra = sorted(set(actual) - expected)
            raise ValueError(f"계획 그룹 불일치(누락={missing}, 추가={extra})")
        for index, step in enumerate(self.steps, start=1):
            step.step_index = index
            step.validate()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class PlanningResult:
    status: PlanningStatus
    removal_order: list[str]
    assembly_plan: Plan | None
    path_results: list[PathCheckResult]
    reason: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ImportSnapshot:
    id: str
    project_id: str
    project_revision: int
    assembly_asset_hash: str
    atomic_bodies: list[AtomicBody]
    groups: list[AssemblyGroup]
    contacts: list[ContactEdge]
    scene_ready: bool
    groups_ready: bool
    calculation_ready: bool
    diagnostics: list[dict[str, Any]] = field(default_factory=list)

