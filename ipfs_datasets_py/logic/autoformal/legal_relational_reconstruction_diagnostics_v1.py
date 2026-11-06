"""Named structural diagnostics over the existing validated pair ledger.

This companion delegates syntax, lexical alpha comparison and original-input
replay to legal_relational_reconstruction_v1. It groups that owner's flat
features; it parses no expression and supplies no semantic correctness score.
Public import uses only the standard library and performs no owner replay.
"""
from __future__ import annotations

import hashlib
from pathlib import Path


SCHEMA = "legal-relational-reconstruction-diagnostics/v1"
PROFILE = "paired-valid-existing-ledger-structural-groups/v1"
MAX_OUTPUT_BYTES = 8 * 1024 * 1024
_SELF_PATH = Path(__file__).resolve()
_SELF_PIN = hashlib.sha256(_SELF_PATH.read_bytes()).hexdigest()
_CONNECTIVES = frozenset(("and", "or", "implies", "iff", "not"))
_FIELDS = {
    "binder_quantifier_topology": (
        "kind", "sort", "binder_paths", "binding_quantifier_path", "quantifier_kind",
        "ordered_child_paths", "modal_ancestry", "connective_ancestry",
    ),
    "modal_operator_placement": (
        "kind", "modal_operator", "ordered_child_paths", "extension_payload_schema",
        "extension_family", "extension_profile", "extension_features", "extension_payload",
        "modal_ancestry", "connective_ancestry",
    ),
    "predicate_ordered_arguments_roles": (
        "kind", "sort", "predicate_symbol", "predicate_typed_path",
        "predicate_argument_index", "declared_argument_role", "argument_roles",
        "binding_quantifier_path", "quantifier_kind", "ordered_child_paths",
        "modal_ancestry", "connective_ancestry",
    ),
    "connective_negation_context": (
        "kind", "ordered_child_paths", "connective_ancestry", "modal_ancestry",
        "modal_operator", "predicate_symbol", "predicate_argument_index",
        "binding_quantifier_path", "quantifier_kind",
    ),
}
_OUTPUT_FIELDS = {
    "schema", "profile", "status", "comparison", "comparison_sha256", "groups",
    "comparisons", "valid_input_pair_only", "invalid_inputs_refused",
    "abstention_coverage_evaluated", "unavailable_output_policy", "producer_pins",
    "authority", "training_mask", "evaluation_gold_mask", "limitations",
}


class RelationalReconstructionDiagnosticsError(ValueError):
    """Original pair replay, bounded output or diagnostic identity differs."""


def _owner():
    from . import legal_relational_reconstruction_v1
    return legal_relational_reconstruction_v1


def _need(condition, message):
    if not condition:
        raise RelationalReconstructionDiagnosticsError(message)


def _member(name, features):
    if features is None:
        return False
    kind = features["kind"]
    if name == "binder_quantifier_topology":
        return kind in ("forall", "exists", "binder", "variable")
    if name == "modal_operator_placement":
        return features["modal_operator"] is not None or bool(features["modal_ancestry"])
    if name == "predicate_ordered_arguments_roles":
        return kind in ("predicate", "variable")
    return kind in _CONNECTIVES or bool(features["connective_ancestry"])


def _group(name, comparison):
    """Project exact ledger paths; never realign a child or traverse an AST."""
    fields = _FIELDS[name]
    rows = []
    for entry in comparison["feature_ledger"]:
        left = entry["reference"] if _member(name, entry["reference"]) else None
        right = entry["candidate"] if _member(name, entry["candidate"]) else None
        if left is None and right is None:
            continue
        left = None if left is None else {key: left[key] for key in fields}
        right = None if right is None else {key: right[key] for key in fields}
        both = left is not None and right is not None
        rows.append({
            "typed_path": entry["typed_path"],
            "presence": "both" if both else "reference_only" if left is not None else "candidate_only",
            "reference": left, "candidate": right,
            "equal": left == right if both else None,
            "different_fields": [key for key in fields if left[key] != right[key]] if both else [],
        })
    declarations = {}
    if name == "predicate_ordered_arguments_roles":
        declarations = {
            "signature_declarations_equal": comparison["comparisons"]["signature_declarations_equal"],
            "argument_roles_equal": comparison["comparisons"]["argument_roles_equal"],
        }
    missing = [row["typed_path"] for row in rows if row["presence"] == "reference_only"]
    unexpected = [row["typed_path"] for row in rows if row["presence"] == "candidate_only"]
    different = [row["typed_path"] for row in rows if row["equal"] is False]
    applicable = bool(rows)
    equal = not (missing or unexpected or different) and all(declarations.values()) if applicable else None
    return {
        "status": "not_applicable" if not applicable else "equal" if equal else "different",
        "equal": equal, "projected_fields": list(fields), "rows": rows,
        "reference_path_count": sum(row["reference"] is not None for row in rows),
        "candidate_path_count": sum(row["candidate"] is not None for row in rows),
        "reference_only_paths": missing, "candidate_only_paths": unexpected,
        "different_paths": different, "declaration_checks": declarations,
    }


