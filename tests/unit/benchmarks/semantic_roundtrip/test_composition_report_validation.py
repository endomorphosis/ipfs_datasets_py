"""Tests for the complete SRT-014 frozen-report validator."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from benchmarks.bench_semantic_roundtrip_compositions import (
    REPORT_INTERFACE,
    REPORT_SCHEMA_VERSION,
    main,
    validate_composition_report,
)
from benchmarks.logic_pipeline.content_addressing import cid_for_dag_json


DETERMINISTIC_IDS = [f"deterministic-{index}" for index in range(4)]
MODEL_IDS = [f"model-{index}" for index in range(26)]


def _fixture(tmp_path: Path) -> tuple[Path, list[str], str]:
    path = tmp_path / "pilot_cases.json"
    rows = [
        {"case_id": f"case-{index}", "source_text": f"case {index}"}
        for index in range(5)
    ]
    raw = json.dumps(rows, sort_keys=True).encode()
    path.write_bytes(raw)
    return path, [row["case_id"] for row in rows], hashlib.sha256(raw).hexdigest()


def _record(
    case_id: str,
    repeat_index: int,
    arm_id: str,
    *,
    cache_namespace: str | None = None,
) -> dict[str, object]:
    record: dict[str, object] = {
        "case_id": case_id,
        "repeat_index": repeat_index,
        "arm_id": arm_id,
        "status": "failed",
        "losses": {
            "forward": 1.0,
            "cycle": 1.0,
            "end_to_end": 1.0,
            "primary": 1.0,
        },
        "gates": {
            "source_copy_exclusion": False,
            "polarity_preservation": False,
            "full_coverage": False,
            "selection_eligible": False,
        },
        "cost": {
            "model_calls": 1,
            "input_tokens": None,
            "output_tokens": None,
            "estimated_cost": None,
        },
    }
    if cache_namespace is not None:
        record["cache_mode"] = "uncached"
        record["cache_namespace"] = cache_namespace
    return record


def _summary(
    case_ids: list[str],
    *,
    repeats: int,
) -> dict[str, object]:
    scheduled = len(case_ids) * repeats
    return {
        "scheduled_coordinate_count": scheduled,
        "observed_coordinate_count": scheduled,
        "missing_coordinate_count": 0,
        "repeat_count_per_case": repeats,
        "execution_status": "complete",
        "per_case": {
            case_id: {
                "status": "failed",
                "observed_repeats": repeats,
                "scheduled_repeat_count": repeats,
                "observed_terminal_repeat_count": repeats,
                "losses": {
                    "forward": 1.0,
                    "cycle": 1.0,
                    "end_to_end": 1.0,
                },
                "all_repeats_selection_eligible": False,
            }
            for case_id in case_ids
        },
        "all_cases_selection_eligible": False,
        "cost": {"model_calls": scheduled},
        "aggregate": {
            loss: {
                "mean": 1.0,
                "uncertainty": {
                    "method": "seeded_case_bootstrap",
                    "low": 1.0,
                    "high": 1.0,
                },
            }
            for loss in ("forward", "cycle", "end_to_end")
        },
    }


def _complete_report(
    fixture_path: Path,
    case_ids: list[str],
    fixture_sha256: str,
) -> dict[str, object]:
    blocks: list[dict[str, object]] = []
    model_records: list[dict[str, object]] = []
    for case_index, case_id in enumerate(case_ids):
        for repeat_index in range(5):
            coordinates: list[dict[str, object]] = []
            for arm_index, arm_id in enumerate(MODEL_IDS):
                namespace = (
                    f"uncached-{case_index}-{repeat_index}-{arm_index}"
                )
                coordinates.append(
                    {
                        "arm_id": arm_id,
                        "cache_mode": "uncached",
                        "cache_namespace": namespace,
                    }
                )
                model_records.append(
                    _record(
                        case_id,
                        repeat_index,
                        arm_id,
                        cache_namespace=namespace,
                    )
                )
            blocks.append(
                {
                    "case_id": case_id,
                    "repeat_index": repeat_index,
                    "arm_order": list(MODEL_IDS),
                    "coordinates": coordinates,
                }
            )
    schedule = {
        "interface": "CounterbalancedRepeatSchedule@1",
        "case_ids": case_ids,
        "model_arm_ids": MODEL_IDS,
        "repeat_count": 5,
        "blocks": blocks,
    }
    deterministic_records = [
        _record(case_id, 0, arm_id)
        for case_id in case_ids
        for arm_id in DETERMINISTIC_IDS
    ]
    summaries = {
        arm_id: _summary(case_ids, repeats=1)
        for arm_id in DETERMINISTIC_IDS
    }
    summaries.update(
        {
            arm_id: _summary(case_ids, repeats=5)
            for arm_id in MODEL_IDS
        }
    )
    report: dict[str, object] = {
        "interface": REPORT_INTERFACE,
        "schema_version": REPORT_SCHEMA_VERSION,
        "inputs": {
            "fixture": {
                "path": str(fixture_path),
                "case_count": len(case_ids),
                "case_ids": case_ids,
                "sha256": fixture_sha256,
                "unchanged": True,
            }
        },
        "preregistration": {
            "deterministic_cell_ids": DETERMINISTIC_IDS,
            "model_backed_cell_ids": MODEL_IDS,
            "planned_cell_count": 30,
            "deterministic_repeats": 1,
            "minimum_uncached_model_repeats": 5,
            "model_schedule": schedule,
            "model_schedule_cid": cid_for_dag_json(schedule),
        },
        "execution": {
            "status": "complete",
            "scheduled_coordinate_count": 670,
            "observed_terminal_coordinate_count": 670,
            "missing_coordinate_count": 0,
            "deterministic": {"records": deterministic_records},
            "model_backed": {"records": model_records},
        },
        "statistics": {"arm_summaries": summaries},
        "acceptance": {
            "all_deterministic_cells_once": True,
            "all_model_backed_cells_five_uncached_repeats": True,
            "unchanged_pilot_cases_scored": True,
            "source_copy_gate_enforced": True,
            "polarity_gate_enforced": True,
            "full_coverage_gate_enforced": True,
            "per_case_and_aggregate_losses_reported": True,
            "uncertainty_reported": True,
            "costs_reported_with_missingness": True,
            "winner_manufactured": False,
        },
        "selection": {
            "outcome": "no_eligible_composition",
            "winner": None,
            "co_winner_arm_ids": [],
            "tie": False,
            "eligible_arm_ids": [],
            "ranked_eligible_arm_ids": [],
            "production_promotion_allowed": False,
            "eligibility_rule": (
                "source-copy exclusion, polarity preservation, and full "
                "coverage must pass for every frozen case/repeat coordinate"
            ),
            "selection_metric": (
                "lowest per-case-first macro mean end-to-end loss"
            ),
            "reasons": ["no arm passed all frozen gates"],
        },
    }
    report["report_cid"] = cid_for_dag_json(report)
    return report


def _refresh_report_cid(report: dict[str, object]) -> None:
    report["report_cid"] = cid_for_dag_json(
        {key: value for key, value in report.items() if key != "report_cid"}
    )


def _mark_arm_eligible(
    report: dict[str, object],
    arm_id: str,
    *,
    loss: float,
) -> None:
    execution = report["execution"]
    assert isinstance(execution, dict)
    records: list[dict[str, object]] = []
    for partition in ("deterministic", "model_backed"):
        group = execution[partition]
        assert isinstance(group, dict)
        raw_records = group["records"]
        assert isinstance(raw_records, list)
        records.extend(
            record
            for record in raw_records
            if isinstance(record, dict) and record["arm_id"] == arm_id
        )
    for record in records:
        record["status"] = "success"
        record["losses"] = {
            "forward": loss,
            "cycle": loss,
            "end_to_end": loss,
            "primary": loss,
        }
        record["gates"] = {
            "source_copy_exclusion": True,
            "polarity_preservation": True,
            "full_coverage": True,
            "selection_eligible": True,
        }

    statistics = report["statistics"]
    assert isinstance(statistics, dict)
    summaries = statistics["arm_summaries"]
    assert isinstance(summaries, dict)
    summary = summaries[arm_id]
    assert isinstance(summary, dict)
    per_case = summary["per_case"]
    assert isinstance(per_case, dict)
    for case_summary in per_case.values():
        assert isinstance(case_summary, dict)
        case_summary["status"] = "success"
        case_summary["losses"] = {
            "forward": loss,
            "cycle": loss,
            "end_to_end": loss,
        }
        case_summary["all_repeats_selection_eligible"] = True
    summary["all_cases_selection_eligible"] = True
    aggregate = summary["aggregate"]
    assert isinstance(aggregate, dict)
    for loss_summary in aggregate.values():
        assert isinstance(loss_summary, dict)
        loss_summary["mean"] = loss


def _set_selection(
    report: dict[str, object],
    *,
    eligible: list[str],
) -> None:
    statistics = report["statistics"]
    assert isinstance(statistics, dict)
    summaries = statistics["arm_summaries"]
    assert isinstance(summaries, dict)
    ranked = sorted(
        eligible,
        key=lambda arm_id: (
            summaries[arm_id]["aggregate"]["end_to_end"]["mean"],
            arm_id,
        ),
    )
    best = (
        summaries[ranked[0]]["aggregate"]["end_to_end"]["mean"]
        if ranked
        else None
    )
    co_winners = [
        arm_id
        for arm_id in ranked
        if summaries[arm_id]["aggregate"]["end_to_end"]["mean"] == best
    ]
    outcome = (
        "selected"
        if len(co_winners) == 1
        else "exact_tie"
        if co_winners
        else "no_eligible_composition"
    )
    report["selection"] = {
        "outcome": outcome,
        "winner": (
            {
                "arm_id": co_winners[0],
                "mean_end_to_end_loss": best,
                "evidence": "complete frozen evidence",
            }
            if len(co_winners) == 1
            else None
        ),
        "co_winner_arm_ids": co_winners,
        "tie": len(co_winners) > 1,
        "eligible_arm_ids": eligible,
        "ranked_eligible_arm_ids": ranked,
        "production_promotion_allowed": False,
        "eligibility_rule": "all frozen gates pass",
        "selection_metric": "lowest per-case-first macro mean end-to-end loss",
        "reasons": ["recomputed test evidence"],
    }
    _refresh_report_cid(report)


def test_complete_report_is_accepted(tmp_path: Path) -> None:
    fixture, case_ids, fixture_sha256 = _fixture(tmp_path)
    report = _complete_report(fixture, case_ids, fixture_sha256)

    validated = validate_composition_report(report, fixture_path=fixture)

    assert validated["status"] == "valid"
    assert validated["terminal_coordinate_count"] == 670
    assert validated["model_repeat_count"] == 5
    assert validated["selection_outcome"] == "no_eligible_composition"
    assert validated["eligible_arm_ids"] == []


def test_unique_selection_is_recomputed_from_terminal_records(
    tmp_path: Path,
) -> None:
    fixture, case_ids, fixture_sha256 = _fixture(tmp_path)
    report = _complete_report(fixture, case_ids, fixture_sha256)
    _mark_arm_eligible(report, DETERMINISTIC_IDS[0], loss=0.25)
    _set_selection(report, eligible=[DETERMINISTIC_IDS[0]])

    validated = validate_composition_report(report, fixture_path=fixture)

    assert validated["selection_outcome"] == "selected"
    assert validated["winner_arm_id"] == DETERMINISTIC_IDS[0]


def test_exact_tie_is_an_explicit_bounded_co_winner_set(
    tmp_path: Path,
) -> None:
    fixture, case_ids, fixture_sha256 = _fixture(tmp_path)
    report = _complete_report(fixture, case_ids, fixture_sha256)
    tied = DETERMINISTIC_IDS[:2]
    for arm_id in tied:
        _mark_arm_eligible(report, arm_id, loss=0.25)
    _set_selection(report, eligible=tied)

    validated = validate_composition_report(report, fixture_path=fixture)

    assert validated["selection_outcome"] == "exact_tie"
    assert validated["co_winner_arm_ids"] == sorted(tied)
    assert validated["bounded_tie"] is True


def test_forged_selection_outcome_is_rejected(tmp_path: Path) -> None:
    fixture, case_ids, fixture_sha256 = _fixture(tmp_path)
    report = _complete_report(fixture, case_ids, fixture_sha256)
    selection = report["selection"]
    assert isinstance(selection, dict)
    selection["outcome"] = "insufficient_evidence"
    _refresh_report_cid(report)

    with pytest.raises(
        ValueError,
        match="selection.outcome differs from recomputed",
    ):
        validate_composition_report(report, fixture_path=fixture)


def test_forged_winner_and_summary_are_rejected(tmp_path: Path) -> None:
    fixture, case_ids, fixture_sha256 = _fixture(tmp_path)
    report = _complete_report(fixture, case_ids, fixture_sha256)
    _mark_arm_eligible(report, DETERMINISTIC_IDS[0], loss=0.25)
    _set_selection(report, eligible=[DETERMINISTIC_IDS[0]])
    selection = report["selection"]
    assert isinstance(selection, dict)
    winner = selection["winner"]
    assert isinstance(winner, dict)
    winner["arm_id"] = DETERMINISTIC_IDS[1]
    _refresh_report_cid(report)

    with pytest.raises(ValueError, match="winner.arm_id differs"):
        validate_composition_report(report, fixture_path=fixture)

    winner["arm_id"] = DETERMINISTIC_IDS[0]
    statistics = report["statistics"]
    assert isinstance(statistics, dict)
    summaries = statistics["arm_summaries"]
    assert isinstance(summaries, dict)
    summaries[DETERMINISTIC_IDS[0]]["aggregate"]["end_to_end"]["mean"] = 0.1
    _refresh_report_cid(report)

    with pytest.raises(ValueError, match="aggregate.end_to_end.mean differs"):
        validate_composition_report(report, fixture_path=fixture)


def test_missing_model_results_are_not_terminal_evidence(
    tmp_path: Path,
) -> None:
    fixture, case_ids, fixture_sha256 = _fixture(tmp_path)
    report = _complete_report(fixture, case_ids, fixture_sha256)
    execution = report["execution"]
    assert isinstance(execution, dict)
    execution["status"] = "incomplete"
    execution["observed_terminal_coordinate_count"] = 20
    execution["missing_coordinate_count"] = 650
    execution["model_backed"] = {"records": []}
    report["report_cid"] = cid_for_dag_json(
        {key: value for key, value in report.items() if key != "report_cid"}
    )

    try:
        validate_composition_report(report, fixture_path=fixture)
    except ValueError as exc:
        assert "$.execution.status must be complete" in str(exc)
    else:
        raise AssertionError("incomplete report was accepted")


def test_cli_validation_does_not_run_inference(
    tmp_path: Path,
    capsys: object,
) -> None:
    fixture, case_ids, fixture_sha256 = _fixture(tmp_path)
    report = _complete_report(fixture, case_ids, fixture_sha256)
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")

    returncode = main(
        [
            "--fixture",
            str(fixture),
            "--validate-report",
            str(report_path),
        ]
    )

    assert returncode == 0
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert json.loads(captured.out)["status"] == "valid"
