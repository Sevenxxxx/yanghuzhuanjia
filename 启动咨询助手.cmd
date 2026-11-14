@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

rem Double-click entry: open the chat page, starting the local service first if needed.
rem Kept ASCII-only on purpose: cmd parses this file in the OEM code page, so UTF-8
rem Chinese text here breaks the parser. Chinese lives in the page, not the launcher.

set "ROOT=%USERPROFILE%\dsh-roads"
set "MARKER=%ROOT%\chat-url.txt"
set "LOG=%ROOT%\logs\chat-console.log"

if /i "%~1"=="--run" goto :run

if not exist "scripts\p3\chat\app.py" (
  echo This launcher must stay in the project root folder:
  echo   C:\Users\Seven\Desktop\yanghuzhuanjia
  echo To use it from elsewhere, make a shortcut instead of copying the file.
  pause
  exit /b 1
)

call :probe
if defined URL (
  echo Road maintenance assistant is already running: !URL!
  start "" "!URL!"
  exit /b 0
)

if not exist "%ROOT%\logs" mkdir "%ROOT%\logs" >nul 2>&1
echo Starting the road maintenance assistant. First start can take up to a minute.
start "RoadChat" /min "%~f0" --run

for /l %%i in (1,1,120) do (
  ping -n 2 127.0.0.1 >nul 2>&1
  call :probe
  if defined URL (
    echo Ready: !URL!
    start "" "!URL!"
    exit /b 0
  )
)

echo.
echo Not ready after 120 seconds.
echo Log: %LOG%
echo Common causes: missing DEEPSEEK_API_KEY, port 8091 in use, dsh not on PATH.
pause
exit /b 1

:probe
set "URL="
if not exist "%MARKER%" goto :eof
set /p CANDIDATE=<"%MARKER%"
if not defined CANDIDATE goto :eof
curl -s -o NUL --max-time 2 "!CANDIDATE!api/health" >nul 2>&1
if not errorlevel 1 set "URL=!CANDIDATE!"
goto :eof

:run
set "CONFIG="
if exist "deploy.json" set "CONFIG=--config deploy.json"
python -X utf8 scripts\p3\chat\app.py %CONFIG% >> "%LOG%" 2>&1
exit /b
