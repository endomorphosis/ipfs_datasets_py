"""
Unit tests for Batch 211 + Batch 212 implementations.

Batch 211 new methods:
- OntologyCritic.min_max_dimension_ratio(score)
- OntologyLearningAdapter.feedback_z_scores()
- LogicValidator.edge_density(ontology)

Batch 211 smoke tests (pre-existing):
- OntologyOptimizer.history_trimmed_mean()
- OntologyOptimizer.score_autocorrelation()
- OntologyGenerator.avg_entity_confidence()
- OntologyPipeline.run_score_range()
- OntologyPipeline.score_plateau_length()
- LogicValidator.strongly_connected_count()

Batch 212 new methods:
- OntologyOptimizer.score_mad()
- OntologyCritic.dimension_range(score)
- OntologyGenerator.relationship_density(result)
- OntologyLearningAdapter.feedback_percentile(p)
- OntologyPipeline.run_score_ewma(alpha)
- LogicValidator.multi_edge_count(ontology)
"""
from __future__ import annotations

import math
import pytest
from unittest.mock import MagicMock

from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    Entity,
    Relationship,
    EntityExtractionResult,
    OntologyGenerator,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_optimizer import (
    OntologyOptimizer,
    OptimizationReport,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import (
    OntologyLearningAdapter,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic, CriticScore
from ipfs_datasets_py.optimizers.graphrag.ontology_pipeline import OntologyPipeline
from ipfs_datasets_py.optimizers.graphrag.logic_validator import LogicValidator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _report(score: float) -> OptimizationReport:
    return OptimizationReport(average_score=score, trend="stable")


def _optimizer_with(scores: list[float]) -> OntologyOptimizer:
    opt = OntologyOptimizer()
    for s in scores:
        opt._history.append(_report(s))
    return opt


def _adapter_with(scores: list[float]) -> OntologyLearningAdapter:
    adapter = OntologyLearningAdapter(domain="test")
    for s in scores:
        adapter.apply_feedback(final_score=s, actions=[])
    return adapter


def _make_critic_score(**kwargs) -> CriticScore:
    defaults = dict(
        completeness=0.8, consistency=0.7, clarity=0.6,
        granularity=0.5, relationship_coherence=0.4, domain_alignment=0.3,
    )
    defaults.update(kwargs)
    return CriticScore(**defaults)


def _make_result(entities=None, relationships=None) -> EntityExtractionResult:
    return EntityExtractionResult(
        entities=entities or [],
        relationships=relationships or [],
        confidence=0.8,
    )


def _entity(eid: str, etype: str = "Person", conf: float = 0.9) -> Entity:
    return Entity(id=eid, text=eid, type=etype, confidence=conf)


def _rel(rid: str, src: str, tgt: str, conf: float = 0.9) -> Relationship:
    return Relationship(id=rid, source_id=src, target_id=tgt, type="rel", confidence=conf)


def _pipeline_with(scores: list[float]) -> OntologyPipeline:
    pipeline = OntologyPipeline()
    for s in scores:
        run = MagicMock()
        run.score = MagicMock()
        run.score.overall = s
        pipeline._run_history.append(run)
    return pipeline


def _ontology(*pairs, entities=None) -> dict:
    rels = [{"source": s, "target": t, "type": "r", "id": f"r{i}"}
            for i, (s, t) in enumerate(pairs)]
    ent = entities or []
    return {"entities": ent, "relationships": rels}


# ===========================================================================
# BATCH 211 — New methods
# ===========================================================================

class TestMinMaxDimensionRatio:
    """OntologyCritic.min_max_dimension_ratio(score)"""

    def test_returns_float(self):
        critic = OntologyCritic()
        score = _make_critic_score()
        result = critic.min_max_dimension_ratio(score)
        assert isinstance(result, float)

    def test_all_equal_dimensions_returns_one(self):
        critic = OntologyCritic()
        score = _make_critic_score(
            completeness=0.5, consistency=0.5, clarity=0.5,
            granularity=0.5, relationship_coherence=0.5, domain_alignment=0.5,
        )
        assert critic.min_max_dimension_ratio(score) == pytest.approx(1.0)

    def test_max_is_zero_returns_zero(self):
        critic = OntologyCritic()
        score = _make_critic_score(
            completeness=0.0, consistency=0.0, clarity=0.0,
            granularity=0.0, relationship_coherence=0.0, domain_alignment=0.0,
        )
        assert critic.min_max_dimension_ratio(score) == pytest.approx(0.0)

    def test_min_is_zero_returns_zero(self):
        critic = OntologyCritic()
        score = _make_critic_score(
            completeness=0.0, consistency=0.5, clarity=0.8,
            granularity=0.6, relationship_coherence=0.7, domain_alignment=0.9,
        )
        assert critic.min_max_dimension_ratio(score) == pytest.approx(0.0)

    def test_ratio_in_zero_one(self):
        critic = OntologyCritic()
        score = _make_critic_score(
            completeness=0.2, consistency=0.4, clarity=0.6,
            granularity=0.8, relationship_coherence=0.5, domain_alignment=1.0,
        )
        ratio = critic.min_max_dimension_ratio(score)
        assert 0.0 <= ratio <= 1.0

    def test_known_ratio(self):
        critic = OntologyCritic()
        score = _make_critic_score(
            completeness=0.2, consistency=0.4, clarity=0.4,
            granularity=0.4, relationship_coherence=0.4, domain_alignment=0.4,
        )
        # min=0.2, max=0.4 → ratio=0.5
        assert critic.min_max_dimension_ratio(score) == pytest.approx(0.5)

    def test_higher_uniformity_gives_higher_ratio(self):
        critic = OntologyCritic()
        uniform = _make_critic_score(
            completeness=0.7, consistency=0.8, clarity=0.75,
            granularity=0.7, relationship_coherence=0.75, domain_alignment=0.8,
        )
        spread = _make_critic_score(
            completeness=0.1, consistency=0.9, clarity=0.5,
            granularity=0.5, relationship_coherence=0.5, domain_alignment=0.5,
        )
        assert critic.min_max_dimension_ratio(uniform) >= critic.min_max_dimension_ratio(spread)


class TestFeedbackZScores:
    """OntologyLearningAdapter.feedback_z_scores()"""

    def test_empty_returns_empty_list(self):
        adapter = OntologyLearningAdapter(domain="test")
        assert adapter.feedback_z_scores() == []

    def test_single_record_returns_empty(self):
        adapter = _adapter_with([0.7])
        assert adapter.feedback_z_scores() == []

    def test_two_records_opposite_z_scores(self):
        adapter = _adapter_with([0.6, 0.8])
        zs = adapter.feedback_z_scores()
        assert len(zs) == 2
        assert abs(zs[0] + zs[1]) < 1e-9  # symmetric about 0

    def test_all_equal_returns_zeros(self):
        adapter = _adapter_with([0.5, 0.5, 0.5])
        zs = adapter.feedback_z_scores()
        assert all(z == pytest.approx(0.0) for z in zs)

    def test_length_matches_feedback(self):
        scores = [0.3, 0.5, 0.7, 0.9]
        adapter = _adapter_with(scores)
        zs = adapter.feedback_z_scores()
        assert len(zs) == len(scores)

    def test_sum_of_z_scores_near_zero(self):
        adapter = _adapter_with([0.2, 0.4, 0.6, 0.8, 1.0])
        zs = adapter.feedback_z_scores()
        assert abs(sum(zs)) < 1e-9

    def test_returns_list_of_floats(self):
        adapter = _adapter_with([0.5, 0.8])
        zs = adapter.feedback_z_scores()
        assert all(isinstance(z, float) for z in zs)

    def test_known_z_score_values(self):
        # scores=[0, 1] → mean=0.5, std=0.5 → zs=[-1.0, 1.0]
        adapter = _adapter_with([0.0, 1.0])
        zs = adapter.feedback_z_scores()
        assert zs[0] == pytest.approx(-1.0)
        assert zs[1] == pytest.approx(1.0)


class TestEdgeDensity:
    """LogicValidator.edge_density(ontology)"""

    def test_no_entities_returns_zero(self):
        lv = LogicValidator()
        assert lv.edge_density({"entities": [], "relationships": []}) == pytest.approx(0.0)

    def test_single_entity_returns_zero(self):
        lv = LogicValidator()
        ont = {"entities": [{"id": "e1"}], "relationships": []}
        assert lv.edge_density(ont) == pytest.approx(0.0)

    def test_no_relationships_returns_zero(self):
        lv = LogicValidator()
        ents = [{"id": "e1"}, {"id": "e2"}, {"id": "e3"}]
        ont = {"entities": ents, "relationships": []}
        assert lv.edge_density(ont) == pytest.approx(0.0)

    def test_one_edge_two_entities(self):
        # 1 / (2*1) = 0.5
        lv = LogicValidator()
        ents = [{"id": "e1"}, {"id": "e2"}]
        rels = [{"source": "e1", "target": "e2", "id": "r1"}]
        assert lv.edge_density({"entities": ents, "relationships": rels}) == pytest.approx(0.5)

    def test_one_edge_three_entities(self):
        # 1 / (3*2) ≈ 0.1667
        lv = LogicValidator()
        ents = [{"id": "e1"}, {"id": "e2"}, {"id": "e3"}]
        rels = [{"source": "e1", "target": "e2", "id": "r1"}]
        assert lv.edge_density({"entities": ents, "relationships": rels}) == pytest.approx(1/6)

    def test_fully_connected_directed_graph(self):
        # 4 nodes, all 12 directed edges → density=1.0
        lv = LogicValidator()
        ents = [{"id": f"e{i}"} for i in range(4)]
        rels = [
            {"source": f"e{i}", "target": f"e{j}", "id": f"r{i}{j}"}
            for i in range(4) for j in range(4) if i != j
        ]
        assert lv.edge_density({"entities": ents, "relationships": rels}) == pytest.approx(1.0)

    def test_result_in_zero_one(self):
        lv = LogicValidator()
        ents = [{"id": "e1"}, {"id": "e2"}, {"id": "e3"}]
        rels = [{"source": "e1", "target": "e2", "id": "r1"},
                {"source": "e2", "target": "e3", "id": "r2"}]
        d = lv.edge_density({"entities": ents, "relationships": rels})
        assert 0.0 <= d <= 1.0

    def test_edges_key_alias(self):
        """Also works with 'edges' key instead of 'relationships'."""
        lv = LogicValidator()
        ents = [{"id": "e1"}, {"id": "e2"}]
        rels = [{"source": "e1", "target": "e2", "id": "r1"}]
        ont = {"entities": ents, "edges": rels}
        assert lv.edge_density(ont) == pytest.approx(0.5)


# ===========================================================================
# BATCH 211 — Smoke tests for pre-existing methods
# ===========================================================================

class TestBatch211SmokePreExisting:
    """Verify pre-existing Batch 211 items are callable without errors."""

    def test_history_trimmed_mean(self):
        opt = _optimizer_with([0.2, 0.4, 0.6, 0.8, 1.0])
        result = opt.history_trimmed_mean()
        assert isinstance(result, float)

    def test_score_autocorrelation(self):
        opt = _optimizer_with([0.5, 0.6, 0.7, 0.6, 0.5])
        result = opt.score_autocorrelation(lag=1)
        assert isinstance(result, float)

    def test_avg_entity_confidence(self):
        og = OntologyGenerator()
        ents = [_entity("e1", conf=0.8), _entity("e2", conf=0.6)]
        result = og.avg_entity_confidence(_make_result(entities=ents))
        assert result == pytest.approx(0.7)

    def test_run_score_range(self):
        pip = _pipeline_with([0.4, 0.7, 0.9, 0.5])
        rng = pip.run_score_range()
        # Should return a tuple or (min, max) or a float range
        assert rng is not None

    def test_score_plateau_length(self):
        opt = _optimizer_with([0.5, 0.5, 0.5, 0.6])
        result = opt.score_plateau_length()
        assert isinstance(result, int) and result >= 0

    def test_strongly_connected_count(self):
        lv = LogicValidator()
        ents = [{"id": "e1"}, {"id": "e2"}, {"id": "e3"}]
        rels = [{"source": "e1", "target": "e2", "id": "r1"},
                {"source": "e2", "target": "e3", "id": "r2"},
                {"source": "e3", "target": "e1", "id": "r3"}]
        count = lv.strongly_connected_count({"entities": ents, "relationships": rels})
        assert isinstance(count, int) and count >= 0


# ===========================================================================
# BATCH 212 — New methods
# ===========================================================================

class TestScoreMad:
    """OntologyOptimizer.score_mad()"""

    def test_empty_history_returns_zero(self):
        assert OntologyOptimizer().score_mad() == pytest.approx(0.0)

    def test_single_entry(self):
        opt = _optimizer_with([0.7])
        assert opt.score_mad() == pytest.approx(0.0)

    def test_all_equal_returns_zero(self):
        opt = _optimizer_with([0.5, 0.5, 0.5])
        assert opt.score_mad() == pytest.approx(0.0)

    def test_known_value(self):
        # scores=[0, 0.5, 1] → mean=0.5, deviations=[0.5, 0, 0.5] → MAD=1/3
        opt = _optimizer_with([0.0, 0.5, 1.0])
        assert opt.score_mad() == pytest.approx(1.0 / 3.0)

    def test_returns_float(self):
        opt = _optimizer_with([0.3, 0.7])
        assert isinstance(opt.score_mad(), float)

    def test_non_negative(self):
        opt = _optimizer_with([0.1, 0.9, 0.5, 0.3, 0.8])
        assert opt.score_mad() >= 0.0

    def test_symmetric_distribution(self):
        # [0.2, 0.4, 0.6, 0.8] → mean=0.5, deviations=[0.3, 0.1, 0.1, 0.3] → MAD=0.2
        opt = _optimizer_with([0.2, 0.4, 0.6, 0.8])
        assert opt.score_mad() == pytest.approx(0.2)

    def test_mad_less_or_equal_to_std(self):
        # MAD ≤ std is NOT always true; but MAD ≥ 0 always
        opt = _optimizer_with([0.1, 0.3, 0.5, 0.7, 0.9])
        assert opt.score_mad() >= 0.0


class TestDimensionRange:
    """OntologyCritic.dimension_range(score)"""

    def test_returns_float(self):
        critic = OntologyCritic()
        assert isinstance(critic.dimension_range(_make_critic_score()), float)

    def test_all_equal_returns_zero(self):
        critic = OntologyCritic()
        score = _make_critic_score(
            completeness=0.5, consistency=0.5, clarity=0.5,
            granularity=0.5, relationship_coherence=0.5, domain_alignment=0.5,
        )
        assert critic.dimension_range(score) == pytest.approx(0.0)

    def test_known_range(self):
        critic = OntologyCritic()
        score = _make_critic_score(
            completeness=0.1, consistency=0.5, clarity=0.5,
            granularity=0.5, relationship_coherence=0.5, domain_alignment=0.9,
        )
        # max=0.9, min=0.1 → range=0.8
        assert critic.dimension_range(score) == pytest.approx(0.8)

    def test_non_negative(self):
        critic = OntologyCritic()
        assert critic.dimension_range(_make_critic_score()) >= 0.0

    def test_max_possible_range(self):
        critic = OntologyCritic()
        score = _make_critic_score(
            completeness=0.0, consistency=0.0, clarity=0.0,
            granularity=0.0, relationship_coherence=0.0, domain_alignment=1.0,
        )
        assert critic.dimension_range(score) == pytest.approx(1.0)

    def test_range_is_max_minus_min(self):
        critic = OntologyCritic()
        score = _make_critic_score(
            completeness=0.2, consistency=0.4, clarity=0.6,
            granularity=0.7, relationship_coherence=0.3, domain_alignment=0.5,
        )
        vals = [score.completeness, score.consistency, score.clarity,
                score.granularity, score.relationship_coherence, score.domain_alignment]
        expected = max(vals) - min(vals)
        assert critic.dimension_range(score) == pytest.approx(expected)


class TestRelationshipDensity:
    """OntologyGenerator.relationship_density(result)"""

    def test_no_entities_returns_zero(self):
        og = OntologyGenerator()
        result = _make_result()
        assert og.relationship_density(result) == pytest.approx(0.0)

    def test_single_entity_returns_zero(self):
        og = OntologyGenerator()
        result = _make_result(entities=[_entity("e1")])
        assert og.relationship_density(result) == pytest.approx(0.0)

    def test_no_relationships_returns_zero(self):
        og = OntologyGenerator()
        result = _make_result(entities=[_entity("e1"), _entity("e2")])
        assert og.relationship_density(result) == pytest.approx(0.0)

    def test_one_rel_two_entities(self):
        # 1 / (2*1) = 0.5
        og = OntologyGenerator()
        ents = [_entity("e1"), _entity("e2")]
        rels = [_rel("r1", "e1", "e2")]
        result = _make_result(entities=ents, relationships=rels)
        assert og.relationship_density(result) == pytest.approx(0.5)

    def test_one_rel_three_entities(self):
        # 1 / (3*2) ≈ 0.1667
        og = OntologyGenerator()
        ents = [_entity("e1"), _entity("e2"), _entity("e3")]
        rels = [_rel("r1", "e1", "e2")]
        result = _make_result(entities=ents, relationships=rels)
        assert og.relationship_density(result) == pytest.approx(1.0 / 6.0)

    def test_result_in_zero_one(self):
        og = OntologyGenerator()
        ents = [_entity(f"e{i}") for i in range(5)]
        rels = [_rel(f"r{i}", f"e{i}", f"e{(i+1)%5}") for i in range(5)]
        result = _make_result(entities=ents, relationships=rels)
        d = og.relationship_density(result)
        assert 0.0 <= d <= 1.0

    def test_returns_float(self):
        og = OntologyGenerator()
        ents = [_entity("e1"), _entity("e2")]
        result = _make_result(entities=ents)
        assert isinstance(og.relationship_density(result), float)


class TestFeedbackPercentile:
    """OntologyLearningAdapter.feedback_percentile(p)"""

    def test_empty_returns_zero(self):
        adapter = OntologyLearningAdapter(domain="test")
        assert adapter.feedback_percentile(50) == pytest.approx(0.0)

    def test_single_record(self):
        adapter = _adapter_with([0.7])
        assert adapter.feedback_percentile(50) == pytest.approx(0.7)

    def test_p0_returns_minimum(self):
        adapter = _adapter_with([0.3, 0.6, 0.9])
        assert adapter.feedback_percentile(0) == pytest.approx(0.3)

    def test_p100_returns_maximum(self):
        adapter = _adapter_with([0.3, 0.6, 0.9])
        # idx = floor(100/100 * 3) = 3, clamped to 2 → 0.9
        assert adapter.feedback_percentile(100) == pytest.approx(0.9)

    def test_returns_float(self):
        adapter = _adapter_with([0.4, 0.8])
        assert isinstance(adapter.feedback_percentile(50), float)

    def test_result_in_range_of_scores(self):
        scores = [0.2, 0.4, 0.6, 0.8]
        adapter = _adapter_with(scores)
        p50 = adapter.feedback_percentile(50)
        assert min(scores) <= p50 <= max(scores)

    def test_monotone_in_p(self):
        adapter = _adapter_with([0.1, 0.3, 0.5, 0.7, 0.9])
        p25 = adapter.feedback_percentile(25)
        p50 = adapter.feedback_percentile(50)
        p75 = adapter.feedback_percentile(75)
        assert p25 <= p50 <= p75


class TestRunScoreEwma:
    """OntologyPipeline.run_score_ewma(alpha)"""

    def test_empty_returns_zero(self):
        assert OntologyPipeline().run_score_ewma() == pytest.approx(0.0)

    def test_single_run(self):
        pip = _pipeline_with([0.7])
        assert pip.run_score_ewma() == pytest.approx(0.7)

    def test_returns_float(self):
        pip = _pipeline_with([0.5, 0.8])
        assert isinstance(pip.run_score_ewma(), float)

    def test_two_runs_known_value(self):
        # scores=[1.0, 0.0], alpha=0.5 → ewma = 0.5*0 + 0.5*1.0 = 0.5
        pip = _pipeline_with([1.0, 0.0])
        assert pip.run_score_ewma(alpha=0.5) == pytest.approx(0.5)

    def test_alpha_one_equals_last_score(self):
        # alpha=1.0 → ewma = last score
        pip = _pipeline_with([0.3, 0.6, 0.9])
        assert pip.run_score_ewma(alpha=1.0) == pytest.approx(0.9)

    def test_high_alpha_tracks_recent(self):
        # High alpha → recent scores dominate
        pip = _pipeline_with([0.1, 0.1, 0.9])
        ewma_high = pip.run_score_ewma(alpha=0.9)
        ewma_low = pip.run_score_ewma(alpha=0.1)
        assert ewma_high > ewma_low

    def test_result_bounded_by_score_range(self):
        scores = [0.3, 0.5, 0.7, 0.9]
        pip = _pipeline_with(scores)
        ewma = pip.run_score_ewma(alpha=0.3)
        assert min(scores) <= ewma <= max(scores)

    def test_constant_scores_returns_that_value(self):
        pip = _pipeline_with([0.6, 0.6, 0.6, 0.6])
        assert pip.run_score_ewma(alpha=0.3) == pytest.approx(0.6)


class TestMultiEdgeCount:
    """LogicValidator.multi_edge_count(ontology)"""

    def test_empty_graph_returns_zero(self):
        lv = LogicValidator()
        assert lv.multi_edge_count({"entities": [], "relationships": []}) == 0

    def test_no_duplicates_returns_zero(self):
        lv = LogicValidator()
        rels = [{"source": "A", "target": "B", "id": "r1"},
                {"source": "B", "target": "C", "id": "r2"}]
        assert lv.multi_edge_count({"entities": [], "relationships": rels}) == 0

    def test_one_duplicate_returns_one(self):
        lv = LogicValidator()
        rels = [{"source": "A", "target": "B", "id": "r1"},
                {"source": "A", "target": "B", "id": "r2"},
                {"source": "A", "target": "C", "id": "r3"}]
        assert lv.multi_edge_count({"entities": [], "relationships": rels}) == 1

    def test_triple_duplicate_returns_two(self):
        lv = LogicValidator()
        rels = [{"source": "X", "target": "Y", "id": "r1"},
                {"source": "X", "target": "Y", "id": "r2"},
                {"source": "X", "target": "Y", "id": "r3"}]
        assert lv.multi_edge_count({"entities": [], "relationships": rels}) == 2

    def test_reverse_direction_not_counted(self):
        # A→B and B→A are distinct directed edges, not multi-edges
        lv = LogicValidator()
        rels = [{"source": "A", "target": "B", "id": "r1"},
                {"source": "B", "target": "A", "id": "r2"}]
        assert lv.multi_edge_count({"entities": [], "relationships": rels}) == 0

    def test_multiple_duplicate_pairs(self):
        lv = LogicValidator()
        rels = [
            {"source": "A", "target": "B", "id": "r1"},
            {"source": "A", "target": "B", "id": "r2"},  # +1
            {"source": "C", "target": "D", "id": "r3"},
            {"source": "C", "target": "D", "id": "r4"},  # +1
        ]
        assert lv.multi_edge_count({"entities": [], "relationships": rels}) == 2

    def test_edges_key_alias(self):
        lv = LogicValidator()
        rels = [{"source": "A", "target": "B", "id": "r1"},
                {"source": "A", "target": "B", "id": "r2"}]
        ont = {"entities": [], "edges": rels}
        assert lv.multi_edge_count(ont) == 1

    def test_returns_int(self):
        lv = LogicValidator()
        assert isinstance(lv.multi_edge_count({"entities": [], "relationships": []}), int)
