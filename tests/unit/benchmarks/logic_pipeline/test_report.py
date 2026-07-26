from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from benchmarks.logic_pipeline import report
from benchmarks.logic_pipeline.contracts import canonical_json


ROOT = Path(__file__).resolve().parents[4]


def _redigest(value: dict[str, object]) -> dict[str, object]:
    value["artifact_sha256"] = hashlib.sha256(
        canonical_json(
            {key: item for key, item in value.items() if key != "artifact_sha256"}
        ).encode("utf-8")
    ).hexdigest()
    return value


def _reanalyze(value: dict[str, object]) -> dict[str, object]:
    value["analysis"] = report.derive_proof_analysis(
        value["observations"]  # type: ignore[arg-type]
    )
    return _redigest(value)


def test_default_report_covers_the_exact_paired_proof_scope() -> None:
    value = report.load_proof_report(ROOT / report.DEFAULT_PROOF_REPORT_PATH)

    assert callable(report.HSSLEV0526A41)
    assert value["evidence"] == report.HSSLEV0526A41()
    assert value["execution_mode"] == "capability_preflight"
    assert value["eligible_case_ids"] == list(report.ELIGIBLE_CASE_IDS)
    assert value["excluded_case_ids"] == list(report.EXCLUDED_CASE_IDS)
    assert value["primary_variant_ids"] == list(report.PRIMARY_VARIANT_IDS)
    assert value["diagnostic_variant_ids"] == ["S1"]
    assert len(value["observations"]) == 154

    coordinates = {
        (row["case_id"], row["cache_mode"], row["variant_id"])
        for row in value["observations"]
    }
    assert len(coordinates) == 154
    for case_id in report.ELIGIBLE_CASE_IDS:
        for mode in report.CACHE_MODES:
            assert (case_id, mode, "A2") in coordinates
            assert (case_id, mode, "A12") in coordinates
            assert (case_id, mode, "S1") in coordinates


def test_ordering_policy_is_not_inferred_from_canonical_stage_order() -> None:
    value = report.create_capability_preflight_report()
    rows = {
        (row["variant_id"], row["cache_mode"], row["case_id"]): row
        for row in value["observations"]
    }

    assert rows[("A2", "cold", "pilot-p01")]["proof_order"] == ["hammer"]
    assert rows[("A4", "cold", "pilot-p01")]["proof_order"] == [
        "hammer",
        "leanstral",
    ]
    assert rows[("A6", "cold", "pilot-p01")]["proof_order"] == [
        "leanstral",
        "hammer",
    ]
    assert rows[("A9", "cold", "pilot-p01")]["proof_order"] == ["leanstral"]
    assert rows[("A12", "warm", "pilot-p09")]["proof_order"] == [
        "leanstral",
        "hammer",
    ]
    assert rows[("S1", "warm", "pilot-p09")]["proof_order"] == []


def test_verified_result_requires_kernel_authority_and_receipt() -> None:
    value = copy.deepcopy(report.create_capability_preflight_report())
    row = value["observations"][0]
    row["status"] = "verified"
    row["missing_reason"] = None
    with pytest.raises(report.ProofReportError, match="native-kernel"):
        report.validate_proof_report(value)

    row["verification_authority"] = "native_kernel"
    row["kernel_accepted"] = True
    with pytest.raises(report.ProofReportError, match="native-kernel"):
        report.validate_proof_report(value)


def test_metric_derivation_reports_component_wins_and_missing_premise_gold() -> None:
    value = copy.deepcopy(report.create_capability_preflight_report())
    value["execution_mode"] = "measured"
    row = next(
        item
        for item in value["observations"]
        if item["variant_id"] == "A2"
        and item["cache_mode"] == "cold"
        and item["case_id"] == "pilot-p01"
    )
    row.update(
        {
            "status": "verified",
            "verification_authority": "native_kernel",
            "kernel_accepted": True,
            "kernel_receipt_sha256": "a" * 64,
            "verified_source": "hammer",
            "missing_reason": None,
            "total_wall_time_ms": 12.5,
        }
    )
    row["hammer"].update(
        {
            "invoked": True,
            "candidate_created": True,
            "reconstruction_attempted": True,
            "reconstruction_succeeded": True,
            "wall_time_ms": 10.0,
        }
    )
    _reanalyze(value)
    metric = next(
        item
        for item in value["analysis"]["primary_metrics"]
        if item["variant_id"] == "A2" and item["cache_mode"] == "cold"
    )
    assert metric["kernel_verified_count"] == 1
    assert metric["kernel_verified_rate"] == 1.0
    assert metric["hammer_candidate_count"] == 1
    assert metric["reconstruction_success_rate"] == 1.0
    assert metric["hammer_unique_verified_count"] == 1
    assert metric["premise_recall_at_budget"] is None
    assert metric["premise_recall_missing_reason"] == (
        "gold_premise_set_unavailable"
    )
    with pytest.raises(report.ProofReportError, match="full case-result"):
        report.validate_proof_report(value)


