from __future__ import annotations

import pytest
from ipfs_datasets_py.optimizers.graphrag.logic_validator import LogicValidator

def test_ontology_to_tdfol_returns_non_empty_string_facts_without_tdfol() -> None:
    from ipfs_datasets_py.optimizers.graphrag.logic_validator import LogicValidator

    validator = LogicValidator(prover_config={"strategy": "AUTO"}, use_cache=False)
    validator._tdfol_available = False

    ontology = {
        "entities": [{"id": "e1", "type": "Person", "text": "Alice"}],
        "relationships": [
            {"id": "r1", "source_id": "e1", "target_id": "e1", "type": "knows"}
        ],
    }

    formulas = validator.ontology_to_tdfol(ontology)

    assert isinstance(formulas, list)
    assert formulas, "expected non-empty formulas for trivial ontology"
    assert all(isinstance(x, str) for x in formulas)
    assert 'entity("e1").' in formulas
    assert 'type("e1", "Person").' in formulas
    assert 'rel("knows", "e1", "e1").' in formulas


class TestEntityToTdfol:
    """Tests for LogicValidator.entity_to_tdfol() single-entity helper."""

    @pytest.fixture
    def validator(self):
        v = LogicValidator(prover_config={"strategy": "AUTO"}, use_cache=False)
        v._tdfol_available = False
        return v

    def test_basic_entity_facts(self, validator):
        entity = {"id": "e1", "type": "Person", "text": "Alice"}
        facts = validator.entity_to_tdfol(entity)
        assert 'entity("e1").' in facts
        assert 'type("e1", "Person").' in facts
        assert 'text("e1", "Alice").' in facts

    def test_no_id_returns_empty(self, validator):
        assert validator.entity_to_tdfol({"type": "Person"}) == []

    def test_non_dict_returns_empty(self, validator):
        assert validator.entity_to_tdfol("not a dict") == []  # type: ignore[arg-type]

    def test_properties_included(self, validator):
        entity = {"id": "e1", "type": "Person", "properties": {"age": 30, "city": "NYC"}}
        facts = validator.entity_to_tdfol(entity)
        assert any('prop("e1", "age"' in f for f in facts)
        assert any('prop("e1", "city"' in f for f in facts)

    def test_result_is_list_of_strings(self, validator):
        entity = {"id": "e2", "type": "Org", "text": "Acme"}
        facts = validator.entity_to_tdfol(entity)
        assert isinstance(facts, list)
        assert all(isinstance(f, str) for f in facts)

    def test_consistent_with_ontology_to_tdfol(self, validator):
        """entity_to_tdfol() must produce a subset of ontology_to_tdfol() facts."""
        entity = {"id": "e1", "type": "Person", "text": "Alice"}
        single_facts = set(validator.entity_to_tdfol(entity))
        full_facts = set(validator.ontology_to_tdfol({"entities": [entity], "relationships": []}))
        assert single_facts.issubset(full_facts)
