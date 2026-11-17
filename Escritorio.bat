@echo off
start "" /B ".\venv\Scripts\python.exe" app.py
timeout /t 2 /nobreak >nul
start "" msedge --app=http://127.0.0.1:5000
