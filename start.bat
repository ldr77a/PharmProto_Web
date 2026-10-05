@echo off
setlocal
set "PROJECT_ROOT=%~dp0"
cd /d "%PROJECT_ROOT%"
set "APP_EXIT=%ERRORLEVEL%"
if not "%APP_EXIT%"=="0" goto :startup_error
set "UV_EXE=%LOCALAPPDATA%\PharmaProto\tools\uv.exe"
set "UV_PROJECT_ENVIRONMENT=%LOCALAPPDATA%\PharmaProto\runtime\venv"
set "UV_PYTHON_INSTALL_DIR=%LOCALAPPDATA%\PharmaProto\runtime\python"
set "UV_CACHE_DIR=%LOCALAPPDATA%\PharmaProto\runtime\uv-cache"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%PROJECT_ROOT%tools\bootstrap-runtime.ps1" -ProjectRoot "%PROJECT_ROOT%."
set "APP_EXIT=%ERRORLEVEL%"
if not "%APP_EXIT%"=="0" goto :startup_error
"%UV_EXE%" run --frozen --no-dev --python 3.12.13 python -m pharma_proto.launcher
set "APP_EXIT=%ERRORLEVEL%"
if not "%APP_EXIT%"=="0" goto :startup_error
exit /b 0

:startup_error
echo [APP-START-001] Program start failed.
echo See: %LOCALAPPDATA%\PharmaProto\logs\bootstrap.log
echo Fix the reported network or checksum problem, then run start.bat again.
if not "%PHARMA_NONINTERACTIVE%"=="1" pause
exit /b %APP_EXIT%
