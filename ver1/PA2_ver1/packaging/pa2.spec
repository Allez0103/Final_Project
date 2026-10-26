from pathlib import Path
from PyInstaller.utils.hooks import collect_all
import PySide6

root = Path(SPECPATH).resolve().parent
datas = [(str(root / "assets"), "assets")]
binaries = []
hiddenimports = ['pa2.ui_verify_v16', 'pa2.ui_verify_v19', 'pa2.ui_verify_v20', 'pa2.ui_verify_v23', 'pa2.ui_verify_v24', 'pa2.ui_verify_v25', 'pa2.cli', 'PySide6.QtTest']
for package in ("vtkmodules", "OCP", "lightgbm", "imageio_ffmpeg", "sqlalchemy", "pymysql"):
    package_datas, package_binaries, package_hidden = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hidden

a = Analysis(
    [str(root / "run.py")],
    pathex=[str(root / "src")], binaries=binaries, datas=datas,
    hiddenimports=hiddenimports, hookspath=[], hooksconfig={}, runtime_hooks=[str(root/'packaging/qt_runtime.py')], excludes=[],
    noarchive=False, optimize=1,
)
# The bootloader loads the root VC runtime before Python imports Qt. Mixing
# Python's older root DLLs with Qt's newer subdirectory DLLs can make QtWidgets
# fail with ERROR_PROC_NOT_FOUND. Ship one matching runtime set at the root.
qt_root=Path(PySide6.__file__).parent
runtime_files=[p for p in qt_root.glob('*.dll') if p.name.lower().startswith(('msvcp140','vcruntime140','concrt140'))]
runtime_names={p.name.lower() for p in runtime_files}
a.binaries=[row for row in a.binaries if Path(row[0]).name.lower() not in runtime_names]
a.binaries += [(p.name,str(p),'BINARY') for p in runtime_files]
# Qt imports the Windows ICU API (unversioned exports). A Poppler/Conda
# icuuc.dll on PATH exports ICU-version-suffixed symbols and is incompatible.
# Resolve the OS API from System32 rather than collecting that same-name DLL.
a.binaries=[row for row in a.binaries if Path(row[0]).name.lower() not in {'icuuc.dll','icuin.dll'}]
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="PA2", debug=False, bootloader_ignore_signals=False, strip=False, upx=False, console=False, icon=str(root/'assets/pa2_icon.ico'))
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, upx_exclude=[], name="PA2")

