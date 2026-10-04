# Platform-Specific Installation Guide

This document describes the platform-specific installation setup for IPFS Datasets Python.

## Platform Detection

The `setup.py` automatically detects your platform using:
- `IS_WINDOWS` - Windows systems
- `IS_LINUX` - Linux systems  
- `IS_MACOS` - macOS (Darwin) systems
- `IS_64BIT` - 64-bit architecture

## Installation Extras

The package provides 18 extras groups for different features:

### Core Extras
- `ipld` - IPLD (InterPlanetary Linked Data) support
- `web_archive` - Web archiving tools (Internet Archive, Wayback, WARC)
- `security` - Cryptography and keyring support
- `audit` - Elasticsearch and audit logging
- `provenance` - Data provenance tracking with Plotly/Dash
- `alerts` - Discord notifications and async HTTP

### Feature Extras
- `test` - Testing framework (pytest, pytest-cov, pytest-xdist, etc.)
- `pdf` - PDF processing (pdfplumber, pymupdf, pytesseract, tiktoken)
- `multimedia` - Media processing (FFmpeg, yt-dlp, moviepy, PIL)
- `ml` - Machine Learning (PyTorch, LlamaIndex, OpenAI)
- `vectors` - Vector stores (FAISS, Qdrant, Elasticsearch)
- `scraping` - Web scraping (BeautifulSoup, Selenium, Scrapy)
- `api` - Web APIs (FastAPI, Flask, MCP)
- `dev` - Development tools (mypy, flake8, coverage, Faker)

### Platform-Specific Extras
- `windows` - Windows-specific packages (pywin32, python-magic-bin)
- `linux` - Linux-specific packages (python-magic)
- `macos` - macOS-specific packages (python-magic)
- `all` - All non-ML extras combined

## Installation Commands

### Basic Installation
```bash
# Core dependencies only
pip install -e .

# With specific feature
pip install -e ".[test]"
pip install -e ".[pdf]"
pip install -e ".[multimedia]"

# Multiple features
pip install -e ".[test,pdf,api]"
```

### Platform-Specific Installation

#### Windows
```powershell
# Core + Windows extras
pip install -e ".[windows]"

# All features + Windows extras
pip install -e ".[all,windows]"

# Specific features + Windows
pip install -e ".[test,pdf,multimedia,windows]"
```

#### Linux
```bash
# Core + Linux extras
pip install -e ".[linux]"

# All features + Linux extras
pip install -e ".[all,linux]"
```

#### macOS
```bash
# Core + macOS extras
pip install -e ".[macos]"

# All features + macOS extras
pip install -e ".[all,macos]"
```

## Platform-Specific Packages

### Windows
- `pywin32>=305` - Windows API access
- `python-magic-bin>=0.4.14` - File type detection (binary included)
- `faiss-cpu>=1.7.0` - Vector similarity search (older version for compatibility)

### Linux
- `python-magic>=0.4.27` - File type detection (requires libmagic)
- `faiss-cpu>=1.8.0` - Vector similarity search (latest version)

### macOS  
- `python-magic>=0.4.27` - File type detection (requires libmagic via Homebrew)
- May require Xcode Command Line Tools: `xcode-select --install`

## Known Platform Issues

### Windows - TESTED on Windows 11, Python 3.14.2

**✅ Working (86% of packages):**
- `test` extras - pytest, pytest-cov, coverage (all work)
- `windows` extras - pywin32, python-magic-bin (both work)
- `multimedia` extras - pillow, yt-dlp (both work)
- `api` extras - fastapi, uvicorn, flask (all work)
- `vectors` extras - faiss-cpu (works with >=1.7.0)
- `security` extras - cryptography (works)
- `pdf` extras - pdfplumber, tiktoken, pysbd (all work)

**⚠️ Known Issues:**
- ❌ `pymupdf` - DLL load failure on Windows
  - **Workaround:** Use `pdfplumber` instead (works perfectly)
  - **Alternative:** Install Microsoft Visual C++ Redistributable
- ⚠️ `ffmpeg-python` - Requires system ffmpeg binary
  - **Solution:** Install ffmpeg: `winget install ffmpeg` or download from ffmpeg.org
- ⚠️ `moviepy` - Requires ffmpeg (same as above)
- ⚠️ `pytesseract` - Requires Tesseract OCR installation  
  - **Solution:** Install Tesseract: `winget install UB-Mannheim.TesseractOCR`
- ⚠️ `opencv-contrib-python` may show "Clock skew detected" errors (cosmetic)
- ⚠️ `surya-ocr` excluded on Windows (Linux/Mac only)

**Test Results:** 6/7 extras groups fully functional (86% success rate)

### Linux
- ✅ All packages supported natively
- ℹ️ Some packages may require system dependencies (libmagic, tesseract, ffmpeg)

### macOS
- ℹ️ May need Xcode Command Line Tools
- ℹ️ libmagic: `brew install libmagic`
- ℹ️ tesseract: `brew install tesseract`
- ℹ️ ffmpeg: `brew install ffmpeg`

## Validation

### Quick Validation
```bash
python validate_platform_setup.py
```

### Comprehensive Test (Actually installs and imports packages)
```bash
python test_extras_windows.py
```

**Test Results on Windows 11:**
- ✅ 6/7 extras groups work (86%)
- ✅ All core dependencies installable
- ✅ Platform-specific packages functional
- ⚠️ pymupdf has DLL issues (use pdfplumber)

Both scripts will:
- Detect your platform
- Show available extras groups
- Validate platform-specific configuration
- Test actual package imports
- Provide installation recommendations

## Example Installation Workflows

### Data Scientist (Windows)
```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -e ".[ml,vectors,pdf,windows]"
```

### Web Developer (Linux)
```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[api,scraping,linux]"
```

### CI/CD Testing (All Platforms)
```bash
python -m venv .venv
source .venv/bin/activate  # or .\.venv\Scripts\activate on Windows
pip install -e ".[test,dev]"
pytest
```

### Full Installation (All Features)
```bash
# Windows
pip install -e ".[all,ml,windows]"

# Linux/macOS
pip install -e ".[all,ml,linux]"  # or macos
```

## Troubleshooting

### Import Error: No module named 'magic'
- **Windows**: Install `python-magic-bin` via `.[windows]` extra
- **Linux/Mac**: Install system libmagic and use `.[linux]` or `.[macos]` extra

### FAISS Installation Issues
- **Windows**: Uses `faiss-cpu>=1.7.0` (older but more compatible)
- **Linux/Mac**: Uses `faiss-cpu>=1.8.0` (latest)
- Alternative: Use conda: `conda install -c conda-forge faiss-cpu`

### ML Packages Too Large
- ML extras (torch, transformers) not included in `[all]`
- Install separately: `pip install -e ".[ml]"`
- Or use specific model: `pip install torch transformers`

## Files Modified

- `setup.py` - Added platform detection and 18 extras groups
- `install.py` - Added platform detection imports
- `quick_setup.py` - Platform-specific package selection
- `validate_platform_setup.py` - Quick validation script (NEW)
- `test_windows_install.py` - Comprehensive test script (NEW)

## Support

For platform-specific issues, check:
1. Run validation script: `python validate_platform_setup.py`
2. Check system dependencies (libmagic, tesseract, ffmpeg)
3. Review error messages for missing system libraries
4. Consider using conda for complex dependencies (faiss, torch)

Last updated: 2026-01-16
