"""Typed errors for the durable graph catalog (KGP-005).

Codes align with ``docs/architecture/knowledge_graphs_service_contract.md`` §6.2
so GraphService can map catalog failures without inventing new strings.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

# Closed set used by the catalog layer (subset of service contract codes).
CATALOG_ERROR_CODES = frozenset(
    {
        "INVALID_REQUEST",
        "INVALID_TARGET",
        "NOT_FOUND",
        "ALREADY_EXISTS",
        "CONFLICT",
        "FENCED",
        "STORAGE",
        "INTERNAL",
    }
)

# Default retryable posture from the service contract table.
_DEFAULT_RETRYABLE: Mapping[str, bool] = {
    "INVALID_REQUEST": False,
    "INVALID_TARGET": False,
    "NOT_FOUND": False,
    "ALREADY_EXISTS": False,
    "CONFLICT": True,
    "FENCED": False,
    "STORAGE": True,
    "INTERNAL": False,
}


class CatalogError(Exception):
    """Catalog failure with a service-contract-aligned typed code."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: Optional[bool] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        if code not in CATALOG_ERROR_CODES:
            raise ValueError(f"unknown catalog error code: {code!r}")
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = (
            bool(_DEFAULT_RETRYABLE[code]) if retryable is None else bool(retryable)
        )
        self.details: Dict[str, Any] = dict(details or {})

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
            "details": dict(self.details),
        }

    def __str__(self) -> str:
        if self.details:
            return f"{self.code}: {self.message} {self.details}"
        return f"{self.code}: {self.message}"


def raise_catalog(
    code: str,
    message: str,
    *,
    retryable: Optional[bool] = None,
    details: Optional[Dict[str, Any]] = None,
) -> None:
    """Raise :class:`CatalogError` (never returns)."""
    raise CatalogError(code, message, retryable=retryable, details=details)


__all__ = [
    "CATALOG_ERROR_CODES",
    "CatalogError",
    "raise_catalog",
]
