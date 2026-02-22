"""
Session 69 tests — deferred v4.0+ features implemented.

Validates:
1. ``KnowledgeGraphExtractor.aggregate_confidence_scores()`` — multi-source
   confidence aggregation (6 methods).
2. ``KnowledgeGraphExtractor.compute_extraction_quality_metrics()`` — quality
   metrics for extracted graphs.
3. ``GraphData.export_streaming()`` ``progress_callback`` parameter.
4. ``extraction/README.md`` Phase 5 status fixed (In Progress → Complete ✅).
5. DEFERRED_FEATURES.md updated to mark these features ✅ Implemented.
6. Version agreement across MASTER_STATUS / CHANGELOG / ROADMAP (v3.22.23).
"""

import math
import pathlib
import tempfile
import os

import pytest

_ROOT = pathlib.Path(__file__).parents[3]
_KG = _ROOT / "ipfs_datasets_py" / "knowledge_graphs"

_MASTER_STATUS = _KG / "MASTER_STATUS.md"
_CHANGELOG = _KG / "CHANGELOG_KNOWLEDGE_GRAPHS.md"
_ROADMAP = _KG / "ROADMAP.md"
_DEFERRED = _KG / "DEFERRED_FEATURES.md"
_EXTRACTION_README = _KG / "extraction" / "README.md"


def _read(p: pathlib.Path) -> str:
    return p.read_text(encoding="utf-8")


# ─────────────────────────────────────────────────────────────────────────────
# 1. aggregate_confidence_scores
# ─────────────────────────────────────────────────────────────────────────────

class TestAggregateConfidenceScores:
    """Tests for KnowledgeGraphExtractor.aggregate_confidence_scores()."""

    @pytest.fixture(autouse=True)
    def _import(self):
        from ipfs_datasets_py.knowledge_graphs.extraction.extractor import (
            KnowledgeGraphExtractor,
        )
        self.agg = KnowledgeGraphExtractor.aggregate_confidence_scores

    def test_empty_returns_zero(self):
        assert self.agg([]) == 0.0

    def test_mean(self):
        result = self.agg([0.9, 0.8, 0.7])
        assert abs(result - 0.8) < 1e-9

    def test_min(self):
        assert self.agg([0.9, 0.5, 0.8], method="min") == 0.5

    def test_max(self):
        assert self.agg([0.9, 0.5, 0.8], method="max") == 0.9

    def test_harmonic_mean(self):
        scores = [0.9, 0.8, 0.7]
        n = len(scores)
        expected = n / sum(1.0 / s for s in scores)
        result = self.agg(scores, method="harmonic_mean")
        assert abs(result - expected) < 1e-9

    def test_harmonic_mean_with_zero_score(self):
        # zero score → denominator would be inf; returns 0.0
        result = self.agg([0.9, 0.0, 0.8], method="harmonic_mean")
        assert result == 0.0

    def test_weighted_mean(self):
        scores = [1.0, 0.0]
        weights = [0.8, 0.2]
        result = self.agg(scores, method="weighted_mean", weights=weights)
        assert abs(result - 0.8) < 1e-9

    def test_weighted_mean_falls_back_to_mean_when_no_weights(self):
        scores = [0.6, 0.4]
        result = self.agg(scores, method="weighted_mean")
        assert abs(result - 0.5) < 1e-9

    def test_weighted_mean_zero_total_weight_returns_zero(self):
        result = self.agg([0.9], method="weighted_mean", weights=[0.0])
        assert result == 0.0

    def test_probabilistic_and(self):
        scores = [0.9, 0.8, 0.7]
        expected = 0.9 * 0.8 * 0.7
        result = self.agg(scores, method="probabilistic_and")
        assert abs(result - expected) < 1e-9

    def test_single_score_all_methods(self):
        for method in ("mean", "min", "max", "harmonic_mean", "weighted_mean",
                       "probabilistic_and"):
            result = self.agg([0.75], method=method)
            assert result == 0.75, f"method={method!r} failed with single score"

    def test_unknown_method_raises_value_error(self):
        with pytest.raises(ValueError, match="Unknown aggregation method"):
            self.agg([0.5], method="unknown")


# ─────────────────────────────────────────────────────────────────────────────
# 2. compute_extraction_quality_metrics
# ─────────────────────────────────────────────────────────────────────────────

