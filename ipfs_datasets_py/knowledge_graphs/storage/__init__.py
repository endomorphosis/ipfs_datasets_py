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

Usage:
    from ipfs_datasets_py.knowledge_graphs.storage import IPLDBackend, create_backend
    from ipfs_datasets_py.router_deps import RouterDeps
    
    # Create storage backend with router deps
    deps = RouterDeps()
    storage = IPLDBackend(deps=deps)
    
    # Or use convenience function
    storage = create_backend()
    
    # Store data (uses ipfs_backend_router automatically)
    cid = storage.store({"hello": "world"}, pin=True)
    
    # Retrieve data
    data = storage.retrieve_json(cid)
    
    # Store complete graph
    graph_cid = storage.store_graph(
        nodes=[{"id": "1", "name": "Alice"}],
        relationships=[{"type": "KNOWS", "start": "1", "end": "2"}]
    )
    
    # Export to CAR file
    car_bytes = storage.export_car(graph_cid)

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
- Phase 1 (Weeks 1-2): IPLD storage with router integration ✅
- Phase 4 (Week 7): Enhanced CAR operations for JSON-LD
"""

# Phase 1 implementation complete
from .ipld_backend import IPLDBackend, LRUCache, create_backend
from .types import Entity, Relationship, EntityID, RelationshipID, is_entity, is_relationship

__all__ = [
    "IPLDBackend",
    "LRUCache",
    "create_backend",
    "Entity",
    "Relationship",
    "EntityID",
    "RelationshipID",
    "is_entity",
    "is_relationship",
]

# Version info
__version__ = "0.1.0"
__status__ = "development"  # Phase 1 in progress
