"""Exact temporal source occurrences, with diagnostic associations only.

This sidecar does not extend CanonicalRule/v1 or the three-field temporal
records. Parser observations, lexical rule candidates and surface proposals
never resolve a legal owner, clock, scope or formula admission.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

SCHEMA = "legal-temporal-occurrence-provenance/v1"
JOIN_SCHEMA = "legal-temporal-occurrence-diagnostic-join/v1"
COORDINATE_SYSTEM = "unicode-codepoint-half-open/source-text-v1"
_FALSE = {
    "semantic_gold": False,
    "source_semantics_verified": False,
    "owner_occurrence_resolved": False,
    "temporal_origin_resolved": False,
    "scope_resolved": False,
    "formula_admission": False,
    "family_coverage_gate": False,
    "qualified": False,
    "admitted": False,
    "formalized": False,
    "model_execution_verified": False,
}


def _wire(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(_wire(value)).hexdigest()


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _copy(value: Any) -> Any:
    return json.loads(_wire(value))


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _bounds(start: Any, end: Any, length: int) -> None:
    _require(type(start) is int and type(end) is int and 0 <= start < end <= length,
             "exact nonempty code-point bounds required")


def _seal(value: dict) -> dict:
    return {**value, "receipt_sha256": digest(value)}


def _source_binding(source_text, source_id, document_text, document_id,
                    clause_start, clause_end, source_selector):
    _require(type(source_text) is str and bool(source_text), "nonempty source text required")
    _require(type(source_id) is str and bool(source_id), "source ID required")
    if document_text is None:
        document_text = source_text
    _require(type(document_text) is str, "document text required")
    if document_id is None:
        document_id = source_id
    _require(type(document_id) is str and bool(document_id), "document ID required")
    _require(type(clause_start) is int, "integer clause start required")
    if clause_end is None:
        clause_end = clause_start + len(source_text)
    _bounds(clause_start, clause_end, len(document_text))
    if source_selector is None:
        _require(document_text[clause_start:clause_end] == source_text,
                 "document-to-clause identity differs; validated source selector required")
        translation = "identity"
    else:
        from ..legal_document import _clause_selector

        byte_offsets = [0]
        for character in document_text:
            byte_offsets.append(byte_offsets[-1] + len(character.encode("utf-8")))
        expected = _clause_selector(document_text, source_text, clause_start,
                                    byte_offsets, _sha(document_text))
        _require(expected is not None and expected["start"] == clause_start
                 and expected["end"] == clause_end
                 and _wire(source_selector) == _wire(expected),
                 "source selector differs from exact whitespace alignment")
        translation = "validated_whitespace_alignment"
    return document_text, {
        "source_id": source_id,
        "clause_id": source_id,
        "document_id": document_id,
        "source_text_sha256": _sha(source_text),
        "document_text_sha256": _sha(document_text),
        "source_coordinate_system": COORDINATE_SYSTEM,
        "document_coordinate_system": "unicode-codepoint-half-open/document-text-v1",
        "clause_start_in_document": clause_start,
        "clause_end_in_document": clause_end,
        "source_selector": _copy(source_selector),
        "document_translation": translation,
    }


def _document_boundary(position: int, binding: dict, source_text: str,
                       document_text: str) -> int | None:
    selector = binding["source_selector"]
    if selector is None:
        return binding["clause_start_in_document"] + position
    candidates = set()
    for item in selector["mapping"]:
        left, right = item["text_start"], item["text_end"]
        raw_left, raw_right = item["source_start"], item["source_end"]
        if position == left:
            candidates.add(raw_left)
        if position == right:
            candidates.add(raw_right)
        if (left < position < right
                and source_text[left:right] == document_text[raw_left:raw_right]):
            candidates.add(raw_left + position - left)
    return next(iter(candidates)) if len(candidates) == 1 else None


def _rule_inventory(rule_rows: Sequence[Mapping[str, Any]]) -> list[dict]:
    _require(isinstance(rule_rows, (list, tuple)), "ordered rule rows required")
    result = []
    for index, row in enumerate(rule_rows):
        _require(isinstance(row, Mapping), "rule row object required")
        rule = row.get("rule")
        _require(rule is None or isinstance(rule, Mapping), "rule object or null required")
        temporal = [] if rule is None else rule.get("temporal", [])
        _require(isinstance(temporal, (list, tuple)) and all(type(atom) is str for atom in temporal),
                 "ordered temporal strings required")
        result.append({"rule_index": index, "status": str(row.get("status") or ""),
                       "rule_sha256": None if rule is None else digest(rule),
                       "row_sha256": digest(row), "has_rule": rule is not None,
                       "temporal_atom_count": len(temporal)})
    return result


def _candidate_atoms(observation: dict) -> set[str]:
    detail = observation["parser_fields"]
    value = detail["value"]
    atoms = {value}
    # Explicit existing display variants only; no new temporal interpretation.
    if detail["temporal_kind"] == "minimum_duration":
        atoms.add("at least " + value)
    return atoms


def build_occurrence_receipt(
    source_text: str, *, source_id: str, document_text: str | None = None,
    document_id: str | None = None, clause_start: int = 0,
    clause_end: int | None = None, source_selector: dict | None = None,
    rule_rows: Sequence[Mapping[str, Any]] = (), parser_inventory: dict | None = None,
) -> dict:
    """Capture exact parser inventory beside unchanged compiler rule rows.

    Source offsets address the exact parser input. Document offsets require
    either identical text or a regenerated legal-clause-selector-v1. Source
    identity is evidence binding, not attestation of document or legal meaning.
    """
    from ..deontic.utils import deontic_parser as parser

    document_text, binding = _source_binding(
        source_text, source_id, document_text, document_id,
        clause_start, clause_end, source_selector)
    inventory = parser.extract_temporal_constraint_inventory(source_text)
    if parser_inventory is not None:
        _require(_wire(parser_inventory) == _wire(inventory),
                 "parser inventory differs from authoritative regeneration")
    rules = _rule_inventory(rule_rows)
    grouped: dict[tuple[int, int], list[dict]] = {}
    observations = [
        {"status": "retained", "parser_fields": detail, "containers": [], "reason_codes": []}
        for detail in inventory["retained"]
    ] + [
        {"status": "excluded", "parser_fields": entry["detail"],
         "containers": entry["containers"], "reason_codes": entry["reason_codes"]}
        for entry in inventory["excluded"]
    ]
    for observation in observations:
        detail = observation["parser_fields"]
        start, end = detail["span"]
        _bounds(start, end, len(source_text))
        _require(detail["raw_text"] == source_text[start:end].strip(),
                 "parser stripped raw text differs from exact source slice")
        grouped.setdefault((start, end), []).append(_copy(observation))
    occurrences = []
    for (start, end), observed in sorted(grouped.items()):
        occurrence_id = "temporal-occurrence-sha256:" + digest({
            "source_text_sha256": binding["source_text_sha256"],
            "coordinate_system": COORDINATE_SYSTEM, "char_start": start, "char_end": end,
        })
        candidates = []
        atom_values = set().union(*[_candidate_atoms(item) for item in observed if item["status"] == "retained"])
        for row, rule in zip(rule_rows, rules):
            for index, atom in enumerate((row.get("rule") or {}).get("temporal", [])):
                if atom in atom_values:
                    candidates.append({"rule_index": rule["rule_index"], "temporal_atom_index": index,
                                       "canonical_temporal_atom": atom,
                                       "rule_sha256": rule["rule_sha256"],
                                       "source_text_sha256": binding["source_text_sha256"],
                                       "relation": "parser_display_string_candidate_only"})
        document_start = _document_boundary(start, binding, source_text, document_text)
        document_end = _document_boundary(end, binding, source_text, document_text)
        translated = document_start is not None and document_end is not None
        document_occurrence_id = None
        if translated:
            document_occurrence_id = "temporal-document-occurrence-sha256:" + digest({
                "document_text_sha256": binding["document_text_sha256"],
                "coordinate_system": binding["document_coordinate_system"],
                "char_start": document_start, "char_end": document_end,
            })
        reasons = ["parser_observation_not_semantic_gold", "owner_occurrence_unresolved"]
        if not translated:
            reasons.append("document_boundary_inside_changed_whitespace_unresolved")
        excluded = all(item["status"] == "excluded" for item in observed)
        if excluded:
            status = "parser_excluded"
            reasons.append("contained_in_condition_or_exception")
        elif len(candidates) > 1:
            status = "multiple_lexical_candidates"
            reasons.append("ambiguous_rule_or_temporal_atom_candidates")
        elif candidates:
            status = "lexical_candidate_only"
        else:
            status = "unmatched"
            reasons.append("no_matching_canonical_temporal_atom")
        occurrences.append({
            "occurrence_id": occurrence_id,
            "document_occurrence_id": document_occurrence_id,
            "temporal_start_in_clause": start, "temporal_end_in_clause": end,
            "temporal_start_in_document": document_start if translated else None,
            "temporal_end_in_document": document_end if translated else None,
            "exact_source_slice": source_text[start:end],
            "exact_document_slice": document_text[document_start:document_end] if translated else None,
            "document_translation_resolved": translated,
            "parser_observations": observed,
            "candidate_rule_indices": sorted({item["rule_index"] for item in candidates}),
            "candidate_rule_associations": candidates,
            "association_status": status, "reason_codes": reasons,
            "authority": dict(_FALSE),
        })
    pins = {"parser_sha256": hashlib.sha256(Path(parser.__file__).read_bytes()).hexdigest(),
            "sidecar_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    if source_selector is not None:
        from .. import legal_document
        pins["selector_producer_sha256"] = hashlib.sha256(Path(legal_document.__file__).read_bytes()).hexdigest()
    return _seal({
        "schema": SCHEMA, "source_binding": binding, "producer_pins": pins,
        "parser_inventory_sha256": digest(inventory), "parser_inventory": _copy(inventory),
        "rule_rows": rules, "occurrences": occurrences,
        "counts": {"occurrences": len(occurrences), "retained_parser_observations": len(inventory["retained"]),
                   "excluded_parser_observations": len(inventory["excluded"]), "rule_rows": len(rules),
                   "rows_without_rule": sum(not row["has_rule"] for row in rules)},
        "inventory_scope": "parser_pattern_inventory_including_exclusions_not_complete_temporal_semantics",
        "authority": dict(_FALSE),
    })


def validate_occurrence_receipt(
    receipt: dict, *, source_text: str, document_text: str | None = None,
    rule_rows: Sequence[Mapping[str, Any]] = (),
    expected_source_id: str | None = None, expected_document_id: str | None = None,
) -> dict:
    """Regenerate exact evidence; caller identities remain separately scoped."""
    _require(type(receipt) is dict and receipt.get("schema") == SCHEMA,
             "versioned occurrence receipt required")
    body = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    _require(receipt.get("receipt_sha256") == digest(body), "occurrence receipt digest differs")
    binding = receipt.get("source_binding")
    _require(type(binding) is dict, "source binding required")
    if expected_source_id is not None:
        _require(binding.get("source_id") == expected_source_id, "expected source ID differs")
    if expected_document_id is not None:
        _require(binding.get("document_id") == expected_document_id, "expected document ID differs")
    expected = build_occurrence_receipt(
        source_text, source_id=binding["source_id"], document_text=document_text,
        document_id=binding["document_id"], clause_start=binding["clause_start_in_document"],
        clause_end=binding["clause_end_in_document"], source_selector=binding["source_selector"],
        rule_rows=rule_rows)
    _require(_wire(receipt) == _wire(expected), "occurrence receipt differs from exact regeneration")
    return receipt


def join_adapter_diagnostics(
    receipt: dict, proposal_receipt: dict, *, source_text: str,
    document_text: str | None = None, rule_rows: Sequence[Mapping[str, Any]] = (),
    expected_source_id: str | None = None, expected_document_id: str | None = None,
) -> dict:
    """Join authenticated surface proposals on exact source hash and interval.

    Every proposal, exclusion and source-only issue is retained. This performs
    the adapter's pure planning validation and never executes an owner model.
    """
    from . import legal_temporal_event_owner_adapter_v4 as adapter

    validate_occurrence_receipt(receipt, source_text=source_text, document_text=document_text,
                                rule_rows=rule_rows, expected_source_id=expected_source_id,
                                expected_document_id=expected_document_id)
    _require(type(proposal_receipt) is dict
             and proposal_receipt.get("source_text") == source_text
             and proposal_receipt.get("source_sha256") == _sha(source_text),
             "adapter source identity differs from occurrence source")
    plan = adapter.plan_batch(proposal_receipt)
    by_span = {(item["temporal_start_in_clause"], item["temporal_end_in_clause"]): item
               for item in receipt["occurrences"]}
    joined, matched_ids = [], set()
    for index, proposal in enumerate(proposal_receipt["proposals"]):
        query = proposal["query"]
        interval = query["proposed_time_span"]
        start, end = interval["char_start"], interval["char_end"]
        _bounds(start, end, len(source_text))
        occurrence = by_span.get((start, end))
        exact_slice = source_text[start:end]
        _require(occurrence is None or occurrence["exact_source_slice"] == exact_slice,
                 "exact proposed temporal text differs")
        if occurrence is not None:
            matched_ids.add(occurrence["occurrence_id"])
        eligibility = plan["eligibility"][index]
        reasons = ["diagnostic_coordinate_join_only", "owner_occurrence_unresolved"]
        if occurrence is None:
            reasons.append("no_exact_parser_occurrence")
        elif occurrence["association_status"] == "parser_excluded":
            reasons.append("parser_occurrence_excluded")
        joined.append({
            "proposal_index": index, "query_id": query["id"],
            "source_sha256": query["source_sha256"], "proposed_time_span": _copy(interval),
            "exact_source_slice": exact_slice,
            "occurrence_id": None if occurrence is None else occurrence["occurrence_id"],
            "status": "unmatched" if occurrence is None else "exact_coordinate_match_only",
            "proposal": _copy(proposal), "adapter_eligibility": _copy(eligibility),
            "reason_codes": reasons, "authority": dict(_FALSE),
        })
    return _seal({
        "schema": JOIN_SCHEMA, "source_sha256": _sha(source_text),
        "occurrence_receipt_sha256": receipt["receipt_sha256"],
        "proposal_receipt_sha256": digest(proposal_receipt),
        "adapter_plan_sha256": digest(plan), "adapter_producer_pins": _copy(plan["producer_pins"]),
        "rows": joined, "excluded": _copy(plan["excluded"]), "issues": _copy(plan["issues"]),
        "unmatched_occurrence_ids": [item["occurrence_id"] for item in receipt["occurrences"]
                                     if item["occurrence_id"] not in matched_ids],
        "counts": {"proposals": len(joined), "exact_coordinate_matches": len(matched_ids),
                   "unmatched_proposals": sum(row["occurrence_id"] is None for row in joined),
                   "excluded_proposals": len(plan["excluded"]), "issues": len(plan["issues"])},
        "model_calls": 0, "authority": dict(_FALSE),
    })
