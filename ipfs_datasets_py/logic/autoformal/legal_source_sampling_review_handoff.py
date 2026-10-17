"""Replay-bound migration of blank source handoffs into blank review drafts.

This adapter preserves custody and unanswered questions. It does not turn the
older preparation packet into a response, authenticate a reviewer, or supply
legal interpretations. Public module import uses only the standard library;
operation owners are fixed, lazy imports and perform their existing pin reads.
"""

from __future__ import annotations

import hashlib
import json
import math
import re

SCHEMA = "legal-source-sampling-review-handoff/v1"
LEGACY_SCHEMA = "legal-v2-actual-source-review-handoff-input/v1"
MAX_HANDOFF_BYTES = 1024 * 1024
MAX_HANDOFF_RECORD_BYTES = 1024 * 1024
LEGACY_QUESTION_IDS = (
    "source_role",
    "authority_edition",
    "scope_applicability",
    "complete_meaning_unit",
    "dependency_inventory",
    "reference_targets",
    "notes_construction",
    "definition_operator",
    "term_and_sense",
    "body_structure",
    "legal_sort_arity",
    "definition_use",
    "formal_profile_fit",
)
ADDED_QUESTION_IDS = ("meaning_statement", "meaning_arguments_qualifiers")
_LEGACY_FIELDS = {
    "schema", "status", "navigation_purpose",
    "sampling_report_full_canonical_sha256", "unit", "source_occurrence",
    "original_context", "v2_context_packet", "responses", "reviewer",
    "exposure_declaration", "meaning_target", "typed_AST",
    "definition_use_bindings", "training_mask", "evaluation_gold_mask", "authority",
}
_DRAFT_FIELDS = {
    "schema", "origin", "bundle_sha256", "question_catalog_ref", "subject_ref",
    "source_version_ref", "source_occurrence_ref", "context_ref",
    "v2_context_packet_ref", "evidence_refs", "response_template",
    "legacy_question_ids", "added_question_ids", "unanswered_question_ids",
    "coordinate_profile", "status", "authority", "training_mask",
    "evaluation_gold_mask", "response_recorded", "review_completed",
    "record_cid", "cid_scope",
}
_SHA = re.compile(r"[0-9a-f]{64}\Z")


def _need(condition, message):
    if not condition:
        raise ValueError(message)


def _keys(value, fields, label):
    _need(type(value) is dict and set(value) == fields, "closed " + label + " fields required")


def _sha(value, label):
    _need(type(value) is str and _SHA.fullmatch(value) is not None,
          "independent lowercase SHA256 required: " + label)


def _wire(value, maximum=MAX_HANDOFF_RECORD_BYTES):
    """Bound ordinary finite JSON before serialization or any operation owner."""
    nodes, remaining = 25_000, maximum

    def visit(item, depth):
        nonlocal nodes, remaining
        nodes -= 1
        _need(nodes >= 0 and depth <= 20, "handoff JSON node/depth bound exceeded")
        if type(item) is dict:
            remaining -= 2 + 2 * len(item)
            for key, child in item.items():
                _need(type(key) is str and "\x00" not in key, "ordinary handoff JSON keys required")
                visit(key, depth + 1)
                visit(child, depth + 1)
        elif type(item) is list:
            remaining -= 2 + len(item)
            for child in item:
                visit(child, depth + 1)
        elif type(item) is str:
            _need("\x00" not in item and len(item) <= remaining,
                  "handoff JSON string/byte bound exceeded")
            try:
                remaining -= len(item.encode("utf-8")) + 2
            except UnicodeError as error:
                raise ValueError("valid UTF8 handoff JSON required") from error
        elif item is None or type(item) is bool:
            remaining -= 5
        elif type(item) is int:
            _need(-(1 << 63) < item < (1 << 63), "bounded handoff integer required")
            remaining -= 20
        elif type(item) is float:
            _need(math.isfinite(item), "finite handoff JSON required")
            remaining -= 32
        else:
            raise ValueError("ordinary handoff JSON values required")
        _need(remaining >= 0, "complete handoff JSON byte bound exceeded")

    visit(value, 0)
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    _need(len(encoded) <= maximum, "complete handoff JSON byte bound exceeded")
    return encoded


def _digest(value):
    return hashlib.sha256(_wire(value)).hexdigest()


def _copy(value):
    return json.loads(_wire(value))


