"""Helpers for structured JSON logs.

This module provides a small, stable envelope for structured log payloads so that
downstream parsers can reliably identify and version log schemas.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

DEFAULT_SCHEMA = "ipfs_datasets_py.optimizer_log"
DEFAULT_SCHEMA_VERSION = 1


def with_schema(
    payload: Mapping[str, Any],
    *,
    schema: str = DEFAULT_SCHEMA,
    schema_version: int = DEFAULT_SCHEMA_VERSION,
) -> Dict[str, Any]:
    """Return a dict payload enriched with schema metadata.

    If the payload already contains a ``schema`` or ``schema_version`` key, its
    value is preserved.
    """

    result: Dict[str, Any] = dict(payload)

    result.setdefault("schema", schema)
    result.setdefault("schema_version", schema_version)

    return result
