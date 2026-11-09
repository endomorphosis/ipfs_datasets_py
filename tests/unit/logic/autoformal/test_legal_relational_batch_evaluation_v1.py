"""Full authored occurrence accounting is distinct from decoder accuracy.

Existing typed builders, relational preparation and pair comparison execute only
inside the root's native qualification. No model, statutory payload, authenticated
target, product replacement namespace or alternate logic implementation is used.
"""
from __future__ import annotations

import builtins
from copy import deepcopy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch

import pytest

from ipfs_datasets_py.logic.autoformal import legal_relational_norm_v1 as relational
from ipfs_datasets_py.logic.autoformal import legal_relational_reconstruction_v1 as paired
from ipfs_datasets_py.logic.autoformal import legal_relational_batch_evaluation_v1 as owner


def _load_fixture():
    path = Path(__file__).with_name("test_legal_relational_reconstruction_v1.py")
    name = "_relational_batch_authored_reconstruction_fixtures"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_FIXTURE = _load_fixture()


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def transport(value):
    return json.dumps(value, sort_keys=True, indent=2,
                      ensure_ascii=False, allow_nan=False).encode("utf-8") + b"\n"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def digest(value):
    return sha(wire(value))


def generation(population_sha256, **changes):
    return {
        "kind": "authored_control", "population_sha256": population_sha256,
        "latent_dimension": None, "checkpoint_sha256": None, "encoder_sha256": None,
        "settings_sha256": sha(b"authored settings; no decoder execution"),
        "teacher_forcing": False, "target_access": False, **changes,
    }


def decoded(row, request, **changes):
    raw = wire(request) if type(request) is dict else request
    assert type(raw) is bytes
    return {
        **row, "status": "decoded", "teacher_forcing": False, "target_access": False,
        "request_utf8": raw.decode("utf-8"), "request_sha256": sha(raw), "reason": None,
        **changes,
    }


def withheld(row, status="abstained", **changes):
    return {
        **row, "status": status, "teacher_forcing": False, "target_access": False,
        "request_utf8": None, "request_sha256": None,
        "reason": "Explicit authored control disposition", **changes,
    }


def case_for(ids, request, *, unavailable=(), repeated_source=False):
    population = {
        "schema": "legal-relational-batch-population/v1", "partition": "authored-controls",
        "selection_sha256": sha(b"complete hand-authored occurrence selection"),
        "rows": [{
            "id": identity,
            "source_sha256": sha(("source:shared" if repeated_source else "source:" + identity).encode()),
            "context_sha256": sha(("context:shared" if repeated_source else "context:" + identity).encode()),
        } for identity in ids],
    }
    # The independent population pin commits original transport, including LF.
    population_raw = transport(population)
    population_pin = sha(population_raw)
    request_raw = wire(request)
    report = relational.prepare_relational_norm_v1(request_raw,
        expected_request_sha256=sha(request_raw))
    references = {
        "schema": "legal-relational-batch-references/v1", "population_sha256": population_pin,
        "rows": [{
            "id": identity, "status": "unavailable" if identity in unavailable else "available",
            "request_utf8": None if identity in unavailable else request_raw.decode(),
            "request_sha256": None if identity in unavailable else sha(request_raw),
            "report": None if identity in unavailable else deepcopy(report),
            "report_sha256": None if identity in unavailable else digest(report),
            "reason": "No authored reference supplied" if identity in unavailable else None,
        } for identity in ids],
    }
    predictions = {
        "schema": "legal-relational-batch-predictions/v1",
        "generation": generation(population_pin),
        "rows": [decoded(row, request_raw) for row in population["rows"]],
    }
    return {"population": population, "references": references, "predictions": predictions,
            "population_raw": population_raw, "request": request}


def originals(case):
    raw = (case["population_raw"], transport(case["references"]), transport(case["predictions"]))
    return raw, {
        "expected_population_sha256": sha(raw[0]), "expected_references_sha256": sha(raw[1]),
        "expected_predictions_sha256": sha(raw[2]),
    }


def prepare(case, **overrides):
    raw, pins = originals(case)
    return owner.prepare_relational_batch_evaluation_v1(*raw, **{**pins, **overrides})


def validate(case, report, **overrides):
    raw, pins = originals(case)
    return owner.validate_relational_batch_evaluation_v1(
        report, *raw, expected_evaluation_sha256=digest(report), **{**pins, **overrides},
    )


@pytest.fixture(scope="module")
def base_request():
    return _FIXTURE._FIXTURE.approval_request()


@pytest.fixture(scope="module")
def one_case(base_request):
    return case_for(["occurrence:one"], base_request)


@pytest.fixture(scope="module")
def mixed_case(base_request):
    ids = ["missing", "duplicate", "malformed", "unverifiable", "abstained",
           "unsupported", "invalid", "without-reference", "compared"]
    case = case_for(ids, base_request, unavailable={"without-reference"})
    by_id = {row["id"]: row for row in case["population"]["rows"]}
    duplicate = decoded(by_id["duplicate"], base_request)
    malformed = decoded(by_id["malformed"], base_request)
    malformed["unknown"] = "not a closed prediction row"
    case["predictions"]["rows"] = [
        duplicate, deepcopy(duplicate), malformed,
        decoded(by_id["unverifiable"], base_request, target_access=True),
        withheld(by_id["abstained"]), withheld(by_id["unsupported"], "unsupported"),
        decoded(by_id["invalid"], b"{"),
        decoded(by_id["without-reference"], base_request),
        decoded(by_id["compared"], _FIXTURE._FIXTURE.approval_request(inner=True)),
        decoded({"id": "unexpected", "source_sha256": sha(b"extra source"),
                 "context_sha256": sha(b"extra context")}, base_request),
        "unidentifiable authored prediction observation",
    ]
    return case


