"""Collect preferences and existing evidence without initiating CAD operations."""
from __future__ import annotations

import hashlib
import json
import uuid
import math
from dataclasses import asdict

from pa2.domain.models import GeometryStatus
from pa2.planning.priority import is_fastener
from pa2.storage.database import LearningObservation, RankingState, TrainingCase
from .ranker import LearningService


def family_fingerprint(snapshot):
    """Cheap geometric duplicate key; names, STEP metadata and grouping excluded.

    This is conservative duplicate suppression, not a learned product taxonomy.
    """
    bodies = getattr(snapshot, 'atomic_bodies', None) or snapshot.groups
    features = sorted((round(b.volume_mm3 or 0., 3),
                       tuple(sorted(round(x, 3) for x in b.bounds.size))) for b in bodies)
    centers = [b.centroid or b.bounds.center for b in bodies]
    distances = sorted(round(math.dist(a,b),3) for i,a in enumerate(centers) for b in centers[i+1:])
    return hashlib.sha256(json.dumps(dict(features=features,distances=distances),sort_keys=True).encode()).hexdigest()


def collect_confirmation(database, plans, confirmation_id, imported, product_type):
    plan = plans.load_confirmation(confirmation_id)
    snapshot = imported.snapshot
    if plan.input_snapshot_id != snapshot.id:
        raise ValueError('확정본과 부품 스냅샷이 다릅니다.')
    generation = plans.generation(plan.id)
    family_id = family_fingerprint(snapshot)
    exceptions = {s.group_id for s in plan.steps if s.geometry_status == GeometryStatus.USER_COLLISION_EXCEPTION}
    if generation:
        exceptions.update(generation.metrics_json.get('collision_exception_ids', []))
    comparison = plans.analyze_confirmation(confirmation_id, snapshot.groups, exceptions)
    original = plans.load_original(plan.id)
    old = {s.group_id: s for s in original.steps} if original else {}
    # Scope every physical label to its original remaining-state and direction.
    # An UNKNOWN is NOT a failure; a final user direction is NOT a geometry PASS.
    evidence = generation.path_results_json if generation else []
    outcomes = []
    for item in evidence:
        e = item.get('evidence', {})
        decision = item.get('decision')
        allowed = (decision in ('PASS', 'BLOCKED') and item.get('group_id') not in exceptions
                   and not e.get('path_check_skipped') and not e.get('user_collision_exception'))
        outcomes.append(dict(group_id=item.get('group_id'), state_key=item.get('state_key'),
            direction=item.get('direction'), travel_mm=item.get('travel_mm'),
            decision=decision, physical_label=decision if allowed else None,
            reason_code=item.get('reason_code'), policy_version=item.get('policy_version')))
    groups = {g.id: g for g in snapshot.groups}
    steps = []
    assembled = [plan.base_group_id]
    for step in plan.steps:
        steps.append(dict(group_id=step.group_id, assembly_index=step.step_index,
            removal_direction=step.removal_direction, assembly_direction=step.assembly_direction,
            remaining_before_removal=list(assembled)+[step.group_id],
            is_fastener=is_fastener(groups[step.group_id]), is_exception=step.group_id in exceptions,
            geometry_status=step.geometry_status.value,
            original_status=old[step.group_id].geometry_status.value if step.group_id in old else None,
            original_direction=old[step.group_id].removal_direction if step.group_id in old else None,
            preference_label=True, confirmed_geometry_pass=False))
        assembled.append(step.group_id)
    payload = dict(schema_version='observations-v20', snapshot_id=snapshot.id,
        assembly_asset_hash=snapshot.assembly_asset_hash, base_group_id=plan.base_group_id,
        source_algorithm=plan.source_algorithm,
        generation_mode='manual' if plan.source_algorithm.startswith('manual-') else 'auto',
        exception_ids=sorted(exceptions), groups=[asdict(g) for g in snapshot.groups],
        contacts=[asdict(e) for e in snapshot.contacts], steps=steps, physical_evidence=outcomes,
        generation_metrics=generation.metrics_json if generation else {}, comparison=comparison)
    # Exact repeated confirmations do not inflate the data count. Cosmetic text
    # and camera edits are deliberately not new sequence/direction examples.
    canonical = dict(project_id=plan.project_id,family=family_id, base=plan.base_group_id,
        groups=[dict(id=g.id, bodies=sorted(g.body_ids)) for g in snapshot.groups],
        order=[dict(id=s.group_id, direction=s.removal_direction, exception=s.group_id in exceptions) for s in plan.steps])
    signature = hashlib.sha256(json.dumps(canonical, sort_keys=True).encode()).hexdigest()
    with database.session() as session:
        existing = session.query(LearningObservation).filter_by(signature=signature).first()
        if existing:
            observation_id = existing.id
        else:
            observation_id = str(uuid.uuid4())
            session.add(LearningObservation(id=observation_id, confirmation_id=confirmation_id,
                family_id=family_id, signature=signature,
                product_type=product_type, payload_json=payload))
    complete = {s.group_id for s in plan.steps} == set(plan.group_ids)-{plan.base_group_id}
    if complete:
        LearningService().capture(database, confirmation_id=confirmation_id,
            family_id=family_id, plan=plan, groups=snapshot.groups,
            contacts=snapshot.contacts, product_type=product_type)
    return dict(observation_id=observation_id, comparison=comparison, ranking_captured=complete)


def learning_status(database, settings):
    with database.session() as session:
        families = session.query(TrainingCase.family_id).distinct().count()
        cases = session.query(TrainingCase).count()
        states = session.query(RankingState).count()
        observations = session.query(LearningObservation).count()
    ready, reason = LearningService.training_ready(families, states,
        settings.training_min_families, settings.training_min_states)
    from .data import recorded_snapshot
    from .pipeline import due
    from pa2.storage.database import LearningProgress
    snapshot=recorded_snapshot(database);qualified=snapshot['counts']
    with database.session() as session:progress=session.get(LearningProgress,'common')
    common_ready,common_reason=due(snapshot,progress.baseline_json if progress else None,None,settings)
    return dict(family_count=families, case_count=cases, state_count=states,
        observation_count=observations, ready=ready, reason=reason,
        qualified=qualified, common_ready=common_ready, common_reason=common_reason,
        note='기본 형상 특징·바디 간 거리로 중복 계열을 억제합니다. 제품 변형의 완전한 계열 분류는 아니며, 학습 가능은 자동 적용을 뜻하지 않습니다.')
