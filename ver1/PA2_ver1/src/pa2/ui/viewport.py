"""Qt icon tools beside the native VTK surface; viewport text lives in VTK."""
from PySide6.QtCore import Qt,QPointF,QRectF,QSize
from PySide6.QtGui import QIcon,QPixmap,QPainter,QPen,QColor,QPolygonF
from PySide6.QtWidgets import QWidget,QFrame,QHBoxLayout,QVBoxLayout,QLabel,QPushButton,QStyleOptionButton,QStylePainter,QStyle


def viewport_icon(name):
    icon=QIcon()
    for mode,color in ((QIcon.Normal,'#607896'),(QIcon.Active,'#2463B5'),(QIcon.Disabled,'#AEBBCB')):
        pixmap=QPixmap(48,48);pixmap.fill(Qt.transparent)
        painter=QPainter(pixmap);painter.setRenderHint(QPainter.Antialiasing);painter.scale(2,2)
        painter.setPen(QPen(QColor(color),1.6,Qt.SolidLine,Qt.RoundCap,Qt.RoundJoin))
        def line(*points):painter.drawPolyline(QPolygonF([QPointF(x,y) for x,y in points]))
        if name=='rotate':
            painter.drawArc(QRectF(5,5,14,14),35*16,285*16);line((16,3),(19,6),(15,7))
        elif name=='pan':
            line((12,3),(12,21));line((3,12),(21,12))
            for points in (((9,6),(12,3),(15,6)),((9,18),(12,21),(15,18)),((6,9),(3,12),(6,15)),((18,9),(21,12),(18,15))):line(*points)
        elif name=='fit':
            for points in (((4,9),(4,4),(9,4)),((15,4),(20,4),(20,9)),((20,15),(20,20),(15,20)),((9,20),(4,20),(4,15))):line(*points)
            painter.drawEllipse(QRectF(9,9,6,6))
        elif name=='view':
            line((12,3),(20,7),(20,17),(12,21),(4,17),(4,7),(12,3))
            line((4,7),(12,12),(20,7));line((12,12),(12,21))
        elif name in ('zoom_in','zoom_out'):
            painter.drawEllipse(QRectF(4,4,12,12));line((15,15),(21,21));line((7,10),(13,10))
            if name=='zoom_in':line((10,7),(10,13))
        elif name=='solo':
            line((12,4),(21,9),(12,14),(3,9),(12,4));line((3,13),(12,18),(21,13));line((5,18),(12,22),(19,18))
        else:
            line((2,12),(6,7),(12,5),(18,7),(22,12),(18,17),(12,19),(6,17),(2,12))
            painter.drawEllipse(QRectF(9,9,6,6))
            if name=='hide':line((3,3),(21,21))
        painter.end();icon.addPixmap(pixmap,mode)
    return icon


def configure_viewport_button(button,name,label):
    button.setText('');button.setIcon(viewport_icon(name));button.setIconSize(QSize(21,21))
    button.setFixedSize(34,34);button.setProperty('viewportTool',True)
    button.setToolTip(label);button.setAccessibleName(label)


class ViewportMenuButton(QPushButton):
    def paintEvent(self,event):
        option=QStyleOptionButton();self.initStyleOption(option)
        # The icon-only menu has no arrow. Do not reserve the native arrow's
        # width, which otherwise shifts the cube outside the highlight centre.
        option.features &= ~QStyleOptionButton.HasMenu
        painter=QStylePainter(self);painter.drawControl(QStyle.CE_PushButton,option)


class ModelViewport(QWidget):
    def __init__(self,canvas,parent=None):
        super().__init__(parent)
        self.setObjectName('modelViewport');self.setMinimumSize(340,210)
        self.canvas=canvas
        canvas.setStyleSheet('border: 0;')
        if hasattr(canvas,'setFrameShape'):canvas.setFrameShape(QFrame.NoFrame)
        layout=QVBoxLayout(self);layout.setContentsMargins(8,6,8,8);layout.setSpacing(4)
        layout.addWidget(canvas,1)
        self.footer=QWidget(self);footer=QHBoxLayout(self.footer);footer.setContentsMargins(0,0,0,0)
        self.toolbar=QFrame(self.footer);self.toolbar.setObjectName('viewportToolbar')
        self.tools=QHBoxLayout(self.toolbar);self.tools.setContentsMargins(8,5,8,5);self.tools.setSpacing(2)
        footer.addStretch();footer.addWidget(self.toolbar);footer.addStretch();layout.addWidget(self.footer)
        canvas.setAccessibleDescription('3D 모델 · 드래그 회전 · 휠 확대 · 우클릭 이동 · Ctrl+클릭 다중 선택')
        self.setAutoFillBackground(True)
        self.setStyleSheet('QWidget#modelViewport { background: white; }')

    def position_overlays(self):
        self.layout().activate()

    def resizeEvent(self,event):
        super().resizeEvent(event);self.position_overlays()

    def showEvent(self,event):
        super().showEvent(event);self.position_overlays()

    def overlays(self):
        # All controls now have their own non-overlapping layout rectangles.
        # QWidget.grab already contains them; only the canvas needs compositing.
        return ()
