"""Datasets-owned v0.1 semantic-outcome comparison (PCCE-012)."""

from __future__ import annotations

from typing import Any, Mapping

from ipfs_datasets_py.proof_context.context_pack import ContextPackRecord
from ipfs_datasets_py.proof_context.contracts import (
    InsufficientContextError,
    StaleContextError,
    UnavailableContextError,
)

INTERFACE = "DatasetsSemanticOutcome@0.1"


class SemanticOutcomeError(RuntimeError):
    reason = "invalid"


def compare_context_packs(
    left: ContextPackRecord | Mapping[str, Any],
    right: ContextPackRecord | Mapping[str, Any],
) -> dict[str, Any]:
    """Compare two datasets-owned packs. Simulated/stale never equal live success."""

    left_id = _identity(left)
    right_id = _identity(right)
    if left_id.get("freshness") == "stale" or right_id.get("freshness") == "stale":
        raise StaleContextError("stale packs cannot compare as live success")
    if left_id.get("unavailable") or right_id.get("unavailable"):
        raise UnavailableContextError("unavailable packs cannot compare as success")
    if left_id.get("provenance") == "simulated" or right_id.get("provenance") == "simulated":
        raise SemanticOutcomeError("simulated semantic outcomes cannot be promoted")
    equal = left_id.get("pack_cid") == right_id.get("pack_cid") and left_id.get(
        "pack_cid"
    )
    return {
        "schema": INTERFACE,
        "equal": bool(equal),
        "left_pack_cid": left_id.get("pack_cid"),
        "right_pack_cid": right_id.get("pack_cid"),
        "producer": "ipfs_datasets_py.proof_context.semantic_outcome",
    }


def require_sufficient(record: ContextPackRecord) -> None:
    if record.expansion_required:
        raise InsufficientContextError(
            "expansion-required packs are not a successful semantic outcome"
        )


def _identity(value: ContextPackRecord | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(value, ContextPackRecord):
        payload = value.identity_payload()
        payload["freshness"] = "fresh"
        payload["unavailable"] = False
        payload["provenance"] = "live"
        return payload
    return dict(value)
