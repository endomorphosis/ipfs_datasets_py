"""Open context packets for exact, independently pinned official V2 views.

These packets retain source geometry and explicit content availability only.
Their six obligations are a checklist, not dependency discovery or legal review.
Native, model and network owners are never imported or executed by this module.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from . import legal_context_obligations as obligations
from . import legal_official_document_views as views

CONTEXT_PACKET_SCHEMA = "legal-official-markup-context-obligations/v1"
VALIDATION_SCHEMA = "legal-official-markup-context-obligations-validation/v1"
DEPENDENCY_KINDS = obligations.DEPENDENCY_KINDS
MAX_CONTEXT_PACKET_BYTES = 1024 * 1024
_SLOT_PREFIX = "legal-official-markup-context-slot:sha256:"
_PACKET_PREFIX = "legal-official-markup-context-packet:sha256:"
_VIEW_ID = re.compile(r"legal-official-markup-view:sha256:[0-9a-f]{64}\Z")
_SELECTOR_KEYS = {
    "schema",
    "view_id",
    "document_id",
    "char_start",
    "char_end",
    "utf8_byte_start",
    "utf8_byte_end",
    "text",
    "text_sha256",
    "occurrence_id",
}
_FALSE = dict.fromkeys(
    (
        "dependency_inventory_exhaustive",
        "context_closure_verified",
        "source_semantics_verified",
        "independently_reviewed",
        "training_qualified",
        "proof_authority",
        "semantic_attachments_inferred",
        "raw_html_coordinate_mapping_verified",
    ),
    False,
)
AUTHORITY = dict.fromkeys(
    (*views.AUTHORITY, *_FALSE, "semantic_graph_admitted", "Lean_admitted", "admitted"),
    False,
)


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def wire(value):
    """Canonical finite UTF8 packet bytes under the fixed one-MiB ceiling."""
    try:
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as error:
        raise ValueError("bounded finite UTF8 V2 context JSON required") from error
    _require(
        len(encoded) <= MAX_CONTEXT_PACKET_BYTES,
        "complete V2 context packet byte bound exceeded",
    )
    return encoded


def digest(value):
    return hashlib.sha256(wire(value)).hexdigest()


def producer_pins():
    """Identify the source-view, decoding and fixed-obligation code dependencies."""
    return {
        str(path): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (
            Path(__file__).resolve(),
            Path(obligations.__file__).resolve(),
            Path(views.__file__).resolve(),
            Path(views.custody.__file__).resolve(),
            Path(views.contexts.__file__).resolve(),
        )
    }


_IMPORTED_OWNER_PINS = producer_pins()


def _checked_view(view_report, raw_html, expected_report_sha256, trusted_inputs):
    _require(
        producer_pins() == _IMPORTED_OWNER_PINS, "V2 context owner changed since import"
    )
    checked = views.validate_official_document_view(
        view_report,
        raw_html,
        expected_report_sha256=expected_report_sha256,
        **trusted_inputs,
    )
    _require(
        checked.get("status") == "comparison_view_extracted",
        "complete extracted V2 view required",
    )
    return checked


def _exact_selector(selector, checked):
    _require(
        type(selector) is dict and set(selector) == _SELECTOR_KEYS,
        "closed exact V2 source selector required",
    )
    expected = views._selector(checked, selector["char_start"], selector["char_end"])
    _require(
        wire(selector) == wire(expected),
        "V2 selector identity or character/UTF8 geometry differs",
    )
    return expected


def source_selector_v2(
    view_report,
    raw_html,
    *,
    char_start,
    char_end,
    expected_report_sha256,
    **trusted_inputs,
):
    """Replay the V2 view and select one exact normalized-text occurrence."""
    checked = _checked_view(
        view_report, raw_html, expected_report_sha256, trusted_inputs
    )
    return json.loads(wire(views._selector(checked, char_start, char_end)))


def _build_packet(
    checked, raw_html, selection, dependency_requests, expected_report_sha256
):
    # Copy before slot creation so neither source requests nor selectors alias the result.
    requests = json.loads(wire(dependency_requests))
    slots = obligations.build_dependency_slots(
        view_id=checked["normalized_view"]["view_id"],
        origin_occurrence_id=selection["occurrence_id"],
        requests=requests,
        view_id_pattern=_VIEW_ID,
        validate_selector=lambda candidate: _exact_selector(candidate, checked),
        require=_require,
        digest=digest,
        slot_prefix=_SLOT_PREFIX,
    )
    doc, view, descriptor = (
        checked["document"],
        checked["normalized_view"],
        checked["descriptor"],
    )
    body = {
        "schema": CONTEXT_PACKET_SCHEMA,
        "source_view_binding": {
            "view_report_sha256": expected_report_sha256,
            "descriptor_sha256": checked["descriptor_sha256"],
            "raw_sha256": checked["raw_sha256"],
            "raw_bytes": len(raw_html),
            "document_id": doc["document_id"],
            "document_text_sha256": doc["document_text_sha256"],
            "normalized_view_id": view["view_id"],
            "normalization_profile": view["normalization_profile"],
            "legal_id": descriptor["legal_id"],
            "edition": descriptor["edition"],
        },
        "selection": selection,
        "dependency_slots": slots,
        "authority": dict(AUTHORITY),
        **_FALSE,
    }
    body = json.loads(wire(body))
    packet = {**body, "packet_id": _PACKET_PREFIX + digest(body)}
    return json.loads(wire(packet))


def build_context_packet_v2(
    view_report,
    raw_html,
    *,
    char_start,
    char_end,
    expected_report_sha256,
    dependency_requests=None,
    **trusted_inputs,
):
    """Retain six open obligations; same-view content remains unreviewed.

    A different expected view marks stale local custody. External locators are
    only locators and do not supply external content or legal applicability.
    """
    wire(dependency_requests)
    checked = _checked_view(
        view_report, raw_html, expected_report_sha256, trusted_inputs
    )
    selection = views._selector(checked, char_start, char_end)
    return _build_packet(
        checked, raw_html, selection, dependency_requests, expected_report_sha256
    )


def validate_context_packet_v2(
    packet,
    view_report,
    raw_html,
    *,
    expected_selector,
    expected_report_sha256,
    dependency_requests=None,
    **trusted_inputs,
):
    """Replay original source and the separately supplied exact selection/requests."""
    wire(packet)
    wire(dependency_requests)
    wire(expected_selector)
    checked = _checked_view(
        view_report, raw_html, expected_report_sha256, trusted_inputs
    )
    selection = _exact_selector(expected_selector, checked)
    expected = _build_packet(
        checked, raw_html, selection, dependency_requests, expected_report_sha256
    )
    _require(
        wire(packet) == wire(expected),
        "V2 context packet differs from original source/selection/open obligations",
    )
    return {
        "schema": VALIDATION_SCHEMA,
        "packet_id": expected["packet_id"],
        "view_id": checked["normalized_view"]["view_id"],
        "selector_occurrence_id": selection["occurrence_id"],
        "source_geometry_verified": True,
        "open_dependency_slots": len(DEPENDENCY_KINDS),
        "context_closure_verified": False,
        "semantic_attachments_verified": False,
        "source_semantics_verified": False,
        "training_qualified": False,
        "proof_authority": False,
    }


__all__ = [
    "CONTEXT_PACKET_SCHEMA",
    "VALIDATION_SCHEMA",
    "DEPENDENCY_KINDS",
    "AUTHORITY",
    "MAX_CONTEXT_PACKET_BYTES",
    "wire",
    "digest",
    "producer_pins",
    "source_selector_v2",
    "build_context_packet_v2",
    "validate_context_packet_v2",
]
