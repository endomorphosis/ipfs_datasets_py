"""Record source-only review declarations without semantic admission.

The pinned blank public packet supplies the complete input boundary. Ordered
human-declared facets and exact scope wording determine mechanical agreement;
no organizer metadata, candidate, reference answer or adjudication is read.
Declared identities and times do not establish that a person reviewed a source
or was independent. Every fit and evaluation mask remains zero.

This bounded dictionary API performs no I/O. File callers must reject duplicate
JSON keys and decode strict UTF8 before constructing dictionaries. The sole
lazy helper dependency is the unchanged richer-review admission owner's
``_annotation`` and ``_meaning_signature`` functions, both purely structural.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from copy import deepcopy

SCHEMA = "canonical-binding-review-recording/v1"
VALIDATION_SCHEMA = "canonical-binding-review-validation/v1"
PACKET_VALIDATION_SCHEMA = "canonical-binding-review-packet-validation/v1"
GUIDE_SCHEMA = "canonical-binding-review-submission-guide/v1"
REVIEWER_SCHEMA = "symbol-binding-source-reviewer/v1"
DIGEST_RECIPE = "sha256_sorted_compact_utf8_json_no_nan_no_newline"
ANNOTATION_HELPER_OWNER = "ipfs_datasets_py.logic.formalization.autoencoder.alignment_richer_review_admission"
ANNOTATION_HELPER_NAMES = ("_annotation", "_meaning_signature")
FACETS = ("modality", "actor", "action", "object", "conditions", "exceptions", "temporal")
ANNOTATION_FIELDS = ("interpretation_status", "ambiguity", "unsupported_meaning", "normative_rules",
                     "freeform_qualifier_scope", "notes", "reviewer_id", "reviewed_at_utc")
INTERPRETATION_STATUSES = ("normative", "no_normative_rule", "ambiguous", "unsupported")
ITEM_STATUSES = ("pending", "single_review", "agreed_multiple_reviews", "disputed", "ambiguous", "unsupported")
MAX_ITEMS = 64
MAX_SUBMISSIONS = 20
MAX_JSON_BYTES = 16 * 1024 * 1024
MAX_JSON_DEPTH = 16
MAX_JSON_NODES = 250000
MAX_SOURCE_BYTES = 65536
MASK_FIELDS = ("weak_decoder_fit", "strong_semantic_fit", "contrastive_supervision",
               "proof_supervision", "fidelity_evaluation")
_PAYLOAD_FIELDS = {"schema", "instructions", "items"}
_ITEM_FIELDS = {"item_id", "source_text", "source_sha256", "input_sha256", "context", "annotation"}
_INSTRUCTION_FIELDS = {"task", "context", "normative_rules", "qualifier_scope", "blank_annotations",
                       "identity", "provenance"}
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_EMPTY_SHA = hashlib.sha256(b"").hexdigest()
_AUTHORITY = {name: False for name in (
    "qualified", "accepted", "production_admitted", "independent_fidelity_available",
    "source_fidelity_established", "source_semantics_verified", "proof_authority",
    "independent_semantic_review_completed", "reviewer_identity_authenticated",
    "reviewer_independence_authenticated", "source_author_independence_authenticated",
    "reviewer_identity_attestations_created", "reviewer_attestations_created",
    "semantic_gold_created", "actual_training_or_evaluation_admission",
)}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _ordinary(value):
    remaining = MAX_JSON_NODES

    def visit(node, depth):
        nonlocal remaining
        remaining -= 1
        _require(remaining >= 0 and depth <= MAX_JSON_DEPTH, "bounded ordinary JSON depth/nodes required")
        kind = type(node)
        if kind is dict:
            _require(all(type(key) is str for key in node), "ordinary JSON string keys required")
            for key, child in node.items():
                visit(key, depth + 1)
                visit(child, depth + 1)
        elif kind is list:
            for child in node:
                visit(child, depth + 1)
        elif kind is float:
            _require(math.isfinite(node), "finite ordinary JSON required")
        else:
            _require(node is None or kind in (str, int, bool), "plain ordinary JSON values required")

    visit(value, 0)


def _raw(value):
    _ordinary(value)
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                             allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, OverflowError, RecursionError, UnicodeError) as error:
        raise ValueError("bounded finite ordinary UTF8 JSON required") from error
    _require(len(encoded) <= MAX_JSON_BYTES, "binding review exceeds JSON byte bound")
    return encoded


def _digest(value):
    return hashlib.sha256(_raw(value)).hexdigest()


def _closed(value, fields, label):
    _require(type(value) is dict and set(value) == set(fields), "closed " + label + " required")


def _text(value, maximum, label):
    _require(type(value) is str and bool(value.strip()) and "\x00" not in value,
             label + " must be nonempty UTF8 text without NUL")
    try:
        count = len(value.encode("utf-8"))
    except UnicodeError as error:
        raise ValueError(label + " must be valid UTF8") from error
    _require(count <= maximum, label + " exceeds UTF8 byte bound")


def _sha(value, label):
    _require(type(value) is str and _SHA.fullmatch(value), label + " must be canonical SHA256")


def _packet(packet, expected_packet_sha256):
    _sha(expected_packet_sha256, "expected_packet_sha256 canonical content pin")
    _closed(packet, _PAYLOAD_FIELDS, "blank source reviewer packet")
    _require(packet["schema"] == REVIEWER_SCHEMA, "symbol-binding source reviewer schema required")
    _require(_digest(packet) == expected_packet_sha256, "blank reviewer packet canonical content SHA mismatch")
    _closed(packet["instructions"], _INSTRUCTION_FIELDS, "reviewer instructions")
    for name, value in packet["instructions"].items():
        _text(value, 4096, "instruction " + name)
    rows = packet["items"]
    _require(type(rows) is list and 1 <= len(rows) <= MAX_ITEMS, "bounded nonempty blank packet items required")
    items, inputs = {}, set()
    for row in rows:
        _closed(row, _ITEM_FIELDS, "blank reviewer item")
        _text(row["source_text"], MAX_SOURCE_BYTES, "source_text")
        _sha(row["source_sha256"], "source_sha256")
        _require(hashlib.sha256(row["source_text"].encode("utf-8")).hexdigest() == row["source_sha256"],
                 "exact source SHA mismatch")
        context = row["context"]
        _closed(context, ("role", "text", "bindings", "sha256"), "source-only context")
        _require(context["role"] == "none_required" and context["text"] == ""
                 and type(context["bindings"]) is dict and context["bindings"] == {}
                 and context["sha256"] == _EMPTY_SHA, "only the exact empty none_required context is supported")
        _sha(row["input_sha256"], "input_sha256")
        _require(_digest({"source_text": row["source_text"], "context": context}) == row["input_sha256"],
                 "exact source/context input SHA mismatch")
        expected_id = "binding-review-item-" + hashlib.sha256(
            b"authored-binding-review-v1\0" + bytes.fromhex(row["input_sha256"])).hexdigest()[:24]
        _require(type(row["item_id"]) is str and row["item_id"] == expected_id, "derived review item ID mismatch")
        _require(row["item_id"] not in items and row["input_sha256"] not in inputs,
                 "unique blank item/input identities required")
        _closed(row["annotation"], ANNOTATION_FIELDS, "blank annotation")
        _require(all(value is None for value in row["annotation"].values()), "prepared annotations must remain blank")
        items[row["item_id"]] = row
        inputs.add(row["input_sha256"])
    return items


def validate_blank_packet(packet: dict, *, expected_packet_sha256: str) -> dict:
    """Validate the pinned blank public packet, without reading organizer data.

    The expected pin hashes canonical content, rather than original file bytes.
    A caller must independently establish that pin; this API does not establish
    source authenticity, reviewer blindness or authored-source independence.
    """
    items = _packet(packet, expected_packet_sha256)
    manifest = [{name: items[identity][name] for name in ("item_id", "source_sha256", "input_sha256")}
                for identity in sorted(items)]
    return {"schema": PACKET_VALIDATION_SCHEMA, "status": "validated_blank_source_only_packet",
            "reviewer_packet_sha256": expected_packet_sha256, "input_manifest_sha256": _digest(manifest),
            "item_count": len(items), "digest_recipe": DIGEST_RECIPE, "input_manifest_order": "item_id_sorted",
            **_AUTHORITY}


def _helpers():
    from ipfs_datasets_py.logic.formalization.autoencoder.alignment_richer_review_admission import (
        _annotation,
        _meaning_signature,
    )

    return _annotation, _meaning_signature


def _payload(payload, packet, items, annotation_validator):
    _closed(payload, _PAYLOAD_FIELDS, "submitted source reviewer payload")
    _raw(payload)
    _require(_raw({name: payload[name] for name in ("schema", "instructions")}) ==
             _raw({name: packet[name] for name in ("schema", "instructions")}), "immutable reviewer metadata changed")
    rows = payload["items"]
    _require(type(rows) is list and 1 <= len(rows) <= MAX_ITEMS, "bounded nonempty submitted items required")
    seen, checked = set(), []
    for row in rows:
        _closed(row, _ITEM_FIELDS, "submitted reviewer item")
        identity = row["item_id"]
        _require(type(identity) is str and identity in items, "unknown submitted item")
        _require(identity not in seen, "duplicate item in review submission")
        seen.add(identity)
        envelope = {name: row[name] for name in _ITEM_FIELDS - {"annotation"}}
        prepared = {name: items[identity][name] for name in _ITEM_FIELDS - {"annotation"}}
        _require(_raw(envelope) == _raw(prepared), "immutable source/context/input envelope changed")
        checked.append((row, annotation_validator(row["annotation"])))
    return checked


def record_reviews(packet: dict, reviewed_payloads: list[dict], *, expected_packet_sha256: str) -> dict:
    """Record submitted declarations and exact agreement; retain every zero mask.

    Complete means that the typed slots are filled, not that a person reviewed
    the source or that its meaning is correct. Different wording or ordering
    can therefore require external adjudication even if a person considers the
    declarations equivalent. No submission is generated by this function.
    """
    packet_validation = validate_blank_packet(packet, expected_packet_sha256=expected_packet_sha256)
    items = {row["item_id"]: row for row in packet["items"]}
    _require(type(reviewed_payloads) is list and len(reviewed_payloads) <= MAX_SUBMISSIONS,
             "bounded review submission list required")
    _raw(reviewed_payloads)
    annotation_validator, meaning_signature = _helpers()
    received = {identity: [] for identity in items}
    submissions, seen_payloads, reviewer_inputs = [], set(), set()
    for index, payload in enumerate(reviewed_payloads):
        checked = _payload(payload, packet, items, annotation_validator)
        payload_sha = _digest(payload)
        _require(payload_sha not in seen_payloads, "duplicate review payload")
        seen_payloads.add(payload_sha)
        declared_ids = set()
        for row, missing in checked:
            annotation, identity = row["annotation"], row["item_id"]
            reviewer = annotation["reviewer_id"]
            if reviewer is not None:
                declaration = (row["input_sha256"], reviewer)
                _require(declaration not in reviewer_inputs, "duplicate declared reviewer for the same input")
                reviewer_inputs.add(declaration)
                declared_ids.add(reviewer)
            complete = not missing
            received[identity].append({"submission_index": index, "submission_sha256": payload_sha,
                "annotation": deepcopy(annotation), "complete": complete, "missing_fields": list(missing),
                "meaning_signature_sha256": meaning_signature(annotation) if complete else None})
        submissions.append({"submission_index": index, "payload_sha256": payload_sha,
            "item_count": len(checked), "declared_reviewer_ids": sorted(declared_ids),
            "identity_authenticated": False, "source_author_independence_authenticated": False,
            "reviewer_attestation_created": False})
    results = []
    for identity in sorted(items):
        complete = [entry for entry in received[identity] if entry["complete"]]
        signatures = {entry["meaning_signature_sha256"] for entry in complete}
        status, consensus = "pending", None
        if complete:
            if len(signatures) != 1:
                status = "disputed"
            else:
                consensus = complete[0]["annotation"]["interpretation_status"]
                status = (consensus if consensus in ("ambiguous", "unsupported") else
                          "agreed_multiple_reviews" if len(complete) >= 2 else "single_review")
        envelope = {name: deepcopy(items[identity][name]) for name in _ITEM_FIELDS - {"annotation"}}
        results.append({**envelope, "review_input_envelope_sha256": _digest(envelope), "status": status,
            "consensus_interpretation_status": consensus, "complete_declaration_count": len(complete),
            "pending_declaration_count": len(received[identity]) - len(complete),
            "meaning_signature_count": len(signatures), "received_declarations": received[identity],
            "external_adjudication_status": "pending", "independent_adjudication_completed": False,
            "masks": {name: 0 for name in MASK_FIELDS}, **_AUTHORITY})
    counts = Counter(row["status"] for row in results)
    interpretations = Counter(row["consensus_interpretation_status"] for row in results
                              if row["consensus_interpretation_status"] is not None)
    completed = sum(row["complete_declaration_count"] for row in results)
    receipt = {"schema": SCHEMA, "status": "submitted_declarations_recorded" if completed else "pending",
        "organizer_private": True, "evaluation_role": "authored_composition_review_readiness_only",
        "reviewer_packet_sha256": expected_packet_sha256,
        "input_manifest_sha256": packet_validation["input_manifest_sha256"], "digest_recipe": DIGEST_RECIPE,
        "annotation_helper_owner": ANNOTATION_HELPER_OWNER, "annotation_helper_names": list(ANNOTATION_HELPER_NAMES),
        "agreement_scope": "exact_complete_declared_meaning_not_semantic_correctness",
        "item_count": len(items), "submission_count": len(submissions), "submissions": submissions, "items": results,
        "status_counts": {name: counts[name] for name in ITEM_STATUSES},
        "interpretation_status_counts": {name: interpretations[name] for name in INTERPRETATION_STATUSES},
        "declared_completed_annotation_count": completed, "human_reviews_authenticated": 0,
        "independent_reviews_authenticated": 0, "masks": {name: 0 for name in MASK_FIELDS},
        "qualified_training_pairs": 0, "candidate_aware_computation": False,
        "authored_reference_scoring_executed": False, "reference_used_to_resolve_disputes": False,
        "automatic_adjudication": False, "training_executed": False, "submissions_created": False,
        "model_calls": 0, "provider_calls": 0, "encoder_calls": 0, "prover_calls": 0,
        "reviewer_identity_evidence": {"status": "unavailable", "authenticated": False},
        "source_author_independence_evidence": {"status": "unavailable", "authenticated": False},
        "reviewer_attestation_evidence": {"status": "unavailable", "authenticated": False},
        "primary_independently_adjudicated_fidelity": {"status": "unavailable", "value": None},
        "native_useful_proof_coverage": {"status": "unrun", "value": None}, **_AUTHORITY}
    receipt["receipt_sha256"] = _digest(receipt)
    _raw(receipt)
    return receipt


def validate_recording(receipt: dict, packet: dict, reviewed_payloads: list[dict], *, expected_packet_sha256: str) -> dict:
    """Replay the complete closed receipt without granting review authority."""
    _require(type(receipt) is dict, "review recording receipt object required")
    supplied = _raw(receipt)
    expected = record_reviews(packet, reviewed_payloads, expected_packet_sha256=expected_packet_sha256)
    _require(supplied == _raw(expected), "review recording differs from exact submission replay")
    return {"schema": VALIDATION_SCHEMA, "status": "validated_declaration_recording_only",
        "receipt_sha256": expected["receipt_sha256"], "reviewer_packet_sha256": expected_packet_sha256,
        "input_manifest_sha256": expected["input_manifest_sha256"], "digest_recipe": DIGEST_RECIPE,
        "item_count": expected["item_count"], "submission_count": expected["submission_count"],
        "status_counts": deepcopy(expected["status_counts"]),
        "declared_completed_annotation_count": expected["declared_completed_annotation_count"],
        "human_reviews_authenticated": 0, "independent_reviews_authenticated": 0,
        "masks": {name: 0 for name in MASK_FIELDS}, "source_meaning_adjudicated": False,
        "automatic_adjudication": False, "training_executed": False, "submissions_created": False,
        "model_calls": 0, "provider_calls": 0, "encoder_calls": 0, "prover_calls": 0, **_AUTHORITY}


def submission_guide() -> dict:
    """Provide the literal declaration contract without answers or identities."""
    return {"schema": GUIDE_SCHEMA, "reviewer_payload_schema": REVIEWER_SCHEMA,
        "submission_format": "Copy the public blank packet, preserve instructions and exact item envelopes, and fill annotation slots only.",
        "allowed_changes": "Fill annotations; optionally submit a nonempty item subset or reorder items. Preserve source, context, hashes and item IDs.",
        "annotation_fields": list(ANNOTATION_FIELDS),
        "interpretation_statuses": {
            "normative": "At least one proposed normative rule, ambiguity=false and unsupported_meaning=false.",
            "no_normative_rule": "Explicit normative_rules=[], both flags false, and nonempty notes explaining the absence of a normative rule.",
            "ambiguous": "ambiguity=true and nonempty notes describing competing interpretations or missing information; proposed rules may be tentative or [].",
            "unsupported": "unsupported_meaning=true and nonempty notes explaining meaning not expressible in the flat facets; proposed rules may be tentative or []."},
        "rule_contract": {"fields": list(FACETS), "modality": "O, P, or F",
            "actor_action": "Nonempty UTF8 strings.", "object": "A UTF8 string; empty string explicitly records no object.",
            "qualifiers": "conditions, exceptions and temporal are lists of nonempty UTF8 strings; order and duplicates are retained.",
            "partial": "Null annotation fields or null whole rule facets remain unanswered. Null qualifier-list members are invalid."},
        "freeform_qualifier_scope": "An explicit string is required for completion. Empty string records no additional scope; normative rules with qualifiers require nonempty scope describing connectives, attachment, binding and timing.",
        "notes": "Optional for normative interpretations; required nonempty rationale for every other interpretation status.",
        "declared_identity": "Only after an actual review, declare a trimmed nonempty reviewer_id and a calendar-valid ISO UTC time using Z or +00:00. Declarations do not authenticate identity or independence.",
        "agreement_recipe": "Compare exact interpretation status, flags, ordered rules and scope. Notes, identity and time do not determine agreement. External adjudication remains pending.",
        "prohibited_hints": "Do not add candidate outputs, authored answers, expectations, split/group metadata, masks, qualification or authentication claims.",
        "packet_pin_scope": "expected_packet_sha256 hashes the complete blank packet's sorted compact UTF8 JSON content, not the original file bytes.",
        "annotation_helper_owner": ANNOTATION_HELPER_OWNER, "annotation_helper_names": list(ANNOTATION_HELPER_NAMES),
        "bounds": {"items_per_payload": MAX_ITEMS, "submissions": MAX_SUBMISSIONS,
            "rules_per_annotation": 32, "qualifiers_per_facet": 128, "atom_utf8_bytes": 4096,
            "scope_notes_utf8_bytes": 16384, "source_utf8_bytes": MAX_SOURCE_BYTES,
            "aggregate_json_bytes": MAX_JSON_BYTES, "json_depth": MAX_JSON_DEPTH},
        "digest_recipe": DIGEST_RECIPE, "generated_reviews": 0, "automatic_adjudication": False,
        "training_executed": False, "submissions_created": False,
        "model_calls": 0, "provider_calls": 0, "encoder_calls": 0, "prover_calls": 0, **_AUTHORITY}


__all__ = ["validate_blank_packet", "record_reviews", "validate_recording", "submission_guide"]
