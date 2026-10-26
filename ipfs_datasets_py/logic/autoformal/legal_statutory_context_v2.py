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


# This profile addresses exact decoded plaintext fields. It deliberately has a
# different packet/view/slot domain from the official markup profile above.
PARENT_CONTEXT_PACKET_SCHEMA = "legal-parent-literal-context-obligations/v1"
PARENT_VALIDATION_SCHEMA = "legal-parent-literal-context-obligations-validation/v1"
_PARENT_VIEW_PREFIX = "legal-parent-literal-context-view:sha256:"
_PARENT_PACKET_PREFIX = "legal-parent-literal-context-packet:sha256:"
_PARENT_SLOT_PREFIX = "legal-parent-literal-context-slot:sha256:"
_PARENT_VIEW_ID = re.compile(r"legal-parent-literal-context-view:sha256:[0-9a-f]{64}\Z")
_PARENT_FALSE = dict.fromkeys(
    (*[key for key in _FALSE if key != "raw_html_coordinate_mapping_verified"],
     "source_authenticity_verified", "contributor_completeness_verified",
     "source_region_roles_verified", "governing_body_selected",
     "governing_edition_verified", "semantic_graph_admitted", "Lean_admitted",
     "admitted", "backend_executed", "lean_compilation_verified"), False)
PARENT_AUTHORITY = dict(_PARENT_FALSE)


