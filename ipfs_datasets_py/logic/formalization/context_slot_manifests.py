"""Extract explicit slot declarations from retrieved, source-bound manifests.

Only the closed structured format below is interpreted. Arbitrary prose stays
unresolved. Manifest declarations are caller premises, not verified source
meaning; retrieval rank never decides between conflicting values.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .context_resolution import AUTHORITY, context_digest, validate_context_bundle

MANIFEST_SCHEMA = "source-bound-context-slot-manifest/v1"
PROPOSAL_SCHEMA = "retrieved-context-slot-proposals/v1"
_SOURCE_SHA = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _require(condition, reason):
    if not condition:
        raise ValueError(reason)


def _guard():
    _require(hashlib.sha256(Path(__file__).read_bytes()).hexdigest() == _SOURCE_SHA,
             "context_manifest_producer_changed_since_import")


def _object(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, "duplicate_manifest_key")
        result[key] = value
    return result


def _decode(text):
    def invalid_constant(value):
        raise ValueError("nonfinite_manifest_value:" + value)
    return json.loads(text, object_pairs_hook=_object, parse_constant=invalid_constant)


def _manifest(value, *, source_ref):
    _require(type(value) is dict and set(value) == {"schema", "selected_source_ref", "scope_note", "slots"},
             "closed_context_manifest_required")
    _require(value["schema"] == MANIFEST_SCHEMA, "context_manifest_schema_required")
    _require(value["selected_source_ref"] == source_ref, "manifest_targets_another_source")
    _require(type(value["scope_note"]) is str and 0 < len(value["scope_note"].encode()) <= 2048,
             "manifest_scope_note_required")
    _require(type(value["slots"]) is list and 0 < len(value["slots"]) <= 32, "bounded_manifest_slots_required")
    seen = set()
    for slot in value["slots"]:
        _require(type(slot) is dict and set(slot) == {"slot_id", "sort", "projection_ids", "value"},
                 "closed_manifest_slot_required")
        _require(type(slot["slot_id"]) is str and 0 < len(slot["slot_id"]) <= 256 and slot["slot_id"] not in seen,
                 "unique_manifest_slot_required")
        seen.add(slot["slot_id"])
        _require(slot["value"] is not None and len(json.dumps(slot["value"], allow_nan=False).encode()) <= 4096,
                 "bounded_manifest_value_required")


def prepare_manifest_binding_proposals(bundle, *, index):
    """Collect exact declarations, preserving missing and conflicting choices.

    Every candidate is parsed at most once across slots. A successful result
    means complete unambiguous *declared* values within the retrieved bundle,
    never complete corpus coverage or legal/app policy truth.
    """
    _guard()
    validate_context_bundle(bundle, index=index)
    parsed, diagnostics = {}, []
    for digest, artifact in sorted(bundle["artifacts"].items()):
        text = artifact["text"]
        # Whole-manifest quotations must fit the binding owner's per-quote cap.
        if len(text.encode()) > 4096:
            diagnostics.append({"artifact_sha256": digest, "reason": "manifest_text_byte_limit"})
            continue
        try:
            value = _decode(text)
        except (ValueError, RecursionError) as exc:
            diagnostics.append({"artifact_sha256": digest, "reason": "not_a_valid_structured_manifest"})
            continue
        if type(value) is not dict or value.get("schema") != MANIFEST_SCHEMA:
            diagnostics.append({"artifact_sha256": digest, "reason": "unrecognized_context_format"})
            continue
        try:
            _manifest(value, source_ref=bundle["selected_source"]["source_ref"])
        except (ValueError, TypeError, RecursionError) as exc:
            diagnostics.append({"artifact_sha256": digest, "reason": str(exc)})
            continue
        parsed[digest] = value
    proposals, missing, conflicts = [], [], []
    for slot in bundle["slots"]:
        choices = {}
        for hit in slot["candidates"]:
            manifest = parsed.get(hit["artifact_sha256"])
            if manifest is None:
                continue
            rows = [row for row in manifest["slots"] if row["slot_id"] == slot["slot_id"]]
            if not rows:
                continue
            row, = rows
            if row["sort"] != slot["sort"] or row["projection_ids"] != slot["projection_ids"]:
                diagnostics.append({"artifact_sha256": hit["artifact_sha256"], "slot_id": slot["slot_id"],
                    "reason": "manifest_slot_sort_or_projection_binding_differs"})
                continue
            key = context_digest(row["value"])
            alternative = choices.setdefault(key, {"value": row["value"], "value_sha256": key,
                "citations": [], "declared_scopes": []})
            artifact = bundle["artifacts"][hit["artifact_sha256"]]
            alternative["citations"].append({"span_id": artifact["span"]["span_id"],
                "start_byte": artifact["span"]["start_byte"], "end_byte": artifact["span"]["end_byte"],
                "quote": artifact["text"]})
            alternative["declared_scopes"].append(manifest["scope_note"])
        if not choices:
            missing.append(slot["slot_id"])
        elif len(choices) > 1:
            conflicts.append({"slot_id": slot["slot_id"], "alternatives": [choices[key] for key in sorted(choices)]})
        else:
            proposals.append({"slot_id": slot["slot_id"], "sort": slot["sort"],
                "projection_ids": slot["projection_ids"], **next(iter(choices.values()))})
    result = {"schema": PROPOSAL_SCHEMA, "bundle_sha256": bundle["bundle_sha256"],
        "index_sha256": bundle["index_sha256"], "selected_source_ref": bundle["selected_source"]["source_ref"],
        "proposals": proposals, "missing_slots": missing, "conflicts": conflicts, "diagnostics": diagnostics,
        "status": "conflict" if conflicts else "incomplete" if missing else "declared_values_available",
        "scope": "exact structured declarations in retrieved candidates; no generic prose interpretation",
        "parsed_manifest_count": len(parsed), "producer_sha256": _SOURCE_SHA,
        "source_resolved_slot_count": 0, "ranking_selects_values": False, **AUTHORITY}
    result["proposal_sha256"] = context_digest(result)
    _guard()
    return result


def bind_manifest_proposals(proposals, *, bundle, index, reviewer_record):
    """Convert replayed unambiguous declarations into cited interpretation inputs.

    The reviewer record is supplied by the caller. This function never creates
    a human review or authenticates that identity. Scope is recorded as the
    manifest author's declaration, not an independently verified relationship.
    """
    from .context_slot_bindings import prepare_context_binding
    expected = prepare_manifest_binding_proposals(bundle, index=index)
    _require(proposals == expected, "context_manifest_proposals_differ_from_replay")
    _require(expected["status"] == "declared_values_available", "complete_unambiguous_manifest_values_required")
    relations = {"temporal_anchor": "deadline_trigger", "temporal_model": "clock_convention",
        "scope": "governing_scope", "confirmation_policy": "application_policy",
        "trace_scope": "application_policy", "referent": "referent", "definition": "defines"}
    bindings = []
    for row in expected["proposals"]:
        bindings.append(prepare_context_binding(bundle, index=index, slot_id=row["slot_id"],
            mode="source_cited_declaration", value=row["value"], citations=row["citations"],
            scope_review={"relation": relations[row["sort"]],
                "governing_scope": "The quoted manifest authors declare applicability to the exact selected SourceRef. Their scope notes remain in the quotations; governing authority is unverified.",
                "alternatives_disposition": "No differing declared value among the retrieved exact-format candidates; corpus completeness unverified."},
            reviewer_record=reviewer_record))
    return tuple(bindings)
