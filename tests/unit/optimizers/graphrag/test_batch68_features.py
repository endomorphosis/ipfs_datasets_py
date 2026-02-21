"""Batch-68 feature tests.

Covers:
- CriticScore.to_html_report()
- OntologyCritic.score_trend()
- OntologyOptimizer.emit_summary_log()
- OntologyPipeline.run_with_metrics()
- LogicValidator.explain_entity()
"""

import pytest

from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic, CriticScore
from ipfs_datasets_py.optimizers.graphrag.ontology_optimizer import OntologyOptimizer, OptimizationReport
from ipfs_datasets_py.optimizers.graphrag.ontology_pipeline import OntologyPipeline
from ipfs_datasets_py.optimizers.graphrag.logic_validator import LogicValidator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _score(overall_value: float) -> CriticScore:
    v = overall_value
    return CriticScore(
        completeness=v, consistency=v, clarity=v, granularity=v, domain_alignment=v,
        recommendations=["Add entities", "Improve clarity"] if v < 0.8 else [],
    )


def _critic() -> OntologyCritic:
    return OntologyCritic(use_llm=False)


def _validator() -> LogicValidator:
    return LogicValidator()


def _optimizer_with_scores(scores):
    opt = OntologyOptimizer()
    for i, s in enumerate(scores):
        opt._history.append(OptimizationReport(
            average_score=s,
            trend="stable",
            improvement_rate=0.5,
            metadata={"num_sessions": 1},
        ))
    return opt


# ---------------------------------------------------------------------------
# CriticScore.to_html_report
# ---------------------------------------------------------------------------

class TestCriticScoreToHtmlReport:
    def test_returns_string(self):
        assert isinstance(_score(0.7).to_html_report(), str)

    def test_contains_table_tag(self):
        html = _score(0.7).to_html_report()
        assert "<table" in html

    def test_contains_all_dims(self):
        html = _score(0.7).to_html_report()
        for dim in ("Completeness", "Consistency", "Clarity", "Granularity", "Domain Alignment"):
            assert dim in html

    def test_contains_overall(self):
        html = _score(0.7).to_html_report()
        assert "Overall" in html

    def test_recs_included(self):
        html = _score(0.5).to_html_report()
        assert "Add entities" in html

    def test_no_recs_message(self):
        score = CriticScore(completeness=0.9, consistency=0.9, clarity=0.9, granularity=0.9, domain_alignment=0.9)
        html = score.to_html_report()
        assert "No recommendations" in html

    def test_scores_in_output(self):
        score = CriticScore(completeness=0.75, consistency=0.75, clarity=0.75, granularity=0.75, domain_alignment=0.75)
        html = score.to_html_report()
        assert "0.7500" in html


# ---------------------------------------------------------------------------
# OntologyCritic.score_trend
# ---------------------------------------------------------------------------

class TestScoreTrend:
    def test_returns_string(self):
        critic = _critic()
        result = critic.score_trend([_score(0.5), _score(0.7)])
        assert isinstance(result, str)

    def test_improving(self):
        critic = _critic()
        result = critic.score_trend([_score(0.3), _score(0.5), _score(0.7), _score(0.9)])
        assert result == "improving"

    def test_degrading(self):
        critic = _critic()
        result = critic.score_trend([_score(0.9), _score(0.7), _score(0.5), _score(0.3)])
        assert result == "degrading"

    def test_stable(self):
        critic = _critic()
        # All same — slope = 0
        result = critic.score_trend([_score(0.7), _score(0.7), _score(0.7)])
        assert result == "stable"

    def test_single_score_raises(self):
        critic = _critic()
        with pytest.raises(ValueError):
            critic.score_trend([_score(0.5)])

    def test_empty_raises(self):
        critic = _critic()
        with pytest.raises(ValueError):
            critic.score_trend([])

    def test_valid_labels(self):
        critic = _critic()
        result = critic.score_trend([_score(0.4), _score(0.6)])
        assert result in ("improving", "stable", "degrading")