def _legacy(handoff_raw, expected_handoff_sha256):
    _sha(expected_handoff_sha256, "original handoff raw bytes")
    _need(type(handoff_raw) is bytes and 0 < len(handoff_raw) <= MAX_HANDOFF_BYTES,
          "bounded immutable original handoff bytes required")
    _need(hashlib.sha256(handoff_raw).hexdigest() == expected_handoff_sha256,
          "independent original handoff raw pin differs")

    def pairs(items):
        result = {}
        for key, item in items:
            _need(key not in result, "duplicate handoff JSON key")
            result[key] = item
        return result

    def constant(_):
        raise ValueError("nonfinite handoff JSON constant")

    try:
        value = json.loads(handoff_raw.decode("utf-8"), object_pairs_hook=pairs,
                           parse_constant=constant)
    except (UnicodeError, ValueError, RecursionError, OverflowError) as error:
        raise ValueError("bounded unique finite UTF8 original handoff JSON required") from error
    # Reject finite-syntax overflows (such as 1e309) and invalid Unicode escapes.
    value = _copy(value)
    _keys(value, _LEGACY_FIELDS, "original source-only handoff")
    _need(value["schema"] == LEGACY_SCHEMA
          and value["status"] == "unanswered_source_only_not_a_review_submission",
          "unanswered original source-only handoff profile required")
    purpose = value["navigation_purpose"]
    _need(type(purpose) is str and purpose.strip() and len(purpose.encode("utf-8")) <= 256,
          "bounded navigation metadata required")
    _sha(value["sampling_report_full_canonical_sha256"], "original complete sampler report")
    _keys(value["responses"], set(LEGACY_QUESTION_IDS), "original thirteen unanswered questions")
    for answer in value["responses"].values():
        _keys(answer, {"answer", "rationale", "evidence_refs"}, "original blank answer")
        _need(answer["answer"] is None and answer["rationale"] is None
              and type(answer["evidence_refs"]) is list and answer["evidence_refs"] == [],
              "partially answered handoff cannot be migrated as blank")
    _need(all(value[key] is None for key in
              ("reviewer", "exposure_declaration", "meaning_target", "typed_AST")),
          "blank reviewer, exposure and meaning fields required")
    _need(type(value["definition_use_bindings"]) is list and value["definition_use_bindings"] == [],
          "blank handoff cannot retain or discard definition-use bindings")
    _need(all(type(value[key]) is int and value[key] == 0 for key in
              ("training_mask", "evaluation_gold_mask")), "zero original handoff masks required")
    _need(type(value["authority"]) is dict and bool(value["authority"])
          and all(flag is False for flag in value["authority"].values()),
          "all original handoff authority flags must be false")
    _need(all(type(value[key]) is dict for key in
              ("unit", "source_occurrence", "original_context", "v2_context_packet")),
          "complete original source/context records required")
    return value


def _owners():
    from . import legal_source_sampling_review as review
    from . import legal_statutory_context_v2 as contexts
    from .corpus_contracts import seal_record

    return review, contexts, seal_record


def _record(ref, records):
    matches = [row for row in records if row.get("schema") == ref["schema"]
               and row.get("record_cid") == ref["record_cid"]
               and _digest(row) == ref["sha256"]]
    _need(len(matches) == 1, "one exact complete sampler source/context record required")
    return matches[0]


