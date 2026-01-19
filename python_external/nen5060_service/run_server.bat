@echo off
echo ===================================================
echo  Starting NEN 5060 Service (Portable)
echo ===================================================
echo.

set PY_EXE=python_runtime\python.exe

if not exist %PY_EXE% (
    echo ERROR: Portable python not found at %PY_EXE%
    echo Please run install_portable_python.ps1 first.
    pause
    exit /b 1
)

REM Verify Python path
echo Using Python Interpreter:
%PY_EXE% -c "import sys; print(sys.executable)"

REM Verify installed packages
echo.
echo Installed Packages:
%PY_EXE% -m pip list
echo.

echo Starting Server...
echo.
%PY_EXE% app.py

if errorlevel 1 (
    echo.
    echo SERVER CRASHED.
)

pause
