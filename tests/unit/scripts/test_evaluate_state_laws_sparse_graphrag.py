"""Unit tests for state-law sparse GraphRAG evaluation (LCR-036).

Acceptance:

* Sealed BM25 / vector / hybrid relevance, graph paths, jurisdiction
  filters, sparse I/O, coverage, and per-cohort thresholds pass.
* Traversal / tamper / digest / decompression / budget / mutable-revision /
  secret probes fail closed.
* No fixture result is called a live canary.
* LCR-035 gold, LCR-027 BM25, LCR-029 vectors, LCR-031 adjacency, and
  LCR-034 query CLI/facade are consumed read-only.
"""

from __future__ import annotations

import importlib.util
import json
import math
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT_PATH = (
    _REPO_ROOT
    / "scripts"
    / "ops"
    / "legal_data"
    / "evaluate_state_laws_sparse_graphrag.py"
)
_REPORT_PATH = _REPO_ROOT / "docs" / "reports" / "legal_corpora_reindex" / "evaluation.json"
_GOLD_PATH = _REPO_ROOT / "tests" / "fixtures" / "legal_ir" / "state_laws_sparse_gold.json"
_NEG_PATH = (
    _REPO_ROOT / "tests" / "fixtures" / "legal_ir" / "state_laws_sparse_negative_controls.json"
)
_BM25_PATH = _REPO_ROOT / "docs" / "reports" / "legal_corpora_reindex" / "bm25_evaluation.json"
_VECTOR_PATH = (
    _REPO_ROOT / "docs" / "reports" / "legal_corpora_reindex" / "vector_evaluation.json"
)
_GRAPH_PATH = _REPO_ROOT / "docs" / "reports" / "legal_corpora_reindex" / "graph_evaluation.json"
_ADJACENCY_PATH = (
    _REPO_ROOT / "docs" / "reports" / "legal_corpora_reindex" / "adjacency_reconciliation.json"
)
_QUERY_CONTRACT_PATH = (
    _REPO_ROOT / "docs" / "reports" / "legal_corpora_reindex" / "query_contract.json"
)
_QUERY_CLI_PATH = _REPO_ROOT / "scripts" / "ops" / "legal_data" / "query_state_laws_hf.py"
_QUERY_FACADE_PATH = (
    _REPO_ROOT
    / "ipfs_datasets_py"
    / "processors"
    / "legal_data"
    / "state_laws_sparse_graphrag.py"
)


