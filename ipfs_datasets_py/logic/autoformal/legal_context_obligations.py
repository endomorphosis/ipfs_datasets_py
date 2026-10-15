"""Fixed six-kind open dependency obligations shared by source-view owners.

Each owner supplies its own immutable view namespace and exact selector checker.
This helper never resolves a dependency or assigns a semantic attachment.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

DEPENDENCY_KINDS = (
    "definition",
    "authority",
    "antecedent",
    "shared_qualifier",
    "temporal_origin",
    "referenced_provision",
)
_REQUEST_KEYS = {
    "kind",
    "availability",
    "locator",
    "expected_view_id",
    "candidate_selector",
}
_IMPORTED_SOURCE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def build_dependency_slots(
    *,
    view_id,
    origin_occurrence_id,
    requests,
    view_id_pattern,
    validate_selector,
    require,
    digest,
    slot_prefix,
):
    """Retain all fixed obligations and caller content availability as open slots.

    The caller is a source owner, not an incoming request. Selector validation,
    view identity and slot domain must be fixed by that owner's public profile.
    """
    require(
        hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        == _IMPORTED_SOURCE_SHA256,
        "context obligation helper changed since import",
    )
    if requests is None:
        requests = [
            {
                "kind": kind,
                "availability": "missing",
                "locator": None,
                "expected_view_id": None,
                "candidate_selector": None,
            }
            for kind in DEPENDENCY_KINDS
        ]
    require(
        type(requests) is list and len(requests) == len(DEPENDENCY_KINDS),
        "one explicit open obligation for each context dependency kind required",
    )
    by_kind = {}
    for request in requests:
        require(
            type(request) is dict and set(request) == _REQUEST_KEYS,
            "closed context dependency request required",
        )
        kind = request["kind"]
        require(
            type(kind) is str and kind in DEPENDENCY_KINDS and kind not in by_kind,
            "unknown or duplicate context dependency kind",
        )
        require(
            request["availability"] in ("missing", "unavailable", "available"),
            "explicit context content availability required",
        )
        locator, expected_id, candidate = (
            request["locator"],
            request["expected_view_id"],
            request["candidate_selector"],
        )
        require(
            locator is None
            or type(locator) is str
            and 0 < len(locator.encode("utf-8")) <= 4096,
            "bounded context locator or null required",
        )
        require(
            expected_id is None
            or type(expected_id) is str
            and view_id_pattern.fullmatch(expected_id),
            "exact expected normalized view identity or null required",
        )
        stale = expected_id is not None and expected_id != view_id
        if candidate is not None:
            require(
                request["availability"] == "available" and not stale,
                "candidate content cannot be missing, unavailable or stale",
            )
            validate_selector(candidate)
        if stale:
            status = "open_stale"
        elif request["availability"] == "unavailable":
            status = "open_unavailable"
        elif candidate is not None:
            status = "open_content_available"
        elif locator is not None:
            status = "open_locator_only"
        else:
            status = "open_missing"
        slot = {
            **request,
            "status": status,
            "open": True,
            "attachments": [],
            "semantic_attachment_verified": False,
        }
        slot["slot_id"] = slot_prefix + digest(
            {"origin_occurrence_id": origin_occurrence_id, "request": request}
        )
        by_kind[kind] = slot
    return [by_kind[kind] for kind in DEPENDENCY_KINDS]
