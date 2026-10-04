# Deprecation Schedule

**Last Updated:** 2026-02-16

This document tracks all deprecated features and their planned removal dates.

---

## v3.0.0 Planned Removals

### Multimedia Conversion Systems

**Date Deprecated:** 2026-02-16  
**Removal Target:** v3.0.0 (TBD, estimated 6-12 months)  
**Reason:** Consolidating 3 duplicate conversion systems into 1 unified system  
**Migration Guide:** `docs/FILE_CONVERTER_MIGRATION_GUIDE.md`

#### 1. convert_to_txt_based_on_mime_type

**Module:** `ipfs_datasets_py.processors.multimedia.convert_to_txt_based_on_mime_type`

**Details:**
- **Size:** 103 files, 1.2MB
- **Async:** Uses asyncio (legacy)
- **Complexity:** 8-level deep directory nesting
- **Issues:** 
  - No IPFS support
  - No URL support
  - No archive support
  - Over-engineered architecture

**Replace With:**
```python
from ipfs_datasets_py.processors.file_converter import FileConverter

converter = FileConverter()
result = converter.convert("input.pdf", output_path="output.txt")
```

**Impact Analysis:**
- **Breaking Change:** Yes (in v3.0.0)
- **Current Status:** Deprecated with warnings
- **Backward Compatible Until:** v3.0.0
- **Users Affected:** Anyone importing from this module
- **Migration Effort:** LOW (simple API change)
- **Feature Parity:** 100% (file_converter has all features + more)

---

#### 2. omni_converter_mk2

**Module:** `ipfs_datasets_py.processors.multimedia.omni_converter_mk2`

**Details:**
- **Size:** 342 files, 13MB
- **Async:** Mixed asyncio/anyio
- **Features:** GUI, batch processing, extensive format support
- **Issues:**
  - Very large codebase
  - Not integrated with main system
  - Duplicate functionality

**Replace With:**
```python
from ipfs_datasets_py.processors.file_converter import FileConverter

converter = FileConverter()
result = converter.convert("input.pdf")
```

**Note:** GUI features are being evaluated for extraction to `file_converter/gui/` before removal.

**Impact Analysis:**
- **Breaking Change:** Yes (in v3.0.0)
- **Current Status:** Deprecated with warnings
- **Backward Compatible Until:** v3.0.0
- **Users Affected:** Anyone importing from this module
- **Migration Effort:** LOW-MEDIUM (depends on GUI usage)
- **Feature Parity:** 95% (GUI to be added if needed)

---

### Summary Statistics

| System | Files | Size | Users | Migration Effort |
|--------|-------|------|-------|------------------|
| convert_to_txt | 103 | 1.2MB | Low | LOW |
| omni_mk2 | 342 | 13MB | Medium | LOW-MEDIUM |
| **Total** | **445** | **14.2MB** | - | - |

**Combined Impact:**
- 445 files will be removed
- 14.2MB code reduction
- ~21 asyncio files eliminated (achieving 100% anyio compliance)
- Single source of truth established

---

## Deprecation Process

### Phase 1: Deprecation Announcement (v2.9.x - Current)
- [x] Add `DeprecationWarning` to affected modules
- [x] Create migration guide
- [x] Update documentation
- [x] Announce in CHANGELOG

### Phase 2: Transition Period (v2.9.x → v3.0.0)
- [ ] Monitor usage and feedback
- [ ] Extract needed features (e.g., GUI)
- [ ] Assist users with migration
- [ ] Ensure feature parity

### Phase 3: Final Warning (v3.0.0-beta)
- [ ] Upgrade warnings to `FutureWarning`
- [ ] Final call for feature requests
- [ ] Complete migration guide
- [ ] Announce removal date

### Phase 4: Removal (v3.0.0)
- [ ] Remove deprecated code
- [ ] Update tests
- [ ] Update documentation
- [ ] Release v3.0.0

---

## Timeline Estimate

```
2026-02-16: Deprecation announced (v2.9.x)
    ↓
2026-04-16: 2-month checkpoint (feedback, features)
    ↓
2026-06-16: 4-month checkpoint (migration progress)
    ↓
2026-08-16: 6-month checkpoint (beta preparation)
    ↓
2026-10-16: v3.0.0-beta (final warning)
    ↓
2027-01-16: v3.0.0 (removal - estimated)
```

**Minimum Transition Period:** 6 months  
**Target Transition Period:** 8-12 months  
**Depends On:** User feedback and migration progress

---

## Migration Support

### Resources
- **Migration Guide:** `docs/FILE_CONVERTER_MIGRATION_GUIDE.md`
- **Refactoring Plan:** `PROCESSORS_REFACTORING_PLAN_2026_02_16.md`
- **AnyIO Reference:** `PROCESSORS_ANYIO_QUICK_REFERENCE.md`
- **Examples:** `examples/file_converter/`

### Get Help
- **GitHub Issues:** Use tag `migration:file-converter`
- **Discussions:** Ask questions in GitHub Discussions
- **Email:** (if available)

### Report Issues
If you find:
- Missing features in `file_converter`
- Migration blockers
- Bugs in new system

Please open a GitHub issue immediately. We'll prioritize fixing before v3.0.0.

---

## Feature Extraction Plan

Before removing deprecated systems, we'll extract any unique features:

### From convert_to_txt_based_on_mime_type
- [x] MIME detection (already better in file_converter)
- [x] Format support (already in file_converter)
- [ ] Any unique extractors (TBD - unlikely)

### From omni_converter_mk2
- [ ] **GUI Interface** (priority - evaluate if needed)
- [x] Batch processing (already in file_converter)
- [x] Format detection (already in file_converter)
- [x] Content extraction (already in file_converter)

**Status:** No unique features identified yet. GUI is under evaluation.

---

## Rollback Plan

If critical issues arise:

1. **Before v3.0.0:** Deprecated systems still work, users can stay on v2.x
2. **After v3.0.0:** Users must stay on v2.x until issues resolved
3. **Emergency:** We can restore code if absolutely necessary

**Best Practice:** Test migration in development environment before production.

---

## Version Compatibility

| Version | convert_to_txt | omni_mk2 | file_converter | Status |
|---------|----------------|----------|----------------|--------|
| v2.8.x | ✅ Works | ✅ Works | ✅ Works | Before deprecation |
| v2.9.x | ⚠️ Deprecated | ⚠️ Deprecated | ✅ Recommended | Current |
| v3.0.0 | ❌ Removed | ❌ Removed | ✅ Only option | Future |

---

## Questions?

**Q: Can deprecation be extended?**  
A: Yes, if users need more time, we can delay v3.0.0.

**Q: Can I keep using old systems?**  
A: Yes, by staying on v2.x releases. But you won't get new features/fixes.

**Q: Will there be a v3 migration tool?**  
A: If needed, we can create an automated refactoring script.

---

**Maintained By:** Development Team  
**Last Review:** 2026-02-16  
**Next Review:** 2026-04-16 (2-month checkpoint)
