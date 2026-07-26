"""Synthetic-only G201/G235 semantic source-replay regressions.

No corpus, fixture, manifest path, or holdout value is opened by this module.
"""

from __future__ import annotations

import pytest

from benchmarks.logic_pipeline.semantic_quality import (
    G201_SEMANTIC_EVIDENCE_INDEX_SCHEMA_V2,
    G235_SEMANTIC_QUALITY_GATE_SCHEMA_V2,
    HSSLEV2350C27,
    SemanticQualityError,
    build_g201_semantic_evidence_index_v2,
    build_g235_semantic_quality_gate_v2,
    validate_g201_semantic_evidence_index_v2,
    validate_g235_semantic_quality_gate_v2,
)
from benchmarks.logic_pipeline.contracts import CacheMode, Split
from tests.integration.benchmarks.logic_pipeline.test_causal_runtime import (
    ENVIRONMENT_SHA256,
    MANIFEST_SHA256,
    SOURCE_TEXT,
)
from tests.integration.benchmarks.logic_pipeline.test_revised_pilot_positive_gates import (
    _complete_runtime_matrix,
    _runtime_matrix,
)

from ._semantic_quality_support import (
    complete_g201_index,
    mutable,
)


@pytest.fixture(scope="module")
def complete_index():
    return complete_g201_index()


@pytest.fixture(scope="module")
def complete_runtime_sources(tmp_path_factory):
    index = complete_g201_index(
        runtime_source_text=SOURCE_TEXT,
        manifest_sha256=MANIFEST_SHA256,
        environment_sha256=ENVIRONMENT_SHA256,
    )
    matrix = _complete_runtime_matrix(
        tmp_path_factory.mktemp("complete-g235-semantic")
    )
    return index, matrix


def test_g235_evidence_marker_names_the_bounded_lane() -> None:
    assert HSSLEV2350C27() == (
        "CID-native G201 source replay with label-blind producer/cache "
        "proofs and per-arm non-vacuous absolute semantic quality"
    )


def test_g201_replays_full_sources_and_absolute_quality(complete_index) -> None:
    replayed = validate_g201_semantic_evidence_index_v2(
        complete_index.to_dict()
    )
    wire = replayed.to_dict()

    assert wire["schema"] == G201_SEMANTIC_EVIDENCE_INDEX_SCHEMA_V2
    assert replayed.index_cid == complete_index.index_cid
    assert replayed.calibration_report["status"] == "complete"
    assert replayed.absolute_quality_passed is True
    assert len(wire["plans"]) == 2
    assert len(wire["results"]) == 100
    assert len(wire["source_coordinates"]) == 100
    assert all(
        row["reviewed_answers_in_producer_inputs_or_cache_keys"] is False
        for row in wire["source_coordinates"]
    )
    assert all(
        receipt["reviewed_answers_absent"] is True
        for row in wire["source_coordinates"]
        for receipt in row["label_blind_input_receipts"]
    )
    symai_cache_receipts = [
        receipt["cache_binding"]
        for row in wire["source_coordinates"]
        if row["producer_id"] == "symai"
        for receipt in row["label_blind_input_receipts"]
        if receipt["stage"] == "symai"
    ]
    assert len(symai_cache_receipts) == 20
    assert all(
        receipt["reviewed_answers_absent"] is True
        and receipt["source_only"] is True
        for receipt in symai_cache_receipts
    )


def test_g201_rejects_report_cids_and_reduced_aggregates(complete_index) -> None:
    report = mutable(complete_index.calibration_report)
    with pytest.raises(SemanticQualityError):
        validate_g201_semantic_evidence_index_v2(report)
    with pytest.raises(SemanticQualityError):
        validate_g201_semantic_evidence_index_v2(
            {
                "schema": G201_SEMANTIC_EVIDENCE_INDEX_SCHEMA_V2,
                "calibration_report_cid": report["artifact_cid"],
                "quality": report["quality"],
            }
        )


@pytest.mark.parametrize("variant_id", ["A5", "A8"])
def test_g201_rejects_missing_arm_or_coordinate(
    complete_index, variant_id: str
) -> None:
    wire = mutable(complete_index.to_dict())
    wire["results"] = [
        result
        for result in wire["results"]
        if result["variant_id"] != variant_id
    ]

    with pytest.raises(SemanticQualityError):
        validate_g201_semantic_evidence_index_v2(wire)


