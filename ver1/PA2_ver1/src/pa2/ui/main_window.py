from __future__ import annotations

import copy
import json
import os
import threading
import uuid
import time
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, QTimer, Signal, Slot, QUrl, QSize
from PySide6.QtGui import QAction, QIcon, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout,
    QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow,
    QMessageBox, QPushButton, QSizePolicy, QSplitter, QTabWidget, QTextEdit, QToolBar, QVBoxLayout, QWidget, QInputDialog, QDialog,
)
from vtkmodules.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor

from pa2.application.import_service import ImportResult, ImportService
from pa2.application.plan_service import PlanService
from pa2.application.manual_grouping import ManualGroupingService
from pa2.application.video_library import VideoLibrary
from pa2.application.project_service import ProjectService, ProjectView
from pa2.domain.models import GeometryStatus, Plan, PlanningStatus
from pa2.planning.engine import Planner
from .part_list import PartListWidget
from pa2.planning.manual import ManualPlanner
from pa2.learning.ranker import LearningService
from pa2.learning.collection import collect_confirmation, learning_status
from pa2.rendering.scene import build_timeline, scene_at
from pa2.rendering.vtk_scene import VtkScene
from pa2.settings.config import AppSettings, SettingsStore
from pa2.storage.assets import AssetStore
from pa2.storage.cache import CacheStore
from pa2.storage.database import Database
from pa2.storage.layout import DataLayout
from pa2.video.renderer import VideoRenderer

from .settings_dialog import SettingsDialog
from .theme import STYLESHEET


class TaskWorker(QObject):
    finished = Signal(object)
    failed = Signal(str)
    progress = Signal(str, str)
    cancelled = Signal()

    def __init__(self, function, cancel_event: threading.Event) -> None:
        super().__init__(); self.function = function; self.cancel_event = cancel_event

    @Slot()
    def run(self) -> None:
        def report(stage, message):
            if self.cancel_event.is_set(): raise InterruptedError("작업을 취소했습니다.")
            self.progress.emit(stage, message)
        try: self.finished.emit(self.function(report))
        except InterruptedError: self.cancelled.emit()
        except BaseException as exc: self.failed.emit(f"{type(exc).__name__}: {exc}")


class ProjectPage(QWidget):
    analyze_requested = Signal(object, object, object)
    project_opened = Signal(object)

    def __init__(self, projects: ProjectService) -> None:
        super().__init__(); self.projects = projects; self.assembly_path = None; self.part_paths = []
        layout = QHBoxLayout(self)
        left = QGroupBox("프로젝트 찾기"); left_layout = QVBoxLayout(left)
        self.project_list = QListWidget(); self.project_list.itemDoubleClicked.connect(self._open)
        left_layout.addWidget(self.project_list); project_buttons=QHBoxLayout(); refresh = QPushButton("새로고침"); refresh.clicked.connect(self.refresh); rename=QPushButton("이름 수정"); rename.clicked.connect(self._rename); remove=QPushButton("삭제"); remove.clicked.connect(self._delete); [project_buttons.addWidget(button) for button in (refresh,rename,remove)]; left_layout.addLayout(project_buttons)
        right = QGroupBox("새 프로젝트 / 입력 파일"); form = QFormLayout(right)
        self.name = QLineEdit(); self.vehicle = QComboBox(); self.vehicle.setEditable(True); self.product = QComboBox(); self.product.setEditable(True)
        self.assembly_label = QLabel("선택 안 함"); self.parts_label = QLabel("선택 안 함"); self.parts_label.setWordWrap(True)
        assembly_button = QPushButton("완제품 STEP 선택"); assembly_button.clicked.connect(self._assembly)
        parts_button = QPushButton("개별 부품 STEP 선택(선택 사항)"); parts_button.clicked.connect(self._parts)
        start = QPushButton("프로젝트 생성 및 분석"); start.setProperty("primary", True); start.clicked.connect(self._analyze)
        for label, widget in (("프로젝트명",self.name),("차종",self.vehicle),("품종",self.product),("완제품",self.assembly_label),("",assembly_button),("개별 부품",self.parts_label),("",parts_button),("",start)): form.addRow(label,widget)
        layout.addWidget(left, 1); layout.addWidget(right, 2); self.refresh()

    def refresh(self) -> None:
        self.project_list.clear(); vehicles, products = self.projects.vocabularies(); self.vehicle.clear(); self.vehicle.addItems(vehicles); self.product.clear(); self.product.addItems(products)
        for project in self.projects.list():
            item = QListWidgetItem(f"{project.vehicle_type}  ›  {project.product_type}  ›  {project.name}"); item.setData(Qt.UserRole, project); self.project_list.addItem(item)

    def _assembly(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "완제품 STEP", "", "STEP (*.stp *.step)")
        if path: self.assembly_path = Path(path); self.assembly_label.setText(self.assembly_path.name)

    def _parts(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "개별 부품 STEP", "", "STEP (*.stp *.step)")
        if paths: self.part_paths = [Path(path) for path in paths]; self.parts_label.setText("\n".join(path.name for path in self.part_paths))

    def _analyze(self) -> None:
        if not self.assembly_path:
            QMessageBox.warning(self, "입력 확인", "완제품 STEP 파일을 선택하세요."); return
        try: project = self.projects.create(self.name.text(), self.vehicle.currentText(), self.product.currentText())
        except Exception as exc: QMessageBox.warning(self, "프로젝트 확인", str(exc)); return
        self.analyze_requested.emit(project, self.assembly_path, self.part_paths)

    def _open(self, item) -> None:
        self.project_opened.emit(item.data(Qt.UserRole))

    def _rename(self) -> None:
        item=self.project_list.currentItem()
        if not item:return
        project=item.data(Qt.UserRole); name,ok=QInputDialog.getText(self,"프로젝트 이름 수정","새 프로젝트명",text=project.name)
        if ok and name.strip(): self.projects.update(project.id,name); self.refresh()

    def _delete(self) -> None:
        item=self.project_list.currentItem()
        if not item:return
        project=item.data(Qt.UserRole)
        answer=QMessageBox.question(self,"프로젝트 삭제",f"'{project.name}' 프로젝트의 소유 데이터만 삭제 표시합니다.\n외부 원본·공용 자산·독립 학습 사례는 삭제하지 않습니다. 계속할까요?")
        if answer==QMessageBox.Yes:self.projects.delete(project.id); self.refresh()