def prepare_relational_reconstruction_diagnostics_v1(
        reference_report, candidate_report, *, reference_request_raw, candidate_request_raw,
        expected_reference_request_sha256, expected_candidate_request_sha256,
        expected_reference_report_sha256, expected_candidate_report_sha256):
    """Replay the original valid pair, then group its existing path features.

Incomplete/invalid generated outputs have no valid candidate report and refuse.
Their caller must retain those enrolled outcomes with structural metrics null;
this pair-only API neither supplies nor changes a corpus denominator.
"""
    owner = _owner()
    try:
        _need(owner._source_pin(_SELF_PATH) == _SELF_PIN, "diagnostics source changed since import")
        comparison = owner.prepare_relational_reconstruction_comparison_v1(
            reference_report, candidate_report,
            reference_request_raw=reference_request_raw, candidate_request_raw=candidate_request_raw,
            expected_reference_request_sha256=expected_reference_request_sha256,
            expected_candidate_request_sha256=expected_candidate_request_sha256,
            expected_reference_report_sha256=expected_reference_report_sha256,
            expected_candidate_report_sha256=expected_candidate_report_sha256,
        )
        groups = {name: _group(name, comparison) for name in _FIELDS}
        pins = dict(comparison["producer_pins"])
        _need(str(_SELF_PATH) not in pins or pins[str(_SELF_PATH)] == _SELF_PIN,
              "diagnostics source pin conflicts with original closure")
        pins[str(_SELF_PATH)] = _SELF_PIN
        result = {
            "schema": SCHEMA, "profile": PROFILE,
            "status": "unreviewed_valid_relational_pair_diagnosed",
            "comparison": comparison,
            "comparison_sha256": owner.relational_reconstruction_comparison_sha256(comparison),
            "comparisons": dict(comparison["comparisons"]), "groups": groups,
            "valid_input_pair_only": True, "invalid_inputs_refused": True,
            "abstention_coverage_evaluated": False,
            "unavailable_output_policy": "retain_enrolled_outcome_with_structural_metrics_unavailable",
            "producer_pins": pins, "authority": dict(comparison["authority"]),
            "training_mask": 0, "evaluation_gold_mask": 0,
            "limitations": [
                "The existing comparator replays both original authored declarations and owns syntax, typed paths and lexical alpha comparison.",
                "Named groups are projections of that complete feature ledger, not a replacement AST, new logic interpretation or aggregate accuracy score.",
                "Lexical binder names, variable symbols, node IDs and native paths are excluded from group projections; binding quantifier paths, ordered positions and predicate identities remain explicit.",
                "Group paths never realign. A node absent from that group on one side is retained as a missing side, even when another kind occupies the same typed path.",
                "An absent group on both valid sides is not_applicable with equal=null; it is not a successful comparison.",
                "Groups overlap and include structural ancestry. A difference describes that projection, not an independently isolated error cause.",
                "The original exact, declared and lexical alpha comparisons remain separate. Group equality is not semantic or legal equivalence.",
                "Invalid or incomplete candidates refuse; callers must retain them in all-enrolled counts with structural diagnostics unavailable rather than replace them with a target or count them as a match.",
                "Target exposure, authored conditioning and decoder provenance require separate reporting. This API qualifies no model, training data, inference policy, source meaning or corpus denominator.",
                "No model, optimizer, solver or build executes. Original replay may regenerate syntax-only Lean text without compiling it.",
            ],
        }
        owner._wire(result, MAX_OUTPUT_BYTES)
        _need(owner._source_pin(_SELF_PATH) == _SELF_PIN, "diagnostics source changed during operation")
        for path, expected in comparison["producer_pins"].items():
            _need(owner._source_pin(Path(path)) == expected, "original producer source changed during diagnostics")
        # Existing finite JSON helper returns detached ordinary objects.
        return owner._copy(result, MAX_OUTPUT_BYTES)
    except ValueError as error:
        if isinstance(error, RelationalReconstructionDiagnosticsError):
            raise
        raise RelationalReconstructionDiagnosticsError(str(error)) from error


def relational_reconstruction_diagnostics_sha256(report):
    """Hash the whole closed diagnostic; self-hashing creates no authority."""
    owner = _owner()
    try:
        _need(type(report) is dict and set(report) == _OUTPUT_FIELDS
              and report["schema"] == SCHEMA and report["profile"] == PROFILE,
              "complete closed reconstruction diagnostics required")
        return owner._digest(report, MAX_OUTPUT_BYTES)
    except ValueError as error:
        if isinstance(error, RelationalReconstructionDiagnosticsError):
            raise
        raise RelationalReconstructionDiagnosticsError(str(error)) from error


def validate_relational_reconstruction_diagnostics_v1(report, *args,
        expected_diagnostics_sha256, **kwargs):
    """Require independent complete-output pin and original-bound regeneration."""
    owner = _owner()
    try:
        owner._pin(expected_diagnostics_sha256, "complete reconstruction diagnostics")
        _need(relational_reconstruction_diagnostics_sha256(report) == expected_diagnostics_sha256,
              "independent complete diagnostics pin differs")
        offered = owner._wire(report, MAX_OUTPUT_BYTES)
        expected = prepare_relational_reconstruction_diagnostics_v1(*args, **kwargs)
        _need(offered == owner._wire(expected, MAX_OUTPUT_BYTES),
              "diagnostics differ from original-bound regeneration")
        return expected
    except ValueError as error:
        if isinstance(error, RelationalReconstructionDiagnosticsError):
            raise
        raise RelationalReconstructionDiagnosticsError(str(error)) from error


__all__ = ["RelationalReconstructionDiagnosticsError",
           "prepare_relational_reconstruction_diagnostics_v1",
           "relational_reconstruction_diagnostics_sha256",
           "validate_relational_reconstruction_diagnostics_v1"]
