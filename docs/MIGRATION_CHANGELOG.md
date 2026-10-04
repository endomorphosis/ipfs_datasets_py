# CHANGELOG

## [Unreleased]

### Added - v2.0.0 Migration
- **Major architectural consolidation**: Moved `data_transformation/` modules into `processors/` for better organization
- New package structure:
  - `processors/storage/ipld/` - IPLD storage, knowledge graphs, vector stores (147KB)
  - `processors/serialization/` - CAR, Parquet, JSONL conversion (388KB)
  - `processors/ipfs/` - IPFS multiformats and UnixFS utilities (51KB)
  - `processors/auth/` - UCAN authentication (60KB)
- Comprehensive migration documentation (63KB across 5 guides)
- Backward compatibility shims with 6-month deprecation window
- 18 comprehensive migration tests in `tests/unit/test_data_transformation_migration.py`

### Changed
- **Import paths updated** (backward compatible until v2.0.0, August 2026):
  - `data_transformation.ipld` → `processors.storage.ipld`
  - `data_transformation.serialization` → `processors.serialization`
  - `data_transformation.ipfs_formats` → `processors.ipfs.formats`
  - `data_transformation.unixfs` → `processors.ipfs` (UnixFSHandler)
  - `data_transformation.ucan` → `processors.auth.ucan`

### Deprecated
- All `data_transformation/` import paths (removal in v2.0.0, August 2026)
- Old import paths will issue `DeprecationWarning` with migration instructions

### Fixed
- UnixFS import: Corrected class name from `UnixFS` to `UnixFSHandler` in `processors/ipfs/__init__.py`

### Documentation
- `docs/COMPLETE_MIGRATION_GUIDE.md` - Comprehensive user migration guide with examples
- `docs/PROCESSORS_DATA_TRANSFORMATION_QUICK_MIGRATION.md` - Quick reference guide
- `docs/PROCESSORS_DATA_TRANSFORMATION_INTEGRATION_PLAN_V2.md` - Full implementation plan
- `docs/DATA_TRANSFORMATION_MIGRATION_SUMMARY.md` - Executive summary
- `docs/FINAL_STATUS_REPORT.md` - Project completion report
- `docs/PHASE_7_TESTING_COMPLETE.md` - Testing validation report

### Migration Timeline
- **Now (v1.x)**: Both old and new import paths work, deprecation warnings issued
- **August 2026 (v2.0.0)**: Old import paths removed, only new paths work
- **Migration Window**: 6 months for users to update their code

### Migration Guide
See `docs/COMPLETE_MIGRATION_GUIDE.md` for detailed migration instructions.

Quick migration:
```python
# OLD (deprecated)
from ipfs_datasets_py.data_transformation.ipld import IPLDStorage

# NEW (recommended)
from ipfs_datasets_py.processors.storage.ipld import IPLDStorage
```

---

## [0.2.0] - Previous Release

See git history for previous changes.
