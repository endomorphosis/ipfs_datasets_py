"""Batch-114 feature tests.

Methods under test:
  - OntologyOptimizer.rolling_best(window)
  - OntologyOptimizer.plateau_count(tol)
  - OntologyGenerator.entity_confidence_map(result)
  - EntityExtractionResult.top_confidence_entity()
  - EntityExtractionResult.entities_with_properties()
  - OntologyCritic.dimension_rankings(score)
  - OntologyCritic.weakest_scores(scores, n)
  - LogicValidator.orphan_entities(ontology)
  - LogicValidator.hub_entities(ontology, min_degree)
"""
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_optimizer():
    from ipfs_datasets_py.optimizers.graphrag.ontology_optimizer import OntologyOptimizer
    return OntologyOptimizer()


class _FakeEntry:
    def __init__(self, score):
        self.average_score = score
        self.trend = "flat"
        self.best_ontology = {}
        self.worst_ontology = {}
        self.metadata = {}


def _opt_with_history(scores):
    opt = _make_optimizer()
    for s in scores:
        opt._history.append(_FakeEntry(s))
    return opt


def _entity(eid, etype="Person", text="Alice", confidence=0.9, properties=None):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Entity
    return Entity(id=eid, type=etype, text=text, confidence=confidence,
                  properties=properties or {})


def _result(entities=None):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import EntityExtractionResult
    return EntityExtractionResult(entities=entities or [], relationships=[], confidence=1.0)


def _make_gen():
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import OntologyGenerator
    return OntologyGenerator()


def _make_critic():
    from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic
    return OntologyCritic(use_llm=False)


def _make_score(v):
    from ipfs_datasets_py.optimizers.graphrag.ontology_critic import CriticScore
    return CriticScore(completeness=v, consistency=v, clarity=v,
                       granularity=v, relationship_coherence=v, domain_alignment=v)


def _make_mixed_score(c, cn, cl, g, da):
    from ipfs_datasets_py.optimizers.graphrag.ontology_critic import CriticScore
    return CriticScore(completeness=c, consistency=cn, clarity=cl,
                       granularity=g, relationship_coherence=da, domain_alignment=da)


def _make_validator():
    from ipfs_datasets_py.optimizers.graphrag.logic_validator import LogicValidator, ProverConfig
    return LogicValidator(ProverConfig())


# ---------------------------------------------------------------------------
# OntologyOptimizer.rolling_best
# ---------------------------------------------------------------------------

class TestRollingBest:
    def test_empty_returns_none(self):
        opt = _make_optimizer()
        assert opt.rolling_best() is None

    def test_returns_best_in_window(self):
        opt = _opt_with_history([0.3, 0.8, 0.5, 0.4])
        best = opt.rolling_best(window=3)
        # last 3: [0.8, 0.5, 0.4]
        assert best.average_score == pytest.approx(0.8)

    def test_window_one_returns_last(self):
        opt = _opt_with_history([0.3, 0.7, 0.6])
        best = opt.rolling_best(window=1)
        assert best.average_score == pytest.approx(0.6)

    def test_window_larger_than_history(self):
        opt = _opt_with_history([0.5, 0.9])
        best = opt.rolling_best(window=10)
        assert best.average_score == pytest.approx(0.9)

    def test_raises_window_zero(self):
        opt = _make_optimizer()
        with pytest.raises(ValueError):
            opt.rolling_best(window=0)


# ---------------------------------------------------------------------------
# OntologyOptimizer.plateau_count
# ---------------------------------------------------------------------------

class TestPlateauCount:
    def test_empty_returns_zero(self):
        opt = _make_optimizer()
        assert opt.plateau_count() == 0

    def test_single_entry_returns_zero(self):
        opt = _opt_with_history([0.5])
        assert opt.plateau_count() == 0

    def test_all_same_all_plateau(self):
        opt = _opt_with_history([0.5, 0.5, 0.5, 0.5])
        assert opt.plateau_count() == 3

    def test_no_plateaus(self):
        opt = _opt_with_history([0.1, 0.5, 0.9])
        assert opt.plateau_count(tol=0.001) == 0

    def test_some_plateaus(self):
        opt = _opt_with_history([0.5, 0.501, 0.9])
        # pair (0.5, 0.501) has diff 0.001 which is within default tol=0.005
        assert opt.plateau_count() >= 1


# ---------------------------------------------------------------------------
# OntologyGenerator.entity_confidence_map
# ---------------------------------------------------------------------------

class TestEntityConfidenceMap:
    def test_empty_result(self):
        gen = _make_gen()
        r = _result()
        assert gen.entity_confidence_map(r) == {}

    def test_basic(self):
        gen = _make_gen()
        r = _result([
            _entity("e1", confidence=0.7),
            _entity("e2", confidence=0.9),
        ])
        m = gen.entity_confidence_map(r)
        assert m["e1"] == pytest.approx(0.7)
        assert m["e2"] == pytest.approx(0.9)

    def test_returns_dict(self):
        gen = _make_gen()
        r = _result([_entity("e1")])
        assert isinstance(gen.entity_confidence_map(r), dict)


# ---------------------------------------------------------------------------
# EntityExtractionResult.top_confidence_entity
# ---------------------------------------------------------------------------

