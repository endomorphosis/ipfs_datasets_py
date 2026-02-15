@echo off
REM Echo to indicate start of the program
echo STARTING PROGRAM...

REM Activate the virtual environment
call venv\Scripts\activate.bat
REM Echo to indicate the start of the Python script
echo *** BEGIN PROGRAM ***

REM Run the Python script
python main.py

REM Echo to indicate the end of the Python script
echo *** END PROGRAM ***

REM Deactivate the virtual environment
call deactivate

REM Echo to indicate program completion
echo PROGRAM EXECUTION COMPLETE.
timeout /t 30
