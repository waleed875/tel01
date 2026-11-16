@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    py -3 -m venv .venv
    if errorlevel 1 (
        echo Python 3.11+ is required.
        pause
        exit /b 1
    )
)
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if not exist .env (
    copy .env.example .env >nul
    echo.
    echo Edit .env with Telegram and OpenAI keys, then rerun.
    notepad .env
    pause
    exit /b 0
)
".venv\Scripts\python.exe" bot.py
pause
