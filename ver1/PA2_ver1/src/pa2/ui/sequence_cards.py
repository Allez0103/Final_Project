"""Sequence-card dragging with a lifted card, animated gap and atomic drop."""
import uuid
from PySide6.QtCore import Qt,QSize,QPoint,QRectF,QMimeData,QTimer,Signal,QSignalBlocker,QItemSelectionModel,QVariantAnimation,QEasingCurve
from PySide6.QtGui import QDrag,QPainter,QPixmap,QColor,QPen
from PySide6.QtWidgets import QListWidget,QListView,QAbstractItemView,QApplication,QStyleOptionViewItem,QStyle


class SequenceCards(QListWidget):
    reordered=Signal()
    drag_started=Signal()
    MIME='application/x-pa2-sequence-cards'

    def __init__(self):
        super().__init__()
        self.setObjectName('sequenceCards')
        self.setViewMode(QListView.IconMode);self.setFlow(QListView.LeftToRight);self.setWrapping(False)
        self.setResizeMode(QListView.Adjust);self.setMovement(QListView.Static)
        self.setDragDropMode(QAbstractItemView.InternalMove);self.setDragEnabled(True)
        self.setAcceptDrops(True);self.viewport().setAcceptDrops(True);self.setDropIndicatorShown(False)
        self.setDefaultDropAction(Qt.MoveAction);self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel);self.setAutoScroll(False)
        self.setIconSize(QSize(105,62));self.setGridSize(QSize(170,132));self.setWordWrap(True);self.setFixedHeight(148)
        self.setToolTip('카드를 끌어 빈자리에 놓으면 순서가 바뀝니다. Ctrl/Shift로 여러 카드를 함께 옮길 수 있습니다.')
        self.viewport().setCursor(Qt.OpenHandCursor)
        self._token=uuid.uuid4().hex;self._press_pos=None;self._pressed=None;self._keep_selection=False
        self._drag_running=False;self._preview=False;self._rest=[];self._moving=[];self._target=0;self._last_pos=None
        self._positions={};self._from={};self._to={};self._landed=set();self._landing_alpha=0.0
        self.active_step_id=None
        self._animation=QVariantAnimation(self);self._animation.setDuration(140);self._animation.setStartValue(0.0);self._animation.setEndValue(1.0)
        self._animation.setEasingCurve(QEasingCurve.OutCubic);self._animation.valueChanged.connect(self._animate_gap)
        self._landing=QVariantAnimation(self);self._landing.setDuration(650);self._landing.setStartValue(1.0);self._landing.setEndValue(0.0)
        self._landing.valueChanged.connect(self._animate_landing)
        self._scroll=QTimer(self);self._scroll.setInterval(24);self._scroll.timeout.connect(self._auto_scroll)

    @staticmethod
    def _key(item):
        value=item.data(Qt.UserRole)
        return value if value is not None else item.text()

    def set_active_step(self,gid):
        if gid==self.active_step_id:return
        self.active_step_id=gid
        if gid is not None and not self._drag_running:
            for i in range(self.count()):
                if self._key(self.item(i))==gid:self.scrollToItem(self.item(i));break
        self.setAccessibleDescription('현재 진행 단계 없음' if gid is None else '빨간 테두리 카드가 현재 진행 단계입니다.')
        self.viewport().update()

    def mousePressEvent(self,event):
        self._press_pos=event.position().toPoint();self._pressed=self.itemAt(self._press_pos)
        self._keep_selection=bool(event.button()==Qt.LeftButton and self._pressed and self._pressed.isSelected()
                                  and len(self.selectedItems())>1 and not event.modifiers())
        if self._keep_selection:
            selected=self.selectedItems()
            with QSignalBlocker(self):
                super().mousePressEvent(event)
                self.clearSelection()
                for item in selected:item.setSelected(True)
                self.setCurrentItem(self._pressed,QItemSelectionModel.NoUpdate)
        else:super().mousePressEvent(event)

    def mouseMoveEvent(self,event):
        if event.buttons() & Qt.LeftButton and self._pressed and self._press_pos is not None:
            if (event.position().toPoint()-self._press_pos).manhattanLength()>=QApplication.startDragDistance():
                if not self._drag_running:self.startDrag(Qt.MoveAction)
                event.accept();return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self,event):
        if self._keep_selection and self._pressed and not self._drag_running:
            self.setCurrentItem(self._pressed,QItemSelectionModel.ClearAndSelect)
        self._pressed=None;self._press_pos=None;self._keep_selection=False
        super().mouseReleaseEvent(event)

    def _drag_pixmap(self,selected):
        front=self._pressed if self._pressed in selected else selected[0]
        rect=self.visualItemRect(front);card=self.viewport().grab(rect)
        ratio=self.devicePixelRatioF();width=rect.width()+24;height=rect.height()+24
        result=QPixmap(round(width*ratio),round(height*ratio));result.setDevicePixelRatio(ratio);result.fill(Qt.transparent)
        painter=QPainter(result);painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen);painter.setBrush(QColor(23,52,84,45));painter.drawRoundedRect(QRectF(11,13,rect.width(),rect.height()),8,8)
        if len(selected)>1:
            painter.setPen(QPen(QColor('#9BB6D7'),1));painter.setBrush(QColor('#EAF2FD'))
            painter.drawRoundedRect(QRectF(13,10,rect.width(),rect.height()),6,6)
        painter.drawPixmap(QPoint(7,6),card)
        painter.setBrush(Qt.NoBrush);painter.setPen(QPen(QColor('#2463B5'),2));painter.drawRoundedRect(QRectF(7,6,rect.width()-1,rect.height()-1),6,6)
        if len(selected)>1:
            painter.setPen(Qt.NoPen);painter.setBrush(QColor('#2463B5'));painter.drawRoundedRect(QRectF(width-55,2,48,25),12,12)
            painter.setPen(Qt.white);painter.drawText(QRectF(width-55,2,48,25),Qt.AlignCenter,f'{len(selected)}개')
        painter.end()
        position=self._press_pos or rect.center()
        hotspot=QPoint(max(7,min(width-10,position.x()-rect.left()+7)),max(6,min(height-10,position.y()-rect.top()+6)))
        return result,hotspot

    def startDrag(self,supported_actions):
        selected=sorted(self.selectedItems(),key=self.row)
        if self._drag_running or not selected:return
        pixmap,hotspot=self._drag_pixmap(selected)
        self._drag_running=True;self._begin_preview(selected);self.drag_started.emit()
        drag=QDrag(self);mime=QMimeData();mime.setData(self.MIME,self._token.encode('ascii'));drag.setMimeData(mime)
        drag.setPixmap(pixmap);drag.setHotSpot(hotspot);self._last_drag_pixmap=pixmap
        self.viewport().setCursor(Qt.ClosedHandCursor)
        try:drag.exec(Qt.MoveAction,Qt.MoveAction)
        finally:
            self._clear_preview();self._drag_running=False;self._press_pos=None;self._pressed=None;self._keep_selection=False
            self.viewport().setCursor(Qt.OpenHandCursor);drag.deleteLater()

    def _begin_preview(self,selected):
        self._moving=selected[:];rows={self.row(item) for item in selected}
        self._rest=[(row,self.item(row)) for row in range(self.count()) if row not in rows]
        self._target=sum(row<min(rows) for row,_ in self._rest)
        self._positions={row:float(self.visualItemRect(item).left()+self.horizontalScrollBar().value()) for row,item in self._rest}
        self._preview=True;self._set_target(self._target,force=True);self.viewport().update()

    def _allowed(self,event):
        return bool(self._drag_running and self._preview and event.source() is self and event.mimeData().hasFormat(self.MIME)
                    and bytes(event.mimeData().data(self.MIME))==self._token.encode('ascii'))

    def dragEnterEvent(self,event):
        if self._allowed(event):event.setDropAction(Qt.MoveAction);event.accept()
        else:event.ignore()

    def dragMoveEvent(self,event):
        if not self._allowed(event):event.ignore();return
        self._last_pos=event.position().toPoint();self._update_target(self._last_pos)
        if not self._scroll.isActive():self._scroll.start()
        event.setDropAction(Qt.MoveAction);event.accept()

    def dragLeaveEvent(self,event):
        self._scroll.stop();self._last_pos=None;event.accept()

    def _update_target(self,point):
        x=point.x()+self.horizontalScrollBar().value();width=self.gridSize().width()
        target=sum((i+int(i>=self._target)+.5)*width<x for i in range(len(self._rest)))
        self._set_target(target)

    def _set_target(self,target,force=False):
        target=max(0,min(len(self._rest),target))
        if target==self._target and not force:return
        self._animation.stop();self._target=target;self._from=self._positions.copy()
        width=self.gridSize().width();self._to={row:float((i+int(i>=target))*width) for i,(row,_) in enumerate(self._rest)}
        self._animation.start();self.viewport().update()

    def _animate_gap(self,value):
        self._positions={row:self._from.get(row,end)+(end-self._from.get(row,end))*float(value) for row,end in self._to.items()}
        self.viewport().update()

    def _auto_scroll(self):
        if not self._preview or self._last_pos is None:self._scroll.stop();return
        x=self._last_pos.x();direction=-1 if x<34 else 1 if x>self.viewport().width()-34 else 0
        if direction:
            bar=self.horizontalScrollBar();bar.setValue(bar.value()+direction*18);self._update_target(self._last_pos);self.viewport().update()

    def dropEvent(self,event):
        if not self._allowed(event):event.ignore();return
        self._update_target(event.position().toPoint());target=self._target
        self._clear_preview();self.move_selection(target)
        event.setDropAction(Qt.MoveAction);event.accept()

    def _clear_preview(self):
        self._animation.stop();self._scroll.stop();self._preview=False;self._rest=[];self._moving=[]
        self._positions={};self._last_pos=None;self.viewport().update()

    def paintEvent(self,event):
        if not self._preview:
            super().paintEvent(event)
            if self._landing_alpha>0:
                painter=QPainter(self.viewport());painter.setRenderHint(QPainter.Antialiasing)
                painter.setPen(QPen(QColor(36,99,181,round(220*self._landing_alpha)),3));painter.setBrush(QColor(84,151,235,round(35*self._landing_alpha)))
                for i in range(self.count()):
                    item=self.item(i)
                    if self._key(item) in self._landed:painter.drawRoundedRect(QRectF(self.visualItemRect(item)).adjusted(5,5,-5,-5),6,6)
                painter.end()
            if self.active_step_id is not None:
                painter=QPainter(self.viewport());painter.setRenderHint(QPainter.Antialiasing)
                for i in range(self.count()):
                    item=self.item(i)
                    if self._key(item)!=self.active_step_id:continue
                    rect=QRectF(self.visualItemRect(item)).adjusted(5,5,-5,-5)
                    painter.setBrush(Qt.NoBrush);painter.setPen(QPen(QColor('#D93036'),3));painter.drawRoundedRect(rect,6,6)
                    badge=QRectF(rect.right()-70,rect.top()+3,67,20)
                    painter.setPen(Qt.NoPen);painter.setBrush(QColor('#D93036'));painter.drawRoundedRect(badge,4,4)
                    painter.setPen(Qt.white);painter.drawText(badge,Qt.AlignCenter,'현재 단계')
                painter.end()
            return
        painter=QPainter(self.viewport());painter.fillRect(self.viewport().rect(),Qt.white);painter.setRenderHint(QPainter.Antialiasing)
        scroll=self.horizontalScrollBar().value();width=self.gridSize().width();height=self.gridSize().height()
        for row,item in self._rest:
            rect=QRectF(self._positions.get(row,0)-scroll,0,width,height)
            if not rect.intersects(QRectF(self.viewport().rect())):continue
            option=QStyleOptionViewItem();self.initViewItemOption(option);option.rect=rect.toRect()
            option.state &= ~QStyle.State_Selected;option.state &= ~QStyle.State_MouseOver
            index=self.model().index(row,0);self.itemDelegateForIndex(index).paint(painter,option,index)
        gap=QRectF(self._target*width-scroll+5,5,width-10,height-10)
        painter.setBrush(QColor('#EAF2FD'));painter.setPen(QPen(QColor('#2463B5'),2,Qt.DashLine));painter.drawRoundedRect(gap,7,7)
        painter.setPen(QColor('#2463B5'));painter.drawText(gap.adjusted(4,0,-4,-14),Qt.AlignCenter,'여기에 놓기')
        painter.setPen(QColor('#66758A'));painter.drawText(gap.adjusted(4,28,-4,0),Qt.AlignCenter,f'{self._target+1}번째 · {len(self._moving)}개 이동')
        painter.end()

    def _animate_landing(self,value):
        self._landing_alpha=float(value);self.viewport().update()

    def move_selection(self,to):
        selected=sorted(self.selectedItems(),key=self.row)
        if not selected:return False
        rest=[self.item(i) for i in range(self.count()) if self.item(i) not in selected]
        to=max(0,min(len(rest),to));new=rest[:to]+selected+rest[to:]
        if new==[self.item(i) for i in range(self.count())]:return False
        current=self.currentItem();landed={self._key(item) for item in selected}
        with QSignalBlocker(self):
            while self.count():self.takeItem(0)
            for item in new:self.addItem(item)
            for item in selected:item.setSelected(True)
            if current:self.setCurrentItem(current,QItemSelectionModel.NoUpdate)
            for item in selected:item.setSelected(True)
        self._landed=landed;self.reordered.emit();self._landing.stop();self._landing.start()
        for i in range(self.count()):
            if self._key(self.item(i)) in landed:self.scrollToItem(self.item(i));break
        return True
