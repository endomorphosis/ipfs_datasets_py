# Complete Migration Guide: data_transformation → processors

**Version:** 2.0.0 Migration  
**Effective Date:** February 2026  
**Deprecation Date:** August 2026  
**Audience:** All IPFS Datasets Python users

---

## 🎯 Quick Start

**What's Changing:**
The `data_transformation/` directory is being consolidated into `processors/` for better organization.

**Action Required:**
Update your imports before August 2026. Your old imports will work with warnings until then.

**Time to Complete:** 5-10 minutes for most projects

---

## 📋 Migration Checklist

### Step 1: Assess Your Usage

Run this command to find all data_transformation imports in your code:

```bash
grep -r "from ipfs_datasets_py.data_transformation" . --include="*.py"
```

### Step 2: Update Imports

Use this table to update your imports:

| Old Path | New Path |
|----------|----------|
| `data_transformation.ipld` | `processors.storage.ipld` |
| `data_transformation.serialization` | `processors.serialization` |
| `data_transformation.ipfs_formats` | `processors.ipfs.formats` |
| `data_transformation.unixfs` | `processors.ipfs` (unixfs) |
| `data_transformation.ucan` | `processors.auth.ucan` |

### Step 3: Test Your Code

```bash
# Run with deprecation warnings visible
python -W default your_script.py

# Run tests
pytest
```

### Step 4: Remove Warnings

If you see deprecation warnings, you've successfully updated most imports. Update any remaining ones.

---

## 🔄 Import Path Changes

### IPLD Storage

**What Moved:** All IPLD (InterPlanetary Linked Data) storage functionality

```python
# ❌ OLD (deprecated)
from ipfs_datasets_py.data_transformation.ipld import (
    IPLDStorage,
    IPLDKnowledgeGraph,
    IPLDVectorStore,
    create_dag_node,
    parse_dag_node
)

# ✅ NEW (current)
from ipfs_datasets_py.processors.storage.ipld import (
    IPLDStorage,
    IPLDKnowledgeGraph,
    IPLDVectorStore,
    create_dag_node,
    parse_dag_node
)
```

**Use Cases:** IPLD storage, knowledge graphs, vector stores

---

### Serialization

**What Moved:** All data format conversion and serialization

```python
# ❌ OLD (deprecated)
from ipfs_datasets_py.data_transformation.serialization import (
    DatasetSerializer,
    DataInterchangeUtils
)
from ipfs_datasets_py.data_transformation.car_conversion import DataInterchangeUtils
from ipfs_datasets_py.data_transformation.jsonl_to_parquet import convert_jsonl

# ✅ NEW (current)
from ipfs_datasets_py.processors.serialization import (
    DatasetSerializer,
    DataInterchangeUtils,
    convert_jsonl
)
```

**Use Cases:** CAR files, Parquet, JSONL, dataset serialization

---

### IPFS Formats

**What Moved:** IPFS multiformats and UnixFS

```python
# ❌ OLD (deprecated)
from ipfs_datasets_py.data_transformation.ipfs_formats import get_cid
from ipfs_datasets_py.data_transformation.unixfs import UnixFS

# ✅ NEW (current)
from ipfs_datasets_py.processors.ipfs.formats import get_cid
from ipfs_datasets_py.processors.ipfs import UnixFS
```

**Use Cases:** CID generation, multihash, multicodec, UnixFS structures

---

### Authentication

**What Moved:** UCAN authentication tokens

```python
# ❌ OLD (deprecated)
from ipfs_datasets_py.data_transformation.ucan import UCAN

# ✅ NEW (current)
from ipfs_datasets_py.processors.auth.ucan import UCAN
```

**Use Cases:** UCAN token generation, verification, delegation

---

## 📝 Code Examples

### Example 1: PDF Processing with IPLD

**Before:**
```python
from ipfs_datasets_py.data_transformation.ipld import IPLDStorage
from ipfs_datasets_py.processors.pdf_processor import PDFProcessor

storage = IPLDStorage()
processor = PDFProcessor(storage=storage)
result = processor.process("document.pdf")
```

**After:**
```python
from ipfs_datasets_py.processors.storage.ipld import IPLDStorage
from ipfs_datasets_py.processors.pdf_processor import PDFProcessor

storage = IPLDStorage()
processor = PDFProcessor(storage=storage)
result = processor.process("document.pdf")
```

**Change:** One import line

---

### Example 2: Dataset Serialization

**Before:**
```python
from ipfs_datasets_py.data_transformation.serialization import DatasetSerializer

serializer = DatasetSerializer()
car_file = serializer.serialize_to_car(dataset)
```

**After:**
```python
from ipfs_datasets_py.processors.serialization import DatasetSerializer

serializer = DatasetSerializer()
car_file = serializer.serialize_to_car(dataset)
```

**Change:** One import line

---

### Example 3: Knowledge Graph with IPLD

**Before:**
```python
from ipfs_datasets_py.data_transformation.ipld import IPLDKnowledgeGraph

kg = IPLDKnowledgeGraph()
kg.add_entity("Person", {"name": "Alice"})
kg.add_relationship("Alice", "knows", "Bob")
```

**After:**
```python
from ipfs_datasets_py.processors.storage.ipld import IPLDKnowledgeGraph

kg = IPLDKnowledgeGraph()
kg.add_entity("Person", {"name": "Alice"})
kg.add_relationship("Alice", "knows", "Bob")
```

**Change:** One import line

---

## 🔍 Finding and Replacing

### Automated Migration

