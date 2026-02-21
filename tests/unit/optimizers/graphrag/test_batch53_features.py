"""Batch 53 tests.

Covers:
- ExtractionConfig.validate()
- CriticScore.__sub__()
- OntologyOptimizer.export_history_csv()
- OntologyMediator.get_action_stats()
"""
from __future__ import annotations

import csv
import io
from unittest.mock import MagicMock, patch

import pytest


# ──────────────────────────────────────────────────────────────────────────────
# ExtractionConfig.validate()
# ──────────────────────────────────────────────────────────────────────────────

class TestExtractionConfigValidate:
    """validate() should raise ValueError for invalid field combinations."""

    @pytest.fixture
    def valid_config(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import ExtractionConfig
        return ExtractionConfig()

    def test_default_config_is_valid(self, valid_config):
        valid_config.validate()  # should not raise

    def test_confidence_threshold_too_high(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import ExtractionConfig
        cfg = ExtractionConfig(confidence_threshold=1.1)
        with pytest.raises(ValueError, match="confidence_threshold"):
            cfg.validate()

    def test_confidence_threshold_negative(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import ExtractionConfig
        cfg = ExtractionConfig(confidence_threshold=-0.1)
        with pytest.raises(ValueError, match="confidence_threshold"):
            cfg.validate()

    def test_max_confidence_zero_invalid(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import ExtractionConfig
        cfg = ExtractionConfig(max_confidence=0.0)
        with pytest.raises(ValueError, match="max_confidence"):
            cfg.validate()

    def test_confidence_threshold_above_max_confidence(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import ExtractionConfig
        cfg = ExtractionConfig(confidence_threshold=0.8, max_confidence=0.5)
        with pytest.raises(ValueError, match="confidence_threshold"):
            cfg.validate()

    def test_max_entities_negative(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import ExtractionConfig
        cfg = ExtractionConfig(max_entities=-1)
        with pytest.raises(ValueError, match="max_entities"):
            cfg.validate()

    def test_max_relationships_negative(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import ExtractionConfig
        cfg = ExtractionConfig(max_relationships=-5)
        with pytest.raises(ValueError, match="max_relationships"):
            cfg.validate()

    def test_window_size_zero(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import ExtractionConfig
        cfg = ExtractionConfig(window_size=0)
        with pytest.raises(ValueError, match="window_size"):
            cfg.validate()

    def test_min_entity_length_zero(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import ExtractionConfig
        cfg = ExtractionConfig(min_entity_length=0)
        with pytest.raises(ValueError, match="min_entity_length"):
            cfg.validate()

    def test_llm_fallback_threshold_out_of_range(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import ExtractionConfig
        cfg = ExtractionConfig(llm_fallback_threshold=1.5)
        with pytest.raises(ValueError, match="llm_fallback_threshold"):
            cfg.validate()

    def test_valid_custom_config_passes(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import ExtractionConfig
        cfg = ExtractionConfig(
            confidence_threshold=0.3,
            max_confidence=0.9,
            max_entities=50,
            window_size=3,
            min_entity_length=2,
            llm_fallback_threshold=0.6,
        )
        cfg.validate()  # should not raise


# ──────────────────────────────────────────────────────────────────────────────
# CriticScore.__sub__()
# ──────────────────────────────────────────────────────────────────────────────

class TestCriticScoreSub:
    """CriticScore.__sub__() should compute per-dimension deltas."""

    @pytest.fixture
    def scores(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_critic import CriticScore
        a = CriticScore(completeness=0.8, consistency=0.7, clarity=0.6,
                        granularity=0.5, domain_alignment=0.9)
        b = CriticScore(completeness=0.6, consistency=0.5, clarity=0.4,
                        granularity=0.3, domain_alignment=0.7)
        return a, b

    def test_sub_returns_critic_score(self, scores):
        from ipfs_datasets_py.optimizers.graphrag.ontology_critic import CriticScore
        a, b = scores
        delta = a - b
        assert isinstance(delta, CriticScore)

    def test_sub_completeness_delta(self, scores):
        a, b = scores
        delta = a - b
        assert abs(delta.completeness - 0.2) < 1e-9

    def test_sub_consistency_delta(self, scores):
        a, b = scores
        delta = a - b
        assert abs(delta.consistency - 0.2) < 1e-9

    def test_sub_clarity_delta(self, scores):
        a, b = scores
        delta = a - b
        assert abs(delta.clarity - 0.2) < 1e-9

    def test_sub_granularity_delta(self, scores):
        a, b = scores
        delta = a - b
        assert abs(delta.granularity - 0.2) < 1e-9

    def test_sub_domain_alignment_delta(self, scores):
        a, b = scores
        delta = a - b
        assert abs(delta.domain_alignment - 0.2) < 1e-9

    def test_sub_metadata_marks_delta(self, scores):
        a, b = scores
        delta = a - b
        assert delta.metadata.get("delta") is True

    def test_sub_negative_delta_when_score_regressed(self, scores):
        a, b = scores
        delta = b - a  # regress
        assert delta.completeness < 0

    def test_sub_wrong_type_returns_not_implemented(self, scores):
        a, _ = scores
        result = a.__sub__("not a score")
        assert result is NotImplemented

    def test_identity_sub_gives_zero_deltas(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_critic import CriticScore
        s = CriticScore(completeness=0.7, consistency=0.7, clarity=0.7,
                        granularity=0.7, domain_alignment=0.7)
        delta = s - s
        for dim in ("completeness", "consistency", "clarity", "granularity", "domain_alignment"):
            assert abs(getattr(delta, dim)) < 1e-9


# ──────────────────────────────────────────────────────────────────────────────
# OntologyOptimizer.export_history_csv()
# ──────────────────────────────────────────────────────────────────────────────

class TestExportHistoryCsv:
    """export_history_csv() should return a CSV string or write to file."""

    @pytest.fixture
    def optimizer_with_history(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_optimizer import (
            OntologyOptimizer, OptimizationReport,
        )
        opt = OntologyOptimizer()
        for score in [0.5, 0.6, 0.75]:
            report = MagicMock(spec=OptimizationReport)
            report.average_score = score
            opt._history.append(report)
        return opt

    def test_returns_string_when_no_filepath(self, optimizer_with_history):
        csv_str = optimizer_with_history.export_history_csv()
        assert isinstance(csv_str, str)
        assert len(csv_str) > 0

    def test_csv_has_header_row(self, optimizer_with_history):
        csv_str = optimizer_with_history.export_history_csv()
        reader = csv.DictReader(io.StringIO(csv_str))
        assert set(reader.fieldnames or []) == {
            "batch_from", "batch_to", "score_from", "score_to", "delta", "direction"
        }

    def test_csv_row_count_equals_pairs(self, optimizer_with_history):
        csv_str = optimizer_with_history.export_history_csv()
        rows = list(csv.DictReader(io.StringIO(csv_str)))
        # 3 history entries → 2 consecutive pairs
        assert len(rows) == 2

    def test_csv_direction_correct(self, optimizer_with_history):
        csv_str = optimizer_with_history.export_history_csv()
        rows = list(csv.DictReader(io.StringIO(csv_str)))
        assert rows[0]["direction"] == "up"
        assert rows[1]["direction"] == "up"

    def test_csv_written_to_file(self, optimizer_with_history, tmp_path):
        outfile = str(tmp_path / "history.csv")
        result = optimizer_with_history.export_history_csv(filepath=outfile)
        assert result is None
        with open(outfile) as fh:
            content = fh.read()
        assert "batch_from" in content

    def test_empty_history_returns_header_only(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_optimizer import OntologyOptimizer
        opt = OntologyOptimizer()
        csv_str = opt.export_history_csv()
        lines = [l for l in csv_str.splitlines() if l.strip()]
        assert len(lines) == 1  # header only


# ──────────────────────────────────────────────────────────────────────────────
# OntologyMediator.get_action_stats()
# ──────────────────────────────────────────────────────────────────────────────

class TestMediatorGetActionStats:
    """get_action_stats() should track cumulative per-action counts."""

    @pytest.fixture
    def mediator(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_mediator import OntologyMediator
        from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import OntologyGenerator
        return OntologyMediator(
            generator=OntologyGenerator(),
            critic=OntologyCritic(use_llm=False),
        )

    def _make_feedback(self, recs):
        fb = MagicMock()
        fb.recommendations = recs
        fb.completeness = fb.consistency = fb.clarity = fb.granularity = fb.domain_alignment = 0.7
        return fb

    def test_empty_stats_before_any_calls(self, mediator):
        assert mediator.get_action_stats() == {}

    def test_action_counted_after_refine(self, mediator):
        ontology = {"entities": [{"id": "e1", "text": "alice", "type": "Person",
                                   "confidence": 0.8}], "relationships": []}
        feedback = self._make_feedback(["rename entity casing"])
        mediator.refine_ontology(ontology, feedback, MagicMock())
        stats = mediator.get_action_stats()
        assert "rename_entity" in stats
        assert stats["rename_entity"] >= 1

    def test_cumulative_counts_across_calls(self, mediator):
        ontology = {"entities": [{"id": "e1", "text": "alice", "type": "Person",
                                   "confidence": 0.8}], "relationships": []}
        fb = self._make_feedback(["rename entity casing"])
        mediator.refine_ontology(ontology, fb, MagicMock())
        mediator.refine_ontology(ontology, fb, MagicMock())
        stats = mediator.get_action_stats()
        assert stats.get("rename_entity", 0) == 2

    def test_returns_copy_not_reference(self, mediator):
        stats = mediator.get_action_stats()
        stats["injected"] = 999
        assert "injected" not in mediator.get_action_stats()
