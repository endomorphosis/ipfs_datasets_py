"""Source-safe synthetic coverage for the bounded HSSL-G237 lane.

The runtime matrix is synthesized in a temporary directory by the same helper
used for G234.  No checked-in fixture, corpus, manifest, or holdout is read.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace

import pytest

from benchmarks.logic_pipeline.content_addressing import (
    cid_for_bytes,
    cid_for_dag_json,
    validate_cid,
)
from benchmarks.logic_pipeline.resource_statistics import (
    HSSLEV2374E49,
    IndependentComponentResourceV2,
    IndependentResourceReceiptV2,
    ResourceStatisticsError,
    build_independent_resource_receipt_v2,
    build_resource_statistics_gate_v2,
    compare_resource_replay_measurements_v2,
    resource_evidence_set_cid_v2,
    validate_independent_resource_receipt_v2,
    validate_resource_replay_comparison_v2,
    validate_resource_statistics_gate_v2,
)
from benchmarks.logic_pipeline.reviewed_control import (
    REVIEWED_CONTROL_SAFETY_GATE_SCHEMA_V2,
)
from benchmarks.logic_pipeline.revised_pilot_authorization import (
    build_g234_efficacy_gate_v2,
)
from benchmarks.logic_pipeline.statistics import StatisticalPlan
from tests.integration.benchmarks.logic_pipeline.test_revised_pilot_positive_gates import (
    _complete_runtime_matrix,
)


TEST_PLAN = StatisticalPlan(
    seed=237,
    bootstrap_samples=32,
)


def _identity(role: str) -> str:
    return cid_for_dag_json(
        {
            "schema": "synthetic-g237-authority.v1",
            "role": role,
        }
    )


def _component(
    variant_id: str,
    *,
    missing_field: str | None = None,
    released: bool | None = True,
    reaped: bool | None = True,
) -> IndependentComponentResourceV2:
    # A1 trades lower latency for higher peak memory and model use so the
    # direction-aware frontier cannot collapse the objectives to one score.
    values: dict[str, object] = {
        "wall_time_ms": 10.0 if variant_id == "A0" else 8.0,
        "peak_memory_bytes": 10 if variant_id == "A0" else 20,
        "model_calls": 0 if variant_id == "A0" else 1,
        "retries": 0,
        "solver_processes": 0,
        "accelerator_minutes": 0.0,
        "queue_delay_ms": 1.0,
        "released": released,
        "process_group_reaped": reaped,
    }
    if missing_field is not None:
        values[missing_field] = None
    reasons = {
        field: "synthetic meter did not emit this measurement"
        for field, value in values.items()
        if value is None
    }
    return IndependentComponentResourceV2(
        component_id="pipeline",
        wall_time_ms=values["wall_time_ms"],  # type: ignore[arg-type]
        peak_memory_bytes=values[
            "peak_memory_bytes"
        ],  # type: ignore[arg-type]
        model_calls=values["model_calls"],  # type: ignore[arg-type]
        retries=values["retries"],  # type: ignore[arg-type]
        solver_processes=values[
            "solver_processes"
        ],  # type: ignore[arg-type]
        accelerator_minutes=values[
            "accelerator_minutes"
        ],  # type: ignore[arg-type]
        queue_delay_ms=values[
            "queue_delay_ms"
        ],  # type: ignore[arg-type]
        released=values["released"],  # type: ignore[arg-type]
        process_group_reaped=values[
            "process_group_reaped"
        ],  # type: ignore[arg-type]
        missing_reasons=reasons,
    )


def _safety_gate(
    *,
    status: str = "passed",
) -> dict[str, object]:
    passed = status == "passed"
    fatal = status == "failed"
    complete = status != "incomplete"
    body = {
        "schema": REVIEWED_CONTROL_SAFETY_GATE_SCHEMA_V2,
        "complete": complete,
        "passed": passed,
        "fatal": fatal,
        "status": status,
        "failure_codes": (
            []
            if passed
            else [
                (
                    "invalid_control_terminal_native_kernel_acceptance"
                    if fatal
                    else "required_runtime_coordinate_missing"
                )
            ]
        ),
        "holdout_included": False,
    }
    return {**body, "receipt_cid": cid_for_dag_json(body)}


def _plain(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            str(key): _plain(member)
            for key, member in value.items()
        }
    if isinstance(value, (tuple, list)):
        return [_plain(member) for member in value]
    return value


def _assert_no_new_bare_sha_fields(value: object) -> None:
    if isinstance(value, Mapping):
        assert not any(str(key).endswith("_sha256") for key in value)
        for member in value.values():
            _assert_no_new_bare_sha_fields(member)
    elif isinstance(value, (tuple, list)):
        for member in value:
            _assert_no_new_bare_sha_fields(member)


@pytest.fixture(scope="module")
def g237_sources(tmp_path_factory: pytest.TempPathFactory):
    matrix = _complete_runtime_matrix(
        tmp_path_factory.mktemp("synthetic-g237")
    )
    producer = _identity("producer")
    meter = _identity("independent-meter")
    validator = _identity("independent-validator")
    receipts = tuple(
        build_independent_resource_receipt_v2(
            evidence,
            (_component(evidence.case_result.variant_id),),
            producer_identity_cid=producer,
            meter_identity_cid=meter,
            validator_identity_cid=validator,
        )
        for evidence in matrix.runtime_evidence
        if evidence.case_result.variant_id in {"A0", "A1"}
    )
    efficacy = build_g234_efficacy_gate_v2(matrix, ("A1",))
    safety = _safety_gate()
    resource_set_cid = resource_evidence_set_cid_v2(
        matrix.runtime_matrix_cid,
        ("A1",),
        receipts,
    )
    return {
        "matrix": matrix,
        "producer": producer,
        "meter": meter,
        "validator": validator,
        "receipts": receipts,
        "efficacy": efficacy,
        "safety": safety,
        "resource_set_cid": resource_set_cid,
    }


def _build_gate(
    sources,
    *,
    receipts=None,
    resource_set_cid: str | None = None,
    safety=None,
    safety_cid: str | None = None,
):
    selected_receipts = (
        sources["receipts"] if receipts is None else tuple(receipts)
    )
    selected_safety = sources["safety"] if safety is None else safety
    return build_resource_statistics_gate_v2(
        sources["matrix"],
        ("A1",),
        selected_receipts,
        sources["efficacy"],
        selected_safety,
        expected_resource_evidence_set_cid=(
            sources["resource_set_cid"]
            if resource_set_cid is None
            else resource_set_cid
        ),
        expected_safety_gate_receipt_cid=(
            sources["safety"]["receipt_cid"]
            if safety_cid is None
            else safety_cid
        ),
        statistical_plan=TEST_PLAN,
    )


def test_g237_marker_is_bounded_to_resource_statistics_and_pareto() -> None:
    assert HSSLEV2374E49() == (
        "CID-native independent resource receipts, exact missing-aware A0 "
        "pairs, replayed statistics, and safety-feasible Pareto evidence"
    )


def test_independent_receipts_are_cid_native_and_authorities_are_distinct(
    g237_sources,
) -> None:
    receipt = g237_sources["receipts"][0]
    replayed = validate_independent_resource_receipt_v2(
        receipt.to_dict()
    )

    assert replayed.receipt_cid == receipt.receipt_cid
    assert replayed.complete is True
    assert replayed.lifecycle_safe is True
    validate_cid(receipt.receipt_cid, codecs=("dag-json",))
    validate_cid(receipt.source_cid, codecs=("raw",))
    _assert_no_new_bare_sha_fields(receipt.to_dict())

    with pytest.raises(
        ResourceStatisticsError,
        match="identities must be distinct",
    ):
        replace(
            receipt,
            validator_identity_cid=receipt.meter_identity_cid,
        )


def test_replay_identity_excludes_volatile_measurements_and_run_receipt(
    g237_sources,
) -> None:
    source = g237_sources["receipts"][0]
    component = replace(
        source.components[0],
        wall_time_ms=source.components[0].wall_time_ms + 5.0,
    )
    replay = replace(
        source,
        runtime_evidence_cid=cid_for_dag_json(
            {"synthetic": "fresh-runtime"}
        ),
        run_identity_cid=cid_for_dag_json(
            {"synthetic": "fresh-run"}
        ),
        coordinate_cid=cid_for_dag_json(
            {"synthetic": "fresh-runtime-coordinate"}
        ),
        producer_identity_cid=_identity("replay-producer"),
        meter_identity_cid=_identity("replay-meter"),
        validator_identity_cid=_identity("replay-validator"),
        components=(component,),
    )

    comparison = compare_resource_replay_measurements_v2(source, replay)

    assert source.receipt_cid != replay.receipt_cid
    assert source.measurement_cid != replay.measurement_cid
    assert source.replay_identity_cid == replay.replay_identity_cid
    assert comparison["passed"] is True
    assert comparison["failure_codes"] == []
    assert (
        validate_resource_replay_comparison_v2(
            comparison,
            source,
            replay,
        )
        == comparison["comparison_receipt_cid"]
    )


@pytest.mark.parametrize(
    ("component", "expected_code"),
    (
        (
            IndependentComponentResourceV2(
                component_id="pipeline",
                wall_time_ms=100.0,
                peak_memory_bytes=10,
                model_calls=0,
                retries=0,
                solver_processes=0,
                accelerator_minutes=0.0,
                queue_delay_ms=1.0,
                released=True,
                process_group_reaped=True,
                missing_reasons={},
            ),
            "resource_replay_measurement_out_of_tolerance",
        ),
        (
            _component("A0", missing_field="wall_time_ms"),
            "resource_replay_measurement_missing",
        ),
        (
            _component("A0", released=False),
            "resource_replay_lifecycle_mismatch",
        ),
    ),
)
def test_replay_measurement_failures_remain_fail_closed(
    g237_sources,
    component: IndependentComponentResourceV2,
    expected_code: str,
) -> None:
    source = g237_sources["receipts"][0]
    replay = replace(source, components=(component,))

    comparison = compare_resource_replay_measurements_v2(source, replay)

    assert comparison["passed"] is False
    assert expected_code in comparison["failure_codes"]


def test_replay_comparison_rejects_identity_and_cid_tampering(
    g237_sources,
) -> None:
    source = g237_sources["receipts"][0]
    replay = replace(
        source,
        replay_coordinate_cid=cid_for_dag_json(
            {"synthetic": "different-treatment-coordinate"}
        ),
    )
    comparison = compare_resource_replay_measurements_v2(source, replay)
    assert comparison["identity_equal"] is False
    assert "resource_replay_identity_mismatch" in (
        comparison["failure_codes"]
    )

    tampered = _plain(comparison)
    tampered["within_tolerance_count"] = 999  # type: ignore[index]
    body = {
        key: value
        for key, value in tampered.items()  # type: ignore[union-attr]
        if key != "comparison_receipt_cid"
    }
    tampered["comparison_receipt_cid"] = cid_for_dag_json(body)  # type: ignore[index]
    with pytest.raises(
        ResourceStatisticsError,
        match="source-recompute",
    ):
        validate_resource_replay_comparison_v2(
            tampered,
            source,
            replay,
        )


def test_complete_gate_preserves_pairs_statistics_and_pareto_directions(
    g237_sources,
) -> None:
    gate = _build_gate(g237_sources)

    assert gate["status"] == "passed"
    assert gate["complete"] is True
    assert gate["passed"] is True
    assert gate["failure_codes"] == ()
    assert gate["efficacy_and_cost_separate"] is True
    assert gate["efficacy_evidence"]["resource_receipt_cids_included"] is False
    assert len(gate["paired_cost_observations"]) == 28
    assert len(gate["paired_cost_analyses"]) == 16
    assert all(
        pair["identity_valid"] is True and pair["measured"] is True
        for pair in gate["paired_cost_observations"]
    )
    assert {
        item["metric_id"]
        for item in gate["pareto_evidence"]["objectives"]
    } == {
        "paired_verified_delta_vs_a0",
        "wall_time_ms",
        "peak_memory_bytes",
        "model_calls",
        "retries",
        "solver_processes",
        "accelerator_minutes",
        "queue_delay_ms",
    }
    # A1 is faster but consumes more memory/model calls, so neither arm
    # dominates the other under the direction-aware objective vector.
    assert gate["pareto_evidence"]["frontier_variant_ids"] == (
        "A0",
        "A1",
    )
    _assert_no_new_bare_sha_fields(gate)
    assert (
        validate_resource_statistics_gate_v2(
            gate,
            g237_sources["matrix"],
            g237_sources["receipts"],
            g237_sources["efficacy"],
            g237_sources["safety"],
            expected_resource_evidence_set_cid=(
                g237_sources["resource_set_cid"]
            ),
            expected_safety_gate_receipt_cid=(
                g237_sources["safety"]["receipt_cid"]
            ),
            statistical_plan=TEST_PLAN,
        )["receipt_cid"]
        == gate["receipt_cid"]
    )


@pytest.mark.parametrize(
    ("missing_field", "expected_code"),
    [
        ("wall_time_ms", "paired_statistics_unpaired"),
        ("queue_delay_ms", "cost_aggregate_incomplete"),
    ],
)
def test_null_resource_work_stays_null_and_makes_gate_incomplete(
    g237_sources,
    missing_field: str,
    expected_code: str,
) -> None:
    receipts = list(g237_sources["receipts"])
    runtime_by_cid = {
        item.receipt_cid: item
        for item in g237_sources["matrix"].runtime_evidence
    }
    target = next(
        index
        for index, receipt in enumerate(receipts)
        if runtime_by_cid[
            receipt.runtime_evidence_cid
        ].case_result.variant_id == "A1"
    )
    original = receipts[target]
    component = _component("A1", missing_field=missing_field)
    receipts[target] = replace(original, components=(component,))
    resource_set = resource_evidence_set_cid_v2(
        g237_sources["matrix"].runtime_matrix_cid,
        ("A1",),
        receipts,
    )

    gate = _build_gate(
        g237_sources,
        receipts=receipts,
        resource_set_cid=resource_set,
    )

    assert gate["status"] == "incomplete"
    assert "resource_measurement_incomplete" in gate["failure_codes"]
    assert expected_code in gate["failure_codes"]
    relevant = [
        pair
        for pair in gate["paired_cost_observations"]
        if (
            pair["candidate_resource_receipt_cid"]
            == receipts[target].receipt_cid
            and pair["metric_id"] == missing_field
        )
    ]
    assert relevant
    assert relevant[0]["candidate_value"] is None
    assert relevant[0]["measured"] is False
    assert relevant[0]["missing_reasons"]


def test_missing_duplicate_stale_and_rebased_resource_sets_fail_closed(
    g237_sources,
) -> None:
    receipts = g237_sources["receipts"]
    missing = receipts[:-1]
    missing_set = resource_evidence_set_cid_v2(
        g237_sources["matrix"].runtime_matrix_cid,
        ("A1",),
        missing,
    )
    missing_gate = _build_gate(
        g237_sources,
        receipts=missing,
        resource_set_cid=missing_set,
    )
    assert missing_gate["status"] == "incomplete"
    assert (
        "resource_receipt_population_incomplete"
        in missing_gate["failure_codes"]
    )

    duplicate = (*receipts, receipts[0])
    duplicate_set = resource_evidence_set_cid_v2(
        g237_sources["matrix"].runtime_matrix_cid,
        ("A1",),
        duplicate,
    )
    duplicate_gate = _build_gate(
        g237_sources,
        receipts=duplicate,
        resource_set_cid=duplicate_set,
    )
    assert duplicate_gate["status"] == "incomplete"
    assert "duplicate_resource_receipt" in duplicate_gate["failure_codes"]

    stale = list(receipts)
    stale[0] = replace(
        stale[0],
        source_cid=cid_for_bytes(b"different source"),
    )
    stale_set = resource_evidence_set_cid_v2(
        g237_sources["matrix"].runtime_matrix_cid,
        ("A1",),
        stale,
    )
    stale_gate = _build_gate(
        g237_sources,
        receipts=stale,
        resource_set_cid=stale_set,
    )
    assert stale_gate["status"] == "incomplete"
    assert "resource_receipt_stale_binding" in stale_gate["failure_codes"]

    rebased = list(receipts)
    rebased[0] = replace(
        rebased[0],
        components=(_component("A0", released=False),),
    )
    lifecycle_set = resource_evidence_set_cid_v2(
        g237_sources["matrix"].runtime_matrix_cid,
        ("A1",),
        rebased,
    )
    lifecycle_gate = _build_gate(
        g237_sources,
        receipts=rebased,
        resource_set_cid=lifecycle_set,
    )
    assert lifecycle_gate["status"] == "failed"
    assert (
        "resource_release_or_reap_failed"
        in lifecycle_gate["failure_codes"]
    )

    rebased_gate = _build_gate(
        g237_sources,
        receipts=rebased,
        # Keep the independently frozen original population CID.
        resource_set_cid=g237_sources["resource_set_cid"],
    )
    assert rebased_gate["status"] == "incomplete"
    assert "resource_evidence_set_rebased" in rebased_gate["failure_codes"]


def test_safety_is_a_hard_constraint_and_rebased_safety_is_incomplete(
    g237_sources,
) -> None:
    # This bounded lane checks the pinned G236 receipt's schema/state/CID.
    # G231 must separately source-replay that receipt with the complete G236
    # control index, manifests, and runtime evidence before composing G237.
    failed_safety = _safety_gate(status="failed")
    failed_gate = _build_gate(
        g237_sources,
        safety=failed_safety,
        safety_cid=failed_safety["receipt_cid"],  # type: ignore[arg-type]
    )
    assert failed_gate["status"] == "failed"
    assert "reviewed_control_safety_failed" in failed_gate["failure_codes"]
    assert failed_gate["pareto_evidence"]["frontier_variant_ids"] == ()
    assert all(
        item["eligible"] is False
        for item in failed_gate["pareto_evidence"]["candidates"]
    )

    rebased_gate = _build_gate(
        g237_sources,
        safety=failed_safety,
        # Preserve the pinned passing receipt CID.
        safety_cid=g237_sources["safety"]["receipt_cid"],
    )
    assert rebased_gate["status"] == "incomplete"
    assert "safety_gate_rebased" in rebased_gate["failure_codes"]


def test_gate_validator_rejects_tampered_statistics_and_pareto(
    g237_sources,
) -> None:
    gate = _build_gate(g237_sources)
    tampered = _plain(gate)
    tampered["paired_cost_analyses"][0]["summary"][  # type: ignore[index]
        "candidate_minus_baseline"
    ] = -999.0
    tampered["pareto_evidence"]["frontier_variant_ids"] = [  # type: ignore[index]
        "A1"
    ]
    pareto_body = {
        key: value
        for key, value in tampered["pareto_evidence"].items()  # type: ignore[union-attr]
        if key != "pareto_cid"
    }
    tampered["pareto_evidence"]["pareto_cid"] = (  # type: ignore[index]
        cid_for_dag_json(pareto_body)
    )
    gate_body = {
        key: value
        for key, value in tampered.items()  # type: ignore[union-attr]
        if key != "receipt_cid"
    }
    tampered["receipt_cid"] = cid_for_dag_json(gate_body)  # type: ignore[index]

    with pytest.raises(
        ResourceStatisticsError,
        match="source-recompute",
    ):
        validate_resource_statistics_gate_v2(
            tampered,
            g237_sources["matrix"],
            g237_sources["receipts"],
            g237_sources["efficacy"],
            g237_sources["safety"],
            expected_resource_evidence_set_cid=(
                g237_sources["resource_set_cid"]
            ),
            expected_safety_gate_receipt_cid=(
                g237_sources["safety"]["receipt_cid"]
            ),
            statistical_plan=TEST_PLAN,
        )
