"""Inference adapters that preserve the general-part/fastener two-stage planner."""
from __future__ import annotations

import hashlib
import json
import math

from pa2.planning.priority import is_fastener
from pa2.planning.two_stage import TwoStagePriorityProvider
from .data import DIRECTION_SCHEMA, direction_rows
from .features import FEATURE_SCHEMA_VERSION, FeatureBuilder

ROLES = ('ranking', 'direction')


def matrix(rows, names, products, parts):
    import numpy as np
    result = []
    for row in rows:
        values = []
        for name in names:
            value = row.get(name)
            if name in ('part_type', 'product_type'):
                categories = parts if name == 'part_type' else products
                value = categories.index(str(value)) if str(value) in categories else categories.index('UNKNOWN')
            values.append(float(value) if value is not None else float('nan'))
        result.append(values)
    return np.asarray(result, dtype=float)


class PreferenceModel:
    def __init__(self, directory, role):
        import lightgbm as lgb
        self.manifest = json.loads((directory/'manifest.json').read_text(encoding='utf-8'))
        m = self.manifest
        expected = FEATURE_SCHEMA_VERSION if role == 'ranking' else DIRECTION_SCHEMA
        model_file = directory/'model.txt'
        if (m.get('schema_version') != expected or m.get('role') != role
                or m.get('bundle_version') != 'model-bundle-v21'
                or m.get('library_version', '').split('.')[0] != lgb.__version__.split('.')[0]
                or m.get('checksum') != hashlib.sha256(model_file.read_bytes()).hexdigest()
                or not m.get('feature_names') or len(set(m['feature_names'])) != len(m['feature_names'])):
            raise ValueError('모델 역할·특징 버전·라이브러리 또는 체크섬 불일치')
        for key in ('product_categories', 'part_categories'):
            if not isinstance(m.get(key), list) or 'UNKNOWN' not in m[key]:
                raise ValueError('모델 범주 정보가 없습니다.')
        self.model = lgb.Booster(model_file=str(model_file), params={'num_threads': 1})
        if self.model.num_feature() != len(m['feature_names']) or self.model.feature_name() != m['feature_names']:
            raise ValueError('모델 입력 특징 개수·순서 불일치')

    def scores(self, rows):
        import numpy as np
        m = self.manifest
        if any(set(row) != set(m['feature_names']) for row in rows):
            raise ValueError('실행 모델과 특징 스키마가 다릅니다.')
        values = self.model.predict(matrix(rows, m['feature_names'], m['product_categories'],
                                           m['part_categories']), num_threads=1)
        if len(values) != len(rows) or not np.all(np.isfinite(values)):
            raise ValueError('모델 예측값이 유한하지 않습니다.')
        return values


class LearnedTwoStageProvider(TwoStagePriorityProvider):
    """Reorder existing candidates only; never bypass collision checking."""
    name = 'two-stage-learned-priority-v21'

    def __init__(self, groups, contacts, base, product_type, models, pair, on_failure=None):
        super().__init__()
        self.builder = FeatureBuilder(groups, contacts, base, product_type)
        self.models, self.pair, self.on_failure = models, dict(pair), on_failure
        self.errors, self.delegate = [], None
        self.predictions = dict(ranking=0, direction=0)

    def _failed(self, role, exc):
        self.errors.append(dict(role=role, model_id=self.pair.get(role), error=f'{type(exc).__name__}: {exc}'))
        self.models = {}
        if self.on_failure:
            self.delegate = self.on_failure(dict(self.pair), role, str(exc))
            self.on_failure = None

    def rank(self, groups, remaining, base_group_id, contacts):
        if self.delegate:
            self.delegate.skeleton = self.skeleton
            return self.delegate.rank(groups, remaining, base_group_id, contacts)
        fallback = super().rank(groups, remaining, base_group_id, contacts)
        # Keep a completed CAD skeleton immutable during post-search insertion.
        ids = [gid for gid in fallback if not is_fastener(groups[gid])]
        if 'ranking' not in self.models or self.skeleton or len(ids) < 2:
            return fallback
        try:
            rows = self.builder.rows(remaining)
            scores = self.models['ranking'].scores([rows[gid] for gid in ids])
            self.predictions['ranking'] += 1
            ranked = sorted(range(len(ids)), key=lambda i: (-float(scores[i]), i))
            return [ids[i] for i in ranked] + [gid for gid in fallback if gid not in ids]
        except Exception as exc:
            self._failed('ranking', exc)
            return self.delegate.rank(groups, remaining, base_group_id, contacts) if self.delegate else fallback

    def rank_directions(self, remaining, gid, fallback):
        if self.delegate and hasattr(self.delegate, 'rank_directions'):
            return self.delegate.rank_directions(remaining, gid, fallback)
        if 'direction' not in self.models or is_fastener(self.builder.groups[gid]):
            return fallback
        try:
            scores = self.models['direction'].scores(direction_rows(self.builder, remaining, gid, fallback))
            self.predictions['direction'] += 1
            return [fallback[i] for i in sorted(range(len(fallback)), key=lambda i: (-float(scores[i]), i))]
        except Exception as exc:
            self._failed('direction', exc)
            return (self.delegate.rank_directions(remaining, gid, fallback)
                    if self.delegate and hasattr(self.delegate, 'rank_directions') else fallback)

    def model_metrics(self):
        return dict(pinned_models=self.pair, predictions=self.predictions, failures=list(self.errors),
                    fallback=self.delegate.model_metrics() if hasattr(self.delegate, 'model_metrics') else None)
