from __future__ import annotations


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
