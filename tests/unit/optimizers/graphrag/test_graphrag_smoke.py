from __future__ import annotations


def test_graphrag_modules_import() -> None:
    # Import-only smoke test: should not raise.
    from ipfs_datasets_py.optimizers.graphrag import (
        cli_wrapper as _cli_wrapper,
        logic_validator as _logic_validator,
        ontology_generator as _ontology_generator,
        ontology_critic as _ontology_critic,
        ontology_optimizer as _ontology_optimizer,
        query_optimizer as _query_optimizer,
    )

    assert _cli_wrapper is not None
    assert _logic_validator is not None
    assert _ontology_generator is not None
    assert _ontology_critic is not None
    assert _ontology_optimizer is not None
    assert _query_optimizer is not None


def test_logic_validator_basic_consistency_check_without_tdfol() -> None:
    from ipfs_datasets_py.optimizers.graphrag.logic_validator import LogicValidator

    validator = LogicValidator(prover_config={"strategy": "AUTO"}, use_cache=False)
    # Force deterministic behavior for this smoke test:
    # when TDFOL is available, the current proving path is a placeholder and
    # may report "consistent" even for structurally invalid ontologies.
    validator._tdfol_available = False

    ontology = {
        "entities": [{"id": "e1", "type": "Thing", "text": "Alice"}],
        "relationships": [
            {"id": "r1", "source_id": "e1", "target_id": "missing", "type": "rel"}
        ],
    }

    result = validator.check_consistency(ontology)

    assert hasattr(result, "is_consistent")
    assert result.prover_used == "basic_structural"
    assert result.is_consistent is False
    assert any("non-existent target entity" in c for c in result.contradictions)


def test_ontology_generator_generate_ontology_minimal_rule_based() -> None:
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
        DataType,
        ExtractionStrategy,
        OntologyGenerationContext,
        OntologyGenerator,
    )

    generator = OntologyGenerator(use_ipfs_accelerate=False)

    context = OntologyGenerationContext(
        data_source="unit-test",
        data_type=DataType.TEXT,
        domain="general",
        extraction_strategy=ExtractionStrategy.RULE_BASED,
    )

    ontology = generator.generate_ontology("Alice pays Bob", context)

    assert isinstance(ontology, dict)
    assert set(ontology.keys()) >= {"entities", "relationships", "metadata", "domain", "version"}
    assert ontology["domain"] == "general"
    assert isinstance(ontology["entities"], list)
    assert isinstance(ontology["relationships"], list)