class TestTopConfidenceEntity:
    def test_empty_returns_none(self):
        r = _result()
        assert r.top_confidence_entity() is None

    def test_single_entity(self):
        r = _result([_entity("e1", confidence=0.7)])
        top = r.top_confidence_entity()
        assert top.id == "e1"

    def test_multiple_entities(self):
        r = _result([
            _entity("e1", confidence=0.5),
            _entity("e2", confidence=0.9),
            _entity("e3", confidence=0.7),
        ])
        top = r.top_confidence_entity()
        assert top.id == "e2"


# ---------------------------------------------------------------------------
# EntityExtractionResult.entities_with_properties
# ---------------------------------------------------------------------------

class TestEntitiesWithProperties:
    def test_empty_result(self):
        r = _result()
        assert r.entities_with_properties() == []

    def test_no_properties(self):
        r = _result([_entity("e1", properties={})])
        assert r.entities_with_properties() == []

    def test_with_properties(self):
        r = _result([
            _entity("e1", properties={"role": "CEO"}),
            _entity("e2", properties={}),
        ])
        result = r.entities_with_properties()
        assert len(result) == 1
        assert result[0].id == "e1"


# ---------------------------------------------------------------------------
# OntologyCritic.dimension_rankings
# ---------------------------------------------------------------------------

class TestDimensionRankings:
    def test_returns_all_dims(self):
        c = _make_critic()
        s = _make_score(0.7)
        rankings = c.dimension_rankings(s)
        assert len(rankings) == 6
        dims = {"completeness", "consistency", "clarity", "granularity", "relationship_coherence", "domain_alignment"}
        assert set(rankings) == dims

    def test_best_first(self):
        c = _make_critic()
        s = _make_mixed_score(c=0.9, cn=0.7, cl=0.5, g=0.3, da=0.1)
        rankings = c.dimension_rankings(s)
        assert rankings[0] == "completeness"
        assert rankings[-1] == "domain_alignment"

    def test_uniform_any_order(self):
        c = _make_critic()
        s = _make_score(0.6)
        rankings = c.dimension_rankings(s)
        # All equal, any order is acceptable
        assert len(rankings) == 6


# ---------------------------------------------------------------------------
# OntologyCritic.weakest_scores
# ---------------------------------------------------------------------------

class TestWeakestScores:
    def test_empty(self):
        c = _make_critic()
        assert c.weakest_scores([], n=3) == []

    def test_returns_bottom_n(self):
        c = _make_critic()
        scores = [_make_score(v) for v in [0.9, 0.3, 0.7, 0.1, 0.5]]
        weak = c.weakest_scores(scores, n=2)
        assert len(weak) == 2
        # Weakest first
        assert weak[0].overall < weak[1].overall

    def test_n_larger_than_list(self):
        c = _make_critic()
        scores = [_make_score(0.5)]
        assert len(c.weakest_scores(scores, n=5)) == 1


# ---------------------------------------------------------------------------
# LogicValidator.orphan_entities
# ---------------------------------------------------------------------------

class TestOrphanEntities:
    def test_all_connected(self):
        v = _make_validator()
        ont = {
            "entities": [{"id": "e1"}, {"id": "e2"}],
            "relationships": [{"source_id": "e1", "target_id": "e2"}],
        }
        assert v.orphan_entities(ont) == []

    def test_one_orphan(self):
        v = _make_validator()
        ont = {
            "entities": [{"id": "e1"}, {"id": "e2"}, {"id": "orphan"}],
            "relationships": [{"source_id": "e1", "target_id": "e2"}],
        }
        assert v.orphan_entities(ont) == ["orphan"]

    def test_no_relationships(self):
        v = _make_validator()
        ont = {"entities": [{"id": "e1"}, {"id": "e2"}], "relationships": []}
        orphans = v.orphan_entities(ont)
        assert set(orphans) == {"e1", "e2"}

    def test_empty_ontology(self):
        v = _make_validator()
        assert v.orphan_entities({}) == []


# ---------------------------------------------------------------------------
# LogicValidator.hub_entities
# ---------------------------------------------------------------------------

class TestHubEntities:
    def test_empty(self):
        v = _make_validator()
        assert v.hub_entities({}) == []

    def test_single_connection(self):
        v = _make_validator()
        ont = {
            "entities": [{"id": "e1"}, {"id": "e2"}],
            "relationships": [{"source_id": "e1", "target_id": "e2"}],
        }
        # e1 has degree 1, e2 has degree 1; min_degree=2 → no hubs
        assert v.hub_entities(ont, min_degree=2) == []

    def test_hub_detected(self):
        v = _make_validator()
        ont = {
            "entities": [{"id": "hub"}, {"id": "e1"}, {"id": "e2"}],
            "relationships": [
                {"source_id": "hub", "target_id": "e1"},
                {"source_id": "hub", "target_id": "e2"},
            ],
        }
        hubs = v.hub_entities(ont, min_degree=2)
        assert "hub" in hubs

    def test_min_degree_one_returns_all_connected(self):
        v = _make_validator()
        ont = {
            "entities": [{"id": "e1"}, {"id": "e2"}],
            "relationships": [{"source_id": "e1", "target_id": "e2"}],
        }
        hubs = v.hub_entities(ont, min_degree=1)
        assert set(hubs) == {"e1", "e2"}
