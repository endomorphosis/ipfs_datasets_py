"""Reconcile imported history with reconstructed repository truth (EAAEF-023)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final


RECONCILE_SCHEMA: Final[str] = (
    "ipfs_datasets_py/analysis/agent-history-reconciliation@1"
)
CLASSES: Final[frozenset[str]] = frozenset(
    {"present", "missing", "stale", "history_only"}
)


class ReconciliationError(ValueError):
    """History reconciliation input is malformed."""


@dataclass(frozen=True)
class HistoryItem:
    path: str
    referenced_id: str
    reconstructed_id: str = ""
    classification: str = "missing"

    def __post_init__(self) -> None:
        if not str(self.path).strip() or not str(self.referenced_id).strip():
            raise ReconciliationError("path and referenced_id are required")
        if self.classification not in CLASSES:
            raise ReconciliationError(f"unknown classification: {self.classification}")

    def to_dict(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "path": self.path,
                "referenced_id": self.referenced_id,
                "reconstructed_id": self.reconstructed_id,
                "classification": self.classification,
            }
        )


def classify(*, referenced_id: str, reconstructed_id: str, in_export: bool) -> str:
    if reconstructed_id and referenced_id == reconstructed_id:
        return "present"
    if reconstructed_id and referenced_id != reconstructed_id:
        return "stale"
    if in_export and not reconstructed_id:
        return "history_only"
    return "missing"


def reconcile(
    items: Sequence[Mapping[str, Any]],
) -> Mapping[str, Any]:
    compiled = []
    for item in items:
        referenced = str(item.get("referenced_id") or "")
        reconstructed = str(item.get("reconstructed_id") or "")
        classification = classify(
            referenced_id=referenced,
            reconstructed_id=reconstructed,
            in_export=bool(item.get("in_export", True)),
        )
        compiled.append(
            HistoryItem(
                path=str(item.get("path") or ""),
                referenced_id=referenced,
                reconstructed_id=reconstructed,
                classification=classification,
            )
        )
    counts = {name: 0 for name in sorted(CLASSES)}
    for item in compiled:
        counts[item.classification] += 1
    return MappingProxyType(
        {
            "schema": RECONCILE_SCHEMA,
            "items": [dict(item.to_dict()) for item in compiled],
            "counts": counts,
        }
    )