class TestComputeExtractionQualityMetrics:
    """Tests for KnowledgeGraphExtractor.compute_extraction_quality_metrics()."""

    @pytest.fixture(autouse=True)
    def _import(self):
        from ipfs_datasets_py.knowledge_graphs.extraction.extractor import (
            KnowledgeGraphExtractor,
        )
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph
        self.metrics_fn = KnowledgeGraphExtractor.compute_extraction_quality_metrics
        self.KG = KnowledgeGraph

    def _build_kg(self):
        """Build a small test graph with 4 entities (1 isolated) and 2 rels."""
        kg = self.KG()
        alice = kg.add_entity("person", name="Alice", confidence=0.9)
        bob = kg.add_entity("person", name="Bob", confidence=0.8)
        acme = kg.add_entity("organization", name="Acme", confidence=0.7)
        kg.add_entity("entity", name="Isolated", confidence=0.3)
        kg.add_relationship("works_for", alice, acme, confidence=0.85)
        kg.add_relationship("knows", alice, bob, confidence=0.75)
        return kg

    def test_empty_graph(self):
        m = self.metrics_fn(self.KG())
        assert m["entity_count"] == 0
        assert m["relationship_count"] == 0
        assert m["relationship_density"] == 0.0
        assert m["isolated_entity_ratio"] == 0.0

    def test_entity_and_relationship_counts(self):
        m = self.metrics_fn(self._build_kg())
        assert m["entity_count"] == 4
        assert m["relationship_count"] == 2

    def test_relationship_density(self):
        m = self.metrics_fn(self._build_kg())
        assert abs(m["relationship_density"] - 0.5) < 1e-9

    def test_avg_entity_confidence(self):
        m = self.metrics_fn(self._build_kg())
        # (0.9 + 0.8 + 0.7 + 0.3) / 4 = 0.675
        assert abs(m["avg_entity_confidence"] - 0.675) < 1e-9

    def test_avg_relationship_confidence(self):
        m = self.metrics_fn(self._build_kg())
        # (0.85 + 0.75) / 2 = 0.8
        assert abs(m["avg_relationship_confidence"] - 0.8) < 1e-9

    def test_confidence_std_is_non_negative(self):
        m = self.metrics_fn(self._build_kg())
        assert m["confidence_std"] >= 0.0

    def test_low_confidence_ratio(self):
        m = self.metrics_fn(self._build_kg())
        # 6 scores; only 0.3 < 0.5 → 1/6
        assert abs(m["low_confidence_ratio"] - 1 / 6) < 1e-9

    def test_entity_type_diversity(self):
        m = self.metrics_fn(self._build_kg())
        # person, organization, entity → 3
        assert m["entity_type_diversity"] == 3

    def test_relationship_type_diversity(self):
        m = self.metrics_fn(self._build_kg())
        # works_for, knows → 2
        assert m["relationship_type_diversity"] == 2

    def test_isolated_entity_ratio(self):
        m = self.metrics_fn(self._build_kg())
        # Only 'Isolated' entity has no relationships → 1/4
        assert abs(m["isolated_entity_ratio"] - 0.25) < 1e-9

    def test_all_keys_present(self):
        m = self.metrics_fn(self._build_kg())
        expected_keys = {
            "entity_count", "relationship_count", "relationship_density",
            "avg_entity_confidence", "avg_relationship_confidence",
            "confidence_std", "low_confidence_ratio",
            "entity_type_diversity", "relationship_type_diversity",
            "isolated_entity_ratio",
        }
        assert expected_keys == set(m.keys())


# ─────────────────────────────────────────────────────────────────────────────
# 3. export_streaming progress_callback
# ─────────────────────────────────────────────────────────────────────────────

