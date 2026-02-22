"""Integration test: full pipeline on multi-paragraph text.

Validates that the full pipeline produces more than 3 entities when given
a realistic multi-paragraph text input.
"""
from __future__ import annotations

import pytest

from ipfs_datasets_py.optimizers.graphrag.ontology_pipeline import OntologyPipeline


def test_full_pipeline_multi_paragraph_text_extracts_entities():
    """
    GIVEN: A multi-paragraph text with multiple named entities
    WHEN: Running the full OntologyPipeline
    THEN: More than 3 entities are extracted
    """
    # GIVEN: multi-paragraph text with several named entities
    text = """
    Alice Johnson is the CEO of Acme Corporation based in San Francisco.
    She signed a contract with Bob Smith, who works at TechStartup Inc.

    The agreement requires Acme Corporation to deliver software components
    by December 31, 2024. Bob Smith will serve as the project manager
    on behalf of TechStartup Inc.

    In case of dispute, the parties agree to arbitration in California.
    Alice Johnson and Bob Smith both approved the final terms.
    """

    # WHEN
    pipeline = OntologyPipeline(domain="general", use_llm=False, max_rounds=1)
    result = pipeline.run(text, data_source="integration_test", refine=False)

    # THEN
    assert result is not None
    entity_count = len(result.entities)
    assert entity_count > 3, (
        f"Expected >3 entities from multi-paragraph text, got {entity_count}. "
        f"Entities: {[e.get('text', e.get('id', '?')) for e in result.entities[:10]]}"
    )


def test_full_pipeline_with_refine_returns_valid_result():
    """
    GIVEN: A multi-paragraph text
    WHEN: Running the full pipeline with refinement
    THEN: Result contains a valid score and ontology
    """
    text = """
    The plaintiff, Jane Doe, alleges that the defendant, XYZ Corp,
    breached the contract signed on January 1, 2024.
    The contract required XYZ Corp to deliver services worth $50,000.
    Jane Doe claims damages of $10,000.
    """

    pipeline = OntologyPipeline(domain="legal", use_llm=False, max_rounds=1)
    result = pipeline.run(text, data_source="integration_test", refine=True)

    assert result is not None
    assert result.ontology is not None
    assert result.score is not None


def test_pipeline_progress_callback_integration():
    """
    GIVEN: A multi-paragraph text and a progress callback
    WHEN: Running the pipeline
    THEN: Callback is invoked with proper stage info
    """
    text = "Alice works at Acme. Bob works at TechCo. Carol is the manager."
    stages = []

    def _cb(info):
        stages.append(info["stage"])

    pipeline = OntologyPipeline(domain="general", use_llm=False, max_rounds=1)
    pipeline.run(text, data_source="test", refine=False, progress_callback=_cb)

    assert "extracting" in stages
    assert "extracted" in stages
