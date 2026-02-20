"""Unit tests for OntologyMediator.refine_ontology() action dispatch.

Tests each refinement action is triggered by the correct keywords and
produces the expected delta in the ontology.
"""

from __future__ import annotations

import pytest
from ipfs_datasets_py.optimizers.graphrag.ontology_mediator import OntologyMediator
from ipfs_datasets_py.optimizers.graphrag.ontology_critic import CriticScore


@pytest.fixture
def mediator():
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import OntologyGenerator
    from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic
    return OntologyMediator(generator=OntologyGenerator(), critic=OntologyCritic())


def _score(**recs) -> CriticScore:
    recommendations = recs.get("recommendations", [])
    return CriticScore(
        completeness=0.5,
        consistency=0.5,
        clarity=0.5,
        granularity=0.5,
        domain_alignment=0.5,
        recommendations=recommendations,
    )


def _ontology(n_ents: int = 4, n_rels: int = 0, with_props: bool = False):
    ents = [
        {
            "id": f"e{i}",
            "type": "Concept",
            "text": f"entity{i}",
            **({"properties": {"k": "v"}} if with_props else {}),
        }
        for i in range(n_ents)
    ]
    rels = [
        {
            "id": f"r{i}",
            "source_id": f"e{i}",
            "target_id": f"e{(i + 1) % n_ents}",
            "type": "related_to",
        }
        for i in range(n_rels)
    ]
    return {"entities": ents, "relationships": rels, "metadata": {}}


class TestRefineOntologyActionDispatch:
    def test_add_missing_properties_action(self, mediator):
        ontology = _ontology(3)
        score = _score(recommendations=["Improve clarity and add property definitions"])
        refined = mediator.refine_ontology(ontology, score, context=None)
        assert "add_missing_properties" in refined["metadata"]["refinement_actions"]
        for ent in refined["entities"]:
            assert ent.get("properties"), "All entities should have properties after action"

    def test_normalize_names_action(self, mediator):
        ontology = {
            "entities": [
                {"id": "e0", "type": "some_concept", "text": "foo"},
                {"id": "e1", "type": "other_concept", "text": "bar"},
            ],
            "relationships": [
                {"id": "r0", "source_id": "e0", "target_id": "e1", "type": "related_to_it"}
            ],
            "metadata": {},
        }
        score = _score(recommendations=["Normalize naming conventions"])
        refined = mediator.refine_ontology(ontology, score, context=None)
        assert "normalize_names" in refined["metadata"]["refinement_actions"]
        # Types should be PascalCase after normalization
        for ent in refined["entities"]:
            t = ent["type"]
            assert t[0].isupper() or len(t) == 0, f"Expected PascalCase, got: {t}"

    def test_prune_orphans_action(self, mediator):
        # e0 and e1 are linked; e2 and e3 are orphans
        ontology = {
            "entities": [
                {"id": "e0", "type": "X", "text": "a"},
                {"id": "e1", "type": "X", "text": "b"},
                {"id": "e2", "type": "X", "text": "c"},
                {"id": "e3", "type": "X", "text": "d"},
            ],
            "relationships": [
                {"id": "r0", "source_id": "e0", "target_id": "e1", "type": "related_to"}
            ],
            "metadata": {},
        }
        score = _score(recommendations=["Prune orphan entities with no coverage"])
        refined = mediator.refine_ontology(ontology, score, context=None)
        assert "prune_orphans" in refined["metadata"]["refinement_actions"]
        ids = [e["id"] for e in refined["entities"]]
        assert "e0" in ids
        assert "e1" in ids
        assert "e2" not in ids
        assert "e3" not in ids

    def test_merge_duplicates_action(self, mediator):
        ontology = {
            "entities": [
                {"id": "e0", "type": "Person", "text": "Alice"},
                {"id": "e1", "type": "Person", "text": "alice"},  # same after lower
            ],
            "relationships": [],
            "metadata": {},
        }
        score = _score(recommendations=["Remove duplicate entities for consistency"])
        refined = mediator.refine_ontology(ontology, score, context=None)
        assert "merge_duplicates" in refined["metadata"]["refinement_actions"]
        assert len(refined["entities"]) == 1

    def test_add_missing_relationships_action(self, mediator):
        # All 4 entities are orphans (no relationships)
        ontology = _ontology(4, n_rels=0)
        score = _score(recommendations=["Add missing relationships for unlinked entities"])
        refined = mediator.refine_ontology(ontology, score, context=None)
        assert "add_missing_relationships" in refined["metadata"]["refinement_actions"]
        assert len(refined["relationships"]) >= 1

    def test_add_missing_relationships_only_links_orphans(self, mediator):
        # e0–e1 already linked; e2 and e3 are orphans
        ontology = {
            "entities": [
                {"id": "e0", "type": "X", "text": "a"},
                {"id": "e1", "type": "X", "text": "b"},
                {"id": "e2", "type": "X", "text": "c"},
                {"id": "e3", "type": "X", "text": "d"},
            ],
            "relationships": [
                {"id": "r0", "source_id": "e0", "target_id": "e1", "type": "related_to"}
            ],
            "metadata": {},
        }
        score = _score(recommendations=["Add missing relationships for unlinked entities"])
        refined = mediator.refine_ontology(ontology, score, context=None)
        new_rels = [r for r in refined["relationships"] if r.get("type") == "co_occurrence"]
        # e2 and e3 should be linked
        assert len(new_rels) >= 1
        linked = {(r["source_id"], r["target_id"]) for r in new_rels}
        assert ("e2", "e3") in linked or ("e3", "e2") in linked

    def test_no_matching_recommendation_no_action(self, mediator):
        ontology = _ontology(2)
        score = _score(recommendations=["Everything looks great"])
        refined = mediator.refine_ontology(ontology, score, context=None)
        assert refined["metadata"]["refinement_actions"] == []

    def test_original_ontology_not_mutated(self, mediator):
        import copy
        ontology = _ontology(3)
        original = copy.deepcopy(ontology)
        score = _score(recommendations=["Improve clarity and add property definitions"])
        mediator.refine_ontology(ontology, score, context=None)
        assert ontology == original

    def test_refinement_actions_recorded_in_metadata(self, mediator):
        ontology = _ontology(3)
        score = _score(recommendations=["Improve clarity"])
        refined = mediator.refine_ontology(ontology, score, context=None)
        assert "refinement_actions" in refined["metadata"]

    def test_empty_recommendations_no_action(self, mediator):
        ontology = _ontology(3)
        score = _score(recommendations=[])
        refined = mediator.refine_ontology(ontology, score, context=None)
        assert refined["metadata"]["refinement_actions"] == []
