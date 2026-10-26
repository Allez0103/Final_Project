@echo off
setlocal
set "PA2_ROOT=%~dp0"
set "PYTHONPATH=%PA2_ROOT%src"
"%PA2_ROOT%.venv\Scripts\python.exe" -m pa2.cli %*
endlocal

