@echo off
echo Setting up the environment...

REM Check if Python is installed
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo Python is not installed. Please install Python 3.7 or later and add it to your PATH.
    exit /b 1
)

REM Check if the virtual environment already exists
if exist venv (
    echo Virtual environment already exists. Skipping creation.
) else (
    REM Create a virtual environment if it doesn't exist
    echo Creating a virtual environment...
    python -m venv venv
)

REM Activate the virtual environment
echo Activating the virtual environment 'venv'...
call venv\Scripts\activate.bat

REM Install required packages from requirements.txt
if exist requirements.txt (
    echo Installing required packages...
    pip install -r requirements.txt
) else (
    echo requirements.txt not found. Skipping package installation.
)

echo Setup complete!
timeout /t 30