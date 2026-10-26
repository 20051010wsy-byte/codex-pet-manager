@echo off
cd /d "%~dp0"
where pythonw.exe >nul 2>&1
if not errorlevel 1 (
  start "" pythonw.exe pet_manager.py
  exit /b 0
)
where python.exe >nul 2>&1
if errorlevel 1 (
  echo Python 3.10 or newer is required.
  pause
  exit /b 1
)
python.exe pet_manager.py
if errorlevel 1 pause