def prepare_sampling_review_handoff(
    handoff_raw, bundle, raw, *, expected_handoff_sha256,
    expected_bundle_sha256, **replay_inputs
):
    """Migrate only unanswered old inputs; all fifteen new answers stay blank."""
    _sha(expected_bundle_sha256, "complete sampling review bundle")
    original = _legacy(handoff_raw, expected_handoff_sha256)
    review, contexts, seal = _owners()
    checked = review.validate_sampling_review_bundle(
        bundle, raw, expected_bundle_sha256=expected_bundle_sha256, **replay_inputs
    )
    report = checked["sampling_report"]
    _need(original["sampling_report_full_canonical_sha256"]
          == checked["manifest"]["sampling_report_sha256"],
          "original handoff belongs to another complete sampler report")
    _need(_wire(original["authority"]) == _wire(contexts.AUTHORITY),
          "original handoff authority profile differs")
    units = [row for row in report["records"]
             if row["schema"] == "legal-source-structured-sample-unit/v1"]
    unit_wire = _wire(original["unit"])
    matches = [(index, unit) for index, unit in enumerate(units)
               if _wire(unit) == unit_wire]
    _need(len(matches) == 1, "original handoff unit differs from complete sampler population")
    index, unit = matches[0]
    subject = {"kind": "unit", "index": index, "sha256": _digest(unit)}
    guides = [guide for guide in checked["guides"] if guide["subject_ref"] == subject]
    _need(len(guides) == 1, "one exact sampler review guide required")
    guide = guides[0]
    occurrence = _record(unit["source_occurrence_ref"], report["records"])
    context = _record(unit["context_ref"], report["records"])
    _need(_wire(original["source_occurrence"]) == _wire(occurrence)
          and _wire(original["original_context"]) == _wire(context),
          "original handoff occurrence or context differs from exact sampler records")
    _need(_wire(guide["source_occurrence_ref"]) == _wire(unit["source_occurrence_ref"])
          and _wire(guide["context_ref"]) == _wire(unit["context_ref"]),
          "review guide source/context correspondence differs")

    packet, view = original["v2_context_packet"], report["document_view_report"]
    selection = packet.get("selection")
    _need(type(selection) is dict, "exact original V2 context selection required")
    geometry = (("char_start", "start_char"), ("char_end", "end_char"),
                ("utf8_byte_start", "start_utf8"), ("utf8_byte_end", "end_utf8"))
    _need(all(type(selection.get(left)) is int
              and selection[left] == occurrence[right] for left, right in geometry),
          "V2 context and original occurrence character/UTF8 geometry differ")
    _need(selection.get("text") == occurrence["span_text"]
          and selection.get("text_sha256") == occurrence["span_sha256"]
          and selection.get("view_id") == unit["normalized_view_id"]
          == view["normalized_view"]["view_id"]
          and selection.get("document_id") == view["document"]["document_id"],
          "V2 context and original occurrence text/view correspondence differs")
    binding = checked["manifest"]["input_binding"]
    source_inputs = {key: binding[key] for key in
                     ("descriptor", "expected_descriptor_sha256",
                      "expected_raw_sha256", "expected_raw_bytes")}
    contexts.validate_context_packet_v2(
        packet, view, raw, expected_selector=selection,
        expected_report_sha256=report["document_view_report_sha256"],
        limits=view["limits"], **source_inputs
    )
    question_ids = [question["question_id"]
                    for question in checked["question_catalog"]["questions"]]
    _need(question_ids == [*LEGACY_QUESTION_IDS, *ADDED_QUESTION_IDS],
          "fixed thirteen-plus-two question catalog required")
    template = _copy(guide["response_template"])
    template["bundle_sha256"] = expected_bundle_sha256
    payload = {
        "schema": SCHEMA,
        "origin": {
            "schema": original["schema"],
            "raw_sha256": expected_handoff_sha256,
            "raw_bytes": len(handoff_raw),
            "full_canonical_sha256": _digest(original),
            "sampling_report_full_canonical_sha256": original["sampling_report_full_canonical_sha256"],
            "navigation_purpose": original["navigation_purpose"],
        },
        "bundle_sha256": expected_bundle_sha256,
        "question_catalog_ref": guide["question_catalog_ref"],
        "subject_ref": guide["subject_ref"],
        "source_version_ref": unit["source_version_ref"],
        "source_occurrence_ref": guide["source_occurrence_ref"],
        "context_ref": guide["context_ref"],
        "v2_context_packet_ref": {"schema": packet["schema"],
                                  "packet_id": packet["packet_id"], "sha256": _digest(packet)},
        "evidence_refs": guide["evidence_refs"],
        "response_template": template,
        "legacy_question_ids": list(LEGACY_QUESTION_IDS),
        "added_question_ids": list(ADDED_QUESTION_IDS),
        "unanswered_question_ids": question_ids,
        "coordinate_profile": "sampler_markup_v2_only_not_native_v1_or_raw_HTML_offsets",
        "status": "blank_handoff_not_a_review_response",
        "authority": dict(review.FALSE_FLAGS),
        "training_mask": 0,
        "evaluation_gold_mask": 0,
        "response_recorded": False,
        "review_completed": False,
    }
    return _copy(seal(_copy(payload)))


def sampling_review_handoff_sha256(draft):
    """Hash the complete bounded draft, including its record envelope."""
    _keys(draft, _DRAFT_FIELDS, "sampling review handoff draft")
    _need(draft["schema"] == SCHEMA, "sampling review handoff schema required")
    return _digest(draft)


def validate_sampling_review_handoff(
    draft, handoff_raw, bundle, raw, *, expected_handoff_record_sha256,
    expected_handoff_sha256, expected_bundle_sha256, **replay_inputs
):
    """Pin the full draft before exact original-source and blank-draft replay."""
    _sha(expected_handoff_record_sha256, "complete sampling review handoff record")
    offered = _copy(draft)
    _keys(offered, _DRAFT_FIELDS, "sampling review handoff draft")
    _need(_digest(offered) == expected_handoff_record_sha256,
          "independent complete sampling review handoff pin differs")
    expected = prepare_sampling_review_handoff(
        handoff_raw, bundle, raw, expected_handoff_sha256=expected_handoff_sha256,
        expected_bundle_sha256=expected_bundle_sha256, **replay_inputs
    )
    _need(_wire(offered) == _wire(expected),
          "handoff draft differs from exact source-bound blank regeneration")
    return expected


__all__ = [
    "prepare_sampling_review_handoff",
    "sampling_review_handoff_sha256",
    "validate_sampling_review_handoff",
]
