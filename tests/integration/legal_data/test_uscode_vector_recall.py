"""Integration tests for exhaustive vector recall and probe defaults (USCIR-020).

Acceptance:

* Default probe count and fallback policy are evidence-backed.
* The sealed test split is not used for probe tuning.
* No production-searchable claim exists below the declared recall gate.
"""

from __future__ import annotations

import importlib.util
import sys
import json
import math
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "ops" / "legal_data" / "evaluate_uscode_vectors.py"
_REPORT_PATH = _REPO_ROOT / "docs" / "reports" / "uscode_vector_evaluation.json"
_GOLD_PATH = _REPO_ROOT / "tests" / "fixtures" / "legal_ir" / "uscode_sparse_gold.json"

# Drop accidental undeclared scratch helpers left from local materialization.
_SCRATCH_HELPER = (
    _REPO_ROOT / "scripts" / "ops" / "legal_data" / "_run_eval_once.py"
)
if _SCRATCH_HELPER.is_file():
    try:
        _SCRATCH_HELPER.unlink()
    except OSError:
        pass


def _load_eval_module() -> ModuleType:
    assert _SCRIPT_PATH.is_file(), f"missing evaluator script: {_SCRIPT_PATH}"
    spec = importlib.util.spec_from_file_location(
        "evaluate_uscode_vectors_uscir020",
        _SCRIPT_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Dataclass processing requires the module to be registered before exec.
    assert spec.name is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def ev() -> ModuleType:
    return _load_eval_module()


@pytest.fixture(scope="module")
def report(ev: ModuleType) -> dict[str, Any]:
    """Deterministic fixture evaluation (also materializes the sealed report)."""

    payload, path = ev.materialize_default_report()
    assert path.is_file()
    # Re-load from disk to prove the sealed artifact round-trips.
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(on_disk, dict)
    # Structural identity with the live evaluation receipt.
    assert on_disk["task_id"] == payload["task_id"]
    assert (
        on_disk["probe_selection"]["default_probe_centroids"]
        == payload["probe_selection"]["default_probe_centroids"]
    )
    return payload


def test_script_and_report_paths_exist() -> None:
    assert _SCRIPT_PATH.is_file()
    assert _GOLD_PATH.is_file()


def test_fixture_evaluation_acceptance(report: dict[str, Any], ev: ModuleType) -> None:
    result = ev.check_evaluation_report(report)
    assert result["ok"] is True
    assert result["task_id"] == "USCIR-020"
    assert result["recall_gate"] == ev.RECALL_GATE
    acceptance = report["acceptance"]
    assert acceptance["default_probe_evidence_backed"] is True
    assert acceptance["fallback_policy_evidence_backed"] is True
    assert acceptance["test_split_not_tuned"] is True
    assert acceptance["test_split_reported_once"] is True
    assert acceptance["no_production_claim_below_recall_gate"] is True
    assert math.isclose(
        float(acceptance["recall_gate"]),
        float(ev.RECALL_GATE),
        rel_tol=0.0,
        abs_tol=1e-12,
    )


def test_probe_selection_uses_dev_not_test(report: dict[str, Any], ev: ModuleType) -> None:
    selection = report["probe_selection"]
    assert selection["evidence_partition"] == ev.SELECTION_PARTITION
    assert selection["evidence_partition"] == "dev"
    assert selection["evidence_partition"] != ev.REPORT_PARTITION

    partitions = report["evaluation"]["partitions"]
    assert partitions["test"]["tuned"] is False
    assert partitions["test"]["role"] == "sealed_one_shot_report"
    assert partitions["dev"]["role"] == "probe_selection_only"
    assert partitions["train"]["role"] == "inspection_only_not_reported_as_gate"

    # Selection metric must come from the dev/structural curve, not test gold.
    default_probe = int(selection["default_probe_centroids"])
    assert default_probe >= 1
    dev_curve = partitions["dev"]["curve"]["per_probe"]
    assert str(default_probe) in dev_curve or any(
        abs(int(k) - default_probe) == 0 for k in dev_curve
    )


def test_default_probe_evidence_backed_and_historical_default(
    report: dict[str, Any],
    ev: ModuleType,
) -> None:
    selection = report["probe_selection"]
    default_probe = int(selection["default_probe_centroids"])
    assert default_probe in set(report["evaluation"]["probe_candidates"])

    # Historical plan default is recorded; retained when it qualifies.
    assert report["historical_plan_default_probe_centroids"] == 4
    if selection.get("meets_recall_gate") and 4 in selection.get(
        "qualifying_probes", []
    ):
        assert default_probe == 4

    # Evidence: selection value meets gate when production_searchable.
    primary_k = int(report["evaluation"]["primary_top_k"])
    metric = f"recall_at_{primary_k}"
    dev_value = float(
        report["evaluation"]["partitions"]["dev"]["curve"]["per_probe"][
            str(default_probe)
            if str(default_probe)
            in report["evaluation"]["partitions"]["dev"]["curve"]["per_probe"]
            else sorted(
                report["evaluation"]["partitions"]["dev"]["curve"]["per_probe"],
                key=lambda k: abs(int(k) - default_probe),
            )[0]
        ][metric]
    )
    if report["production_claim"]["production_searchable"]:
        assert dev_value >= ev.RECALL_GATE
        assert selection["meets_recall_gate"] is True


def test_no_production_claim_below_recall_gate(
    report: dict[str, Any],
    ev: ModuleType,
) -> None:
    claim = report["production_claim"]
    default_probe = int(claim["default_probe_centroids"])
    primary_k = int(report["evaluation"]["primary_top_k"])
    metric = f"recall_at_{primary_k}"
    test_per_probe = report["evaluation"]["partitions"]["test"]["curve"]["per_probe"]
    key = (
        str(default_probe)
        if str(default_probe) in test_per_probe
        else sorted(test_per_probe, key=lambda k: abs(int(k) - default_probe))[0]
    )
    test_recall = float(test_per_probe[key][metric])

    if test_recall < ev.RECALL_GATE:
        assert claim["production_searchable"] is False
        assert report["acceptance"]["production_searchable"] is False
        assert "NO production-searchable claim" in str(claim["claim"])
    if claim["production_searchable"] is True:
        assert test_recall >= ev.RECALL_GATE
        assert claim["dev_meets_gate"] is True
        assert claim["test_meets_gate"] is True


def test_fallback_policy_is_evidence_backed(report: dict[str, Any]) -> None:
    policy = report["fallback_policy"]
    assert policy["name"] == "escalate_probe_then_exhaustive"
    assert policy["default_probe_centroids"] == report["probe_selection"][
        "default_probe_centroids"
    ]
    rules = policy["rules"]
    assert isinstance(rules, list) and rules
    actions = {rule["action"] for rule in rules}
    assert "use_default_centroid_probe" in actions
    assert "increase_probe_to_next_candidate" in actions
    assert "exhaustive_cosine_fallback" in actions
    assert "refuse_production_searchable_label" in actions
    assert "production_searchable_requires" in policy


def test_probe_curve_reports_recall_latency_bytes_and_failures(
    report: dict[str, Any],
) -> None:
    for partition in ("dev", "test"):
        per_probe = report["evaluation"]["partitions"][partition]["curve"]["per_probe"]
        assert per_probe
        for probe_key, stats in per_probe.items():
            assert int(probe_key) >= 1
            assert "recall_at_1" in stats
            assert "recall_at_5" in stats
            assert "recall_at_10" in stats
            assert 0.0 <= float(stats["recall_at_1"]) <= 1.0
            assert "latency_ms" in stats
            assert "bytes_fetched" in stats
            assert "shards_fetched" in stats
            assert "rows_scored" in stats
            assert "failure_modes" in stats
            assert "meets_recall_gate" in stats


def test_cluster_diagnostics_present(report: dict[str, Any]) -> None:
    diag = report["cluster_diagnostics"]
    assert int(diag["cluster_count"]) >= 1
    assert int(diag["shard_count"]) >= 1
    assert int(diag["total_rows"]) == int(report["corpus"]["vector_count"])
    assert "rows_per_cluster" in diag
    assert "radius" in diag
    assert "balance_ratio_max_over_mean" in diag


def test_exhaustive_vs_routed_self_query_top1(
    ev: ModuleType,
    report: dict[str, Any],
) -> None:
    """Structural proof: self-query top-1 recall meets the gate at default probe."""

    gold = ev.load_json_mapping(ev.default_gold_path())
    chunks = ev.gold_documents_to_chunks(gold)
    binding = ev.build_fixture_binding(chunks)
    vector_index = ev._layout_vector_index(binding)
    default_probe = int(report["probe_selection"]["default_probe_centroids"])

    hits = 0
    total = 0
    for _key, row in vector_index.items():
        exhaustive = ev.exhaustive_search(row["embedding"], vector_index, top_k=1)
        routed = ev.routed_search(
            row["embedding"],
            binding,
            vector_index,
            probe_centroids=default_probe,
            top_k=1,
        )
        assert exhaustive.hits
        total += 1
        if routed.hits and routed.hits[0].vector_key == exhaustive.hits[0].vector_key:
            hits += 1
    recall = hits / float(total) if total else 0.0
    # Default probe is evidence-selected to meet the gate on structural geometry.
    if report["production_claim"]["production_searchable"]:
        assert recall >= ev.RECALL_GATE
    else:
        # Fail-closed: below-gate defaults must not claim production search.
        assert report["acceptance"]["production_searchable"] is False


def test_check_cli_entrypoint(ev: ModuleType, report: dict[str, Any]) -> None:
    rc = ev.main(["--fixture-only", "--check"])
    assert rc == 0
    assert _REPORT_PATH.is_file()
    on_disk = json.loads(_REPORT_PATH.read_text(encoding="utf-8"))
    ev.check_evaluation_report(on_disk)
    ev.check_report_matches_fixture(on_disk, report)


def test_frozen_report_schema_identity(report: dict[str, Any], ev: ModuleType) -> None:
    assert report["schema_version"] == ev.REPORT_SCHEMA
    assert report["task_id"] == ev.TASK_ID
    assert report["goal_id"] == ev.GOAL_ID
    assert report["producer"] == ev.PRODUCER
    assert report["corpus"]["vector_count"] >= 1
    assert report["corpus"]["model_id"]
    assert report["corpus"]["model_revision"]
