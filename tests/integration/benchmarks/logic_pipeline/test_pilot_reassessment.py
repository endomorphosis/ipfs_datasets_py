"""Integration evidence for the source-bound HSSL-G140 pilot decision."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from benchmarks.logic_pipeline.contracts import canonical_json
from benchmarks.logic_pipeline import pilot_reassessment as gate


REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
ARTIFACT = REPOSITORY_ROOT / gate.DEFAULT_PILOT_REASSESSMENT_PATH
SNAPSHOT = REPOSITORY_ROOT / gate.DEFAULT_PILOT_REASSESSMENT_SNAPSHOT


@pytest.fixture(scope="module")
def report() -> dict[str, object]:
    return gate.load_pilot_reassessment_report(
        ARTIFACT, repository_root=REPOSITORY_ROOT
    )


def test_hssl_g140_evidence_symbol_is_ast_visible_and_complete() -> None:
    statement = gate.HSSLEV1409B38()

    assert callable(gate.HSSLEV1409B38)
    assert "complete unchanged pilot and development source receipts" in statement
    for required in (
        "front-end",
        "proof",
        "efficiency",
        "statistics",
        "safety",
        "Pareto",
        "exact deeply frozen",
        "fail-closed",
    ):
        assert required in statement


def test_checked_artifact_recomputes_all_560_source_receipts(
    report: dict[str, object],
) -> None:
    completeness = report["completeness"]
    reports = report["reports"]

    assert completeness == {
        "source_validated": True,
        "matrix_status": "complete",
        "coordinate_count": 560,
        "expected_coordinate_count": 560,
        "case_count": 20,
        "variant_ids": [
            "A0",
            "A1",
            "A2",
            "A3",
            "A4",
            "A5",
            "A6",
            "A7",
            "A8",
            "A9",
            "A10",
            "A11",
            "A12",
            "S1",
        ],
        "splits": ["pilot", "development"],
        "cache_modes": ["cold", "warm"],
        "status_counts": {
            "not_verified": 132,
            "rejected": 388,
            "unavailable": 40,
        },
        "all_coordinates_terminal": True,
        "typed_missingness_retained": True,
    }
    assert reports["proof"]["efficacy_observation_count"] == 520
    assert reports["proof"]["kernel_verified_rate"] == 0.0
    assert reports["efficiency"]["coordinate_count"] == 560
    assert reports["efficiency"]["wall_time_ms_total"] > 0
    assert reports["efficiency"]["resource_leases"] == 1580
    assert reports["statistics"]["paired_observations_per_candidate"] == 40
    assert reports["safety"][
        "kernel_verified_invalid_control_false_positive_count"
    ] == 0


def test_no_arm_is_invented_when_materiality_and_quality_do_not_pass(
    report: dict[str, object],
) -> None:
    candidates = report["candidate_evidence"]
    shortlist = report["shortlist"]
    pareto = report["reports"]["pareto"]

    assert len(candidates) == 12
    assert all(item["efficacy"]["kernel_verified_rate"] == 0.0 for item in candidates)
    assert all(
        item["cost"]["wall_time_ms_mean_per_coordinate"] > 0
        for item in candidates
    )
    assert all(item["eligible"] is False for item in candidates)
    assert all(
        "independent semantic-quality evidence unavailable"
        in item["ineligibility_reasons"]
        for item in candidates
    )
    assert pareto["eligible_candidate_ids"] == []
    assert pareto["eligible_nondominated_candidate_ids"] == []
    assert pareto["ranking_applied"] is False
    assert pareto["truncation_applied"] is False
    assert shortlist["selected_variant_ids"] == []
    assert shortlist["freeze_kind"] == "empty_due_to_no_eligible_candidate"
    assert report["holdout"]["authorized"] is False
    assert report["holdout"]["status"] == "sealed"
    assert len(report["remediation"]) == 4


def test_deep_freeze_binds_every_selection_input(
    report: dict[str, object],
) -> None:
    freeze = report["deep_freeze"]
    inputs = freeze["inputs"]

    assert freeze["frozen"] is True
    assert freeze["tuning_permitted"] is False
    assert freeze["holdout_outcomes_permitted"] is False
    assert freeze["selected_configurations"] == []
    assert set(inputs) == {
        "prompts",
        "policies",
        "model_identities",
        "cache_policy",
        "resource_policy",
        "thresholds",
        "source",
    }
    assert all(item["frozen"] is True for item in inputs.values())
    assert all(
        len(item["binding_sha256"]) == 64 for item in inputs.values()
    )
    without_digest = {
        key: value for key, value in freeze.items() if key != "freeze_sha256"
    }
    assert freeze["freeze_sha256"] == hashlib.sha256(
        canonical_json(without_digest).encode("utf-8")
    ).hexdigest()


def test_artifact_and_snapshot_are_strict_canonical_json(
    report: dict[str, object],
) -> None:
    artifact_text = ARTIFACT.read_text(encoding="utf-8")
    snapshot_text = SNAPSHOT.read_text(encoding="utf-8")
    snapshot = json.loads(snapshot_text)

    assert artifact_text == canonical_json(report) + "\n"
    assert snapshot_text == canonical_json(snapshot) + "\n"
    assert snapshot["results"]["artifact"]["bytes_sha256"] == hashlib.sha256(
        ARTIFACT.read_bytes()
    ).hexdigest()
    assert (
        snapshot["results"]["artifact"]["semantic_sha256"]
        == report["artifact_sha256"]
    )
    assert snapshot["results"]["holdout_authorized"] is False


def test_digest_tampering_is_rejected_before_source_recomputation(
    report: dict[str, object],
) -> None:
    tampered = dict(report)
    tampered["status"] = "complete"

    with pytest.raises(gate.PilotReassessmentError, match="digest changed"):
        gate.validate_pilot_reassessment_report(
            tampered, repository_root=REPOSITORY_ROOT
        )


def test_required_report_cli_validates_v2_artifact() -> None:
    process = subprocess.run(
        [
            sys.executable,
            "benchmarks/logic_pipeline/report.py",
            "--gate",
            "pilot-shortlist",
            "--artifact",
            gate.DEFAULT_PILOT_REASSESSMENT_PATH.as_posix(),
        ],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert process.returncode == 0, process.stderr
    summary = json.loads(process.stdout)
    assert summary["schema"] == gate.PILOT_REASSESSMENT_SCHEMA
    assert summary["outcome_cell_count"] == 560
    assert summary["selected_variant_ids"] == []
    assert summary["holdout_authorized"] is False
    assert summary["remediation_required"] is True
