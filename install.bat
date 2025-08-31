@echo off
:: Enhanced Installation script for ipfs_datasets_py (Windows)
:: This script sets up the necessary dependencies and configures the environment
:: with automatic dependency installation for Windows

echo 🚀 Installing ipfs_datasets_py with automated dependency management...

:: Function to install system dependencies
echo 🔧 Installing system dependencies for Windows...

:: Check for Chocolatey
choco --version >nul 2>&1
if %errorlevel% == 0 (
    echo 📦 Using Chocolatey package manager...
    choco install tesseract ffmpeg opencv poppler -y
) else (
    echo ⚠️ Chocolatey not found. Checking for Scoop...
    scoop --version >nul 2>&1
    if errorlevel 0 (
        echo 📦 Using Scoop package manager...
        scoop install tesseract ffmpeg opencv poppler
    ) else (
        echo ⚠️ No supported package manager found.
        echo Please install Chocolatey or Scoop, then run this script again.
        echo Chocolatey: https://chocolatey.org/install
        echo Scoop: https://scoop.sh/
        echo.
        echo Or install these manually:
        echo - Tesseract OCR
        echo - FFmpeg
        echo - OpenCV
        echo - Poppler
        pause
        exit /b 1
    )
)

:: Check for Python 3.10+
set python_cmd=
for %%c in (python3.12 python3.11 python3.10 python3 python) do (
    %%c --version >nul 2>&1
    if not errorlevel 1 (
        for /f "tokens=2" %%v in ('%%c --version 2^>^&1') do (
            echo %%v | findstr /r "^3\.[1-9][0-9]\|^3\.1[0-9]" >nul
            if not errorlevel 1 (
                set python_cmd=%%c
                set python_version=%%v
                goto :python_found
            )
        )
    )
)

echo ❌ Error: Python 3.10+ is required but not found
echo Please install Python 3.10 or later from https://python.org
pause
exit /b 1

:python_found
echo ✅ Using Python: %python_cmd% (version %python_version%)

:: Create virtual environment if it doesn't exist
if not exist "venv" (
    echo 📦 Creating virtual environment...
    %python_cmd% -m venv venv
)

:: Activate virtual environment
echo 🔄 Activating virtual environment...
call venv\Scripts\activate.bat

:: Upgrade pip and install build tools
echo ⬆️ Upgrading pip and installing build tools...
python -m pip install --upgrade pip setuptools wheel

:: Install core dependencies first
echo 📚 Installing core dependencies...
pip install -r requirements.txt

:: Install the package in development mode
echo 🛠️ Installing ipfs_datasets_py in development mode...
pip install -e .

:: Run automated dependency installer for GraphRAG
echo 🤖 Running automated dependency installation for GraphRAG...
python -c "import sys; import os; sys.path.insert(0, '.'); from ipfs_datasets_py.auto_installer import install_for_component; print('Installing GraphRAG dependencies...'); success = install_for_component('graphrag'); print('✅ GraphRAG dependencies installed successfully' if success else '⚠️ Some GraphRAG dependencies may have failed to install'); sys.exit(0)"

:: Verify installation
echo 🔍 Verifying installation...
python -c "try: import ipfs_datasets_py; print('✅ ipfs_datasets_py imports successfully'); from ipfs_datasets_py import PDFProcessor, GraphRAGIntegrator; print('✅ PDFProcessor available' if PDFProcessor is not None else '⚠️ PDFProcessor not available'); print('✅ GraphRAGIntegrator available' if GraphRAGIntegrator is not None else '⚠️ GraphRAGIntegrator not available'); print('📊 Installation verification complete'); except Exception as e: print(f'⚠️ Import test failed: {e}'); print('The installation may be incomplete but core functionality should work')"

echo.
echo 🎉 Installation complete!
echo.
echo 📋 Next steps:
echo 1. Activate the virtual environment:
echo    venv\Scripts\activate.bat
echo 2. Run tests: python -m pytest tests/
echo 3. Try the GraphRAG demo: python demonstrate_graphrag_pdf.py --create-sample
echo 4. Check system dependencies: python ipfs_datasets_py/auto_installer.py graphrag --verbose
echo.
echo 🔧 Configuration:
echo - Set IPFS_AUTO_INSTALL=false to disable automatic dependency installation
echo - Set IPFS_INSTALL_VERBOSE=true for verbose installation output
echo.
echo 📚 For more information, see README.md

pause