def test_s1_claims_stay_non_authoritative_and_out_of_primary_metrics() -> None:
    value = copy.deepcopy(report.create_capability_preflight_report())
    value["execution_mode"] = "measured"
    row = next(
        item for item in value["observations"] if item["variant_id"] == "S1"
    )
    row["status"] = "not_verified"
    row["missing_reason"] = None
    row["model_claimed_verified"] = True
    _reanalyze(value)

    assert len(value["analysis"]["primary_metrics"]) == 20
    assert value["analysis"]["s1_diagnostic"] == {
        "attempt_count": 14,
        "model_verified_claim_count": 1,
        "native_kernel_verified_count": 0,
        "included_in_primary_metrics": False,
    }

    forged = copy.deepcopy(value)
    s1 = next(
        item for item in forged["observations"] if item["variant_id"] == "S1"
    )
    s1.update(
        {
            "status": "verified",
            "verification_authority": "native_kernel",
            "kernel_accepted": True,
            "kernel_receipt_sha256": "b" * 64,
            "missing_reason": None,
        }
    )
    with pytest.raises(report.ProofReportError, match="S1"):
        report.validate_proof_report(forged)


def test_tamper_missing_cell_duplicate_and_analysis_changes_fail_closed() -> None:
    value = copy.deepcopy(report.create_capability_preflight_report())
    value["observations"].pop()
    with pytest.raises(report.ProofReportError, match="incomplete"):
        report.validate_proof_report(value)

    value = copy.deepcopy(report.create_capability_preflight_report())
    value["observations"][-1] = copy.deepcopy(value["observations"][0])
    with pytest.raises(report.ProofReportError, match="duplicate"):
        report.validate_proof_report(value)

    value = copy.deepcopy(report.create_capability_preflight_report())
    value["analysis"]["coverage"]["observed_observation_count"] = 153
    _redigest(value)
    with pytest.raises(report.ProofReportError, match="differs"):
        report.validate_proof_report(value)

    value = copy.deepcopy(report.create_capability_preflight_report())
    value["artifact_sha256"] = "f" * 64
    with pytest.raises(report.ProofReportError, match="digest"):
        report.validate_proof_report(value)


def test_loader_rejects_noncanonical_and_duplicate_json(tmp_path: Path) -> None:
    value = report.create_capability_preflight_report()
    noncanonical = tmp_path / "noncanonical.json"
    noncanonical.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(report.ProofReportError, match="canonical"):
        report.load_proof_report(noncanonical)

    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"schema":"a","schema":"b"}\n', encoding="utf-8")
    with pytest.raises(report.ProofReportError, match="strict"):
        report.load_proof_report(duplicate)


def test_required_cli_validates_checked_in_evidence() -> None:
    process = subprocess.run(
        [
            sys.executable,
            "benchmarks/logic_pipeline/report.py",
            "--section",
            "proof",
            "--validate",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert process.returncode == 0, process.stderr
    summary = json.loads(process.stdout)
    assert summary == {
        "artifact_sha256": (
            "dae3faa6af66d5a78156dad69fb93151c8f600a1d7f07bada8e7ae6943eef9b9"
        ),
        "execution_mode": "capability_preflight",
        "kernel_verified_count": 0,
        "missingness_retained": True,
        "observation_count": 154,
        "s1_included_in_primary_metrics": False,
        "section": "proof",
        "status": "valid",
    }
