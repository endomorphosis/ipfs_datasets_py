"""Batch-109 feature tests.

Methods under test:
  - OntologyGenerator.validate_result(result)
  - OntologyGenerator.confidence_stats(result)
  - OntologyGenerator.clone_result(result)
  - OntologyGenerator.add_entity(result, entity)
  - OntologyGenerator.remove_entity(result, entity_id)
  - OntologyGenerator.type_diversity(result)
"""
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_gen():
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import OntologyGenerator
    return OntologyGenerator()


def _entity(eid, etype="Person", text="Alice", confidence=0.9):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Entity
    return Entity(id=eid, type=etype, text=text, confidence=confidence)


def _relationship(rid, src, tgt, rtype="knows"):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Relationship
    return Relationship(id=rid, source_id=src, target_id=tgt, type=rtype)


def _result(entities=None, relationships=None):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import EntityExtractionResult
    return EntityExtractionResult(
        entities=entities or [],
        relationships=relationships or [],
        confidence=1.0,
    )


# ---------------------------------------------------------------------------
# OntologyGenerator.validate_result
# ---------------------------------------------------------------------------

class TestValidateResult:
    def test_empty_result_no_issues(self):
        gen = _make_gen()
        r = _result()
        assert gen.validate_result(r) == []

    def test_good_entity_no_issues(self):
        gen = _make_gen()
        r = _result([_entity("e1")])
        assert gen.validate_result(r) == []

    def test_blank_text_flagged(self):
        gen = _make_gen()
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Entity
        bad = Entity(id="e-bad", type="T", text="   ", confidence=0.8)
        r = _result([bad])
        issues = gen.validate_result(r)
        assert len(issues) == 1
        assert "empty text" in issues[0]

    def test_out_of_range_confidence_flagged(self):
        gen = _make_gen()
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Entity
        bad = Entity(id="e-bad", type="T", text="X", confidence=1.5)
        r = _result([bad])
        issues = gen.validate_result(r)
        assert any("confidence" in i for i in issues)

    @pytest.mark.parametrize(
        "source_id,target_id,missing_id",
        [
            ("ghost", "e1", "ghost"),
            ("e1", "missing", "missing"),
        ],
    )
    def test_dangling_endpoint_flagged(self, source_id, target_id, missing_id):
        gen = _make_gen()
        e = _entity("e1")
        rel = _relationship("r1", source_id, target_id)
        r = _result([e], [rel])
        issues = gen.validate_result(r)
        assert any(missing_id in i for i in issues)

    def test_valid_relationship_no_issues(self):
        gen = _make_gen()
        e1 = _entity("e1")
        e2 = _entity("e2")
        rel = _relationship("r1", "e1", "e2")
        r = _result([e1, e2], [rel])
        assert gen.validate_result(r) == []


# ---------------------------------------------------------------------------
# OntologyGenerator.confidence_stats
# ---------------------------------------------------------------------------

class TestConfidenceStats:
    @pytest.mark.parametrize(
        "entities,expected_count,expected_mean",
        [
            ([], 0.0, 0.0),
            ([_entity("e1", confidence=0.8)], 1.0, 0.8),
        ],
    )
    def test_basic_stats_scenarios(self, entities, expected_count, expected_mean):
        gen = _make_gen()
        stats = gen.confidence_stats(_result(entities))
        assert stats["count"] == expected_count
        assert stats["mean"] == pytest.approx(expected_mean)

    def test_multiple_entities(self):
        gen = _make_gen()
        r = _result([
            _entity("e1", confidence=0.4),
            _entity("e2", confidence=0.8),
        ])
        stats = gen.confidence_stats(r)
        assert stats["count"] == 2.0
        assert stats["mean"] == pytest.approx(0.6)
        assert stats["min"] == pytest.approx(0.4)
        assert stats["max"] == pytest.approx(0.8)
        assert stats["std"] > 0.0

    def test_all_keys_present(self):
        gen = _make_gen()
        r = _result([_entity("e1")])
        stats = gen.confidence_stats(r)
        for key in ("count", "mean", "min", "max", "std"):
            assert key in stats


# ---------------------------------------------------------------------------
# OntologyGenerator.clone_result
# ---------------------------------------------------------------------------

class TestCloneResult:
    def test_clone_is_equal(self):
        gen = _make_gen()
        r = _result([_entity("e1")])
        cloned = gen.clone_result(r)
        assert cloned.entities[0].id == r.entities[0].id

    def test_clone_is_independent(self):
        gen = _make_gen()
        e = _entity("e1")
        r = _result([e])
        cloned = gen.clone_result(r)
        # Mutate original
        r.entities.append(_entity("e2"))
        # Clone should be unaffected
        assert len(cloned.entities) == 1

    def test_empty_result_clones_ok(self):
        gen = _make_gen()
        r = _result()
        cloned = gen.clone_result(r)
        assert cloned.entities == []


# ---------------------------------------------------------------------------
# OntologyGenerator.add_entity
# ---------------------------------------------------------------------------

class TestAddEntity:
    def test_adds_entity(self):
        gen = _make_gen()
        r = _result()
        new_e = _entity("e1")
        r2 = gen.add_entity(r, new_e)
        assert len(r2.entities) == 1
        assert r2.entities[0].id == "e1"

    def test_original_unchanged(self):
        gen = _make_gen()
        r = _result()
        gen.add_entity(r, _entity("e1"))
        assert len(r.entities) == 0

    def test_appends_to_existing(self):
        gen = _make_gen()
        r = _result([_entity("e1")])
        r2 = gen.add_entity(r, _entity("e2"))
        assert len(r2.entities) == 2


# ---------------------------------------------------------------------------
# OntologyGenerator.remove_entity
# ---------------------------------------------------------------------------

class TestRemoveEntity:
    def test_removes_entity(self):
        gen = _make_gen()
        r = _result([_entity("e1"), _entity("e2")])
        r2 = gen.remove_entity(r, "e1")
        ids = [e.id for e in r2.entities]
        assert "e1" not in ids
        assert "e2" in ids

    def test_prunes_relationships(self):
        gen = _make_gen()
        e1 = _entity("e1")
        e2 = _entity("e2")
        rel = _relationship("r1", "e1", "e2")
        r = _result([e1, e2], [rel])
        r2 = gen.remove_entity(r, "e1")
        assert len(r2.relationships) == 0

    def test_keeps_unrelated_rels(self):
        gen = _make_gen()
        e1 = _entity("e1")
        e2 = _entity("e2")
        e3 = _entity("e3")
        rel = _relationship("r1", "e2", "e3")
        r = _result([e1, e2, e3], [rel])
        r2 = gen.remove_entity(r, "e1")
        assert len(r2.relationships) == 1

    def test_nonexistent_id_no_change(self):
        gen = _make_gen()
        r = _result([_entity("e1")])
        r2 = gen.remove_entity(r, "ghost")
        assert len(r2.entities) == 1


# ---------------------------------------------------------------------------
# OntologyGenerator.type_diversity
# ---------------------------------------------------------------------------

class TestTypeDiversity:
    @pytest.mark.parametrize(
        "entities,expected",
        [
            ([], 0),
            ([_entity("e1", "Person"), _entity("e2", "Person")], 1),
            ([_entity("e1", "Person"), _entity("e2", "Place"), _entity("e3", "Org")], 3),
            ([_entity("e1", "A"), _entity("e2", "B"), _entity("e3", "A")], 2),
        ],
    )
    def test_type_diversity_scenarios(self, entities, expected):
        gen = _make_gen()
        r = _result(entities)
        assert gen.type_diversity(r) == expected
