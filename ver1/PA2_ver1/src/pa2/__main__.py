from __future__ import annotations

import multiprocessing
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon

from .ui.main_window import MainWindow


def main() -> int:
    multiprocessing.freeze_support()
    app = QApplication(sys.argv)
    app.setApplicationName("PA²")
    app.setOrganizationName("THN")
    if sys.platform=='win32':
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('THN.PA2.Desktop')
    # PyInstaller extracts bundled data below ``sys._MEIPASS``.  In a source
    # checkout the project root is two levels above this module.
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    app.setWindowIcon(QIcon(str(root/'assets/pa2_icon.ico')))
    window = MainWindow(root)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

