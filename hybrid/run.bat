@echo off
setlocal

echo ========================================
echo Starting App
echo ========================================

REM Check if virtual environment exists
if not exist ".venv" (
    echo Virtual environment not found.
    echo Please run setup.bat first.
    echo.
    pause
    exit /b 1
)

REM Activate virtual environment
call .venv\Scripts\activate.bat
if errorlevel 1 (
    echo Failed to activate virtual environment.
    echo Please run setup.bat again.
    echo.
    pause
    exit /b 1
)

REM Check if secrets.env exists
if not exist "secrets.env" (
    echo secrets.env not found.
    echo Please run setup.bat and fill out secrets.env.
    echo.
    pause
    exit /b 1
)

REM Run the Streamlit app
echo.
echo Launching Streamlit...
streamlit run src\app.py

pause