"""Transport explicit predicted occurrences into the existing scope declaration.

This is a proposal boundary for a future occurrence decoder, not a source parser
or a trained qualifier model. Modality and attachment are unreviewed declarations.
Opaque conditions are preserved without inventing implication or modal placement.
The existing scope owner validates transport and retains every admission mask at 0.
"""
from __future__ import annotations

import hashlib
import json
import re

from ...legal_ir import canonical_statement_scope as scope

PREDICTION_SCHEMA = "legal-scope-span-prediction/v1"
PROPOSAL_SCHEMA = "legal-scope-span-proposal/v1"
INTERPRETATION_PROFILE = "opaque_condition_attachment/v1"
MAX_SOURCE_CHARS = 8192
_TOKEN = re.compile(r"\w+|[^\w\s]", re.UNICODE)
_FACETS = ("modality", "actor", "action", "object", "condition")


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()


def propose_scope_from_spans(source_text, prediction, *, expected_source_sha256):
    """Copy closed, nonoverlapping Unicode character spans; never infer anchors.

    A future model must emit modality, actor and action occurrences and explicit
    nullable object/condition occurrences. Grouped v2 does not provide those extra
    endpoints. Source bytes are bound externally; meaning and source completeness
    remain unassessed, with unavailable context and a full-source review marker.
    """
    _require(type(source_text) is str and 0 < len(source_text) <= MAX_SOURCE_CHARS
             and source_text.strip() and "\x00" not in source_text, "bounded nonempty source required")
    try:
        raw = source_text.encode("utf-8")
    except UnicodeError as error:
        raise ValueError("valid UTF8 source required") from error
    _require(type(expected_source_sha256) is str
             and re.fullmatch(r"[0-9a-f]{64}", expected_source_sha256) is not None,
             "externally expected lowercase source SHA256 required")
    _require(hashlib.sha256(raw).hexdigest() == expected_source_sha256, "source digest mismatch")
    fields = {"schema", "interpretation_profile", "modality", "spans", "condition_attachment"}
    _require(type(prediction) is dict and all(type(k) is str for k in prediction)
             and set(prediction) == fields, "closed span prediction required")
    _require(type(prediction["schema"]) is str and prediction["schema"] == PREDICTION_SCHEMA
             and type(prediction["interpretation_profile"]) is str
             and prediction["interpretation_profile"] == INTERPRETATION_PROFILE, "known prediction/profile required")
    _require(type(prediction["modality"]) is str and prediction["modality"] in {"O", "P", "F"},
             "declared O/P/F modality required")
    spans = prediction["spans"]
    _require(type(spans) is dict and all(type(k) is str for k in spans)
             and set(spans) == set(_FACETS), "closed occurrence spans required")
    starts, ends = set(), set()
    for token in _TOKEN.finditer(source_text):
        starts.add(token.start())
        ends.add(token.end())
    coordinates = []
    for facet in _FACETS:
        value = spans[facet]
        if value is None and facet in {"object", "condition"}:
            continue
        _require(type(value) is list and len(value) == 2 and all(type(v) is int for v in value),
                 "explicit integer occurrence pair required: " + facet)
        start, end = value
        _require(0 <= start < end <= len(source_text), "occurrence outside source: " + facet)
        _require(start in starts and end in ends, "occurrence cuts a token or includes edge whitespace: " + facet)
        coordinates.append((start, end, facet))
    ordered = sorted(coordinates)
    _require(all(left[1] <= right[0] for left, right in zip(ordered, ordered[1:])),
             "distinct occurrence facets must not overlap")
    attachment = prediction["condition_attachment"]
    if spans["condition"] is None:
        _require(attachment is None, "absent condition requires absent attachment")
    else:
        _require(type(attachment) is str and attachment in {"rule", "statement"},
                 "condition requires explicit rule/statement attachment")
    context = {"role": "required_unavailable", "text": "", "bindings": {},
               "sha256": hashlib.sha256(b"").hexdigest()}
    request = {"source_text": source_text, "context": context}
    input_sha256 = _digest(request)
    occurrences, identities = [], {}
    for start, end, facet in coordinates:
        identity = "occ-" + facet + "-" + str(start) + "-" + str(end)
        identities[facet] = identity
        occurrences.append({"occurrence_id": identity,
            "facet": "conditions" if facet == "condition" else facet,
            "canonical_symbol": prediction["modality"] if facet == "modality" else source_text[start:end],
            "anchor": {"origin": "source", "start": start, "end": end,
                       "text": source_text[start:end], "offset_unit": "unicode_character_half_open"}})
    qualifiers = {name: None for name in scope.QUALIFIERS}
    if attachment is not None:
        qualifiers["conditions"] = {"op": "leaf", "occurrence_id": identities["condition"]}
    local = qualifiers if attachment == "rule" else {name: None for name in scope.QUALIFIERS}
    structure = {"op": "rule", "rule_id": "rule-0"}
    if attachment == "statement":
        structure = {"op": "attach", "body": structure, "qualifiers": qualifiers}
    declaration = {"schema": scope.SCHEMA, "family": "deontic", "profile": scope.PROFILE,
        "input": request, "input_sha256": input_sha256, "occurrences": occurrences,
        "rules": [{"rule_id": "rule-0", "body": {name: identities.get(name) for name in scope.CORE},
                   "qualifiers": local}], "statement_structure": structure, "binders": [],
        "coverage": {"declared_status": "unassessed", "segments": []},
        "unresolved": [{"code": "source_interpretation_and_context_review_required",
            "span": {"origin": "source", "start": 0, "end": len(source_text),
                     "text": source_text, "offset_unit": "unicode_character_half_open"},
            "reason": "Predicted occurrences and opaque attachment do not establish legal meaning or source completeness."}]}
    declaration["content_sha256"] = _digest(declaration)
    validated = scope.validate_scope_declaration(request, declaration, expected_input_sha256=input_sha256)
    _require(all(mask == 0 for mask in validated["masks"].values()), "proposal must not acquire admission masks")
    return {"schema": PROPOSAL_SCHEMA, "status": "unreviewed_occurrence_proposal",
        "source_sha256": expected_source_sha256, "interpretation_profile": INTERPRETATION_PROFILE,
        "declaration": declaration, "validation": validated, "masks": dict(validated["masks"]),
        "context_resolved": False, "source_coverage_assessed": False,
        "source_semantics_verified": False, "source_fidelity_established": False,
        "semantic_profile_validated": False, "semantic_equivalence_assessed": False,
        "binder_terms_typechecked": False, "normalization_approved": False, "lowering_authorized": False,
        "model_executed": False, "training_executed": False, "target_access": False,
        "qualified": False, "accepted": False, "formalized": False, "proof_ready": False, "proof_authority": False,
        "model_calls": 0, "prover_calls": 0, "formal_output": None,
        "blockers": ["source_interpretation_unreviewed", "source_coverage_unassessed", "context_required_unavailable"]}


__all__ = ["propose_scope_from_spans"]
