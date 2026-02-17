# Knowledge Graphs Lineage Migration - Troubleshooting Guide

This guide helps you resolve common issues encountered during the lineage package migration.

## Table of Contents

1. [Migration Script Issues](#migration-script-issues)
2. [Import Errors](#import-errors)
3. [Deprecation Warnings](#deprecation-warnings)
4. [Test Failures](#test-failures)
5. [Rollback Issues](#rollback-issues)
6. [Performance Issues](#performance-issues)
7. [Advanced Troubleshooting](#advanced-troubleshooting)

---

## Migration Script Issues

### Issue: "Permission denied" when running shell script

**Symptom:**
```bash
$ ./scripts/migration/migrate_lineage.sh myfile.py
bash: ./scripts/migration/migrate_lineage.sh: Permission denied
```

**Solution:**
```bash
chmod +x scripts/migration/migrate_lineage.sh
./scripts/migration/migrate_lineage.sh myfile.py
```

---

### Issue: Python script not found

**Symptom:**
```bash
$ python scripts/migration/migrate_lineage_imports.py
python: can't open file 'scripts/migration/migrate_lineage_imports.py': [Errno 2] No such file or directory
```

**Solution:**
Make sure you're in the project root directory:
```bash
cd /path/to/ipfs_datasets_py
python scripts/migration/migrate_lineage_imports.py --help
```

---

### Issue: Script modifies wrong files

**Symptom:**
The migration script changes files it shouldn't, or misses files it should change.

**Solution:**
1. **Use dry-run first** to preview changes:
   ```bash
   python scripts/migration/migrate_lineage_imports.py --dry-run .
   ```

2. **Check your path** - ensure you're targeting the right directory:
   ```bash
   # Wrong - modifies system files
   python scripts/migration/migrate_lineage_imports.py /
   
   # Right - modifies your project
   python scripts/migration/migrate_lineage_imports.py ./src/
   ```

3. **Review the output** before proceeding with actual migration.

---

### Issue: Migration creates too many backup files

**Symptom:**
Your directory is cluttered with `.backup` files.

**Solution:**
1. **Clean up backups after successful migration:**
   ```bash
   find . -name "*.backup" -delete
   ```

2. **Use no-backup mode** if you're confident:
   ```bash
   python scripts/migration/migrate_lineage_imports.py --no-backup .
   ```

3. **Or use version control** as your backup (recommended):
   ```bash
   git commit -am "Before lineage migration"
   python scripts/migration/migrate_lineage_imports.py --no-backup .
   git diff  # Review changes
   ```

---

## Import Errors

### Issue: ImportError after migration

**Symptom:**
```python
ImportError: cannot import name 'EnhancedLineageTracker' from 'ipfs_datasets_py.knowledge_graphs.lineage'
```

**Solutions:**

**1. Check Python path:**
```bash
python -c "import sys; print('\n'.join(sys.path))"
```

**2. Reinstall the package:**
```bash
pip install -e .
# or
python setup.py develop
```

**3. Check import is correct:**
```python
# Wrong
from ipfs_datasets_py.knowledge_graphs.cross_document_lineage import EnhancedLineageTracker

# Right
from ipfs_datasets_py.knowledge_graphs.lineage import EnhancedLineageTracker
```

**4. Clear Python cache:**
```bash
find . -type d -name __pycache__ -exec rm -rf {} +
find . -type f -name "*.pyc" -delete
```

---

### Issue: ModuleNotFoundError for 'lineage'

**Symptom:**
```python
ModuleNotFoundError: No module named 'ipfs_datasets_py.knowledge_graphs.lineage'
```

**Solutions:**

**1. Ensure package is properly installed:**
```bash
pip list | grep ipfs-datasets
```

**2. Check lineage package exists:**
```bash
ls -la ipfs_datasets_py/knowledge_graphs/lineage/
```

**3. Verify __init__.py exists:**
```bash
cat ipfs_datasets_py/knowledge_graphs/lineage/__init__.py
```

**4. Reinstall in development mode:**
```bash
pip uninstall ipfs-datasets-py
pip install -e .
```

---

### Issue: Circular import error

**Symptom:**
```python
ImportError: cannot import name 'X' from partially initialized module 'Y' (most likely due to a circular import)
```

**Solutions:**

**1. Check for circular dependencies:**
```bash
# Find potential circular imports
grep -r "from.*lineage" ipfs_datasets_py/knowledge_graphs/lineage/
```

**2. Use lazy imports** if needed:
```python
# Instead of top-level import
def my_function():
    from ipfs_datasets_py.knowledge_graphs.lineage import EnhancedLineageTracker
    return EnhancedLineageTracker()
```

**3. Report the issue** - this shouldn't happen with the new package structure.

---

## Deprecation Warnings

### Issue: Too many deprecation warnings

**Symptom:**
```
DeprecationWarning: cross_document_lineage module is deprecated.
DeprecationWarning: cross_document_lineage module is deprecated.
... (repeated many times)
```

**Solutions:**

**1. Migrate your imports** (recommended):
```bash
python scripts/migration/migrate_lineage_imports.py .
```

**2. Suppress warnings temporarily** (not recommended):
```python
import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)
```

**3. Suppress specific warnings:**
```python
import warnings
warnings.filterwarnings(
    "ignore",
    message="cross_document_lineage module is deprecated",
    category=DeprecationWarning
)
```

**4. In pytest:**
```python
# In pytest.ini or setup.cfg
[tool:pytest]
filterwarnings =
    ignore::DeprecationWarning:ipfs_datasets_py.knowledge_graphs.cross_document_lineage
```

---

### Issue: Deprecation warning in production logs

**Symptom:**
Your production logs are filled with deprecation warnings.

**Solutions:**

**1. Migrate immediately** (recommended):
```bash
python scripts/migration/migrate_lineage_imports.py --validate /path/to/app/
```

**2. Configure logging** to filter warnings:
```python
import logging
logging.captureWarnings(True)
warnings_logger = logging.getLogger('py.warnings')
warnings_logger.setLevel(logging.ERROR)
```

**3. Set environment variable:**
```bash
export PYTHONWARNINGS="ignore::DeprecationWarning"
python your_app.py
```

---

## Test Failures

### Issue: Tests fail after migration

**Symptom:**
```
FAILED test_module.py::test_function - ImportError: cannot import name ...
```

**Solutions:**

**1. Check test file imports:**
```bash
grep -r "cross_document_lineage" tests/
```

**2. Update test imports:**
```bash
python scripts/migration/migrate_lineage_imports.py tests/
```

**3. Clear pytest cache:**
```bash
rm -rf .pytest_cache
pytest --cache-clear
```

**4. Check for hardcoded paths:**
```python
# Bad - hardcoded old path
sys.path.insert(0, "ipfs_datasets_py/knowledge_graphs/cross_document_lineage")

# Good - use new path
sys.path.insert(0, "ipfs_datasets_py/knowledge_graphs/lineage")
```

---

### Issue: Mock imports fail

**Symptom:**
```python
ERROR: test_module.py - ModuleNotFoundError: No module named 'cross_document_lineage'
```

**Solution:**
Update mock paths in tests:
```python
# Old
@patch('module.cross_document_lineage.EnhancedLineageTracker')
def test_something(mock_tracker):
    pass

# New
@patch('module.lineage.EnhancedLineageTracker')
def test_something(mock_tracker):
    pass
```

---

### Issue: Fixture imports fail

**Symptom:**
```python
ERROR at setup of test_function: cannot import name 'X' from 'Y'
```

**Solution:**
Update conftest.py imports:
```python
# conftest.py
# Old
from ipfs_datasets_py.knowledge_graphs.cross_document_lineage import EnhancedLineageTracker

# New
from ipfs_datasets_py.knowledge_graphs.lineage import EnhancedLineageTracker
```

---

## Rollback Issues

### Issue: Rollback doesn't restore files

**Symptom:**
```bash
$ python scripts/migration/migrate_lineage_imports.py --rollback .
No backup files found
```

**Solutions:**

**1. Check if backups exist:**
```bash
find . -name "*.backup"
```

**2. If backups were deleted:**
```bash
# Use git to restore
git status
git diff
git checkout -- .
```

**3. If migration used --no-backup:**
```bash
# Restore from git
git log --oneline
git checkout <commit-before-migration> -- .
```

---

### Issue: Rollback leaves mixed state

**Symptom:**
Some files rolled back, others didn't, imports are inconsistent.

**Solution:**
```bash
# Clean slate approach
git checkout -- .  # Restore all from git
python scripts/migration/migrate_lineage_imports.py .  # Re-migrate
```

---

## Performance Issues

### Issue: Migration script is slow

**Symptom:**
Migration takes several minutes for large codebase.

**Solutions:**

**1. Run on specific directories:**
```bash
# Instead of entire project
python scripts/migration/migrate_lineage_imports.py ./src/
```

**2. Use shell script** (faster for simple cases):
```bash
./scripts/migration/migrate_lineage.sh ./src/
```

**3. Exclude unnecessary directories:**
```bash
# Create temporary .gitignore-like file
python scripts/migration/migrate_lineage_imports.py . \
    --exclude=node_modules,venv,.git
```

---

### Issue: Import performance degraded after migration

**Symptom:**
Application startup or imports are noticeably slower.

**Solution:**
This shouldn't happen - import paths are actually shorter now. If you experience this:

**1. Clear Python bytecode cache:**
```bash
find . -type d -name __pycache__ -exec rm -rf {} +
python -m compileall .
```

**2. Check for import loops:**
```bash
python -X importtime your_app.py 2>&1 | grep lineage
```

**3. Profile imports:**
```python
import importtime
with importtime.time_imports():
    from ipfs_datasets_py.knowledge_graphs.lineage import EnhancedLineageTracker
```

---

## Advanced Troubleshooting

### Debug: Enable verbose logging

**Python script:**
```bash
python scripts/migration/migrate_lineage_imports.py --verbose --dry-run .
```

**In your code:**
```python
import logging
logging.basicConfig(level=logging.DEBUG)

from ipfs_datasets_py.knowledge_graphs.lineage import EnhancedLineageTracker
```

---

### Debug: Check what was actually changed

**After migration:**
```bash
# See all changes
git diff

# See only import changes
git diff | grep "import.*lineage"

# Count changes
git diff --stat
```

---

### Debug: Validate migration completeness

**Check for remaining old imports:**
```bash
# Find any remaining old imports
grep -r "cross_document_lineage" . \
    --include="*.py" \
    --exclude-dir=".git" \
    --exclude-dir="__pycache__" \
    --exclude-dir=".backup"
```

**Expected:** Should only find imports in:
- `cross_document_lineage.py` (deprecation wrapper)
- `cross_document_lineage_enhanced.py` (deprecation wrapper)
- Documentation files (*.md)
- Backup files (*.backup)

---

### Debug: Test import manually

**Interactive Python:**
```python
# Test old import (should work with warning)
from ipfs_datasets_py.knowledge_graphs.cross_document_lineage import EnhancedLineageTracker
# Should show: DeprecationWarning

# Test new import (should work without warning)
from ipfs_datasets_py.knowledge_graphs.lineage import EnhancedLineageTracker
# Should work silently

# Verify they're the same class
print(EnhancedLineageTracker.__module__)
```

---

### Debug: Check Python environment

```bash
# Python version
python --version

# Installed packages
pip list | grep ipfs

# Package location
python -c "import ipfs_datasets_py; print(ipfs_datasets_py.__file__)"

# Import path
python -c "import sys; import pprint; pprint.pprint(sys.path)"
```

---

## Getting Help

If none of these solutions work:

### 1. Gather Diagnostic Information

```bash
# System info
python --version
pip list | grep ipfs

# Migration attempt
python scripts/migration/migrate_lineage_imports.py --dry-run --verbose . > migration_output.txt 2>&1

# Current state
grep -r "cross_document_lineage" . --include="*.py" > remaining_imports.txt
```

### 2. Create Minimal Reproduction

```python
# minimal_repro.py
from ipfs_datasets_py.knowledge_graphs.lineage import EnhancedLineageTracker

tracker = EnhancedLineageTracker()
print("Success!")
```

### 3. Open GitHub Issue

Include:
- Python version
- Package version
- Operating system
- Migration command used
- Error message (full traceback)
- Diagnostic information from above
- Minimal reproduction case

---

## Prevention

### Best Practices to Avoid Issues

1. **Always use dry-run first:**
   ```bash
   python scripts/migration/migrate_lineage_imports.py --dry-run .
   ```

2. **Commit before migrating:**
   ```bash
   git commit -am "Before lineage migration"
   ```

3. **Test after migrating:**
   ```bash
   pytest
   ```

4. **Use validation:**
   ```bash
   python scripts/migration/migrate_lineage_imports.py --validate .
   ```

5. **Keep backups:**
   - Don't use `--no-backup` until you're confident
   - Don't delete `.backup` files until migration is verified

---

## Quick Command Reference

```bash
# Troubleshooting commands
python scripts/migration/migrate_lineage_imports.py --dry-run --verbose .
git diff
pytest --tb=short
grep -r "cross_document_lineage" . --include="*.py"
find . -name "*.backup"

# Recovery commands
python scripts/migration/migrate_lineage_imports.py --rollback .
git checkout -- .
find . -name "*.backup" -exec sh -c 'mv "$1" "${1%.backup}"' _ {} \;

# Validation commands
python scripts/migration/migrate_lineage_imports.py --validate .
pytest
python -c "from ipfs_datasets_py.knowledge_graphs.lineage import *"
```

---

**Remember:** Most issues can be resolved by:
1. Reading error messages carefully
2. Checking import statements
3. Using dry-run mode
4. Having git backups
5. Asking for help when stuck!