class ModelPage(QWidget):
    plan_requested = Signal(str)
    confirm_requested = Signal(object)
    preset_changed = Signal()

    def __init__(self) -> None:
        super().__init__(); self.result: ImportResult | None = None; self.plan: Plan | None = None; self.play_time = 0.0
        root = QVBoxLayout(self); split = QSplitter(Qt.Horizontal)
        left = QWidget(); ll = QVBoxLayout(left); self.search = QLineEdit(); self.search.setPlaceholderText("부품 검색"); self.search.textChanged.connect(self._filter); self.parts = PartListWidget(); self.parts.itemSelectionChanged.connect(self._select_group); visibility=QHBoxLayout(); hide=QPushButton("숨기기"); hide.clicked.connect(self._hide); solo=QPushButton("단독"); solo.clicked.connect(self._solo); show_all=QPushButton("전체"); show_all.clicked.connect(self._show_all); [visibility.addWidget(button) for button in (hide,solo,show_all)]; ll.addWidget(self.search); ll.addLayout(visibility); ll.addWidget(self.parts)
        center = QWidget(); cl = QVBoxLayout(center); tools = QHBoxLayout(); self.fit_button=QPushButton("화면 맞춤"); self.fit_button.clicked.connect(lambda:self.vtk_scene.fit() if hasattr(self,"vtk_scene") else None); tools.addWidget(self.fit_button); tools.addStretch(1); cl.addLayout(tools)
        self.headless = os.environ.get("QT_QPA_PLATFORM") == "offscreen"
        if self.headless:
            self.vtk_widget = QLabel("3D 뷰 · 헤드리스 검증 모드")
            self.vtk_widget.setAlignment(Qt.AlignCenter)
            self.vtk_scene = VtkScene(offscreen=True)
        else:
            self.vtk_widget=QVTKRenderWindowInteractor(center)
            self.vtk_scene=VtkScene(self.vtk_widget.GetRenderWindow())
            self.vtk_widget.Initialize()
        cl.addWidget(self.vtk_widget,1)
        right = QWidget(); form = QFormLayout(right); self.direction = QComboBox(); self.direction.addItems(["자동", "+X", "-X", "+Y", "-Y", "+Z", "-Z"]); self.distance=QDoubleSpinBox(); self.distance.setRange(0.001,1_000_000); self.distance.setSuffix(" mm"); self.camera=QComboBox(); self.camera.addItems(["AUTO","TOP","BOTTOM","FRONT","LEFT","RIGHT","BACK"]); self.process=QTextEdit(); self.material=QTextEdit(); self.caution=QTextEdit(); apply_btn=QPushButton("선택 단계에 적용"); apply_btn.clicked.connect(self._apply_step); forward_btn=QPushButton("이 뒤로 과정 문구 일괄 적용"); forward_btn.clicked.connect(self._apply_forward); form.addRow("분해 방향",self.direction); form.addRow("거리",self.distance); form.addRow("카메라",self.camera); form.addRow("조립 과정",self.process); form.addRow("",forward_btn); form.addRow("자재정보",self.material); form.addRow("주의사항",self.caution); form.addRow(apply_btn)
        split.addWidget(left); split.addWidget(center); split.addWidget(right); split.setSizes([260,900,300]); root.addWidget(split,1)
        bottom=QHBoxLayout(); self.order=QListWidget(); self.order.setDragDropMode(QAbstractItemView.InternalMove); self.order.setSelectionMode(QAbstractItemView.ExtendedSelection); self.order.currentItemChanged.connect(self._edit_step); bottom.addWidget(self.order,1); controls=QVBoxLayout(); self.base=QComboBox(); generate=QPushButton("순서 생성"); generate.setProperty("primary",True); generate.clicked.connect(lambda:self.plan_requested.emit(self.base.currentData() or "")); preview=QPushButton("미리보기 갱신"); preview.clicked.connect(self.preview); confirm=QPushButton("순서 확정"); confirm.clicked.connect(lambda:self.confirm_requested.emit(self.plan) if self.plan else None); self.speed=QComboBox(); self.speed.addItems(["0.25","0.5","1","1.5","2","3","4"]); self.play=QPushButton("재생"); self.play.clicked.connect(self._toggle_play); self.play_timer=QTimer(self); self.play_timer.timeout.connect(self._play_tick); self.status=QLabel("모델을 불러오세요."); self.status.setWordWrap(True); [controls.addWidget(w) for w in (QLabel("기준 부품"),self.base,generate,preview,confirm,QLabel("재생 속도"),self.speed,self.play,self.status)]; controls.addStretch(1); bottom.addLayout(controls); root.addLayout(bottom,0)
        self.diagnostics_button=QPushButton("순서 생성 진단"); self.diagnostics_button.setEnabled(False); self.diagnostics_button.clicked.connect(self._show_diagnostics); controls.addWidget(self.diagnostics_button); self.diagnostics_text=""
        self.exception_ids=[]
        self.exception_button=QPushButton('예외 부품 사전 설정 (0개)')
        self.exception_button.clicked.connect(self._configure_exceptions)
        controls.insertWidget(2,self.exception_button)
        self.base.currentIndexChanged.connect(lambda _:self.preset_changed.emit())

    def _configure_exceptions(self):
        if not self.result:return
        dialog=QDialog(self); dialog.setWindowTitle('선제 제거할 간섭 예외 부품'); dialog.resize(510,500)
        layout=QVBoxLayout(dialog)
        note=QLabel('선택 부품은 간섭·지지 검사 없이 분해 선두에 배치합니다.\n6축 노출도 1순위 방향을 적용하며, 조립 목록에서는 마지막에 배치됩니다.')
        note.setWordWrap(True); layout.addWidget(note)
        listing=QListWidget(); layout.addWidget(listing)
        for group in self.result.snapshot.groups:
            if group.id==self.base.currentData():continue
            item=QListWidgetItem(group.display_name); item.setData(Qt.UserRole,group.id)
            item.setFlags(item.flags()|Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if group.id in self.exception_ids else Qt.Unchecked)
            listing.addItem(item)
        save=QPushButton('적용'); save.clicked.connect(dialog.accept); layout.addWidget(save)
        cancel=QPushButton('취소'); cancel.clicked.connect(dialog.reject); layout.addWidget(cancel)
        if dialog.exec()==QDialog.Accepted:
            self.set_exceptions([listing.item(i).data(Qt.UserRole) for i in range(listing.count())
                                 if listing.item(i).checkState()==Qt.Checked])
            self.preset_changed.emit()

    def set_exceptions(self, ids):
        self.exception_ids=list(ids)
        self.exception_button.setText(f'예외 부품 사전 설정 ({len(ids)}개)')
        names={g.id:g.display_name for g in self.result.snapshot.groups} if self.result else {}
        self.exception_button.setToolTip(', '.join(names.get(g,g) for g in ids))

    def set_planning_diagnostics(self,result,path):
        names={g.id:g.display_name for g in self.result.snapshot.groups}
        labels={"INITIAL_OVERLAP":"초기 형상 겹침","PATH_BLOCKED":"이동 중 간섭","PATH_UNKNOWN":"경로 미판정","SUPPORT_UNKNOWN":"지지 경로 미확인","TIME_BUDGET_EXCEEDED":"계산 시간 초과","CERTIFIED_CLEAR":"경로 확인","BOLT_NON_AXIAL":"체결 볼트의 비축 방향 차단","FASTENER_INITIAL_OVERLAP_ALLOWED":"볼트 초기 체결 겹침 예외로 경로 확인"}
        counts=Counter(item.reason_code for item in result.path_results)
        labels["PATH_CLEAR_SUPPORT_UNVERIFIED"]="경로 통과·지지 미검증(검토용)"
        labels["INITIAL_REGION_ALLOWED"]="초기 겹침 영역 예외로 경로 확인(검토용)"
        labels["INITIAL_DECREASE_ALLOWED"]="초기 겹침 감소 예외(위치별 검사·검토용)"
        labels['USER_COLLISION_EXCEPTION']='사용자 지정 선제 제거 예외 · 간섭·지지 미검증'
        lines=[f"생성된 제거 단계: {len(result.removal_order)} / {result.metrics['total_moving_groups']}",result.reason,
               "판정 수는 부품 수가 아니라 검사한 방향 후보 수입니다.",
               *[f"{labels.get(key,key)}: {value}" for key,value in counts.items()],"",f"전체 결과 파일: {path}",""]
        if "native_path_calls" in result.metrics:
            metrics = result.metrics
            lines[2:2] = [
                f"신규 경로 계산 요청: {metrics['native_path_calls']}회 · 차단 근거 재사용: {metrics.get('blocked_witness_cache_hits', 0)}회",
                f"중복 상태 건너뛰기: {metrics.get('closed_state_skips', 0)}회 · 부품 판정 재사용: {metrics.get('group_evaluation_cache_hits', 0)}회",
                f"전체 탐색 시간: {metrics.get('elapsed_sec', 0):.1f}초 · 신규 경로 요청 소요 합계: {metrics.get('native_path_elapsed_sec', 0):.1f}초",
            ]
            if 'skeleton_order' in metrics:
                lines[2:2]=[
                    f"체결물 없는 일반 부품 초안: {len(metrics['skeleton_order'])}개 · {metrics.get('skeleton_elapsed_sec',0):.1f}초",
                    f"사용자 지정 무검사 예외: {metrics.get('collision_exception_steps',0)}개 · 방향 힌트 계산: {metrics.get('direction_hint_calls',0)}회 / {metrics.get('direction_hint_elapsed_sec',0):.1f}초",
                    f"가상 후보 {metrics.get('virtual_candidate_records',0)}개 · 실제 상태 신규 경로 {metrics.get('actual_native_path_calls',0)}회 / 가상 상태 신규 경로 {metrics.get('virtual_native_path_calls',0)}회"]
        seen=set()
        for item in result.path_results:
            if item.reason_code=="CERTIFIED_CLEAR" and not item.evidence.get("input_repairs"):continue
            key=(item.group_id,item.reason_code,tuple(item.obstacle_ids),
                 tuple(detail.get("code") for detail in item.evidence.get("pair_diagnostics",[])))
            if key in seen:continue
            seen.add(key)
            related=", ".join(names.get(g,g) for g in item.obstacle_ids)
            lines.append(f"{names.get(item.group_id,item.group_id)} · {labels.get(item.reason_code,item.reason_code)}"+(f" · 관련 부품: {related}" if related else ""))
            for exception in item.evidence.get("fastener_exceptions",[]):
                lines.append(f"  체결 예외 검사: {names.get(exception['obstacle_id'],exception['obstacle_id'])} · 초기 겹침 {exception['initial_overlap_mm3']:.4f} mm³ · 쌍 판정 {exception['pair_decision']}")
            for exception in item.evidence.get("initial_region_exceptions",[]):
                lines.append(f"  초기 영역 예외 검사: {names.get(exception['obstacle_id'],exception['obstacle_id'])} · 초기 겹침 {exception['initial_overlap_mm3']:.4f} mm³ · 쌍 판정 {exception['pair_decision']}")
            for exception in item.evidence.get("initial_decrease_exceptions",[]):
                lines.append(f"  초기 감소 예외 검사: {names.get(exception['obstacle_id'],exception['obstacle_id'])} · 초기 겹침 {exception['initial_overlap_mm3']:.4f} mm³ · 쌍 판정 {exception['pair_decision']} · 동일 상대 내 국소 충돌 배제 불가")
            detail_labels={"INPUT_GEOMETRY_INVALID":"입력 BREP 정밀 유효성 실패", "SWEEP_UNRESOLVED":"곡면 경로의 보수적 포괄 영역 미해결", "SWEEP_CONSTRUCTION_FAILED":"경로 형상 생성 실패", "INITIAL_BOOLEAN_FAILED":"초기 교차 계산 실패", "INITIAL_REGION_CUT_FAILED":"초기 영역 차감 실패", "INITIAL_REGION_CUT_INVALID":"초기 영역 차감 형상 유효성 실패", "CANDIDATE_TIME_BUDGET":"후보 계산 시간 초과", "ENDPOINT_NOT_SEPARATED":"종점 분리 미확인", "ORIGINAL_ENDPOINT_NOT_SEPARATED":"원래 상대 형상과 종점 분리 미확인", "EXACT_COLLISION_WITNESS":"이동 위치에서 실제 교차 체적 확인"}
            detail_labels.update({"INITIAL_DECREASE_SAMPLED":"초기 겹침 감소 위치별 검사 통과(검토용)",
                "OVERLAP_REINCREASE":"초기 겹침 부피 재증가", "DECREASE_BOOLEAN_FAILED":"감소 검사 교차 계산 실패",
                "DECREASE_TAIL_UNKNOWN":"겹침 해소 후 연속 경로 미판정", "DECREASE_TAIL_BLOCKED":"겹침 해소 후 연속 경로 충돌",
                "DECREASE_SAMPLE_BUDGET":"감소 검사 위치 수 제한"})
            for detail in item.evidence.get("pair_diagnostics",[]):
                label=detail_labels.get(detail["code"],detail["code"])
                lines.append(f"  상세: {label} · 상대 {names.get(detail['obstacle_id'],detail['obstacle_id'])}"+f" · {detail.get('error','')}")
                if "samples" in detail:
                    lines.append("  겹침 검사 위치(mm)/부피(mm³): "+", ".join(f"{s['position_mm']:.3f}/{s['overlap_mm3']:.6f}" if s['overlap_mm3'] is not None else f"{s['position_mm']:.3f}/계산 실패" for s in detail['samples']))
                if "max_tolerance_after_mm" in detail:
                    repair_limit=detail.get('repair_max_tolerance_mm',detail['epsilon_mm'])
                    lines.append(f"  보정 허용 한계 확인: 최대 허용오차 {detail['max_tolerance_after_mm']:.7f} mm / 기준 {repair_limit:.7f} mm · 체적 변화 {abs(detail['volume_after_mm3']-detail['volume_before_mm3']):.9f} mm³ · 보정 적용 안 함")
            if item.evidence.get("native_error"):
                lines.append(f"  계산 오류: {item.evidence['native_error']}")
            for repair in item.evidence.get("input_repairs",[]):
                lines.append(f"  계산용 파라미터 보정: {names.get(repair['group_id'],repair['group_id'])} · 최대 허용오차 {repair['max_tolerance_after_mm']:.7f} mm · 원본 변경 없음")
            unsupported=item.evidence.get("support",{}).get("unsupported",[])
            if unsupported:
                lines.append("  지지 미확인: "+", ".join(names.get(g,g) for g in unsupported))
        self.diagnostics_text="\n".join(lines); self.diagnostics_button.setEnabled(True)

    def _show_diagnostics(self):
        dialog=QDialog(self); dialog.setWindowTitle("순서 생성 진단"); dialog.resize(900,650)
        layout=QVBoxLayout(dialog); text=QTextEdit(); text.setReadOnly(True); text.setPlainText(self.diagnostics_text); layout.addWidget(text); close=QPushButton("닫기"); close.clicked.connect(dialog.accept); layout.addWidget(close); dialog.exec()

    def set_result(self, result: ImportResult, settings: AppSettings) -> None:
        self.scene_update_on_ui_thread=QThread.currentThread()==QApplication.instance().thread()
        if not self.scene_update_on_ui_thread:
            raise RuntimeError('3D 모델 화면 갱신은 UI 스레드에서 수행해야 합니다.')
        self.base.blockSignals(True)
        self.result=result; self.parts.clear(); self.base.clear(); self.plan=None; self.order.clear(); self.settings=settings; self.diagnostics_button.setEnabled(False)
        self.set_exceptions([])
        for group in result.snapshot.groups:
            item=QListWidgetItem(f"{group.display_name}  [{group.matching_status.value}]"); item.setData(Qt.UserRole,group.id); self.parts.addItem(item); self.base.addItem(group.display_name,group.id)
        try:
            self.base.setCurrentIndex(self.base.findData(Planner.choose_base(result.snapshot.groups)))
        except ValueError:
            pass
        self.base.blockSignals(False)
        resolved=settings.resolved_for_diagonal(result.assembly_scene.bounds.diagonal); self.vtk_scene.load(result.assembly_scene,result.snapshot.groups,resolved["display_mesh_deflection_mm"])
        self.status.setText(f"그룹 {len(result.snapshot.groups)}개 · 접촉 {len(result.snapshot.contacts)}개 · 캐시 {result.cache_hits} hit/{result.cache_misses} miss")

    def set_plan(self, plan: Plan, message: str) -> None:
        self.plan=plan; self.order.clear()
        names={g.id:g.display_name for g in self.result.snapshot.groups} if self.result else {}
        for step in plan.steps:
            marker=" [지지 미검증]" if step.geometry_status==GeometryStatus.SUPPORT_UNVERIFIED else " [초기 영역 예외]" if step.geometry_status==GeometryStatus.INITIAL_REGION_EXCEPTION else " [계산용 보정]" if step.geometry_status==GeometryStatus.GEOMETRY_REPAIRED else " [체결 예외]" if step.geometry_status==GeometryStatus.FASTENER_EXCEPTION else ""
            if step.geometry_status==GeometryStatus.INITIAL_DECREASE_EXCEPTION:marker=" [초기 감소 예외]"
            if step.geometry_status==GeometryStatus.USER_COLLISION_EXCEPTION:marker=' [사용자 간섭 예외]'
            if step.geometry_status==GeometryStatus.DRAFT_UNRESOLVED:marker=' [경로 확인 필요]'
            item=QListWidgetItem(f"{step.step_index}. {names.get(step.group_id,step.group_id)}{marker}"); item.setData(Qt.UserRole,step.group_id); self.order.addItem(item)
        self.status.setText(message)

    def _filter(self,text):
        for i in range(self.parts.count()): self.parts.item(i).setHidden(text.lower() not in self.parts.item(i).text().lower())

    def _select_group(self):
        selected={item.data(Qt.UserRole) for item in self.parts.selectedItems()}
        for gid,actor in self.vtk_scene.actors.items(): actor.GetProperty().SetEdgeVisibility(gid in selected); actor.GetProperty().SetEdgeColor(0.15,0.2,0.77); actor.GetProperty().SetLineWidth(3)
        self.vtk_scene.render_window.Render()

    def _hide(self):
        for item in self.parts.selectedItems():
            actor=self.vtk_scene.actors.get(item.data(Qt.UserRole))
            if actor:actor.SetVisibility(False)
        self.vtk_scene.render_window.Render()

    def _solo(self):
        selected={item.data(Qt.UserRole) for item in self.parts.selectedItems()}
        for gid,actor in self.vtk_scene.actors.items():actor.SetVisibility(gid in selected)
        self.vtk_scene.render_window.Render()

    def _show_all(self):
        for actor in self.vtk_scene.actors.values():actor.SetVisibility(True)
        self.vtk_scene.render_window.Render()

    def _edit_step(self,current,_previous):
        if not current or not self.plan:return
        gid=current.data(Qt.UserRole); step=next(s for s in self.plan.steps if s.group_id==gid); self.distance.setValue(step.travel_mm); self.camera.setCurrentText(step.camera_mode); self.process.setPlainText(step.process_text); self.material.setPlainText(step.material_text); self.caution.setPlainText(step.caution_text)

    def _apply_step(self):
        if not self.plan or not self.order.currentItem():return
        selected={item.data(Qt.UserRole) for item in self.order.selectedItems()}
        for step in self.plan.steps:
            if step.group_id in selected:
                step.travel_mm=self.distance.value()
                if step.geometry_status!=GeometryStatus.USER_COLLISION_EXCEPTION:step.geometry_status=GeometryStatus.USER_CONFIRMED_UNCHECKED
        gid=self.order.currentItem().data(Qt.UserRole); step=next(s for s in self.plan.steps if s.group_id==gid); directions={"+X":(1,0,0),"-X":(-1,0,0),"+Y":(0,1,0),"-Y":(0,-1,0),"+Z":(0,0,1),"-Z":(0,0,-1)}
        if self.direction.currentText() in directions:step.removal_direction=directions[self.direction.currentText()]; step.assembly_direction=tuple(-v for v in step.removal_direction)
        step.camera_mode=self.camera.currentText(); step.process_text=self.process.toPlainText(); step.material_text=self.material.toPlainText(); step.caution_text=self.caution.toPlainText()
        if step.geometry_status!=GeometryStatus.USER_COLLISION_EXCEPTION:step.geometry_status=GeometryStatus.USER_CONFIRMED_UNCHECKED
        self.plan.user_modified=True

    def _apply_forward(self):
        if not self.plan or not self.order.currentItem():return
        start=self.order.row(self.order.currentItem()); text=self.process.toPlainText(); order=[self.order.item(i).data(Qt.UserRole) for i in range(self.order.count())]; mapping={step.group_id:step for step in self.plan.steps}
        for gid in order[start:]:
            mapping[gid].process_text=text
            if mapping[gid].geometry_status!=GeometryStatus.USER_COLLISION_EXCEPTION:mapping[gid].geometry_status=GeometryStatus.USER_CONFIRMED_UNCHECKED
        self.plan.user_modified=True

    def preview(self):
        if not self.plan or not self.result:return
        if [self.order.item(i).data(Qt.UserRole) for i in range(self.order.count())]!=[s.group_id for s in self.plan.steps]:self.plan.user_modified=True
        ids=[self.order.item(i).data(Qt.UserRole) for i in range(self.order.count())]; mapping={s.group_id:s for s in self.plan.steps}; self.plan.steps=[mapping[i] for i in ids]; [setattr(s,"step_index",i) for i,s in enumerate(self.plan.steps,1)]; timeline=self._timeline(); state=scene_at(self.plan,timeline.duration,self.settings,timeline); self.vtk_scene.apply(state); self.status.setText("현재 편집본으로 미리보기를 갱신했습니다. CAD 간섭 재검사는 수행하지 않았습니다.")

    def _timeline(self,plan=None):
        bounds=self.result.assembly_scene.bounds if self.result else None
        return build_timeline(plan or self.plan,self.settings,bounds)

    def _toggle_play(self):
        if not self.plan:return
        if self.play_timer.isActive():self.play_timer.stop(); self.play.setText("재생"); return
        self.play_time=0.0; self.play.setText("일시정지"); self.play_timer.start(33)

    def _play_tick(self):
        if not self.plan:return
        speed=float(self.speed.currentText()); self.play_time += .033*speed; timeline=self._timeline()
        if self.play_time>=timeline.duration:self.play_time=timeline.duration; self.play_timer.stop(); self.play.setText("재생")
        self.vtk_scene.apply(scene_at(self.plan,self.play_time,self.settings,timeline))


