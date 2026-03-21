@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

if "%~1"=="" (
    set "HOST=127.0.0.1"
) else (
    set "HOST=%~1"
)

if "%~2"=="" (
    set "PORT=8765"
) else (
    set "PORT=%~2"
)

if "%~3"=="" (
    set "OUT_DIR=%SCRIPT_DIR%exports"
) else (
    set "OUT_DIR=%~3"
)

set "PYTHONPATH=%SCRIPT_DIR%src"

echo Starting py2fl web UI...
echo Host: %HOST%
echo Port: %PORT%
echo Output: %OUT_DIR%
echo.
python -m py2fl.cli serve --host "%HOST%" --port "%PORT%" --out "%OUT_DIR%"

endlocal
