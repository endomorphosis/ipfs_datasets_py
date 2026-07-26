"""Production contract tests for the paired holdout phase gate."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from benchmarks.logic_pipeline import ablation, holdout_gate, report
from benchmarks.logic_pipeline.cases import (
    FROZEN_CORPUS_MANIFEST_SHA256,
    FROZEN_SPLIT_SHA256,
    load_reviewed_corpus,
)
from benchmarks.logic_pipeline.contracts import Split, canonical_json


ROOT = Path(__file__).resolve().parents[4]


def _sha256_json(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _redigest(value: dict[str, object]) -> dict[str, object]:
    value["artifact_sha256"] = _sha256_json(
        {
            key: item
            for key, item in value.items()
            if key != "artifact_sha256"
        }
    )
    return value


@pytest.fixture(scope="module")
def canonical_report() -> dict[str, object]:
    return holdout_gate.load_holdout_gate_report(repository_root=ROOT)


def test_marker_proxy_and_canonical_identity(
    canonical_report: dict[str, object],
) -> None:
    marker = (
        "untouched paired holdout seal with prerequisite authorization, "
        "balanced ordering, strict budgets, kernel receipts, and replay"
    )
    assert holdout_gate.HSSLEV0909F29() == marker
    assert report.HSSLEV0909F29() == marker
    assert canonical_report["evidence"] == marker
    assert canonical_report["schema"] == holdout_gate.HOLDOUT_GATE_SCHEMA
    assert canonical_report["run_id"] == holdout_gate.HOLDOUT_GATE_RUN_ID


def test_source_binding_revalidates_pilot_gate(
    canonical_report: dict[str, object],
) -> None:
    binding = canonical_report["source_binding"]
    assert isinstance(binding, dict)
    source = ROOT / holdout_gate.PILOT_SOURCE_PATH
    source_value = json.loads(source.read_text(encoding="utf-8"))
    assert binding == {
        "kind": "pilot_shortlist_gate",
        "path": holdout_gate.PILOT_SOURCE_PATH.as_posix(),
        "schema": "ipfs-datasets.logic-pipeline-benchmark."
        "pilot-shortlist-gate.v1",
        "content_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "semantic_sha256": source_value["artifact_sha256"],
    }
    assert holdout_gate.ALLOWED_SOURCE_PATHS == {
        holdout_gate.PILOT_SOURCE_PATH.as_posix()
    }


def test_prerequisite_blocks_access_and_baseline_only_execution(
    canonical_report: dict[str, object],
) -> None:
    prerequisite = canonical_report["prerequisite"]
    access = canonical_report["access"]
    outcomes = canonical_report["outcomes"]
    decision = canonical_report["decision"]
    assert isinstance(prerequisite, dict)
    assert prerequisite["observed_status"] == "incomplete"
    assert prerequisite["selected_variant_ids"] == []
    assert prerequisite["holdout_authorized"] is False
    assert prerequisite["satisfied"] is False
    assert prerequisite["failure_kind"] == "incomplete_empty_shortlist"

    assert access == {
        "status": "unopened",
        "authorized": False,
        "access_log_ids": [],
        "audit_receipts": [],
        "first_access_recorded": False,
        "outcomes_inspected": False,
        "tuning_after_access": False,
        "cache_namespaces_opened": [],
    }
    assert isinstance(outcomes, dict)
    assert outcomes["status"] == "not_run"
    assert outcomes["scheduled_pair_count"] == 0
    assert outcomes["observed_pair_count"] == 0
    assert outcomes["case_results"] == []
    assert outcomes["baseline_only_execution_forbidden"] is True
    assert outcomes["efficacy_claimed"] is False
    assert decision["status"] == "blocked"
    assert decision["seal_status"] == "sealed_unopened"
    assert decision["holdout_untouched"] is True
    assert decision["paired_evaluation_complete"] is False


def test_holdout_manifest_is_frozen_without_inspecting_outcomes(
    canonical_report: dict[str, object],
) -> None:
    manifest = canonical_report["holdout_manifest"]
    corpus = load_reviewed_corpus()
    holdout = corpus.split_integrity.holdout
    assert isinstance(manifest, dict)
    assert manifest["corpus_manifest_sha256"] == (
        FROZEN_CORPUS_MANIFEST_SHA256
    )
    assert manifest["split_sha256"] == FROZEN_SPLIT_SHA256[Split.HOLDOUT]
    assert manifest["case_ids"] == list(holdout.case_ids)
    assert manifest["case_sha256s"] == list(holdout.case_sha256s)
    assert manifest["source_sha256s"] == list(holdout.source_sha256s)
    assert manifest["case_count"] == 10
    assert manifest["semantic_targets_inspected_by_gate"] is False
    assert manifest["outcomes_inspected_by_gate"] is False


def test_future_evaluation_contract_freezes_every_acceptance_boundary(
    canonical_report: dict[str, object],
) -> None:
    contract = canonical_report["evaluation_contract"]
    assert isinstance(contract, dict)
    assert contract["baseline_variant_id"] == "A0"
    assert contract["candidate_variant_ids"] == []
    assert contract["evaluation_variant_ids"] == []
    assert contract["cache_modes"] == ["cold", "warm"]
    assert contract["identical_case_manifest_required"] is True
    assert contract["identical_manifest_sha256"] == (
        FROZEN_SPLIT_SHA256[Split.HOLDOUT]
    )
    assert contract["expected_pair_count"] == 0
    assert contract["kernel_success_authority"] == (
        "independent_native_kernel"
    )
    assert contract["success_receipt_required"] is True
    assert contract["fresh_worktree_replay_required"] is True
    assert contract["sampled_failure_replay_required"] is True
    assert contract["tuning_after_first_access_forbidden"] is True
    assert contract["shadow_only"] is True
    assert contract["production_promotion_authorized"] is False

    order = contract["balanced_order"]
    budgets = contract["strict_budgets"]
    assert isinstance(order, dict)
    assert order["required"] is True
    assert order["scheduled_coordinates"] == []
    assert order["status"] == "not_scheduled_before_authorization"
    assert isinstance(budgets, dict)
    assert budgets["required"] is True
    assert budgets["execution_claimed"] is False
    assert budgets["resource_policy"]["max_model_instances"] == 1
    assert budgets["resource_policy"]["max_solver_processes"] == 1
    assert budgets["resource_policy"]["max_kernel_workers"] == 1


def test_all_nonbaseline_candidates_are_explicitly_ineligible(
    canonical_report: dict[str, object],
) -> None:
    eligibility = canonical_report["candidate_eligibility"]
    assert isinstance(eligibility, list)
    assert [item["variant_id"] for item in eligibility] == [
        f"A{index}" for index in range(1, 13)
    ]
    assert all(
        item["status"] == "ineligible_before_holdout"
        and item["selection_eligible"] is False
        and item["scheduled"] is False
        and item["reasons"]
        for item in eligibility
    )
    assert canonical_report["outcomes"][
        "capability_ineligible_candidate_count"
    ] == 12


def test_null_metrics_cover_every_required_domain(
    canonical_report: dict[str, object],
) -> None:
    metrics = canonical_report["metrics"]
    assert isinstance(metrics, dict)
    assert metrics["required_domains"] == [
        "safety",
        "quality",
        "latency",
        "resource",
        "routing",
    ]
    assert metrics["measured_domain_count"] == 0
    assert metrics["complete"] is False
    assert metrics["status"] == "not_applicable_before_authorization"
    assert metrics["cold_warm_collapsed"] is False
    domains = metrics["domains"]
    assert isinstance(domains, list)
    assert [item["domain"] for item in domains] == metrics[
        "required_domains"
    ]
    for item in domains:
        assert item["measurement_status"] == "not_observed"
        assert item["complete"] is False
        assert item["reason"]
        assert item["values"]
        assert all(value is None for value in item["values"].values())


def test_replay_is_not_claimed_and_does_not_invent_receipts(
    canonical_report: dict[str, object],
) -> None:
    replay = canonical_report["replay"]
    assert replay == {
        "status": "not_applicable_no_execution",
        "success_receipt_count": 0,
        "required_success_replay_count": 0,
        "completed_success_replay_count": 0,
        "sampled_failure_receipt_count": 0,
        "completed_failure_replay_count": 0,
        "all_observed_successes_replayed": True,
        "replay_claimed": False,
        "fresh_worktree_receipts": [],
    }


@pytest.mark.parametrize(
    ("section", "key", "replacement"),
    [
        ("prerequisite", "holdout_authorized", True),
        ("access", "access_log_ids", ["holdout-access-001"]),
        ("access", "outcomes_inspected", True),
        ("outcomes", "case_results", [{"invented": True}]),
        ("outcomes", "efficacy_claimed", True),
        ("replay", "replay_claimed", True),
        ("decision", "holdout_untouched", False),
        ("decision", "production_promotion_authorized", True),
    ],
)
def test_redigested_state_invention_is_rejected(
    canonical_report: dict[str, object],
    section: str,
    key: str,
    replacement: object,
) -> None:
    changed = copy.deepcopy(canonical_report)
    changed[section][key] = replacement
    with pytest.raises(
        holdout_gate.HoldoutGateError, match="allowlisted source evidence"
    ):
        holdout_gate.validate_holdout_gate_report(_redigest(changed))


def test_redigested_non_null_metric_is_rejected(
    canonical_report: dict[str, object],
) -> None:
    changed = copy.deepcopy(canonical_report)
    changed["metrics"]["domains"][0]["values"][
        "invalid_control_kernel_false_positive_count"
    ] = 0
    with pytest.raises(
        holdout_gate.HoldoutGateError, match="allowlisted source evidence"
    ):
        holdout_gate.validate_holdout_gate_report(_redigest(changed))


def test_digest_field_and_unknown_field_tampering_are_rejected(
    canonical_report: dict[str, object],
) -> None:
    changed = copy.deepcopy(canonical_report)
    changed["decision"]["status"] = "complete"
    with pytest.raises(holdout_gate.HoldoutGateError, match="digest"):
        holdout_gate.validate_holdout_gate_report(changed)

    changed = copy.deepcopy(canonical_report)
    changed["invented"] = True
    with pytest.raises(holdout_gate.HoldoutGateError, match="keys changed"):
        holdout_gate.validate_holdout_gate_report(changed)


def test_writer_round_trip_and_overwrite_protection(
    tmp_path: Path, canonical_report: dict[str, object]
) -> None:
    path = tmp_path / "holdout.json"
    written = holdout_gate.write_holdout_gate_report(
        canonical_report,
        path,
        repository_root=ROOT,
    )
    assert written == path
    assert path.read_text(encoding="utf-8") == (
        canonical_json(canonical_report) + "\n"
    )
    assert holdout_gate.load_holdout_gate_report(
        path, repository_root=ROOT
    ) == canonical_report
    with pytest.raises(holdout_gate.HoldoutGateError, match="overwrite"):
        holdout_gate.write_holdout_gate_report(
            canonical_report,
            path,
            repository_root=ROOT,
        )


@pytest.mark.parametrize(
    "payload",
    [
        "{}",
        '{"schema":"x","schema":"y"}\n',
        '{"value":NaN}\n',
        '{"value":1}\n\n',
    ],
)
def test_loader_rejects_noncanonical_or_nonstrict_json(
    tmp_path: Path, payload: str
) -> None:
    path = tmp_path / "bad.json"
    path.write_text(payload, encoding="utf-8")
    with pytest.raises(holdout_gate.HoldoutGateError):
        holdout_gate.load_holdout_gate_report(path, repository_root=ROOT)


def test_generic_ablation_executor_cannot_bypass_holdout_gate(
    tmp_path: Path,
) -> None:
    corpus = load_reviewed_corpus()
    holdout_cases = [
        case for case in corpus.cases if case.split is Split.HOLDOUT
    ]
    plan = ablation.build_ablation_plan(
        "unauthorized-holdout",
        holdout_cases,
        case_manifest_sha256=corpus.manifest_sha256,
        split=Split.HOLDOUT,
        seed=17291,
        variant_ids=("A0", "A1"),
        holdout_access_log_id="fake-access-id",
    )
    output = tmp_path / "must-not-exist"
    with pytest.raises(
        ablation.AblationValidationError,
        match="generic ablation execution is forbidden for holdout",
    ):
        ablation.execute_ablation(plan, {}, output_root=output)
    assert not output.exists()


def test_summary_and_required_cli(
    canonical_report: dict[str, object],
) -> None:
    expected = {
        "section": "holdout",
        "status": "blocked",
        "structurally_valid": True,
        "artifact_sha256": canonical_report["artifact_sha256"],
        "prerequisite_satisfied": False,
        "holdout_untouched": True,
        "holdout_access_authorized": False,
        "access_log_ids": [],
        "selected_variant_ids": [],
        "scheduled_pair_count": 0,
        "observed_pair_count": 0,
        "metrics_complete": False,
        "efficacy_claimed": False,
        "production_promotion_authorized": False,
    }
    assert holdout_gate.holdout_gate_summary(
        canonical_report, repository_root=ROOT
    ) == expected

    completed = subprocess.run(
        [
            sys.executable,
            "benchmarks/logic_pipeline/report.py",
            "--gate",
            "holdout",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == expected
    assert completed.stderr == ""
