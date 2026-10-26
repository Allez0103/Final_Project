from __future__ import annotations

from dataclasses import fields

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QGroupBox, QScrollArea,
    QSpinBox, QDoubleSpinBox, QVBoxLayout, QWidget, QComboBox, QMessageBox,
)

from pa2.settings.config import AppSettings, SettingsStore


class SettingsDialog(QDialog):
    saved = Signal(object)

    def __init__(self, store: SettingsStore, settings: AppSettings, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("PA² 설정")
        self.resize(620, 700)
        self.store, self.settings, self.widgets = store, settings, {}
        root = QVBoxLayout(self)
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        panel = QWidget(); panel_layout = QVBoxLayout(panel)
        groups = {
            "처리 시간·자원": ["import_timeout_sec", "generation_timeout_sec", "video_timeout_sec", "native_operation_timeout_sec", "candidate_timeout_sec", "foreground_workers", "background_workers", "background_threads", "cad_boolean_threads"],
            "형상 판정·탐색": ["max_directions", "direction_merge_angle_deg", "backtrack_depth", "backtrack_count", "contact_gap_mm", "axis_angle_tol_deg", "axis_offset_tol_mm", "radius_match_tol_mm", "support_enabled", "initial_overlap_region_enabled", "initial_overlap_decrease_enabled", "bolt_initial_overlap_enabled", "allow_support_unknown_draft"],
            "표시·영상": ["highlight_sec", "assembly_move_sec", "camera_180_sec", "final_hold_sec", "video_width", "video_height", "video_fps", "video_encoder"],
            "자동 학습·평가": ["auto_learning_enabled", "auto_model_apply_enabled", "learning_idle_sec", "learning_budget_sec", "learning_memory_mb", "training_min_families", "training_min_states", "retrain_new_projects", "direction_min_samples", "direction_min_axes", "direction_min_per_axis", "evaluation_repeats", "promotion_accuracy_gain", "promotion_cost_ratio", "promotion_efficiency_gain", "promotion_preference_tolerance"],
        }
        for title, names in groups.items():
            box = QGroupBox(title); form = QFormLayout(box)
            for name in names:
                value = getattr(settings, name)
                if name=='video_encoder':
                    widget=QComboBox(); widget.addItems(['auto','libx264','h264_nvenc','h264_qsv','h264_amf']); widget.setCurrentText(value)
                elif isinstance(value, bool):
                    widget = QCheckBox(); widget.setChecked(value)
                elif isinstance(value, int):
                    widget = QSpinBox(); widget.setRange(0, 100000); widget.setValue(value)
                else:
                    widget = QDoubleSpinBox(); widget.setDecimals(4); widget.setRange(0, 100000); widget.setValue(value)
                self.widgets[name] = widget
                learning_labels = {
                    'auto_learning_enabled':'유휴 시간 자동 학습·평가 허용',
                    'auto_model_apply_enabled':'평가 통과 모델 자동 적용 허용',
                    'retrain_new_projects':'재학습 신규 확정 프로젝트 수 (변형 포함)',
                    'learning_idle_sec':'사용자 입력 없는 유휴 시간 (초)',
                    'learning_budget_sec':'한 번의 유휴 작업 시간 한도 (초)',
                    'learning_memory_mb':'학습·평가 프로세스 합계 메모리 한도 (MiB)',
                    'training_min_families':'최초 학습 최소 독립 형상 계열',
                    'training_min_states':'최초 학습 최소 순서 선택 사례',
                    'retrain_new_families':'재학습 신규 계열 기준 (OR)',
                    'retrain_new_states':'재학습 신규 선택 사례 기준 (OR)',
                    'retrain_min_hours':'최소 재학습 간격 (시간)',
                    'direction_min_samples':'방향 모델 최소 방향 선택 사례',
                    'direction_min_axes':'방향 모델 최소 축 종류 (± 포함 6축)',
                    'direction_min_per_axis':'축별 최소 사례',
                    'evaluation_repeats':'실제 CAD 비교 반복 횟수',
                    'promotion_accuracy_gain':'적용 기준: 선호도 개선 폭 (0.03 = 3%p)',
                    'promotion_cost_ratio':'시간·검사 수 증가 상한 (1.05 = 5%)',
                    'promotion_efficiency_gain':'대체 적용 기준: 시간·검사 감소율 (0.10 = 10%)',
                    'promotion_preference_tolerance':'선호도 유지 허용 폭 (0.01 = 1%p)',
                }
                label = "볼트 축 방향 초기 체결 겹침 예외" if name == "bolt_initial_overlap_enabled" else name
                if name in ('assembly_move_sec','highlight_sec'):
                    label='부품 이동 시간' if name=='assembly_move_sec' else '이동 전 점멸 시간'
                    widget.setDecimals(2);widget.setRange(.01 if name=='assembly_move_sec' else 0,600)
                    widget.setSingleStep(.1);widget.setSuffix(' 초')
                    widget.setToolTip('모델·순서 미리보기와 새로 생성하는 영상에 공통 적용합니다. 기존 MP4 파일은 변경하지 않습니다.')
                if name=='cad_boolean_threads':label='CAD 계산 스레드 수'; widget.setToolTip('1은 순차 계산. 병렬 계산은 실제 형상 비교 시험 후 선택하세요.')
                if name=='video_encoder':label='영상 인코더'; widget.setToolTip('auto: 사용 가능한 인코더를 시험해 선택. 미지원 하드웨어는 CPU로 대체합니다.')
                if name == "bolt_initial_overlap_enabled":
                    widget.setToolTip("모든 부품 초기 영역 예외가 꺼진 경우에만 적용합니다. 볼트 축 방향에 한해 초기 겹침 영역만 허용하며 새로운 간섭과 종점 분리를 검사합니다.")
                if name == "initial_overlap_region_enabled":
                    label="모든 부품의 초기 겹침 예외 사용 (검토용)"
                    widget.setToolTip("감소 예외가 켜지면 위치별 겹침 감소를 허용합니다. 꺼지면 기존 고정 초기 영역만 허용합니다. 처음 겹치지 않은 상대는 연속 경로 검사하며 예외 적용 계획은 검토 필요입니다.")
                if name == "initial_overlap_decrease_enabled":
                    label="초기 겹침 감소 허용 (위치별 검사·검토용)"
                    widget.setToolTip("모든 부품 초기 겹침 예외 사용 시 적용. 최대 0.5 mm 간격으로 부피가 최저값보다 재증가하면 차단합니다. 분리 후 연속 경로를 검사합니다. 동일 상대 내 국소 새 간섭과 검사 위치 사이의 재증가는 배제하지 못합니다.")
                if name == "allow_support_unknown_draft":
                    label="지지 미확인 단계의 검토용 초안 허용"
                    widget.setToolTip("경로가 통과한 경우에만 지지 미확인 경고를 붙여 초안에 포함합니다. 검증 완료가 아니며 충돌/경로 미판정은 계속 제외합니다.")
                if name in learning_labels:
                    label=learning_labels[name]
                    widget.setToolTip('사용자 확정 데이터를 프로젝트별 1회 집계합니다. 두 모델을 순차 학습하고 실제 CAD 비교를 통과해야 교체합니다. 사용자 작업·프로그램 종료 시 학습을 중단합니다.')
                form.addRow(label, widget)
            panel_layout.addWidget(box)
        panel_layout.addStretch(1); scroll.setWidget(panel); root.addWidget(scroll)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel | QDialogButtonBox.RestoreDefaults)
        buttons.accepted.connect(self._save); buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.RestoreDefaults).clicked.connect(self._defaults)
        root.addWidget(buttons)

    def _values(self) -> dict:
        result = {}
        for name, widget in self.widgets.items():
            result[name] = widget.currentText() if isinstance(widget,QComboBox) else widget.isChecked() if isinstance(widget, QCheckBox) else widget.value()
        return result

    def _save(self) -> None:
        try:
            value = SettingsStore.update(self.settings, **self._values())
            self.store.save(value); self.saved.emit(value); self.accept()
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, '설정 확인', str(exc))

    def _defaults(self) -> None:
        defaults = AppSettings()
        for name, widget in self.widgets.items():
            value = getattr(defaults, name)
            if isinstance(widget,QComboBox):widget.setCurrentText(value)
            elif isinstance(widget,QCheckBox):widget.setChecked(value)
            else:widget.setValue(value)

