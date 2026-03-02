@echo off
setlocal
set ROOT=%~dp0
cd /d "%ROOT%"
set PY=

if exist "%ROOT%.venv\Scripts\python.exe" set PY=%ROOT%.venv\Scripts\python.exe
if not defined PY if exist "%ROOT%.venv311\Scripts\python.exe" set PY=%ROOT%.venv311\Scripts\python.exe
if not defined PY if exist "%ROOT%.venv_caption\Scripts\python.exe" set PY=%ROOT%.venv_caption\Scripts\python.exe
if not defined PY set PY=py -3

REM Auto-install deps if missing, then launch (router on 8502, Streamlit on 8503, browser opens)
"%PY%" -m pip install -q -r requirements.txt 2>nul
"%PY%" "%ROOT%launch_lab_webui_with_ie_fallback.py"

endlocal
