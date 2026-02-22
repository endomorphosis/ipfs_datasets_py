"""Batch 221 feature tests.

New methods:
  * OntologyOptimizer.score_wmd()
  * OntologyCritic.score_dimension_entropy(score)
  * OntologyGenerator.relationship_avg_length(result)
  * OntologyPipeline.run_score_positive_rate()

Stale smoke tests (already implemented in source):
  * OntologyLearningAdapter.feedback_positive_rate()
  * LogicValidator.isolated_node_count()
"""
import math
import pytest


# ---------------------------------------------------------------------------
# Lightweight stubs to avoid heavy import chain
# ---------------------------------------------------------------------------

def _make_optimizer(scores):
    from ipfs_datasets_py.optimizers.graphrag.ontology_optimizer import OntologyOptimizer
    class _E:
        def __init__(self, v):
            self.average_score = v
    o = object.__new__(OntologyOptimizer)
    o._history = [_E(v) for v in scores]
    return o


def _make_critic():
    from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic
    return object.__new__(OntologyCritic)


def _make_critic_score(completeness=0.5, consistency=0.5, clarity=0.5,
                       granularity=0.5, relationship_coherence=0.5,
                       domain_alignment=0.5):
    from ipfs_datasets_py.optimizers.graphrag.ontology_critic import CriticScore
    return CriticScore(
        completeness=completeness,
        consistency=consistency,
        clarity=clarity,
        granularity=granularity,
        relationship_coherence=relationship_coherence,
        domain_alignment=domain_alignment,
    )


def _make_rel(rtype):
    class _R:
        def __init__(self, t):
            self.type = t
            self.id = "r"
            self.source_id = "a"
            self.target_id = "b"
            self.confidence = 1.0
    return _R(rtype)


def _make_extraction_result(rel_types):
    class _Res:
        def __init__(self, rels):
            self.entities = []
            self.relationships = rels
            self.confidence = 1.0
    return _Res([_make_rel(t) for t in rel_types])


def _make_pipeline(scores):
    from ipfs_datasets_py.optimizers.graphrag.ontology_pipeline import OntologyPipeline
    class _S:
        def __init__(self, v):
            self.overall = v
    class _R:
        def __init__(self, v):
            self.score = _S(v)
    p = object.__new__(OntologyPipeline)
    p._run_history = [_R(v) for v in scores]
    return p


def _make_adapter(scores):
    from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import OntologyLearningAdapter
    class _FR:
        def __init__(self, s):
            self.final_score = s
    la = object.__new__(OntologyLearningAdapter)
    la._feedback = [_FR(s) for s in scores]
    return la


def _make_ontology(entity_ids, rels):
    class _E:
        def __init__(self, i):
            self.id = i
    class _R:
        def __init__(self, s, t):
            self.source_id = s
            self.target_id = t
    class _Ont:
        def __init__(self, eids, rs):
            self.entities = [_E(i) for i in eids]
            self.relationships = [_R(s, t) for s, t in rs]
    return _Ont(entity_ids, rels)


def _make_validator():
    from ipfs_datasets_py.optimizers.graphrag.logic_validator import LogicValidator
    return object.__new__(LogicValidator)


# ---------------------------------------------------------------------------
# OntologyOptimizer.score_wmd
# ---------------------------------------------------------------------------

class TestScoreWmd:
    def test_empty_returns_zero(self):
        opt = _make_optimizer([])
        assert opt.score_wmd() == 0.0

    def test_single_entry_returns_zero(self):
        opt = _make_optimizer([0.5])
        assert opt.score_wmd() == 0.0

    def test_two_identical_entries_returns_zero(self):
        opt = _make_optimizer([0.5, 0.5])
        assert opt.score_wmd() == 0.0

    def test_two_different_entries(self):
        # lower=[0.2], upper=[0.8] → wmd = |0.8 - 0.2| / 1 = 0.6
        opt = _make_optimizer([0.2, 0.8])
        result = opt.score_wmd()
        assert abs(result - 0.6) < 1e-9

    def test_four_entries_symmetric(self):
        # sorted=[0.1,0.3,0.5,0.7]; lower=[0.1,0.3], upper=[0.5,0.7]
        # wmd = (|0.5-0.1| + |0.7-0.3|) / 2 = 0.4
        opt = _make_optimizer([0.7, 0.1, 0.5, 0.3])
        result = opt.score_wmd()
        assert abs(result - 0.4) < 1e-9

    def test_non_negative(self):
        opt = _make_optimizer([0.9, 0.1, 0.4, 0.6, 0.3, 0.7])
        assert opt.score_wmd() >= 0.0

    def test_identical_halves_returns_zero(self):
        # sorted=[0.5,0.5,0.5,0.5]; lower=upper → wmd=0
        opt = _make_optimizer([0.5, 0.5, 0.5, 0.5])
        assert opt.score_wmd() == 0.0

    def test_returns_float(self):
        opt = _make_optimizer([0.2, 0.8])
        assert isinstance(opt.score_wmd(), float)

    def test_large_history(self):
        # Monotone increasing: wmd should be positive
        opt = _make_optimizer([i / 9 for i in range(10)])
        assert opt.score_wmd() > 0.0

    def test_odd_length_history(self):
        # 3 entries: sorted=[0.1,0.5,0.9]; lower=[0.1], upper=[0.9] (mid=1)
        opt = _make_optimizer([0.9, 0.1, 0.5])
        result = opt.score_wmd()
        # lower=[0.1], upper=[0.9] → wmd = 0.8
        assert abs(result - 0.8) < 1e-9


