"""Incremental semantic index refresh (EAAEF-101)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import Any, Final


REFRESH_SCHEMA: Final[str] = (
    "ipfs_datasets_py/analysis/external-agent-incremental-refresh@1"
)
INDEXES: Final[frozenset[str]] = frozenset(
    {"ast", "semantic_state", "capsule", "bm25", "vector", "graph_rag", "kg", "tests", "proofs"}
)


class RefreshError(ValueError):
    """Refresh request is malformed."""


def refresh(*, changed_paths: Sequence[str], indexes: Sequence[str]) -> Mapping[str, Any]:
    unknown = [name for name in indexes if name not in INDEXES]
    if unknown:
        raise RefreshError(f"unknown index {unknown[0]}")
    invalidations = tuple(sorted(set(changed_paths)))
    return MappingProxyType(
        {
            "schema": REFRESH_SCHEMA,
            "indexes": list(indexes),
            "invalidations": list(invalidations),
            "reuse": [name for name in sorted(INDEXES) if name not in set(indexes)],
        }
    )
