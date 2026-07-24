"""Trust-boundary tests for the HSSL-G170 replacement decision and runbook."""

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
from benchmarks.logic_pipeline.reassessment_reports import (
    REQUIRED_DECISION_DOMAINS,
)


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


def test_replacement_marker_identity_and_stable_summary(
    final_decision: dict[str, object],
) -> None:
    results = final_decision["results"]
    assert isinstance(results, dict)

    assert report.HSSLEV1703E61() == report.REASSESSMENT_FINAL_DECISION_EVIDENCE
    assert results["evidence"] == report.HSSLEV1703E61()
    assert results["evidence_symbol"] == "HSSLEV1703E61"
    assert results["schema"] == report.REASSESSMENT_FINAL_DECISION_SCHEMA
    assert report.final_decision_summary(final_decision) == {
        "section": "final-decision",
        "status": "valid",
        "artifact_sha256": results["artifact_sha256"],
        "architecture_outcome": "gather_more_evidence",
        "evidence_status": "measured_pilot_development_no_eligible_candidate",
        "holdout_status": "sealed_unopened",
        "production_promotion_authorized": False,
        "component_decision_count": 4,
        "delegation_row_count": 14,
        "policy_decision_count": 4,
    }


def test_replacement_preserves_v1_and_binds_complete_live_source_graph(
    final_decision: dict[str, object],
) -> None:
    results = final_decision["results"]
    assert isinstance(results, dict)
    predecessor = results["supersedes"]
    assert isinstance(predecessor, dict)
    assert predecessor == {
        "path": report.LEGACY_FINAL_DECISION_PATH.as_posix(),
        "schema": report.FINAL_DECISION_SCHEMA,
        "content_sha256": (
            "0e53798d3f1deaab040cf99f10034644f421ffd51f15090a948aa7085041a84e"
        ),
        "semantic_sha256": (
            "80823442e5115b2f499a2e77a11817dff555494ca0ecccfc79e59cbf423b7cce"
        ),
        "relationship": "immutable_predecessor",
        "preserved": True,
    }
    legacy = report.load_final_decision(
        report.LEGACY_FINAL_DECISION_PATH, repository_root=ROOT
    )
    assert legacy["results"]["evidence_symbol"] == "HSSLEV1006B8A"

    sources = results["source_artifacts"]
    assert isinstance(sources, dict)
    assert list(sources) == [
        "holdout",
        "matrix",
        "pilot",
        "replay",
        "reports",
        "statistics",
    ]
    for binding in sources.values():
        assert isinstance(binding, dict)
        source_path = ROOT / binding["path"]
        document = json.loads(source_path.read_text(encoding="utf-8"))
        assert binding["content_sha256"] == hashlib.sha256(
            source_path.read_bytes()
        ).hexdigest()
        source_results = document.get("results", {})
        semantic_sha256 = document.get(
            "artifact_sha256", source_results.get("artifact_sha256")
        )
        if semantic_sha256 is None:
            semantic_sha256 = hashlib.sha256(
                canonical_json(document).encode("utf-8")
            ).hexdigest()
        assert binding["semantic_sha256"] == semantic_sha256

    graph = results["source_graph"]
    assert graph == {
        "validated": True,
        "pilot_development_case_result_count": 560,
        "statistics_pair_count": 480,
        "holdout_case_result_count": 0,
        "replay_receipt_count": 0,
        "untraced_claim_count": 0,
        "independent_native_kernel_is_only_success_authority": True,
    }


def test_replacement_disposes_every_component_arm_policy_and_domain(
    final_decision: dict[str, object],
) -> None:
    results = final_decision["results"]
    assert isinstance(results, dict)

    components = results["component_decisions"]
    assert [row["component"] for row in components] == [
        "spacy",
        "symai",
        "hammer",
        "leanstral",
    ]
    assert all(
        row["production_responsibility_added"] is False
        and row["production_authorized"] is False
        and row["bounded_experimental_responsibility"]
        for row in components
    )

    matrix = results["delegation_matrix"]
    assert [row["variant_id"] for row in matrix] == [
        *(f"A{index}" for index in range(13)),
        "S1",
    ]
    assert matrix[0]["disposition"] == "retained_current_reference_not_selected"
    assert all(
        row["disposition"] == "rejected_current_reassessment_ineligible"
        for row in matrix[1:13]
    )
    assert matrix[-1]["disposition"] == (
        "rejected_diagnostic_only_never_candidate"
    )
    assert all(
        row["production_authorized"] is False
        and row["holdout_observed_pair_count"] == 0
        and row["measured_evidence"]["coordinate_count"] == 40
        for row in matrix
    )

    policies = results["policy_decisions"]
    assert [row["policy"] for row in policies] == [
        "P0_ALWAYS_ON",
        "P1_DETERMINISTIC_FIRST",
        "P2_PROOF_FAMILY",
        "P3_BOUNDED_LEARNED",
    ]
    assert all(
        row["selected"] is False
        and row["production_authorized"] is False
        and row["disposition"]
        == "rejected_no_eligible_variant_or_holdout_evidence"
        for row in policies
    )

    tradeoffs = results["tradeoffs"]
    assert tradeoffs["required_domains"] == list(REQUIRED_DECISION_DOMAINS)
    assert [row["domain"] for row in tradeoffs["domains"]] == list(
        REQUIRED_DECISION_DOMAINS
    )
    assert tradeoffs["holdout_pair_count"] == 0
    assert tradeoffs["holdout_measured_domain_count"] == 0
    assert tradeoffs["missingness_synthesized_as_zero"] is False
    assert all(
        row["holdout_status"] == "not_applicable_before_authorization"
        and row["holdout_values"] is None
        and row["values"]["holdout"] is None
        for row in tradeoffs["domains"]
    )
    domain_by_name = {row["domain"]: row for row in tradeoffs["domains"]}
    assert (
        domain_by_name["quality"]["values"]["pilot_development"][
            "kernel_verified_rate"
        ]
        == 0.0
    )
    assert (
        domain_by_name["resources"]["values"]["pilot_development"][
            "resource_leases"
        ]
        == 1580
    )
    assert domain_by_name["complexity_pareto"]["values"][
        "pilot_development"
    ]["eligible_candidate_ids"] == []