TERMINAL_STATUSES = {
    "missing", "duplicate", "malformed", "unverifiable_generation", "abstained",
    "unsupported", "invalid_typed_output", "valid_without_reference", "compared",
}
COMPARISONS = {
    "exact_typed_expression_equal", "family_profile_equal", "signature_declarations_equal",
    "argument_roles_equal", "declared_structure_equal", "lexical_alpha_structure_equal",
}


def assert_unreviewed(report):
    assert set(report) == {
        "schema", "profile", "status", "inputs", "population", "reference_availability",
        "coverage", "observation_ledger", "occurrences", "terminal_counts", "valid_typed_output",
        "full_selected_structure_diagnostics", "comparable_pair_structure_diagnostics",
        "generation", "generation_issues", "producer_pins", "authority", "training_mask",
        "evaluation_gold_mask", "generation_claims_are_declarations_only", "metric_reference_access",
        "limitations",
    }
    assert report["schema"] == "legal-relational-batch-evaluation/v1"
    assert report["profile"] == "full-selected-authored-relational-output-diagnostics/v1"
    assert report["status"] == "full_selected_unreviewed_relational_batch_evaluated"
    assert report["generation_claims_are_declarations_only"] is True
    assert report["metric_reference_access"] is True
    assert report["authority"] and all(value is False for value in report["authority"].values())
    for flag in ("numerical_execution_authenticated", "latent_only_verified", "decoder_accuracy_established",
                 "reviewed_targets_verified", "partition_membership_verified", "source_commitments_verified"):
        assert report["authority"][flag] is False
    assert type(report["training_mask"]) is int and report["training_mask"] == 0
    assert type(report["evaluation_gold_mask"]) is int and report["evaluation_gold_mask"] == 0
    assert set(report["terminal_counts"]) == TERMINAL_STATUSES
    assert sum(report["terminal_counts"].values()) == len(report["occurrences"])
    assert set(report["full_selected_structure_diagnostics"]) == COMPARISONS
    assert set(report["comparable_pair_structure_diagnostics"]) == COMPARISONS
    assert owner.relational_batch_evaluation_sha256(report) == digest(report)


def assert_metric(cell, matched, total):
    assert set(cell) == {"matched", "total", "fraction"}
    assert cell["matched"] == matched and cell["total"] == total
    assert cell["fraction"] == (None if total == 0 else matched / total)


def assert_original_commitments(case, report):
    raw, _ = originals(case)
    assert report["inputs"] == {
        name: {"sha256": sha(value), "bytes": len(value)}
        for name, value in zip(("population", "references", "predictions"), raw, strict=True)
    }
    assert report["population"] == {
        "population_sha256": sha(raw[0]), "partition": case["population"]["partition"],
        "selection_sha256": case["population"]["selection_sha256"],
        "ordered_ids": [row["id"] for row in case["population"]["rows"]],
    }
    assert [row["id"] for row in report["occurrences"]] == [row["id"] for row in case["population"]["rows"]]
    assert [row["index"] for row in report["occurrences"]] == list(range(len(case["population"]["rows"])))
    for occurrence, population_row, reference in zip(
            report["occurrences"], case["population"]["rows"], case["references"]["rows"], strict=True):
        assert set(occurrence) == {"index", "id", "source_sha256", "context_sha256", "reference",
                                   "observation_indices", "declared_status", "status", "reasons", "pair_diagnostic"}
        assert occurrence["source_sha256"] == population_row["source_sha256"]
        assert occurrence["context_sha256"] == population_row["context_sha256"]
        assert occurrence["reference"] == {key: reference[key] for key in
                                            ("status", "request_sha256", "report_sha256", "reason")}
    assert len(report["observation_ledger"]) == len(case["predictions"]["rows"])
    for index, (observed, original) in enumerate(zip(
            report["observation_ledger"], case["predictions"]["rows"], strict=True)):
        assert set(observed) == {"index", "id", "sha256", "associated_population_index", "declared_status",
                                "shape_valid", "shape_reasons", "provenance_valid", "provenance_reasons", "outcome"}
        assert observed["index"] == index and observed["sha256"] == digest(original)


def test_mixed_population_accounts_every_terminal_outcome_and_every_submitted_row(mixed_case):
    before = deepcopy(mixed_case)
    report = prepare(mixed_case)
    assert_unreviewed(report)
    assert_original_commitments(mixed_case, report)
    assert report["terminal_counts"] == {status: 1 for status in TERMINAL_STATUSES}
    assert [row["status"] for row in report["occurrences"]] == [
        "missing", "duplicate", "malformed", "unverifiable_generation", "abstained",
        "unsupported", "invalid_typed_output", "valid_without_reference", "compared",
    ]
    assert report["coverage"] == {
        "valid": False, "expected_count": 9, "prediction_row_count": 11,
        "missing_ids": ["missing"], "duplicate_ids": {"duplicate": [0, 1]},
        "unexpected_ids": {"unexpected": [9]}, "unidentifiable_indices": [10],
    }
    assert report["reference_availability"] == {"available": 8, "unavailable": 1, "total": 9, "fraction": 8 / 9}
    assert report["valid_typed_output"] == {"count": 2, "total": 9, "fraction": 2 / 9}
    for key in COMPARISONS:
        matched = int(key in {"family_profile_equal", "signature_declarations_equal", "argument_roles_equal"})
        assert_metric(report["full_selected_structure_diagnostics"][key], matched, 9)
        assert_metric(report["comparable_pair_structure_diagnostics"][key], matched, 1)
    assert report["occurrences"][7]["pair_diagnostic"] is None
    pair = report["occurrences"][8]["pair_diagnostic"]
    assert pair is not None and set(pair["comparisons"]) == COMPARISONS
    assert len(pair["comparison_sha256"]) == 64
    assert validate(mixed_case, report) == report
    assert mixed_case == before


