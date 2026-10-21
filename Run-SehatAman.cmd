@echo off
setlocal
cd /d "%~dp0"
set "SEHATAMAN_PYTHON=C:\Users\HP\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if not exist "%SEHATAMAN_PYTHON%" set "SEHATAMAN_PYTHON=python"
"%SEHATAMAN_PYTHON%" manage.py serve --port 8787
pause
