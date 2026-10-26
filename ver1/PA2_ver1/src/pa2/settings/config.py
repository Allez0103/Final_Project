from __future__ import annotations

import json
import math
import os
from dataclasses import asdict, dataclass, fields, replace
from pathlib import Path
from typing import Any

from platformdirs import user_data_dir


@dataclass(frozen=True, slots=True)
class AppSettings:
    schema_version: int = 1
    version: str = "settings-v17"
    import_timeout_sec: int = 3600
    generation_timeout_sec: int = 3600
    video_timeout_sec: int = 3600
    native_operation_timeout_sec: int = 120
    candidate_timeout_sec: int = 240
    max_directions: int = 24
    direction_merge_angle_deg: float = 3.0
    backtrack_depth: int = 3
    backtrack_count: int = 100
    contact_gap_mm: float = 0.05
    axis_angle_tol_deg: float = 2.0
    axis_offset_tol_mm: float = 0.05
    radius_match_tol_mm: float = 0.05
    support_enabled: bool = True
    bolt_initial_overlap_enabled: bool = True
    initial_overlap_region_enabled: bool = True
    initial_overlap_decrease_enabled: bool = True
    allow_support_unknown_draft: bool = True
    foreground_workers: int = 1
    background_workers: int = 1
    background_threads: int = max(1, min(4, (os.cpu_count() or 2) // 2))
    highlight_sec: float = 2.0
    assembly_move_sec: float = 0.7
    camera_180_sec: float = 3.0
    camera_mode: str = "smooth"
    final_hold_sec: float = 2.0
    video_width: int = 1920
    video_height: int = 1080
    video_fps: int = 30
    video_encoder: str = 'auto'
    cad_boolean_threads: int = max(1,min(4,os.cpu_count() or 1))
    volume_relative_tolerance: float = 1e-4
    memory_fraction: float = 0.60
    training_min_families: int = 30
    training_min_states: int = 1000
    retrain_new_families: int = 5
    retrain_new_states: int = 500
    retrain_min_hours: int = 24
    promotion_accuracy_gain: float = 0.03
    promotion_time_ratio: float = 1.2
    # Opt-in until the customer's own dummy projects have been checked.
    auto_learning_enabled: bool = True
    auto_model_apply_enabled: bool = True
    retrain_new_projects: int = 10
    learning_idle_sec: int = 120
    learning_budget_sec: int = 1800
    learning_memory_mb: int = 1536
    direction_min_samples: int = 100
    direction_min_axes: int = 2
    direction_min_per_axis: int = 10
    evaluation_repeats: int = 2
    promotion_cost_ratio: float = 1.05
    promotion_efficiency_gain: float = 0.10
    promotion_preference_tolerance: float = 0.01

    def resolved_for_diagonal(self, diagonal_mm: float) -> dict[str, Any]:
        d = max(0.0, float(diagonal_mm))
        result = asdict(self)
        result.update({
            "geometry_epsilon_mm": min(0.01, max(0.001, d * 1e-7)),
            "exit_clearance_mm": max(1.0, d * 0.005),
            "path_min_interval_mm": min(0.01, max(0.001, d * 1e-7)),
            "coarse_mesh_deflection_mm": max(0.2, d * 0.001),
            "display_mesh_deflection_mm": max(0.05, d * 0.0002),
        })
        return result

    def validate(self) -> None:
        for name, minimum in (('assembly_move_sec', 0.01), ('highlight_sec', 0.0)):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not minimum <= value <= 600:
                raise ValueError(f'{name}은 {minimum}~600초 범위여야 합니다.')
        for name in ('auto_learning_enabled', 'auto_model_apply_enabled'):
            if not isinstance(getattr(self, name), bool):
                raise ValueError(f'{name}는 참/거짓이어야 합니다.')
        if not isinstance(self.retrain_new_projects,int) or isinstance(self.retrain_new_projects,bool) or self.retrain_new_projects<1:
            raise ValueError('재학습 신규 확정 프로젝트 수는 1 이상이어야 합니다.')
        for name, low, high in (
            ('learning_idle_sec', 30, 86400), ('learning_budget_sec', 60, 86400),
            ('learning_memory_mb', 256, 32768), ('training_min_families', 2, 100000),
            ('training_min_states', 2, 10000000), ('retrain_new_families', 1, 100000),
            ('retrain_new_states', 1, 10000000), ('retrain_min_hours', 1, 8760),
            ('direction_min_samples', 2, 10000000), ('direction_min_axes', 2, 6),
            ('direction_min_per_axis', 1, 1000000), ('evaluation_repeats', 2, 5),
        ):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or not low <= value <= high:
                raise ValueError(f'{name}은 {low}~{high} 범위의 정수여야 합니다.')
        for name, low, high in (
            ('promotion_accuracy_gain', 0.001, 1.0), ('promotion_cost_ratio', 1.0, 1.2),
            ('promotion_efficiency_gain', 0.01, 0.9), ('promotion_preference_tolerance', 0., 0.05),
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
                raise ValueError(f'{name} 범위가 잘못되었습니다: {low}~{high}')
        if self.video_encoder not in {'auto','libx264','h264_nvenc','h264_qsv','h264_amf'}:
            raise ValueError('지원하지 않는 영상 인코더입니다.')
        if not 1<=self.cad_boolean_threads<=min(16,os.cpu_count() or 1):
            raise ValueError('CAD 계산 스레드 수가 지원 범위를 벗어났습니다.')
        if not isinstance(self.initial_overlap_decrease_enabled, bool):
            raise ValueError("initial_overlap_decrease_enabled는 참/거짓이어야 합니다.")
        if not isinstance(self.initial_overlap_region_enabled, bool):
            raise ValueError("initial_overlap_region_enabled는 참/거짓이어야 합니다.")
        if not isinstance(self.bolt_initial_overlap_enabled, bool):
            raise ValueError("bolt_initial_overlap_enabled는 참/거짓이어야 합니다.")
        if not isinstance(self.allow_support_unknown_draft, bool):
            raise ValueError("allow_support_unknown_draft는 참/거짓이어야 합니다.")
        for name in ("import_timeout_sec", "generation_timeout_sec", "video_timeout_sec"):
            value = getattr(self, name)
            if not 1800 <= value <= 86400:
                raise ValueError(f"{name}은 1800~86400초 범위여야 합니다.")
        if not 1 <= self.native_operation_timeout_sec <= 600:
            raise ValueError("native_operation_timeout_sec은 1~600초 범위여야 합니다.")
        if not 1 <= self.candidate_timeout_sec <= 1800:
            raise ValueError("candidate_timeout_sec은 1~1800초 범위여야 합니다.")
        if not 6 <= self.max_directions <= 64:
            raise ValueError("max_directions는 6~64 범위여야 합니다.")
        if self.camera_mode not in {"smooth", "stepped_45"}:
            raise ValueError("camera_mode는 smooth 또는 stepped_45여야 합니다.")
        if (self.video_width, self.video_height, self.video_fps) != (1920, 1080, 30):
            if min(self.video_width, self.video_height, self.video_fps) <= 0:
                raise ValueError("영상 규격은 양수여야 합니다.")


class SettingsStore:
    def __init__(self, path: Path | None = None) -> None:
        root = Path(os.environ.get('PA2_DATA_ROOT') or user_data_dir("PA2", "THN"))
        self.path = path or root / "settings.json"

    def load(self) -> AppSettings:
        if not self.path.exists():
            return AppSettings()
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        if raw.get('version','settings-v1') != 'settings-v17':
            if raw.get('candidate_timeout_sec',180)==180:raw['candidate_timeout_sec']=240
            raw['version']='settings-v17'
        allowed = {item.name for item in fields(AppSettings)}
        settings = AppSettings(**{k: v for k, v in raw.items() if k in allowed})
        settings.validate()
        return settings

    def save(self, settings: AppSettings) -> None:
        settings.validate()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(asdict(settings), ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(self.path)

    def reset(self) -> AppSettings:
        value = AppSettings()
        self.save(value)
        return value

    @staticmethod
    def update(settings: AppSettings, **changes: Any) -> AppSettings:
        candidate = replace(settings, **changes)
        candidate.validate()
        return candidate

