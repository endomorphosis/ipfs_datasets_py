"""Batch 79: OntologyPipeline.history, ExtractionConfig.apply_defaults_for_domain,
OntologyOptimizer.score_history, OntologyCritic.top_dimension, OntologyMediator.action_log."""

from __future__ import annotations

import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parents[4]))

import pytest

from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    ExtractionConfig,
    OntologyGenerator,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_pipeline import OntologyPipeline
from ipfs_datasets_py.optimizers.graphrag.ontology_optimizer import (
    OntologyOptimizer,
    OptimizationReport,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic, CriticScore
from ipfs_datasets_py.optimizers.graphrag.ontology_mediator import OntologyMediator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mediator():
    gen = OntologyGenerator()
    crit = OntologyCritic()
    return OntologyMediator(gen, crit)


def _make_score(c=0.8, con=0.7, cl=0.6, g=0.5, da=0.9) -> CriticScore:
    return CriticScore(
        completeness=c, consistency=con, clarity=cl, granularity=g, domain_alignment=da
    )


def _make_report(score: float) -> OptimizationReport:
    return OptimizationReport(average_score=score, trend="stable")


# ---------------------------------------------------------------------------
# OntologyPipeline.history
# ---------------------------------------------------------------------------


class TestPipelineHistory:
    def test_empty_before_run(self):
        p = OntologyPipeline()
        assert p.history == []

    def test_returns_list(self):
        p = OntologyPipeline()
        assert isinstance(p.history, list)

    def test_copy_returned(self):
        p = OntologyPipeline()
        h1 = p.history
        h2 = p.history
        assert h1 is not h2

    def test_after_run_has_one_entry(self):
        p = OntologyPipeline()
        p.run("Alice and Bob worked at ACME Corp.")
        assert len(p.history) == 1

    def test_multiple_runs_accumulate(self):
        p = OntologyPipeline()
        p.run("Alice at ACME.")
        p.run("Bob at Widget Inc.")
        assert len(p.history) == 2

    def test_history_entries_are_pipeline_results(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_pipeline import PipelineResult
        p = OntologyPipeline()
        p.run("Alice at ACME.")
        assert isinstance(p.history[0], PipelineResult)


# ---------------------------------------------------------------------------
# ExtractionConfig.apply_defaults_for_domain
# ---------------------------------------------------------------------------


class TestApplyDefaultsForDomain:
    def test_legal_sets_threshold(self):
        cfg = ExtractionConfig()
        cfg.apply_defaults_for_domain("legal")
        assert cfg.confidence_threshold == pytest.approx(0.75, abs=1e-6)

    def test_medical_sets_high_threshold(self):
        cfg = ExtractionConfig()
        cfg.apply_defaults_for_domain("medical")
        assert cfg.confidence_threshold == pytest.approx(0.80, abs=1e-6)

    def test_general_sets_low_threshold(self):
        cfg = ExtractionConfig()
        cfg.apply_defaults_for_domain("general")
        assert cfg.confidence_threshold == pytest.approx(0.50, abs=1e-6)

    def test_unknown_domain_no_change(self):
        cfg = ExtractionConfig(confidence_threshold=0.42)
        cfg.apply_defaults_for_domain("unknown_domain_xyz")
        assert cfg.confidence_threshold == pytest.approx(0.42, abs=1e-6)

    def test_sets_max_entities(self):
        cfg = ExtractionConfig()
        cfg.apply_defaults_for_domain("finance")
        assert cfg.max_entities == 250

    def test_mutates_in_place(self):
        cfg = ExtractionConfig()
        original_id = id(cfg)
        cfg.apply_defaults_for_domain("legal")
        assert id(cfg) == original_id

    def test_case_insensitive(self):
        cfg1 = ExtractionConfig()
        cfg1.apply_defaults_for_domain("LEGAL")
        cfg2 = ExtractionConfig()
        cfg2.apply_defaults_for_domain("legal")
        assert cfg1.confidence_threshold == cfg2.confidence_threshold


# ---------------------------------------------------------------------------
# OntologyOptimizer.score_history
# ---------------------------------------------------------------------------


class TestScoreHistory:
    def test_empty_history(self):
        opt = OntologyOptimizer()
        assert opt.score_history() == []

    def test_returns_list(self):
        opt = OntologyOptimizer()
        assert isinstance(opt.score_history(), list)

    def test_single_entry(self):
        opt = OntologyOptimizer()
        opt._history.append(_make_report(0.75))
        assert opt.score_history() == [0.75]

    def test_multiple_entries_ordered(self):
        opt = OntologyOptimizer()
        opt._history.append(_make_report(0.5))
        opt._history.append(_make_report(0.7))
        opt._history.append(_make_report(0.9))
        assert opt.score_history() == [0.5, 0.7, 0.9]

    def test_values_are_floats(self):
        opt = OntologyOptimizer()
        opt._history.append(_make_report(0.6))
        assert all(isinstance(s, float) for s in opt.score_history())

    def test_length_matches_history_length(self):
        opt = OntologyOptimizer()
        for v in [0.3, 0.5, 0.7]:
            opt._history.append(_make_report(v))
        assert len(opt.score_history()) == opt.history_length


# ---------------------------------------------------------------------------
# OntologyCritic.top_dimension
# ---------------------------------------------------------------------------


class TestTopDimension:
    def setup_method(self):
        self.critic = OntologyCritic()

    def test_domain_alignment_highest(self):
        score = _make_score(c=0.5, con=0.4, cl=0.3, g=0.2, da=0.9)
        assert self.critic.top_dimension(score) == "domain_alignment"

    def test_completeness_highest(self):
        score = _make_score(c=0.95, con=0.1, cl=0.1, g=0.1, da=0.1)
        assert self.critic.top_dimension(score) == "completeness"

    def test_returns_string(self):
        score = _make_score()
        dim = self.critic.top_dimension(score)
        assert isinstance(dim, str)

    def test_result_is_valid_dimension(self):
        score = _make_score()
        valid_dims = {"completeness", "consistency", "clarity", "granularity", "domain_alignment"}
        assert self.critic.top_dimension(score) in valid_dims

    def test_consistency_highest(self):
        score = _make_score(c=0.1, con=0.99, cl=0.1, g=0.1, da=0.1)
        assert self.critic.top_dimension(score) == "consistency"

    def test_granularity_highest(self):
        score = _make_score(c=0.1, con=0.1, cl=0.1, g=0.8, da=0.1)
        assert self.critic.top_dimension(score) == "granularity"


# ---------------------------------------------------------------------------
# OntologyMediator.action_log
# ---------------------------------------------------------------------------


class TestActionLog:
    def test_empty_before_actions(self):
        med = _make_mediator()
        assert med.action_log() == []

    def test_returns_list(self):
        med = _make_mediator()
        assert isinstance(med.action_log(), list)

    def test_max_entries_limits_output(self):
        med = _make_mediator()
        for i in range(20):
            med._action_entries.append({"action": f"act_{i}", "round": i})
        result = med.action_log(max_entries=5)
        assert len(result) == 5

    def test_most_recent_entries_returned(self):
        med = _make_mediator()
        for i in range(10):
            med._action_entries.append({"action": f"act_{i}", "round": i})
        result = med.action_log(max_entries=3)
        assert result[0]["action"] == "act_7"
        assert result[-1]["action"] == "act_9"

    def test_entries_have_required_keys(self):
        med = _make_mediator()
        med._action_entries.append({"action": "merge", "round": 1})
        entry = med.action_log()[0]
        assert "action" in entry
        assert "round" in entry

    def test_default_max_50(self):
        med = _make_mediator()
        for i in range(100):
            med._action_entries.append({"action": "x", "round": i})
        assert len(med.action_log()) == 50
