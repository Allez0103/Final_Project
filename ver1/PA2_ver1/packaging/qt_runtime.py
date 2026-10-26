"""Resolve packaged Qt from its own directory before importing bindings."""
import os
import sys
from pathlib import Path

if sys.platform=='win32' and hasattr(sys,'_MEIPASS'):
    _pa2_root=Path(sys._MEIPASS)
    _pa2_qt_handles=[]
    for _pa2_dir in (_pa2_root,_pa2_root/'PySide6',_pa2_root/'shiboken6'):
        if _pa2_dir.is_dir():_pa2_qt_handles.append(os.add_dll_directory(str(_pa2_dir)))
    import ctypes
    _pa2_system=Path(os.environ.get('SystemRoot','C:/Windows'))/'System32'
    _pa2_icu=[ctypes.WinDLL(str(_pa2_system/name)) for name in ('icuuc.dll','icuin.dll')
              if (_pa2_system/name).is_file()]
    _pa2_qt_libs=[ctypes.WinDLL(str(_pa2_root/'PySide6'/name))
                  for name in ('Qt6Core.dll','Qt6Gui.dll','Qt6Widgets.dll')]
