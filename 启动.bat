@echo off
cd /d "%~dp0"

set "PORT=%~1"
if "%PORT%"=="" set "PORT=8017"

set "PY="
if exist "F:\comfyui_official\ComfyUI_windows_portable\python_embeded\python.exe" set "PY=F:\comfyui_official\ComfyUI_windows_portable\python_embeded\python.exe"
if not defined PY (
    where python >nul 2>nul
    if not errorlevel 1 set "PY=python"
)

if not defined PY (
    echo [ERROR] Python not found.
    echo Install Python, or run manually in this folder:
    echo     python serve.py
    pause
    exit /b 1
)

echo Starting splat-viewer on port %PORT% ...
echo Models: .\models first (if exists), then ComfyUI output\3d
echo.
"%PY%" serve.py %PORT%

echo.
echo [stopped] exit code = %errorlevel%
pause
