@echo off
setlocal

echo ========================================
echo Project Setup
echo ========================================

REM Check if Python 3.11 is installed through the Python Launcher
py -3.11 --version >nul 2>&1
if errorlevel 1 (
    echo Python 3.11 was not found.
    echo.
    echo Please install Python 3.11 from:
    echo https://www.python.org/downloads/release/python-311/
    echo.
    echo IMPORTANT: During installation, check:
    echo "Add python.exe to PATH"
    echo.
    echo After installing Python 3.11, run setup.bat again.
    echo.
    pause
    exit /b 1
)

echo Python 3.11 found:
py -3.11 --version

REM Create virtual environment if it does not exist
if not exist ".venv" (
    echo.
    echo Creating virtual environment using Python 3.11...
    py -3.11 -m venv .venv
    if errorlevel 1 (
        echo.
        echo Failed to create virtual environment.
        pause
        exit /b 1
    )
) else (
    echo.
    echo Virtual environment already exists.
)

REM Activate virtual environment
echo.
echo Activating virtual environment...
call .venv\Scripts\activate.bat
if errorlevel 1 (
    echo.
    echo Failed to activate virtual environment.
    pause
    exit /b 1
)

REM Upgrade pip
echo.
echo Upgrading pip...
python -m pip install --upgrade pip
if errorlevel 1 (
    echo.
    echo Failed to upgrade pip.
    pause
    exit /b 1
)

REM Install dependencies
echo.
echo Installing dependencies...
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo Failed to install dependencies.
    pause
    exit /b 1
)

REM Create secrets.env if missing
if not exist "secrets.env" (
    if exist "secrets.env.example" (
        echo.
        echo Creating secrets.env from secrets.env.example...
        copy secrets.env.example secrets.env
    ) else (
        echo.
        echo WARNING: secrets.env.example not found.
    )
) else (
    echo.
    echo secrets.env already exists.
)

echo.
echo ========================================
echo Setup complete.
echo ========================================
echo.
echo Next steps:
echo 1. Open secrets.env
echo 2. Add your API keys/settings
echo 3. Set GEMINI_MODEL=gemini-3.5-flash
echo 4. Run run.bat
echo.

pause