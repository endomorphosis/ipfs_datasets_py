@echo off
REM Quick test script for diagnosing failing state scrapers (Windows)
REM Run this from the scripts directory or repository root

echo ========================================================================
echo DIAGNOSTIC TEST FOR FAILING STATE LAW SCRAPERS
echo ========================================================================
echo.
echo This will test 11 failing states and provide detailed diagnostics
echo Results will be saved to: diagnostic_results/
echo.
echo Installing dependencies if needed...

REM Check and install dependencies
python -c "import requests" 2>nul || pip install requests
python -c "import bs4" 2>nul || pip install beautifulsoup4

echo.
echo Running diagnostic tests...
echo.

REM Run the diagnostic script from scripts directory
cd /d %~dp0
python diagnostic_test_states.py

echo.
echo ========================================================================
echo TESTS COMPLETE
echo ========================================================================
echo.
echo Results saved in: diagnostic_results/
echo.
echo Key files to review:
echo   - diagnostic_summary.json    (Overall summary)
echo   - diagnostic_test.log        (Full execution log)
echo   - ^<STATE^>_diagnostic.json    (Individual state details)
echo   - ^<STATE^>_sample.html        (HTML samples from each site)
echo.
echo Share these files to help diagnose and fix scraper issues.
echo.
echo See docs/README_DIAGNOSTICS.md for detailed instructions.
echo.
pause
