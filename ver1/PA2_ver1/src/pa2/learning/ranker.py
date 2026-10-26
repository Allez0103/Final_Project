from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import lightgbm as lgb
import numpy as np

from pa2.domain.models import AssemblyGroup, ContactEdge
from pa2.planning.priority import DefaultPriorityProvider
from pa2.storage.database import Database, RankingCandidate, RankingState, TrainingCase

from .features import FEATURE_SCHEMA_VERSION, PART_TYPES, FeatureBuilder


@dataclass(slots=True)
class ModelManifest:
    schema_version: str
    feature_names: list[str]
    part_categories: list[str]
    product_categories: list[str]
    library_version: str
    training_settings: dict[str, Any]
    checksum: str = ""


class LightGBMPriorityProvider:
    name = "lightgbm"

    def __init__(self, model_path: Path, manifest_path: Path, feature_builder: FeatureBuilder) -> None:
        self.default = DefaultPriorityProvider()
        self.feature_builder = feature_builder
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("schema_version") != FEATURE_SCHEMA_VERSION:
            raise ValueError("MODEL_INCOMPATIBLE: 특징 스키마 버전이 다릅니다.")
        expected_hash = manifest.get("checksum")
        actual_hash = hashlib.sha256(model_path.read_bytes()).hexdigest()
        if expected_hash != actual_hash:
            raise ValueError("MODEL_INCOMPATIBLE: 모델 체크섬이 다릅니다.")
        self.manifest = manifest
        self.model = lgb.Booster(model_file=str(model_path))

    def rank(self, groups: dict[str, AssemblyGroup], remaining: set[str], base_group_id: str, contacts: list[ContactEdge]) -> list[str]:
        fallback = self.default.rank(groups, remaining, base_group_id, contacts)
        rows = self.feature_builder.rows(remaining)
        try:
            matrix = np.asarray([[self._number(name, rows[group_id].get(name)) for name in self.manifest["feature_names"]] for group_id in fallback], dtype=float)
            scores = self.model.predict(matrix)
            if not np.all(np.isfinite(scores)):
                return fallback
            positions = {group_id: index for index, group_id in enumerate(fallback)}
            return sorted(fallback, key=lambda group_id: (-float(scores[positions[group_id]]), positions[group_id]))
        except Exception:
            return fallback

    def _number(self, name: str, value: object) -> float:
        if value is None:
            return float("nan")
        if isinstance(value, (int, float, bool)):
            return float(value)
        categories = self.manifest.get("part_categories" if name == "part_type" else "product_categories", [])
        try:
            return float(categories.index(str(value)))
        except ValueError:
            return float(categories.index("UNKNOWN")) if "UNKNOWN" in categories else float("nan")


class LearningService:
    """Builds ranking rows and trains only after the configured real-data thresholds are met."""

    PARAMS = {
        "objective": "lambdarank", "metric": "ndcg", "label_gain": [0, 1],
        "n_estimators": 300, "learning_rate": 0.05, "num_leaves": 15,
        "min_child_samples": 20, "random_state": 20261017,
    }

    @staticmethod
    def training_ready(family_count: int, state_count: int, min_families: int = 30, min_states: int = 1000) -> tuple[bool, str]:
        if family_count < min_families or state_count < min_states:
            return False, f"학습 보류: 독립 형상 계열 {family_count}/{min_families}, ranking state {state_count}/{min_states}"
        return True, "학습 가능"

    def capture(
        self,
        database: Database,
        *,
        confirmation_id: str,
        family_id: str,
        plan,
        groups: list[AssemblyGroup],
        contacts: list[ContactEdge],
        product_type: str,
    ) -> str:
        """Persist teacher-forced ranking states; confirmation is preference, not geometry PASS."""
        from pa2.planning.priority import is_fastener
        eligible = {g.id for g in groups if not is_fastener(g)}
        removal_order = [step.group_id for step in reversed(plan.steps) if step.group_id in eligible]
        signature_payload = json.dumps({"family": family_id, "groups": sorted(plan.group_ids), "removal": removal_order}, sort_keys=True)
        signature = hashlib.sha256(signature_payload.encode("utf-8")).hexdigest()
        with database.session() as session:
            existing = session.query(TrainingCase).filter_by(input_signature=signature).first()
            if existing is not None:
                return existing.id
            case_id = str(uuid.uuid4())
            session.add(TrainingCase(
                id=case_id, family_id=family_id, confirmation_id=confirmation_id,
                input_signature=signature, source_algorithm=plan.source_algorithm,
                user_changed=plan.user_modified,
            ))
            builder = FeatureBuilder(groups, contacts, plan.base_group_id, product_type)
            remaining = set(plan.group_ids) & eligible
            geometry_by_group = {step.group_id: step.geometry_status.value for step in plan.steps}
            for state_index, selected_group in enumerate(removal_order):
                rows = builder.rows(remaining)
                if len(rows) >= 2 and selected_group in rows:
                    state_id = str(uuid.uuid4())
                    session.add(RankingState(
                        id=state_id, case_id=case_id, state_index=state_index,
                        remaining_ids_json=sorted(remaining), group_size=len(rows),
                    ))
                    for group_id, features in rows.items():
                        session.add(RankingCandidate(
                            id=str(uuid.uuid4()), state_id=state_id, group_id=group_id,
                            features_json=features, relevance=int(group_id == selected_group),
                            geometry_status=geometry_by_group.get(group_id, "NOT_TESTED") if group_id == selected_group else "NOT_TESTED",
                        ))
                remaining.discard(selected_group)
            return case_id

    def train(self, x: np.ndarray, y: np.ndarray, group_sizes: list[int], output_dir: Path, feature_names: list[str], product_categories: list[str]) -> tuple[Path, Path]:
        if sum(group_sizes) != len(y) or any(size < 2 for size in group_sizes):
            raise ValueError("ranking group 크기와 학습 행 수가 일치하지 않습니다.")
        output_dir.mkdir(parents=True, exist_ok=True)
        ranker = lgb.LGBMRanker(**self.PARAMS)
        categorical = [index for index, name in enumerate(feature_names) if name in {"part_type", "product_type"}]
        ranker.fit(x, y, group=group_sizes, categorical_feature=categorical)
        temp_model = output_dir / ".ranking-model.tmp"
        model_path = output_dir / "ranking-model.txt"
        ranker.booster_.save_model(str(temp_model))
        temp_model.replace(model_path)
        checksum = hashlib.sha256(model_path.read_bytes()).hexdigest()
        manifest = ModelManifest(
            schema_version=FEATURE_SCHEMA_VERSION,
            feature_names=feature_names,
            part_categories=PART_TYPES,
            product_categories=product_categories,
            library_version=lgb.__version__,
            training_settings=self.PARAMS,
            checksum=checksum,
        )
        manifest_path = output_dir / "manifest.json"
        temporary = manifest_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(asdict(manifest), ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(manifest_path)
        return model_path, manifest_path

