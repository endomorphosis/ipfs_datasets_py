"""Compare actual grouped decoder outputs with separately held semantic targets.

This evaluator does not run a learned model or infer legal truth. The candidate
decoder receives only its own closed semantic request; a failed/missing output
cannot borrow the target, its formula or its readiness.
"""
from __future__ import annotations

from typing import Any

from ..deontic.coordination_decoder import (
    CoordinationDecodeRequest,
    decode_coordination_request,
    semantic_label_identity,
)

SCHEMA = "legal-coordination-output-evaluation/v1"
MAX_EVALUATION_ITEMS = 1024
NORMALIZATION_PROFILE = "whitespace_casefold_actor_article/v1"
_MEASURES = (
    "scope_equal", "connective_equal", "binding_profile_equal", "member_count_equal",
    "actor_equal", "modality_equal", "action_equal", "request_exact_match",
    "formula_exact_match", "native_ast_exact_match", "semantic_ir_agreement",
)


def _request(value: Any) -> CoordinationDecodeRequest:
    if type(value) is CoordinationDecodeRequest:
        value.validate()
        return value
    return CoordinationDecodeRequest.from_dict(value)


def evaluate_coordination_outputs(targets, outputs) -> dict[str, Any]:
    """Count every output and preserve branch order/multiplicity and modal scope.

    Target items must be validated typed requests. Candidate outputs may be
    typed requests or their exact closed JSON dictionaries. Invalid candidates
    become failed observations. Unequal item counts retain missing/extra cases.
    Normalized semantic agreement and exact request field agreement are reported
    separately; neither establishes independently reviewed source meaning.
    """
    if type(targets) not in (list, tuple) or type(outputs) not in (list, tuple):
        raise ValueError("bounded target/output sequences required")
    if len(targets) > MAX_EVALUATION_ITEMS or len(outputs) > MAX_EVALUATION_ITEMS:
        raise ValueError("coordination evaluation exceeds item bound")
    if any(type(item) is not CoordinationDecodeRequest for item in targets):
        raise ValueError("validated typed reference requests required")
    targets = [_request(item) for item in targets]
    # Reference validity is checked independently, before candidate evaluation.
    references = [decode_coordination_request(item) for item in targets]
    count = max(len(targets), len(outputs))
    cases = []
    for index in range(count):
        row = {"index": index, "status": "failed", "blockers": [],
               **{measure: False for measure in _MEASURES}}
        if index >= len(targets):
            row["blockers"].append("unexpected_output")
        elif index >= len(outputs):
            row["blockers"].append("missing_output")
        else:
            try:
                candidate = _request(outputs[index])
                decoded = decode_coordination_request(candidate)
            except (ValueError, TypeError, KeyError, AttributeError, RecursionError) as error:
                row["blockers"].append("invalid_output_schema")
                row["diagnostic"] = str(error)
            else:
                target = targets[index]
                row.update({
                    "scope_equal": target.modal_scope == candidate.modal_scope,
                    "connective_equal": target.connective == candidate.connective,
                    "binding_profile_equal": target.binding_profile == candidate.binding_profile,
                    "member_count_equal": len(target.members) == len(candidate.members),
                    "request_exact_match": target.to_dict() == candidate.to_dict(),
                    "formula_exact_match": references[index]["formula"] == decoded["formula"],
                    "native_ast_exact_match": references[index]["native_ast"] == decoded["native_ast"],
                })
                for slot, measure in (("actor", "actor_equal"), ("modality", "modality_equal"),
                                      ("action", "action_equal")):
                    row[measure] = row["member_count_equal"] and all(
                        (semantic_label_identity(getattr(left, slot), actor=slot == "actor")
                         == semantic_label_identity(getattr(right, slot), actor=slot == "actor"))
                        for left, right in zip(target.members, candidate.members)
                    )
                row["semantic_ir_agreement"] = all(row[measure] for measure in (
                    "scope_equal", "connective_equal", "binding_profile_equal", "member_count_equal",
                    "actor_equal", "modality_equal", "action_equal", "native_ast_exact_match",
                ))
                row["candidate_formula"] = decoded["formula"]
                row["candidate_normalized_text"] = decoded["normalized_text"]
                row["candidate_syntax_valid"] = decoded["family_validation"]["passed"]
                if row["semantic_ir_agreement"]:
                    row["status"] = "passed"
                else:
                    row["blockers"].extend(measure + "_mismatch" for measure in (
                        "scope_equal", "connective_equal", "binding_profile_equal", "member_count_equal",
                        "actor_equal", "modality_equal", "action_equal", "native_ast_exact_match",
                    ) if not row[measure])
        cases.append(row)
    totals = {measure: sum(row[measure] for row in cases) for measure in _MEASURES}
    passed = sum(row["status"] == "passed" for row in cases)
    return {
        "schema": SCHEMA, "normalization_profile": NORMALIZATION_PROFILE,
        "target_count": len(targets), "output_count": len(outputs), "case_count": count,
        "aligned_count": min(len(targets), len(outputs)),
        "missing_output_count": max(0, len(targets) - len(outputs)),
        "unexpected_output_count": max(0, len(outputs) - len(targets)),
        "invalid_output_count": sum("invalid_output_schema" in row["blockers"] for row in cases),
        "passed_count": passed, "failed_count": count - passed,
        "measure_counts": totals,
        "measure_rates": {measure: total / count if count else 0.0 for measure, total in totals.items()},
        "all_outputs_agree_with_target_ir": bool(count and targets) and passed == count,
        "blockers": [] if targets else ["empty_reference_set"], "cases": cases,
        "target_ir_comparison_only": True, "source_semantics_verified": False,
        "semantic_equivalence_checked": False, "model_accuracy_claimed": False,
        "model_calls": 0, "training_calls": 0, "proof_ready": False,
    }