# ---------------------------------------------------------------------------
# OntologyOptimizer.emit_summary_log
# ---------------------------------------------------------------------------

class TestEmitSummaryLog:
    def test_returns_string(self):
        opt = _optimizer_with_scores([0.5, 0.7])
        assert isinstance(opt.emit_summary_log(), str)

    def test_starts_with_prefix(self):
        opt = _optimizer_with_scores([0.5])
        assert opt.emit_summary_log().startswith("[OntologyOptimizer]")

    def test_contains_batches(self):
        opt = _optimizer_with_scores([0.5, 0.6, 0.7])
        line = opt.emit_summary_log()
        assert "batches=3" in line

    def test_empty_history(self):
        opt = OntologyOptimizer()
        line = opt.emit_summary_log()
        assert "batches=0" in line
        assert "N/A" in line

    def test_contains_trend(self):
        opt = _optimizer_with_scores([0.3, 0.9])
        line = opt.emit_summary_log()
        assert "trend=" in line

    def test_contains_variance(self):
        opt = _optimizer_with_scores([0.4, 0.6])
        line = opt.emit_summary_log()
        assert "variance=" in line


# ---------------------------------------------------------------------------
# OntologyPipeline.run_with_metrics
# ---------------------------------------------------------------------------

class TestRunWithMetrics:
    def test_returns_dict(self):
        p = OntologyPipeline(domain="test")
        result = p.run_with_metrics("Alice works at ACME.")
        assert isinstance(result, dict)

    def test_result_key_present(self):
        p = OntologyPipeline(domain="test")
        metrics = p.run_with_metrics("Alice.")
        assert "result" in metrics

    def test_latency_non_negative(self):
        p = OntologyPipeline(domain="test")
        metrics = p.run_with_metrics("Alice.")
        assert metrics["latency_seconds"] >= 0

    def test_score_in_range(self):
        p = OntologyPipeline(domain="test")
        metrics = p.run_with_metrics("Alice.")
        assert 0.0 <= metrics["score"] <= 1.0

    def test_entity_count_int(self):
        p = OntologyPipeline(domain="test")
        metrics = p.run_with_metrics("Alice founded ACME Corp.")
        assert isinstance(metrics["entity_count"], int)
        assert metrics["entity_count"] >= 0

    def test_all_expected_keys(self):
        p = OntologyPipeline(domain="test")
        metrics = p.run_with_metrics("Test.")
        assert {"result", "latency_seconds", "score", "entity_count"} <= set(metrics.keys())


# ---------------------------------------------------------------------------
# LogicValidator.explain_entity
# ---------------------------------------------------------------------------

class TestExplainEntity:
    def test_returns_dict(self):
        result = _validator().explain_entity({"id": "e1", "type": "Person", "text": "Alice"})
        assert isinstance(result, dict)

    def test_required_keys(self):
        result = _validator().explain_entity({"id": "e1", "type": "T", "text": "x"})
        assert "entity_id" in result
        assert "is_valid" in result
        assert "contradictions" in result
        assert "explanation" in result

    def test_entity_id_matches(self):
        result = _validator().explain_entity({"id": "my_id", "type": "T", "text": "x"})
        assert result["entity_id"] == "my_id"

    def test_valid_entity_is_valid(self):
        result = _validator().explain_entity({"id": "e1", "type": "Person", "text": "Alice"})
        assert result["is_valid"] is True

    def test_valid_entity_no_contradictions(self):
        result = _validator().explain_entity({"id": "e1", "type": "Person", "text": "Alice"})
        assert result["contradictions"] == []

    def test_explanation_is_string(self):
        result = _validator().explain_entity({"id": "e1", "type": "T", "text": "x"})
        assert isinstance(result["explanation"], str)

    def test_handles_missing_id(self):
        result = _validator().explain_entity({"type": "T", "text": "x"})
        assert result["entity_id"] == "unknown"
