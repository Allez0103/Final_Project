"""Immediate editable assembly draft. Never runs a native path/contact search."""
from __future__ import annotations

import time
import uuid

from pa2.cad.direction_policy import _fastener_hint
from pa2.cad.path_check import exit_distance, state_key
from pa2.cad.shapes import compound
from pa2.domain.models import (Bounds, GeometryDecision, GeometryStatus, PartType,
    PathCheckResult, Plan, PlanningResult, PlanningStatus, PlanStep, normalize)
from .attachments import fastener_attachments
from .fastener_direction import assigned_direction
from .priority import is_fastener


def fastener_hints(groups, shapes, epsilon, cancel_check=lambda: False):
    """Read analytic faces only; no worker serialization, BREP Common or distance."""
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopExp import TopExp_Explorer
    from types import SimpleNamespace
    dispatcher = SimpleNamespace(activity=lambda *_: None)
    hints = {}
    for group in groups:
        if cancel_check():
            raise InterruptedError('수동생성을 취소했습니다.')
        if not is_fastener(group):
            continue
        faces = []
        explorer = TopExp_Explorer(compound([shapes[b] for b in group.body_ids]), TopAbs_FACE)
        while explorer.More():
            faces.append((None, explorer.Current()))
            explorer.Next()
        try:
            hints[group.id] = _fastener_hint(dispatcher, group.id, faces, epsilon, group.part_type.value)
        except Exception as exc:
            hints[group.id] = {'method': 'axis_hint_failed', 'error': str(exc)}
    return hints


class ManualPlanner:
    VERSION = 'manual-v20-list-order'

    def __init__(self, settings):
        self.settings = settings

    def generate(self, project_id, project_revision, snapshot_id, groups, contacts,
                 shapes_by_body, base_group_id, *, display_order=None,
                 collision_exception_ids=(), default_direction=(0, 0, 1),
                 cancel_check=lambda: False, progress=lambda *_: None):
        started = time.perf_counter()
        mapping = {g.id: g for g in groups}
        if base_group_id not in mapping:
            raise ValueError('기준 부품을 선택하세요.')
        exceptions = set(collision_exception_ids)
        if exceptions-set(mapping) or base_group_id in exceptions:
            raise ValueError('예외 부품 설정을 확인하세요.')
        order = list(display_order) if display_order is not None else [g.id for g in groups]
        if len(order) != len(set(order)) or set(order) != set(mapping):
            raise ValueError('현재 부품 목록과 모델 구성이 다릅니다.')
        direction = normalize(default_direction)
        general = [gid for gid in order if gid != base_group_id and not is_fastener(mapping[gid])]
        positions = {gid: i for i, gid in enumerate(general)}
        attachments = fastener_attachments(mapping, contacts, base_group_id)
        # Assembly order: shared fasteners follow the LAST related general part.
        owners = {gid: max((t for t in relation['targets'] if t in positions),
                          key=positions.get, default=base_group_id)
                  for gid, relation in attachments.items()}
        resolved = self.settings.resolved_for_diagonal(Bounds.union(g.bounds for g in groups).diagonal)
        progress('manual', '일반 부품 목록 배치 · 볼트/너트 축·머리 방향 계산')
        hint_started = time.perf_counter()
        hints = fastener_hints(groups, shapes_by_body, resolved['geometry_epsilon_mm'], cancel_check)
        hint_elapsed = time.perf_counter()-hint_started
        ids = [f for f in order if owners.get(f) == base_group_id]
        for gid in general:
            ids.append(gid)
            ids.extend(f for f in order if owners.get(f) == gid)
        run_id = str(uuid.uuid4())
        steps = []
        records = []
        for gid in ids:
            if cancel_check():
                raise InterruptedError('수동생성을 취소했습니다.')
            group = mapping[gid]
            d, method, linked = direction, 'manual_default_plus_z', None
            target = owners.get(gid)
            if target is not None:
                neighbors = {e.group_b if e.group_a == gid else e.group_a
                             for e in contacts if gid in (e.group_a, e.group_b)}
                bolts = [(mapping[n], hints.get(n, {})) for n in sorted(neighbors)
                         if mapping[n].part_type == PartType.BOLT]
                d, method, linked = assigned_direction(group, mapping[target], hints.get(gid, {}), bolts)
            travel = exit_distance(group.bounds, [g.bounds for g in groups if g.id != gid],
                                   d, resolved['exit_clearance_mm'])
            status = (GeometryStatus.USER_COLLISION_EXCEPTION if gid in exceptions else
                      GeometryStatus.FASTENER_ASSIGNED if target is not None else GeometryStatus.MANUAL_ASSIGNED)
            steps.append(PlanStep(gid, len(steps)+1, d, tuple(-v for v in d), travel,
                process_text=f'{group.display_name} 조립', material_text=group.display_name,
                geometry_status=status, source_run_id=run_id))
            records.append(PathCheckResult(gid, state_key(set(mapping)), d, travel,
                GeometryDecision.NOT_TESTED, status.value, policy_version=self.VERSION,
                evidence={'evaluation_source': 'manual_assignment', 'path_check_skipped': True,
                          'direction_method': method, 'target_group_id': target, 'linked_bolt_id': linked}))
        plan = Plan(str(uuid.uuid4()), project_id, 1, base_group_id, list(order), steps,
                    PlanningStatus.REVIEW_REQUIRED, source_algorithm=self.VERSION,
                    input_snapshot_id=snapshot_id, settings_version=self.settings.version)
        plan.validate()
        metrics = dict(elapsed_sec=time.perf_counter()-started, tested_candidates=0,
            native_path_calls=0, actual_native_path_calls=0, brep_common_calls=0,
            completed_groups=len(steps), total_moving_groups=len(groups)-1,
            verified_path_steps=0, fastener_assigned_steps=len(attachments),
            collision_exception_steps=len(exceptions), collision_exception_ids=sorted(exceptions),
            unresolved_general_steps=0, unresolved_general_ids=[], draft_complete=True, path_complete=False,
            generation_mode='manual', direction_hint_calls=len(hints),
            direction_hint_elapsed_sec=hint_elapsed,
            direction_hints=[dict(group_id=gid, **hint) for gid, hint in hints.items()],
            fastener_attachments=attachments, general_assembly_order=general,
            contact_graph_reused=True, default_removal_direction=direction)
        return PlanningResult(plan.status, list(reversed(ids)), plan, records,
            '수동 편집용 전체 초안 · 일반 부품 목록 순서/+Z 분해 기본값 · 간섭 검사 생략', metrics)