@pytest.mark.parametrize("kind", ["missing", "abstained", "unsupported", "invalid"],
                         ids=["all-missing", "all-abstained", "all-unsupported", "all-invalid"])
def test_zero_comparable_pairs_never_produce_optimistic_conditional_agreement(base_request, kind):
    case = case_for(["one", "two", "three"], base_request)
    if kind == "missing":
        case["predictions"]["rows"] = []
    elif kind == "invalid":
        case["predictions"]["rows"] = [decoded(row, b"{") for row in case["population"]["rows"]]
    else:
        case["predictions"]["rows"] = [withheld(row, kind) for row in case["population"]["rows"]]
    report = prepare(case)
    assert_unreviewed(report)
    terminal = "invalid_typed_output" if kind == "invalid" else kind
    assert report["terminal_counts"][terminal] == 3
    assert report["valid_typed_output"] == {"count": 0, "total": 3, "fraction": 0}
    assert report["coverage"]["valid"] is (kind != "missing")
    for key in COMPARISONS:
        assert_metric(report["full_selected_structure_diagnostics"][key], 0, 3)
        assert_metric(report["comparable_pair_structure_diagnostics"][key], 0, 0)


def test_valid_candidates_without_references_remain_visible_and_are_lowered(base_request):
    case = case_for(["one", "two"], base_request, unavailable={"one", "two"})
    report = prepare(case)
    assert_unreviewed(report)
    assert_original_commitments(case, report)
    assert report["coverage"]["valid"] is True
    assert report["terminal_counts"]["valid_without_reference"] == 2
    assert report["reference_availability"] == {"available": 0, "unavailable": 2, "total": 2, "fraction": 0}
    assert report["valid_typed_output"] == {"count": 2, "total": 2, "fraction": 1}
    assert all(row["pair_diagnostic"] is None for row in report["occurrences"])
    for key in COMPARISONS:
        assert_metric(report["full_selected_structure_diagnostics"][key], 0, 2)
        assert_metric(report["comparable_pair_structure_diagnostics"][key], 0, 0)
    changed = deepcopy(case)
    changed["predictions"]["rows"][0] = decoded(case["population"]["rows"][0], b"{")
    other = prepare(changed)
    assert other["terminal_counts"]["invalid_typed_output"] == 1
    assert other["valid_typed_output"]["count"] == 1


@pytest.mark.parametrize("order", ["original", "reverse"], ids=["arrival-order", "reversed-arrival"])
def test_identical_source_commitments_do_not_merge_distinct_physical_occurrence_ids(base_request, order):
    case = case_for(["physical:first", "physical:second"], base_request, repeated_source=True)
    case["predictions"]["rows"][1] = decoded(case["population"]["rows"][1],
        _FIXTURE._FIXTURE.approval_request(inner=True))
    if order == "reverse":
        case["predictions"]["rows"].reverse()
    report = prepare(case)
    assert_unreviewed(report)
    assert_original_commitments(case, report)
    assert report["coverage"]["valid"] is True
    assert report["terminal_counts"]["compared"] == 2
    assert_metric(report["full_selected_structure_diagnostics"]["lexical_alpha_structure_equal"], 1, 2)
    assert [row["observation_indices"] for row in report["occurrences"]] == ([[0], [1]] if order == "original" else [[1], [0]])


@pytest.mark.parametrize("kind", ["identical", "favorable-first", "favorable-last", "malformed-first"],
                         ids=["identical-duplicates", "matching-first", "matching-last", "malformed-first"])
def test_duplicate_ids_never_select_a_favorable_candidate(one_case, kind):
    case = deepcopy(one_case)
    good = deepcopy(case["predictions"]["rows"][0])
    wrong = decoded(case["population"]["rows"][0], _FIXTURE._FIXTURE.approval_request(inner=True))
    if kind == "identical":
        rows = [good, deepcopy(good)]
    elif kind == "favorable-first":
        rows = [good, wrong]
    elif kind == "favorable-last":
        rows = [wrong, good]
    else:
        rows = [{"id": good["id"], "unknown": True}, good]
    case["predictions"]["rows"] = rows
    report = prepare(case)
    assert_unreviewed(report)
    assert_original_commitments(case, report)
    assert report["terminal_counts"]["duplicate"] == 1
    assert report["coverage"]["duplicate_ids"] == {good["id"]: [0, 1]}
    assert report["occurrences"][0]["observation_indices"] == [0, 1]
    assert report["occurrences"][0]["pair_diagnostic"] is None
    assert report["valid_typed_output"]["count"] == 0
    for key in COMPARISONS:
        assert_metric(report["full_selected_structure_diagnostics"][key], 0, 1)
        assert_metric(report["comparable_pair_structure_diagnostics"][key], 0, 0)


@pytest.mark.parametrize("observation", ["unknown-id", "scalar", "null-id", "blank-id"],
                         ids=["unknown-id", "scalar-observation", "null-id", "blank-id"])
def test_unknown_and_unidentifiable_observations_cannot_supply_a_missing_occurrence(one_case, observation):
    case = deepcopy(one_case)
    row = deepcopy(case["predictions"]["rows"][0])
    if observation == "scalar":
        row = 7
    else:
        row["id"] = {"unknown-id": "not-in-population", "null-id": None, "blank-id": " "}[observation]
    case["predictions"]["rows"] = [row]
    report = prepare(case)
    assert_unreviewed(report)
    assert_original_commitments(case, report)
    assert report["terminal_counts"]["missing"] == 1
    assert report["coverage"]["expected_count"] == 1 and report["coverage"]["prediction_row_count"] == 1
    assert report["coverage"]["valid"] is False
    assert report["valid_typed_output"]["count"] == 0
    if observation == "unknown-id":
        assert report["coverage"]["unexpected_ids"] == {"not-in-population": [0]}
    else:
        assert report["coverage"]["unidentifiable_indices"] == [0]


