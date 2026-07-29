"""Durable graph catalog with branch-head CAS (KGP-005).

SQLite WAL stores control-plane metadata only:

* tenant/graph lifecycle and uniqueness
* named branches with atomic head compare-and-swap
* immutable revision records
* tombstones, writer leases (fencing epochs), idempotency keys, pin roots

Graph payloads remain owned by storage adapters. Identity and heads are never
authoritative from process-local caches: reopen the same catalog path after
restart to resume.
"""

from __future__ import annotations

from .errors import CATALOG_ERROR_CODES, CatalogError, raise_catalog
from .identity import (
    DEFAULT_BRANCH,
    DEFAULT_GRAPH_KIND,
    DEFAULT_STORAGE_PROFILE,
    STORAGE_PROFILES,
    bootstrap_revision_id,
    request_hash,
)
from .models import (
    BranchRecord,
    GraphDescription,
    GraphRecord,
    IdempotencyRecord,
    LeaseRecord,
    PinRootRecord,
    RevisionRecord,
    TombstoneRecord,
)
from .store import GraphCatalog, open_catalog

__all__ = [
    "CATALOG_ERROR_CODES",
    "CatalogError",
    "raise_catalog",
    "DEFAULT_BRANCH",
    "DEFAULT_GRAPH_KIND",
    "DEFAULT_STORAGE_PROFILE",
    "STORAGE_PROFILES",
    "bootstrap_revision_id",
    "request_hash",
    "BranchRecord",
    "GraphDescription",
    "GraphRecord",
    "IdempotencyRecord",
    "LeaseRecord",
    "PinRootRecord",
    "RevisionRecord",
    "TombstoneRecord",
    "GraphCatalog",
    "open_catalog",
]
