"""Federate existing retrieval indexes without a duplicate system (EAAEF-062)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import Any, Final


FEDERATION_SCHEMA: Final[str] = "ipfs_datasets_py/retrieval/agent-work-federation@1"
ENGINES: Final[frozenset[str]] = frozenset(
    {
        "ast",
        "symbol",
        "semantic",
        "capsule",
        "bm25",
        "vector",
        "graph_rag",
        "kg",
        "legal",
        "proof",
        "counterexample",
    }
)


class FederationError(ValueError):
    """Unknown engine or duplicate index system."""


def federate(hits: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    engines = []
    for hit in hits:
        engine = str(hit.get("engine") or "")
        if engine not in ENGINES:
            raise FederationError(f"unknown engine: {engine}")
        if engine == "duplicate_index":
            raise FederationError("duplicate index system is not admitted")
        engines.append(engine)
    return MappingProxyType(
        {
            "schema": FEDERATION_SCHEMA,
            "engines": engines,
            "duplicate_index_system": False,
        }
    )
