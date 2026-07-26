"""Integration evidence for the source-bound HSSL-G150 holdout decision."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from benchmarks.logic_pipeline.contracts import canonical_json
from benchmarks.logic_pipeline import holdout_reassessment as gate
from benchmarks.logic_pipeline import report as report_cli


REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
ARTIFACT = REPOSITORY_ROOT / gate.DEFAULT_HOLDOUT_REASSESSMENT_PATH
SNAPSHOT = REPOSITORY_ROOT / gate.DEFAULT_HOLDOUT_REASSESSMENT_SNAPSHOT


@pytest.fixture(scope="module")
def holdout_report() -> dict[str, object]:
    return gate.load_holdout_reassessment_report(
        ARTIFACT, repository_root=REPOSITORY_ROOT
    )


def _redigest(value: dict[str, object]) -> dict[str, object]:
    value["artifact_sha256"] = hashlib.sha256(
        canonical_json(
            {
                key: item
                for key, item in value.items()
                if key != "artifact_sha256"
            }
        ).encode("utf-8")
    ).hexdigest()
    return value


def test_hssl_g150_evidence_symbol_is_ast_visible_and_complete() -> None:
    statement = gate.HSSLEV1507C49()

    assert callable(gate.HSSLEV1507C49)
    assert report_cli.HSSLEV1507C49() == statement
    for required in (
        "exact HSSL-G140-authorized",
        "source-first access audit",
        "identical frozen manifests",
        "counterbalanced cold and warm",
        "native-kernel authority",
        "terminal pair accounting",
        "no tuning or substitution",
        "zero-activity sealed result",
    ):
        assert required in statement


def test_exact_hssl_g140_source_is_revalidated(
    holdout_report: dict[str, object],
) -> None:
    source = (
        REPOSITORY_ROOT / gate.DEFAULT_PILOT_REASSESSMENT_PATH
    )
    pilot = json.loads(source.read_text(encoding="utf-8"))
    binding = holdout_report["source_binding"]
    prerequisite = holdout_report["prerequisite"]

    assert binding == {
        "kind": "hssl_g140_pilot_authorization",
        "path": gate.DEFAULT_PILOT_REASSESSMENT_PATH.as_posix(),
        "schema": (
            "ipfs-datasets.logic-pipeline-benchmark."
            "reassessment-pilot-shortlist.v1"
        ),
        "bytes_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "semantic_sha256": pilot["artifact_sha256"],
        "deep_freeze_sha256": pilot["deep_freeze"]["freeze_sha256"],
        "source_validated": True,
    }
    assert prerequisite["goal_id"] == "HSSL-G140"
    assert prerequisite["observed_status"] == "incomplete"
    assert prerequisite["shortlist_frozen"] is True
    assert prerequisite["selected_variant_ids"] == []
    assert prerequisite["holdout_authorized"] is False
    assert prerequisite["authorization_sha256"] is None
    assert prerequisite["satisfied"] is False


def test_unauthorized_gate_stops_before_all_holdout_activity(
    holdout_report: dict[str, object],
) -> None:
    audit = holdout_report["authorization_audit"]
    access = holdout_report["access"]
    outcomes = holdout_report["outcomes"]
    decision = holdout_report["decision"]

    assert audit["checks"]["source_revalidated"] is True
    assert audit["checks"]["shortlist_frozen"] is True
    assert audit["checks"]["shortlist_nonempty"] is False
    assert audit["checks"]["decision_complete"] is False
    assert audit["checks"]["holdout_explicitly_authorized"] is False
    assert audit["satisfied"] is False
    assert audit["rejection_stage"] == "before_holdout_activity"
    assert audit["reviewed_holdout_inputs_loaded"] is False
    assert audit["holdout_semantics_inspected"] is False
    assert audit["execution_namespace_created"] is False
    assert audit["execution_write_count"] == 0
    assert audit["backend_call_count"] == 0

    assert access == {
        "status": "unopened",
        "authorized": False,
        "access_audit_count": 0,
        "access_audit_sha256s": [],
        "first_access_recorded": False,
        "cache_namespaces_opened": [],
        "execution_namespace_created": False,
        "execution_write_count": 0,
        "backend_call_count": 0,
        "outcomes_inspected": False,
        "tuning_after_access": False,
    }
    assert outcomes["status"] == "not_run"
    assert outcomes["scheduled_pair_count"] == 0
    assert outcomes["observed_pair_count"] == 0
    assert outcomes["terminal_pair_count"] == 0
    assert outcomes["case_results"] == []
    assert outcomes["efficacy_claimed"] is False
    assert decision["status"] == "blocked"
    assert decision["seal_status"] == "sealed_unopened"
    assert decision["holdout_untouched"] is True


def test_public_manifest_metadata_is_bound_without_reviewed_input_access(
    holdout_report: dict[str, object],
) -> None:
    manifest = holdout_report["holdout_manifest"]

    assert manifest["corpus_manifest_sha256"] == (
        "58b9122c24e4d9d4cc2ad01c7437dfeb45c80ad2535df769d81a89acbda24a26"
    )
    assert manifest["split_sha256"] == (
        "c7b969ed19a1248143740068e2853ca6132ba3d65dfeec4133e37fad55dbab4a"
    )
    assert manifest["case_count"] == 10
    assert len(manifest["case_ids"]) == 10
    assert len(manifest["case_sha256s"]) == 10
    assert len(manifest["source_sha256s"]) == 10
    assert manifest["reviewed_inputs_loaded"] is False
    assert manifest["semantic_targets_inspected"] is False
    assert manifest["outcomes_inspected"] is False


def test_frozen_contract_preserves_complete_future_pairing_boundary(
    holdout_report: dict[str, object],
) -> None:
    contract = holdout_report["frozen_execution_contract"]

    assert contract["baseline_variant_id"] == "A0"
    assert contract["candidate_variant_ids"] == []
    assert contract["evaluation_variant_ids"] == []
    assert contract["cache_modes"] == ["cold", "warm"]
    assert contract["expected_pair_count"] == 0
    assert contract["balanced_order"]["required"] is True
    assert contract["balanced_order"]["scheduled_coordinates"] == []
    assert contract["cache_namespaces_isolated"] is True
    assert contract["identical_case_and_source_manifest_required"] is True
    assert contract["access_audit_required_before_activity"] is True
    assert contract["one_access_audit_per_run_contract"] is True
    assert contract["native_kernel_only_success"] is True
    assert contract["every_scheduled_pair_terminal"] is True
    assert contract["baseline_only_execution_forbidden"] is True
    assert contract["arm_substitution_forbidden"] is True
    assert contract["fallback_forbidden"] is True
    assert contract["resume_forbidden"] is True
    assert contract["tuning_after_first_access_forbidden"] is True
    assert contract["production_promotion_authorized"] is False
    assert contract["protocol_sha256"] == (
        "a12067c4239b9628fde065db3fe10e623148c95a55891a642306e0c90dee8fa3"
    )
    assert contract["registry_sha256"] == (
        "53a106ddd6c68af445d0a3a912b0d7d09e04c6b23500d4c6362bb5c089f2e44f"
    )


def test_all_candidate_dispositions_remain_unscheduled(
    holdout_report: dict[str, object],
) -> None:
    dispositions = holdout_report["candidate_dispositions"]

    assert [item["variant_id"] for item in dispositions] == [
        f"A{index}" for index in range(1, 13)
    ]
    assert all(item["eligible"] is False for item in dispositions)
    assert all(item["scheduled"] is False for item in dispositions)
    assert all(item["ineligibility_reasons"] for item in dispositions)


def test_unobserved_metrics_remain_null_not_synthetic_zero(
    holdout_report: dict[str, object],
) -> None:
    metrics = holdout_report["metrics"]

    assert metrics["required_domains"] == list(gate.METRIC_DOMAINS)
    assert metrics["measured_domain_count"] == 0
    assert metrics["complete"] is False
    assert metrics["missingness_synthesized_as_zero"] is False
    assert metrics["cold_warm_collapsed"] is False
    for domain in metrics["domains"]:
        assert domain["status"] == "not_observed"
        assert domain["complete"] is False
        assert domain["reason"]
        assert all(value is None for value in domain["values"].values())


def test_artifact_and_snapshot_are_canonical_and_cross_bound(
    holdout_report: dict[str, object],
) -> None:
    artifact_text = ARTIFACT.read_text(encoding="utf-8")
    snapshot_text = SNAPSHOT.read_text(encoding="utf-8")
    snapshot = json.loads(snapshot_text)

    assert artifact_text == canonical_json(holdout_report) + "\n"
    assert snapshot_text == canonical_json(snapshot) + "\n"
    assert snapshot["results"]["artifact"]["bytes_sha256"] == hashlib.sha256(
        ARTIFACT.read_bytes()
    ).hexdigest()
    assert snapshot["results"]["artifact"]["semantic_sha256"] == (
        holdout_report["artifact_sha256"]
    )
    assert snapshot["results"]["holdout_authorized"] is False
    assert snapshot["results"]["activity"] == {
        "scheduled_pair_count": 0,
        "observed_pair_count": 0,
        "execution_write_count": 0,
        "backend_call_count": 0,
    }


def test_digest_and_redigested_state_invention_are_rejected(
    holdout_report: dict[str, object],
) -> None:
    changed = copy.deepcopy(holdout_report)
    changed["access"]["backend_call_count"] = 1
    with pytest.raises(
        gate.HoldoutReassessmentError, match="digest changed"
    ):
        gate.validate_holdout_reassessment_report(
            changed, repository_root=REPOSITORY_ROOT
        )

    redigested = copy.deepcopy(holdout_report)
    redigested["decision"]["holdout_untouched"] = False
    with pytest.raises(
        gate.HoldoutReassessmentError,
        match="differs from recomputed source evidence",
    ):
        gate.validate_holdout_reassessment_report(
            _redigest(redigested), repository_root=REPOSITORY_ROOT
        )


def test_required_report_cli_validates_v2_artifact() -> None:
    process = subprocess.run(
        [
            sys.executable,
            "benchmarks/logic_pipeline/report.py",
            "--gate",
            "holdout",
            "--artifact",
            gate.DEFAULT_HOLDOUT_REASSESSMENT_PATH.as_posix(),
        ],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert process.returncode == 0, process.stderr
    summary = json.loads(process.stdout)
    assert summary["schema"] == gate.HOLDOUT_REASSESSMENT_SCHEMA
    assert summary["status"] == "blocked"
    assert summary["holdout_untouched"] is True
    assert summary["selected_variant_ids"] == []
    assert summary["scheduled_pair_count"] == 0
    assert summary["execution_write_count"] == 0
    assert summary["backend_call_count"] == 0
