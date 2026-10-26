"""Vector transport icons shared by the model and video pages."""
from PySide6.QtCore import Qt, QPointF, QSize
from PySide6.QtGui import QIcon, QPainter, QPen, QPixmap, QPolygonF, QColor


def transport_icon(name, primary=False):
    icon = QIcon()
    for mode, color in ((QIcon.Normal, '#FFFFFF' if primary else '#526D90'),
                        (QIcon.Disabled, '#AFBDCE')):
        pixmap = QPixmap(48, 48)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.scale(2, 2)
        painter.setPen(QPen(QColor(color), 1.7, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        if name in ('play', 'first', 'last'):
            points = [(8, 5), (18, 12), (8, 19)] if name != 'first' else [(16, 5), (6, 12), (16, 19)]
            painter.drawPolygon(QPolygonF([QPointF(x, y) for x, y in points]))
            if name == 'first': painter.drawLine(4, 5, 4, 19)
            if name == 'last': painter.drawLine(20, 5, 20, 19)
        elif name == 'pause':
            painter.drawLine(9, 5, 9, 19); painter.drawLine(16, 5, 16, 19)
        else:
            points = [(14, 6), (8, 12), (14, 18)] if name == 'previous' else [(10, 6), (16, 12), (10, 18)]
            painter.drawPolyline(QPolygonF([QPointF(x, y) for x, y in points]))
        painter.end()
        icon.addPixmap(pixmap, mode)
    return icon


def configure_transport(button, name, tooltip, primary=False):
    button.setText('')
    button.setIcon(transport_icon(name, primary))
    button.setIconSize(QSize(22, 22))
    button.setFixedSize(38 if primary else 30, 38)
    button.setProperty('transport', True)
    if primary: button.setObjectName('playTransport')
    button.setToolTip(tooltip)
    button.setAccessibleName(tooltip)


def update_play_button(button, playing):
    configure_transport(button, 'pause' if playing else 'play', '일시정지' if playing else '재생', True)
