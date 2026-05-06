@echo off
REM ===================================================================
REM RadimCare Tapo Gateway — Windows launcher
REM ===================================================================
REM Run on system startup via Task Scheduler.
REM Restart automatically on failure (configure in Task Scheduler).
REM Logs go to C:\RadimCare\gateway.log
REM ===================================================================

cd /d C:\RadimCare

REM Load env vars from .env (simple parser — KEY=VALUE per line, no quotes)
if exist .env (
    for /f "usebackq tokens=1,* delims==" %%A in (".env") do (
        set "%%A=%%B"
    )
)

REM Append-mode log with timestamp
echo [%date% %time%] Starting Tapo Gateway >> gateway.log
python tapo_gateway.py >> gateway.log 2>&1
echo [%date% %time%] Gateway exited code %ERRORLEVEL% >> gateway.log

REM Exit with non-zero so Task Scheduler restarts us
exit /b %ERRORLEVEL%
