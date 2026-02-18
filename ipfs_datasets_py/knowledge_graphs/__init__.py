"""Knowledge graphs package for IPFS Datasets Python.

Prefer importing from stable subpackages:
    - ipfs_datasets_py.knowledge_graphs.extraction
    - ipfs_datasets_py.knowledge_graphs.query
    - ipfs_datasets_py.knowledge_graphs.cypher
    - ipfs_datasets_py.knowledge_graphs.neo4j_compat
    - ipfs_datasets_py.knowledge_graphs.storage / transactions / migration

⚠️ Root-level re-exports from this package are maintained for backward
compatibility only and may be removed in a future release.

See docs/knowledge_graphs/MIGRATION_GUIDE.md for migration instructions.
"""

from __future__ import annotations

import importlib
import warnings
from typing import Any

from .exceptions import (
    EntityExtractionError,
    EntityNotFoundError,
    ExtractionError,
    KnowledgeGraphError,
    MigrationError,
    QueryError,
    QueryExecutionError,
    QueryParseError,
    RelationshipExtractionError,
    RelationshipNotFoundError,
    ValidationError,
)


__all__ = [
    # Public exceptions are stable at the package root.
    "KnowledgeGraphError",
    "ExtractionError",
    "EntityExtractionError",
    "RelationshipExtractionError",
    "ValidationError",
    "QueryError",
    "QueryParseError",
    "QueryExecutionError",
    "MigrationError",
    "EntityNotFoundError",
    "RelationshipNotFoundError",
]


_DEPRECATED_ROOT_EXPORTS: dict[str, tuple[str, str, str]] = {
    # name: (module, attr, preferred_import_path)
    "GraphDatabase": ("ipfs_datasets_py.knowledge_graphs.neo4j_compat", "GraphDatabase", "ipfs_datasets_py.knowledge_graphs.neo4j_compat"),
    "IPFSDriver": ("ipfs_datasets_py.knowledge_graphs.neo4j_compat", "IPFSDriver", "ipfs_datasets_py.knowledge_graphs.neo4j_compat"),
    "IPFSSession": ("ipfs_datasets_py.knowledge_graphs.neo4j_compat", "IPFSSession", "ipfs_datasets_py.knowledge_graphs.neo4j_compat"),
    "GraphEngine": ("ipfs_datasets_py.knowledge_graphs.core", "GraphEngine", "ipfs_datasets_py.knowledge_graphs.core"),
    "QueryExecutor": ("ipfs_datasets_py.knowledge_graphs.core", "QueryExecutor", "ipfs_datasets_py.knowledge_graphs.core"),
    "IPLDBackend": ("ipfs_datasets_py.knowledge_graphs.storage", "IPLDBackend", "ipfs_datasets_py.knowledge_graphs.storage"),
    "LRUCache": ("ipfs_datasets_py.knowledge_graphs.storage", "LRUCache", "ipfs_datasets_py.knowledge_graphs.storage"),
    "Entity": ("ipfs_datasets_py.knowledge_graphs.storage", "Entity", "ipfs_datasets_py.knowledge_graphs.storage"),
    "Relationship": ("ipfs_datasets_py.knowledge_graphs.storage", "Relationship", "ipfs_datasets_py.knowledge_graphs.storage"),
}


def __getattr__(name: str) -> Any:
    """Lazy, deprecated root-level re-exports.

    This keeps existing imports working (e.g. `from ipfs_datasets_py.knowledge_graphs
    import GraphDatabase`) while discouraging new usage.
    """

    if name not in _DEPRECATED_ROOT_EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module_name, attr_name, preferred_import = _DEPRECATED_ROOT_EXPORTS[name]
    warnings.warn(
        f"Importing '{name}' from '{__name__}' is deprecated. "
        f"Prefer: 'from {preferred_import} import {attr_name}'. "
        "See docs/knowledge_graphs/MIGRATION_GUIDE.md for details.",
        DeprecationWarning,
        stacklevel=2,
    )
    module = importlib.import_module(module_name)
    return getattr(module, attr_name)


def __dir__() -> list[str]:
    return sorted(list(globals().keys()) + list(_DEPRECATED_ROOT_EXPORTS.keys()))
