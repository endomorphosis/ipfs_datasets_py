@echo off
call venv\Scripts\activate

deactivate


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
    REM Activate the virtual environment
    echo Activating the virtual environment 'venv'...
    call venv\Scripts\activate.bat
) else (
    REM If venv doesn't exist, exit
    echo Virtual environment doesn't exist. Exiting...
    exit /b 1
)

REM Run pytest on the test directory
echo *** BEGIN TESTS ***

pytest test\

echo *** END TESTS ***

REM Deactivate the virtual environment
call deactivate