def _load_eval_module() -> ModuleType:
    assert _SCRIPT_PATH.is_file(), f"missing evaluator script: {_SCRIPT_PATH}"
    spec = importlib.util.spec_from_file_location(
        "evaluate_state_laws_sparse_graphrag_lcr036",
        _SCRIPT_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
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
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(on_disk, dict)
    assert on_disk["task_id"] == payload["task_id"]
    assert (
        on_disk["fusion_selection"]["candidate_id"]
        == payload["fusion_selection"]["candidate_id"]
    )
    assert (
        on_disk["fusion_selection"]["config_digest"]
        == payload["fusion_selection"]["config_digest"]
    )
    assert on_disk["evaluation_cid"] == payload["evaluation_cid"]
    return payload


def test_script_and_readonly_dependencies_exist() -> None:
    assert _SCRIPT_PATH.is_file()
    assert _GOLD_PATH.is_file()
    assert _NEG_PATH.is_file()
    assert _BM25_PATH.is_file()
    assert _VECTOR_PATH.is_file()
    assert _GRAPH_PATH.is_file()
    assert _ADJACENCY_PATH.is_file()
    assert _QUERY_CONTRACT_PATH.is_file()
    assert _QUERY_CLI_PATH.is_file()
    assert _QUERY_FACADE_PATH.is_file()


def test_help_exits_zero(ev: ModuleType) -> None:
    assert ev.main(["--help"]) == 0


def test_identity_constants(ev: ModuleType) -> None:
    assert ev.TASK_ID == "LCR-036"
    assert ev.GOAL_ID == "LCR-G060"
    assert ev.PROGRAM_ID == "legal-corpora-reindex-v1"
    assert ev.GOLD_TASK_ID == "LCR-035"
    assert ev.BM25_TASK_ID == "LCR-027"
    assert ev.VECTORS_TASK_ID == "LCR-029"
    assert ev.ADJACENCY_TASK_ID == "LCR-031"
    assert ev.QUERY_TASK_ID == "LCR-034"


def test_fixture_evaluation_acceptance(report: dict[str, Any], ev: ModuleType) -> None:
    result = ev.check_evaluation_report(report)
    assert result["ok"] is True
    assert result["task_id"] == "LCR-036"
    assert result["goal_id"] == "LCR-G060"
    assert result["hybrid_recall_gate"] == ev.RECALL_GATE_HYBRID
    assert result["component_baselines_available"] is True
    assert result["no_unsupported_production_claim"] is True
    assert result["bounded_shard_selection"] is True
    assert result["substantially_less_than_full_release"] is True
    assert result["sealed_thresholds_pass"] is True
    assert result["differential_references_pass"] is True
    assert result["security_probes_fail_closed"] is True
    assert result["two_build_determinism"] is True
    assert result["live_canary"] is False
    assert result["no_fixture_result_called_live_canary"] is True

    acceptance = report["acceptance"]
    assert acceptance["all_modes_meet_declared_recall_and_ranking"] is True
    assert acceptance["bm25_meets_declared_gates"] is True
    assert acceptance["vector_meets_declared_gates"] is True
    assert acceptance["hybrid_meets_declared_gates"] is True
    assert acceptance["graph_meets_declared_gates"] is True
    assert acceptance["semantic_traversal_meets_declared_gates"] is True
    assert acceptance["graph_edges_pass"] is True
    assert acceptance["filters_pass"] is True
    assert acceptance["coverage_pass"] is True
    assert acceptance["skew_pass"] is True
    assert acceptance["sealed_thresholds_pass_per_cohort"] is True
    assert acceptance["bounded_shard_selection"] is True
    assert acceptance["substantially_less_than_full_release"] is True
    assert acceptance["fetch_traces_prove_sparse_io"] is True
    assert acceptance["chosen_defaults_declared"] is True
    assert acceptance["defaults_derived_from_metrics"] is True
    assert acceptance["names_exact_manifest_and_model"] is True
    assert acceptance["stale_fixture_receipts_not_full_live_evidence"] is True
    assert acceptance["regressions_and_exceptions_explicit"] is True
    assert acceptance["reference_hardware_network_recorded"] is True
    assert acceptance["no_unsupported_production_claim"] is True
    assert acceptance["test_split_not_tuned"] is True
    assert acceptance["test_split_reported_once"] is True
    assert acceptance["budget_exhaustion_fail_closed"] is True
    assert acceptance["traversal_fail_closed"] is True
    assert acceptance["tamper_fail_closed"] is True
    assert acceptance["digest_fail_closed"] is True
    assert acceptance["decompression_fail_closed"] is True
    assert acceptance["mutable_revision_fail_closed"] is True
    assert acceptance["secrets_absent_fail_closed"] is True
    assert acceptance["security_probes_fail_closed"] is True
    assert acceptance["two_build_determinism"] is True
    assert acceptance["sealed_thresholds_pass"] is True
    assert acceptance["differential_references_pass"] is True
    assert acceptance["no_fixture_result_called_live_canary"] is True
    assert acceptance["live_canary"] is False
    assert acceptance["hub_upload"] is False
    assert acceptance["secrets_absent"] is True
    assert "Sealed thresholds and differential references pass" in acceptance["criteria"]


def test_five_modes_reported_with_recall_and_ranking(report: dict[str, Any]) -> None:
    test = report["evaluation"]["partitions"]["test"]
    for mode in ("bm25", "vector", "hybrid", "graph", "semantic-graph"):
        metrics = test[mode]
        assert metrics["query_count"] > 0
        for metric_key in (
            "relevance_recall_at_1",
            "relevance_recall_at_5",
            "relevance_recall_at_10",
            "mean_reciprocal_rank",
            "ndcg_at_1",
            "ndcg_at_5",
            "ndcg_at_10",
        ):
            assert metric_key in metrics, f"{mode}.{metric_key}"
            assert isinstance(metrics[metric_key], (int, float))
        if mode in {"bm25", "vector", "hybrid", "semantic-graph"}:
            assert metrics["meets_recall_gate"] is True, mode
        if mode in {"bm25", "hybrid"}:
            assert metrics["meets_ranking_gate"] is True, mode


def test_declared_thresholds_met(report: dict[str, Any], ev: ModuleType) -> None:
    test = report["evaluation"]["partitions"]["test"]
    assert test["bm25"]["primary_metric_value"] >= ev.RECALL_GATE_BM25
    assert test["vector"]["primary_metric_value"] >= ev.RECALL_GATE_VECTOR
    assert test["hybrid"]["primary_metric_value"] >= ev.RECALL_GATE_HYBRID
    assert test["semantic-graph"]["primary_metric_value"] >= ev.RECALL_GATE_SEMANTIC
    assert test["bm25"]["mean_reciprocal_rank"] >= ev.RANKING_MRR_GATE
    assert test["hybrid"]["mean_reciprocal_rank"] >= ev.RANKING_MRR_GATE
    assert test["bm25"]["ndcg_at_5"] >= ev.RANKING_NDCG_GATE
    assert test["hybrid"]["ndcg_at_5"] >= ev.RANKING_NDCG_GATE
    if test["bm25"]["exact_citation_query_count"]:
        assert test["bm25"]["exact_citation_success_rate"] >= ev.EXACT_CITATION_GATE
    assert report["graph_path"]["ok"] is True
    assert report["graph_path"]["all_partitions"]["success_rate"] >= ev.RECALL_GATE_GRAPH
    assert report["graph_path"]["edge_count"] > 0
    assert report["filters"]["ok"] is True


def test_chosen_defaults_declared(report: dict[str, Any], ev: ModuleType) -> None:
    defaults = report["chosen_defaults"]
    assert "bm25" in defaults
    assert "vector" in defaults
    assert "fusion" in defaults
    assert "graph" in defaults
    assert "semantic-graph" in defaults

    bm25_params = defaults["bm25"]["parameters"]
    assert bm25_params["k1"] == 1.2
    assert bm25_params["b"] == 0.75
    assert bm25_params["tokenizer_id"] == "state-laws-bm25-tokenizer/v1"
    for field_name in (
        "citation",
        "title",
        "heading",
        "hierarchy",
        "jurisdiction",
        "body",
        "note",
    ):
        assert field_name in bm25_params["field_weights"]

    assert defaults["vector"]["default_probe_centroids"] >= 1
    assert defaults["vector"]["embedding_model_id"] == "thenlper/gte-small"
    assert defaults["vector"]["embedding_model_revision"] == (
        "17e1f347d17fe144873b1201da91788898c639cd"
    )
    fusion = defaults["fusion"]
    assert fusion["candidate_id"]
    assert fusion["config"]["method"] in {"weighted", "rrf"}
    assert fusion["evidence_partition"] == ev.SELECTION_PARTITION
    assert defaults["semantic-graph"]["hydration_policy"] == "entry_locator"

    selection = report["fusion_selection"]
    assert selection["evidence_partition"] == "dev"
    assert selection["evidence_partition"] != ev.REPORT_PARTITION
    assert selection["config_digest"]
    assert len(selection["config_digest"]) == 64


def test_test_split_reported_once_untuned(report: dict[str, Any], ev: ModuleType) -> None:
    partitions = report["evaluation"]["partitions"]
    assert partitions["test"]["tuned"] is False
    assert partitions["test"]["role"] == "sealed_one_shot_report"
    assert partitions["test"]["report_count"] == 1
    assert partitions["dev"]["role"] == "fusion_selection_only"
    assert partitions["dev"]["tuned"] is True
    assert partitions["train"]["role"] == "inspection_only_not_reported_as_gate"


def test_fetch_traces_prove_bounded_and_sparse_io(report: dict[str, Any], ev: ModuleType) -> None:
    sparse = report["io"]["sparse"]
    assert sparse["full_release_bytes"] > 0
    assert sparse["bounded_shard_selection"] is True
    assert sparse["substantially_less_than_full_release"] is True
    assert sparse["byte_ratio_gate"] == ev.SPARSE_IO_BYTE_RATIO_GATE
    assert sparse["shard_ratio_gate"] == ev.SPARSE_IO_SHARD_RATIO_GATE
    assert "cache_hit_ratio" in sparse
    for mode in ("bm25", "vector", "hybrid", "graph", "semantic-graph"):
        block = sparse["modes"][mode]
        assert block["bounded_shard_selection"] is True, mode
        assert block["substantially_less_than_full_release"] is True, mode
        assert block["bytes_ratio"] <= ev.SPARSE_IO_BYTE_RATIO_GATE, mode
        if block["shards_available_mean"] > 0:
            assert block["shard_ratio"] <= ev.SPARSE_IO_SHARD_RATIO_GATE, mode
            assert block["shards_mean"] < block["shards_available_mean"], mode

    test = report["evaluation"]["partitions"]["test"]
    for mode in ("bm25", "vector", "hybrid"):
        traces = test[mode]["fetch_traces"]
        assert traces, mode
        for trace in traces:
            assert trace["bounded_shard_selection"] is True
            assert trace["shards_fetched"] < trace["shards_available"]
            assert trace["route_family"]
            assert isinstance(trace["routed_paths"], list)


def test_regressions_and_exceptions_explicit(report: dict[str, Any]) -> None:
    regressions = report["regressions"]
    assert "bm25_primary" in regressions
    assert "vector_primary" in regressions
    assert "fused_primary" in regressions
    assert "exceptions" in regressions
    assert isinstance(regressions["exceptions"], list)
    assert "no_unapproved_regression" in regressions
    assert "regression_tolerance" in regressions
    for exc in regressions["exceptions"]:
        assert "kind" in exc
        assert "approved" in exc
        assert "detail" in exc


def test_reference_hardware_and_network_recorded(report: dict[str, Any]) -> None:
    hardware = report["reference_hardware"]
    assert hardware["cpu_model"]
    assert hardware["memory_gib"]
    assert hardware["architecture"]
    assert hardware["python_target"] == "python3.12"

    network = report["reference_network"]
    assert network["network_required"] is False
    assert network["mode"] == "fixture_offline"
    assert network["hub_access"] == "disabled_in_fixture_gate"
    assert "notes" in network


def test_no_unsupported_production_claim_or_live_canary(report: dict[str, Any]) -> None:
    claim = report["production_claim"]
    assert claim["production_searchable"] is False
    assert claim["live_canary"] is False
    assert "NO production-searchable claim" in claim["claim"]
    assert report["acceptance"]["no_unsupported_production_claim"] is True
    assert report["authorizing_for_release"] is False
    assert report["authorizing_for_publication"] is False
    assert report["authorizing_hub_upload"] is False
    assert report["hub_upload"] is False
    assert report["not_legal_advice"] is True
    assert report["live_canary"] is False
    assert report["canary"]["live_canary"] is False
    assert report["canary"]["fixture_result_called_live_canary"] is False
    assert report["canary"]["kind"] == "fixture_offline_not_live"
    text = json.dumps(report).lower()
    assert "live canary" not in text or "not a live canary" in text or "not_live" in text


def test_io_latency_memory_and_budget_surfaces(report: dict[str, Any]) -> None:
    io = report["io"]
    for key in ("bm25_test", "vector_test", "hybrid_test", "graph_test", "semantic_test"):
        block = io[key]
        for metric in ("bytes_fetched", "shards_fetched", "latency_ms"):
            assert metric in block
            assert "p50" in block[metric]
            assert "p95" in block[metric]

    resources = report["resources"]
    assert resources["peak_memory_bytes"] > 0
    assert resources["build_throughput_rows_per_second"] > 0
    assert "cache_hit_ratio" in resources

    budget = report["budget_exhaustion"]
    assert budget["all_exhaustion_stops"] is True
    assert budget["scenarios"]
    assert any(scenario["exhausted"] for scenario in budget["scenarios"])
    assert any(not scenario["exhausted"] for scenario in budget["scenarios"])


def test_security_probes_fail_closed(report: dict[str, Any]) -> None:
    security = report["security"]
    assert security["all_fail_closed"] is True
    assert security["live_canary"] is False
    assert security["fixture_result_called_live_canary"] is False
    for kind in (
        "traversal",
        "tamper",
        "digest",
        "decompression",
        "budget",
        "mutable-revision",
        "secrets_absent",
    ):
        assert security["kinds"][kind] is True, kind
    kinds_seen = {probe["kind"] for probe in security["probes"]}
    assert kinds_seen >= {
        "traversal",
        "tamper",
        "digest",
        "decompression",
        "budget",
        "mutable-revision",
        "secrets_absent",
    }
    assert all(probe["failed_closed"] for probe in security["probes"])
    assert all(probe["ok"] for probe in security["probes"])


def test_two_build_determinism(report: dict[str, Any], ev: ModuleType) -> None:
    two = report["two_build_determinism"]
    assert two["ok"] is True
    assert two["runs"] == 2
    assert two["bm25_match"] is True
    assert two["vector_match"] is True
    assert two["graph_match"] is True
    assert two["digest_a"] == two["digest_b"]

    first = ev.run_fixture_evaluation()
    second = ev.run_fixture_evaluation()
    assert first["fusion_selection"]["candidate_id"] == second["fusion_selection"]["candidate_id"]
    assert first["fusion_selection"]["config_digest"] == second["fusion_selection"]["config_digest"]
    assert (
        first["evaluation"]["partitions"]["test"]["hybrid"]["primary_metric_value"]
        == second["evaluation"]["partitions"]["test"]["hybrid"]["primary_metric_value"]
    )
    assert first["evaluation_cid"] == second["evaluation_cid"]
    assert first["production_claim"]["production_searchable"] is False
    assert first["live_canary"] is False


def test_gold_bm25_vector_adjacency_query_consumed_read_only(report: dict[str, Any]) -> None:
    consumed = report["consumed_inputs"]
    assert consumed["read_only"] is True
    assert consumed["hub_upload"] is False
    assert consumed["stale_fixture_receipts_used_as_full_live_evidence"] is False
    for key in ("gold", "bm25", "vector", "adjacency", "query"):
        assert consumed[key]["consumed_read_only"] is True
        assert consumed[key]["available"] is True
        assert consumed[key]["task_id"]
        assert consumed[key].get("full_live_evidence") is not True
    assert consumed["gold"]["task_id"] == "LCR-035"
    assert consumed["bm25"]["task_id"] == "LCR-027"
    assert consumed["vector"]["task_id"] == "LCR-029"
    assert consumed["adjacency"]["task_id"] == "LCR-031"
    assert consumed["query"]["task_id"] == "LCR-034"

    gold_before = _GOLD_PATH.read_bytes()
    bm25_before = _BM25_PATH.read_bytes()
    vector_before = _VECTOR_PATH.read_bytes()
    adjacency_before = _ADJACENCY_PATH.read_bytes()
    query_before = _QUERY_CONTRACT_PATH.read_bytes()
    cli_before = _QUERY_CLI_PATH.read_bytes()
    facade_before = _QUERY_FACADE_PATH.read_bytes()
    assert gold_before == _GOLD_PATH.read_bytes()
    assert bm25_before == _BM25_PATH.read_bytes()
    assert vector_before == _VECTOR_PATH.read_bytes()
    assert adjacency_before == _ADJACENCY_PATH.read_bytes()
    assert query_before == _QUERY_CONTRACT_PATH.read_bytes()
    assert cli_before == _QUERY_CLI_PATH.read_bytes()
    assert facade_before == _QUERY_FACADE_PATH.read_bytes()

    differential = report["differential_references"]
    assert differential["ok"] is True
    assert differential["gold_task_id"] == "LCR-035"
    assert differential["bm25_task_id"] == "LCR-027"
    assert differential["vectors_task_id"] == "LCR-029"
    assert differential["adjacency_task_id"] == "LCR-031"
    assert differential["query_task_id"] == "LCR-034"
    assert differential["stale_fixture_receipts_used_as_full_live_evidence"] is False


def test_coverage_filters_skew_and_cohorts(report: dict[str, Any], ev: ModuleType) -> None:
    coverage = report["coverage"]
    assert coverage["ok"] is True
    assert coverage["jurisdiction_count"] == 51
    assert coverage["includes_dc"] is True
    assert coverage["cohort_count"] == 13
    assert report["filters"]["case_count"] >= 1
    assert report["filters"]["success_rate"] == 1.0
    assert report["skew"]["ok"] is True
    assert report["skew"]["max_jurisdiction_share"] <= ev.SKEW_MAX_SHARE_GATE
    cohorts = report["cohorts"]
    assert cohorts["ok"] is True
    assert cohorts["represented_cohort_count"] == 13
    assert cohorts["sealed_thresholds_pass_per_cohort"] is True
    for letter in ev.COHORTS:
        row = cohorts["cohorts"][letter]
        assert row["represented"] is True
        assert row["meets_recall_gate"] is True
        assert row["query_count"] >= 1


def test_named_identity_is_exact_manifest_and_model(report: dict[str, Any], ev: ModuleType) -> None:
    named = report["named_identity"]
    assert named["dataset_repo_id"] == "justicedao/ipfs_state_laws"
    assert named["embedding_model_id"] == ev.PINNED_MODEL_ID
    assert named["embedding_model_revision"] == ev.PINNED_MODEL_REVISION
    assert named["tokenizer_id"] == ev.TOKENIZER_ID
    assert named["manifest_name"]
    assert named["pinned_corpus_revision"]
    assert named["names_exact_manifest_and_model"] is True


def test_component_baselines_available(report: dict[str, Any]) -> None:
    components = report["component_baselines"]
    for key in ("bm25", "vector", "graph", "adjacency", "gold", "query"):
        assert components[key]["available"] is True, key
        assert components[key]["task_id"]
        assert components[key]["consumed_read_only"] is True
        assert components[key].get("full_live_evidence") is not True


def test_cli_fixture_only_check(ev: ModuleType, report: dict[str, Any]) -> None:
    assert _REPORT_PATH.is_file()
    rc = ev.main(["--fixture-only", "--check"])
    assert rc == 0


def test_live_check_without_fixture_only_fails(ev: ModuleType) -> None:
    rc = ev.main(["--check"])
    assert rc == 1


def test_check_rejects_production_claim(report: dict[str, Any], ev: ModuleType) -> None:
    bad = json.loads(json.dumps(report))
    bad["production_claim"] = dict(bad["production_claim"])
    bad["production_claim"]["production_searchable"] = True
    with pytest.raises(ev.SparseGraphragEvaluationError):
        ev.check_evaluation_report(bad)


def test_check_rejects_live_canary_label(report: dict[str, Any], ev: ModuleType) -> None:
    bad = json.loads(json.dumps(report))
    bad["live_canary"] = True
    with pytest.raises(ev.SparseGraphragEvaluationError, match="live canary"):
        ev.check_evaluation_report(bad)
    bad2 = json.loads(json.dumps(report))
    bad2["canary"] = dict(bad2["canary"])
    bad2["canary"]["live_canary"] = True
    with pytest.raises(ev.SparseGraphragEvaluationError, match="live canary"):
        ev.check_evaluation_report(bad2)


def test_check_rejects_untuned_test_split_drift(report: dict[str, Any], ev: ModuleType) -> None:
    bad = json.loads(json.dumps(report))
    bad["evaluation"]["partitions"]["test"]["tuned"] = True
    with pytest.raises(ev.SparseGraphragEvaluationError):
        ev.check_evaluation_report(bad)


def test_metrics_helpers(ev: ModuleType) -> None:
    hits = [
        {"entry_cid": "a", "score": 1.0},
        {"entry_cid": "b", "score": 0.5},
        {"entry_cid": "c", "score": 0.1},
    ]
    relevant = {"a", "c"}
    assert math.isclose(ev.relevance_recall_at_k(hits, relevant, k=1), 0.5)
    assert math.isclose(ev.relevance_recall_at_k(hits, relevant, k=3), 1.0)
    assert math.isclose(ev.reciprocal_rank(hits, relevant), 1.0)
    grades = {"a": 3, "c": 2}
    ndcg = ev.ndcg_at_k(hits, grades, k=3)
    assert 0.0 <= ndcg <= 1.0
    assert math.isclose(ev.ndcg_at_k([], {}, k=5), 1.0)


def test_popular_name_expansion(ev: ModuleType) -> None:
    expanded = ev.expand_popular_name("Hawaii UIPA")
    assert "uniform information practices act" in expanded.lower()
    ccpa = ev.expand_popular_name("California Consumer Privacy Act")
    assert "CCPA" in ccpa or "ccpa" in ccpa.lower()


def test_report_is_secret_free_and_compact(report: dict[str, Any]) -> None:
    text = json.dumps(report)
    assert "hf_" not in text
    assert "sk-" not in text
    assert "Bearer " not in text
    assert _REPORT_PATH.stat().st_size < 1_048_576
    assert report["task_id"] == "LCR-036"
    assert report["goal_id"] == "LCR-G060"
    assert report["program_id"] == "legal-corpora-reindex-v1"
    assert report["fixture_only"] is True
    assert report["secrets_absent"] is True
    assert report["hub_upload"] is False
