# Root Directory Cleanup Plan

## Current Status Analysis

The root directory contains approximately 200+ files, many of which are:
- Test files from development/migration process
- Documentation from migration
- Temporary/debug files
- Configuration files
- Generated reports

## Cleanup Strategy

### 1. KEEP IN ROOT (Core Files)
- `README.md` - Main project documentation
- `LICENSE` - License file
- `pyproject.toml` - Package configuration
- `setup.py` - Package setup
- `requirements.txt` - Dependencies
- `Dockerfile` - Container configuration
- `__init__.py` - Package init
- `.gitignore` - Git ignore rules
- `package.json` - NPM dependencies (if needed)
- `pytest.ini` - Test configuration

### 2. MOVE TO DOCS/ (Documentation)
- All `*.md` files except README.md and LICENSE
- Migration reports
- Testing guides
- Configuration summaries

### 3. ARCHIVE (Development/Migration Artifacts)
Create `/archive/migration_artifacts/` for:
- All test files (`test_*.py`, `*_test.py`)
- Debug files (`debug_*.py`)
- Migration demo files
- Temporary configuration files
- Test results and reports (JSON files)

### 4. ORGANIZE INTO PROPER DIRECTORIES
- Move all Python test files to `/tests/`
- Move configuration files to `/config/`
- Move build artifacts to `/build/`
- Keep main directories: `ipfs_datasets_py/`, `docs/`, `examples/`, `test/`

### 5. DELETE (Temporary/Generated Files)
- `__pycache__/` directories
- Build artifacts in `/build/` and `/dist/`
- Temporary files
- Duplicate files (`.backup` files)

## Directory Structure After Cleanup

```
ipfs_datasets_py/
├── README.md
├── LICENSE
├── pyproject.toml
├── setup.py
├── requirements.txt
├── Dockerfile
├── __init__.py
├── .gitignore
├── package.json
├── pytest.ini
├── ipfs_datasets_py/          # Main package
├── docs/                      # All documentation
├── config/                    # Configuration files
├── examples/                  # Usage examples
├── tests/                     # All test files
├── archive/                   # Migration artifacts
│   └── migration_artifacts/
├── logs/                      # Log files
├── audit_reports/             # Audit reports
└── test_results/              # Test results
```
