"""Tests for the complete SRT-014 frozen-report validator."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

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
            case_id: {"status": "failed", "observed_repeats": repeats}
            for case_id in case_ids
        },
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
            "outcome": "insufficient_evidence",
            "winner": None,
            "eligible_arm_ids": [],
        },
    }
    report["report_cid"] = cid_for_dag_json(report)
    return report


def test_complete_report_is_accepted(tmp_path: Path) -> None:
    fixture, case_ids, fixture_sha256 = _fixture(tmp_path)
    report = _complete_report(fixture, case_ids, fixture_sha256)

    validated = validate_composition_report(report, fixture_path=fixture)

    assert validated["status"] == "valid"
    assert validated["terminal_coordinate_count"] == 670
    assert validated["model_repeat_count"] == 5


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