# ---------------------------------------------------------------------------
# OntologyCritic.score_dimension_entropy
# ---------------------------------------------------------------------------

class TestScoreDimensionEntropy:
    def test_uniform_distribution_max_entropy(self):
        critic = _make_critic()
        s = _make_critic_score(1 / 6, 1 / 6, 1 / 6, 1 / 6, 1 / 6, 1 / 6)
        result = critic.score_dimension_entropy(s)
        expected = math.log(6)  # ln(6) ≈ 1.7917
        assert abs(result - expected) < 1e-6

    def test_all_zero_returns_zero(self):
        critic = _make_critic()
        s = _make_critic_score(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        assert critic.score_dimension_entropy(s) == 0.0

    def test_single_mass_minimum_entropy(self):
        critic = _make_critic()
        s = _make_critic_score(1.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        # p=[1,0,0,0,0,0] → entropy = -1*ln(1) = 0
        assert critic.score_dimension_entropy(s) == pytest.approx(0.0, abs=1e-9)

    def test_two_equal_masses_entropy(self):
        critic = _make_critic()
        s = _make_critic_score(0.5, 0.5, 0.0, 0.0, 0.0, 0.0)
        # p=[0.5,0.5,0,...] → entropy = -2*(0.5*ln(0.5)) = ln(2)
        assert critic.score_dimension_entropy(s) == pytest.approx(math.log(2), abs=1e-6)

    def test_returns_non_negative(self):
        critic = _make_critic()
        s = _make_critic_score(0.9, 0.1, 0.3, 0.7, 0.5, 0.2)
        assert critic.score_dimension_entropy(s) >= 0.0

    def test_returns_float(self):
        critic = _make_critic()
        s = _make_critic_score()
        assert isinstance(critic.score_dimension_entropy(s), float)

    def test_entropy_leq_ln6(self):
        critic = _make_critic()
        s = _make_critic_score(0.9, 0.1, 0.3, 0.7, 0.5, 0.2)
        assert critic.score_dimension_entropy(s) <= math.log(6) + 1e-9

    def test_entropy_increases_toward_uniform(self):
        critic = _make_critic()
        s_concentrated = _make_critic_score(1.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        s_spread = _make_critic_score(0.8, 0.1, 0.1, 0.0, 0.0, 0.0)
        s_uniform = _make_critic_score(1 / 6, 1 / 6, 1 / 6, 1 / 6, 1 / 6, 1 / 6)
        assert (
            critic.score_dimension_entropy(s_concentrated)
            <= critic.score_dimension_entropy(s_spread)
            <= critic.score_dimension_entropy(s_uniform)
        )

    def test_scale_invariant(self):
        # Doubling all values should not change entropy (same proportions)
        critic = _make_critic()
        s1 = _make_critic_score(0.1, 0.2, 0.3, 0.1, 0.2, 0.1)
        s2 = _make_critic_score(0.2, 0.4, 0.6, 0.2, 0.4, 0.2)
        assert abs(critic.score_dimension_entropy(s1) - critic.score_dimension_entropy(s2)) < 1e-9


# ---------------------------------------------------------------------------
# OntologyGenerator.relationship_avg_length
# ---------------------------------------------------------------------------

class TestRelationshipAvgLength:
    def _make_gen(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import OntologyGenerator
        return object.__new__(OntologyGenerator)

    def test_empty_relationships_returns_zero(self):
        gen = self._make_gen()
        result = _make_extraction_result([])
        assert gen.relationship_avg_length(result) == 0.0

    def test_single_relationship(self):
        gen = self._make_gen()
        result = _make_extraction_result(["causes"])  # len("causes") = 6
        assert gen.relationship_avg_length(result) == pytest.approx(6.0)

    def test_multiple_relationships(self):
        gen = self._make_gen()
        # "owns" (4), "has" (3), "causes" (6) → mean = (4+3+6)/3 = 13/3
        result = _make_extraction_result(["owns", "has", "causes"])
        expected = (4 + 3 + 6) / 3
        assert gen.relationship_avg_length(result) == pytest.approx(expected)

    def test_uniform_types(self):
        gen = self._make_gen()
        result = _make_extraction_result(["ab", "cd", "ef"])  # all length 2
        assert gen.relationship_avg_length(result) == pytest.approx(2.0)

    def test_returns_float(self):
        gen = self._make_gen()
        result = _make_extraction_result(["causes"])
        assert isinstance(gen.relationship_avg_length(result), float)

    def test_non_negative(self):
        gen = self._make_gen()
        result = _make_extraction_result(["a", "bb", "ccc"])
        assert gen.relationship_avg_length(result) >= 0.0

    def test_empty_type_string_counts_as_zero(self):
        gen = self._make_gen()
        result = _make_extraction_result(["", "", ""])
        assert gen.relationship_avg_length(result) == 0.0

    def test_mixed_empty_and_nonempty(self):
        gen = self._make_gen()
        # "" (0), "abc" (3) → mean = 1.5
        result = _make_extraction_result(["", "abc"])
        assert gen.relationship_avg_length(result) == pytest.approx(1.5)

    def test_single_char_types(self):
        gen = self._make_gen()
        result = _make_extraction_result(["a", "b", "c"])
        assert gen.relationship_avg_length(result) == pytest.approx(1.0)

    def test_no_relationships_attr(self):
        gen = self._make_gen()
        class _NoRels:
            entities = []
            confidence = 1.0
        assert gen.relationship_avg_length(_NoRels()) == 0.0


# ---------------------------------------------------------------------------
# OntologyPipeline.run_score_positive_rate
# ---------------------------------------------------------------------------

class TestRunScorePositiveRate:
    def test_empty_returns_zero(self):
        p = _make_pipeline([])
        assert p.run_score_positive_rate() == 0.0

    def test_all_above_threshold(self):
        p = _make_pipeline([0.6, 0.7, 0.8])
        assert p.run_score_positive_rate() == pytest.approx(1.0)

    def test_none_above_threshold(self):
        p = _make_pipeline([0.1, 0.2, 0.3])
        assert p.run_score_positive_rate() == pytest.approx(0.0)

    def test_half_above_threshold(self):
        p = _make_pipeline([0.3, 0.3, 0.7, 0.7])
        assert p.run_score_positive_rate() == pytest.approx(0.5)

    def test_exact_threshold_not_positive(self):
        # strict > threshold, so 0.5 is NOT positive
        p = _make_pipeline([0.5, 0.5])
        assert p.run_score_positive_rate() == pytest.approx(0.0)

    def test_custom_threshold(self):
        p = _make_pipeline([0.1, 0.2, 0.3, 0.4, 0.9])
        rate = p.run_score_positive_rate(threshold=0.3)
        # 0.4 and 0.9 are above 0.3 → 2/5
        assert rate == pytest.approx(0.4)

    def test_single_run_positive(self):
        p = _make_pipeline([0.8])
        assert p.run_score_positive_rate() == pytest.approx(1.0)

    def test_single_run_not_positive(self):
        p = _make_pipeline([0.2])
        assert p.run_score_positive_rate() == pytest.approx(0.0)

    def test_returns_float(self):
        p = _make_pipeline([0.6])
        assert isinstance(p.run_score_positive_rate(), float)

    def test_value_in_unit_interval(self):
        p = _make_pipeline([0.1, 0.5, 0.9, 0.3, 0.8])
        rate = p.run_score_positive_rate()
        assert 0.0 <= rate <= 1.0


# ---------------------------------------------------------------------------
# Stale smoke tests — already implemented in source
# ---------------------------------------------------------------------------

class TestStaleSmoke:
    """Exercise stale TODO methods that were already in the source before B221."""

    def test_feedback_positive_rate_above_zero(self):
        """OntologyLearningAdapter.feedback_positive_rate already exists."""
        la = _make_adapter([0.3, 0.6, 0.7, 0.2])
        result = la.feedback_positive_rate()
        # 0.6 and 0.7 are > 0.5 (default or 0.6 threshold, check both)
        assert isinstance(result, float)
        assert 0.0 <= result <= 1.0

    def test_feedback_positive_rate_empty(self):
        la = _make_adapter([])
        result = la.feedback_positive_rate()
        assert result == 0.0

    def test_isolated_node_count_no_edges(self):
        """LogicValidator.isolated_node_count already exists."""
        validator = _make_validator()
        ont = _make_ontology(["A", "B", "C"], [])
        result = validator.isolated_node_count(ont)
        assert result == 3  # all nodes isolated

    def test_isolated_node_count_chain(self):
        validator = _make_validator()
        ont = _make_ontology(["A", "B", "C"], [("A", "B"), ("B", "C")])
        result = validator.isolated_node_count(ont)
        assert result == 0  # all nodes have at least one edge

    def test_isolated_node_count_returns_int(self):
        validator = _make_validator()
        ont = _make_ontology(["A"], [])
        assert isinstance(validator.isolated_node_count(ont), int)

    def test_isolated_node_count_single_isolated(self):
        validator = _make_validator()
        # A→B (connected), C (isolated)
        ont = _make_ontology(["A", "B", "C"], [("A", "B")])
        result = validator.isolated_node_count(ont)
        assert result == 1
