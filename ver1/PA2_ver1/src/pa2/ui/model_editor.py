"""PILOT-style horizontal sequence editor; manual edits never call CAD checks."""
import copy
from PySide6.QtCore import Qt, QSize, Signal, QSignalBlocker, QItemSelectionModel, QTimer
from PySide6.QtGui import QIcon, QImage, QPixmap, QAction, QActionGroup
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QSplitter,
    QLabel, QPushButton, QComboBox, QListWidget, QAbstractItemView, QSpinBox, QSlider,
    QGroupBox, QScrollArea, QFrame, QMenu)
from pa2.domain.models import GeometryStatus, MatchingStatus
from .group_dialog import ManualGroupDialog
from pa2.rendering.scene import build_timeline, scene_at
from .transport import configure_transport, update_play_button
from .viewport import ModelViewport, ViewportMenuButton, configure_viewport_button, viewport_icon


from .sequence_cards import SequenceCards


def enhanced_model_page(legacy):
    class ModelEditor(legacy):
        save_requested = Signal(object)
        manual_requested = Signal(object)
        grouping_requested = Signal(object)
        edit_state_changed = Signal()

        def __init__(self):
            super().__init__()
            self._syncing = False; self._undo = []; self._redo = []; self._icons = {}
            self._step_preview = None
            self._part_isolation_snapshot = None
            self._visibility_restore = None
            self._timeline_focus = False
            self.preview_timer=QTimer(self); self.preview_timer.timeout.connect(self._preview_tick)
            self.thumbnail_timer=QTimer(self); self.thumbnail_timer.timeout.connect(self._next_thumbnail)
            self._legacy_container = QWidget(self)
            self._legacy_container.setLayout(self.layout()); self._legacy_container.hide()
            root = QVBoxLayout(self); root.setContentsMargins(16,10,16,8); root.setSpacing(8)
            bar = QHBoxLayout(); self.project_heading=QLabel('모델 · 조립 순서 편집'); bar.addWidget(self.project_heading); bar.addStretch()
            self.auto_generate = QPushButton('자동생성'); self.auto_generate.setProperty('primary', True)
            self.auto_generate.clicked.connect(lambda: self.plan_requested.emit(self.base.currentData() or ''))
            self.manual_generate = QPushButton('수동생성')
            self.manual_generate.setToolTip('목록 순서로 즉시 배치 · 일반 부품 분해 +Z 기본값 · 경로 검사 생략')
            self.manual_generate.clicked.connect(lambda: self.manual_requested.emit({
                'base': self.base.currentData() or '',
                'display_order': [self.parts.item(i).data(Qt.UserRole) for i in range(self.parts.count())]}))
            bar.addWidget(self.auto_generate); bar.addWidget(self.manual_generate); root.addLayout(bar)
            split = QSplitter(Qt.Horizontal)
            left = QFrame();left.setObjectName('whiteCard');left.setMinimumWidth(200)
            ll = QVBoxLayout(left);ll.setContentsMargins(14,12,14,12);ll.setSpacing(12)
            self.parts_heading=QLabel('부품 목록');self.parts_heading.setProperty('cardTitle',True)
            ll.addWidget(self.parts_heading);ll.addWidget(self.search);ll.addWidget(self.parts)
            self.parts.setSelectionMode(QAbstractItemView.ExtendedSelection)
            self.parts.setToolTip('Ctrl/Shift 다중선택: 선택 부품은 빨간색, 나머지는 회색·투명도 90%로 표시합니다. 직접 숨긴 부품은 유지됩니다.')
            grouping=QHBoxLayout()
            self.group_button=QPushButton('그룹화');self.ungroup_button=QPushButton('그룹해제')
            self.group_button.clicked.connect(self._group_selected);self.ungroup_button.clicked.connect(self._ungroup_selected)
            grouping.addWidget(self.group_button);grouping.addWidget(self.ungroup_button);ll.addLayout(grouping)
            center = QWidget(); cl = QVBoxLayout(center); cl.setContentsMargins(6,0,6,0); cl.setSpacing(6)
            self.orbit = QPushButton('회전'); self.pan = QPushButton('이동')
            self.orbit.setCheckable(True); self.pan.setCheckable(True); self.orbit.setChecked(True)
            self.orbit.clicked.connect(lambda: self._navigation(False)); self.pan.clicked.connect(lambda: self._navigation(True))
            self.views = QComboBox(); self.views.addItems(['등각','상면','하면','정면','후면','좌측','우측'])
            self.views.setParent(self._legacy_container)
            self.views.currentTextChanged.connect(self._view)
            self.viewer_surface=ModelViewport(self.vtk_widget)
            tools=self.viewer_surface.tools
            old_fit=self.fit_button;old_fit.hide();old_fit.deleteLater()
            self.fit_button=QPushButton(self.viewer_surface.toolbar)
            self.fit_button.clicked.connect(self.vtk_scene.fit)
            self.viewport_buttons={}
            for button,name,title in ((self.orbit,'rotate','회전'),(self.pan,'pan','이동'),(self.fit_button,'fit','화면 맞춤')):
                configure_viewport_button(button,name,title);tools.addWidget(button);self.viewport_buttons[name]=button
            self.view_menu_button=ViewportMenuButton();configure_viewport_button(self.view_menu_button,'view','시점 선택')
            menu=QMenu(self.view_menu_button);group=QActionGroup(menu);group.setExclusive(True)
            for name in ('등각','상면','하면','정면','후면','좌측','우측'):
                action=QAction(name,menu);action.setCheckable(True);action.setChecked(name=='등각');group.addAction(action);menu.addAction(action)
                action.triggered.connect(lambda checked,n=name:self.views.setCurrentText(n))
                self.views.currentTextChanged.connect(lambda value,a=action:a.setChecked(a.text()==value))
            self.view_menu_button.setMenu(menu);tools.addWidget(self.view_menu_button);self.viewport_buttons['view']=self.view_menu_button
            for name,title,factor in [('zoom_out','축소',.8),('zoom_in','확대',1.25)]:
                button=QPushButton();configure_viewport_button(button,name,title)
                button.clicked.connect(lambda _,f=factor:self.vtk_scene.zoom(f));tools.addWidget(button);self.viewport_buttons[name]=button
            self.visibility_button=QPushButton();configure_viewport_button(self.visibility_button,'show','선택 부품 숨기기')
            self.visibility_button.setCheckable(True);self.visibility_button.setObjectName('visibilityToggle')
            self._visibility_icons={False:viewport_icon('show'),True:viewport_icon('hide')}
            self.visibility_button.clicked.connect(self._toggle_part_visibility)
            tools.addWidget(self.visibility_button);self.viewport_buttons['visibility']=self.visibility_button
            viewer=QFrame();viewer.setObjectName('viewerFrame');vl=QVBoxLayout(viewer);vl.setContentsMargins(1,1,1,1)
            vl.addWidget(self.viewer_surface);cl.addWidget(viewer,1)
            playback_widget=QWidget(); playback_widget.setObjectName('playbackBar')
            playback=QHBoxLayout(playback_widget); playback.setContentsMargins(8,4,8,4); playback.setSpacing(4)
            self.first_button=QPushButton(); self.previous_button=QPushButton()
            self.next_button=QPushButton(); self.last_button=QPushButton()
            for button,name,tooltip in ((self.first_button,'first','처음으로'),(self.previous_button,'previous','이전 단계'),
                                        (self.next_button,'next','다음 단계'),(self.last_button,'last','끝으로')):
                configure_transport(button,name,tooltip)
            self.first_button.clicked.connect(lambda:self._jump_end(False))
            self.previous_button.clicked.connect(lambda:self._neighbor(-1))
            self.next_button.clicked.connect(lambda:self._neighbor(1))
            self.last_button.clicked.connect(lambda:self._jump_end(True))
            update_play_button(self.play,False)
            for button in (self.first_button,self.previous_button,self.play,self.next_button,self.last_button):playback.addWidget(button)
            self.time_label=QLabel('0.0 / 0.0s'); self.time_label.setProperty('muted',True); self.time_label.setMinimumWidth(96)
            playback.addWidget(self.time_label); playback.addWidget(self.speed)
            self.speed.setFixedWidth(62); self.speed.setToolTip('재생 배속')
            playback.addWidget(QLabel('×')); playback.addStretch()
            self.playback_state=QLabel('완성 형상'); self.playback_state.setProperty('muted',True); playback.addWidget(self.playback_state)
            self.speed.setCurrentText('1')
            self.scrubber=QSlider(Qt.Horizontal); self.scrubber.setRange(0,10000); self.scrubber.sliderMoved.connect(self._seek)
            cl.addWidget(playback_widget); cl.addWidget(self.scrubber)
            right=QWidget(); right.setObjectName('propertiesBody'); form=QFormLayout(right)
            self.base_assign=QPushButton('선택 부품을 기준으로 지정'); self.base_assign.clicked.connect(self._assign_base)
            self.exception_add=QPushButton('선택 → 예외 지정'); self.exception_add.clicked.connect(lambda:self._set_selected_exceptions(True))
            self.exception_remove=QPushButton('선택 예외 해제'); self.exception_remove.clicked.connect(lambda:self._set_selected_exceptions(False))
            form.addRow('기준 부품',self.base); form.addRow(self.base_assign); form.addRow(self.exception_button)
            role_buttons=QHBoxLayout(); role_buttons.addWidget(self.exception_add); role_buttons.addWidget(self.exception_remove); form.addRow(role_buttons)
            form.addRow('분해 방향',self.direction); form.addRow('거리',self.distance); form.addRow('카메라',self.camera)
            self._camera_roll_deg=0
            roll_row=QHBoxLayout()
            self.camera_roll_left=QPushButton('↶ 90°');self.camera_roll_right=QPushButton('↷ 90°')
            self.camera_roll_label=QLabel('0°')
            for button,delta,label in ((self.camera_roll_left,-90,'화면 왼쪽으로 90도 회전'),
                                      (self.camera_roll_right,90,'화면 오른쪽으로 90도 회전')):
                button.setToolTip(label+' · 모델/조립 방향은 유지 · 미리보기로 확인 후 적용')
                button.setAccessibleName(label)
                button.clicked.connect(lambda checked=False,d=delta:self._rotate_camera(d))
                roll_row.addWidget(button)
            roll_row.addWidget(self.camera_roll_label);form.addRow('화면 회전',roll_row)
            self.camera_roll_label.setToolTip('탑뷰는 완성 모델의 긴 쪽을 가로로 자동 정렬합니다. 표시 각도는 자동 정렬에 더하는 사용자 회전값입니다.')
            self.step_preview_button=QPushButton('미리보기'); self.step_preview_button.clicked.connect(self._preview_step)
            self.step_preview_button.setToolTip('입력 중인 방향·거리·카메라로 선택 단계 재생')
            form.addRow(self.step_preview_button)
            for title,widget in [('조립 과정',self.process),('자재정보',self.material),('주의사항',self.caution)]:
                widget.setMaximumHeight(72); form.addRow(title,widget)
            self.apply_button=QPushButton('선택 단계에 적용'); self.apply_button.clicked.connect(self._apply_step); form.addRow(self.apply_button)
            forward=QPushButton('이 뒤로 과정 문구 적용'); forward.clicked.connect(self._apply_forward); form.addRow(forward)
            scroll=QScrollArea(); scroll.setWidgetResizable(True); scroll.setWidget(right)
            properties=QFrame();properties.setObjectName('whiteCard');properties.setMinimumWidth(310);properties.setMaximumWidth(365)
            properties_layout=QVBoxLayout(properties);properties_layout.setContentsMargins(14,12,14,12);properties_layout.setSpacing(12)
            self.properties_heading=QLabel('작업 속성');self.properties_heading.setProperty('cardTitle',True)
            properties_layout.addWidget(self.properties_heading);properties_layout.addWidget(scroll)
            split.addWidget(left); split.addWidget(center); split.addWidget(properties); split.setSizes([215,920,345]); root.addWidget(split,1)
            self.order=SequenceCards(); self.order.currentItemChanged.connect(self._edit_step)
            self.order.itemSelectionChanged.connect(self._order_selection); self.order.itemChanged.connect(self._checked)
            self.order.reordered.connect(self._reordered)
            self.order.drag_started.connect(self._pause_for_card_drag)
            stepsbox=QGroupBox('조립 순서'); steps_layout=QVBoxLayout(stepsbox)
            actions=QHBoxLayout()
            self.selection_label=QLabel('0개 선택'); actions.addWidget(self.selection_label); actions.addStretch()
            self.undo_button=QPushButton('실행 취소'); self.undo_button.clicked.connect(lambda:self._history(False))
            self.redo_button=QPushButton('다시 실행'); self.redo_button.clicked.connect(lambda:self._history(True))
            for b in (self.undo_button,self.redo_button):actions.addWidget(b)
            saved_label=QLabel('초안·편집 자동 저장');saved_label.setProperty('muted',True);actions.addWidget(saved_label)
            confirm=QPushButton('순서 확정'); confirm.setProperty('primary',True); confirm.clicked.connect(lambda:self.confirm_requested.emit(self.plan) if self.plan else None); actions.addWidget(confirm)
            steps_layout.addWidget(self.order); steps_layout.addLayout(actions)
            move=QHBoxLayout()
            for text,fn in [('전체 선택',self.order.selectAll),('현재 부품만',self._single),('앞으로',lambda:self._move(-1)),('뒤로',lambda:self._move(1))]:
                b=QPushButton(text); b.clicked.connect(fn); move.addWidget(b)
            move.addWidget(QLabel('묶음 시작 단계')); self.position=QSpinBox(); self.position.setMinimum(1); move.addWidget(self.position)
            jump=QPushButton('이동'); jump.clicked.connect(lambda:self.order.move_selection(self.position.value()-1)); move.addWidget(jump)
            preview=QPushButton('미리보기 갱신'); preview.clicked.connect(self.preview); move.addWidget(preview)
            self.diagnostics_button.hide()  # Keep diagnostic collection, not a user-facing control.
            steps_layout.addLayout(move)
            root.addWidget(stepsbox)
            root.addWidget(self.status)
            if not self.headless:
                self.vtk_scene.configure_interaction(self.vtk_widget.GetRenderWindow().GetInteractor(),self._picked,self.vtk_widget)
            self.base.currentIndexChanged.connect(self._base_changed)
            for signal in (self.direction.currentTextChanged,self.distance.valueChanged,self.camera.currentTextChanged,
                           self.process.textChanged,self.material.textChanged,self.caution.textChanged):
                signal.connect(self._notify_edit)
            self._update_group_buttons()
            self._sync_playback()

        def _notify_edit(self,*_):
            if not self._syncing:self.edit_state_changed.emit()

        def _pause_for_card_drag(self):
            self._stop_preview();self.play_timer.stop();self._timeline_focus=False;self._sync_playback()

        def _manual_ids(self):
            structure=getattr(self.result,'grouping_structure',None) if self.result else None
            return {n['id'] for n in (structure or {}).get('roots',[]) if n['kind']=='manual'}

        def _update_group_buttons(self):
            if not hasattr(self,'group_button'):return
            ids={i.data(Qt.UserRole) for i in self.parts.selectedItems()}
            base=self.base.currentData()
            self.group_button.setEnabled(len(ids)>=2 and base not in ids)
            self.ungroup_button.setEnabled(len(ids)==1 and bool(ids & self._manual_ids()) and base not in ids)
            self.ungroup_button.setToolTip('수동 그룹만 해제할 수 있습니다. 자동 그룹은 하나의 부품으로 잠겨 있습니다.')

        def _group_selected(self):
            if not self.result:return
            ids={i.data(Qt.UserRole) for i in self.parts.selectedItems()}
            if len(ids)<2 or self.base.currentData() in ids:return
            groups=[g for g in self.result.snapshot.groups if g.id in ids]
            dialog=ManualGroupDialog(groups,self)
            if dialog.exec():
                self.grouping_requested.emit({'ids':list(ids),'name':dialog.group_name(),'ungroup':False})

        def _ungroup_selected(self):
            ids={i.data(Qt.UserRole) for i in self.parts.selectedItems()}
            if len(ids)==1 and ids & self._manual_ids() and self.base.currentData() not in ids:
                self.grouping_requested.emit({'ids':list(ids),'ungroup':True})

        def has_pending_fields(self):
            if not self.plan or not self.order.currentItem() or len(self.order.selectedItems())!=1:return False
            gid=self.order.currentItem().data(Qt.UserRole)
            step=next((s for s in self.plan.steps if s.group_id==gid),None)
            if not step:return False
            return (self.direction.currentText()!=self._direction_text(step.removal_direction)
                or round(self.distance.value(),self.distance.decimals())!=round(step.travel_mm,self.distance.decimals())
                or self.camera.currentText()!=step.camera_mode or self._camera_roll_deg!=step.camera_roll_deg
                or self.process.toPlainText()!=step.process_text
                or self.material.toPlainText()!=step.material_text or self.caution.toPlainText()!=step.caution_text)

        def set_result(self,result,settings):
            self._timeline_focus=False;self.order.set_active_step(None)
            self._clear_visibility_toggle(restore=False)
            self._stop_preview()
            self.play_timer.stop(); self.play_time=0.0
            self._part_isolation_snapshot=None
            self.thumbnail_timer.stop()
            self._syncing=True
            try: super().set_result(result,settings)
            finally:self._syncing=False
            self._icons={}; self._undo=[]; self._redo=[]
            self._view(self.views.currentText())
            manual=self._manual_ids();groups={g.id:g for g in result.snapshot.groups}
            for i in range(self.parts.count()):
                item=self.parts.item(i);group=groups[item.data(Qt.UserRole)]
                origin='수동 · 해제 가능' if group.id in manual else '자동 · 잠금' if group.matching_status==MatchingStatus.MATCHED else '미매칭'
                item.setText(f'{group.display_name}  [{origin}]')
            for widget in (self.direction,self.distance,self.camera,self.camera_roll_left,self.camera_roll_right,self.process,self.material,self.caution,self.apply_button,self.step_preview_button):
                widget.setEnabled(False)
            self._update_group_buttons()
            self._sync_playback()

        def _icon(self,gid):
            if gid not in self._icons:
                rgb=self.vtk_scene.thumbnail(gid); h,w,_=rgb.shape
                self._icons[gid]=QIcon(QPixmap.fromImage(QImage(rgb.data,w,h,w*3,QImage.Format_RGB888).copy()))
            return self._icons[gid]

        def set_plan(self,plan,message):
            self._timeline_focus=False;self.order.set_active_step(None)
            self._stop_preview()
            self._clear_visibility_toggle()
            self.play_timer.stop(); self.play_time=0.0
            self._clear_part_isolation()
            self.thumbnail_timer.stop()
            self._syncing=True
            try:
                super().set_plan(plan,message)
                names={g.id:g.display_name for g in self.result.snapshot.groups}
                for i,step in enumerate(plan.steps):
                    item=self.order.item(i)
                    if step.group_id in self._icons:item.setIcon(self._icons[step.group_id])
                    marker=' · 경로 확인 필요' if step.geometry_status==GeometryStatus.DRAFT_UNRESOLVED else ' · 예외' if step.geometry_status==GeometryStatus.USER_COLLISION_EXCEPTION else ''
                    item.setText(f'{i+1:02d}  {names[step.group_id]}\n분해 {self._direction_text(step.removal_direction)} · {step.travel_mm:.1f} mm{marker}')
                    item.setFlags(item.flags()|Qt.ItemIsUserCheckable); item.setCheckState(Qt.Unchecked)
                if plan.steps:self.order.setCurrentRow(0)
            finally:self._syncing=False
            self._update_group_buttons()
            self._order_selection()
            self._edit_step(self.order.currentItem(),None)
            self.undo_button.setEnabled(bool(self._undo)); self.redo_button.setEnabled(bool(self._redo))
            self.thumbnail_timer.start(10)
            self._sync_playback()

        def _next_thumbnail(self):
            pending=[self.order.item(i) for i in range(self.order.count())
                     if self.order.item(i).data(Qt.UserRole) not in self._icons]
            if not pending:self.thumbnail_timer.stop(); return
            visible=[item for item in pending if self.order.viewport().rect().intersects(self.order.visualItemRect(item))]
            item=(visible or pending)[0]
            item.setIcon(self._icon(item.data(Qt.UserRole)))

        @staticmethod
        def _direction_text(direction):
            return next((name for name,d in {'+X':(1,0,0),'-X':(-1,0,0),'+Y':(0,1,0),'-Y':(0,-1,0),'+Z':(0,0,1),'-Z':(0,0,-1)}.items() if sum(a*b for a,b in zip(direction,d))>.999),'자동')

        def _selected(self):
            return {item.data(Qt.UserRole) for item in (self.order.selectedItems() or self.parts.selectedItems())}

        def _clear_part_isolation(self,restore=True):
            previous=self._part_isolation_snapshot
            self._part_isolation_snapshot=None
            if restore and previous is not None:
                for gid,actor in self.vtk_scene.actors.items():
                    actor.SetVisibility(previous.get(gid,True))

        def _isolate_selected_parts(self,ids):
            # Selection styles properties only, never reveal explicitly hidden parts.
            self._clear_part_isolation()
            self.vtk_scene.highlight(ids)

        def _visibility_selected(self):
            items=self.parts.selectedItems() or self.order.selectedItems()
            return {item.data(Qt.UserRole) for item in items} & self.vtk_scene.actors.keys()

        def _sync_visibility_button(self):
            if not hasattr(self,'visibility_button'):return
            hidden=self._visibility_restore is not None
            self.visibility_button.setChecked(hidden);self.visibility_button.setIcon(self._visibility_icons[hidden])
            self.visibility_button.setEnabled(hidden or bool(self._visibility_selected()))
            label='숨긴 부품 복원' if hidden else '선택 부품 숨기기'
            self.visibility_button.setToolTip(label);self.visibility_button.setAccessibleName(label)

        def _clear_visibility_toggle(self,restore=True):
            previous=self._visibility_restore;self._visibility_restore=None
            if restore and previous is not None:
                for gid,actor in self.vtk_scene.actors.items():actor.SetVisibility(previous.get(gid,True))
            self._sync_visibility_button()

        def _toggle_part_visibility(self):
            self._stop_preview();self.play_timer.stop();self._sync_playback()
            if self._visibility_restore is not None:
                self._clear_visibility_toggle()
            else:
                selected=self._visibility_selected()
                if not selected:self._sync_visibility_button();return
                # Leave temporary multi-selection isolation before hiding the
                # selected batch, so the surrounding parts stay visible.
                self._clear_part_isolation()
                self._visibility_restore={gid:bool(actor.GetVisibility()) for gid,actor in self.vtk_scene.actors.items()}
                for gid in selected:self.vtk_scene.actors[gid].SetVisibility(False)
                self._sync_visibility_button()
            self.vtk_scene.highlight(self._visibility_selected())

        def _hide(self):
            self._stop_preview();self._clear_visibility_toggle();self._clear_part_isolation();super()._hide()

        def _solo(self):
            self._stop_preview();self._clear_visibility_toggle();self._clear_part_isolation();super()._solo()

        def _show_all(self):
            self._stop_preview();self._clear_visibility_toggle(restore=False);self._clear_part_isolation(restore=False);super()._show_all()

        def _order_selection(self,sync_parts=True):
            if self._syncing:return
            self._stop_preview()
            self.play_timer.stop();self._timeline_focus=False;self.order.set_active_step(None)
            # Sequence-card multi-selection is for moving steps, not grouping.
            self._clear_part_isolation()
            self._syncing=True
            try:
                selected={i.data(Qt.UserRole) for i in self.order.selectedItems()}
                for i in range(self.order.count()):
                    item=self.order.item(i); item.setCheckState(Qt.Checked if item.data(Qt.UserRole) in selected else Qt.Unchecked)
                if sync_parts:
                    self.parts.blockSignals(True)
                    for i in range(self.parts.count()):self.parts.item(i).setSelected(self.parts.item(i).data(Qt.UserRole) in selected)
                    self.parts.blockSignals(False)
                self.vtk_scene.highlight(selected)
                self.selection_label.setText(f'{len(selected)}개 선택')
                self.position.setMaximum(max(1,self.order.count()-len(selected)+1))
                rows=[self.order.row(i) for i in self.order.selectedItems()]
                if rows:self.position.setValue(min(rows)+1)
                for w in (self.direction,self.distance,self.camera,self.camera_roll_left,self.camera_roll_right,self.process,self.material,self.caution,self.apply_button,self.step_preview_button):w.setEnabled(len(selected)==1)
            finally:self._syncing=False
            self._update_group_buttons()
            self._sync_visibility_button()
            self._sync_playback()

        def _checked(self,item):
            if self._syncing:return
            item.setSelected(item.checkState()==Qt.Checked)
            self._order_selection()

        def _select_group(self):
            if self._syncing:return
            self._timeline_focus=False
            self._stop_preview();self.play_timer.stop();self._sync_playback()
            self._syncing=True
            ids={i.data(Qt.UserRole) for i in self.parts.selectedItems()}
            try:
                current=None
                for i in range(self.order.count()):
                    item=self.order.item(i); item.setSelected(item.data(Qt.UserRole) in ids)
                    if item.data(Qt.UserRole) in ids:current=item
                if current:self.order.setCurrentItem(current,QItemSelectionModel.NoUpdate)
            finally:self._syncing=False
            if current:self._order_selection(sync_parts=False); self._edit_step(current,None)
            self._isolate_selected_parts(ids)
            self.selection_label.setText(f'{len(ids)}개 선택')
            if len(ids)!=1:
                for widget in (self.direction,self.distance,self.camera,self.camera_roll_left,self.camera_roll_right,self.process,self.material,self.caution,self.apply_button,self.step_preview_button):widget.setEnabled(False)
            self._update_group_buttons()
            self._sync_visibility_button()
            # Clearing the sole selection also clears unapplied field state.
            # Refresh confirmation/render eligibility just as switching cards does.
            self.edit_state_changed.emit()

        def _picked(self,gid,extend=False):
            if not gid:return
            toggle_off = not extend and {i.data(Qt.UserRole) for i in self.parts.selectedItems()} == {gid}
            self.parts.blockSignals(True)
            for i in range(self.parts.count()):
                item=self.parts.item(i)
                item.setSelected(not toggle_off and ((item.isSelected() if extend else False) or item.data(Qt.UserRole)==gid))
            self.parts.blockSignals(False); self._select_group()

        def _edit_step(self,current,previous):
            if self._syncing or not current or not self.plan:return
            self._stop_preview()
            self._syncing=True
            try:
                super()._edit_step(current,previous)
                step=next(s for s in self.plan.steps if s.group_id==current.data(Qt.UserRole))
                self.direction.setCurrentText(self._direction_text(step.removal_direction))
                self._camera_roll_deg=step.camera_roll_deg
                self.camera_roll_label.setText(f'{self._camera_roll_deg}°')
            finally:self._syncing=False
            self.edit_state_changed.emit()

        def _record(self):
            if self.plan:self._undo.append(copy.deepcopy(self.plan)); self._undo=self._undo[-30:]; self._redo=[]

        def _rotate_camera(self,delta):
            if not self.plan or len(self.order.selectedItems())!=1:return
            self._stop_preview()
            self._camera_roll_deg=(self._camera_roll_deg+delta)%360
            self.camera_roll_label.setText(f'{self._camera_roll_deg}°')
            self._notify_edit()

        def _reordered(self):
            self._record(); self._commit_order(); self.status.setText('선택 단계 묶음 이동 · 내부 순서 유지'); self._renumber()
            self._save()
            self.edit_state_changed.emit()

        def _commit_order(self):
            if not self.plan:return
            ids=[self.order.item(i).data(Qt.UserRole) for i in range(self.order.count())]
            if ids!=[s.group_id for s in self.plan.steps]:self.plan.user_modified=True
            mapping={s.group_id:s for s in self.plan.steps}; self.plan.steps=[mapping[gid] for gid in ids]
            for i,step in enumerate(self.plan.steps,1):step.step_index=i

        def _renumber(self):
            selected=self._selected(); current=self.order.currentItem().data(Qt.UserRole) if self.order.currentItem() else None
            self.set_plan(self.plan,self.status.text())
            self._syncing=True
            for i in range(self.order.count()):
                item=self.order.item(i); item.setSelected(item.data(Qt.UserRole) in selected)
                if item.data(Qt.UserRole)==current:self.order.setCurrentItem(item,QItemSelectionModel.NoUpdate)
            self._syncing=False; self._order_selection()
            self._edit_step(self.order.currentItem(),None)

        def _move(self,delta):
            rows=[self.order.row(i) for i in self.order.selectedItems()]
            if rows:self.order.move_selection(min(rows)+delta)

        def _single(self):
            current=self.order.currentItem()
            if current:self.order.clearSelection(); current.setSelected(True)

        def _history(self,redo):
            source,target=(self._redo,self._undo) if redo else (self._undo,self._redo)
            if not source or not self.plan:return
            target.append(copy.deepcopy(self.plan)); restored=source.pop()
            for field in restored.__dataclass_fields__:setattr(self.plan,field,copy.deepcopy(getattr(restored,field)))
            self.set_plan(self.plan,'편집 다시 실행' if redo else '편집 실행 취소')
            self._save()
            self.edit_state_changed.emit()

        def _apply_step(self):
            if len(self.order.selectedItems())!=1:return
            self._record(); super()._apply_step()
            gid=self.order.currentItem().data(Qt.UserRole)
            next(s for s in self.plan.steps if s.group_id==gid).camera_roll_deg=self._camera_roll_deg
            self._renumber(); self.status.setText('수동 수정값 적용 · 간섭 재검사 없음')
            self._save()
            self.edit_state_changed.emit()

        def _apply_forward(self):
            self._record(); super()._apply_forward()
            self.undo_button.setEnabled(bool(self._undo)); self.redo_button.setEnabled(bool(self._redo))
            self._save()
            self.edit_state_changed.emit()

        def _preview_step(self):
            if self._step_preview:
                self._stop_preview(); return
            if not self.plan or len(self.order.selectedItems())!=1:return
            self._clear_visibility_toggle()
            self.play_timer.stop(); self._sync_playback()
            preview=copy.deepcopy(self.plan)
            gid=self.order.currentItem().data(Qt.UserRole)
            step=next(s for s in preview.steps if s.group_id==gid)
            axes={'+X':(1,0,0),'-X':(-1,0,0),'+Y':(0,1,0),'-Y':(0,-1,0),'+Z':(0,0,1),'-Z':(0,0,-1)}
            step.removal_direction=axes.get(self.direction.currentText(),step.removal_direction)
            step.assembly_direction=tuple(-v for v in step.removal_direction)
            step.travel_mm=self.distance.value(); step.camera_mode=self.camera.currentText()
            step.camera_roll_deg=self._camera_roll_deg
            step.process_text=self.process.toPlainText(); step.material_text=self.material.toPlainText(); step.caution_text=self.caution.toPlainText()
            import vtk
            camera=vtk.vtkCamera(); camera.DeepCopy(self.vtk_scene.renderer.GetActiveCamera())
            selection_state=self.vtk_scene.capture_selection_state()
            timeline=self._timeline(preview)
            segment=next(s for s in timeline.segments if s.step_index==step.step_index)
            self._step_preview={'plan':preview,'timeline':timeline,'time':segment.camera_start,'end':segment.move_end,
                                'camera':camera,'selection_state':selection_state,
                                'framing':(self.vtk_scene.base_center,self.vtk_scene.camera_distance,self.vtk_scene.camera_base_id)}
            self.step_preview_button.setText('미리보기 중지')
            self.vtk_scene.apply(scene_at(preview,segment.camera_start,self.settings,timeline))
            self.preview_timer.start(33)
            self._sync_playback()

        def _preview_tick(self):
            preview=self._step_preview
            if not preview:return
            preview['time']=min(preview['end'],preview['time']+.033*float(self.speed.currentText()))
            self.vtk_scene.apply(scene_at(preview['plan'],preview['time'],self.settings,preview['timeline']))
            self._sync_playback()
            if preview['time']>=preview['end']:self._stop_preview()

        def _stop_preview(self):
            if not self._step_preview:return
            self.preview_timer.stop(); previous=self._step_preview; self._step_preview=None
            self.vtk_scene.renderer.GetActiveCamera().DeepCopy(previous['camera'])
            self.vtk_scene.base_center,self.vtk_scene.camera_distance,self.vtk_scene.camera_base_id=previous['framing']
            self.vtk_scene.restore_selection_state(previous['selection_state'])
            self.step_preview_button.setText('미리보기')
            self._sync_playback()

        def _save(self):
            self._commit_order()
            if self.plan:self.save_requested.emit(self.plan)

        def _assign_base(self):
            ids=self._selected()
            if len(ids)!=1:return
            gid=next(iter(ids))
            if gid in self.exception_ids:self.status.setText('예외 지정을 해제한 뒤 기준 부품으로 지정하세요.'); return
            self.base.setCurrentIndex(self.base.findData(gid))

        def _base_changed(self):
            gid=self.base.currentData()
            if gid in self.exception_ids:self.set_exceptions([x for x in self.exception_ids if x!=gid]); self.preset_changed.emit()
            self._update_group_buttons()

        def _set_selected_exceptions(self,enabled):
            selected=self._selected()-{self.base.currentData()}
            ids=set(self.exception_ids)
            ids=ids|selected if enabled else ids-selected
            self.set_exceptions(sorted(ids)); self.preset_changed.emit()

        def _navigation(self,pan):
            self.orbit.setChecked(not pan); self.pan.setChecked(pan); self.vtk_scene.pan_mode=pan

        def _view(self,name):self.vtk_scene.set_view(name)

        def preview(self):
            self._clear_visibility_toggle()
            self._clear_part_isolation()
            super().preview()
            if self.plan:self.scrubber.setValue(10000); self.play_time=self._timeline().duration
            self._sync_playback()

        def _sync_playback(self):
            self._sync_visibility_button()
            ready=bool(self.plan)
            for button in (self.first_button,self.previous_button,self.play,self.next_button,self.last_button,self.scrubber,self.speed):
                button.setEnabled(ready)
            duration=self._timeline().duration if ready else 0.0
            update_play_button(self.play,self.play_timer.isActive())
            self.time_label.setText(f'{self.play_time:.1f} / {duration:.1f}s')
            self.playback_state.setText('재생 중' if self.play_timer.isActive() else '완성 형상' if not ready or self.play_time>=duration else '일시정지' if self.play_time else '시작')
            if not self.scrubber.isSliderDown():self.scrubber.setValue(round(self.play_time/max(duration,.001)*10000))
            frame=None
            if self._step_preview:
                preview=self._step_preview
                frame=scene_at(preview['plan'],preview['time'],self.settings,preview['timeline'])
            elif ready and self._timeline_focus:
                frame=scene_at(self.plan,self.play_time,self.settings,self._timeline())
            self.order.set_active_step(frame.active_group_id if frame else None)
            if frame and frame.active_group_id:
                state='미리보기' if self._step_preview else '재생 중' if self.play_timer.isActive() else '일시정지'
                self.playback_state.setText(f'{frame.step_index:02d}단계 · {state}')

        def _toggle_play(self):
            if not self.plan:return
            self._clear_visibility_toggle()
            self._stop_preview()
            self._clear_part_isolation()
            self._commit_order()
            if self.play_timer.isActive():self.play_timer.stop(); self._sync_playback(); return
            if self.play_time>=self._timeline().duration:self.play_time=0
            self._timeline_focus=True
            self.play_timer.start(33); self._sync_playback()

        def _play_tick(self):
            self._timeline_focus=True
            super()._play_tick()
            self._sync_playback()

        def _seek(self,value):
            if not self.plan:return
            self._clear_visibility_toggle()
            self._stop_preview()
            self._clear_part_isolation()
            timeline=self._timeline()
            self.play_time=timeline.duration*value/10000
            self._timeline_focus=True
            self.vtk_scene.apply(scene_at(self.plan,self.play_time,self.settings,timeline))
            self._sync_playback()

        def _jump_end(self,end):
            if not self.plan:return
            self.play_timer.stop(); self._stop_preview()
            if self.order.count():self.order.setCurrentRow(self.order.count()-1 if end else 0)
            self._seek(10000 if end else 0)

        def _neighbor(self,delta):
            if not self.plan or not self.order.count():return
            self.play_timer.stop(); self._stop_preview()
            row=max(0,min(self.order.count()-1,self.order.currentRow()+delta))
            self.order.setCurrentRow(row)
            timeline=self._timeline()
            self._seek(round(timeline.segments[row].camera_start/max(timeline.duration,.001)*10000))

    return ModelEditor

