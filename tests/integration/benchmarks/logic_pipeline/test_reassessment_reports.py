"""Integration evidence for HSSL-G160 replay and report publication."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from benchmarks.logic_pipeline.contracts import canonical_json
from benchmarks.logic_pipeline import reassessment_reports as publication
from benchmarks.logic_pipeline import report as report_cli
from benchmarks.logic_pipeline.statistics import (
    StatisticsError,
    validate_statistics_report,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
REPLAY = REPOSITORY_ROOT / publication.DEFAULT_REPLAY_INDEX_PATH
STATISTICS = REPOSITORY_ROOT / publication.DEFAULT_STATISTICS_PATH
SNAPSHOT = REPOSITORY_ROOT / publication.DEFAULT_REPORTS_SNAPSHOT


@pytest.fixture(scope="module")
def replay_index() -> dict[str, object]:
    return publication.load_replay_index(
        REPLAY, repository_root=REPOSITORY_ROOT
    )


@pytest.fixture(scope="module")
def statistics_report() -> dict[str, object]:
    value = json.loads(STATISTICS.read_text(encoding="utf-8"))
    return validate_statistics_report(value)


@pytest.fixture(scope="module")
def snapshot() -> dict[str, object]:
    return json.loads(SNAPSHOT.read_text(encoding="utf-8"))


def test_hssl_g160_evidence_symbol_is_ast_visible_and_complete() -> None:
    statement = publication.HSSLEV1605D50()

    assert callable(publication.HSSLEV1605D50)
    assert report_cli.HSSLEV1605D50() == statement
    for required in (
        "kernel-verified holdout success",
        "sampled failure",
        "fresh detached-worktree cold-cache replay",
        "drift stale-receipt and same-run rejection",
        "native-kernel traceability",
        "marginal-escalation",
        "unnecessary-call",
        "complexity-Pareto",
        "typed nulls",
    ):
        assert required in statement


def test_replay_population_is_exactly_the_sealed_holdout_population(
    replay_index: dict[str, object],
) -> None:
    holdout_path = (
        REPOSITORY_ROOT
        / "workspace/benchmarks/hammer-symai-spacy-leanstral/"
        "reassessment-v2/results/holdout-evaluation-v2.json"
    )
    holdout = json.loads(holdout_path.read_text(encoding="utf-8"))
    source = replay_index["source_binding"]
    selection = replay_index["selection"]
    execution = replay_index["execution"]

    assert source["bytes_sha256"] == hashlib.sha256(
        holdout_path.read_bytes()
    ).hexdigest()
    assert source["semantic_sha256"] == holdout["artifact_sha256"]
    assert source["source_validated"] is True
    assert selection["kernel_verified_success_result_sha256s"] == []
    assert selection["observed_failure_result_sha256s"] == []
    assert selection["sampled_failure_result_sha256s"] == []
    assert selection["required_success_replay_count"] == 0
    assert selection["required_sampled_failure_replay_count"] == 0
    assert selection["selection_complete"] is True
    assert execution["completed_success_replay_count"] == 0
    assert execution["completed_failure_replay_count"] == 0
    assert execution["replay_receipts"] == []
    assert execution["fresh_worktree_receipts"] == []
    assert execution["replay_claimed"] is False
    assert execution["all_observed_successes_replayed"] is True
    assert execution["all_sampled_failures_replayed"] is True


def test_zero_population_does_not_open_replay_state(
    replay_index: dict[str, object],
) -> None:
    execution = replay_index["execution"]
    safety = replay_index["safety"]
    traceability = replay_index["traceability"]

    assert execution["worktree_count"] == 0
    assert execution["process_namespaces"] == []
    assert execution["cache_namespaces"] == []
    assert execution["execution_write_count"] == 0
    assert execution["backend_call_count"] == 0
    assert safety["holdout_inputs_read"] is False
    assert safety["holdout_outcomes_inspected"] is False
    assert safety["execution_namespace_created"] is False
    assert safety["production_routing_changed"] is False
    assert safety["production_promotion_authorized"] is False
    assert traceability["vacuous_coverage_is_not_replay_success"] is True
    assert traceability["untraced_claim_count"] == 0


def test_future_replay_contract_rejects_freshness_and_identity_drift(
    replay_index: dict[str, object],
) -> None:
    contract = replay_index["freshness_contract"]

    assert all(contract.values())
    assert contract["distinct_run_id_required"] is True
    assert contract["detached_fresh_worktree_required"] is True
    assert contract["fresh_cold_cache_namespace_required"] is True
    assert contract["same_source_commit_required"] is True
    assert contract["same_environment_required"] is True
    assert contract["same_case_manifest_required"] is True
    assert contract["same_route_and_adapter_identities_required"] is True
    assert contract["same_independent_native_kernel_receipt_required"] is True
    assert contract["stale_receipt_rejected"] is True
    assert contract["same_run_rejected"] is True
    assert contract["configuration_drift_rejected"] is True


def test_statistics_recompute_all_pilot_development_pairs(
    statistics_report: dict[str, object],
) -> None:
    requests = statistics_report["requests"]
    analyses = statistics_report["analyses"]
    pareto = statistics_report["pareto"]

    assert len(requests) == 48
    assert len(analyses) == 48
    assert sum(len(item["observations"]) for item in requests) == 480
    assert {
        (item["spec"]["candidate_variant_id"], item["spec"]["domain"])
        for item in requests
    } == {(f"A{index}", "quality") for index in range(1, 13)}
    assert {item["split"] for item in analyses} == {"pilot", "development"}
    assert {item["cache_mode"] for item in analyses} == {"cold", "warm"}
    assert all(item["scheduled_count"] == 10 for item in analyses)
    assert all(item["missing_count"] == 0 for item in analyses)
    assert pareto["frontier_candidate_ids"] == []
    assert all(
        item["ineligible_reason"].startswith("safety_infeasible:")
        for item in pareto["candidates"]
    )


def test_snapshot_covers_every_decision_domain_with_typed_holdout_nulls(
    snapshot: dict[str, object],
) -> None:
    results = snapshot["results"]
    reports = results["reports"]
    domains = reports["domains"]

    assert reports["required_domains"] == list(
        publication.REQUIRED_DECISION_DOMAINS
    )
    assert [item["domain"] for item in domains] == list(
        publication.REQUIRED_DECISION_DOMAINS
    )
    assert reports["structurally_complete"] is True
    assert reports["all_applicable_values_non_null"] is True
    assert reports["holdout_pair_count"] == 0
    assert reports["holdout_measured_domain_count"] == 0
    assert reports["missingness_synthesized_as_zero"] is False
    assert reports["measured_holdout_claims_published"] is False
    assert reports["statistics_comparison_count"] == 48
    assert reports["statistics_paired_observation_count"] == 480
    for domain in domains:
        assert domain["structurally_complete"] is True
        assert domain["pilot_development_source_bound"] is True
        assert domain["holdout_status"] == (
            "not_applicable_before_authorization"
        )
        assert domain["holdout_values"] is None
        assert domain["holdout_reason"]


def test_artifacts_are_canonical_and_snapshot_is_cross_bound(
    replay_index: dict[str, object],
    statistics_report: dict[str, object],
    snapshot: dict[str, object],
) -> None:
    for path in (REPLAY, STATISTICS, SNAPSHOT):
        raw = path.read_bytes()
        value = json.loads(raw)
        assert raw == (canonical_json(value) + "\n").encode("utf-8")

    artifacts = snapshot["results"]["artifacts"]
    assert artifacts["replay"]["bytes_sha256"] == hashlib.sha256(
        REPLAY.read_bytes()
    ).hexdigest()
    assert artifacts["replay"]["semantic_sha256"] == replay_index[
        "artifact_sha256"
    ]
    assert artifacts["statistics"]["bytes_sha256"] == hashlib.sha256(
        STATISTICS.read_bytes()
    ).hexdigest()
    assert artifacts["statistics"]["semantic_sha256"] == statistics_report[
        "artifact_sha256"
    ]
    decision = snapshot["results"]["decision"]
    assert decision["status"] == "blocked"
    assert decision["holdout_untouched"] is True
    assert decision["efficacy_claimed"] is False
    assert decision["replay_claimed"] is False
    assert decision["production_promotion_authorized"] is False


def test_tampered_replay_and_statistics_fail_closed(
    replay_index: dict[str, object],
    statistics_report: dict[str, object],
) -> None:
    replay_tamper = copy.deepcopy(replay_index)
    replay_tamper["execution"]["replay_claimed"] = True
    with pytest.raises(publication.ReassessmentReportsError):
        publication.validate_replay_index(
            replay_tamper, repository_root=REPOSITORY_ROOT
        )

    statistics_tamper = copy.deepcopy(statistics_report)
    statistics_tamper["analyses"][0]["scheduled_count"] = 9
    with pytest.raises(StatisticsError):
        validate_statistics_report(statistics_tamper)


def test_exact_statistics_cli_validates_the_complete_publication() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "benchmarks/logic_pipeline/report.py",
            "--section",
            "statistics",
            "--validate",
            "--results-path",
            publication.DEFAULT_STATISTICS_PATH.as_posix(),
        ],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=180,
    )
    summary = json.loads(result.stdout)

    assert summary["section"] == "statistics"
    assert summary["status"] == "valid"
    assert summary["evidence"] == "HSSLEV1605D50"
    assert summary["comparison_count"] == 48
    assert summary["scheduled_pair_count"] == 480
    assert summary["missing_pair_count"] == 0
    assert summary["frontier_candidate_ids"] == []
    assert summary["source_graph_validated"] is True
    assert summary["replay_status"] == (
        "not_applicable_before_authorized_holdout"
    )
    assert summary["replay_claimed"] is False
    assert summary["reports_structurally_complete"] is True