from .model_editor import enhanced_model_page
ModelPage = enhanced_model_page(ModelPage)


class VideoPage(QWidget):
    render_requested = Signal()
    export_requested = Signal(object)
    def __init__(self):
        super().__init__(); layout=QVBoxLayout(self); self.info=QLabel("확정된 순서가 없습니다."); self.info.setWordWrap(True); self.generate=QPushButton("1080p30 MP4 생성"); self.generate.setProperty("primary",True); self.generate.setEnabled(False); self.generate.clicked.connect(self.render_requested); self.export=QPushButton("파일 내보내기"); self.export.setEnabled(False); self.export.clicked.connect(self._export); self.result=QLabel(""); layout.addWidget(self.info); layout.addWidget(self.generate); layout.addWidget(self.export); layout.addWidget(self.result); layout.addStretch(1)
    def confirmed(self,cid,partial=False): self.info.setText(f"{'검토용 부분 순서' if partial else '확정본'} {cid}을 출력합니다."); self.generate.setEnabled(True)
    def rendered(self,path): self.result.setText(f"생성 완료: {path}"); self.export.setEnabled(True); self.video_path=Path(path)
    def _export(self):
        path,_=QFileDialog.getSaveFileName(self,"MP4 내보내기","PA2_assembly.mp4","MP4 (*.mp4)");
        if path:self.export_requested.emit(Path(path))


