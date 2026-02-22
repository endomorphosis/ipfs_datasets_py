"""Batch 56 tests.

Covers:
- graphrag/typing.py type aliases
- OntologyPipeline facade (run, run_batch)
- OntologyHarness.run_concurrent()
- batch_extract() merge_provenance source tagging
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest


# ──────────────────────────────────────────────────────────────────────────────
# typing.py type aliases
# ──────────────────────────────────────────────────────────────────────────────

class TestTypingAliases:
    """Type aliases in typing.py should be importable and behave as expected."""

    def test_import_all_aliases(self):
        from ipfs_datasets_py.optimizers.graphrag.typing import (
            OntologyDict, EntityDict, RelationshipDict, MetadataDict,
            EntityList, RelationshipList, FixSuggestion, ActionName,
        )

    def test_ontology_dict_is_dict_type(self):
        from ipfs_datasets_py.optimizers.graphrag.typing import OntologyDict
        # Type alias — at runtime it's just dict; the alias exists for annotations
        sample: OntologyDict = {"entities": [], "relationships": []}
        assert isinstance(sample, dict)

    def test_entity_dict_is_dict_type(self):
        from ipfs_datasets_py.optimizers.graphrag.typing import EntityDict
        sample: EntityDict = {"id": "e1", "text": "Alice", "type": "Person"}
        assert isinstance(sample, dict)

    def test_all_exported(self):
        import ipfs_datasets_py.optimizers.graphrag.typing as t
        for name in t.__all__:
            assert hasattr(t, name)


# ──────────────────────────────────────────────────────────────────────────────
# OntologyPipeline facade
# ──────────────────────────────────────────────────────────────────────────────

class TestOntologyPipeline:
    """OntologyPipeline should run the full workflow in one call."""

    @pytest.fixture
    def pipeline(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_pipeline import OntologyPipeline
        return OntologyPipeline(domain="general")

    def test_run_returns_pipeline_result(self, pipeline):
        from ipfs_datasets_py.optimizers.graphrag.ontology_pipeline import PipelineResult
        result = pipeline.run("Alice met Bob in London.")
        assert isinstance(result, PipelineResult)

    def test_run_result_has_score(self, pipeline):
        from ipfs_datasets_py.optimizers.graphrag.ontology_critic import CriticScore
        result = pipeline.run("Alice works at Acme Corp.")
        assert isinstance(result.score, CriticScore)

    def test_run_result_has_entities(self, pipeline):
        result = pipeline.run("Alice met Bob.")
        assert isinstance(result.entities, list)

    def test_run_result_has_ontology(self, pipeline):
        result = pipeline.run("Alice met Bob.")
        assert "entities" in result.ontology
        assert "relationships" in result.ontology

    def test_run_result_metadata_has_domain(self, pipeline):
        result = pipeline.run("Alice.")
        assert result.metadata.get("domain") == "general"

    def test_run_no_refine_still_works(self, pipeline):
        result = pipeline.run("Alice.", refine=False)
        assert result.score is not None
        assert result.actions_applied == []

    def test_run_batch_returns_list(self, pipeline):
        docs = ["Alice.", "Bob.", "Acme Corp."]
        results = pipeline.run_batch(docs)
        assert len(results) == 3

    def test_run_batch_each_has_score(self, pipeline):
        from ipfs_datasets_py.optimizers.graphrag.ontology_critic import CriticScore
        results = pipeline.run_batch(["Alice.", "Bob."])
        for r in results:
            assert isinstance(r.score, CriticScore)

    def test_run_empty_text_does_not_crash(self, pipeline):
        result = pipeline.run("")
        assert result is not None


# ──────────────────────────────────────────────────────────────────────────────
# OntologyHarness.run_concurrent()
# ──────────────────────────────────────────────────────────────────────────────

class TestHarnessRunConcurrent:
    """run_concurrent() should return results for each doc in order."""

    @pytest.fixture
    def harness_ctx(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_harness import OntologyPipelineHarness
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
            OntologyGenerator, OntologyGenerationContext,
        )
        from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic
        from ipfs_datasets_py.optimizers.graphrag.ontology_mediator import OntologyMediator
        gen = OntologyGenerator()
        ctx = OntologyGenerationContext(
            data_source="test", data_type="text", domain="general"
        )
        critic = OntologyCritic(use_llm=False)
        mediator = OntologyMediator(generator=gen, critic=critic)
        harness = OntologyPipelineHarness(generator=gen, critic=critic, mediator=mediator)
        return harness, ctx

    def test_returns_list_of_correct_length(self, harness_ctx):
        harness, ctx = harness_ctx
        docs = ["Alice.", "Bob.", "Acme Corp."]
        results = harness.run_concurrent(docs, ctx, max_workers=2)
        assert len(results) == 3

    def test_all_results_are_dicts(self, harness_ctx):
        harness, ctx = harness_ctx
        docs = ["Alice.", "Bob."]
        results = harness.run_concurrent(docs, ctx)
        assert all(isinstance(r, dict) for r in results)

    def test_empty_docs_returns_empty(self, harness_ctx):
        harness, ctx = harness_ctx
        results = harness.run_concurrent([], ctx)
        assert results == []

    def test_single_doc_returns_single_result(self, harness_ctx):
        harness, ctx = harness_ctx
        results = harness.run_concurrent(["Alice met Bob."], ctx)
        assert len(results) == 1


# ──────────────────────────────────────────────────────────────────────────────
# batch_extract() merge_provenance source tagging
# ──────────────────────────────────────────────────────────────────────────────

class TestBatchExtractProvenance:
    """batch_extract should tag entities with source_doc_index."""

    @pytest.fixture
    def gen_ctx(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
            OntologyGenerator, OntologyGenerationContext,
        )
        gen = OntologyGenerator()
        ctx = OntologyGenerationContext(
            data_source="test", data_type="text", domain="general"
        )
        return gen, ctx

    def test_entities_have_source_doc_index(self, gen_ctx):
        gen, ctx = gen_ctx
        docs = ["Alice met Bob.", "Carol runs Acme."]
        results = gen.batch_extract(docs, ctx)
        for idx, r in enumerate(results):
            for ent in r.entities:
                if hasattr(ent, '__dict__'):
                    assert ent.__dict__.get('source_doc_index') == idx

    def test_correct_index_per_doc(self, gen_ctx):
        gen, ctx = gen_ctx
        docs = ["Alice.", "Bob.", "Carol."]
        results = gen.batch_extract(docs, ctx, max_workers=1)
        for idx, r in enumerate(results):
            for ent in r.entities:
                if hasattr(ent, '__dict__'):
                    assert ent.__dict__['source_doc_index'] == idx
