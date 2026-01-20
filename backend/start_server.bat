@echo off
echo === NEN 5060 Server Clean Start ===
echo.

echo [1/3] Killing all Python processes...
taskkill /f /im python.exe 2>nul
timeout /t 1 /nobreak >nul

echo [2/3] Clearing Python cache...
if exist __pycache__ rmdir /s /q __pycache__
if exist core\__pycache__ rmdir /s /q core\__pycache__

echo [3/3] Starting server...
echo.
python_runtime\python.exe app.py