def test_repeated_unexpected_id_keeps_all_indices_without_changing_expected_denominator(one_case):
    case = deepcopy(one_case)
    extra = deepcopy(case["predictions"]["rows"][0])
    extra["id"] = "unexpected:repeated"
    case["predictions"]["rows"].extend([extra, deepcopy(extra)])
    report = prepare(case)
    assert_unreviewed(report)
    assert_original_commitments(case, report)
    assert report["coverage"]["valid"] is False
    assert report["coverage"]["duplicate_ids"] == {}
    assert report["coverage"]["unexpected_ids"] == {"unexpected:repeated": [1, 2]}
    assert report["coverage"]["expected_count"] == 1 and report["coverage"]["prediction_row_count"] == 3
    assert report["terminal_counts"]["compared"] == 1
    assert [row["outcome"] for row in report["observation_ledger"]][1:] == ["unexpected", "unexpected"]
    for key in COMPARISONS:
        assert_metric(report["full_selected_structure_diagnostics"][key], 1, 1)


def test_real_public_pair_controls_separate_exact_declared_and_alpha_agreement(base_request):
    ids = ["self", "new-ids", "alpha", "modal-change"]
    case = case_for(ids, base_request)
    candidates = [
        base_request, _FIXTURE.change_artifact_ids(base_request),
        _FIXTURE.rename_bound_variables(base_request, {"actor": "person", "recipient": "beneficiary", "approver": "official"}),
        _FIXTURE._FIXTURE.approval_request(inner=True),
    ]
    case["predictions"]["rows"] = [decoded(row, request) for row, request in
                                      zip(case["population"]["rows"], candidates, strict=True)]
    report = prepare(case)
    assert_unreviewed(report)
    assert_original_commitments(case, report)
    assert report["terminal_counts"]["compared"] == 4
    assert report["valid_typed_output"] == {"count": 4, "total": 4, "fraction": 1}
    expected = {"exact_typed_expression_equal": 1, "declared_structure_equal": 2,
                "lexical_alpha_structure_equal": 3, "family_profile_equal": 4,
                "signature_declarations_equal": 4, "argument_roles_equal": 4}
    for key, count in expected.items():
        assert_metric(report["full_selected_structure_diagnostics"][key], count, 4)
        assert_metric(report["comparable_pair_structure_diagnostics"][key], count, 4)
    for occurrence in report["occurrences"]:
        pair = occurrence["pair_diagnostic"]
        assert set(pair) == {"comparison_sha256", "comparisons", "feature_counts",
                             "reference_only_paths", "candidate_only_paths"}
        counts = pair["feature_counts"]
        assert counts["total"] == counts["shared"] + counts["reference_only"] + counts["candidate_only"]
        assert counts["reference_only"] == len(pair["reference_only_paths"])
        assert counts["candidate_only"] == len(pair["candidate_only_paths"])
    assert validate(case, report) == report


@pytest.mark.parametrize("dimension", [8, 384, 768], ids=["latent-8", "latent-384", "latent-768"])
def test_decoder_generation_declarations_do_not_authenticate_model_execution(one_case, dimension):
    case = deepcopy(one_case)
    declaration = case["predictions"]["generation"]
    declaration.update(kind="decoder_declared", latent_dimension=dimension,
                       checkpoint_sha256=sha(b"declared checkpoint"), encoder_sha256=sha(b"declared encoder"))
    report = prepare(case)
    assert_unreviewed(report)
    assert report["generation_issues"] == []
    assert report["generation"] == {
        "present": True, "declaration_sha256": digest(declaration), "kind": "decoder_declared",
        "latent_dimension": dimension, "checkpoint_sha256": declaration["checkpoint_sha256"],
        "encoder_sha256": declaration["encoder_sha256"], "settings_sha256": declaration["settings_sha256"],
        "valid": True,
    }
    assert report["terminal_counts"]["compared"] == 1
    assert report["authority"]["numerical_execution_authenticated"] is False
    assert report["authority"]["latent_only_verified"] is False


@pytest.mark.parametrize("mutation,code", [
    ("missing", "generation_missing"), ("scalar", "generation_not_object"),
    ("fields", "generation_fields_mismatch"), ("kind", "generation_kind_invalid"),
    ("population", "generation_population_mismatch"), ("settings", "generation_settings_sha256_invalid"),
    ("teacher", "generation_teacher_forcing_not_false"), ("target", "generation_target_access_not_false"),
    ("dimension", "generation_decoder_dimension_invalid"), ("checkpoint", "generation_decoder_checkpoint_invalid"),
    ("encoder", "generation_decoder_encoder_invalid"), ("authored-binding", "generation_authored_binding_nonnull"),
], ids=["missing-declaration", "scalar-declaration", "extra-generation-field", "unknown-kind",
        "wrong-population", "invalid-settings", "teacher-forcing", "target-access", "invalid-dimension",
        "missing-checkpoint", "missing-encoder", "authored-with-model-binding"])
