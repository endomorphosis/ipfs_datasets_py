"""Trust-boundary tests for the HSSL-G100 decision and operator runbook."""

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


def _redigest(snapshot: dict[str, object]) -> dict[str, object]:
    results = snapshot["results"]
    assert isinstance(results, dict)
    results["artifact_sha256"] = hashlib.sha256(
        canonical_json(
            {
                key: item
                for key, item in results.items()
                if key != "artifact_sha256"
            }
        ).encode("utf-8")
    ).hexdigest()
    return snapshot


@pytest.fixture(scope="module")
def final_decision() -> dict[str, object]:
    return report.load_final_decision(repository_root=ROOT)


@pytest.fixture(scope="module")
def runbook_text() -> str:
    return (ROOT / report.DEFAULT_BENCHMARK_RUNBOOK_PATH).read_text(
        encoding="utf-8"
    )


def test_final_decision_marker_identity_and_stable_summary(
    final_decision: dict[str, object],
) -> None:
    results = final_decision["results"]
    assert isinstance(results, dict)

    assert report.HSSLEV1006B8A() == report.FINAL_DECISION_EVIDENCE
    assert results["evidence"] == report.HSSLEV1006B8A()
    assert results["evidence_symbol"] == "HSSLEV1006B8A"
    assert results["schema"] == report.FINAL_DECISION_SCHEMA
    assert report.final_decision_summary(final_decision) == {
        "section": "final-decision",
        "status": "valid",
        "artifact_sha256": results["artifact_sha256"],
        "architecture_outcome": "gather_more_evidence",
        "evidence_status": "inconclusive",
        "holdout_status": "sealed_unopened",
        "production_promotion_authorized": False,
        "component_decision_count": 4,
        "delegation_row_count": 14,
        "policy_decision_count": 4,
    }


def test_final_decision_binds_all_sources_to_live_bytes_and_semantics(
    final_decision: dict[str, object],
) -> None:
    results = final_decision["results"]
    assert isinstance(results, dict)
    sources = results["source_artifacts"]
    assert isinstance(sources, dict)

    assert list(sources) == ["baseline", "frontend", "proof", "pilot", "holdout"]
    for binding in sources.values():
        assert isinstance(binding, dict)
        source_path = ROOT / binding["path"]
        source_value = json.loads(source_path.read_text(encoding="utf-8"))
        assert binding["content_sha256"] == hashlib.sha256(
            source_path.read_bytes()
        ).hexdigest()
        semantic_sha256 = source_value.get("artifact_sha256")
        if semantic_sha256 is None:
            semantic_sha256 = hashlib.sha256(
                canonical_json(source_value).encode("utf-8")
            ).hexdigest()
        assert binding["semantic_sha256"] == semantic_sha256
        assert binding["schema"] == source_value["schema"]


def test_final_decision_rejects_fabricated_promotion_even_when_redigested(
    final_decision: dict[str, object],
) -> None:
    forged = copy.deepcopy(final_decision)
    forged["results"]["decision"]["production_promotion_authorized"] = True
    _redigest(forged)

    with pytest.raises(
        report.FinalDecisionValidationError,
        match="production_promotion_authorized",
    ):
        report.validate_final_decision(forged, repository_root=ROOT)


def test_final_decision_rejects_source_and_delegation_tampering(
    final_decision: dict[str, object],
) -> None:
    forged = copy.deepcopy(final_decision)
    forged["results"]["source_artifacts"]["holdout"]["content_sha256"] = "f" * 64
    _redigest(forged)
    with pytest.raises(
        report.FinalDecisionValidationError,
        match="holdout.content_sha256",
    ):
        report.validate_final_decision(forged, repository_root=ROOT)

    forged = copy.deepcopy(final_decision)
    forged["results"]["delegation_matrix"].pop()
    _redigest(forged)
    with pytest.raises(
        report.FinalDecisionValidationError,
        match="A0-A12 and S1",
    ):
        report.validate_final_decision(forged, repository_root=ROOT)


def test_final_decision_rejects_missingness_recast_as_measurement(
    final_decision: dict[str, object],
) -> None:
    forged = copy.deepcopy(final_decision)
    domain = forged["results"]["tradeoffs"]["domains"][0]
    domain["measurement_status"] = "measured"
    domain["values"]["kernel_verified_completion_rate"] = 0.0
    _redigest(forged)

    with pytest.raises(
        report.FinalDecisionValidationError,
        match="must remain not_observed",
    ):
        report.validate_final_decision(forged, repository_root=ROOT)


def test_runbook_binds_decision_and_complete_ordered_operating_flow(
    runbook_text: str,
    final_decision: dict[str, object],
) -> None:
    results = final_decision["results"]
    assert isinstance(results, dict)

    summary = report.validate_runbook(runbook_text, repository_root=ROOT)
    assert summary == {
        "section": "runbook",
        "status": "valid",
        "path": report.DEFAULT_BENCHMARK_RUNBOOK_PATH.as_posix(),
        "evidence_symbol": "HSSLEV1006B8A",
        "decision_artifact_sha256": results["artifact_sha256"],
        "heading_count": 17,
        "production_promotion_authorized": False,
    }


def test_runbook_rejects_missing_phase_or_automatic_promotion(
    runbook_text: str,
) -> None:
    missing_phase = runbook_text.replace("## Holdout gate\n", "")
    with pytest.raises(
        report.RunbookValidationError, match="headings changed"
    ):
        report.validate_runbook(missing_phase, repository_root=ROOT)

    unsafe = runbook_text.replace(
        "## Published decision\n",
        "## Published decision\n\nProduction promotion is authorized.\n",
    )
    with pytest.raises(
        report.RunbookValidationError,
        match="must not authorize production promotion",
    ):
        report.validate_runbook(unsafe, repository_root=ROOT)


@pytest.mark.parametrize(
    ("argument", "section"),
    [
        ("--validate-final-decision", "final-decision"),
        ("--validate-runbook", "runbook"),
    ],
)
def test_required_final_decision_clis(argument: str, section: str) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "benchmarks/logic_pipeline/report.py",
            argument,
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stderr == ""
    summary = json.loads(completed.stdout)
    assert summary["section"] == section
    assert summary["status"] == "valid"
    assert summary["production_promotion_authorized"] is False


def test_final_decision_loader_rejects_duplicate_json_keys(
    tmp_path: Path,
) -> None:
    duplicate = tmp_path / "decision.json"
    duplicate.write_text(
        '{"benchmark_script":"a","benchmark_script":"b"}\n',
        encoding="utf-8",
    )
    with pytest.raises(
        report.FinalDecisionValidationError, match="not strict JSON"
    ):
        report.load_final_decision(duplicate, repository_root=ROOT)
