from __future__ import annotations

import os
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship

from .layout import DataLayout


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class VehicleType(Base, TimestampMixin):
    __tablename__ = "vehicle_types"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)


class ProductType(Base, TimestampMixin):
    __tablename__ = "product_types"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    vehicle_type_id: Mapped[str] = mapped_column(ForeignKey("vehicle_types.id", ondelete="RESTRICT"), index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    __table_args__ = (UniqueConstraint("vehicle_type_id", "name", name="uq_product_vehicle_name"),)


class Project(Base, TimestampMixin):
    __tablename__ = "projects"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    vehicle_type_id: Mapped[str] = mapped_column(ForeignKey("vehicle_types.id", ondelete="RESTRICT"), index=True)
    product_type_id: Mapped[str] = mapped_column(ForeignKey("product_types.id", ondelete="RESTRICT"), index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    current_snapshot_id: Mapped[str | None] = mapped_column(String(36))
    current_draft_plan_id: Mapped[str | None] = mapped_column(String(36))
    current_confirmation_id: Mapped[str | None] = mapped_column(String(36))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PlanningPresetRecord(Base, TimestampMixin):
    __tablename__ = 'planning_presets'
    project_id: Mapped[str] = mapped_column(ForeignKey('projects.id', ondelete='CASCADE'), primary_key=True)
    snapshot_id: Mapped[str] = mapped_column(String(36), nullable=False)
    base_group_id: Mapped[str] = mapped_column(String(64), nullable=False)
    exception_ids_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)


class Asset(Base, TimestampMixin):
    __tablename__ = "assets"
    sha256: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    relative_path: Mapped[str] = mapped_column(Text, nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)


class ProjectAsset(Base):
    __tablename__ = "project_assets"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    asset_hash: Mapped[str] = mapped_column(ForeignKey("assets.sha256", ondelete="RESTRICT"), index=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    original_name: Mapped[str] = mapped_column(Text, nullable=False)
    original_path: Mapped[str] = mapped_column(Text, nullable=False)
    project_revision: Mapped[int] = mapped_column(Integer, nullable=False)


class AssetRef(Base):
    __tablename__ = "asset_refs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    asset_hash: Mapped[str] = mapped_column(ForeignKey("assets.sha256", ondelete="CASCADE"), index=True)
    owner_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    owner_id: Mapped[str] = mapped_column(String(64), nullable=False)
    __table_args__ = (UniqueConstraint("asset_hash", "owner_kind", "owner_id", name="uq_asset_ref"),)


class ImportSnapshotRecord(Base):
    __tablename__ = "import_snapshots"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    project_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    assembly_asset_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    scene_ready: Mapped[bool] = mapped_column(Boolean, default=False)
    groups_ready: Mapped[bool] = mapped_column(Boolean, default=False)
    calculation_ready: Mapped[bool] = mapped_column(Boolean, default=False)
    diagnostics_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class GroupingStructureRecord(Base):
    __tablename__ = "grouping_structures"
    snapshot_id: Mapped[str] = mapped_column(ForeignKey("import_snapshots.id", ondelete="CASCADE"), primary_key=True)
    source_snapshot_id: Mapped[str] = mapped_column(String(36), nullable=False)
    roots_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ShapeDefinition(Base):
    __tablename__ = "shape_definitions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    asset_hash: Mapped[str] = mapped_column(ForeignKey("assets.sha256", ondelete="RESTRICT"), index=True)
    local_shape_key: Mapped[str] = mapped_column(String(255), nullable=False)
    brep_relative_path: Mapped[str | None] = mapped_column(Text)
    validity: Mapped[str] = mapped_column(String(32), nullable=False)
    __table_args__ = (UniqueConstraint("asset_hash", "local_shape_key", name="uq_shape_asset_key"),)


class Occurrence(Base):
    __tablename__ = "occurrences"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    snapshot_id: Mapped[str] = mapped_column(ForeignKey("import_snapshots.id", ondelete="CASCADE"), index=True)
    shape_definition_id: Mapped[str] = mapped_column(ForeignKey("shape_definitions.id", ondelete="RESTRICT"))
    parent_id: Mapped[str | None] = mapped_column(String(64))
    assembly_path: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    world_transform_json: Mapped[list[float]] = mapped_column(JSON, nullable=False)
    color_json: Mapped[list[float] | None] = mapped_column(JSON)


class AtomicBodyRecord(Base):
    __tablename__ = "atomic_bodies"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    snapshot_id: Mapped[str] = mapped_column(ForeignKey("import_snapshots.id", ondelete="CASCADE"), index=True)
    occurrence_id: Mapped[str] = mapped_column(String(64), nullable=False)
    solid_index: Mapped[int] = mapped_column(Integer, nullable=False)
    source_relative_path: Mapped[str] = mapped_column(Text, nullable=False)
    bounds_json: Mapped[dict[str, float]] = mapped_column(JSON, nullable=False)
    volume_mm3: Mapped[float | None] = mapped_column(Float)
    area_mm2: Mapped[float | None] = mapped_column(Float)
    centroid_json: Mapped[list[float] | None] = mapped_column(JSON)
    geometry_valid: Mapped[bool] = mapped_column(Boolean, nullable=False)
    unit: Mapped[str] = mapped_column(String(16), nullable=False)


class PartDefinition(Base):
    __tablename__ = "part_definitions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    asset_hash: Mapped[str] = mapped_column(ForeignKey("assets.sha256", ondelete="RESTRICT"), index=True)
    original_name: Mapped[str] = mapped_column(Text, nullable=False)
    part_type: Mapped[str] = mapped_column(String(32), nullable=False)
    signature_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class AssemblyGroupRecord(Base):
    __tablename__ = "assembly_groups"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    snapshot_id: Mapped[str] = mapped_column(ForeignKey("import_snapshots.id", ondelete="CASCADE"), index=True)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    part_type: Mapped[str] = mapped_column(String(32), nullable=False)
    part_definition_id: Mapped[str | None] = mapped_column(String(64))
    matching_status: Mapped[str] = mapped_column(String(32), nullable=False)
    bounds_json: Mapped[dict[str, float]] = mapped_column(JSON, nullable=False)
    volume_mm3: Mapped[float | None] = mapped_column(Float)
    centroid_json: Mapped[list[float] | None] = mapped_column(JSON)
    geometry_valid: Mapped[bool] = mapped_column(Boolean, nullable=False)


class GroupMember(Base):
    __tablename__ = "group_members"
    group_id: Mapped[str] = mapped_column(ForeignKey("assembly_groups.id", ondelete="CASCADE"), primary_key=True)
    body_id: Mapped[str] = mapped_column(ForeignKey("atomic_bodies.id", ondelete="CASCADE"), primary_key=True)


class StaticFeature(Base):
    __tablename__ = "static_features"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    snapshot_id: Mapped[str] = mapped_column(String(36), index=True)
    group_id: Mapped[str] = mapped_column(String(64), index=True)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    values_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    missing_json: Mapped[dict[str, bool]] = mapped_column(JSON, nullable=False)


class ContactRecord(Base):
    __tablename__ = "contacts"
    pair_id: Mapped[str] = mapped_column(String(140), primary_key=True)
    snapshot_id: Mapped[str] = mapped_column(String(36), index=True)
    group_a: Mapped[str] = mapped_column(String(64), index=True)
    group_b: Mapped[str] = mapped_column(String(64), index=True)
    distance_mm: Mapped[float | None] = mapped_column(Float)
    evidence_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    policy_version: Mapped[str] = mapped_column(String(32), nullable=False)


class JobRecord(Base, TimestampMixin):
    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    input_snapshot_id: Mapped[str | None] = mapped_column(String(36))
    settings_version: Mapped[str] = mapped_column(String(64), nullable=False)
    project_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cancel_token: Mapped[str] = mapped_column(String(36), nullable=False)
    result_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_detail: Mapped[str | None] = mapped_column(Text)


class JobEvent(Base):
    __tablename__ = "job_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    stage: Mapped[str] = mapped_column(String(64), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    details_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class PlanRecord(Base, TimestampMixin):
    __tablename__ = "plans"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    base_group_id: Mapped[str] = mapped_column(String(64), nullable=False)
    group_ids_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(48), nullable=False)
    source_algorithm: Mapped[str] = mapped_column(String(32), nullable=False)
    user_modified: Mapped[bool] = mapped_column(Boolean, nullable=False)
    input_snapshot_id: Mapped[str] = mapped_column(String(36), nullable=False)
    settings_version: Mapped[str] = mapped_column(String(64), nullable=False)
    preview_version: Mapped[int] = mapped_column(Integer, default=0)


class PlanPresentationRecord(Base):
    """Additive table: legacy plans/steps are not rewritten on database open."""
    __tablename__ = "plan_presentations"
    plan_id: Mapped[str] = mapped_column(ForeignKey("plans.id", ondelete="CASCADE"), primary_key=True)
    camera_rolls_json: Mapped[dict[str, int]] = mapped_column(JSON, default=dict)


class PlanStepRecord(Base):
    __tablename__ = "plan_steps"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    plan_id: Mapped[str] = mapped_column(ForeignKey("plans.id", ondelete="CASCADE"), index=True)
    step_index: Mapped[int] = mapped_column(Integer, nullable=False)
    group_id: Mapped[str] = mapped_column(String(64), nullable=False)
    removal_direction_json: Mapped[list[float]] = mapped_column(JSON, nullable=False)
    assembly_direction_json: Mapped[list[float]] = mapped_column(JSON, nullable=False)
    travel_mm: Mapped[float] = mapped_column(Float, nullable=False)
    camera_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    process_text: Mapped[str] = mapped_column(Text, default="")
    material_text: Mapped[str] = mapped_column(Text, default="")
    caution_text: Mapped[str] = mapped_column(Text, default="")
    geometry_status: Mapped[str] = mapped_column(String(48), nullable=False)
    source_run_id: Mapped[str] = mapped_column(String(36), nullable=False)
    final_transform_json: Mapped[list[float]] = mapped_column(JSON, nullable=False)


class GenerationRecord(Base):
    """Append-only original generation, including original statuses and diagnostics."""
    __tablename__ = 'plan_generations'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey('projects.id', ondelete='CASCADE'), index=True)
    plan_id: Mapped[str] = mapped_column(ForeignKey('plans.id', ondelete='CASCADE'), unique=True)
    snapshot_id: Mapped[str] = mapped_column(String(36), index=True)
    generation_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    plan_snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    metrics_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    path_results_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    settings_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ConfirmationAnalysis(Base):
    __tablename__ = 'confirmation_analyses'
    confirmation_id: Mapped[str] = mapped_column(ForeignKey('confirmations.id', ondelete='CASCADE'), primary_key=True)
    generation_id: Mapped[str | None] = mapped_column(ForeignKey('plan_generations.id', ondelete='SET NULL'))
    metrics_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LearningObservation(Base):
    """No extra CAD: final preferences and scoped, original physical evidence."""
    __tablename__ = 'learning_observations'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    confirmation_id: Mapped[str] = mapped_column(ForeignKey('confirmations.id', ondelete='CASCADE'), index=True)
    family_id: Mapped[str] = mapped_column(String(64), index=True)
    signature: Mapped[str] = mapped_column(String(64), unique=True)
    product_type: Mapped[str] = mapped_column(String(255), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ConfirmationRecord(Base):
    __tablename__ = "confirmations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    plan_id: Mapped[str] = mapped_column(ForeignKey("plans.id", ondelete="RESTRICT"), index=True)
    plan_snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TrainingCase(Base):
    __tablename__ = "training_cases"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    family_id: Mapped[str] = mapped_column(String(64), index=True)
    confirmation_id: Mapped[str] = mapped_column(String(36), index=True)
    input_signature: Mapped[str] = mapped_column(String(64), index=True)
    source_algorithm: Mapped[str] = mapped_column(String(32), nullable=False)
    user_changed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RankingState(Base):
    __tablename__ = "ranking_states"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("training_cases.id", ondelete="CASCADE"), index=True)
    state_index: Mapped[int] = mapped_column(Integer, nullable=False)
    remaining_ids_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    group_size: Mapped[int] = mapped_column(Integer, nullable=False)


