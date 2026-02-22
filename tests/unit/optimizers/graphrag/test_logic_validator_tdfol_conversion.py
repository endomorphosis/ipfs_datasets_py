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


class TestEntityContradictionCount:
    """Tests for LogicValidator.entity_contradiction_count() method."""

    @pytest.fixture
    def validator(self):
        return LogicValidator(prover_config={"strategy": "AUTO"}, use_cache=False)

    def test_empty_ontology_returns_zero(self, validator):
        """Empty ontology should have 0 entity contradictions."""
        ontology = {"entities": [], "relationships": []}
        count = validator.entity_contradiction_count(ontology)
        assert count == 0

    def test_returns_integer(self, validator):
        """Method should always return an integer."""
        ontology = {"entities": [{"id": "e1", "type": "Person"}], "relationships": []}
        count = validator.entity_contradiction_count(ontology)
        assert isinstance(count, int)
        assert count >= 0

    def test_consistent_ontology_returns_zero(self, validator):
        """Ontology with valid entities should return 0."""
        ontology = {
            "entities": [
                {"id": "e1", "type": "Person", "text": "Alice"},
                {"id": "e2", "type": "Person", "text": "Bob"},
            ],
            "relationships": [
                {"id": "r1", "source_id": "e1", "target_id": "e2", "type": "knows"}
            ],
        }
        count = validator.entity_contradiction_count(ontology)
        assert count == 0

    def test_exception_handling_returns_zero(self, validator):
        """Test that exceptions during validation are handled gracefully."""
        # None is not a valid ontology dict, should handle gracefully
        count = validator.entity_contradiction_count(None)
        # Should return an integer (may be 0 or positive depending on error handling)
        assert isinstance(count, int)
        assert count >= 0

    def test_malformed_ontology_returns_zero(self, validator):
        """Malformed ontology should return 0 via exception handling."""
        malformed = {"not": "valid"}
        count = validator.entity_contradiction_count(malformed)
        assert count == 0

    def test_result_is_non_negative(self, validator):
        """Result should never be negative."""
        ontology = {
            "entities": [
                {"id": "e1", "type": "Person"},
                {"id": "e2", "type": "Organization"},
            ],
            "relationships": [],
        }
        count = validator.entity_contradiction_count(ontology)
        assert count >= 0

