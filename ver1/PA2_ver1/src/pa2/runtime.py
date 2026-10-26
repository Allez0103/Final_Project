"""Separate immutable resources, install-adjacent logs and per-user data."""
import os,sys
from pathlib import Path

def install_root():
    override=os.environ.get('PA2_INSTALL_ROOT')
    return Path(override).resolve() if override else (Path(sys.executable).resolve().parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parents[2])

def resource_root():
    return Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parents[2]))