def test_bad_generation_preserves_rows_and_withholds_comparable_credit(one_case, mutation, code):
    case = deepcopy(one_case)
    declaration = case["predictions"]["generation"]
    if mutation == "missing":
        case["predictions"].pop("generation")
    elif mutation == "scalar":
        case["predictions"]["generation"] = "unverifiable generation declaration"
    elif mutation == "fields":
        declaration["unknown"] = True
    elif mutation == "kind":
        declaration["kind"] = "authenticated_decoder"
    elif mutation == "population":
        declaration["population_sha256"] = sha(b"other population")
    elif mutation == "settings":
        declaration["settings_sha256"] = "not-a-sha"
    elif mutation == "teacher":
        declaration["teacher_forcing"] = True
    elif mutation == "target":
        declaration["target_access"] = True
    elif mutation == "authored-binding":
        declaration["latent_dimension"] = 8
    else:
        declaration.update(kind="decoder_declared", latent_dimension=384,
            checkpoint_sha256=sha(b"checkpoint"), encoder_sha256=sha(b"encoder"))
        declaration[{"dimension": "latent_dimension", "checkpoint": "checkpoint_sha256", "encoder": "encoder_sha256"}[mutation]] = None
    report = prepare(case)
    assert_unreviewed(report)
    assert_original_commitments(case, report)
    assert code in report["generation_issues"] and report["generation"]["valid"] is False
    assert report["coverage"]["valid"] is True
    assert report["terminal_counts"]["unverifiable_generation"] == 1
    assert report["valid_typed_output"]["count"] == 0
    assert report["occurrences"][0]["pair_diagnostic"] is None
    for key in COMPARISONS:
        assert_metric(report["full_selected_structure_diagnostics"][key], 0, 1)


@pytest.mark.parametrize("status", ["decoded", "abstained"], ids=["decoded-provenance", "abstention-provenance"])
@pytest.mark.parametrize("mutation", ["source", "context", "teacher", "target", "boolean-zero"],
                         ids=["source-mismatch", "context-mismatch", "teacher-forcing", "target-access", "zero-is-not-false"])
def test_row_provenance_contradictions_withhold_credit_and_retain_declared_status(one_case, status, mutation):
    case = deepcopy(one_case)
    row = case["predictions"]["rows"][0] if status == "decoded" else withheld(case["population"]["rows"][0])
    if mutation in {"source", "context"}:
        row[mutation + "_sha256"] = sha(b"different declared provenance")
    else:
        row["teacher_forcing" if mutation == "teacher" else "target_access"] = 0 if mutation == "boolean-zero" else True
    case["predictions"]["rows"] = [row]
    report = prepare(case)
    assert_unreviewed(report)
    assert report["coverage"]["valid"] is True
    occurrence = report["occurrences"][0]
    assert occurrence["declared_status"] == status
    assert occurrence["status"] == "unverifiable_generation" and occurrence["reasons"]
    ledger = report["observation_ledger"][0]
    assert ledger["shape_valid"] is True and ledger["provenance_valid"] is False and ledger["provenance_reasons"]
    assert occurrence["pair_diagnostic"] is None


@pytest.mark.parametrize("mutation", ["unknown-field", "missing-field", "unknown-status", "decoded-reason", "abstention-payload", "unsupported-no-reason", "candidate-pin"],
                         ids=["unknown-row-field", "missing-row-field", "unknown-status", "decoded-with-reason",
                              "abstention-with-payload", "unsupported-without-reason", "candidate-pin-mismatch"])
def test_malformed_candidate_rows_are_accounted_without_poisoning_outer_transport(one_case, mutation):
    case = deepcopy(one_case)
    row = case["predictions"]["rows"][0]
    if mutation == "unknown-field":
        row["extra"] = True
    elif mutation == "missing-field":
        row.pop("request_sha256")
    elif mutation == "unknown-status":
        row["status"] = "accepted"
    elif mutation == "decoded-reason":
        row["reason"] = "Contradictory decoded reason"
    elif mutation == "abstention-payload":
        row["status"] = "abstained"
        row["reason"] = "Contradictory payload-bearing abstention"
    elif mutation == "unsupported-no-reason":
        row = withheld(case["population"]["rows"][0], "unsupported", reason=None)
        case["predictions"]["rows"] = [row]
    else:
        row["request_sha256"] = sha(b"different generated request bytes")
    report = prepare(case)
    assert_unreviewed(report)
    assert_original_commitments(case, report)
    assert report["terminal_counts"]["malformed"] == 1 and report["coverage"]["valid"] is True
    assert report["valid_typed_output"]["count"] == 0
    if mutation == "candidate-pin":
        assert "candidate_request_sha256_mismatch" in report["occurrences"][0]["reasons"]


@pytest.mark.parametrize("mutation", ["invalid-json", "duplicate-key", "nonfinite", "wrong-schema", "source-binding", "free-variable"],
                         ids=["invalid-candidate-json", "duplicate-candidate-key", "candidate-nan", "unsupported-schema",
                              "unsupported-source-binding", "unbound-variable"])
def test_malformed_json_and_unsupported_fragments_are_terminal_candidate_failures(one_case, mutation):
    case = deepcopy(one_case)
    request = deepcopy(case["request"])
    if mutation == "invalid-json":
        raw = b"{"
    elif mutation == "duplicate-key":
        raw = b'{"schema":"duplicate",' + wire(request)[1:]
    elif mutation == "nonfinite":
        raw = b'{"value":NaN}'
    else:
        if mutation == "wrong-schema":
            request["schema"] = "unsupported-request/v1"
        elif mutation == "source-binding":
            request["source_binding"] = {"caller_grounding_claim": True}
        else:
            implication = request["expression"]["root"]["arguments"][0]["arguments"][0]["arguments"][0]
            implication["arguments"][0]["extension"]["children"][0]["arguments"][0]["arguments"][0]["symbol"] = "unbound_person"
            request = _FIXTURE._FIXTURE.reseal_expression(request)
        raw = wire(request)
    case["predictions"]["rows"] = [decoded(case["population"]["rows"][0], raw)]
    report = prepare(case)
    assert_unreviewed(report)
    assert report["terminal_counts"]["invalid_typed_output"] == 1
    assert report["coverage"]["valid"] is True and report["valid_typed_output"]["count"] == 0