class RankingCandidate(Base):
    __tablename__ = "ranking_candidates"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    state_id: Mapped[str] = mapped_column(ForeignKey("ranking_states.id", ondelete="CASCADE"), index=True)
    group_id: Mapped[str] = mapped_column(String(64), nullable=False)
    features_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    relevance: Mapped[int] = mapped_column(Integer, nullable=False)
    geometry_status: Mapped[str] = mapped_column(String(32), nullable=False)


class ModelBundle(Base):
    __tablename__ = "model_bundles"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    relative_path: Mapped[str] = mapped_column(Text, nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    manifest_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    compatible: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Evaluation(Base):
    __tablename__ = "evaluations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    model_bundle_id: Mapped[str] = mapped_column(String(36), index=True)
    evaluation_set_version: Mapped[str] = mapped_column(String(64), nullable=False)
    metrics_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ActiveModel(Base):
    __tablename__ = "active_model"
    slot: Mapped[str] = mapped_column(String(32), primary_key=True, default="ranking")
    model_bundle_id: Mapped[str | None] = mapped_column(String(36))
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fallback_reason: Mapped[str | None] = mapped_column(Text)


class LearningProgress(Base):
    __tablename__ = 'learning_progress'
    key: Mapped[str] = mapped_column(String(64),primary_key=True)
    baseline_json: Mapped[dict[str,Any]] = mapped_column(JSON,default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),default=utcnow)