def parent_context_producer_pins():
    """Pin this operation's source owners without importing a parent decoder.

    The parent corpus owner separately pins and replays its complete original
    intake chain. These hashes guard the context operation before and after that
    replay; they neither authenticate legal meaning nor execute a native owner.
    """
    directory = Path(__file__).resolve().parent
    paths = [directory / name for name in (
        "legal_statutory_context_v2.py", "legal_context_obligations.py",
        "corpus_contracts.py", "corpus_source.py", "legal_semantic_graph.py",
        "corpus_parent_occurrence_adapter.py")]
    paths.append(directory.parent.parent / "utils" / "cid_utils.py")
    return {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


def _parent_inputs(selected_occurrence, expected_selected_occurrence_cid,
                   expected_source_binding_sha256, dependency_requests, identities):
    # Compact public records are checked before importing/replaying parent owners.
    # Original reports and the complete population retain their separate bounds.
    from . import corpus_contracts as contracts, corpus_source as sources

    selection = sources._occurrence_shape(contracts.clone_json(selected_occurrence))
    requests = contracts.clone_json(dependency_requests)
    contracts.require_sha256(expected_source_binding_sha256, "expected_source_binding_sha256")
    for name, value in (*identities, ("expected_selected_occurrence_cid", expected_selected_occurrence_cid)):
        contracts.require_cid(value, name, codecs=("dag-json",))
    _require(selection["record_cid"] == expected_selected_occurrence_cid,
             "selected occurrence differs from independently expected CID")
    _require(not selection["historical_aliases"], "parent selection cannot introduce historical aliases")
    wire(selection)
    wire(requests)
    return selection, requests


def _parent_exact_occurrence(candidate, source):
    """Rebuild the complete record from global character and UTF8 coordinates."""
    from . import corpus_source as sources

    version, whole = source["source_version"], source["selector"]
    arguments = dict(source_version=version,
        expected_raw_sha256=version["raw_artifact"]["sha256"],
        extracted_text=whole["span_text"],
        expected_extracted_sha256=version["extracted_view"]["sha256"])
    checked = sources.validate_source_occurrence(candidate, **arguments)
    expected = sources.build_source_occurrence(**arguments,
        start_char=checked["start_char"], end_char=checked["end_char"],
        start_utf8=checked["start_utf8"], end_utf8=checked["end_utf8"])
    _require(wire(checked) == wire(expected),
             "parent occurrence identity or exact character/UTF8 geometry differs")
    return expected


def _parent_packet(source, selection, requests):
    from . import corpus_contracts as contracts

    version, whole = source["source_version"], source["selector"]
    view = version["extracted_view"]
    identity = {"parent_manifest_cid": source["parent_manifest_cid"],
                "source_binding_sha256": source["source_binding_sha256"]}
    view_id = _PARENT_VIEW_PREFIX + digest(identity)
    # The helper's origin ID is explicitly scoped to the physical companion,
    # complete manifest and independent selected occurrence, not merely its text.
    origin_id = digest({**identity, "selected_occurrence_cid": selection["record_cid"]})
    slots = obligations.build_dependency_slots(
        view_id=view_id, origin_occurrence_id=origin_id, requests=requests,
        view_id_pattern=_PARENT_VIEW_ID,
        validate_selector=lambda candidate: _parent_exact_occurrence(candidate, source),
        require=_require, digest=digest, slot_prefix=_PARENT_SLOT_PREFIX)
    body = {
        "schema": PARENT_CONTEXT_PACKET_SCHEMA,
        "source_view_binding": {
            "view_id": view_id, **identity,
            "root_source_occurrence_cid": whole["record_cid"],
            "companion_record_cid": source["companion_record"]["record_cid"],
            "parent_record_cid": source["parent_record"]["record_cid"],
            "cache_row_record_cid": source["cache_row_record"]["record_cid"]
                if source["cache_row_record"] is not None else None,
            "source_version_cid": version["record_cid"],
            "original_context_cid": source["context"]["record_cid"],
            "document_id": source["document_id"],
            "document_revision": source["document_revision"],
            "edition": source["edition"],
            "raw_sha256": version["raw_artifact"]["sha256"],
            "raw_bytes": len(whole["span_text"].encode("utf-8")),
            "extracted_text_sha256": view["sha256"],
            "extracted_characters": view["character_length"],
            "extracted_utf8_bytes": view["byte_length"],
        },
        "source_version": version,
        # This remains the original ROOT declaration. A derived selection does
        # not silently acquire a resolved context or a rewritten source record.
        "original_context": source["context"],
        "selection": selection,
        "dependency_slots": slots,
        "authority": dict(PARENT_AUTHORITY),
        **_PARENT_FALSE,
    }
    body = contracts.clone_json(body)
    packet = {**body, "packet_id": _PARENT_PACKET_PREFIX + digest(body)}
    return contracts.clone_json(packet)


def build_parent_context_packet_v1(
    parent_bundle, *, expected_manifest_cid, source_occurrence_cid,
    companion_record_cid, report_bytes, expected_report_pins, replay_inputs,
    selected_occurrence, expected_selected_occurrence_cid,
    expected_source_binding_sha256, dependency_requests=None, parent_limits=None,
):
    """Bind six open obligations to a whole/derived literal parent occurrence.

    ``source_occurrence_cid`` identifies a complete original field in the replayed
    population. ``selected_occurrence`` may be its independently pinned derived
    slice. Same-field dependency candidates are exact corpus occurrence records;
    external locators remain locators, and all context obligations remain open.
    No edition, contributor completeness, source role or review is inferred.
    """
    selection, requests = _parent_inputs(selected_occurrence,
        expected_selected_occurrence_cid, expected_source_binding_sha256,
        dependency_requests, (("expected_manifest_cid", expected_manifest_cid),
            ("source_occurrence_cid", source_occurrence_cid),
            ("companion_record_cid", companion_record_cid)))
    _require(producer_pins() == _IMPORTED_OWNER_PINS,
             "parent context owner changed since import")
    pins = parent_context_producer_pins()
    from . import legal_semantic_graph as graphs, corpus_parent_occurrence_adapter as parent
    from . import corpus_source as sources

    # Reuse the existing closed, lower-only bounds; no parallel decoder or
    # recovery path can replace the complete original corpus replay.
    parent._limits(parent_limits)
    source = graphs.bind_parent_source_occurrence(parent_bundle,
        expected_manifest_cid=expected_manifest_cid,
        source_occurrence_cid=source_occurrence_cid,
        companion_record_cid=companion_record_cid, report_bytes=report_bytes,
        expected_report_pins=expected_report_pins, replay_inputs=replay_inputs,
        limits=parent_limits)
    _require(source["source_binding_sha256"] == expected_source_binding_sha256,
             "parent source binding differs from independently expected SHA256")
    version, whole = source["source_version"], source["selector"]
    view = version["extracted_view"]
    _require(whole["start_char"] == whole["start_utf8"] == 0
             and whole["end_char"] == view["character_length"]
             and whole["end_utf8"] == view["byte_length"]
             and whole["span_sha256"] == view["sha256"]
             and whole["span_cid"] == view["cid"],
             "complete exact literal field required; a fragment root is insufficient")
    sources.validate_source_occurrence(whole, source_version=version,
        expected_raw_sha256=version["raw_artifact"]["sha256"],
        extracted_text=whole["span_text"], expected_extracted_sha256=view["sha256"])
    selection = _parent_exact_occurrence(selection, source)
    packet = _parent_packet(source, selection, requests)
    _require(parent_context_producer_pins() == pins
             and producer_pins() == _IMPORTED_OWNER_PINS,
             "parent context operation owner changed during source replay")
    return packet


def validate_parent_context_packet_v1(
    packet, parent_bundle, *, expected_manifest_cid, source_occurrence_cid,
    companion_record_cid, report_bytes, expected_report_pins, replay_inputs,
    selected_occurrence, expected_selected_occurrence_cid,
    expected_source_binding_sha256, dependency_requests=None, parent_limits=None,
):
    """Replay complete originals and compare the independently bound packet.

    This is custody/geometry validation only. It does not make a parent packet a
    subject of the official V2 review domain or satisfy a legal dependency.
    """
    from . import corpus_contracts as contracts

    checked = contracts.clone_json(packet)
    wire(checked)
    expected = build_parent_context_packet_v1(parent_bundle,
        expected_manifest_cid=expected_manifest_cid,
        source_occurrence_cid=source_occurrence_cid,
        companion_record_cid=companion_record_cid, report_bytes=report_bytes,
        expected_report_pins=expected_report_pins, replay_inputs=replay_inputs,
        selected_occurrence=selected_occurrence,
        expected_selected_occurrence_cid=expected_selected_occurrence_cid,
        expected_source_binding_sha256=expected_source_binding_sha256,
        dependency_requests=dependency_requests, parent_limits=parent_limits)
    _require(wire(checked) == wire(expected),
             "parent context packet differs from original source/selection/open obligations")
    return {
        "schema": PARENT_VALIDATION_SCHEMA,
        "packet_id": expected["packet_id"],
        "view_id": expected["source_view_binding"]["view_id"],
        "root_source_occurrence_cid": source_occurrence_cid,
        "selected_occurrence_cid": expected_selected_occurrence_cid,
        "source_geometry_verified": True,
        "open_dependency_slots": len(DEPENDENCY_KINDS),
        "semantic_attachments_verified": False,
        **_PARENT_FALSE,
    }


__all__ += [
    "PARENT_CONTEXT_PACKET_SCHEMA", "PARENT_VALIDATION_SCHEMA", "PARENT_AUTHORITY",
    "parent_context_producer_pins", "build_parent_context_packet_v1",
    "validate_parent_context_packet_v1",
]