def test_oversized_candidate_request_is_accounted_without_calling_relational_lowering(one_case):
    case = deepcopy(one_case)
    raw = b" " * (524288 + 1)
    case["predictions"]["rows"] = [decoded(case["population"]["rows"][0], raw)]
    original = relational.prepare_relational_norm_v1
    def bounded_prepare(candidate_raw, **kwargs):
        if len(candidate_raw) > 524288:
            raise AssertionError("overbound candidate reached operation lowering")
        return original(candidate_raw, **kwargs)
    with patch.object(relational, "prepare_relational_norm_v1", bounded_prepare):
        report = prepare(case)
    assert_unreviewed(report)
    assert report["terminal_counts"]["invalid_typed_output"] == 1
    assert "candidate_request_bound_exceeded" in report["occurrences"][0]["reasons"]


def test_precedence_preserves_missing_duplicate_and_shape_facts_when_generation_is_bad(mixed_case):
    case = deepcopy(mixed_case)
    case["predictions"]["generation"]["teacher_forcing"] = True
    report = prepare(case)
    assert_unreviewed(report)
    assert_original_commitments(case, report)
    assert report["terminal_counts"]["missing"] == 1
    assert report["terminal_counts"]["duplicate"] == 1
    assert report["terminal_counts"]["malformed"] == 1
    assert report["terminal_counts"]["unverifiable_generation"] == 6
    assert "generation_teacher_forcing_not_false" in report["generation_issues"]
    assert report["observation_ledger"][2]["shape_valid"] is False
    assert report["coverage"]["missing_ids"] == ["missing"]
    assert report["coverage"]["duplicate_ids"] == {"duplicate": [0, 1]}
    assert report["valid_typed_output"]["count"] == 0


@pytest.mark.parametrize("predictions", ["missing", "abstained", "duplicate", "bad-generation"],
                         ids=["invalid-reference-missing-output", "invalid-reference-abstention",
                              "invalid-reference-duplicate-output", "invalid-reference-bad-generation"])
def test_every_available_reference_is_validated_even_without_comparable_prediction(one_case, predictions):
    case = deepcopy(one_case)
    reference = case["references"]["rows"][0]
    reference["report"]["counts"]["nodes"] -= 1
    reference["report_sha256"] = digest(reference["report"])
    if predictions == "missing":
        case["predictions"]["rows"] = []
    elif predictions == "abstained":
        case["predictions"]["rows"] = [withheld(case["population"]["rows"][0])]
    elif predictions == "duplicate":
        case["predictions"]["rows"] *= 2
    else:
        case["predictions"]["generation"]["target_access"] = True
    with pytest.raises(ValueError):
        prepare(case)


@pytest.mark.parametrize("mutation", ["drop", "duplicate", "unknown", "reorder", "population-pin", "unavailable-payload"],
                         ids=["missing-reference-row", "duplicate-reference-row", "unknown-reference-id",
                              "reordered-reference-rows", "wrong-reference-population", "unavailable-with-payload"])
def test_reference_envelope_cannot_drop_or_retarget_the_population(base_request, mutation):
    case = case_for(["one", "two"], base_request)
    references = case["references"]
    if mutation == "drop":
        references["rows"].pop()
    elif mutation == "duplicate":
        references["rows"][1] = deepcopy(references["rows"][0])
    elif mutation == "unknown":
        references["rows"][1]["id"] = "outside-population"
    elif mutation == "reorder":
        references["rows"].reverse()
    elif mutation == "population-pin":
        references["population_sha256"] = sha(b"another population")
    else:
        references["rows"][0]["status"] = "unavailable"
        references["rows"][0]["reason"] = "Payload fields were not cleared"
    with pytest.raises(ValueError):
        prepare(case)


@pytest.mark.parametrize("pin", ["expected_population_sha256", "expected_references_sha256", "expected_predictions_sha256"],
                         ids=["population-transport-pin", "references-transport-pin", "predictions-transport-pin"])
def test_three_independent_transport_pins_refuse_before_lazy_owners(one_case, pin):
    with patch.object(owner, "_owners", side_effect=AssertionError("operation owner reached")) as operation:
        with pytest.raises(ValueError):
            prepare(one_case, **{pin: sha(b"different original transport")})
        operation.assert_not_called()


@pytest.mark.parametrize("mutation", ["duplicate-key", "nonfinite", "invalid-utf8", "mutable-bytes", "unknown-envelope", "rows-not-list", "population-empty", "population-duplicate", "population-bound", "observation-bound"],
                         ids=["duplicate-outer-key", "outer-nonfinite", "outer-invalid-utf8", "mutable-transport",
                              "unknown-prediction-envelope-field", "nonlist-observations", "empty-population",
                              "duplicate-population-id", "population-over-64", "observations-over-256"])
