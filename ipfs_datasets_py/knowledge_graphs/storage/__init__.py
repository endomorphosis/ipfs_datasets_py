"""
IPLD Storage Backend Module

This module provides the storage layer for the IPFS graph database,
using IPLD (InterPlanetary Linked Data) for content-addressed graph storage.

Key Features:
- Content-addressed storage with CIDs
- Integration with ipfs_backend_router (Kubo + ipfs_kit_py compatibility)
- CAR file import/export for data portability
- Local caching for performance
- Batch operations for efficiency
- Automatic chunking for large graphs

Backend Compatibility:
This module uses ipfs_backend_router to support multiple IPFS backends:
- Kubo (default): Native IPFS daemon via CLI
- ipfs_kit_py: Python-native IPFS implementation
- ipfs_accelerate_py: Performance-optimized backend

Environment Variables:
- IPFS_DATASETS_PY_IPFS_BACKEND: Force specific backend (e.g., "accelerate")
- IPFS_DATASETS_PY_ENABLE_IPFS_KIT: Enable ipfs_kit_py backend
- IPFS_DATASETS_PY_ENABLE_IPFS_ACCELERATE: Enable acceleration

Components:
- IPLDBackend: Main storage interface using ipfs_backend_router
- CacheLayer: LRU cache for frequently accessed CIDs
- BatchProcessor: Bulk operations for efficiency
- CAROperations: Import/export CAR files

Usage:
    from ipfs_datasets_py.knowledge_graphs.storage import IPLDBackend
    from ipfs_datasets_py.router_deps import RouterDeps
    
    # Create storage backend with router deps
    deps = RouterDeps()
    storage = IPLDBackend(deps=deps)
    
    # Store data (uses ipfs_backend_router automatically)
    cid = storage.store(data_bytes, pin=True)
    
    # Retrieve data
    data = storage.retrieve(cid)
    
    # Export to CAR file
    storage.export_to_car(root_cid, "graph.car")

Integration Pattern:
    All IPFS operations go through ipfs_backend_router for compatibility:
    
    from ipfs_datasets_py.ipfs_backend_router import get_ipfs_backend
    
    class IPLDBackend:
        def __init__(self, deps: RouterDeps = None):
            self.deps = deps or RouterDeps()
            self.backend = get_ipfs_backend(deps=self.deps)
        
        def store(self, data: bytes) -> str:
            return self.backend.add_bytes(data, pin=True)
        
        def retrieve(self, cid: str) -> bytes:
            return self.backend.cat(cid)

Roadmap:
- Phase 1 (Weeks 1-2): Consolidate IPLD storage with router integration
- Phase 4 (Week 7): Enhanced CAR operations for JSON-LD
"""

# Phase 1 implementation (Weeks 1-2)
# from .ipld_backend import IPLDBackend
# from .cache import CacheLayer
# from .car_operations import CAROperations

__all__ = [
    # Phase 1 exports will go here
    # "IPLDBackend",
    # "CacheLayer",
    # "CAROperations",
]

# Version info
__version__ = "0.1.0"
__status__ = "planning"  # Will be "development" in Phase 1
