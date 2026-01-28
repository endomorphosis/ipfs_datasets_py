# Root Directory Reorganization

**Date:** 2026-01-28  
**Status:** ✅ Complete

## Overview

The root directory of ipfs_datasets_py has been reorganized to improve maintainability and follow Python project best practices. This document describes the changes made and how they affect the project.

## Summary of Changes

### Before Reorganization
- **76 Python files** in root directory
- **11 HTML files** in root directory
- **Total:** 100+ files cluttering the root

### After Reorganization
- **8 Python files** in root directory (89% reduction)
- **0 HTML files** in root directory
- All files organized in appropriate subdirectories

## File Moves

### 1. Test Files → `tests/integration/`

**32 files moved:**
```
test_*.py files (27 files)
_test_with_faker.py
simple_test.py
docker_test.py
comprehensive_cli_test.py
```

**Path Updates:**
- GitHub workflow: `.github/workflows/example-cached-workflow.yml` updated
- Import statements in moved test files updated to handle new paths

### 2. Validation Scripts → `scripts/validation/`

**10 files moved:**
```
validate_caselaw_setup.py
validate_mcp_dashboard.py
validate_platform_setup.py
validate_scraper_framework.py
validate_testing_framework.py
check_indiana.py
check_scraper_status.py
comprehensive_runner_validation.py
comprehensive_scraper_validation.py
example_scraper_validation.py
```

**Usage:** `python scripts/validation/validate_caselaw_setup.py`

### 3. Installation/Setup Scripts → `scripts/setup/`

**4 files moved:**
```
install.py
install_deps.py
quick_setup.py
ipfs_auto_install_config.py
```

**New Usage:**
```bash
# Old:
python install.py --quick

# New:
python scripts/setup/install.py --quick
```

### 4. Debug Scripts → `scripts/debug/`

**3 files moved:**
```
debug_caselaw.py
debug_delaware_html.py
inspect_pages.py
```

### 5. Dashboard Scripts → `scripts/dashboard/`

**4 files moved:**
```
capture_dashboard_screenshot.py
take_dashboard_screenshots.py
mcp_dashboard_tests.py
demo_dashboards.py
```

### 6. Migration Helpers → `scripts/migration/`

**3 files moved:**
```
migrate_to_anyio.py
anyio_migration_helpers.py
cleanup_pytest_conflicts.py
```

### 7. Demo Scripts → `scripts/demo/`

**9 files moved:**
```
demo_cli.py
demo_mcp_conversion.py
demo_patent_scraper.py
bulk_caselaw_demo.py
bulk_processing_concept_demo.py
caselaw_dashboard_demo.py
fixed_caselaw_dashboard_demo.py
comprehensive_legal_debugger_demo.py
final_demonstration.py
```

**New Usage:**
```bash
# Old:
python demo_cli.py

# New:
python scripts/demo/demo_cli.py
```

### 8. Utility Scripts → `scripts/utilities/`

**4 files moved:**
```
dependency_health_checker.py
dependency_manager.py
scraper_management.py
final_documentation_verification.py
```

**New Usage:**
```bash
# Old:
python dependency_health_checker.py check

# New:
python scripts/utilities/dependency_health_checker.py check
```

### 9. Dashboard HTML Files → `docs/dashboards/`

**11 files moved:**
```
advanced_dashboard_final.html
bulk_processing_dashboard_preview.html
caselaw_dashboard_preview.html
comprehensive_mcp_dashboard_final.html
enhanced_dashboard_preview.html
fixed_caselaw_dashboard.html
fixed_dashboard_working.html
maps_tab_demonstration.html
mcp_dashboard_screenshot.html
professional_desktop_dashboard.html
working_mcp_dashboard.html
```

## Files Kept in Root

The following files remain in the root directory as they are standard for Python projects:

### Core Files
- `setup.py` - Package setup and configuration
- `requirements.txt` - Python dependencies
- `README.md` - Project documentation
- `LICENSE` - License information
- `CHANGELOG.md` - Change history
- `TODO.md` - Project tasks
- `CLAUDE.md` - AI worker coordination

### Configuration Files
- `pytest.ini` - Test configuration
- `pytest.ini.mcp` - MCP-specific test config
- `mypy.ini` - Type checking configuration
- `docker-compose.yml` - Docker orchestration
- `Dockerfile*` - Container definitions

### CLI Entry Points
- `ipfs_datasets_cli.py` - Main CLI entry point
- `mcp_cli.py` - MCP CLI entry point
- `enhanced_cli.py` - Enhanced CLI interface
- `integrated_cli.py` - Integrated CLI interface
- `comprehensive_distributed_cli.py` - Distributed CLI
- `comprehensive_mcp_tools.py` - MCP tools interface

## Path Reference Updates

### Documentation Updates
- `README.md` - Updated all script path references
- Installation commands now use `scripts/setup/install.py`
- Dependency checker commands now use `scripts/utilities/dependency_health_checker.py`

### Workflow Updates
- `.github/workflows/example-cached-workflow.yml` - Updated test file path

### Import Updates
All moved Python files had their imports updated to work from new locations:
- `sys.path.insert()` statements updated with correct relative paths
- Script references updated to use new paths

## Testing

### Verification Steps Completed
1. ✅ Imports tested for moved files
2. ✅ Main CLI (`ipfs_datasets_cli.py`) verified working
3. ✅ Simple integration test verified from new location
4. ✅ Git tracking maintained (files moved, not copied)

### How to Test After Update
```bash
# Test CLI still works
python ipfs_datasets_cli.py --help

# Test moved scripts work
python scripts/setup/install.py --help
python scripts/utilities/dependency_health_checker.py --help

# Run tests from new location
pytest tests/integration/test_cli.py
```

## Migration Guide

### For Developers

If you have local changes or scripts that reference the old paths:

1. **Update script calls:**
   ```bash
   # Old
   python test_cli.py
   
   # New
   python tests/integration/test_cli.py
   ```

2. **Update imports in custom scripts:**
   ```python
   # If you were importing from root
   sys.path.insert(0, str(Path(__file__).parent))
   
   # Update to account for new structure
   sys.path.insert(0, str(Path(__file__).parent.parent))
   ```

3. **Update documentation references:**
   - Search for old paths in your docs
   - Update to new organized structure

### For CI/CD Pipelines

Most workflows are unchanged. Only update if you:
- Reference specific test files directly
- Call validation scripts
- Use installation scripts

## Benefits

1. **Cleaner Root Directory** - 89% reduction in root-level files
2. **Better Organization** - Files grouped by purpose
3. **Easier Navigation** - Clear structure for contributors
4. **Maintainability** - Easier to find and maintain scripts
5. **Best Practices** - Follows Python project conventions
6. **Backward Compatibility** - Core CLI tools remain accessible

## Rollback Instructions

If needed, the reorganization can be rolled back:

```bash
git revert <commit-hash>
```

The reorganization script (`reorganize_root.py`) is preserved for reference but is not needed for normal operation.

## Related Documentation

- [Project README](../README.md)
- [Contributing Guide](../CLAUDE.md)
- [Scripts Documentation](../scripts/README.md)
- [Testing Guide](../tests/README.md)

## Questions?

If you encounter issues after the reorganization:
1. Check this document for the new file locations
2. Update your local scripts to use new paths
3. Refer to updated README.md for command examples
4. Open an issue if you find broken references

---

**Reorganization Script:** `reorganize_root.py` (in root for reference)  
**Commit:** See git history for full changes  
**Next Review:** Consider moving additional documentation to `docs/` subdirectory
