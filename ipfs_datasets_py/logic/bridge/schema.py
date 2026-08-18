"""Packaged JSON Schema for the canonical typed bridge."""

from __future__ import annotations

import json
from importlib import resources
from typing import Any

from ipfs_datasets_py.logic.legal_ir.canonical_contracts import (
    CANONICAL_TYPED_BRIDGE_INTERFACE,
    CANONICAL_TYPED_BRIDGE_SCHEMA_VERSION,
    CanonicalContractError,
)


def typed_bridge_schema_path() -> resources.abc.Traversable:
    """Return the packaged typed-bridge schema resource."""

    return resources.files("ipfs_datasets_py.logic.bridge").joinpath(
        "schemas/canonical_typed_bridge.schema.json"
    )


def load_typed_bridge_schema() -> dict[str, Any]:
    """Load a detached copy of the packaged typed-bridge JSON Schema."""

    with typed_bridge_schema_path().open("r", encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise CanonicalContractError("typed bridge schema must be an object")
    if value.get("x-interface") != CANONICAL_TYPED_BRIDGE_INTERFACE:
        raise CanonicalContractError("typed bridge schema interface changed")
    if value.get("x-schema-version") != CANONICAL_TYPED_BRIDGE_SCHEMA_VERSION:
        raise CanonicalContractError("typed bridge schema version changed")
    return value


__all__ = [
    "load_typed_bridge_schema",
    "typed_bridge_schema_path",
]
