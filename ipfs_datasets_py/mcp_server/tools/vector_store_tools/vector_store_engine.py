"""
Compatibility shim — business logic moved to ipfs_datasets_py.vector_stores.vector_store_engine.

Do not add new code here. Use the canonical package location instead.
Import from ipfs_datasets_py.vector_stores.vector_store_engine for all new code.
"""
# noqa: F401 — re-export all symbols for backward compatibility
from ipfs_datasets_py.vector_stores.vector_store_engine import *  # noqa: F401,F403
