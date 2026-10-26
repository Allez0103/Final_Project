"""Explicit offline training with held-out product families; no auto promotion."""
from __future__ import annotations

import json
import time
from pathlib import Path

import lightgbm as lgb
import numpy as np

from pa2.storage.database import RankingCandidate, RankingState, TrainingCase
from .collection import learning_status
from .features import PART_TYPES
from .ranker import LearningService


def train_recorded(database, settings, output_dir: Path, *, pilot=False):
    status = learning_status(database, settings)
    if not status['ready'] and not (pilot and status['family_count'] >= 10):
        raise ValueError(status['reason']+' · 예비 실험도 독립 계열 10개 이상 필요합니다.')
    started = time.perf_counter()
    with database.session() as session:
        cases = {c.id: c for c in session.query(TrainingCase).all()}
        states = session.query(RankingState).order_by(RankingState.id).all()
        candidates = session.query(RankingCandidate).order_by(RankingCandidate.state_id,
                                                             RankingCandidate.group_id).all()
    by_state = {}
    for row in candidates:
        by_state.setdefault(row.state_id, []).append(row)
    families = sorted({c.family_id for c in cases.values()})
    # Keep related states, repeated confirmations and family variants together.
    test_families = set(families[::5])
    train_families = set(families)-test_families
    feature_names = sorted({name for row in candidates for name in row.features_json})
    products = sorted({str(row.features_json.get('product_type', 'UNKNOWN')) for row in candidates} | {'UNKNOWN'})
    def matrix(selected):
        x, y, sizes = [], [], []
        for state in states:
            if cases[state.case_id].family_id not in selected:
                continue
            rows = by_state.get(state.id, [])
            if len(rows) < 2 or sum(r.relevance > 0 for r in rows) != 1:
                continue
            sizes.append(len(rows))
            for row in rows:
                values = []
                for name in feature_names:
                    value = row.features_json.get(name)
                    if name in ('part_type', 'product_type'):
                        categories = PART_TYPES if name == 'part_type' else products
                        value = categories.index(str(value)) if str(value) in categories else categories.index('UNKNOWN')
                    values.append(float(value) if value is not None else float('nan'))
                x.append(values); y.append(row.relevance)
        return np.asarray(x, dtype=float), np.asarray(y, dtype=int), sizes
    x, y, sizes = matrix(train_families)
    tx, ty, tsizes = matrix(test_families)
    if not sizes or not tsizes:
        raise ValueError('독립 계열 평가에 사용할 순서 선택 사례가 부족합니다.')
    service = LearningService()
    service.PARAMS = dict(service.PARAMS, n_jobs=1, verbosity=-1)
    trial = lgb.LGBMRanker(**service.PARAMS)
    categorical = [i for i, n in enumerate(feature_names) if n in ('part_type', 'product_type')]
    trial.fit(x, y, group=sizes, categorical_feature=categorical)
    scores = trial.predict(tx)
    def top1(values):
        index = hits = 0
        for size in tsizes:
            hits += int(ty[index+int(np.argmax(values[index:index+size]))] > 0)
            index += size
        return hits/len(tsizes)
    # Geometry-only inexpensive baseline, not an imitation of the full CAD search.
    volume_index = feature_names.index('volume') if 'volume' in feature_names else None
    baseline = -np.nan_to_num(tx[:, volume_index], nan=0.) if volume_index is not None else np.zeros(len(tx))
    evaluation = dict(schema_version='ranking-evaluation-v20', pilot=pilot,
        family_count=len(families), training_families=sorted(train_families),
        held_out_families=sorted(test_families), family_leakage=False,
        training_states=len(sizes), evaluation_states=len(tsizes),
        preference_top1=top1(scores), small_volume_baseline_top1=top1(baseline),
        baseline_is_full_planner=False, physical_validation=False,
        auto_activated=False, deployment_approved=False,
        reason='선호 평가 실험 결과입니다. 실제 검사 수·시간·단계 수 비교 후에만 적용을 검토합니다.')
    output_dir = Path(output_dir)
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError('기존 모델을 덮어쓰지 않도록 빈 출력 폴더를 지정하세요.')
    model, manifest = service.train(x, y, sizes, output_dir, feature_names, products)
    evaluation.update(elapsed_sec=time.perf_counter()-started, model_path=str(model), manifest_path=str(manifest))
    (output_dir/'evaluation.json').write_text(json.dumps(evaluation, ensure_ascii=False, indent=2), encoding='utf-8')
    return evaluation
