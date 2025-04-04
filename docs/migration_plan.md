# Migration Plan: Moving from old ipfs_kit to ipfs_kit_py

## Overview
This document outlines the plan for migrating from the current `ipfs_kit` implementation to the new `ipfs_kit_py` package. The new package provides more robust functionality, improved architecture, role-based operation, and enhanced features like tiered caching, cluster management, and AI/ML integration.

## Current Usage Analysis
Based on analysis of the codebase, the `ipfs_kit` is currently used in:
1. `/home/barberb/ipfs_datasets_py/ipfs_datasets_py/ipfs_faiss_py/ipfs_knn_lib/knn.py`

Current usage patterns:
- Import: `from ipfs_kit import ipfs_kit`
- Initialization: `self.ipfs_kit = ipfs_kit(resources, meta)`
- Primary methods used:
  - `ipfs_upload_object()` - Used to upload JSON objects to IPFS

## Key Differences Between Old and New Implementations

### Architecture
- **Old ipfs_kit**: Simpler implementation with basic IPFS operations
- **New ipfs_kit_py**: Comprehensive architecture with role-based operation (master/worker/leecher), tiered caching, and advanced features

### API Changes
- **Old ipfs_kit**: Direct method calls with result dictionaries
- **New ipfs_kit_py**: Multiple API options:
  - Core API (similar to old ipfs_kit but more consistent)
  - High-Level API (`IPFSSimpleAPI` with simplified interface)
  - Command-line interface
  - HTTP API server

### Method Names and Parameters
- **Old ipfs_kit**:
  - `ipfs_upload_object(object_data, **kwargs)`
- **New ipfs_kit_py**:
  - Core API: `ipfs_add(filepath_or_data)`
  - High-Level API: `add(filepath_or_data)`

### Result Format
- **Old ipfs_kit**: Custom result dictionaries
- **New ipfs_kit_py**: Standardized result format with consistent fields

## Migration Steps

### 1. Install the New Package
```bash
pip install ipfs_kit_py
```

### 2. Update Import Statements
```python
# Old
from ipfs_kit import ipfs_kit

# New - Core API (closest to old API)
from ipfs_kit_py.ipfs_kit import ipfs_kit

# New - High-Level API (recommended)
from ipfs_kit_py.high_level_api import IPFSSimpleAPI
```

### 3. Update Initialization
```python
# Old
old_ipfs = ipfs_kit(resources, meta)

# New - Core API (similar initialization)
new_ipfs = ipfs_kit(role="leecher", metadata=meta)

# New - High-Level API (recommended)
api = IPFSSimpleAPI(role="leecher")
```

### 4. Method Migration Example for knn.py

```python
# Old
vector_store_cid = self.ipfs_kit.ipfs_upload_object(json.dumps(vector_store), **kwargs)

# New - Core API approach
vector_store_cid = self.ipfs_kit.ipfs_add(json.dumps(vector_store))
if vector_store_cid.get("success"):
    cid = vector_store_cid.get("Hash")

# New - High-Level API approach (recommended)
cid = self.api.add(json.dumps(vector_store))
```

### 5. Specific Changes for knn.py

```python
# Initialize the module
from ipfs_kit_py.high_level_api import IPFSSimpleAPI

class KNN:
    # ...existing code...
    
    def __init__(self, resources, meta):
        # ...existing code...
        
        # Old
        # self.ipfs_kit = ipfs_kit(resources, meta)
        
        # New
        self.api = IPFSSimpleAPI(metadata=meta)
        
        # ...existing code...
    
    # ...
    
    def save_database(self, dest, bucket, dir, documentdb, **kwargs):
        # ...existing code...
        
        # Old
        # vector_store_cid = self.ipfs_kit.ipfs_upload_object(json.dumps(vector_store), **kwargs)
        # vector_index_cid = self.ipfs_kit.ipfs_upload_object(json.dumps(vector_index), **kwargs)
        # doc_index_cid = self.ipfs_kit.ipfs_upload_object(json.dumps(doc_index), **kwargs)
        # doc_store_cid = self.ipfs_kit.ipfs_upload_object(json.dumps(doc_store), **kwargs)
        # metadata_cid = self.ipfs_kit.ipfs_upload_object(json.dumps(metadata_json), **kwargs)
        
        # New
        vector_store_cid = self.api.add(json.dumps(vector_store))
        vector_index_cid = self.api.add(json.dumps(vector_index))
        doc_index_cid = self.api.add(json.dumps(doc_index))
        doc_store_cid = self.api.add(json.dumps(doc_store))
        metadata_cid = self.api.add(json.dumps(metadata_json))
        
        # ...existing code...
```

## Benefits of Migration

1. **Enhanced Functionality**: Access to tiered caching, cluster management, metadata indexing
2. **Improved Performance**: Optimized operations with memory-mapped structures 
3. **Robustness**: Better error handling and recovery mechanisms
4. **Scalability**: Role-based architecture for distributed operations
5. **Future-proofing**: Ongoing development and maintenance of the new package

## Testing Recommendations

1. **Parallel Implementation**: Initially, maintain both old and new implementations in parallel:
   ```python
   try:
       # Try new implementation
       from ipfs_kit_py.high_level_api import IPFSSimpleAPI
       api = IPFSSimpleAPI(metadata=meta)
       cid = api.add(json.dumps(data))
   except Exception as e:
       # Fall back to old implementation
       from ipfs_kit import ipfs_kit
       old_ipfs = ipfs_kit(resources, meta)
       cid = old_ipfs.ipfs_upload_object(json.dumps(data))
   ```

2. **Validate Results**: For each operation, compare the results from old and new implementations
3. **Incremental Migration**: Migrate one component at a time, thoroughly testing each

## Timeline

1. **Preparation (1 day)**
   - Install new package
   - Update import statements
   - Create test harness for validation

2. **Implementation (1 day)**
   - Update initialization code
   - Migrate method calls
   - Add error handling

3. **Testing (1-2 days)**
   - Validate results against old implementation
   - Check for edge cases
   - Stress test with large files

4. **Cleanup (1 day)**
   - Remove old code and fallbacks
   - Update documentation
   - Commit final changes

## Conclusion

The migration from the old `ipfs_kit` to the new `ipfs_kit_py` package will enhance the functionality and robustness of the IPFS integration in our application. The new package provides a more comprehensive architecture with advanced features like tiered caching, role-based operation, and improved error handling, which will benefit the overall system performance and reliability.