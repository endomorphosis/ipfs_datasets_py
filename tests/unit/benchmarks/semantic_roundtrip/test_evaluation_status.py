"""Contract tests for SemanticRoundTripEvaluationStatus@1."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from benchmarks.semantic_roundtrip.contracts import (
    ComponentStatus,
    ContractError,
    FailureReason,
)
from benchmarks.semantic_roundtrip.evaluation_status import (
    DEFAULT_DETERMINISTIC_BASELINE_ARM_ID,
    EVALUATION_STATUS_INTERFACE,
    EVALUATION_STATUS_SCHEMA,
    PREFLIGHT_CAUSAL_QUALIFICATION,
    PREFLIGHT_LIVE_SMOKE,
    REPLACEMENT_2026_07_27_FAILURE_REASON_COUNTS,
    REPLACEMENT_2026_07_27_GUIDED_ARM_COUNT,
    REPLACEMENT_2026_07_27_GUIDED_COORDINATE_COUNT,
    REPLACEMENT_2026_07_27_SCHEDULED_COUNT,
    REPLACEMENT_2026_07_27_SUCCESS_COUNT,
    EvaluationStatus,
    LaunchPreflightError,
    NotMeasuredReason,
    RuntimeFailedReason,
    assert_matrix_launch_preflight,
    classify_coordinate_record,
    classify_evaluation_status,
    classify_historical_replacement_failure_reason,
    classify_replacement_report_coordinates,
    count_reasons,
    count_statuses,
    evaluate_matrix_launch_preflight,
    filter_leaderboard_classifications,
    filter_paired_baseline_classifications,
    is_default_leaderboard_eligible,
    is_deterministic_baseline_arm,
    required_preflights_for_arm,
)

ROOT = Path(__file__).resolve().parents[4]
REPLACEMENT_REPORT = (
    ROOT
    / "docs"
    / "performance_snapshots"
    / "2026-07-27_semantic_roundtrip_composition_replacement.json"
)

GUIDED_ARM = (
    "typed_deontic__guided__no_repair__not_applicable__deterministic"
)
RETRY_ARM = (
    "typed_deontic__no_guidance__no_repair__not_applicable__leanstral_direct"
)
BASELINE = DEFAULT_DETERMINISTIC_BASELINE_ARM_ID


def _success_record(arm_id: str = BASELINE) -> dict[str, object]:
    return {
        "arm_id": arm_id,
        "cell_id": arm_id,
        "coordinate_key": f"{arm_id}|exception_with_window|0|",
        "status": "success",
        "failure": None,
        "losses": {"end_to_end": 0.1, "forward": 0.05, "cycle": 0.05},
    }


def _guided_failure_record() -> dict[str, object]:
    return {
        "arm_id": GUIDED_ARM,
        "cell_id": GUIDED_ARM,
        "coordinate_key": f"{GUIDED_ARM}|exception_with_window|0|",
        "status": "failed",
        "failure": {
            "reason": "post_schedule_capability_unavailable",
            "detail": "unavailable_no_reviewed_causal_l1_adapter",
        },
        "losses": {"end_to_end": 1.0, "forward": 1.0, "cycle": 1.0},
        "qualification_status": "terminal_unsupported",
        "qualification_reason": "unavailable_no_reviewed_causal_l1_adapter",
    }


def _retry_exhausted_record() -> dict[str, object]:
    return {
        "arm_id": RETRY_ARM,
        "cell_id": RETRY_ARM,
        "coordinate_key": f"{RETRY_ARM}|exception_with_window|0|",
        "status": "failed",
        "failure": {
            "reason": "retry_exhausted",
            "detail": (
                "preregistered model-output recovery retry exhausted "
                "after malformed_output"
            ),
        },
        "losses": {"end_to_end": 1.0, "forward": 1.0, "cycle": 1.0},
    }


def test_statuses_are_disjoint_and_exhaustive() -> None:
    values = {item.value for item in EvaluationStatus}
    assert values == {
        EvaluationStatus.NOT_MEASURED.value,
        EvaluationStatus.RUNTIME_FAILED.value,
        EvaluationStatus.SEMANTIC_SCORED.value,
    }
    assert len(EvaluationStatus) == 3


def test_semantic_scored_success_with_defined_gates() -> None:
    record = classify_evaluation_status(
        status=ComponentStatus.SUCCESS,
        arm_id=BASELINE,
    )
    assert record.status is EvaluationStatus.SEMANTIC_SCORED
    assert record.reason == "success"
    assert record.loss_is_semantic is True
    assert record.include_in_default_leaderboard is True
    assert record.include_in_paired_baseline is True
    payload = record.to_dict()
    assert payload["interface"] == EVALUATION_STATUS_INTERFACE
    assert payload["schema_version"] == EVALUATION_STATUS_SCHEMA


def test_not_measured_terminal_unsupported() -> None:
    record = classify_evaluation_status(
        qualification_status="terminal_unsupported",
        qualification_reason="unavailable_no_reviewed_causal_l1_adapter",
        arm_id=GUIDED_ARM,
    )
    assert record.status is EvaluationStatus.NOT_MEASURED
    assert record.reason == NotMeasuredReason.TERMINAL_UNSUPPORTED.value
    assert record.loss_is_semantic is False
    assert record.include_in_default_leaderboard is False


def test_not_measured_preflight_blocked() -> None:
    record = classify_evaluation_status(
        preflight_blocked=True,
        detail="live_smoke missing for direct",
        arm_id=RETRY_ARM,
    )
    assert record.status is EvaluationStatus.NOT_MEASURED
    assert record.reason == NotMeasuredReason.PREFLIGHT_BLOCKED.value
    assert record.detail is not None
    assert "live_smoke" in record.detail


def test_runtime_failed_retry_exhausted() -> None:
    record = classify_evaluation_status(
        status="failed",
        failure_reason=FailureReason.RETRY_EXHAUSTED,
        detail="retry budget exhausted",
        arm_id=RETRY_ARM,
    )
    assert record.status is EvaluationStatus.RUNTIME_FAILED
    assert record.reason == RuntimeFailedReason.RETRY_EXHAUSTED.value
    assert record.loss_is_semantic is False
    assert record.include_in_default_leaderboard is False


def test_runtime_failed_provider_error() -> None:
    for token in ("provider_error", "endpoint_error", FailureReason.TIMEOUT, FailureReason.EXCEPTION):
        record = classify_evaluation_status(
            status="failed",
            failure_reason=token,
            arm_id=RETRY_ARM,
        )
        assert record.status is EvaluationStatus.RUNTIME_FAILED
        assert record.reason == RuntimeFailedReason.PROVIDER_ERROR.value


def test_guided_arm_from_2026_07_27_is_not_measured() -> None:
    """Guided replacement coordinates must not look like semantic loss 1.0."""
    record = classify_coordinate_record(_guided_failure_record())
    assert record.status is EvaluationStatus.NOT_MEASURED
    assert record.reason == NotMeasuredReason.TERMINAL_UNSUPPORTED.value
    assert record.arm_id == GUIDED_ARM
    assert record.detail is not None
    assert "unavailable_no_reviewed_causal_l1_adapter" in record.detail
    assert is_default_leaderboard_eligible(record) is False


def test_retry_exhausted_from_2026_07_27_is_runtime_failed() -> None:
    record = classify_coordinate_record(_retry_exhausted_record())
    assert record.status is EvaluationStatus.RUNTIME_FAILED
    assert record.reason == RuntimeFailedReason.RETRY_EXHAUSTED.value
    assert record.arm_id == RETRY_ARM
    assert is_default_leaderboard_eligible(record) is False


def test_historical_failure_reason_wrapper_matches_taxonomy() -> None:
    guided = classify_historical_replacement_failure_reason(
        "post_schedule_capability_unavailable",
        arm_id=GUIDED_ARM,
        detail="unavailable_no_reviewed_causal_l1_adapter",
    )
    retry = classify_historical_replacement_failure_reason(
        "retry_exhausted",
        arm_id=RETRY_ARM,
    )
    assert guided.status is EvaluationStatus.NOT_MEASURED
    assert retry.status is EvaluationStatus.RUNTIME_FAILED


def test_default_leaderboard_uses_only_semantic_scored() -> None:
    rows = [
        classify_coordinate_record(_success_record(BASELINE)),
        classify_coordinate_record(
            _success_record(
                "typed_deontic__no_guidance__selective__not_applicable__deterministic"
            )
        ),
        classify_coordinate_record(_guided_failure_record()),
        classify_coordinate_record(_retry_exhausted_record()),
    ]
    eligible = filter_leaderboard_classifications(rows)
    assert len(eligible) == 2
    assert all(
        item.status is EvaluationStatus.SEMANTIC_SCORED for item in eligible
    )
    assert not any(
        item.arm_id in {GUIDED_ARM, RETRY_ARM} for item in eligible
    )


def test_paired_baseline_comparisons_exclude_not_measured_and_runtime() -> None:
    rows = [
        classify_coordinate_record(_success_record(BASELINE)),
        classify_coordinate_record(
            _success_record(
                "modal_spacy__no_guidance__no_repair__not_applicable__deterministic"
            )
        ),
        classify_coordinate_record(_guided_failure_record()),
        classify_coordinate_record(_retry_exhausted_record()),
    ]
    paired = filter_paired_baseline_classifications(rows)
    assert {item.arm_id for item in paired} == {
        BASELINE,
        "modal_spacy__no_guidance__no_repair__not_applicable__deterministic",
    }
    assert all(
        item.status is EvaluationStatus.SEMANTIC_SCORED for item in paired
    )


def test_deterministic_baseline_identity() -> None:
    assert is_deterministic_baseline_arm(BASELINE)
    assert not is_deterministic_baseline_arm(GUIDED_ARM)
    assert not is_deterministic_baseline_arm(None)


def test_success_cannot_carry_failure_reason() -> None:
    with pytest.raises(ContractError, match="success status cannot carry"):
        classify_evaluation_status(
            status="success",
            failure_reason="retry_exhausted",
        )


def test_reason_must_match_status_on_record() -> None:
    from benchmarks.semantic_roundtrip.evaluation_status import (
        EvaluationStatusRecord,
    )

    with pytest.raises(ContractError, match="not_measured reason"):
        EvaluationStatusRecord(
            status=EvaluationStatus.NOT_MEASURED,
            reason="retry_exhausted",
        )


def test_required_preflights_guided_requires_causal() -> None:
    arm = {
        "cell_id": GUIDED_ARM,
        "composition": {
            "guidance": "guided",
            "constructor_route": "not_applicable",
        },
        "realizer": {"mode": "deterministic", "route": "not_applicable"},
        "model_backed": False,
        "deterministic": True,
        "route_requirements": [],
    }
    req = required_preflights_for_arm(arm)
    assert PREFLIGHT_CAUSAL_QUALIFICATION in req.requirements
    assert PREFLIGHT_LIVE_SMOKE not in req.requirements
    assert req.guided is True


def test_required_preflights_model_requires_live_smoke() -> None:
    arm = {
        "cell_id": RETRY_ARM,
        "composition": {
            "guidance": "no_guidance",
            "constructor_route": "not_applicable",
        },
        "realizer": {"mode": "model", "route": "direct"},
        "model_backed": True,
        "deterministic": False,
        "route_requirements": ["direct"],
    }
    req = required_preflights_for_arm(arm)
    assert PREFLIGHT_LIVE_SMOKE in req.requirements
    assert PREFLIGHT_CAUSAL_QUALIFICATION not in req.requirements
    assert "direct" in req.routes


def test_matrix_launch_fails_closed_without_causal_qualification() -> None:
    arms = [
        {
            "cell_id": GUIDED_ARM,
            "composition": {"guidance": "guided"},
            "realizer": {"mode": "deterministic", "route": "not_applicable"},
            "deterministic": True,
            "model_backed": False,
            "route_requirements": [],
        }
    ]
    verdict = evaluate_matrix_launch_preflight(
        arms,
        live_smokes={},
        causal_qualification={
            "disposition": "terminal_unsupported",
            "status": "terminal_unsupported",
        },
    )
    assert verdict.authorized is False
    assert any(
        item.get("preflight") == PREFLIGHT_CAUSAL_QUALIFICATION
        for item in verdict.missing
    )
    with pytest.raises(LaunchPreflightError, match="matrix launch blocked"):
        assert_matrix_launch_preflight(
            arms,
            causal_qualification={"disposition": "terminal_unsupported"},
        )


def test_matrix_launch_fails_closed_without_live_smoke() -> None:
    arms = [
        {
            "cell_id": RETRY_ARM,
            "composition": {"guidance": "no_guidance"},
            "realizer": {"mode": "model", "route": "direct"},
            "model_backed": True,
            "route_requirements": ["direct"],
        }
    ]
    verdict = evaluate_matrix_launch_preflight(
        arms,
        live_smokes={
            "direct": {
                "status": "passed",
                "model_inference_performed": False,
                "health_only": True,
            }
        },
    )
    assert verdict.authorized is False
    assert any(
        item.get("preflight") == PREFLIGHT_LIVE_SMOKE
        for item in verdict.missing
    )


def test_matrix_launch_authorizes_when_preflights_present() -> None:
    arms = [
        {
            "cell_id": BASELINE,
            "composition": {"guidance": "no_guidance"},
            "realizer": {
                "mode": "deterministic",
                "route": "not_applicable",
            },
            "deterministic": True,
            "model_backed": False,
            "route_requirements": [],
        },
        {
            "cell_id": RETRY_ARM,
            "composition": {"guidance": "no_guidance"},
            "realizer": {"mode": "model", "route": "direct"},
            "model_backed": True,
            "route_requirements": ["direct"],
        },
        {
            "cell_id": GUIDED_ARM,
            "composition": {"guidance": "guided"},
            "realizer": {
                "mode": "deterministic",
                "route": "not_applicable",
            },
            "deterministic": True,
            "model_backed": False,
            "route_requirements": [],
        },
    ]
    verdict = assert_matrix_launch_preflight(
        arms,
        live_smokes={
            "direct": {
                "status": "passed",
                "model_inference_performed": True,
            }
        },
        causal_qualification={
            "status": "scored_supported",
            "disposition": "scored_supported",
            "causal_contract": {"preregistered": True},
        },
    )
    assert verdict.authorized is True
    assert verdict.missing == ()


def test_replacement_report_2026_07_27_status_histogram() -> None:
    """Reclassify the frozen replacement run with the disjoint taxonomy.

    The 2026-07-27 replacement shell reported:

    * 260 ``post_schedule_capability_unavailable`` (all guided arms) →
      ``not_measured`` / ``terminal_unsupported``
    * 210 ``retry_exhausted`` (mostly Leanstral routes) →
      ``runtime_failed`` / ``retry_exhausted``
    * 200 successes → ``semantic_scored`` / ``success``
    """
    assert REPLACEMENT_REPORT.is_file(), (
        "replacement report snapshot must be present for contract tests"
    )
    report = json.loads(REPLACEMENT_REPORT.read_bytes())
    execution = report.get("execution") or {}
    records: list[dict[str, object]] = []
    for lane in ("deterministic", "model_backed"):
        bucket = execution.get(lane) or {}
        if not isinstance(bucket, dict):
            continue
        lane_records = bucket.get("records") or []
        if isinstance(lane_records, list):
            records.extend(
                item for item in lane_records if isinstance(item, dict)
            )
    assert len(records) == REPLACEMENT_2026_07_27_SCHEDULED_COUNT

    arm_qualifications: dict[str, dict[str, object]] = {}
    plan_arms = (
        ((report.get("preregistration") or {}).get("plan") or {}).get("arms")
        or []
    )
    for arm in plan_arms:
        if not isinstance(arm, dict):
            continue
        arm_id = arm.get("arm_id") or arm.get("cell_id")
        if not arm_id:
            continue
        arm_qualifications[str(arm_id)] = {
            "qualification_status": arm.get("qualification_status"),
            "qualification_reason": arm.get("qualification_reason"),
        }

    raw_failure_counts: Counter[str] = Counter()
    for record in records:
        failure = record.get("failure") if isinstance(record, dict) else None
        if isinstance(failure, dict):
            reason = failure.get("reason") or failure.get("failure_reason")
            if isinstance(reason, str):
                raw_failure_counts[reason] += 1
        elif isinstance(record, dict):
            reason = record.get("failure_reason")
            if isinstance(reason, str):
                raw_failure_counts[reason] += 1

    assert (
        raw_failure_counts["post_schedule_capability_unavailable"]
        == REPLACEMENT_2026_07_27_FAILURE_REASON_COUNTS[
            "post_schedule_capability_unavailable"
        ]
    )
    assert (
        raw_failure_counts["retry_exhausted"]
        == REPLACEMENT_2026_07_27_FAILURE_REASON_COUNTS["retry_exhausted"]
    )
    success_count = sum(
        1
        for record in records
        if isinstance(record, dict) and record.get("status") == "success"
    )
    assert success_count == REPLACEMENT_2026_07_27_SUCCESS_COUNT

    classified = classify_replacement_report_coordinates(
        records,
        arm_qualifications=arm_qualifications,
    )
    status_counts = count_statuses(classified)
    reason_counts = count_reasons(classified)

    assert (
        status_counts["not_measured"]
        == REPLACEMENT_2026_07_27_GUIDED_COORDINATE_COUNT
    )
    assert status_counts["runtime_failed"] == 210
    assert status_counts["semantic_scored"] == REPLACEMENT_2026_07_27_SUCCESS_COUNT
    assert reason_counts["success"] == REPLACEMENT_2026_07_27_SUCCESS_COUNT
    assert (
        reason_counts[NotMeasuredReason.TERMINAL_UNSUPPORTED.value]
        == REPLACEMENT_2026_07_27_GUIDED_COORDINATE_COUNT
    )
    assert reason_counts[RuntimeFailedReason.RETRY_EXHAUSTED.value] == 210

    guided_arms = {
        item.arm_id
        for item in classified
        if item.status is EvaluationStatus.NOT_MEASURED
    }
    assert len(guided_arms) == REPLACEMENT_2026_07_27_GUIDED_ARM_COUNT

    guided_rows = [
        item
        for item in classified
        if item.status is EvaluationStatus.NOT_MEASURED
    ]
    assert all(
        item.reason == NotMeasuredReason.TERMINAL_UNSUPPORTED.value
        for item in guided_rows
    )
    retry_rows = [
        item
        for item in classified
        if item.status is EvaluationStatus.RUNTIME_FAILED
    ]
    assert len(retry_rows) == 210
    assert all(
        item.reason == RuntimeFailedReason.RETRY_EXHAUSTED.value
        for item in retry_rows
    )

    leaderboard = filter_leaderboard_classifications(classified)
    assert all(
        item.status is EvaluationStatus.SEMANTIC_SCORED for item in leaderboard
    )
    assert not any(
        item.status is EvaluationStatus.NOT_MEASURED for item in leaderboard
    )
    assert not any(
        item.status is EvaluationStatus.RUNTIME_FAILED for item in leaderboard
    )
    assert any(item.arm_id == BASELINE for item in leaderboard)
    statistics = report.get("statistics") or {}
    baseline_arm_id = statistics.get("baseline_arm_id") or BASELINE
    assert baseline_arm_id == BASELINE


def test_launch_preflight_blocks_historical_guided_schedule_shape() -> None:
    """A schedule that still includes unsupported guided arms fails closed."""
    assert REPLACEMENT_REPORT.is_file()
    report = json.loads(REPLACEMENT_REPORT.read_bytes())
    plan_arms = (
        ((report.get("preregistration") or {}).get("plan") or {}).get("arms")
        or []
    )
    guided_plan_arms = [
        arm
        for arm in plan_arms
        if isinstance(arm, dict)
        and arm.get("qualification_status") == "terminal_unsupported"
    ]
    assert len(guided_plan_arms) == REPLACEMENT_2026_07_27_GUIDED_ARM_COUNT

    verdict = evaluate_matrix_launch_preflight(
        guided_plan_arms,
        live_smokes={
            route: {
                "status": "passed",
                "model_inference_performed": True,
            }
            for route in ("direct", "symai")
        },
        causal_qualification={
            "disposition": "terminal_unsupported",
            "guided_coordinates": {
                "disposition": "terminal_unsupported",
            },
        },
    )
    assert verdict.authorized is False
    assert all(
        item.get("preflight") == PREFLIGHT_CAUSAL_QUALIFICATION
        for item in verdict.missing
    )