def test_whole_transport_and_population_intake_failures_refuse_before_operation_imports(one_case, mutation):
    case = deepcopy(one_case)
    raw, pins = originals(case)
    raw = list(raw)
    if mutation == "duplicate-key":
        raw[2] = b'{"schema":"duplicate",' + raw[2][1:]
    elif mutation == "nonfinite":
        raw[2] = b'{"schema":NaN}'
    elif mutation == "invalid-utf8":
        raw[2] = b"\xff"
    elif mutation == "mutable-bytes":
        raw[2] = bytearray(raw[2])
    elif mutation == "unknown-envelope":
        case["predictions"]["unknown"] = True
        raw[2] = transport(case["predictions"])
    elif mutation == "rows-not-list":
        case["predictions"]["rows"] = {}
        raw[2] = transport(case["predictions"])
    elif mutation in {"population-empty", "population-duplicate", "population-bound"}:
        if mutation == "population-empty":
            case["population"]["rows"] = []
        elif mutation == "population-duplicate":
            case["population"]["rows"] *= 2
        else:
            original = case["population"]["rows"][0]
            case["population"]["rows"] = [{**original, "id": "bounded:" + str(i)} for i in range(65)]
        raw[0] = transport(case["population"])
    else:
        case["predictions"]["rows"] = [None] * 257
        raw[2] = transport(case["predictions"])
    pins = dict(zip(("expected_population_sha256", "expected_references_sha256", "expected_predictions_sha256"),
                    (sha(value) for value in raw), strict=True))
    with patch.object(owner, "_owners", side_effect=AssertionError("operation owner reached")) as operation:
        with pytest.raises(ValueError):
            owner.prepare_relational_batch_evaluation_v1(*raw, **pins)
        operation.assert_not_called()


@pytest.mark.parametrize("which", ["population", "references", "predictions"],
                         ids=["population-byte-ceiling", "references-byte-ceiling", "predictions-byte-ceiling"])
def test_outer_transport_byte_ceiling_refuses_without_clipping(one_case, which):
    raw, _ = originals(one_case)
    raw = list(raw)
    index = {"population": 0, "references": 1, "predictions": 2}[which]
    maximum = 128 * 1024 if which == "population" else 16 * 1024 * 1024
    raw[index] += b" " * (maximum + 1 - len(raw[index]))
    pins = dict(zip(("expected_population_sha256", "expected_references_sha256", "expected_predictions_sha256"),
                    (sha(value) for value in raw), strict=True))
    with patch.object(owner, "_owners", side_effect=AssertionError("operation owner reached")) as operation:
        with pytest.raises(ValueError):
            owner.prepare_relational_batch_evaluation_v1(*raw, **pins)
        operation.assert_not_called()


@pytest.mark.parametrize("which", ["request", "report", "depth"],
                         ids=["reference-request-bound", "reference-report-bound", "outer-json-depth-bound"])
def test_nested_reference_and_ordinary_json_bounds_refuse_before_lazy_owners(one_case, which):
    case = deepcopy(one_case)
    reference = case["references"]["rows"][0]
    if which == "request":
        reference["request_utf8"] = " " * (524288 + 1)
        reference["request_sha256"] = sha(reference["request_utf8"].encode())
    elif which == "report":
        reference["report"]["extra"] = "x" * (8 * 1024 * 1024 + 1)
        reference["report_sha256"] = digest(reference["report"])
    else:
        value = "leaf"
        for _ in range(97):
            value = [value]
        case["predictions"]["rows"] = [value]
    with patch.object(owner, "_owners", side_effect=AssertionError("operation owner reached")) as operation:
        with pytest.raises(ValueError):
            prepare(case)
        operation.assert_not_called()


@pytest.mark.parametrize("error_type", [OSError, ImportError, RuntimeError], ids=["os-error", "import-error", "runtime-error"])
def test_operational_candidate_failures_are_never_reported_as_invalid_model_output(one_case, error_type):
    case = deepcopy(one_case)
    candidate_request = _FIXTURE.change_artifact_ids(case["request"])
    candidate_raw = wire(candidate_request)
    case["predictions"]["rows"] = [decoded(case["population"]["rows"][0], candidate_raw)]
    original = relational.prepare_relational_norm_v1
    def operation(raw, **kwargs):
        if raw == candidate_raw:
            raise error_type("controlled operational failure")
        return original(raw, **kwargs)
    with patch.object(relational, "prepare_relational_norm_v1", operation):
        with pytest.raises(error_type):
            prepare(case)


def test_public_pair_replay_failure_refuses_instead_of_becoming_a_candidate_failure(one_case):
    with patch.object(paired, "prepare_relational_reconstruction_comparison_v1",
                      side_effect=ValueError("controlled public pair replay failure")):
        with pytest.raises(ValueError):
            prepare(one_case)


def test_source_fence_failure_refuses_instead_of_becoming_invalid_candidate_output(one_case):
    case = deepcopy(one_case)
    candidate_raw = wire(_FIXTURE.change_artifact_ids(case["request"]))
    case["predictions"]["rows"] = [decoded(case["population"]["rows"][0], candidate_raw)]
    original = relational.prepare_relational_norm_v1
    old_pin = owner._SELF_PIN
    def operation(raw, **kwargs):
        if raw == candidate_raw:
            owner._SELF_PIN = sha(b"controlled self source identity mismatch")
            raise ValueError("controlled candidate failure with changed source fence")
        return original(raw, **kwargs)
    with patch.object(owner, "_SELF_PIN", old_pin), patch.object(relational, "prepare_relational_norm_v1", operation):
        with pytest.raises(ValueError):
            prepare(case)
    assert owner._SELF_PIN == old_pin


@pytest.mark.parametrize("trusted_owner,field", [
    ("relational", "_SELF_PIN"), ("relational", "_OWNER_PINS"),
    ("paired", "_SELF_PIN"), ("paired", "_OPERATION_PINS"),
], ids=["first-use-relational-import-anchor", "first-use-relational-cache",
        "first-use-pair-import-anchor", "first-use-pair-cache"])
