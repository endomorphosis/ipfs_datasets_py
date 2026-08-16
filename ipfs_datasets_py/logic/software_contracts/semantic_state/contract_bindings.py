"""Canonical callable/program contract bindings for the datasets producer.

This module is a datasets-owned metadata surface over the existing bindings
owner.  It does not add operational fields, a new index, or accelerator
control-plane types.
"""

from __future__ import annotations

from ipfs_datasets_py.logic.software_contracts.semantic_state.bindings import (
    BindingsError,
    relevant_binding_projection_for_symbol,
)

__all__ = (
    "BindingsError",
    "relevant_binding_projection_for_symbol",
    "OPERATIONAL_FIELDS_FORBIDDEN",
)

OPERATIONAL_FIELDS_FORBIDDEN = (
    "lease_id",
    "fencing_token",
    "claim_id",
    "duckdb_path",
    "quack_endpoint",
    "attempt_id",
)