def test_g201_rejects_forged_reviewed_field(complete_index) -> None:
    wire = mutable(complete_index.to_dict())
    wire["target_manifest"]["cases"][0]["expected_semantics"][
        "target"
    ] = "forged_reviewed_answer"

    with pytest.raises(SemanticQualityError):
        validate_g201_semantic_evidence_index_v2(wire)


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("prompt_cid", "baguqeerak5wviqaf2dclxj2hztk7wz2gkd5t3zu2beu7t4tkhx3uocaaaaaa"),
        (
            "projection_schema_cid",
            "baguqeerak5wviqaf2dclxj2hztk7wz2gkd5t3zu2beu7t4tkhx3uocaaaaaa",
        ),
        (
            "calibration_route_manifest_cid",
            "baguqeerak5wviqaf2dclxj2hztk7wz2gkd5t3zu2beu7t4tkhx3uocaaaaaa",
        ),
    ],
)
def test_g201_rejects_post_freeze_protocol_drift(
    complete_index,
    field: str,
    replacement: str,
) -> None:
    wire = mutable(complete_index.to_dict())
    wire["protocol_identities"][field] = replacement

    with pytest.raises(SemanticQualityError):
        validate_g201_semantic_evidence_index_v2(wire)


def test_g201_rejects_cache_key_or_producer_identity_tampering(
    complete_index,
) -> None:
    cache_wire = mutable(complete_index.to_dict())
    symai_result = next(
        result
        for result in cache_wire["results"]
        if result["variant_id"] == "A5"
    )
    symai_stage = next(
        stage
        for stage in symai_result["stages"]
        if stage["stage"] == "symai"
    )
    symai_stage["data"]["cache"]["key"] += "-reviewed-answer"
    with pytest.raises(SemanticQualityError):
        validate_g201_semantic_evidence_index_v2(cache_wire)

    identity_wire = mutable(complete_index.to_dict())
    compiler = identity_wire["results"][0]["stages"][0]
    compiler["provenance"]["requested_identity"][
        "expected_ir"
    ] = {"target": "reviewed-answer"}
    with pytest.raises(SemanticQualityError):
        validate_g201_semantic_evidence_index_v2(identity_wire)


def test_g201_validation_error_precedence_is_measured_zero() -> None:
    index = complete_g201_index(
        symai_validation_error_case_id="synthetic-g201-pilot-00"
    )
    symai_observations = [
        row["semantic_observation"]
        for row in index.to_dict()["source_coordinates"]
        if row["producer_id"] == "symai"
    ]
    precedence = [
        row
        for row in symai_observations
        if row["validation_error_precedence_applied"] is True
    ]

    assert len(precedence) == 1
    assert precedence[0]["quality_millionths"] == 0
    assert precedence[0]["status"] == "semantic_validation_failed"
    assert index.absolute_quality_passed is True


def test_g201_builder_rejects_an_absent_target(complete_index) -> None:
    with pytest.raises(SemanticQualityError):
        build_g201_semantic_evidence_index_v2(
            target_manifest=complete_index.target_manifest,
            targets=complete_index.targets[:-1],
            plans=complete_index.plans,
            results=complete_index.results,
        )


def test_g235_replays_every_selected_runtime_semantic_coordinate(
    complete_runtime_sources,
) -> None:
    index, matrix = complete_runtime_sources
    gate = build_g235_semantic_quality_gate_v2(
        index, matrix, ("A1", "A12")
    )

    assert gate["schema"] == G235_SEMANTIC_QUALITY_GATE_SCHEMA_V2
    assert gate["status"] == "passed"
    assert gate["complete"] is gate["passed"] is True
    assert gate["failure_codes"] == ()
    assert gate["expected_coordinate_count"] == 12
    assert gate["observed_coordinate_count"] == 12
    assert len(gate["observations"]) == 12
    assert {
        (row["variant_id"], row["split"], row["cache_mode"])
        for row in gate["observations"]
    } == {
        (variant_id, split, cache_mode)
        for variant_id in ("A0", "A1", "A12")
        for split in ("pilot", "development")
        for cache_mode in ("cold", "warm")
    }
    assert all(
        row["measured"] is True
        and row["quality_millionths"] == 1_000_000
        and row["projection_nonvacuous"] is True
        and row[
            "reviewed_answers_in_producer_inputs_or_cache_keys"
        ]
        is False
        and str(row["runtime_receipt_cid"]).startswith("b")
        and str(row["case_result_cid"]).startswith("b")
        and str(row["observation_cid"]).startswith("b")
        for row in gate["observations"]
    )
    assert all(
        metric["absolute_quality_passed"] is True
        and metric["validation_error_precedence_verified_count"]
        == metric["scheduled_coordinate_count"]
        and metric["validation_error_precedence_applied_count"] == 0
        for metric in gate["per_arm_metrics"]
    )
    assert (
        validate_g235_semantic_quality_gate_v2(
            gate, index, matrix
        )["receipt_cid"]
        == gate["receipt_cid"]
    )