class TestExportStreamingProgressCallback:
    """Tests for GraphData.export_streaming() progress_callback parameter."""

    @pytest.fixture(autouse=True)
    def _import(self):
        from ipfs_datasets_py.knowledge_graphs.migration.formats import (
            GraphData, NodeData, RelationshipData,
        )
        self.GraphData = GraphData
        self.NodeData = NodeData
        self.RelationshipData = RelationshipData

    def _build_graph(self, n_nodes=5, n_rels=4):
        nodes = [self.NodeData(id=str(i), labels=["N"], properties={"v": i})
                 for i in range(n_nodes)]
        rels = [self.RelationshipData(id=str(i), type="R",
                                       start_node=str(i), end_node=str(i + 1))
                for i in range(n_rels)]
        return self.GraphData(nodes=nodes, relationships=rels)

    def test_no_callback_still_works(self, tmp_path):
        g = self._build_graph()
        nw, rw = g.export_streaming(str(tmp_path / "out.jsonl"))
        assert nw == 5
        assert rw == 4

    def test_callback_called_with_correct_totals(self, tmp_path):
        g = self._build_graph(n_nodes=5, n_rels=4)
        calls = []
        g.export_streaming(
            str(tmp_path / "out.jsonl"),
            chunk_size=2,
            progress_callback=lambda nw, nt, rw, rt: calls.append((nw, nt, rw, rt)),
        )
        # Each call must have total_nodes=5 and total_rels=4
        for nw, nt, rw, rt in calls:
            assert nt == 5
            assert rt == 4

    def test_callback_nodes_monotonically_increasing(self, tmp_path):
        g = self._build_graph(n_nodes=6, n_rels=3)
        node_progress = []
        g.export_streaming(
            str(tmp_path / "out.jsonl"),
            chunk_size=2,
            progress_callback=lambda nw, nt, rw, rt: node_progress.append(nw),
        )
        # nodes_written must never decrease across calls
        for a, b in zip(node_progress, node_progress[1:]):
            assert b >= a

    def test_callback_final_call_has_all_nodes_and_rels(self, tmp_path):
        g = self._build_graph(n_nodes=5, n_rels=4)
        calls = []
        g.export_streaming(
            str(tmp_path / "out.jsonl"),
            chunk_size=3,
            progress_callback=lambda nw, nt, rw, rt: calls.append((nw, nt, rw, rt)),
        )
        assert calls, "callback must be called at least once"
        last_nw, last_nt, last_rw, last_rt = calls[-1]
        assert last_nw == 5
        assert last_rw == 4

    def test_callback_called_for_each_chunk(self, tmp_path):
        # chunk_size=2 with 5 nodes → 3 node-chunks + 2 rel-chunks (4 rels)
        g = self._build_graph(n_nodes=5, n_rels=4)
        calls = []
        g.export_streaming(
            str(tmp_path / "out.jsonl"),
            chunk_size=2,
            progress_callback=lambda *a: calls.append(a),
        )
        assert len(calls) == 5  # ceil(5/2)=3 node chunks + ceil(4/2)=2 rel chunks


# ─────────────────────────────────────────────────────────────────────────────
# 4. extraction/README.md Phase 5 status
# ─────────────────────────────────────────────────────────────────────────────

class TestExtractionReadmePhase5Fixed:
    """extraction/README.md Phase 5 status must be Complete ✅, not In Progress."""

    def test_phase5_not_in_progress(self):
        txt = _read(_EXTRACTION_README)
        assert "Phase 5: Production Readiness\n- **Status:** In Progress" not in txt, \
            "extraction/README.md still says 'Phase 5: Production Readiness — In Progress'"

    def test_phase5_complete(self):
        txt = _read(_EXTRACTION_README)
        assert "Phase 5: Production Readiness" in txt
        assert "Complete" in txt

    def test_no_duplicate_security_audit_line(self):
        txt = _read(_EXTRACTION_README)
        # Original had "Security audit and validation" twice — should only appear once now
        count = txt.count("Security audit and validation")
        assert count <= 1, f"'Security audit and validation' appears {count} times; expected 1"


# ─────────────────────────────────────────────────────────────────────────────
# 5. DEFERRED_FEATURES.md updated
# ─────────────────────────────────────────────────────────────────────────────

class TestDeferredFeaturesUpdated:
    """DEFERRED_FEATURES.md must mark confidence scoring and progress tracking ✅."""

    def test_confidence_scoring_marked_implemented(self):
        txt = _read(_DEFERRED)
        assert "Implemented" in txt and ("3.22.23" in txt or "aggregate_confidence_scores" in txt), \
            "DEFERRED_FEATURES.md should note confidence scoring implemented in v3.22.23"

    def test_progress_tracking_marked_implemented(self):
        txt = _read(_DEFERRED)
        assert "progress_callback" in txt or "progress tracking" in txt.lower(), \
            "DEFERRED_FEATURES.md should mention progress_callback / progress tracking"


# ─────────────────────────────────────────────────────────────────────────────
# 6. Version agreement
# ─────────────────────────────────────────────────────────────────────────────

class TestVersionAgreement:
    """MASTER_STATUS, CHANGELOG, and ROADMAP must all reference v3.22.23."""

    def test_master_status_has_v3_22_23(self):
        assert "3.22.23" in _read(_MASTER_STATUS)

    def test_changelog_has_v3_22_23(self):
        assert "3.22.23" in _read(_CHANGELOG)

    def test_roadmap_has_v3_22_23(self):
        assert "3.22.23" in _read(_ROADMAP)
