@echo off
setlocal
set "PA2_ROOT=%~dp0"
if exist "%PA2_ROOT%PA2.exe" (
    start "" "%PA2_ROOT%PA2.exe"
    exit /b
)
set "PYTHONPATH=%PA2_ROOT%src"
"%PA2_ROOT%.venv\Scripts\pythonw.exe" -m pa2
endlocal

