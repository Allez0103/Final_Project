"""Small stdlib-only remover; intentionally excludes GUI/CAD dependencies."""
from pathlib import Path
root=Path(SPECPATH).resolve().parent
a=Analysis([str(root/'uninst.py')],pathex=[str(root/'src')],binaries=[],datas=[],
           hiddenimports=[],hookspath=[],hooksconfig={},runtime_hooks=[],excludes=[],noarchive=False,optimize=1)
pyz=PYZ(a.pure)
exe=EXE(pyz,a.scripts,a.binaries,a.datas,[],name='uninst',debug=False,
        bootloader_ignore_signals=False,strip=False,upx=False,console=False,
        icon=str(root/'assets/pa2_icon.ico'))
