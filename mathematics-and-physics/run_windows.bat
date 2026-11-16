@echo off
cd /d "%~dp0"
where docker >nul 2>nul
if errorlevel 1 (
    echo Docker Desktop is required. Install it and retry.
    pause
    exit /b 1
)
if not exist ".env" (
    copy ".env.example" ".env" >nul
    echo Set a strong PostgreSQL password in .env, then rerun.
    notepad ".env"
    pause
    exit /b 0
)
docker compose up --build -d
if errorlevel 1 (
    echo Docker Compose failed. Inspect configuration and logs.
    pause
    exit /b 1
)
docker compose ps
echo Open http://localhost:8000 in your browser.
pause