Use these sed commands (review before running!):

```bash
# IPLD Storage
find . -name "*.py" -exec sed -i 's/from ipfs_datasets_py\.data_transformation\.ipld/from ipfs_datasets_py.processors.storage.ipld/g' {} +

# Serialization
find . -name "*.py" -exec sed -i 's/from ipfs_datasets_py\.data_transformation\.serialization/from ipfs_datasets_py.processors.serialization/g' {} +

# IPFS Formats
find . -name "*.py" -exec sed -i 's/from ipfs_datasets_py\.data_transformation\.ipfs_formats/from ipfs_datasets_py.processors.ipfs.formats/g' {} +

# UnixFS
find . -name "*.py" -exec sed -i 's/from ipfs_datasets_py\.data_transformation\.unixfs/from ipfs_datasets_py.processors.ipfs/g' {} +

# UCAN
find . -name "*.py" -exec sed -i 's/from ipfs_datasets_py\.data_transformation\.ucan/from ipfs_datasets_py.processors.auth.ucan/g' {} +
```

### Manual Migration

For Python 3.10+, imports can also be done via IDE refactoring:
1. Find all references to old imports
2. Update to new paths
3. Run tests to verify

---

## ⚠️ Common Issues

### Issue 1: Import Errors After Migration

**Problem:**
```python
ImportError: cannot import name 'IPLDStorage' from 'ipfs_datasets_py.processors.storage.ipld'
```

**Solution:**
Make sure you're using the latest version of ipfs_datasets_py:
```bash
pip install --upgrade ipfs_datasets_py
```

---

### Issue 2: Deprecation Warnings Won't Go Away

**Problem:**
Still seeing warnings after updating imports.

**Solution:**
Check for indirect imports in your dependencies or internal modules. Run:
```bash
python -W error::DeprecationWarning your_script.py
```
This will show exactly where the warnings are coming from.

---

### Issue 3: Circular Import Errors

**Problem:**
Getting circular import errors after migration.

**Solution:**
Ensure you're using the new paths consistently. Don't mix old and new imports.

---

## 📅 Timeline

- **February 2026:** Migration begins, both paths work
- **February-August 2026:** Deprecation warnings issued for old paths
- **August 2026 (v2.0.0):** Old paths removed, only new paths work

**You have 6 months to update your code.**

---

## 🆘 Getting Help

### Documentation
- **Integration Plan:** `docs/PROCESSORS_DATA_TRANSFORMATION_INTEGRATION_PLAN_V2.md`
- **Quick Migration:** `docs/PROCESSORS_DATA_TRANSFORMATION_QUICK_MIGRATION.md`
- **Architecture:** `docs/PROCESSORS_DATA_TRANSFORMATION_ARCHITECTURE.md`

### Migration Summary
- **Summary:** `docs/DATA_TRANSFORMATION_MIGRATION_SUMMARY.md`

### Support
- **GitHub Issues:** Report migration problems as issues
- **Pull Requests:** Submit PRs for documentation improvements

---

## ✅ Verification

### Checklist

After migration, verify:

- [ ] All imports updated to new paths
- [ ] No deprecation warnings when running code
- [ ] All tests pass
- [ ] No import errors
- [ ] Code works as expected

### Test Script

```python
# test_migration.py
"""Test that migration is complete."""

def test_new_imports():
    """Test that new imports work."""
    from ipfs_datasets_py.processors.storage.ipld import IPLDStorage
    from ipfs_datasets_py.processors.serialization import DatasetSerializer
    from ipfs_datasets_py.processors.ipfs.formats import get_cid
    from ipfs_datasets_py.processors.auth.ucan import UCAN
    
    print("✅ All new imports work!")

def test_no_old_imports():
    """Ensure code doesn't use old imports."""
    import warnings
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always", DeprecationWarning)
        
        # Your import statements here
        # If any use old paths, warnings will be recorded
        
        if len(w) > 0:
            print(f"⚠️  Found {len(w)} deprecation warnings")
            for warning in w:
                print(f"   - {warning.message}")
        else:
            print("✅ No deprecated imports found!")

if __name__ == "__main__":
    test_new_imports()
    test_no_old_imports()
```

---

## 📊 Benefits of Migration

### For Users
- ✅ Clearer, more logical organization
- ✅ Easier to find functionality
- ✅ Better IDE auto-completion
- ✅ Consistent with rest of package

### For Developers
- ✅ Reduced code duplication
- ✅ Clearer module responsibilities
- ✅ Easier maintenance
- ✅ Better testing organization

### For the Project
- ✅ More maintainable architecture
- ✅ Easier to extend
- ✅ Better documentation structure
- ✅ Simplified dependencies

---

## 🎓 Best Practices

1. **Update Early:** Don't wait until the deadline
2. **Update All at Once:** Avoid mixing old and new imports
3. **Test Thoroughly:** Run your full test suite after migration
4. **Update Documentation:** Update any internal docs or examples
5. **Share Knowledge:** Help team members migrate their code

---

## 📚 Additional Resources

### Architecture Documentation
- `processors/storage/` - IPLD storage and knowledge graphs
- `processors/serialization/` - Format conversion and serialization
- `processors/ipfs/` - IPFS-specific utilities
- `processors/auth/` - Authentication and authorization

### Related Migrations
- Multimedia migration (already complete)
- Knowledge graphs refactoring (in progress)

---

**Last Updated:** 2026-02-15  
**Version:** 1.0 (v2.0.0 migration)  
**Status:** Active - 6 month migration window
