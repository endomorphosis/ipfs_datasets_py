# Quick Migration Guide: data_transformation → processors

**Quick Reference for Migrating from data_transformation/ to processors/**

---

## TL;DR

The `data_transformation/` directory is being deprecated and merged into `processors/` for better organization. All old import paths will continue to work with deprecation warnings until v2.0.0 (August 2026).

---

## Import Path Changes

### IPLD Storage & Knowledge Graphs

```python
# ❌ OLD (deprecated)
from ipfs_datasets_py.data_transformation.ipld import IPLDStorage
from ipfs_datasets_py.data_transformation.ipld import KnowledgeGraph
from ipfs_datasets_py.data_transformation.ipld import VectorStore
from ipfs_datasets_py.data_transformation.ipld import DAGPBCodec

# ✅ NEW (use this)
from ipfs_datasets_py.processors.storage.ipld import IPLDStorage
from ipfs_datasets_py.processors.storage.ipld import KnowledgeGraph
from ipfs_datasets_py.processors.storage.ipld import VectorStore
from ipfs_datasets_py.processors.storage.ipld import DAGPBCodec
```

### Serialization

```python
# ❌ OLD (deprecated)
from ipfs_datasets_py.data_transformation.serialization import DatasetSerializer
from ipfs_datasets_py.data_transformation.serialization import DataInterchangeUtils
from ipfs_datasets_py.data_transformation.car_conversion import convert_to_car
from ipfs_datasets_py.data_transformation.jsonl_to_parquet import convert_jsonl
from ipfs_datasets_py.data_transformation.dataset_serialization import serialize_dataset

# ✅ NEW (use this)
from ipfs_datasets_py.processors.serialization import DatasetSerializer
from ipfs_datasets_py.processors.serialization import DataInterchangeUtils
from ipfs_datasets_py.processors.serialization import convert_to_car
from ipfs_datasets_py.processors.serialization import convert_jsonl
from ipfs_datasets_py.processors.serialization import serialize_dataset
```

### IPFS Formats & UnixFS

```python
# ❌ OLD (deprecated)
from ipfs_datasets_py.data_transformation.ipfs_formats import get_cid
from ipfs_datasets_py.data_transformation.ipfs_formats.ipfs_multiformats import get_cid
from ipfs_datasets_py.data_transformation.unixfs import UnixFS

# ✅ NEW (use this)
from ipfs_datasets_py.processors.ipfs.formats import get_cid
from ipfs_datasets_py.processors.ipfs.formats.multiformats import get_cid
from ipfs_datasets_py.processors.ipfs import UnixFS
```

### Authentication (UCAN)

```python
# ❌ OLD (deprecated)
from ipfs_datasets_py.data_transformation.ucan import UCAN

# ✅ NEW (use this)
from ipfs_datasets_py.processors.auth.ucan import UCAN
```

### Multimedia (Already Migrated)

```python
# ❌ OLD (deprecated)
from ipfs_datasets_py.data_transformation.multimedia import FFmpegWrapper
from ipfs_datasets_py.data_transformation.multimedia import YtDlpWrapper
from ipfs_datasets_py.data_transformation.multimedia import MediaProcessor

# ✅ NEW (use this)
from ipfs_datasets_py.processors.multimedia import FFmpegWrapper
from ipfs_datasets_py.processors.multimedia import YtDlpWrapper
from ipfs_datasets_py.processors.multimedia import MediaProcessor
```

---

## Migration Steps

### Step 1: Update Your Imports

Find and replace old import paths with new ones:

```bash
# Example sed command (review before running!)
find . -name "*.py" -exec sed -i 's/from ipfs_datasets_py.data_transformation.ipld/from ipfs_datasets_py.processors.storage.ipld/g' {} +
find . -name "*.py" -exec sed -i 's/from ipfs_datasets_py.data_transformation.serialization/from ipfs_datasets_py.processors.serialization/g' {} +
```

### Step 2: Test Your Code

```bash
# Run your tests
pytest

# Check for deprecation warnings
python -W default your_script.py
```

### Step 3: Remove Deprecation Warnings

Once you've updated all imports, you should no longer see deprecation warnings.

---

## Timeline

- **Now - August 2026**: Both old and new import paths work
- **August 2026 (v2.0.0)**: Old import paths removed

You have **6 months** to migrate your code.

---

## Common Issues

### Issue: "ImportError: cannot import name 'X'"

**Solution**: You may be importing from a deprecated path. Update to the new path.

### Issue: "DeprecationWarning: Importing from 'data_transformation' is deprecated"

**Solution**: This is expected. Update your imports to the new paths to remove the warning.

### Issue: Circular import errors

**Solution**: Ensure you're using the new import paths consistently throughout your codebase.

---

## Need Help?

- **Full Migration Guide**: See `docs/PROCESSORS_DATA_TRANSFORMATION_MIGRATION_GUIDE_V2.md`
- **Architecture Documentation**: See `docs/PROCESSORS_DATA_TRANSFORMATION_ARCHITECTURE.md`
- **Integration Plan**: See `docs/PROCESSORS_DATA_TRANSFORMATION_INTEGRATION_PLAN_V2.md`

---

## Quick Checklist

- [ ] Find all imports from `data_transformation.ipld`
- [ ] Update to `processors.storage.ipld`
- [ ] Find all imports from `data_transformation.serialization`
- [ ] Update to `processors.serialization`
- [ ] Find all imports from `data_transformation.ipfs_formats`
- [ ] Update to `processors.ipfs.formats`
- [ ] Find all imports from `data_transformation.ucan`
- [ ] Update to `processors.auth.ucan`
- [ ] Find all imports from `data_transformation.multimedia`
- [ ] Update to `processors.multimedia`
- [ ] Run tests to verify everything works
- [ ] Check for deprecation warnings
- [ ] Update documentation if needed

---

**Last Updated:** 2026-02-15  
**Deprecation Date:** August 2026 (v2.0.0)
