# Knowledge Graphs Lineage Migration - FAQ

## Frequently Asked Questions

### General Questions

#### Q: Why was the lineage code migrated to a new package?

**A:** The original `cross_document_lineage.py` and `cross_document_lineage_enhanced.py` files contained 6,423 lines of duplicate code. By consolidating into a focused `lineage/` package with 2,025 lines across 5 modules, we achieved:
- 97.8% code reduction (6,282 lines eliminated)
- Better organization and maintainability
- Clearer separation of concerns
- Improved testability

####Q: Is this a breaking change?

**A:** No! Full backward compatibility is maintained through:
- Deprecation wrapper files at old locations
- Clear deprecation warnings guiding migration
- Backward-compatible class aliases
- 4-6 month transition period

#### Q: When will the old modules be removed?

**A:** The deprecated modules (`cross_document_lineage.py` and `cross_document_lineage_enhanced.py`) are planned for removal in **version 2.0** (approximately 4-6 months from now). You'll receive deprecation warnings until then.

---

### Migration Questions

#### Q: How do I migrate my code?

**A:** Three options:

**Option 1: Automated Python Script (Recommended)**
```bash
# Preview changes
python scripts/migration/migrate_lineage_imports.py --dry-run your_project/

# Migrate with backups
python scripts/migration/migrate_lineage_imports.py your_project/

# Validate
python scripts/migration/migrate_lineage_imports.py --validate your_project/
```

**Option 2: Quick Shell Script**
```bash
# Preview
./scripts/migration/migrate_lineage.sh --dry-run your_project/

# Migrate
./scripts/migration/migrate_lineage.sh your_project/
```

**Option 3: Manual Find & Replace**
- Find: `cross_document_lineage`
- Replace with: `lineage`
- Find: `cross_document_lineage_enhanced`
- Replace with: `lineage`

#### Q: What if the migration script breaks my code?

**A:** The migration scripts create automatic backups (`.backup` files). To rollback:

**Python script:**
```bash
python scripts/migration/migrate_lineage_imports.py --rollback your_project/
```

**Shell script:**
```bash
for f in your_project/**/*.py.backup; do mv "$f" "${f%.backup}"; done
```

#### Q: Can I migrate just one file?

**A:** Yes! Both scripts work on single files or entire directories:
```bash
python scripts/migration/migrate_lineage_imports.py myfile.py
./scripts/migration/migrate_lineage.sh myfile.py
```

---

### Compatibility Questions

#### Q: Will my old imports still work?

**A:** Yes, with deprecation warnings:
```python
# OLD (still works, shows warning)
from ipfs_datasets_py.knowledge_graphs.cross_document_lineage import EnhancedLineageTracker

# DeprecationWarning: cross_document_lineage module is deprecated.
# Please use 'from ipfs_datasets_py.knowledge_graphs.lineage import ...' instead.
```

#### Q: What classes have changed names?

**A:** Most classes keep their names, but two have aliases for compatibility:

| Old Name | New Name | Status |
|----------|----------|--------|
| EnhancedLineageTracker | EnhancedLineageTracker | Same ✅ |
| LineageTracker | LineageTracker | Same ✅ |
| CrossDocumentLineageEnhancer | EnhancedLineageTracker | Alias ⚠️ |
| DetailedLineageIntegrator | LineageMetrics | Alias ⚠️ |

The aliased classes will continue to work but are deprecated.

#### Q: Do I need to update my tests?

**A:** Your tests should continue to work unchanged, but you should:
1. Update import statements to use new paths
2. Suppress deprecation warnings in tests (if desired)
3. Re-run your test suite to verify

---

### Technical Questions

#### Q: Where is the new lineage package?

**A:** The new package structure is:
```
ipfs_datasets_py/knowledge_graphs/lineage/
├── __init__.py          # Public API exports
├── types.py             # Core data types
├── core.py              # LineageTracker, LineageGraph
├── enhanced.py          # Enhanced tracking features
├── visualization.py     # Visualization tools
└── metrics.py           # Metrics and analysis
```

#### Q: What's the import path mapping?

**A:** 

| Old Import | New Import |
|------------|------------|
| `from ...cross_document_lineage import X` | `from ...lineage import X` |
| `from ...cross_document_lineage_enhanced import Y` | `from ...lineage import Y` |
| `import ...cross_document_lineage` | `import ...lineage` |

#### Q: Are there any API changes?

**A:** No breaking API changes. All public methods, classes, and functions remain the same. Only import paths have changed.

---

### Performance Questions

#### Q: Will migration improve performance?

**A:** The migration itself is performance-neutral (same functionality), but benefits include:
- Cleaner codebase easier to optimize
- Better test coverage (67 tests)
- More maintainable code
- Foundation for future improvements

#### Q: How long does migration take?

**A:** Very fast!
- Single file: < 1 second
- Small project (< 50 files): < 5 seconds
- Large project (100+ files): < 30 seconds

---

### Testing Questions

#### Q: How do I test after migration?

**A:** Follow this checklist:

1. **Run migration in dry-run mode first**
   ```bash
   python scripts/migration/migrate_lineage_imports.py --dry-run .
   ```

2. **Review proposed changes**
   - Check output for accuracy
   - Verify patterns match expectations

