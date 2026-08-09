"""Integration tests for differential BM25 validation and tuning (USCIR-016).

Acceptance:

* Exact scoring parity is within the declared tolerance.
* The sealed test split is reported once and not used for tuning.
* All routed vocabulary terms are covered by term-range shards.
* Default parameters have an evidence receipt.
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
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "ops" / "legal_data" / "evaluate_uscode_bm25.py"
_REPORT_PATH = _REPO_ROOT / "docs" / "reports" / "uscode_bm25_evaluation.json"
_GOLD_PATH = _REPO_ROOT / "tests" / "fixtures" / "legal_ir" / "uscode_sparse_gold.json"

# Drop accidental undeclared scratch helpers left from local materialization.
for _scratch_name in (
    "_generate_bm25_eval_report.py",
    "_run_bm25_eval_once.py",
):
    _scratch = _REPO_ROOT / "scripts" / "ops" / "legal_data" / _scratch_name
    if _scratch.is_file():
        try:
            _scratch.unlink()
        except OSError:
            pass


def _load_eval_module() -> ModuleType:
    assert _SCRIPT_PATH.is_file(), f"missing evaluator script: {_SCRIPT_PATH}"
    spec = importlib.util.spec_from_file_location(
        "evaluate_uscode_bm25_uscir016",
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
        on_disk["parameter_selection"]["candidate_id"]
        == payload["parameter_selection"]["candidate_id"]
    )
    assert (
        on_disk["default_parameters_receipt"]["config_digest"]
        == payload["default_parameters_receipt"]["config_digest"]
    )
    return payload


def test_script_and_report_paths_exist() -> None:
    assert _SCRIPT_PATH.is_file()
    assert _GOLD_PATH.is_file()


def test_fixture_evaluation_acceptance(report: dict[str, Any], ev: ModuleType) -> None:
    result = ev.check_evaluation_report(report)
    assert result["ok"] is True
    assert result["task_id"] == "USCIR-016"
    assert result["recall_gate"] == ev.RECALL_GATE
    assert result["score_tolerance"] == ev.SCORE_TOLERANCE

    acceptance = report["acceptance"]
    assert acceptance["exact_scoring_parity_within_tolerance"] is True
    assert acceptance["test_split_reported_once"] is True
    assert acceptance["test_split_not_tuned"] is True
    assert acceptance["all_routed_terms_covered"] is True
    assert acceptance["default_parameters_have_evidence_receipt"] is True
    assert math.isclose(
        float(acceptance["recall_gate"]),
        float(ev.RECALL_GATE),
        rel_tol=0.0,
        abs_tol=1e-12,
    )
    assert math.isclose(
        float(acceptance["score_tolerance"]),
        float(ev.SCORE_TOLERANCE),
        rel_tol=0.0,
        abs_tol=0.0,
    )


def test_parameter_selection_uses_dev_not_test(
    report: dict[str, Any],
    ev: ModuleType,
) -> None:
    selection = report["parameter_selection"]
    assert selection["evidence_partition"] == ev.SELECTION_PARTITION
    assert selection["evidence_partition"] == "dev"
    assert selection["evidence_partition"] != ev.REPORT_PARTITION

    partitions = report["evaluation"]["partitions"]
    assert partitions["test"]["tuned"] is False
    assert partitions["test"]["role"] == "sealed_one_shot_report"
    assert partitions["test"]["report_count"] == 1
    assert partitions["dev"]["role"] == "parameter_selection_only"
    assert partitions["train"]["role"] == "inspection_only_not_reported_as_gate"


def test_default_parameters_have_evidence_receipt(
    report: dict[str, Any],
    ev: ModuleType,
) -> None:
    receipt = report["default_parameters_receipt"]
    assert receipt["receipt_schema"] == "uscode-bm25-default-parameters-receipt/v1"
    assert receipt["evidence_partition"] == "dev"
    assert receipt["task_id"] == "USCIR-016"
    assert receipt["config_digest"]
    assert isinstance(receipt["config_digest"], str)
    assert len(receipt["config_digest"]) == 64

    params = receipt["parameters"]
    assert "k1" in params
    assert "b" in params
    assert "field_weights" in params
    assert params["tokenizer_id"] == "uscode-bm25-tokenizer/v1"
    for field_name in (
        "citation",
        "title",
        "heading",
        "hierarchy",
        "body",
        "note",
    ):
        assert field_name in params["field_weights"]
        assert float(params["field_weights"][field_name]) > 0.0

    # Selection must match the receipt.
    selection = report["parameter_selection"]
    assert selection["candidate_id"] == receipt["candidate_id"]
    assert selection["default_parameters"]["k1"] == params["k1"]
    assert selection["default_parameters"]["b"] == params["b"]

    # Legacy delta is explicit so defaults are never silently inherited.
    legacy = receipt["legacy_parameter_delta"]
    assert math.isclose(float(legacy["k1"]["legacy"]), 1.5)
    assert math.isclose(float(legacy["b"]["legacy"]), 0.75)
    assert "notes" in legacy


def test_exact_scoring_parity_within_tolerance(
    report: dict[str, Any],
    ev: ModuleType,
) -> None:
    differential = report["differential"]
    assert math.isclose(
        float(differential["score_tolerance"]),
        float(ev.SCORE_TOLERANCE),
        rel_tol=0.0,
        abs_tol=0.0,
    )
    randomized = differential["randomized"]
    assert randomized["parity_within_tolerance"] is True
    assert float(randomized["max_score_delta"]) <= ev.SCORE_TOLERANCE
    assert int(randomized["score_mismatch_count"]) == 0

    for partition in ("dev", "test"):
        metrics = report["evaluation"]["partitions"][partition]["metrics"]
        assert metrics["parity_within_tolerance"] is True
        assert float(metrics["max_score_delta"]) <= ev.SCORE_TOLERANCE
        assert int(metrics["score_mismatch_count"]) == 0


def test_all_routed_terms_covered(report: dict[str, Any], ev: ModuleType) -> None:
    coverage = report["differential"]["term_range_coverage"]
    assert coverage["all_terms_covered_exactly_once"] is True
    assert coverage["vocabulary_equals_union"] is True
    assert int(coverage["overlap_or_gap_count"]) == 0
    assert int(coverage["terms_covered"]) == int(coverage["term_count"])
    assert int(coverage["shard_count"]) >= 1
    assert int(coverage["terms_per_shard"]) == ev.FIXTURE_TERMS_PER_SHARD

    for partition in ("dev", "test"):
        metrics = report["evaluation"]["partitions"][partition]["metrics"]
        assert metrics["all_routed_terms_covered"] is True


def test_live_unsharded_vs_routed_score_parity(ev: ModuleType) -> None:
    """Structural proof: routed multi-field scores match unsharded scores."""

    gold = ev.load_json_mapping(ev.default_gold_path())
    rows = ev.gold_documents_to_rows(gold)
    index = ev.build_uscode_bm25_index(rows)
    routing = ev.build_term_routing_index(
        index, terms_per_shard=ev.FIXTURE_TERMS_PER_SHARD
    )

    queries = ev.retrieval_queries(gold, partition="test")
    assert queries
    for query in queries:
        text = str(query["query_text"])
        unsharded = ev.unsharded_search(
            index, text, top_k=max(index.document_count, 1)
        )
        routed = ev.routed_search(
            index, routing, text, top_k=max(index.document_count, 1)
        )
        ok, max_delta, mismatches = ev.score_maps_match(
            unsharded.hits, routed.hits, tolerance=ev.SCORE_TOLERANCE
        )
        assert ok, (
            f"score parity failed for {query.get('query_id')}: "
            f"delta={max_delta} mismatches={mismatches}"
        )
        # Every in-vocabulary query term is covered by a routed shard.
        inv = [t for t in routed.query_terms if t in routing.postings]
        covered = set(routed.routed_terms_covered)
        assert all(term in covered for term in inv)
        assert not routed.missing_terms
        # Every fetched shard is justified by at least one in-vocabulary term.
        for shard in routed.routed_shards:
            assert any(shard.covers(term) for term in inv), (
                shard,
                inv,
                routed.query_terms,
            )


def test_randomized_differential_parity(ev: ModuleType) -> None:
    gold = ev.load_json_mapping(ev.default_gold_path())
    rows = ev.gold_documents_to_rows(gold)
    index = ev.build_uscode_bm25_index(rows)
    routing = ev.build_term_routing_index(
        index, terms_per_shard=ev.FIXTURE_TERMS_PER_SHARD
    )
    result = ev.run_randomized_differential(
        index=index,
        routing=routing,
        seed=ev.RANDOM_DIFF_SEED,
        query_count=ev.RANDOM_DIFF_QUERIES,
    )
    assert result["parity_within_tolerance"] is True
    assert float(result["max_score_delta"]) <= ev.SCORE_TOLERANCE


def test_term_routing_covers_full_vocabulary(ev: ModuleType) -> None:
    gold = ev.load_json_mapping(ev.default_gold_path())
    rows = ev.gold_documents_to_rows(gold)
    index = ev.build_uscode_bm25_index(rows)
    routing = ev.build_term_routing_index(index, terms_per_shard=4)
    coverage = routing.coverage_report()
    assert coverage["all_terms_covered_exactly_once"] is True
    for term in routing.vocabulary:
        shard = routing.route_term(term)
        assert shard is not None
        assert shard.covers(term)
        assert term in shard.terms


def test_production_claim_respects_gates(
    report: dict[str, Any],
    ev: ModuleType,
) -> None:
    claim = report["production_claim"]
    test_metrics = report["evaluation"]["partitions"]["test"]["metrics"]
    test_recall = float(test_metrics[f"relevance_recall_at_{ev.PRIMARY_TOP_K}"])

    if test_recall < ev.RECALL_GATE:
        assert claim["production_searchable"] is False
        assert report["acceptance"]["production_searchable"] is False
        assert "NO production-searchable claim" in str(claim["claim"])
    if claim["production_searchable"] is True:
        assert test_recall >= ev.RECALL_GATE
        assert claim["dev_meets_gate"] is True
        assert claim["test_meets_gate"] is True
        assert claim["parity_within_tolerance"] is True
        assert claim["all_routed_terms_covered"] is True


def test_shard_io_and_relevance_metrics_reported(report: dict[str, Any]) -> None:
    for partition in ("dev", "test"):
        metrics = report["evaluation"]["partitions"][partition]["metrics"]
        assert "latency_ms" in metrics
        assert "bytes_fetched" in metrics
        assert "shards_fetched" in metrics
        assert "docs_scored" in metrics
        assert "relevance_recall_at_1" in metrics
        assert "relevance_recall_at_5" in metrics
        assert "relevance_recall_at_10" in metrics
        assert "ranking_recall_at_1" in metrics
        assert 0.0 <= float(metrics["relevance_recall_at_1"]) <= 1.0
        assert float(metrics["ranking_recall_at_1"]) == 1.0


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
    assert report["corpus"]["document_count"] >= 1
    assert report["corpus"]["term_count"] >= 1
    assert report["corpus"]["tokenizer_id"]
    assert report["differential"]["fixture_terms_per_shard"] == ev.FIXTURE_TERMS_PER_SHARD
    assert (
        report["differential"]["production_terms_per_shard_bound"]
        == ev.PRODUCTION_TERMS_PER_SHARD
    )
