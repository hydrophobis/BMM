@echo off
rem Balatro Mod Manager launcher: sets up a local venv on first run, then starts the window.
cd /d "%~dp0"
if not exist .venv\Scripts\pythonw.exe (
  echo First run: installing the Raven GUI library into .venv ...
  python -m venv .venv || (echo Python 3.8+ is required: https://www.python.org/downloads/ & pause & exit /b 1)
  .venv\Scripts\python -m pip install -q -r requirements.txt || (pause & exit /b 1)
)
start "" .venv\Scripts\pythonw.exe app.pyw