def test_first_use_owner_identity_failure_refuses_even_with_all_references_unavailable(
        base_request, trusted_owner, field):
    case = case_for(["unique-candidate"], base_request, unavailable={"unique-candidate"})
    trusted = relational if trusted_owner == "relational" else paired
    mismatch = sha(b"controlled stale fixed-owner identity")
    if field != "_SELF_PIN":
        existing = getattr(trusted, field)
        mismatch = deepcopy(existing) if type(existing) is dict and existing else {
            str(Path(trusted.__file__).resolve()): sha(b"controlled stale fixed-owner cache"),
        }
        mismatch[next(iter(mismatch))] = sha(b"controlled stale fixed-owner cache")
    with patch.object(owner, "_OPERATION_SNAPSHOTS", None), patch.object(trusted, field, mismatch), patch.object(
            relational, "prepare_relational_norm_v1", side_effect=AssertionError("candidate lowering reached")) as lowering:
        with pytest.raises(ValueError):
            prepare(case)
        lowering.assert_not_called()


def test_complete_report_ceiling_refuses_without_dropping_rows(one_case):
    report = prepare(one_case)
    before = deepcopy(one_case)
    with patch.object(owner, "MAX_OUTPUT_BYTES", len(wire(report)) - 1):
        with pytest.raises(ValueError):
            prepare(one_case)
    assert one_case == before
    assert validate(one_case, report) == report


@pytest.mark.parametrize("damage", ["drop-occurrence", "reorder-occurrences", "terminal-count", "denominator", "conditional-denominator", "observation-digest", "drop-observation", "generation-claim", "authority", "training-boolean", "gold-float", "pair-disagreement", "unknown-key"],
                         ids=["omitted-occurrence", "reordered-occurrences", "altered-terminal-count", "reduced-population-denominator",
                              "reduced-comparable-denominator", "altered-observation-digest", "omitted-observation",
                              "promoted-generation-claim", "promoted-authority", "boolean-mask", "float-mask",
                              "promoted-pair-disagreement", "unknown-output-field"])
def test_rehashed_batch_tampering_cannot_replace_complete_original_regeneration(mixed_case, damage):
    original = prepare(mixed_case)
    offered = deepcopy(original)
    if damage == "drop-occurrence":
        offered["occurrences"].pop()
    elif damage == "reorder-occurrences":
        offered["occurrences"].reverse()
    elif damage == "terminal-count":
        offered["terminal_counts"]["compared"] += 1
    elif damage == "denominator":
        offered["full_selected_structure_diagnostics"]["lexical_alpha_structure_equal"]["total"] = 1
    elif damage == "conditional-denominator":
        offered["comparable_pair_structure_diagnostics"]["lexical_alpha_structure_equal"]["total"] = 0
    elif damage == "observation-digest":
        offered["observation_ledger"][0]["sha256"] = sha(b"substituted observation")
    elif damage == "drop-observation":
        offered["observation_ledger"].pop()
    elif damage == "generation-claim":
        offered["generation_claims_are_declarations_only"] = False
    elif damage == "authority":
        offered["authority"]["decoder_accuracy_established"] = True
    elif damage == "training-boolean":
        offered["training_mask"] = False
    elif damage == "gold-float":
        offered["evaluation_gold_mask"] = 0.0
    elif damage == "pair-disagreement":
        offered["occurrences"][-1]["pair_diagnostic"]["comparisons"]["lexical_alpha_structure_equal"] = True
    else:
        offered["invented"] = "unknown output namespace"
    with pytest.raises(ValueError):
        validate(mixed_case, offered)


def test_wrong_independent_whole_report_pin_refuses_before_regeneration(one_case):
    report = prepare(one_case)
    raw, pins = originals(one_case)
    with patch.object(owner, "prepare_relational_batch_evaluation_v1",
                      side_effect=AssertionError("regeneration reached")) as regenerate:
        with pytest.raises(ValueError):
            owner.validate_relational_batch_evaluation_v1(report, *raw,
                expected_evaluation_sha256=sha(b"another complete report"), **pins)
        regenerate.assert_not_called()


def test_public_import_is_standard_library_only_and_writes_nothing(monkeypatch):
    name = "_relational_batch_cold_public_source"
    spec = importlib.util.spec_from_file_location(name, Path(owner.__file__))
    assert spec is not None and spec.loader is not None
    cold = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, cold)
    attempts = []
    forbidden = ("ipfs_datasets_py", "numpy", "pyarrow", "multiformats", "torch", "transformers", "symai", "tensorflow")
    original_import, original_open, original_os_open = builtins.__import__, builtins.open, os.open
    def checked_import(import_name, *args, **kwargs):
        if any(import_name == root or import_name.startswith(root + ".") for root in forbidden):
            attempts.append(import_name)
            raise AssertionError("operation owner imported during public import")
        return original_import(import_name, *args, **kwargs)
    def checked_open(file, mode="r", *args, **kwargs):
        if type(mode) is str and any(flag in mode for flag in "wax+"):
            attempts.append("file write")
            raise AssertionError("public import wrote a file")
        return original_open(file, mode, *args, **kwargs)
    def checked_os_open(file, flags, *args, **kwargs):
        if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
            attempts.append("descriptor write")
            raise AssertionError("public import wrote through os.open")
        return original_os_open(file, flags, *args, **kwargs)
    with patch.object(builtins, "__import__", checked_import), patch.object(builtins, "open", checked_open), patch.object(io, "open", checked_open), patch.object(os, "open", checked_os_open):
        spec.loader.exec_module(cold)
    assert attempts == []
    assert cold.SCHEMA == owner.SCHEMA and cold.PROFILE == owner.PROFILE
    assert all(hasattr(cold, symbol) for symbol in (
        "prepare_relational_batch_evaluation_v1", "validate_relational_batch_evaluation_v1",
        "relational_batch_evaluation_sha256",
    ))
