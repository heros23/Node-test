@echo off
cd /d "%~dp0"
python run_dashboard.py
start "" cmd /k python src/dashboard_server.py
timeout /t 2 >nul
start "" http://127.0.0.1:8000/