def test_replacement_rejects_promotion_routing_and_holdout_invention(
    final_decision: dict[str, object],
) -> None:
    for field in (
        "production_promotion_authorized",
        "production_routing_changed",
        "paired_holdout_evidence_available",
        "replay_claimed",
    ):
        forged = copy.deepcopy(final_decision)
        forged["results"]["decision"][field] = True
        _redigest(forged)
        with pytest.raises(
            report.FinalDecisionValidationError,
            match="must not invent holdout/replay evidence",
        ):
            report.validate_final_decision(forged, repository_root=ROOT)


def test_replacement_rejects_arm_policy_and_missingness_tampering(
    final_decision: dict[str, object],
) -> None:
    forged = copy.deepcopy(final_decision)
    forged["results"]["delegation_matrix"].pop()
    _redigest(forged)
    with pytest.raises(
        report.FinalDecisionValidationError, match="cover A0-A12 and S1"
    ):
        report.validate_final_decision(forged, repository_root=ROOT)

    forged = copy.deepcopy(final_decision)
    forged["results"]["policy_decisions"][0]["selected"] = True
    _redigest(forged)
    with pytest.raises(
        report.FinalDecisionValidationError, match="reject P0-P3"
    ):
        report.validate_final_decision(forged, repository_root=ROOT)

    forged = copy.deepcopy(final_decision)
    quality = forged["results"]["tradeoffs"]["domains"][1]
    assert quality["domain"] == "quality"
    quality["holdout_status"] = "measured"
    quality["holdout_values"] = {"kernel_verified_rate": 0.0}
    _redigest(forged)
    with pytest.raises(
        report.FinalDecisionValidationError, match="typed null"
    ):
        report.validate_final_decision(forged, repository_root=ROOT)


def test_replacement_rejects_redigested_source_binding_tampering(
    final_decision: dict[str, object],
) -> None:
    forged = copy.deepcopy(final_decision)
    forged["results"]["source_artifacts"]["holdout"][
        "content_sha256"
    ] = "f" * 64
    _redigest(forged)

    with pytest.raises(
        report.FinalDecisionValidationError,
        match="differs from the validated source graph",
    ):
        report.validate_final_decision(forged, repository_root=ROOT)


def test_runbook_binds_replacement_and_complete_ordered_flow(
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
        "evidence_symbol": "HSSLEV1703E61",
        "decision_artifact_sha256": results["artifact_sha256"],
        "heading_count": 17,
        "production_promotion_authorized": False,
    }


def test_runbook_rejects_metadata_phase_and_automatic_promotion(
    runbook_text: str,
) -> None:
    old_marker = runbook_text.replace(
        "Evidence: HSSLEV1703E61", "Evidence: HSSLEV1006B8A"
    )
    with pytest.raises(
        report.RunbookValidationError, match="metadata 'Evidence'"
    ):
        report.validate_runbook(old_marker, repository_root=ROOT)

    duplicate = runbook_text.replace(
        "Evidence: HSSLEV1703E61\n",
        "Evidence: HSSLEV1703E61\nEvidence: HSSLEV1703E61\n",
    )
    with pytest.raises(
        report.RunbookValidationError, match="duplicated"
    ):
        report.validate_runbook(duplicate, repository_root=ROOT)

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
        report.RunbookValidationError, match="must not authorize"
    ):
        report.validate_runbook(unsafe, repository_root=ROOT)


@pytest.mark.parametrize(
    ("arguments", "section"),
    [
        (
            [
                "--validate-final-decision",
                "--artifact",
                (
                    "docs/performance_snapshots/"
                    "2026-07-24_hammer_symai_spacy_leanstral_"
                    "final_decision_v2.json"
                ),
            ],
            "final-decision",
        ),
        (["--validate-runbook"], "runbook"),
    ],
)
def test_required_replacement_decision_clis(
    arguments: list[str], section: str
) -> None:
    completed = subprocess.run(
        [sys.executable, "benchmarks/logic_pipeline/report.py", *arguments],
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


def test_replacement_loader_enforces_strict_canonical_json(
    tmp_path: Path,
    final_decision: dict[str, object],
) -> None:
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text(
        '{"benchmark_script":"a","benchmark_script":"b"}\n',
        encoding="utf-8",
    )
    with pytest.raises(
        report.FinalDecisionValidationError, match="not strict JSON"
    ):
        report.load_final_decision(duplicate, repository_root=ROOT)

    noncanonical = tmp_path / "noncanonical.json"
    noncanonical.write_text(
        json.dumps(final_decision, indent=2) + "\n", encoding="utf-8"
    )
    with pytest.raises(
        report.FinalDecisionValidationError, match="not canonical newline JSON"
    ):
        report.load_final_decision(noncanonical, repository_root=ROOT)

    nonfinite_value = copy.deepcopy(final_decision)
    nonfinite_value["results"]["tradeoffs"]["holdout_pair_count"] = float("nan")
    nonfinite = tmp_path / "nonfinite.json"
    nonfinite.write_text(
        json.dumps(nonfinite_value, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(
        report.FinalDecisionValidationError, match="not strict finite JSON"
    ):
        report.load_final_decision(nonfinite, repository_root=ROOT)
