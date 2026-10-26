"""Authored raw-ID accounting; no model, real-law target or training execution."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import pytest

from ipfs_datasets_py.logic.autoformal import legal_relational_batch_evaluation_v1 as owner
from ipfs_datasets_py.logic.formalization.autoencoder import legal_relational_compact_codec_v1 as compact


def _fixtures():
    name = "_compact_batch_original_fixtures"
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name("test_legal_relational_batch_evaluation_v1.py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


legacy = _fixtures()
wire, sha, transport = legacy.wire, legacy.sha, legacy.transport


def byte_ids(raw):
    return [1, *(3 + value for value in raw), 2]


def generated(row, ids, **changes):
    return {**row, "status": "generated", "teacher_forcing": False, "target_access": False,
        "generated_ids": deepcopy(ids), "generated_ids_sha256": sha(wire(ids)), "reason": None, **changes}


def declared(row, status):
    return {**row, "status": status, "teacher_forcing": False, "target_access": False,
        "generated_ids": None, "generated_ids_sha256": None, "reason": "Explicit authored disposition"}


@pytest.fixture(scope="module")
def material():
    request = legacy._FIXTURE._FIXTURE.approval_request()
    codec = compact.build_relational_compact_codec_v1()
    codec_sha = compact.relational_compact_codec_sha256(codec)
    raw = wire(request)
    encoding = compact.encode_relational_compact_target_v1(raw, expected_request_sha256=sha(raw),
        codec=codec, expected_codec_sha256=codec_sha)
    return request, codec, codec_sha, encoding


def make_case(material, ids=("one",), *, unavailable=(), repeated_source=False):
    request, codec, codec_sha, encoding = material
    case = legacy.case_for(list(ids), request, unavailable=unavailable, repeated_source=repeated_source)
    case["predictions"] = {"schema": owner.COMPACT_PREDICTIONS_SCHEMA, "codec": deepcopy(codec),
        "codec_sha256": codec_sha, "generation": legacy.generation(sha(case["population_raw"])),
        "rows": [generated(row, encoding["target_ids"]) for row in case["population"]["rows"]]}
    return case


def prepare(case, **changes):
    raw, pins = legacy.originals(case)
    return owner.prepare_relational_compact_batch_evaluation_v1(*raw, **{**pins, **changes})


def validate(case, report):
    raw, pins = legacy.originals(case)
    return owner.validate_relational_compact_batch_evaluation_v1(report, *raw,
        expected_evaluation_sha256=sha(wire(report)), **pins)


def assert_no_authority(report):
    assert all(value is False for value in report["authority"].values())
    assert report["training_mask"] == report["evaluation_gold_mask"] == 0
    assert report["generation_claims_are_declarations_only"] is True
    assert report["declared_operational_statuses_are_unverified"] is True


def test_complete_mixed_population_retains_each_raw_observation_and_all_terminal_outcomes(material):
    statuses = list(owner.COMPACT_TERMINAL_STATUSES)
    case = make_case(material, statuses, unavailable={"valid_without_reference"})
    rows = {row["id"]: row for row in case["population"]["rows"]}
    bad_typed = json.loads(material[3]["compact_request_raw_utf8"])
    bad_typed["request"].pop(material[1]["key_map"]["expression"])
    observations = [
        generated(rows["duplicate"], byte_ids(b"\xff")), generated(rows["duplicate"], []),
        generated(rows["malformed"], byte_ids(b"\xff"), unexpected="retained"),
        generated(rows["unverifiable_generation"], [], target_access=True),
        generated(rows["invalid_typed_output"], byte_ids(wire(bad_typed))),
        generated(rows["valid_without_reference"], material[3]["target_ids"]),
        generated(rows["compared"], material[3]["target_ids"]),
        generated(rows["incomplete"], byte_ids(b"{}")[0:-1]),
        generated(rows["invalid_frame"], [1, 999, 2]),
        generated(rows["invalid_utf8"], byte_ids(b"\xff")),
        generated(rows["invalid_compact_output"], byte_ids(b"{}")),
        *[declared(rows[status], status) for status in
          ("abstained", "unsupported", "error", "timeout", "cancellation", "not_started")],
        generated({**rows["compared"], "id": "outside_population"}, byte_ids(b"\xff")),
        generated({key: value for key, value in rows["compared"].items() if key != "id"}, []),
        ["unidentifiable", True, 7],
    ]
    case["predictions"]["rows"] = observations
    before = deepcopy(case)
    report = prepare(case)
    assert case == before
    assert report["schema"] == owner.COMPACT_SCHEMA
    assert report["terminal_counts"] == {status: 1 for status in statuses}
    assert sum(report["terminal_counts"].values()) == len(statuses)
    assert report["population"]["ordered_ids"] == statuses
    assert report["coverage"]["prediction_row_count"] == len(observations)
    assert report["coverage"]["missing_ids"] == ["missing"]
    assert report["coverage"]["duplicate_ids"] == {"duplicate": [0, 1]}
    assert report["coverage"]["unexpected_ids"] == {"outside_population": [17]}
    assert report["coverage"]["unidentifiable_indices"] == [18, 19]
    assert report["coverage"]["valid"] is False
    assert [row["raw_observation"] for row in report["observation_ledger"]] == observations
    assert [row["outcome"] for row in report["observation_ledger"][-3:]] == [
        "unexpected", "unidentifiable", "unidentifiable"]
    first = report["observation_ledger"][0]["compact_decoding"]
    assert first["status"] == "rejected" and first["reason"] == "invalid_utf8"
    assert first["generated_transport_hex"] == "ff"
    assert first["generated_transport_utf8"] is None
    assert first["generated_transport_sha256"] == sha(b"\xff")
    assert report["observation_ledger"][1]["compact_decoding"]["status"] == "incomplete"
    assert report["valid_typed_output"] == {"count": 2, "total": len(statuses), "fraction": 2 / len(statuses)}
    for name in owner.COMPARISON_FIELDS:
        assert report["full_selected_structure_diagnostics"][name]["total"] == len(statuses)
        assert report["comparable_pair_structure_diagnostics"][name]["total"] == 1
    assert_no_authority(report)


def test_legacy_and_compact_calls_share_population_loop_without_changing_legacy_cache(material):
    old = legacy.case_for(["one"], material[0])
    before = legacy.prepare(old)
    core_snapshot = deepcopy(owner._OPERATION_SNAPSHOTS)
    new = prepare(make_case(material))
    assert owner._OPERATION_SNAPSHOTS == core_snapshot
    assert legacy.prepare(old) == before
    assert new["terminal_counts"]["compared"] == before["terminal_counts"]["compared"] == 1
    assert new["full_selected_structure_diagnostics"] == before["full_selected_structure_diagnostics"]
    assert set(new["producer_pins"]) > set(before["producer_pins"])
    for suffix in ("legal_relational_compact_codec_v1.py", "legal_relational_target_codec_v1.py", "syntax_core/codec.py"):
        assert any(path.endswith(suffix) for path in new["producer_pins"])


def test_shuffled_outputs_keep_exact_identity_and_same_source_rivals_are_not_substituted(material):
    case = make_case(material, ("A", "B"), repeated_source=True)
    rival = legacy._FIXTURE._FIXTURE.approval_request(inner=True)
    raw = wire(rival)
    encoding = compact.encode_relational_compact_target_v1(raw, expected_request_sha256=sha(raw),
        codec=material[1], expected_codec_sha256=material[2])
    case["predictions"]["rows"] = [generated(case["population"]["rows"][1], encoding["target_ids"]),
        generated(case["population"]["rows"][0], material[3]["target_ids"])]
    report = prepare(case)
    assert report["coverage"]["valid"] is True
    assert report["population"]["ordered_ids"] == ["A", "B"]
    assert [row["observation_indices"] for row in report["occurrences"]] == [[1], [0]]
    assert report["terminal_counts"]["compared"] == 2
    assert report["full_selected_structure_diagnostics"]["exact_typed_expression_equal"]["matched"] == 1
    assert report["full_selected_structure_diagnostics"]["declared_structure_equal"]["matched"] == 1
    assert report["occurrences"][1]["pair_diagnostic"]["comparisons"]["exact_typed_expression_equal"] is False
    assert_no_authority(report)


@pytest.mark.parametrize("ids", [[True], [1.0], [2 ** 40]])
def test_malformed_ids_are_retained_without_coercion_or_compact_dispatch(material, monkeypatch, ids):
    case = make_case(material)
    case["predictions"]["rows"][0] = generated(case["population"]["rows"][0], ids)
    monkeypatch.setattr(compact, "decode_relational_compact_candidate_v1",
        lambda *args, **kwargs: pytest.fail("malformed IDs were dispatched"))
    report = prepare(case)
    assert report["terminal_counts"]["malformed"] == 1
    assert report["observation_ledger"][0]["raw_observation"]["generated_ids"] == ids
    assert report["observation_ledger"][0]["compact_decoding"] is None


@pytest.mark.parametrize("mutation", ["ids_pin", "source", "context", "teacher", "target", "generation"])
def test_changed_identity_or_provenance_never_gains_comparison_credit(material, mutation):
    case = make_case(material)
    row = case["predictions"]["rows"][0]
    if mutation == "ids_pin": row["generated_ids_sha256"] = "0" * 64
    elif mutation in ("source", "context"): row[mutation + "_sha256"] = "0" * 64
    elif mutation == "generation": case["predictions"].pop("generation")
    else: row["teacher_forcing" if mutation == "teacher" else "target_access"] = True
    report = prepare(case)
    assert report["terminal_counts"]["malformed" if mutation == "ids_pin" else "unverifiable_generation"] == 1
    assert report["valid_typed_output"]["count"] == 0
    assert report["observation_ledger"][0]["raw_observation"] == row


@pytest.mark.parametrize("status", ["error", "timeout", "cancellation", "not_started", "unsupported", "abstained"])
def test_explicit_nonoutput_declarations_are_distinct_and_never_numerically_authenticated(material, status):
    case = make_case(material)
    case["predictions"]["rows"] = [declared(case["population"]["rows"][0], status)]
    report = prepare(case)
    assert report["terminal_counts"][status] == 1
    assert report["occurrences"][0]["reasons"] == ["declared_" + status]
    assert report["observation_ledger"][0]["compact_decoding"] is None
    assert_no_authority(report)


@pytest.mark.parametrize("error_type", [RuntimeError, ValueError, KeyboardInterrupt])
def test_real_codec_operational_failures_propagate_without_a_partial_result(material, monkeypatch, error_type):
    case = make_case(material)
    failure = error_type("authored operational refusal")
    def refused(*args, **kwargs):
        raise failure
    monkeypatch.setattr(compact, "decode_relational_compact_candidate_v1", refused)
    with pytest.raises(error_type) as raised:
        prepare(case)
    assert raised.value is failure


def test_source_fence_failure_after_decode_is_not_invalid_model_output(material, monkeypatch):
    case = make_case(material)
    original = compact.decode_relational_compact_candidate_v1
    failure = owner.RelationalBatchEvaluationError("authored codec source changed")
    def changed(*args, **kwargs):
        result = original(*args, **kwargs)
        def refuse_sources(*args):
            raise failure
        monkeypatch.setattr(owner, "_compact_sources", refuse_sources)
        return result
    monkeypatch.setattr(compact, "decode_relational_compact_candidate_v1", changed)
    with pytest.raises(owner.RelationalBatchEvaluationError) as raised:
        prepare(case)
    assert raised.value is failure


@pytest.mark.parametrize("damage", ["whole_pin", "codec_pin", "codec_table", "old_schema", "extra_envelope_field"])
def test_wrong_transport_or_codec_contract_refuses_whole_operation(material, monkeypatch, damage):
    case = make_case(material)
    if damage == "whole_pin":
        monkeypatch.setattr(owner, "_owners", lambda: pytest.fail("owner loaded before failed original pin"))
        with pytest.raises(owner.RelationalBatchEvaluationError):
            prepare(case, expected_predictions_sha256="0" * 64)
        return
    if damage == "codec_pin": case["predictions"]["codec_sha256"] = "0" * 64
    elif damage == "codec_table":
        case["predictions"]["codec"]["vocabulary"][3:5] = reversed(case["predictions"]["codec"]["vocabulary"][3:5])
        case["predictions"]["codec_sha256"] = sha(wire(case["predictions"]["codec"]))
    elif damage == "old_schema": case["predictions"]["schema"] = "legal-relational-batch-predictions/v1"
    else: case["predictions"]["target_dictionary"] = {}
    with pytest.raises(ValueError):
        prepare(case)


def test_complete_output_bound_refuses_instead_of_dropping_an_occurrence(material, monkeypatch):
    case = make_case(material)
    report = prepare(case)
    monkeypatch.setattr(owner, "MAX_OUTPUT_BYTES", len(wire(report)) - 1)
    with pytest.raises(owner.RelationalBatchEvaluationError):
        prepare(case)


@pytest.mark.parametrize("limit", ["MAX_PREDICTIONS_BYTES", "MAX_JSON_NODES", "MAX_OBSERVATIONS"])
def test_shared_input_bounds_are_atomic_and_not_silently_raised(material, monkeypatch, limit):
    case = make_case(material)
    if limit == "MAX_PREDICTIONS_BYTES": value = len(transport(case["predictions"])) - 1
    elif limit == "MAX_JSON_NODES": value = 10
    else: value = 0
    monkeypatch.setattr(owner, limit, value)
    monkeypatch.setattr(owner, "_owners", lambda: pytest.fail("owner loaded before full input refusal"))
    with pytest.raises(owner.RelationalBatchEvaluationError):
        prepare(case)


def test_full_original_replay_and_resealed_output_mutation_refusal(material):
    case = make_case(material)
    report = prepare(case)
    assert validate(case, report) == report
    assert owner.relational_compact_batch_evaluation_sha256(report) == sha(wire(report))
    changed = deepcopy(report)
    changed["observation_ledger"][0]["raw_observation"]["generated_ids"][1] = 999
    with pytest.raises(owner.RelationalBatchEvaluationError):
        validate(case, changed)
    changed = deepcopy(report)
    changed["training_mask"] = 1
    with pytest.raises(owner.RelationalBatchEvaluationError):
        validate(case, changed)


def test_wrong_independent_evaluation_pin_refuses_before_replay(material, monkeypatch):
    case = make_case(material)
    report = prepare(case)
    raw, pins = legacy.originals(case)
    monkeypatch.setattr(owner, "prepare_relational_compact_batch_evaluation_v1",
        lambda *args, **kwargs: pytest.fail("regeneration reached before failed report pin"))
    with pytest.raises(owner.RelationalBatchEvaluationError):
        owner.validate_relational_compact_batch_evaluation_v1(report, *raw,
            expected_evaluation_sha256="0" * 64, **pins)
