"""Unit tests for fused US Code sparse GraphRAG evaluation (USCIR-035).

Acceptance:

* Both component and fused baselines are reported.
* Chosen defaults are declared.
* Regressions / exceptions are explicit.
* Reference hardware / network are recorded.
* No unsupported production claim is made.
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
    _REPO_ROOT / "scripts" / "ops" / "legal_data" / "evaluate_uscode_sparse_graphrag.py"
)
_REPORT_PATH = (
    _REPO_ROOT / "docs" / "reports" / "uscode_sparse_graphrag_evaluation.json"
)
_GOLD_PATH = _REPO_ROOT / "tests" / "fixtures" / "legal_ir" / "uscode_sparse_gold.json"
_BM25_REPORT = _REPO_ROOT / "docs" / "reports" / "uscode_bm25_evaluation.json"
_VECTOR_REPORT = _REPO_ROOT / "docs" / "reports" / "uscode_vector_evaluation.json"
_GRAPH_REPORT = _REPO_ROOT / "docs" / "reports" / "uscode_graph_evaluation.json"


def _load_eval_module() -> ModuleType:
    assert _SCRIPT_PATH.is_file(), f"missing evaluator script: {_SCRIPT_PATH}"
    spec = importlib.util.spec_from_file_location(
        "evaluate_uscode_sparse_graphrag_uscir035",
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
    return payload


def test_script_and_dependencies_exist() -> None:
    assert _SCRIPT_PATH.is_file()
    assert _GOLD_PATH.is_file()
    assert _BM25_REPORT.is_file()
    assert _VECTOR_REPORT.is_file()
    assert _GRAPH_REPORT.is_file()


def test_help_exits_zero(ev: ModuleType) -> None:
    assert ev.main(["--help"]) == 0


def test_fixture_evaluation_acceptance(report: dict[str, Any], ev: ModuleType) -> None:
    result = ev.check_evaluation_report(report)
    assert result["ok"] is True
    assert result["task_id"] == "USCIR-035"
    assert result["fused_recall_gate"] == ev.FUSED_RECALL_GATE
    assert result["component_baselines_available"] is True
    assert result["no_unsupported_production_claim"] is True

    acceptance = report["acceptance"]
    assert acceptance["component_and_fused_baselines_reported"] is True
    assert acceptance["chosen_defaults_declared"] is True
    assert acceptance["regressions_and_exceptions_explicit"] is True
    assert acceptance["reference_hardware_network_recorded"] is True
    assert acceptance["no_unsupported_production_claim"] is True
    assert acceptance["test_split_not_tuned"] is True
    assert acceptance["test_split_reported_once"] is True
    assert acceptance["budget_exhaustion_fail_closed"] is True
    assert math.isclose(
        float(acceptance["fused_recall_gate"]),
        float(ev.FUSED_RECALL_GATE),
        rel_tol=0.0,
        abs_tol=1e-12,
    )


def test_component_and_fused_baselines_reported(report: dict[str, Any]) -> None:
    components = report["component_baselines"]
    for key in ("bm25", "vector", "graph"):
        assert components[key]["available"] is True, key
        assert components[key]["task_id"]

    partitions = report["evaluation"]["partitions"]
    test = partitions["test"]
    assert test["bm25"]["mode"] == "bm25"
    assert test["vector"]["mode"] == "vector"
    assert test["fused"]["mode"] == "hybrid"
    assert test["bm25"]["query_count"] > 0
    assert test["vector"]["query_count"] > 0
    assert test["fused"]["query_count"] > 0
    for metric_key in (
        "relevance_recall_at_1",
        "relevance_recall_at_5",
        "relevance_recall_at_10",
        "mean_reciprocal_rank",
        "ndcg_at_1",
        "ndcg_at_5",
        "ndcg_at_10",
    ):
        assert metric_key in test["fused"]
        assert isinstance(test["fused"][metric_key], (int, float))


def test_chosen_defaults_declared(report: dict[str, Any], ev: ModuleType) -> None:
    defaults = report["chosen_defaults"]
    assert "bm25" in defaults
    assert "vector" in defaults
    assert "fusion" in defaults
    assert "graph" in defaults

    bm25_params = defaults["bm25"]["parameters"]
    assert bm25_params["k1"] == 1.2
    assert bm25_params["b"] == 0.75
    assert bm25_params["tokenizer_id"] == "uscode-bm25-tokenizer/v1"
    for field_name in (
        "citation",
        "title",
        "heading",
        "hierarchy",
        "body",
        "note",
    ):
        assert field_name in bm25_params["field_weights"]

    assert defaults["vector"]["default_probe_centroids"] >= 1
    fusion = defaults["fusion"]
    assert fusion["candidate_id"]
    assert fusion["config"]["method"] in {"weighted", "rrf"}
    assert fusion["evidence_partition"] == ev.SELECTION_PARTITION

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


def test_regressions_and_exceptions_explicit(report: dict[str, Any]) -> None:
    regressions = report["regressions"]
    assert "bm25_primary" in regressions
    assert "vector_primary" in regressions
    assert "fused_primary" in regressions
    assert "exceptions" in regressions
    assert isinstance(regressions["exceptions"], list)
    assert "no_unapproved_regression" in regressions
    assert "regression_tolerance" in regressions
    # Every exception must declare approval status.
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


def test_no_unsupported_production_claim(report: dict[str, Any]) -> None:
    claim = report["production_claim"]
    assert "production_searchable" in claim
    assert "claim" in claim
    assert isinstance(claim["claim"], str)
    assert claim["claim"]

    # When production_searchable is true, every authorizing gate must be true.
    if claim["production_searchable"] is True:
        for gate in (
            "component_bm25_production_searchable",
            "component_vector_production_searchable",
            "fused_dev_meets_gate",
            "fused_test_meets_gate",
            "dense_agreement_meets_gate",
            "no_unapproved_regression",
            "abstention_honesty",
            "graph_paths_ok",
        ):
            assert claim[gate] is True, gate
    else:
        # Explicit non-claim language for diagnostic fixture runs.
        assert "NO production-searchable claim" in claim["claim"]

    assert report["acceptance"]["no_unsupported_production_claim"] is True


def test_io_latency_memory_and_budget_surfaces(report: dict[str, Any]) -> None:
    io = report["io"]
    assert "fused_test" in io
    fused_io = io["fused_test"]
    for key in ("bytes_fetched", "shards_fetched", "latency_ms"):
        assert key in fused_io
        assert "p50" in fused_io[key]
        assert "p95" in fused_io[key]

    resources = report["resources"]
    assert resources["peak_memory_bytes"] > 0
    assert resources["build_throughput_rows_per_second"] > 0
    assert "cache_hit_ratio" in resources

    budget = report["budget_exhaustion"]
    assert budget["all_exhaustion_stops"] is True
    assert budget["scenarios"]
    assert any(s["exhausted"] for s in budget["scenarios"])
    assert any(not s["exhausted"] for s in budget["scenarios"])


def test_exact_citation_dense_graph_abstention_surfaces(
    report: dict[str, Any],
) -> None:
    fused = report["evaluation"]["partitions"]["test"]["fused"]
    assert "exact_citation_success_rate" in fused
    assert fused["exact_citation_query_count"] >= 0

    dense = report["dense_agreement"]["test"]
    assert "recall_at_1" in dense
    assert dense["probe_centroids"] >= 1

    graph = report["graph_path"]["from_component_report"]
    assert graph["available"] is True
    assert graph["ok"] is True
    assert float(graph["success_rate"]) == 1.0

    abstention = report["abstention"]
    assert abstention["all_honest"] is True
    assert abstention["case_count"] >= 1


def test_fixture_evaluation_is_deterministic(ev: ModuleType) -> None:
    a = ev.run_fixture_evaluation()
    b = ev.run_fixture_evaluation()
    assert a["fusion_selection"]["candidate_id"] == b["fusion_selection"]["candidate_id"]
    assert a["fusion_selection"]["config_digest"] == b["fusion_selection"]["config_digest"]
    assert (
        a["evaluation"]["partitions"]["test"]["fused"]["primary_metric_value"]
        == b["evaluation"]["partitions"]["test"]["fused"]["primary_metric_value"]
    )
    assert a["evaluation_cid"] == b["evaluation_cid"]
    assert a["production_claim"]["production_searchable"] == b["production_claim"][
        "production_searchable"
    ]


def test_cli_fixture_only_check(ev: ModuleType, report: dict[str, Any]) -> None:
    # Report already materialized by the report fixture.
    assert _REPORT_PATH.is_file()
    rc = ev.main(["--fixture-only", "--check"])
    assert rc == 0


def test_live_check_without_fixture_only_fails(ev: ModuleType) -> None:
    rc = ev.main(["--check"])
    assert rc == 1


def test_check_rejects_production_claim_without_gates(
    report: dict[str, Any],
    ev: ModuleType,
) -> None:
    bad = json.loads(json.dumps(report))
    bad["production_claim"] = dict(bad["production_claim"])
    bad["production_claim"]["production_searchable"] = True
    # Leave a required gate false.
    bad["production_claim"]["component_bm25_production_searchable"] = False
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