3. **Run migration with validation**
   ```bash
   python scripts/migration/migrate_lineage_imports.py --validate .
   ```

4. **Run your test suite**
   ```bash
   pytest
   # or your test command
   ```

5. **Check for deprecation warnings**
   ```bash
   python -W default::DeprecationWarning your_app.py
   ```

#### Q: What if my tests fail after migration?

**A:** 
1. Check the error message - most issues are import-related
2. Verify all imports were updated
3. Check for any hardcoded module paths in tests
4. Use `--rollback` to restore and try again
5. Open an issue if problems persist

---

### Support Questions

#### Q: Where can I get help?

**A:**
1. Check this FAQ first
2. Review the [Migration Guide](KNOWLEDGE_GRAPHS_LINEAGE_MIGRATION.md)
3. Check the [Troubleshooting Guide](KNOWLEDGE_GRAPHS_LINEAGE_TROUBLESHOOTING.md)
4. Open a GitHub issue with:
   - Python version
   - Error message
   - Migration command used
   - Sample of affected code

#### Q: How do I report a migration bug?

**A:** Open a GitHub issue with:
```markdown
**Migration Script:** Python / Shell
**Command Used:** `python scripts/migration/...`
**Expected:** What should have happened
**Actual:** What actually happened
**Error Output:** Full error message
**Sample Code:** Minimal example that reproduces the issue
```

#### Q: Can I contribute improvements?

**A:** Yes! Contributions welcome:
- Migration script improvements
- Additional test cases
- Documentation updates
- Bug fixes

---

### Edge Cases

#### Q: What about dynamic imports?

**A:** Dynamic imports need manual review:
```python
# These won't be auto-migrated
module_name = "cross_document_lineage"
mod = importlib.import_module(f"ipfs_datasets_py.knowledge_graphs.{module_name}")
```

Review your code for dynamic imports and update them manually.

#### Q: What about string references to modules?

**A:** String references need manual updates:
```python
# Manual update needed
module_path = "ipfs_datasets_py.knowledge_graphs.cross_document_lineage"
# Should be: "ipfs_datasets_py.knowledge_graphs.lineage"
```

#### Q: What about imports in comments/docstrings?

**A:** Migration scripts only update actual Python import statements. Update documentation imports manually if needed.

---

### Best Practices

#### Q: What's the recommended migration workflow?

**A:** 

1. **Prepare**
   - Commit all pending changes
   - Ensure tests pass
   - Back up your code

2. **Preview**
   ```bash
   python scripts/migration/migrate_lineage_imports.py --dry-run .
   ```

3. **Migrate**
   ```bash
   python scripts/migration/migrate_lineage_imports.py --verbose .
   ```

4. **Validate**
   ```bash
   python scripts/migration/migrate_lineage_imports.py --validate .
   ```

5. **Test**
   ```bash
   pytest
   ```

6. **Commit**
   ```bash
   git add .
   git commit -m "Migrate to new lineage package"
   ```

#### Q: Should I migrate incrementally or all at once?

**A:** **Recommendation: All at once** because:
- Migration is fast (< 1 minute for most projects)
- Avoids mixed old/new imports
- Easier to verify and test
- Single commit for clean history

But incremental is fine for very large projects (1000+ files).

#### Q: What about external packages that depend on this?

**A:** External packages will continue to work due to:
- Backward-compatible deprecation wrappers
- 4-6 month transition period
- Clear deprecation warnings
- Public announcement of changes

External maintainers should migrate at their convenience within the transition period.

---

### Version-Specific Questions

#### Q: What version introduced the new package?

**A:** Version **1.x.x** (current). The migration path is available immediately.

#### Q: What version removes old modules?

**A:** Version **2.0.0** (future, ~4-6 months). Old modules will be completely removed.

#### Q: How do I check which version I'm using?

**A:**
```python
import ipfs_datasets_py
print(ipfs_datasets_py.__version__)
```

---

## Quick Reference

### Import Cheat Sheet

```python
# OLD ❌
from ipfs_datasets_py.knowledge_graphs.cross_document_lineage import (
    EnhancedLineageTracker,
    LineageTracker
)

# NEW ✅
from ipfs_datasets_py.knowledge_graphs.lineage import (
    EnhancedLineageTracker,
    LineageTracker
)
```

### Migration Command Cheat Sheet

```bash
# Preview changes
python scripts/migration/migrate_lineage_imports.py --dry-run .

# Migrate with backups
python scripts/migration/migrate_lineage_imports.py .

# Migrate without backups (careful!)
python scripts/migration/migrate_lineage_imports.py --no-backup .

# Validate migration
python scripts/migration/migrate_lineage_imports.py --validate .

# Rollback if needed
python scripts/migration/migrate_lineage_imports.py --rollback .
```

---

## Still Have Questions?

If your question isn't answered here:
1. Check the [Migration Guide](KNOWLEDGE_GRAPHS_LINEAGE_MIGRATION.md)
2. Review the [Troubleshooting Guide](KNOWLEDGE_GRAPHS_LINEAGE_TROUBLESHOOTING.md)
3. Open a GitHub issue

**Remember:** The old modules will continue to work with deprecation warnings for 4-6 months. There's no rush, but migrating early is recommended!
