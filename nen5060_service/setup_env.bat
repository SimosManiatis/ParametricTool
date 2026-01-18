@echo off
echo ===================================================
echo  NEN 5060 Service - Environment Setup
echo ===================================================
echo.
echo This script will set up the Python virtual environment.
echo NOTE: You MUST have Python 3.9, 3.10, 3.11, or 3.12 installed.
echo Python 3.13 and 3.14 are NOT supported by rhino3dm.
echo.

set /p py_cmd="Enter your python command (e.g. 'py -3.11' or full path to python.exe): "

if "%py_cmd%"=="" set py_cmd=python

echo.
echo Using: %py_cmd%
echo Creating virtual environment in .venv...
"%py_cmd%" -m venv .venv

if errorlevel 1 (
    echo.
    echo ERROR: Failed to create venv. Check if Python is installed and valid.
    pause
    exit /b 1
)

echo.
echo Installing dependencies...
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\python -m pip install -r requirements.txt

if errorlevel 1 (
    echo.
    echo ERROR: Failed to install dependencies.
    echo If failing on rhino3dm, ensure you are NOT using Python 3.13+.
    pause
    exit /b 1
)

echo.
echo SUCCESS! Environmental setup complete.
echo To run the server: run_server.bat
pause
