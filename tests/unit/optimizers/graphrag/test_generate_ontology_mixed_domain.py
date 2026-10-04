"""Regression tests for mixed-domain ontology generation."""

from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    OntologyGenerator,
    OntologyGenerationContext,
)


def test_generate_ontology_mixed_domain_input():
    """Ensure mixed-domain text generates a non-empty ontology."""
    generator = OntologyGenerator()
    context = OntologyGenerationContext(
        data_source="mixed-domain-test",
        data_type="text",
        domain="general",
    )

    text = (
        "Acme Corp signed a contract with Beta LLC on January 5, 2026. "
        "Dr. Chen reviewed the patient record under HIPAA guidance. "
        "The backend API endpoint /v1/claims returns JSON for the web client."
    )

    ontology = generator.generate_ontology(text, context)

    assert isinstance(ontology, dict)
    assert "entities" in ontology
    assert "relationships" in ontology
    assert len(ontology["entities"]) > 0