def test_g235_missing_target_and_arm_remain_null_and_incomplete(
    tmp_path,
) -> None:
    index = complete_g201_index()
    matrix = _runtime_matrix(tmp_path)
    gate = build_g235_semantic_quality_gate_v2(index, matrix, ("A1",))

    assert gate["status"] == "incomplete"
    assert gate["complete"] is gate["passed"] is False
    assert set(gate["failure_codes"]) >= {
        "g210_runtime_matrix_incomplete",
        "runtime_semantic_population_incomplete",
        "reviewed_runtime_target_missing",
        "runtime_semantic_measurement_incomplete",
    }
    assert all(
        row["quality_millionths"] is None
        and row["measured"] is False
        for row in gate["observations"]
    )
    assert all(
        metric["semantic_quality_millionths"] is None
        and metric["semantic_quality_rate"] is None
        for metric in gate["per_arm_metrics"]
    )


def test_g235_rejects_derived_observation_and_protocol_drift(
    complete_runtime_sources,
) -> None:
    index, matrix = complete_runtime_sources
    gate = build_g235_semantic_quality_gate_v2(index, matrix, ("A12",))
    observation_tamper = mutable(gate)
    observation_tamper["observations"][0][
        "quality_millionths"
    ] = 999_999
    with pytest.raises(SemanticQualityError):
        validate_g235_semantic_quality_gate_v2(
            observation_tamper, index, matrix
        )

    prompt_tamper = mutable(gate)
    prompt_tamper["protocol_identities"]["prompt_cid"] = (
        prompt_tamper["protocol_identities"]["response_schema_cid"]
    )
    with pytest.raises(SemanticQualityError):
        validate_g235_semantic_quality_gate_v2(
            prompt_tamper, index, matrix
        )

    precedence_tamper = mutable(gate)
    precedence_tamper["per_arm_metrics"][0][
        "validation_error_precedence_verified_count"
    ] = 0
    with pytest.raises(SemanticQualityError):
        validate_g235_semantic_quality_gate_v2(
            precedence_tamper, index, matrix
        )


def test_g235_requires_the_preregistered_g201_absolute_quality_condition(
    complete_runtime_sources,
) -> None:
    _passing_index, matrix = complete_runtime_sources
    failing_index = complete_g201_index(
        runtime_source_text=SOURCE_TEXT,
        manifest_sha256=MANIFEST_SHA256,
        environment_sha256=ENVIRONMENT_SHA256,
        validation_error_case_ids=tuple(
            f"synthetic-g201-pilot-{index:02d}" for index in range(6)
        ),
    )
    gate = build_g235_semantic_quality_gate_v2(
        failing_index, matrix, ("A1",)
    )

    assert failing_index.absolute_quality_passed is False
    assert gate["status"] == "failed"
    assert gate["complete"] is True
    assert gate["passed"] is False
    assert gate["failure_codes"] == (
        "g201_absolute_quality_condition_failed",
    )


def test_g235_runtime_validation_error_precedence_is_zero_not_missing(
    tmp_path,
) -> None:
    index = complete_g201_index(
        runtime_source_text=SOURCE_TEXT,
        manifest_sha256=MANIFEST_SHA256,
        environment_sha256=ENVIRONMENT_SHA256,
    )
    matrix = _complete_runtime_matrix(
        tmp_path,
        symai_validation_error_coordinates=(
            (Split.PILOT, CacheMode.COLD, "A12"),
            (Split.PILOT, CacheMode.WARM, "A12"),
        ),
    )
    gate = build_g235_semantic_quality_gate_v2(
        index, matrix, ("A12",)
    )
    precedence = [
        row
        for row in gate["observations"]
        if row["variant_id"] == "A12"
        and row["validation_error_precedence_applied"] is True
    ]
    candidate_metric = next(
        metric
        for metric in gate["per_arm_metrics"]
        if metric["variant_id"] == "A12"
    )

    assert gate["status"] == "failed"
    assert gate["complete"] is True
    assert gate["passed"] is False
    assert gate["failure_codes"] == (
        "runtime_arm_absolute_quality_failed",
    )
    assert len(precedence) == 2
    assert all(
        row["quality_millionths"] == 0 and row["measured"] is True
        for row in precedence
    )
    assert candidate_metric["measured_coordinate_count"] == 4
    assert (
        candidate_metric["validation_error_precedence_verified_count"]
        == 4
    )
    assert (
        candidate_metric["validation_error_precedence_applied_count"]
        == 2
    )
    assert candidate_metric["semantic_quality_millionths"] == 500_000
    assert candidate_metric["absolute_quality_passed"] is False
