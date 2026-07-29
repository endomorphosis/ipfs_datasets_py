"""Knowledge graphs package for IPFS Datasets Python.

Stable public API (KGP-017, ``kg-python-client/v1``)::

    from ipfs_datasets_py.knowledge_graphs import (
        Client,
        AsyncClient,
        GraphTarget,
        LifecycleResult,
        QueryResultEnvelope,
        TypedError,
        ServiceError,
        Transaction,
        CLIENT_API_VERSION,
        CONTRACT_VERSION,
    )

    with Client.open(catalog_path) as client:
        client.create(GraphTarget(tenant="acme", graph_id="skills", branch="main"),
                      idempotency_key="create-1")

Prefer these versioned exports for production. Optional backends (spaCy,
transformers, neo4j drivers, ipfs_kit, …) are **not** import-time requirements
of this package root.

Legacy root-level re-exports (GraphDatabase, GraphEngine, …) remain available
via attribute access with :class:`DeprecationWarning` and may be removed in a
future release. See docs/knowledge_graphs/MIGRATION_GUIDE.md.
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
    TransactionAbortedError,
    TransactionConflictError,
    TransactionError,
    TransactionTimeoutError,
    ValidationError,
)

# Stable control-plane + client surface (service has no optional backends).
from .client import (
    CLIENT_API_VERSION,
    AsyncClient,
    Client,
    ClientClosedError,
    ClientConfig,
    ServiceError,
    StreamPage,
    Transaction,
    raise_for_status,
)
from .service import (
    CONTRACT_VERSION,
    QUERY_ENVELOPE_VERSION,
    TYPED_ERROR_CODES,
    GraphService,
    GraphTarget,
    GraphTargetError,
    LifecycleRequest,
    LifecycleResult,
    QueryResultEnvelope,
    TypedError,
)


__all__ = [
    # Version stamps
    "CLIENT_API_VERSION",
    "CONTRACT_VERSION",
    "QUERY_ENVELOPE_VERSION",
    "TYPED_ERROR_CODES",
    # Clients + shared configuration
    "Client",
    "AsyncClient",
    "ClientConfig",
    "Transaction",
    "StreamPage",
    # Targets / results / requests
    "GraphTarget",
    "GraphTargetError",
    "LifecycleRequest",
    "LifecycleResult",
    "QueryResultEnvelope",
    "GraphService",
    # Typed errors
    "TypedError",
    "ServiceError",
    "ClientClosedError",
    "raise_for_status",
    # Exception hierarchy (stable at package root)
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
    "TransactionError",
    "TransactionConflictError",
    "TransactionAbortedError",
    "TransactionTimeoutError",
]


_DEPRECATED_ROOT_EXPORTS: dict[str, tuple[str, str, str]] = {
    # name: (module, attr, preferred_import_path)
    "GraphDatabase": (
        "ipfs_datasets_py.knowledge_graphs.neo4j_compat",
        "GraphDatabase",
        "ipfs_datasets_py.knowledge_graphs.neo4j_compat",
    ),
    "IPFSDriver": (
        "ipfs_datasets_py.knowledge_graphs.neo4j_compat",
        "IPFSDriver",
        "ipfs_datasets_py.knowledge_graphs.neo4j_compat",
    ),
    "IPFSSession": (
        "ipfs_datasets_py.knowledge_graphs.neo4j_compat",
        "IPFSSession",
        "ipfs_datasets_py.knowledge_graphs.neo4j_compat",
    ),
    "GraphEngine": (
        "ipfs_datasets_py.knowledge_graphs.core",
        "GraphEngine",
        "ipfs_datasets_py.knowledge_graphs.core",
    ),
    "QueryExecutor": (
        "ipfs_datasets_py.knowledge_graphs.core",
        "QueryExecutor",
        "ipfs_datasets_py.knowledge_graphs.core",
    ),
    "IPLDBackend": (
        "ipfs_datasets_py.knowledge_graphs.storage",
        "IPLDBackend",
        "ipfs_datasets_py.knowledge_graphs.storage",
    ),
    "LRUCache": (
        "ipfs_datasets_py.knowledge_graphs.storage",
        "LRUCache",
        "ipfs_datasets_py.knowledge_graphs.storage",
    ),
    "Entity": (
        "ipfs_datasets_py.knowledge_graphs.storage",
        "Entity",
        "ipfs_datasets_py.knowledge_graphs.storage",
    ),
    "Relationship": (
        "ipfs_datasets_py.knowledge_graphs.storage",
        "Relationship",
        "ipfs_datasets_py.knowledge_graphs.storage",
    ),
}


def __getattr__(name: str) -> Any:
    """Lazy, deprecated root-level re-exports.

    This keeps existing imports working (e.g. ``from ipfs_datasets_py.knowledge_graphs
    import GraphDatabase``) while discouraging new usage. Optional backends are
    loaded only when a deprecated name is actually accessed.
    """

    if name not in _DEPRECATED_ROOT_EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module_name, attr_name, preferred_import = _DEPRECATED_ROOT_EXPORTS[name]
    warnings.warn(
        f"Importing '{name}' from '{__name__}' is deprecated. "
        f"Prefer: 'from {preferred_import} import {attr_name}'. "
        "For production graphs use Client / AsyncClient + GraphTarget. "
        "See docs/knowledge_graphs/MIGRATION_GUIDE.md for details.",
        DeprecationWarning,
        stacklevel=2,
    )
    module = importlib.import_module(module_name)
    return getattr(module, attr_name)


def __dir__() -> list[str]:
    return sorted(list(globals().keys()) + list(_DEPRECATED_ROOT_EXPORTS.keys()))