from .video_page import VideoPage


class MainWindow(QMainWindow):
    def __init__(self, app_root: Path) -> None:
        super().__init__(); self.app_root=app_root; self.layout=DataLayout.default(); self.database=Database(self.layout); self.database.initialize(); self.database.mark_interrupted_jobs(); self.settings_store=SettingsStore(); self.settings=self.settings_store.load(); self.assets=AssetStore(self.layout); self.cache=CacheStore(self.layout); self.projects=ProjectService(self.database); self.imports=ImportService(self.database,self.assets,self.cache); self.plans=PlanService(self.database); self.current_project=None; self.import_result=None; self.current_plan=None; self.confirmation_id=None; self.video_path=None; self.thread=None
        self.setWindowTitle("PA² · Pilot Assembly Assistant"); self.resize(1540,1010); self.setStyleSheet(STYLESHEET)
        self._confirmed_signature=None
        from pa2.learning.bootstrap import bootstrap
        try:self.model_bootstrap=bootstrap(self.database)
        except Exception as exc:self.model_bootstrap={'status':'FAILED','error':str(exc)}
        from pa2.uninstaller import register_data
        from pa2.runtime import install_root
        try:register_data(install_root(),self.layout.root)
        except Exception as exc:self.uninstall_registration_warning=str(exc)
        self.setWindowIcon(QIcon(str(app_root/'assets/pa2_icon.ico')))
        toolbar=QToolBar()
        toolbar.setObjectName("mainToolbar")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        self.brand_icon=QLabel()
        self.brand_icon.setObjectName("brandIcon")
        self.brand_icon.setAccessibleName("PA² 프로그램 아이콘")
        self.brand_icon.setFixedSize(36,36)
        self.brand_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.brand_icon.setPixmap(self.windowIcon().pixmap(QSize(32,32),self.devicePixelRatioF()))
        toolbar.addWidget(self.brand_icon)
        self.brand_title=QLabel("Pilot Assembly Assistant")
        self.brand_title.setObjectName("brandTitle")
        toolbar.addWidget(self.brand_title)
        spacer=QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Preferred)
        toolbar.addWidget(spacer)
        self.thn_logo=QLabel()
        self.thn_logo.setObjectName('thnLogo')
        self.thn_logo.setAccessibleName('THN 주식회사 티에이치엔')
        self.thn_logo.setToolTip('THN · 주식회사 티에이치엔')
        self.thn_logo.setFixedSize(150,40)
        self.thn_logo.setAlignment(Qt.AlignCenter)
        logo_pixmap=QPixmap(str(app_root/'assets/thn_logo.png')).scaled(
            QSize(144,36)*self.devicePixelRatioF(),Qt.KeepAspectRatio,Qt.SmoothTransformation)
        logo_pixmap.setDevicePixelRatio(self.devicePixelRatioF())
        self.thn_logo.setPixmap(logo_pixmap)
        toolbar.addWidget(self.thn_logo)
        self.cancel_action=QAction("작업 취소",self)
        self.cancel_action.setEnabled(False)
        self.cancel_action.triggered.connect(self._cancel_task)
        toolbar.addAction(self.cancel_action)
        settings_action=QAction("⚙ 설정",self)
        settings_action.triggered.connect(self._settings)
        toolbar.addAction(settings_action)
        learning_action=QAction('학습 현황',self)
        learning_action.triggered.connect(self._learning_status)
        toolbar.addAction(learning_action)
        self.tabs=QTabWidget(); self.setCentralWidget(self.tabs); self.project_page=ProjectPage(self.projects); self.model_page=ModelPage(); self.video_page=VideoPage(); self.tabs.addTab(self.project_page,"1  프로젝트"); self.tabs.addTab(self.model_page,"2  모델·순서"); self.tabs.addTab(self.video_page,"3  영상"); self.project_page.analyze_requested.connect(self._analyze); self.project_page.project_opened.connect(self._reopen); self.model_page.plan_requested.connect(self._generate); self.model_page.confirm_requested.connect(self._confirm); self.video_page.render_requested.connect(self._render); self.video_page.export_requested.connect(self._export); self.statusBar().showMessage("준비")

        self.model_page.preset_changed.connect(self._save_preset)
        self.model_page.save_requested.connect(self.plans.save_draft)
        self.model_page.manual_requested.connect(self._generate_manual)
        self.model_page.grouping_requested.connect(self._change_grouping)
        self.model_page.edit_state_changed.connect(self._refresh_confirmation_state)
        self.video_page.cleanup_requested.connect(self._keep_latest_video)
        from pa2.learning.idle import IdleLearningController
        self.idle_learning = IdleLearningController(self.database, lambda: self.settings,
            lambda: bool(self.thread and self.thread.isRunning())
                or self.model_page.play_timer.isActive() or self.model_page.preview_timer.isActive()
                or self.video_page.player.playbackState().name == 'PlayingState', self)
        if self.model_bootstrap.get('status')=='FAILED':self.statusBar().showMessage('모델 초기 적용 실패 · 기존 규칙 사용: '+self.model_bootstrap['error'])

    def _task(self,function,on_done):
        if self.thread and self.thread.isRunning(): QMessageBox.information(self,"작업 중","현재 작업이 끝난 뒤 다시 시도하세요."); return
        self.idle_learning.user_activity()
        self.cancel_event=threading.Event(); self.cancel_action.setEnabled(True)
        self.project_page.setEnabled(False)
        self.model_page.setEnabled(False);self.video_page.cleanup.setEnabled(False)
        self._task_callback=on_done
        self.thread=QThread(self); worker=TaskWorker(function,self.cancel_event)
        worker.moveToThread(self.thread); self.thread.started.connect(worker.run)
        # A plain Python closure has no QObject receiver thread. It previously
        # applied CAD results and created VTK/OpenGL state on the worker thread,
        # racing the main widget's paintEvent and crashing project reopen.
        worker.progress.connect(self._task_progress,Qt.QueuedConnection)
        worker.finished.connect(self._task_succeeded,Qt.QueuedConnection)
        worker.finished.connect(self.thread.quit)
        worker.failed.connect(self._task_failed,Qt.QueuedConnection)
        worker.failed.connect(self.thread.quit)
        worker.cancelled.connect(self._task_cancelled,Qt.QueuedConnection)
        worker.cancelled.connect(self.thread.quit)
        self.thread.finished.connect(worker.deleteLater)
        self.thread.finished.connect(self._task_thread_finished,Qt.QueuedConnection)
        self._worker=worker; self.thread.start()

    def _busy(self):
        if self.thread and self.thread.isRunning():
            QMessageBox.information(self,"작업 중","현재 작업이 끝난 뒤 다시 시도하세요.")
            return True
        return False

    @Slot(str,str)
    def _task_progress(self,stage,message):
        if not self.cancel_event.is_set():self.statusBar().showMessage(message)
        if stage=='video':
            import re
            match=re.search(r'(\d+)/(\d+)',message)
            if match:self.video_page.progress(int(match[1]),int(match[2]))

    @Slot(object)
    def _task_succeeded(self,result):
        callback=self._task_callback; self._task_callback=None
        try:
            if callback:callback(result)
        except Exception as exc:self._failed(f"{type(exc).__name__}: {exc}")

    @Slot(str)
    def _task_failed(self,message):
        self._log_generation_attempt('FAILED',message)
        self._task_callback=None; self._failed(message)
        self.video_page.stopped('작업 실패 · '+message)

    @Slot()
    def _task_cancelled(self):
        self._log_generation_attempt('CANCELLED','사용자 취소')
        self._task_callback=None
        self.statusBar().showMessage("작업을 취소했습니다. 기존 저장 결과는 유지됩니다.")
        self.video_page.stopped('작업 취소')

    @Slot()
    def _task_thread_finished(self):
        self.idle_learning.user_activity()
        self.cancel_action.setEnabled(False)
        self.project_page.setEnabled(True)
        self.model_page.setEnabled(True)
        self.video_page.cleanup.setEnabled(self.current_project is not None)
        self._refresh_confirmation_state()
    def _cancel_task(self):
        if hasattr(self,"cancel_event"):self.cancel_event.set(); self.statusBar().showMessage("취소 중 · 계산 프로세스를 종료하고 있습니다.")

    def _analyze(self,project,assembly,parts):
        if self._busy():return
        self.statusBar().showMessage("불러오기 준비 중")
        settings=self.settings
        def done(result):
            project=next(p for p in self.projects.list() if p.id==result.snapshot.project_id)
            self.current_project=project
            self._analyzed(result)
        self._task(lambda progress:self.imports.prepare(project.id,assembly,parts,settings,progress=progress,cancel_check=self.cancel_event.is_set),done)
    def _analyzed(self,result):
        self.current_plan=None; self.confirmation_id=None; self._confirmed_signature=None; self.video_path=None; self.video_page.reset()
        self.import_result=result; self.model_page.set_result(result,self.settings)
        self._restore_preset()
        self.tabs.setCurrentWidget(self.model_page); self.statusBar().showMessage("분석 준비 완료")

    def _restore_preset(self):
        preset=self.plans.load_preset(self.current_project.id,self.import_result.snapshot.id)
        if preset:
            self.model_page.base.blockSignals(True)
            index=self.model_page.base.findData(preset['base_group_id'])
            if index>=0:self.model_page.base.setCurrentIndex(index)
            self.model_page.base.blockSignals(False)
            valid={g.id for g in self.import_result.snapshot.groups}
            self.model_page.set_exceptions([g for g in preset['exception_ids'] if g in valid])

    def _save_preset(self):
        if not self.import_result or not self.current_project:return
        if not self.model_page.base.currentData():return
        try:
            self.plans.save_preset(self.current_project.id,self.import_result.snapshot.id,
                self.model_page.base.currentData(),self.model_page.exception_ids)
        except (ValueError,KeyError) as exc:
            self.model_page.status.setText(str(exc))
    def _reopen(self,project):
        if self._busy():return
        def done(result):
            self.plans.recover_original(result.snapshot.project_id)
            project=next(p for p in self.projects.list() if p.id==result.snapshot.project_id)
            self.current_project=project
            self.confirmation_id=None; self._confirmed_signature=None; self.video_path=None; self.video_page.reset()
            self.import_result=result; self.model_page.set_result(result,self.settings); self.current_plan=self.plans.load_current_draft(project.id)
            self._restore_preset()
            if self.current_plan:self.model_page.set_plan(self.current_plan,"저장된 초안을 복원했습니다.")
            if project.current_confirmation_id:
                self.confirmation_id=project.current_confirmation_id
                self._confirmed_signature=self.plans.content_signature(self.plans.load_confirmation(self.confirmation_id))
                partial=bool(self.current_plan and len(self.current_plan.steps)<len(self.current_plan.group_ids)-1)
                self.video_page.confirmed(self.confirmation_id,partial)
                videos=sorted((self.layout.projects/project.id/'videos').glob(f'{self.confirmation_id}*.mp4'),key=lambda path:path.stat().st_mtime,reverse=True)
                if videos:self.video_path=videos[0]; self.video_page.rendered(videos[0])
            self.tabs.setCurrentWidget(self.model_page); self.statusBar().showMessage("프로젝트 재열기 완료 · STEP 재분석 생략")
        self._task(lambda progress:self.imports.reopen(project.id),done)

    def _change_grouping(self,request):
        if self._busy() or not self.import_result:return
        imported=self.import_result;project_id=self.current_project.id
        base=self.model_page.base.currentData();exceptions=list(self.model_page.exception_ids)
        def work(progress):
            progress('grouping','부품 그룹 구성을 저장하는 중')
            ManualGroupingService(self.database).change(imported,request['ids'],name=request.get('name'),
                ungroup=request.get('ungroup',False),base_id=base,exception_ids=exceptions)
            return self.imports.reopen(project_id)
        def done(result):
            self.current_project=next(p for p in self.projects.list() if p.id==project_id)
            self._analyzed(result);self.project_page.refresh()
            self.model_page.status.setText('그룹 구성 저장 완료 · 순서를 다시 생성하세요. 자동 그룹 내부는 유지됩니다.')
        self._task(work,done)

    def _refresh_confirmation_state(self):
        if not hasattr(self,'video_page'):return
        if self.thread and self.thread.isRunning():return
        plan=self.model_page.plan
        if not plan:
            self.video_page.generate.setEnabled(False)
            return
        pending=self.model_page.has_pending_fields()
        valid=bool(self.confirmation_id and self._confirmed_signature
                   and self.plans.content_signature(plan)==self._confirmed_signature and not pending)
        self.video_page.generate.setEnabled(valid)
        if not valid:self.video_page.require_confirmation(pending)
    def _generate(self,base):
        if self._busy():return
        if not self.import_result:return
        exceptions=list(self.model_page.exception_ids)
        if base in exceptions:
            QMessageBox.warning(self,'설정 확인','기준 부품은 간섭 예외로 지정할 수 없습니다.'); return
        self.plans.save_preset(self.current_project.id,self.import_result.snapshot.id,base,exceptions)
        settings=self.settings
        imported=self.import_result; project=self.current_project
        from pa2.learning.registry import ModelRegistry
        registry = ModelRegistry(self.database)
        pinned_models = registry.active_pair()
        self._generation_context=(project.id,'auto',time.monotonic(),pinned_models)
        def work(progress):
            self.imports.ensure_contacts(imported,settings,progress=progress,cancel_check=self.cancel_event.is_set)
            if not imported.snapshot.calculation_ready:
                graph=next((item for item in imported.snapshot.diagnostics if item.get("code")=="CONTACT_GRAPH"),{})
                raise ValueError(f"접촉 계산 후에도 미판정 {len(graph.get('unknown_pairs',[]))}쌍이 남았습니다. 설정의 시간 제한과 분석 진단을 확인하세요.")
            progress("planning","분해 경로를 탐색하는 중")
            actual_base = Planner.choose_base([g for g in imported.snapshot.groups if g.id not in exceptions], base or None)
            provider = registry.provider(imported.snapshot.groups, imported.snapshot.contacts,
                actual_base, project.product_type, pair=pinned_models)
            return Planner(settings).generate(project.id,imported.snapshot.project_revision,imported.snapshot.id,imported.snapshot.groups,imported.snapshot.contacts,imported.assembly_scene.shapes,base or None,priority_provider=provider,cancel_check=self.cancel_event.is_set,progress=progress,jobs_dir=self.layout.jobs,collision_exception_ids=exceptions)
        self._task(work,self._planned)
        if self.thread and self.thread.isRunning():self.model_page.setEnabled(False)

    def _generate_manual(self, request):
        if self._busy() or not self.import_result:return
        imported=self.import_result;project=self.current_project;settings=self.settings
        base=request['base'];exceptions=list(self.model_page.exception_ids)
        if base in exceptions:
            QMessageBox.warning(self,'설정 확인','기준 부품은 간섭 예외로 지정할 수 없습니다.');return
        self.plans.save_preset(project.id,imported.snapshot.id,base,exceptions)
        self._generation_context=(project.id,'manual',time.monotonic(),{})
        def work(progress):
            # Saved complete contacts are reused. Manual mode deliberately does
            # not upgrade contacts or invoke the automatic planner/native worker.
            return ManualPlanner(settings).generate(project.id,imported.snapshot.project_revision,
                imported.snapshot.id,imported.snapshot.groups,imported.snapshot.contacts,
                imported.assembly_scene.shapes,base,display_order=request['display_order'],
                collision_exception_ids=exceptions,cancel_check=self.cancel_event.is_set,progress=progress)
        self._task(work,self._planned)
    def _log_generation_attempt(self,status,details):
        context=getattr(self,'_generation_context',None)
        if context:
            from pa2.run_log import safe_log
            pid,mode,started,models=context
            safe_log(self,'attempt',pid,mode,status,time.monotonic()-started,{'message':details,'models_selected':models})
            self._generation_context=None

    def _planned(self,result):
        if result.status == PlanningStatus.CANCELLED:
            self._log_generation_attempt('CANCELLED',result.reason)
            self.statusBar().showMessage("순서 생성을 취소했습니다. 기존 초안은 유지됩니다."); return
        if result.assembly_plan is None:
            self._log_generation_attempt(result.status.value,result.reason)
            self.statusBar().showMessage('생성된 순서가 없습니다. 기존 초안을 유지합니다.');return
        context=getattr(self,'_generation_context',None)
        if context:
            result.metrics['generation_wall_sec']=time.monotonic()-context[2]
            result.metrics['models_selected']=context[3]
        self.current_plan=result.assembly_plan; self.plans.save_generated(result,self.settings)
        self._generation_context=None
        if getattr(self.plans,'log_warning',None):QMessageBox.warning(self,'로그 기록 경고',self.plans.log_warning+'\n순서 데이터는 프로젝트에 저장되었습니다.')
        self.confirmation_id=None;self._confirmed_signature=None;self.video_path=None;self.video_page.reset()
        m=result.metrics
        brief=f"실제 후보 {m.get('tested_candidates',0)} · 신규 경로 {m.get('native_path_calls',0)} · {m.get('elapsed_sec',0):.1f}초"
        self.model_page.set_plan(self.current_plan,f"{result.status.value}: {result.reason}\n{brief}")
        full=len(self.current_plan.steps)==len(self.current_plan.group_ids)-1
        self.statusBar().showMessage("순서 생성 완료" if result.status==PlanningStatus.COMPLETE else "전체 초안 생성 완료 · 편집 후 확정하세요." if full else "순서 생성 종료 · 부분 결과와 진단을 확인하세요.")
        path=self.layout.projects/self.current_project.id/"planning"/f"{self.current_plan.id}.json"
        path.parent.mkdir(parents=True,exist_ok=True)
        temporary=path.with_suffix(".tmp"); temporary.write_text(json.dumps(asdict(result),ensure_ascii=False,indent=2),encoding="utf-8"); temporary.replace(path)
        self.model_page.set_planning_diagnostics(result,path)
    def _confirm(self,plan):
        if self._busy():return
        try:
            if self.model_page.has_pending_fields():
                raise ValueError('작업 속성의 수정값을 먼저 선택 단계에 적용한 뒤 순서를 확정하세요.')
            self.model_page.preview()
            partial=len(plan.steps)<len(set(plan.group_ids)-{plan.base_group_id})
            self.confirmation_id=self.plans.confirm(plan,allow_partial=partial); self.current_plan=plan
            self.video_path=None
            self._confirmed_signature=self.plans.content_signature(plan)
            self.last_collection=collect_confirmation(self.database,self.plans,self.confirmation_id,
                self.import_result,self.current_project.product_type)
            if getattr(self.plans,'log_warning',None):QMessageBox.warning(self,'로그 기록 경고',self.plans.log_warning+'\n확정본은 프로젝트에 저장되었습니다.')
            comparison=self.last_collection['comparison']
            if comparison.get('available'):
                values=comparison['general_without_exceptions']
                ratio=values['pair_order_ratio']
                self.statusBar().showMessage('확정·학습 기록 저장 완료 · 일반 부품 선후 유지율 '+
                    (f'{ratio:.1%}' if ratio is not None else '비교 대상 부족'))
            self.video_page.confirmed(self.confirmation_id,partial); self.tabs.setCurrentWidget(self.video_page)
        except Exception as exc:QMessageBox.warning(self,"확정할 수 없음",str(exc))

    def _learning_status(self):
        if self._busy():return
        status=learning_status(self.database,self.settings)
        from pa2.learning.registry import ModelRegistry
        registry=ModelRegistry(self.database); lifecycle=registry.status()
        dialog=QDialog(self);dialog.setWindowTitle('자동 수집·학습 현황');dialog.resize(800,650)
        layout=QVBoxLayout(dialog);text=QTextEdit();text.setReadOnly(True)
        lines=[f"독립 형상 계열: {status['family_count']} (초기 모델 없는 경우 기준 {self.settings.training_min_families})",
            f"일반 부품 순서 선택 사례: {status['state_count']} (초기 모델 없는 경우 기준 {self.settings.training_min_states})",
            f"중복 제외 확정 관찰 기록: {status['observation_count']}",status.get('common_reason',status['reason']),status['note'],
            '', '예외 부품 포함 전체 확정 기록을 보존합니다.',
            '사용자 선호와 실제 CAD 통과·간섭·미판정은 분리합니다.',
            '두 모델은 동일 데이터·계열 분리 기준으로 순서 → 방향 순차 학습합니다.',
            f'재학습: 신규 완전 확정 프로젝트 {self.settings.retrain_new_projects}개 추가마다 · 재확정 중복 제외',
            f"자동 학습: {'켜짐' if self.settings.auto_learning_enabled else '꺼짐'} / 자동 적용: {'켜짐' if self.settings.auto_model_apply_enabled else '꺼짐'}",
            '상태: '+self.idle_learning.message,
            '현재 순서 모델: '+str(lifecycle['active']['ranking'] or '기존 규칙'),
            '현재 방향 모델: '+str(lifecycle['active']['direction'] or '기존 규칙'),
            '학습 중 사용자 작업이 시작되면 보류합니다. 기존 확정 순서·영상은 변경하지 않습니다.']
        qualified = status.get('qualified', {})
        if qualified:
            lines += [f"공통 주기 유효 데이터 (프로젝트별 최신 완전 확정본·중복 제외): {qualified['families']}계열 / {qualified['states']}선택 사례",
                      '초기 모델 적용 이후 신규 프로젝트 수로 재학습하며, 변형 제품도 프로젝트별 1회 집계합니다.']
        for cycle in lifecycle['cycles']:
            lines += ['', f"주기 {cycle['id']} · {cycle['status']} · {cycle['phase']}"]
            if cycle['error']:lines.append(cycle['error'])
            detail=cycle['result'].get('direction_data', {})
            if detail:lines.append('방향 데이터: '+detail.get('reason',''))
        for entry in lifecycle['history']:
            lines.append(f"{entry['date']} · {entry['reason']} · {entry['pair']}")
        if self.current_plan and self.confirmation_id:
            from pa2.storage.database import ConfirmationAnalysis
            with self.database.session() as session:
                row=session.get(ConfirmationAnalysis,self.confirmation_id)
            if row:
                lines+=['','현재 확정본과 최초 생성 원본 비교 (선호 지표; 간섭 정확도 아님)']
                for key,label in [('all','전체'),('general','일반 부품'),('general_without_exceptions','일반·예외 제외')]:
                    m=row.metrics_json[key]
                    pct=lambda v: '—' if v is None else f'{v:.1%}'
                    lines.append(f"{label}: 선후 {pct(m['pair_order_ratio'])} · LCS {pct(m['lcs_ratio'])} · 방향 {pct(m['direction_agreement'])}")
        text.setPlainText('\n'.join(lines));layout.addWidget(text)
        restore=QPushButton('이전 모델로 복원');restore.setEnabled(any(lifecycle['active'].values()))
        def rollback():
            if QMessageBox.question(dialog,'모델 복원','이전 검증 모델 구성으로 복원할까요? 이전 모델이 없으면 기존 규칙을 사용합니다. 기존 순서·영상은 바뀌지 않습니다.') != QMessageBox.StandardButton.Yes:return
            self.idle_learning.pause('사용자 요청: 이전 모델 복원')
            try:
                pair=registry.rollback();text.append('\n복원 완료: '+str(pair));restore.setEnabled(any(pair.values()))
            except Exception as exc:QMessageBox.warning(dialog,'복원 보류',str(exc))
        restore.clicked.connect(rollback);layout.addWidget(restore)
        pending = next((c for c in lifecycle['cycles'] if c['status']=='READY'), None)
        apply_model=QPushButton('평가 통과 모델 적용');apply_model.setEnabled(bool(pending))
        def apply_candidate():
            if not pending:return
            if QMessageBox.question(dialog,'모델 적용','분리 계열·실제 CAD 비교를 통과한 모델 구성을 다음 자동 생성부터 사용할까요?') != QMessageBox.StandardButton.Yes:return
            self.idle_learning.pause('사용자가 평가 통과 모델 적용')
            try:
                from pa2.learning.pipeline import policy_signature
                if policy_signature(AppSettings(**pending['settings'])) != policy_signature(self.settings):
                    raise ValueError('평가 이후 설정이 변경되었습니다. 기존 모델을 유지하며 재평가가 필요합니다.')
                pair=registry.promote(pending['id']);text.append('\n적용 완료: '+str(pair));apply_model.setEnabled(False);restore.setEnabled(True)
            except Exception as exc:QMessageBox.warning(dialog,'적용 보류',str(exc))
        apply_model.clicked.connect(apply_candidate);layout.addWidget(apply_model)
        close=QPushButton('닫기');close.clicked.connect(dialog.accept);layout.addWidget(close);dialog.exec()
    def _render(self):
        if not all((self.current_plan,self.import_result,self.confirmation_id)):return
        if self.thread and self.thread.isRunning():return
        self.model_page._commit_order()
        if self.model_page.has_pending_fields() or not self.plans.matches_confirmation(self.model_page.plan,self.confirmation_id):
            self.video_page.require_confirmation(self.model_page.has_pending_fields())
            QMessageBox.information(self,'순서 확정 필요','수정값을 적용하고 순서를 다시 확정한 뒤 영상을 생성하세요.');return
        render_plan=self.plans.load_confirmation(self.confirmation_id)
        if render_plan.input_snapshot_id!=self.import_result.snapshot.id:
            QMessageBox.warning(self,'순서 재생성 필요','그룹 구성이 변경됐습니다. 순서를 다시 생성하고 확정하세요.');return
        imported=self.import_result; project=self.current_project
        output=self.layout.projects/self.current_project.id/"videos"/f"{self.confirmation_id}-{uuid.uuid4().hex[:8]}.mp4"; renderer=VideoRenderer(self.settings,self.app_root/"assets/video_template_v1.json",self.app_root/"assets/thn_logo.png")
        self.video_page.started()
        self._task(lambda progress:renderer.render(render_plan,imported.assembly_scene,imported.snapshot.groups,output,vehicle_name=project.vehicle_type,product_name=project.product_type,project_name=project.name,cancel_event=self.cancel_event,progress=lambda a,b:progress("video",f"영상 프레임 {a}/{b}")),lambda result:(setattr(self,"video_path",result.path),self.video_page.rendered(result.path)))
    def _keep_latest_video(self):
        if self._busy() or not self.current_project:return
        project_id=self.current_project.id
        self.video_page.player.stop();self.video_page.player.setSource(QUrl())
        def done(result):
            if result['kept']:
                self.video_path=Path(result['kept']);self.video_page.rendered(self.video_path)
            freed=result['freed_bytes']/1024**2
            text=f"이전 영상 {len(result['deleted'])}개 삭제 · {freed:.2f} MiB 확보"
            if result['errors']:text+=f" · 삭제하지 못한 파일 {len(result['errors'])}개"
            if not result['kept']:text='정상 생성된 보관 영상이 없습니다. 삭제하지 않았습니다.'
            self.video_page.result.setText(text)
            self.last_cleanup_result=result
            self._refresh_confirmation_state()
        self._task(lambda progress:VideoLibrary(self.database,self.layout).keep_latest(project_id),done)
    def _export(self,destination):
        if not self.video_path:return
        try:VideoRenderer(self.settings,self.app_root/"assets/video_template_v1.json",self.app_root/"assets/thn_logo.png").export(self.video_path,destination); QMessageBox.information(self,"내보내기 완료",str(destination))
        except Exception as exc:QMessageBox.warning(self,"내보내기 실패",str(exc))
    def _settings(self):
        dialog=SettingsDialog(self.settings_store,self.settings,self)
        def saved(value):self.settings=value; self.model_page.settings=value
        dialog.saved.connect(saved); dialog.exec()
    def _failed(self,message): QMessageBox.critical(self,"작업 실패",message); self.statusBar().showMessage("작업 실패")

    def closeEvent(self,event):
        self.idle_learning.close()
        if self.thread and self.thread.isRunning():
            self._cancel_task(); event.ignore(); QTimer.singleShot(300,self.close); return
        self.model_page._stop_preview(); self.model_page.thumbnail_timer.stop()
        self.model_page.play_timer.stop(); self.video_page.player.stop(); self.video_page.video.setFullScreen(False)
        scene=self.model_page.vtk_scene
        if scene._thumbnail_window is not None:scene._thumbnail_window.Finalize()
        scene.render_window.Finalize()
        super().closeEvent(event)

