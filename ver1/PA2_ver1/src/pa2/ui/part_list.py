"""Toggle a sole selected part on a plain click, preserving Qt multi-selection."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QListWidget


class PartListWidget(QListWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._toggle_press = None

    def mousePressEvent(self, event):
        self._toggle_press = None
        item = self.itemAt(event.position().toPoint())
        if (event.button() == Qt.LeftButton and not event.modifiers()
                and item is not None and self.selectedItems() == [item]):
            self._toggle_press = (item, event.position().toPoint())
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        pending = self._toggle_press
        self._toggle_press = None
        super().mouseReleaseEvent(event)
        if pending and event.button() == Qt.LeftButton and not event.modifiers():
            item, origin = pending
            point = event.position().toPoint()
            if (self.itemAt(point) is item and self.selectedItems() == [item]
                    and (point-origin).manhattanLength() < QApplication.startDragDistance()):
                self.clearSelection()