class LearningCycle(Base):
    """One immutable data snapshot shared by sequential ranking/direction fits."""
    __tablename__ = 'learning_cycles'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    phase: Mapped[str] = mapped_column(String(64), nullable=False)
    snapshot_path: Mapped[str] = mapped_column(Text, nullable=False)
    counts_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    settings_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    baseline_models_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    result_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error_detail: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ModelActivation(Base):
    """Append-only atomic pair activation/rollback audit trail."""
    __tablename__ = 'model_activations'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    cycle_id: Mapped[str | None] = mapped_column(String(36))
    previous_models_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    active_models_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CacheEntry(Base):
    __tablename__ = "cache_entries"
    stage: Mapped[str] = mapped_column(String(32), primary_key=True)
    cache_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    relative_path: Mapped[str] = mapped_column(Text, nullable=False)
    manifest_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    complete: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SettingsVersion(Base):
    __tablename__ = "settings_versions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    settings_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class VideoRecord(Base):
    __tablename__ = "videos"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    confirmation_id: Mapped[str] = mapped_column(ForeignKey("confirmations.id", ondelete="RESTRICT"), index=True)
    template_version: Mapped[str] = mapped_column(String(32), nullable=False)
    relative_path: Mapped[str] = mapped_column(Text, nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    fps: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_sec: Mapped[float] = mapped_column(Float, nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Database:
    """SQLAlchemy storage. SQLite is the development fallback; packaged builds use PA2_DATABASE_URL for MariaDB."""

    def __init__(self, layout: DataLayout, url: str | None = None) -> None:
        self.layout = layout
        layout.ensure()
        database_url = url or os.environ.get("PA2_DATABASE_URL")
        if not database_url:
            database_url = f"sqlite:///{(layout.database / 'pa2-dev.sqlite3').as_posix()}"
        options: dict[str, Any] = {"future": True, "pool_pre_ping": True}
        if database_url.startswith("sqlite"):
            options["connect_args"] = {"check_same_thread": False}
        self.engine: Engine = create_engine(database_url, **options)

    def initialize(self) -> None:
        Base.metadata.create_all(self.engine)
        with self.session() as session:
            for role in ('ranking', 'direction'):
                if session.get(ActiveModel, role) is None:
                    session.add(ActiveModel(slot=role, model_bundle_id=None, fallback_reason="학습 데이터 부족: 기존 규칙 사용"))

    @contextmanager
    def session(self) -> Iterator[Session]:
        with Session(self.engine, expire_on_commit=False) as session:
            try:
                yield session
                session.commit()
            except BaseException:
                session.rollback()
                raise

    def mark_interrupted_jobs(self) -> int:
        with self.session() as session:
            rows = list(session.scalars(select(JobRecord).where(JobRecord.status.in_(["RUNNING", "CANCELLING"]))))
            for row in rows:
                row.status = "FAILED"
                row.error_code = "INTERRUPTED"
                row.error_detail = "이전 실행이 정상 종료되지 않았습니다."
            return len(rows)

    @staticmethod
    def new_id() -> str:
        return str(uuid.uuid4())

