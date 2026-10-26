from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

from sqlalchemy import select

from pa2.cad.brep_cache import load_scene, save_scene
from pa2.cad.contacts import ContactService
from pa2.cad.grouping import GroupingResult, GroupingService
from pa2.cad.importer import CadScene, StepImporter
from pa2.domain.models import AssemblyGroup, AtomicBody, Bounds, ContactEdge, ImportSnapshot, MatchingStatus, PartType
from pa2.domain.classification import classify_part
from pa2.settings.config import AppSettings
from pa2.storage.assets import AssetStore, ManagedAsset
from pa2.storage.cache import CacheStore, cache_key
from pa2.storage.database import (
    Asset,
    AssemblyGroupRecord,
    AtomicBodyRecord,
    ContactRecord,
    Database,
    GroupMember,
    ImportSnapshotRecord,
    PartDefinition,
    Project,
    ProjectAsset,
)


Progress = Callable[[str, str], None]


@dataclass(slots=True)
class ImportResult:
    snapshot: ImportSnapshot
    assembly_scene: CadScene
    part_scenes: list[CadScene]
    grouping: GroupingResult
    cache_hits: int
    cache_misses: int
    elapsed_sec: float
    grouping_structure: dict | None = None


class ImportService:
    def __init__(self, database: Database, assets: AssetStore, cache: CacheStore) -> None:
        self.database = database
        self.assets = assets
        self.cache = cache
        self.importer = StepImporter()

    def prepare(
        self,
        project_id: str,
        assembly_path: Path,
        part_paths: list[Path],
        settings: AppSettings,
        *,
        assumed_unit: str | None = None,
        progress: Progress | None = None,
        cancel_check=lambda: False,
    ) -> ImportResult:
        started = time.perf_counter()
        deadline = time.monotonic() + settings.import_timeout_sec
        callback = progress or (lambda _stage, _message: None)
        settings.validate()
        assembly_asset = self.assets.ingest(assembly_path, "assembly_step")
        part_assets = [self.assets.ingest(path, "part_step") for path in part_paths]
        hits = misses = 0

        def scene_for(asset: ManagedAsset) -> CadScene:
            nonlocal hits, misses
            key = cache_key("shape", [asset.sha256], StepImporter.VERSION, {"unit": assumed_unit or "file"})
            cached = self.cache.get("shape", key)
            managed_source = self.assets.resolve(asset.relative_path)
            if cached is not None:
                try:
                    scene = load_scene(cached, managed_source)
                    scene.original_name = asset.original_name
                    hits += 1
                    callback("cache", f"캐시에서 복원: {asset.original_name}")
                    return scene
                except Exception:
                    callback("cache", f"손상된 캐시 무시: {asset.original_name}")
            misses += 1
            scene = self.importer.read(managed_source, asset.sha256, asset.relative_path, assumed_unit=assumed_unit, progress=callback)
            scene.original_name = asset.original_name
            with self.cache.publisher("shape", key) as directory:
                if not (directory / "complete.json").exists():
                    save_scene(scene, directory)
            return scene

        assembly_scene = scene_for(assembly_asset)
        part_scenes = [scene_for(asset) for asset in part_assets]
        callback("matching", "개별 부품과 완제품 바디를 대응하는 중")
        resolved = settings.resolved_for_diagonal(assembly_scene.bounds.diagonal)
        grouping_service = GroupingService(settings.volume_relative_tolerance, resolved["geometry_epsilon_mm"])
        grouping = grouping_service.resolve(assembly_scene, part_scenes)
        callback("features", "초기 접촉 관계를 계산하는 중")
        contact_result = ContactService(settings.contact_gap_mm, settings.native_operation_timeout_sec).build(
            grouping.groups, assembly_scene.bodies, assembly_scene, cancel_check=cancel_check,
            progress=callback, deadline=deadline, jobs_dir=self.cache.layout.jobs)
        snapshot = ImportSnapshot(
            id=str(uuid.uuid4()), project_id=project_id, project_revision=0,
            assembly_asset_hash=assembly_asset.sha256, atomic_bodies=assembly_scene.bodies,
            groups=grouping.groups, contacts=contact_result.edges, scene_ready=True, groups_ready=True,
            calculation_ready=any(group.geometry_valid for group in grouping.groups) and contact_result.complete,
            diagnostics=[
                {"code": "CACHE_STATS", "hits": hits, "misses": misses},
                {"code": "UNMATCHED_BODIES", "body_ids": grouping.unresolved_body_ids},
                {"code": "AMBIGUOUS_MATCHES", "items": grouping.ambiguous},
                {"code": "GROUPING_FALLBACK_MATCHES", "items": grouping.fallback_matches},
                {"code": "GROUPING_ROTATION_MATCHES", "items": grouping.rotation_matches},
                {"code": "GROUPING_ANCHOR_MATCHES", "items": grouping.anchor_matches},
                {"code": "GROUPING_RELAXED_MATCHES", "items": grouping.relaxed_matches},
                {"code": "NON_SOLID_COUNT", "count": assembly_scene.non_solid_count},
                {"code": "CONTACT_GRAPH", "version": ContactService.VERSION, "gap_mm": settings.contact_gap_mm,
                 "complete": contact_result.complete, "candidate_count": contact_result.candidate_count,
                 "unknown_pairs": contact_result.unknown_pairs, "failures": contact_result.failures},
            ],
        )
        self._persist(project_id, snapshot, assembly_asset, part_assets, grouping)
        return ImportResult(snapshot, assembly_scene, part_scenes, grouping, hits, misses, time.perf_counter()-started)

    def ensure_contacts(self, result: ImportResult, settings: AppSettings, *, progress=None, cancel_check=lambda: False) -> ImportResult:
        """Upgrade old/incomplete snapshots in place; preserve plans and confirmations."""
        graph = next((item for item in result.snapshot.diagnostics if item.get("code") == "CONTACT_GRAPH"), {})
        if (result.snapshot.calculation_ready and graph.get("version") == ContactService.VERSION
                and graph.get("gap_mm") == settings.contact_gap_mm):
            return result
        contacts = ContactService(settings.contact_gap_mm, settings.native_operation_timeout_sec).build(
            result.snapshot.groups, result.snapshot.atomic_bodies, result.assembly_scene,
            progress=progress or (lambda *_: None), cancel_check=cancel_check,
            deadline=time.monotonic()+settings.import_timeout_sec, jobs_dir=self.cache.layout.jobs)
        if cancel_check():
            raise InterruptedError("접촉 계산을 취소했습니다.")
        snapshot = result.snapshot
        diagnostics = [item for item in snapshot.diagnostics if item.get("code") != "CONTACT_GRAPH"]
        diagnostics.append({"code": "CONTACT_GRAPH", "version": ContactService.VERSION,
                            "gap_mm": settings.contact_gap_mm, "complete": contacts.complete,
                            "candidate_count": contacts.candidate_count, "unknown_pairs": contacts.unknown_pairs,
                            "failures": contacts.failures})
        ready = contacts.complete and any(group.geometry_valid for group in snapshot.groups)
        with self.database.session() as session:
            record = session.get(ImportSnapshotRecord, snapshot.id)
            if record is None:
                raise KeyError("현재 분석 스냅샷을 찾을 수 없습니다.")
            session.query(ContactRecord).filter_by(snapshot_id=snapshot.id).delete()
            for edge in contacts.edges:
                session.add(ContactRecord(pair_id=f"{snapshot.id}:{edge.pair_id}", snapshot_id=snapshot.id,
                    group_a=edge.group_a, group_b=edge.group_b, distance_mm=edge.distance_mm,
                    evidence_json=edge.evidence, policy_version=edge.policy_version))
            record.calculation_ready = ready
            record.diagnostics_json = diagnostics
        snapshot.contacts, snapshot.calculation_ready, snapshot.diagnostics = contacts.edges, ready, diagnostics
        return result

    def reopen(self, project_id: str) -> ImportResult:
        """Restore the current immutable snapshot without re-reading external STEP files."""
        with self.database.session() as session:
            project = session.get(Project, project_id)
            if project is None or project.deleted_at is not None or not project.current_snapshot_id:
                raise KeyError("재열기 가능한 현재 스냅샷이 없습니다.")
            snapshot_row = session.get(ImportSnapshotRecord, project.current_snapshot_id)
            if snapshot_row is None:
                raise KeyError("현재 스냅샷 레코드를 찾을 수 없습니다.")
            asset = session.get(Asset, snapshot_row.assembly_asset_hash)
            if asset is None:
                raise KeyError("관리 영역의 완제품 자산을 찾을 수 없습니다.")
            body_rows = list(session.scalars(select(AtomicBodyRecord).where(AtomicBodyRecord.snapshot_id == snapshot_row.id)))
            group_rows = list(session.scalars(select(AssemblyGroupRecord).where(AssemblyGroupRecord.snapshot_id == snapshot_row.id)))
            members = list(session.scalars(select(GroupMember).where(GroupMember.group_id.like(f"{snapshot_row.id}:%"))))
            contact_rows = list(session.scalars(select(ContactRecord).where(ContactRecord.snapshot_id == snapshot_row.id)))
            part_assets = list(session.scalars(select(ProjectAsset).where(
                ProjectAsset.project_id == project_id, ProjectAsset.role == "part",
                ProjectAsset.project_revision == snapshot_row.project_revision)))
            original_names = {f"partdef-{item.asset_hash[:16]}": item.original_name for item in part_assets}
            for row in group_rows:
                original = original_names.get(row.part_definition_id)
                if original and row.display_name.startswith("source"):
                    repeated = sum(item.part_definition_id == row.part_definition_id for item in group_rows) > 1
                    suffix = f" #{int(row.id.rsplit('-',1)[-1])}" if repeated else ""
                    row.display_name = f"{Path(original).stem}{suffix}"
                    row.part_type = classify_part(original).value

        key = cache_key("shape", [snapshot_row.assembly_asset_hash], StepImporter.VERSION, {"unit": "file"})
        cached = self.cache.get("shape", key)
        rebuilt=cached is None
        if cached is None:
            # Rebuild a versioned cache from the immutable managed STEP, never
            # from the user's external original; preserve all older caches.
            managed_source=self.assets.resolve(asset.relative_path)
            assembly_scene=self.importer.read(managed_source,snapshot_row.assembly_asset_hash,asset.relative_path)
            expected={row.id.removeprefix(f"{snapshot_row.id}:") for row in body_rows}
            if set(assembly_scene.shapes)!=expected:
                raise ValueError("캐시 재생성 바디 ID가 기존 스냅샷과 달라 자동 교체하지 않습니다.")
            with self.cache.publisher("shape",key) as directory:
                if not (directory/"complete.json").exists():save_scene(assembly_scene,directory)
            cached=self.cache.get("shape",key)
        assembly_scene = load_scene(cached, self.assets.resolve(asset.relative_path))
        body_map: dict[str, AtomicBody] = {body.id: body for body in assembly_scene.bodies}
        member_map: dict[str, list[str]] = {}
        prefix = f"{snapshot_row.id}:"
        for member in members:
            group_id = member.group_id.removeprefix(prefix)
            body_id = member.body_id.removeprefix(prefix)
            member_map.setdefault(group_id, []).append(body_id)
        groups = [AssemblyGroup(
            id=row.id.removeprefix(prefix), display_name=row.display_name,
            body_ids=member_map.get(row.id.removeprefix(prefix), []), part_type=PartType(row.part_type),
            bounds=Bounds(**row.bounds_json), volume_mm3=row.volume_mm3,
            centroid=tuple(row.centroid_json) if row.centroid_json else None,
            geometry_valid=row.geometry_valid, matching_status=MatchingStatus(row.matching_status),
            part_definition_id=row.part_definition_id,
        ) for row in group_rows]
        contacts = [ContactEdge(
            group_a=row.group_a, group_b=row.group_b, distance_mm=row.distance_mm,
            evidence=row.evidence_json, policy_version=row.policy_version,
        ) for row in contact_rows]
        snapshot = ImportSnapshot(
            id=snapshot_row.id, project_id=project_id, project_revision=snapshot_row.project_revision,
            assembly_asset_hash=snapshot_row.assembly_asset_hash, atomic_bodies=list(body_map.values()),
            groups=groups, contacts=contacts, scene_ready=snapshot_row.scene_ready,
            groups_ready=snapshot_row.groups_ready, calculation_ready=snapshot_row.calculation_ready,
            diagnostics=snapshot_row.diagnostics_json,
        )
        unresolved = [body_id for group in groups if group.matching_status == MatchingStatus.UNMATCHED for body_id in group.body_ids]
        grouping = GroupingResult(groups=groups, definitions=[], unresolved_body_ids=unresolved)
        grouping.assert_partition(body_map)
        from .manual_grouping import ManualGroupingService
        structure=ManualGroupingService(self.database).structure(snapshot.id,groups)
        return ImportResult(snapshot, assembly_scene, [], grouping, cache_hits=int(not rebuilt), cache_misses=int(rebuilt), elapsed_sec=0.0,
                            grouping_structure=structure)

    def _persist(self, project_id: str, snapshot: ImportSnapshot, assembly_asset: ManagedAsset, part_assets: list[ManagedAsset], grouping: GroupingResult) -> None:
        body_map = {body.id: body for body in snapshot.atomic_bodies}
        with self.database.session() as session:
            project = session.get(Project, project_id)
            if project is None or project.deleted_at is not None:
                raise KeyError("프로젝트를 찾을 수 없습니다.")
            project.revision += 1
            snapshot.project_revision = project.revision
            assets = [assembly_asset, *part_assets]
            for asset in assets:
                if session.get(Asset, asset.sha256) is None:
                    session.add(Asset(sha256=asset.sha256, kind=asset.kind, relative_path=asset.relative_path, byte_size=asset.byte_size))
                session.add(ProjectAsset(
                    id=str(uuid.uuid4()), project_id=project_id, asset_hash=asset.sha256,
                    role="assembly" if asset is assembly_asset else "part", original_name=asset.original_name,
                    original_path=asset.original_path, project_revision=project.revision,
                ))
            session.add(ImportSnapshotRecord(
                id=snapshot.id, project_id=project_id, project_revision=project.revision,
                assembly_asset_hash=snapshot.assembly_asset_hash, scene_ready=snapshot.scene_ready,
                groups_ready=snapshot.groups_ready, calculation_ready=snapshot.calculation_ready,
                diagnostics_json=snapshot.diagnostics,
            ))
            for body in snapshot.atomic_bodies:
                session.add(AtomicBodyRecord(
                    id=f"{snapshot.id}:{body.id}", snapshot_id=snapshot.id, occurrence_id=body.occurrence_path,
                    solid_index=body.solid_index, source_relative_path=body.source_relative_path,
                    bounds_json=asdict(body.bounds), volume_mm3=body.volume_mm3, area_mm2=body.area_mm2,
                    centroid_json=list(body.centroid) if body.centroid else None,
                    geometry_valid=body.geometry_valid, unit=body.unit,
                ))
            for definition in grouping.definitions:
                if session.get(PartDefinition, definition.id) is None:
                    session.add(PartDefinition(
                        id=definition.id, asset_hash=definition.source_hash, original_name=definition.original_name,
                        part_type=definition.part_type.value,
                        signature_json={"solid_volumes": [body.volume_mm3 for body in definition.bodies]},
                    ))
            for group in snapshot.groups:
                session.add(AssemblyGroupRecord(
                    id=f"{snapshot.id}:{group.id}", snapshot_id=snapshot.id, display_name=group.display_name,
                    part_type=group.part_type.value, part_definition_id=group.part_definition_id,
                    matching_status=group.matching_status.value, bounds_json=asdict(group.bounds),
                    volume_mm3=group.volume_mm3, centroid_json=list(group.centroid) if group.centroid else None,
                    geometry_valid=group.geometry_valid,
                ))
                for body_id in group.body_ids:
                    session.add(GroupMember(group_id=f"{snapshot.id}:{group.id}", body_id=f"{snapshot.id}:{body_id}"))
            for edge in snapshot.contacts:
                session.add(ContactRecord(
                    pair_id=f"{snapshot.id}:{edge.pair_id}", snapshot_id=snapshot.id,
                    group_a=edge.group_a, group_b=edge.group_b, distance_mm=edge.distance_mm,
                    evidence_json=edge.evidence, policy_version=edge.policy_version,
                ))
            project.current_snapshot_id = snapshot.id

