"""Opt-in, checkpointed common cycle: ranking -> direction -> evaluation.

This module defines the later learning workflow. Importing it never fits a model,
validates learning, generates plans, or activates anything.
"""
from __future__ import annotations

import hashlib
import json
import math
import statistics
import time
import uuid
from collections import defaultdict,Counter
from dataclasses import asdict, replace
from datetime import UTC
from pathlib import Path

from pa2.settings.config import AppSettings
from pa2.storage.database import Evaluation, LearningCycle, LearningProgress, utcnow
from .data import (DIRECTION_SCHEMA, atomic_json, choice_groups, digest,
                   direction_readiness, recorded_snapshot, unpack)
from .features import FEATURE_SCHEMA_VERSION, PART_TYPES, FeatureBuilder
from .models import matrix
from .registry import ModelRegistry

TERMINAL = ('READY', 'APPLIED', 'REJECTED', 'FAILED', 'STALE')


class CyclePaused(Exception):
    pass


def utc(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def policy_signature(settings):
    """Do not resume an old cycle under new geometry/evaluation policy."""
    raw = asdict(settings)
    for key in ('auto_learning_enabled', 'auto_model_apply_enabled', 'learning_idle_sec',
                'learning_budget_sec', 'learning_memory_mb'):
        raw.pop(key, None)
    return digest(raw)


def due(snapshot, previous_snapshot, last_completed, settings):
    c = snapshot['counts']
    if previous_snapshot is not None and 'project_ids' in snapshot:
        added=set(snapshot['project_ids'])-set(previous_snapshot.get('project_ids',[]))
        return len(added)>=settings.retrain_new_projects, f'신규 확정 프로젝트 {len(added)}/{settings.retrain_new_projects}'
    if c['families'] < settings.training_min_families or c['states'] < settings.training_min_states:
        return False, '최초 학습 기준 미달'
    if last_completed is None:
        return True, '최초 공통 학습'
    if (utcnow()-utc(last_completed)).total_seconds() < settings.retrain_min_hours*3600:
        return False, '최소 재학습 간격 대기'
    old = previous_snapshot or {}
    new_families = len(set(snapshot['families'])-set(old.get('families', [])))
    new_states = len(set(snapshot['state_ids'])-set(old.get('state_ids', [])))
    return (new_families >= settings.retrain_new_families or new_states >= settings.retrain_new_states), '신규 계열·선택 사례 기준 확인'


def macro(rows, key):
    by_family = defaultdict(list)
    for row in rows:
        value = row.get(key)
        if value is not None and math.isfinite(value):
            by_family[row['family']].append(value)
    values = [statistics.mean(v) for v in by_family.values()]
    return statistics.mean(values) if values else None


def _preference_projection(case, provider):
    """Cheap preliminary filter, NOT the real CAD comparison used for promotion."""
    from pa2.cad.directions import GLOBALS
    from pa2.planning.priority import ExteriorPriorityProvider, is_fastener
    groups, contacts, base = unpack(case)
    mapping = {g.id: g for g in groups}
    exceptions = set(case['payload']['exception_ids'])
    remaining = {g.id for g in groups if not is_fastener(g)} | {base}
    remaining -= exceptions
    teacher = [s for s in reversed(case['payload']['steps']) if s['group_id'] in remaining-{base}]
    expected = [s['group_id'] for s in teacher]
    # A greedy no-CAD priority projection is useful only as a preliminary filter.
    actual, trial = [], set(remaining)
    while trial != {base}:
        gid = provider.rank(mapping, trial, base, contacts)[0]
        actual.append(gid); trial.remove(gid)
    positions = {gid: i for i, gid in enumerate(expected)}
    n = len(actual)*(len(actual)-1)//2
    pair = sum(positions[actual[i]] < positions[actual[j]]
               for i in range(len(actual)) for j in range(i+1, len(actual))) / n if n else None
    hits = directions = count = changed = 0
    for step in teacher:
        gid = step['group_id']
        ranked = provider.rank(mapping, remaining, base, contacts)
        hits += int(ranked[0] == gid)
        fallback = ExteriorPriorityProvider().ordered_directions(mapping[gid],
            [mapping[x] for x in sorted(remaining-{gid})], GLOBALS)
        selected = provider.rank_directions(remaining, gid, fallback) if hasattr(provider, 'rank_directions') else fallback
        wanted = step['removal_direction']
        directions += int(sum(a*b for a, b in zip(selected[0], wanted)) >= math.cos(math.radians(1.)))
        changed += int(selected != fallback)
        count += 1
        remaining.remove(gid)
    return dict(id=case['id'], family=case['family'], pair=pair,
                top1=hits/count if count else None, direction=directions/count if count else None,
                direction_changes=changed)


def promotion_gate(baseline, candidate, settings):
    """Conservative configurable initial gates; missing evidence never passes."""
    reasons = []
    if not baseline or len(baseline) != len(candidate):
        return False, ['평가 사례 부족·불일치']
    old = {(r['id'], r['repeat']): r for r in baseline}
    if set(old) != {(r['id'], r['repeat']) for r in candidate}:
        return False, ['평가 사례·반복 식별자 불일치']
    for row in candidate:
        before = old.get((row['id'], row['repeat']))
        if not before:
            reasons.append('사례·반복 불일치'); continue
        for key in ('steps', 'verified'):
            if row[key] < before[key]:
                reasons.append(f"{row['id']}: {key} 감소")
        for key in ('unresolved', 'unknown', 'timeouts', 'errors'):
            if row[key] > before[key]:
                reasons.append(f"{row['id']}: {key} 증가")
        if before['pair'] is not None and (row['pair'] is None or row['pair'] < before['pair']-.05):
            reasons.append(f"{row['id']}: 선호도 5%p 이상 하락")
    bpair, cpair = macro(baseline, 'pair'), macro(candidate, 'pair')
    bdir, cdir = macro(baseline, 'direction'), macro(candidate, 'direction')
    if bpair is None or cpair is None or bdir is None or cdir is None:
        reasons.append('일반·예외 제외 선호 평가 대상 부족')
        return False, reasons
    if cpair < bpair-settings.promotion_preference_tolerance or cdir < bdir-settings.promotion_preference_tolerance:
        reasons.append('순서·방향 선호도 유지 기준 미달')
    # Mean within project repetitions first, then family macro mean. Large
    # projects and their many fasteners do not dominate this comparison.
    paired = []
    for row in candidate:
        before = old[(row['id'], row['repeat'])]
        paired.append(dict(family=row['family'], time_ratio=row['seconds']/max(before['seconds'], .001),
                           calls_ratio=row['calls']/max(before['calls'], 1),
                           candidates_ratio=row['candidates']/max(before['candidates'], 1)))
    ratios = {k: macro(paired, k) for k in ('time_ratio', 'calls_ratio', 'candidates_ratio')}
    if any(v > settings.promotion_cost_ratio for v in ratios.values()):
        reasons.append('시간·검사 수 증가 한도 초과')
    preference_gain = (cpair-bpair >= settings.promotion_accuracy_gain or
                       cdir-bdir >= settings.promotion_accuracy_gain)
    efficiency_gain = (ratios['time_ratio'] <= 1-settings.promotion_efficiency_gain or
                       ratios['calls_ratio'] <= 1-settings.promotion_efficiency_gain)
    if not (preference_gain or efficiency_gain):
        reasons.append('선호도 또는 시간·경로 검사 개선 기준 미달')
    return not reasons, dict(reasons=reasons, baseline_pair=bpair, candidate_pair=cpair,
        baseline_direction=bdir, candidate_direction=cdir, **ratios)


class LearningPipeline:
    def __init__(self, database, settings, cancel_check=lambda: False):
        self.database, self.settings, self.cancel_check = database, settings, cancel_check
        self.registry = ModelRegistry(database)
        self.deadline = time.monotonic()+settings.learning_budget_sec
        self.cycle = None

    def check(self):
        if self.cancel_check() or time.monotonic() >= self.deadline:
            raise CyclePaused('사용자 작업·유휴 시간 예산: 다음 유휴 시간에 재개')

    def checkpoint(self, phase, result=None, status='RUNNING', error=None):
        with self.database.session() as session:
            row = session.get(LearningCycle, self.cycle.id)
            row.phase, row.status, row.updated_at, row.error_detail = phase, status, utcnow(), error
            if result is not None:
                row.result_json = result
            if status in TERMINAL:
                row.completed_at = utcnow()
            session.flush()
            self.cycle = row
            if status in ('READY','REJECTED') and hasattr(self,'data_snapshot'):
                from .bootstrap import current_progress
                progress=session.get(LearningProgress,'common')
                if progress is None:progress=LearningProgress(key='common');session.add(progress)
                progress.baseline_json=current_progress(self.data_snapshot);progress.updated_at=utcnow()
        from pa2.run_log import safe_log
        safe_log(self,'cycle',self.cycle)

    def _resume_or_create(self):
        with self.database.session() as session:
            pending = session.query(LearningCycle).filter(LearningCycle.status.in_(('RUNNING', 'PAUSED', 'READY'))).order_by(LearningCycle.created_at.desc()).first()
            previous = session.query(LearningCycle).filter(LearningCycle.status.in_(TERMINAL)).order_by(LearningCycle.created_at.desc()).first()
        if pending:
            self.cycle = pending
            if (pending.baseline_models_json != self.registry.active_pair()
                    or policy_signature(AppSettings(**pending.settings_json)) != policy_signature(self.settings)):
                self.checkpoint('정책·적용 모델 변경: 새 주기에서 재평가', status='STALE')
                return None
            if pending.status == 'READY':
                return None
            return json.loads(self.registry.path(pending.snapshot_path).read_text(encoding='utf-8'))
        self.check()
        from .bootstrap import expanded_snapshot,current_progress
        snapshot = expanded_snapshot(self.database)
        old = json.loads(self.registry.path(previous.snapshot_path).read_text(encoding='utf-8')) if previous else None
        with self.database.session() as session:
            progress=session.get(LearningProgress,'common')
            if progress:old=progress.baseline_json
            elif any(self.registry.active_pair().values()):
                session.add(LearningProgress(key='common',baseline_json=current_progress(snapshot)))
                return None
        ready, reason = due(snapshot, old, previous.completed_at if previous else None, self.settings)
        if not ready:
            return None
        cid = str(uuid.uuid4())
        path = self.registry.path(f'cycles/{cid}/snapshot.json')
        snapshot['settings_signature'] = policy_signature(self.settings)
        snapshot['data_digest'] = digest(snapshot)
        atomic_json(path, snapshot)
        with self.database.session() as session:
            row = LearningCycle(id=cid, status='RUNNING', phase='공통 스냅샷 고정',
                snapshot_path=str(path.relative_to(self.registry.root)), counts_json=snapshot['counts'],
                settings_json=asdict(self.settings), baseline_models_json=self.registry.active_pair(), result_json={})
            session.add(row); session.flush(); self.cycle = row
        return snapshot

    def _fit(self, role, cases, snapshot):
        self.check()
        import lightgbm as lgb
        import numpy as np
        from .ranker import LearningService
        choices=[];families=[]
        for case in cases:
            items=list(choice_groups(case,role));choices.extend(items);families.extend([case['family']]*len(items))
        if not choices:
            raise ValueError('학습용 선택 상태가 없습니다.')
        names = sorted(choices[0]['rows'][0])
        products = sorted({c['product_type'] or 'UNKNOWN' for c in cases} | {'UNKNOWN'})
        rows = [row for s in choices for row in s['rows']]
        labels = np.asarray([v for s in choices for v in s['labels']], dtype=int)
        sizes = [len(s['rows']) for s in choices]
        params = dict(LearningService.PARAMS, n_jobs=1, verbosity=-1, deterministic=True,
                      force_col_wise=True)
        model = lgb.LGBMRanker(**params)
        counts=Counter(families)
        weights=np.asarray([len(choices)/(len(counts)*counts[f]) for f,q in zip(families,choices) for _ in q['rows']])
        model.fit(matrix(rows, names, products, PART_TYPES), labels, group=sizes,sample_weight=weights,
                  categorical_feature=[i for i, n in enumerate(names) if n in ('part_type', 'product_type')],
                  feature_name=names)
        self.check()
        bid = str(uuid.uuid5(uuid.UUID(self.cycle.id), role))
        directory = self.registry.path(f'bundles/{bid}')
        directory.mkdir(parents=True, exist_ok=True)
        temp = directory/'model.tmp'
        model.booster_.save_model(str(temp)); temp.replace(directory/'model.txt')
        manifest = dict(bundle_version='model-bundle-v21', role=role,
            schema_version=FEATURE_SCHEMA_VERSION if role == 'ranking' else DIRECTION_SCHEMA,
            feature_names=names, part_categories=PART_TYPES, product_categories=products,
            library_version=lgb.__version__, training_settings=params,
            data_digest=snapshot['data_digest'], heldout_families=snapshot['heldout_families'],
            training_families=sorted({c['family'] for c in cases}),
            training_case_ids=sorted({c['id'] for c in cases}),tied_source_operations=True,family_query_weighting=True,
            preference_labels_only=True, physics_labels_used=False,
            checksum=hashlib.sha256((directory/'model.txt').read_bytes()).hexdigest())
        atomic_json(directory/'manifest.json', manifest)
        self.registry.register(bid, directory)
        return bid

    def _geometry_descriptor(self, case):
        from pa2.cad.contacts import ContactService
        from pa2.cad.importer import StepImporter
        from pa2.storage.cache import cache_key
        graph = case['contact_graph']
        if (not case['contact_ready'] or not graph.get('complete') or
                graph.get('gap_mm') != self.settings.contact_gap_mm or
                graph.get('version') != ContactService.VERSION):
            raise ValueError('평가 입력의 저장 접촉 그래프가 불완전하거나 현재 정책과 다릅니다. 자동 적용 금지.')
        key = cache_key('shape', [case['payload']['assembly_asset_hash']], StepImporter.VERSION, {'unit': 'file'})
        directory = (self.database.layout.cache/'shape'/key).resolve()
        if case.get('external'):
            from .bootstrap import pilot_root
            directory=Path(case['external_geometry']).resolve()
            if not directory.is_relative_to((pilot_root()/'scenes').resolve()):raise ValueError('평가 자료 경로 오류')
        if not case.get('external') and not (directory/'complete.json').is_file():
            raise ValueError('평가용 저장 BREP 캐시 없음: 외부 STEP 재분석이나 기존 프로젝트 변경은 하지 않습니다.')
        manifest_file = directory/'scene.json'
        manifest = json.loads(manifest_file.read_text(encoding='utf-8'))
        if manifest['source_hash'] != case['payload']['assembly_asset_hash']:
            raise ValueError('BREP 캐시의 자산 해시가 다릅니다.')
        files = {'scene.json': hashlib.sha256(manifest_file.read_bytes()).hexdigest()}
        for row in manifest['bodies']:
            self.check()
            target = (directory/row['brep_file']).resolve()
            if not target.is_relative_to(directory):
                raise ValueError('캐시 경로가 관리 영역 밖에 있습니다.')
            files[row['brep_file']] = hashlib.sha256(target.read_bytes()).hexdigest()
        return dict(directory=str(directory) if case.get('external') else str(directory.relative_to(self.database.layout.root.resolve())),
                    external=bool(case.get('external')),files=files)

    def _actual_run(self, case, pair, repeat, descriptor):
        from pa2.application.plan_service import PlanService
        from pa2.cad.brep_cache import load_scene
        from pa2.domain.models import GeometryDecision, PlanningStatus
        from pa2.planning.engine import Planner
        from .comparison import compare_orders
        self.check()
        directory = (self.database.layout.root/descriptor['directory']).resolve()
        from .bootstrap import pilot_root
        allowed=(pilot_root()/'scenes').resolve() if descriptor.get('external') else self.database.layout.cache.resolve()
        if not directory.is_relative_to(allowed):
            raise ValueError('평가 캐시 경로 오류')
        for name, checksum in descriptor['files'].items():
            self.check()
            target = (directory/name).resolve()
            if not target.is_relative_to(directory) or hashlib.sha256(target.read_bytes()).hexdigest() != checksum:
                raise ValueError('평가 중 저장 형상이 변경되었습니다. 현재 주기는 적용하지 않습니다.')
        scene = load_scene(directory, self.database.layout.assets/'cached-evaluation-only.step')
        groups, contacts, base = unpack(case)
        if not {bid for g in groups for bid in g.body_ids} <= set(scene.shapes):
            raise ValueError('평가 스냅샷의 바디가 저장 형상에 없습니다.')
        # Both baseline and candidate use the SAME frozen settings and one CAD
        # thread; no geometry threshold is relaxed by this workflow.
        settings = replace(self.settings, cad_boolean_threads=1)
        provider = self.registry.provider(groups, contacts, base, case['product_type'], pair=pair, audit=False)
        result = Planner(settings).generate(case['project_id'], 0, case['payload']['snapshot_id'],
            groups, contacts, scene.shapes, base, priority_provider=provider,
            collision_exception_ids=case['payload']['exception_ids'],
            jobs_dir=self.database.layout.jobs/'learning',
            cancel_check=lambda: self.cancel_check() or time.monotonic() >= self.deadline)
        self.check()
        if not result.assembly_plan or result.status == PlanningStatus.CANCELLED:
            raise CyclePaused('평가 계산이 중단되었습니다. 완성되지 않은 실행은 비교하지 않습니다.')
        confirmed = PlanService._from_dict(case['confirmed_plan'])
        comparison = compare_orders(result.assembly_plan, confirmed, groups, case['payload']['exception_ids'])
        primary = comparison['general_without_exceptions']
        m = result.metrics
        first = {}; checked_directions = 0
        for path in result.path_results:
            if path.decision != GeometryDecision.NOT_TESTED:
                checked_directions += 1
                first.setdefault((path.state_key, path.group_id), path.decision)
        return dict(id=case['id'], family=case['family'], repeat=repeat,
            pair=primary['pair_order_ratio'], direction=primary['direction_agreement'],
            lcs=primary['lcs_ratio'], steps=len(result.assembly_plan.steps),
            verified=m.get('verified_path_steps', 0), unresolved=m.get('unresolved_general_steps', 0),
            unknown=m.get('unknown_count', 0), timeouts=m.get('native_timeout_count', 0),
            errors=sum(m.get('unknown_pair_codes', {}).values()),
            seconds=m['elapsed_sec'], calls=m.get('native_path_calls', 0),
            candidates=m.get('tested_candidates', 0),
            directions_per_state=checked_directions/max(len(first), 1),
            first_direction_pass_rate=sum(v == GeometryDecision.PASS for v in first.values())/len(first) if first else None,
            comparison=comparison, planner_metrics=m)

    def run(self):
        self.settings.validate()
        import os
        if os.environ.get('PA2_DISABLE_BACKGROUND_LEARNING') == '1':
            return dict(status='DISABLED', reason='이번 실행은 학습 실행·검증 금지')
        try:
            snapshot = self._resume_or_create()
            if snapshot is None:
                return dict(status='WAITING', reason='공통 학습 기준·주기 또는 적용 대기')
            self.data_snapshot=snapshot
            raw = dict(snapshot); saved_digest = raw.pop('data_digest')
            if digest(raw) != saved_digest:
                raise ValueError('고정 학습 스냅샷이 변경되었습니다.')
            heldout = set(snapshot['heldout_families'])
            train = [c for c in snapshot['cases'] if c['family'] not in heldout]
            test = [c for c in snapshot['cases'] if c['family'] in heldout]
            if not train or not test:
                raise ValueError('독립 형상 계열 학습·평가 분리 불가')
            result = dict(self.cycle.result_json)
            result.setdefault('models', {})
            # Exactly one training process; these fits are deliberately serial.
            if 'ranking' not in result['models']:
                self.checkpoint('1/4 순서 모델 학습', result)
                result['models']['ranking'] = self._fit('ranking', train, snapshot)
                self.checkpoint('순서 모델 저장 완료', result)
            ready, detail = direction_readiness(train, self.settings)
            result['direction_data'] = detail
            if ready and 'direction' not in result['models']:
                self.checkpoint('2/4 방향 모델 학습', result)
                result['models']['direction'] = self._fit('direction', train, snapshot)
                self.checkpoint('방향 모델 저장 완료', result)
            baseline = self.cycle.baseline_models_json
            combos = {'baseline': dict(baseline)}
            if result['models'].get('ranking'):
                combos['ranking'] = dict(baseline, ranking=result['models']['ranking'])
            if result['models'].get('direction'):
                combos['direction'] = dict(baseline, direction=result['models']['direction'])
            if len(result['models']) == 2:
                combos['both'] = dict(result['models'])
            result.setdefault('cheap', {})
            for name, pair in combos.items():
                if name not in result['cheap']:
                    rows = []
                    for case in test:
                        self.check()
                        groups, contacts, base = unpack(case)
                        provider = self.registry.provider(groups, contacts, base, case['product_type'], pair=pair, audit=False)
                        rows.append(_preference_projection(case, provider))
                    result['cheap'][name] = rows
                    self.checkpoint('3/4 저비용 선호 평가 '+name, result)
            cheap_base = result['cheap']['baseline']
            promising = []
            for name in combos:
                if name == 'baseline':
                    continue
                rows = result['cheap'][name]
                gains = [macro(rows, k)-macro(cheap_base, k) for k in ('pair', 'top1', 'direction')
                         if macro(rows, k) is not None and macro(cheap_base, k) is not None]
                if gains and min(gains) >= -self.settings.promotion_preference_tolerance and max(gains) > .000001:
                    promising.append(name)
            if not promising:
                self.checkpoint('저비용 선호 평가에서 개선 후보 없음', result, status='REJECTED')
                return dict(status='REJECTED', cycle_id=self.cycle.id)
            result.setdefault('geometry', {})
            for case in test:
                if case['id'] not in result['geometry']:
                    result['geometry'][case['id']] = self._geometry_descriptor(case)
                    self.checkpoint('평가 형상 스냅샷 고정', result)
            result.setdefault('runs', {})
            # Run-order alternates per repetition to reduce warm-up/order bias.
            for repeat in range(self.settings.evaluation_repeats):
                names = ['baseline']+promising
                if repeat % 2:
                    names.reverse()
                for case in test:
                    for name in names:
                        key = f'{name}:{case["id"]}:{repeat}'
                        if key in result['runs']:
                            continue
                        self.checkpoint(f'4/4 실제 CAD 비교 {len(result["runs"])+1}/{len(names)*len(test)*self.settings.evaluation_repeats}', result)
                        result['runs'][key] = self._actual_run(case, combos[name], repeat, result['geometry'][case['id']])
                        self.checkpoint('실제 CAD 비교 실행 저장', result)
            before = [v for k, v in result['runs'].items() if k.startswith('baseline:')]
            result['gates'] = {}
            approved = []
            for name in promising:
                rows = [v for k, v in result['runs'].items() if k.startswith(name+':')]
                passed, metrics = promotion_gate(before, rows, self.settings)
                result['gates'][name] = dict(passed=passed, metrics=metrics, models=combos[name])
                eid = str(uuid.uuid5(uuid.UUID(self.cycle.id), 'evaluation:'+name))
                with self.database.session() as session:
                    if session.get(Evaluation, eid) is None:
                        session.add(Evaluation(id=eid, model_bundle_id=next(v for k, v in combos[name].items() if v != baseline[k]),
                            evaluation_set_version=snapshot['data_digest'], passed=passed,
                            metrics_json=dict(pair=combos[name], baseline=baseline, summary=metrics,
                                              candidate=rows, baseline_runs=before)))
                if passed:
                    approved.append(name)
            if approved:
                best = max(approved, key=lambda n: (
                    macro([v for k, v in result['runs'].items() if k.startswith(n+':')], 'pair') or 0,
                    macro([v for k, v in result['runs'].items() if k.startswith(n+':')], 'direction') or 0,
                    -(macro([v for k, v in result['runs'].items() if k.startswith(n+':')], 'seconds') or 0)))
                result['approved_pair'] = combos[best]
                result['selected_combination'] = best
                self.checkpoint('평가 완료 · 적용 대기 (기존 결과 변경 없음)', result, status='READY')
            else:
                self.checkpoint('기존 모델 유지 · 성능·안전 기준 미달', result, status='REJECTED')
            return dict(status=self.cycle.status, cycle_id=self.cycle.id)
        except CyclePaused as exc:
            if self.cycle:
                self.checkpoint(self.cycle.phase, status='PAUSED', error=str(exc))
            return dict(status='PAUSED')
        except Exception as exc:
            if self.cycle:
                self.checkpoint(self.cycle.phase, status='FAILED', error=f'{type(exc).__name__}: {exc}')
            return dict(status='FAILED', reason=f'{type(exc).__name__}: {exc}')
