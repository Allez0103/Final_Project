"""Immutable bundles and transactionally activated, per-job pinned model pairs."""
from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path

from sqlalchemy import select
from pa2.planning.two_stage import TwoStagePriorityProvider
from pa2.storage.database import ActiveModel, LearningCycle, ModelActivation, ModelBundle, utcnow
from .models import LearnedTwoStageProvider, PreferenceModel, ROLES

RULES = dict(ranking=None, direction=None)


class ModelRegistry:
    def __init__(self, database):
        self.database = database
        self.root = database.layout.learning.resolve()

    def path(self, relative):
        path = (self.root/relative).resolve()
        if not path.is_relative_to(self.root) or path == self.root:
            raise ValueError('모델 경로가 학습 저장소 밖에 있습니다.')
        return path

    @staticmethod
    def _pair(session):
        # Read both slots in ONE SQL statement; even SQLite's legacy transaction
        # mode must not pin half of one activation and half of the next.
        rows = {row.slot: row.model_bundle_id for row in session.scalars(
            select(ActiveModel).where(ActiveModel.slot.in_(ROLES)))}
        return {role: rows.get(role) for role in ROLES}

    def active_pair(self):
        with self.database.session() as session:
            return self._pair(session)

    def register(self, bundle_id, directory):
        directory = directory.resolve()
        relative = str(directory.relative_to(self.root))
        manifest = json.loads((directory/'manifest.json').read_text(encoding='utf-8'))
        # Loading here is part of the later explicit learning/evaluation run.
        PreferenceModel(directory, manifest['role'])
        with self.database.session() as session:
            if session.get(ModelBundle, bundle_id) is None:
                session.add(ModelBundle(id=bundle_id, relative_path=relative,
                    checksum=manifest['checksum'], manifest_json=manifest, compatible=True))

    def load_pair(self, pair):
        result = {}
        with self.database.session() as session:
            bundles = {role: session.get(ModelBundle, bid) for role, bid in pair.items() if bid}
        for role, bundle in bundles.items():
            if not bundle or not bundle.compatible or bundle.manifest_json.get('role') != role:
                raise ValueError(f'{role} 모델이 없거나 호환되지 않습니다.')
            model = PreferenceModel(self.path(bundle.relative_path), role)
            if model.manifest != bundle.manifest_json or model.manifest['checksum'] != bundle.checksum:
                raise ValueError('등록된 모델 명세가 변경되었습니다.')
            result[role] = model
        return result

    def _transaction_lock(self, session):
        if self.database.engine.dialect.name == 'sqlite':
            session.connection().exec_driver_sql('BEGIN IMMEDIATE')
        else:
            list(session.scalars(select(ActiveModel).with_for_update()))

    @staticmethod
    def _set_pair(session, before, after, reason, cycle_id=None):
        for role in ROLES:
            row = session.get(ActiveModel, role)
            if row is None:
                row = ActiveModel(slot=role)
                session.add(row)
            row.model_bundle_id = after.get(role)
            row.activated_at = utcnow()
            row.fallback_reason = reason if after.get(role) is None else None
        session.add(ModelActivation(id=str(uuid.uuid4()), cycle_id=cycle_id,
            previous_models_json=dict(before), active_models_json=dict(after), reason=reason))

    def promote(self, cycle_id):
        with self.database.session() as session:
            cycle = session.get(LearningCycle, cycle_id)
            if not cycle or cycle.status != 'READY' or not cycle.result_json.get('approved_pair'):
                raise ValueError('실제 CAD 비교를 통과한 적용 대기 모델이 없습니다.')
            pair = cycle.result_json['approved_pair']
            baseline = cycle.baseline_models_json
            if not any(g.get('passed') and g.get('models') == pair
                       for g in cycle.result_json.get('gates', {}).values()):
                raise ValueError('모델 조합의 실제 CAD 비교 통과 기록이 없습니다.')
        self.load_pair(pair)
        with self.database.session() as session:
            self._transaction_lock(session)
            cycle = session.get(LearningCycle, cycle_id)
            before = self._pair(session)
            if cycle.status != 'READY' or before != baseline:
                raise ValueError('학습 중 사용 모델이 변경되어 재평가가 필요합니다.')
            self._set_pair(session, before, pair, '동일 계열 분리 평가·CAD 성능 기준 통과', cycle_id)
            cycle.status = 'APPLIED'; cycle.updated_at = utcnow()
        from pa2.run_log import safe_log
        safe_log(self,'cycle',cycle)
        safe_log(self,'event','model_activation',{'cycle_id':cycle_id,'before':before,'after':pair})
        return pair

    def previous_pair(self, current, bad_ids=()):
        with self.database.session() as session:
            history = session.query(ModelActivation).order_by(ModelActivation.created_at.desc()).all()
        # Never manufacture an unevaluated ranking/direction combination.
        for entry in history:
            pair = entry.previous_models_json
            if pair == current or any(bid in bad_ids for bid in pair.values() if bid):
                continue
            try:
                self.load_pair(pair)
                return pair
            except Exception:
                continue
        return dict(RULES)

    def rollback(self, reason='사용자가 이전 모델로 복원', *, expected=None, bad_ids=()):
        before = self.active_pair()
        if expected is not None and before != expected:
            return self.previous_pair(expected, bad_ids)
        after = self.previous_pair(before, bad_ids)
        with self.database.session() as session:
            self._transaction_lock(session)
            if self._pair(session) != before:
                raise ValueError('다른 작업에서 모델 구성이 변경되었습니다. 다시 확인하세요.')
            for bid in bad_ids:
                row = session.get(ModelBundle, bid)
                if row:
                    row.compatible = False
            self._set_pair(session, before, after, reason)
        from pa2.run_log import safe_log
        safe_log(self,'event','model_rollback',{'before':before,'after':after,'reason':reason})
        return after

    def provider(self, groups, contacts, base, product_type, *, pair=None, audit=True, _bad_ids=()):
        pair = dict(pair if pair is not None else self.active_pair())
        if not any(pair.values()):
            return TwoStagePriorityProvider()

        def failed(pinned, role, reason):
            bad = list(set(_bad_ids) | set([pinned[role]] if pinned.get(role) else [x for x in pinned.values() if x]))
            if audit:
                try:
                    fallback = self.rollback('모델 오류: '+reason, expected=pinned, bad_ids=bad)
                except Exception:
                    # An unavailable audit DB must not break normal generation.
                    return TwoStagePriorityProvider()
            else:
                # A candidate evaluation must fail, not quietly score the rules.
                raise ValueError('평가 중 모델 오류: '+reason)
            try:
                return self.provider(groups, contacts, base, product_type, pair=fallback, audit=True, _bad_ids=bad)
            except Exception:
                return TwoStagePriorityProvider()
        try:
            models = self.load_pair(pair)
        except Exception as exc:
            return failed(pair, '', str(exc))
        return LearnedTwoStageProvider(groups, contacts, base, product_type, models, pair, failed)

    def status(self):
        with self.database.session() as session:
            cycles = session.query(LearningCycle).order_by(LearningCycle.created_at.desc()).limit(8).all()
            history = session.query(ModelActivation).order_by(ModelActivation.created_at.desc()).limit(8).all()
        return dict(active=self.active_pair(), cycles=[dict(id=c.id, status=c.status, phase=c.phase,
            counts=c.counts_json, error=c.error_detail, result=c.result_json, settings=c.settings_json) for c in cycles],
            history=[dict(date=str(h.created_at), reason=h.reason, pair=h.active_models_json) for h in history])
