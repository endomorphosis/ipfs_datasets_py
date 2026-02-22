"""Batch 57 tests.

Covers:
- OntologyCritic._evaluate_provenance()
- OntologyCritic.evaluate_ontology() metadata includes provenance_score
- OntologyGenerator.merge_provenance_report()
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest


# ──────────────────────────────────────────────────────────────────────────────
# OntologyCritic._evaluate_provenance()
# ──────────────────────────────────────────────────────────────────────────────

class TestEvaluateProvenance:
    """_evaluate_provenance() should score entity source-span coverage."""

    @pytest.fixture
    def critic(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic
        OntologyCritic.clear_shared_cache()
        return OntologyCritic(use_llm=False)

    def test_empty_ontology_returns_neutral(self, critic):
        score = critic._evaluate_provenance({"entities": []})
        assert score == 0.5

    def test_all_entities_have_source_span(self, critic):
        ontology = {
            "entities": [
                {"id": "e1", "text": "Alice", "type": "Person",
                 "source_span": "0:5", "confidence": 0.9},
                {"id": "e2", "text": "Bob", "type": "Person",
                 "source_span": "10:13", "confidence": 0.8},
            ]
        }
        score = critic._evaluate_provenance(ontology)
        assert score == 1.0

    def test_no_entities_have_provenance(self, critic):
        ontology = {
            "entities": [
                {"id": "e1", "text": "Alice", "type": "Person", "confidence": 0.9},
                {"id": "e2", "text": "Bob", "type": "Person", "confidence": 0.8},
            ]
        }
        score = critic._evaluate_provenance(ontology)
        assert score == 0.0

    def test_half_entities_annotated(self, critic):
        ontology = {
            "entities": [
                {"id": "e1", "text": "Alice", "source_span": "0:5", "confidence": 0.9},
                {"id": "e2", "text": "Bob", "confidence": 0.8},  # no span
            ]
        }
        score = critic._evaluate_provenance(ontology)
        assert abs(score - 0.5) < 1e-9

    def test_source_doc_index_counts_as_provenance(self, critic):
        ontology = {
            "entities": [
                {"id": "e1", "text": "Alice", "source_doc_index": 0, "confidence": 0.9},
            ]
        }
        score = critic._evaluate_provenance(ontology)
        assert score == 1.0

    def test_span_in_properties_counts(self, critic):
        ontology = {
            "entities": [
                {"id": "e1", "text": "Alice", "confidence": 0.9,
                 "properties": {"span": "2:7"}},
            ]
        }
        score = critic._evaluate_provenance(ontology)
        assert score == 1.0

    def test_returns_float_in_01(self, critic):
        ontology = {
            "entities": [
                {"id": f"e{i}", "text": f"E{i}", "confidence": 0.5}
                for i in range(5)
            ]
        }
        score = critic._evaluate_provenance(ontology)
        assert 0.0 <= score <= 1.0


class TestEvaluateOntologyProvenanceMetadata:
    """evaluate_ontology() metadata should include provenance_score."""

    @pytest.fixture(autouse=True)
    def clear_cache(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic
        OntologyCritic.clear_shared_cache()

    def test_metadata_has_provenance_score(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic
        critic = OntologyCritic(use_llm=False)
        ctx = MagicMock()
        ctx.domain = "general"
        ontology = {
            "entities": [{"id": "e1", "text": "Alice", "type": "Person",
                          "confidence": 0.9, "source_span": "0:5", "properties": {}}],
            "relationships": [],
        }
        score = critic.evaluate_ontology(ontology, ctx)
        assert "provenance_score" in score.metadata

    def test_provenance_score_is_float(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic
        critic = OntologyCritic(use_llm=False)
        ctx = MagicMock()
        ctx.domain = "general"
        ontology = {
            "entities": [{"id": "e1", "text": "Alice", "type": "Person",
                          "confidence": 0.9, "properties": {}}],
            "relationships": [],
        }
        score = critic.evaluate_ontology(ontology, ctx)
        assert isinstance(score.metadata["provenance_score"], float)


# ──────────────────────────────────────────────────────────────────────────────
# OntologyGenerator.merge_provenance_report()
# ──────────────────────────────────────────────────────────────────────────────

class TestMergeProvenanceReport:
    """merge_provenance_report() should map entities to their source documents."""

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

    def test_returns_list(self, gen_ctx):
        gen, ctx = gen_ctx
        docs = ["Alice.", "Bob."]
        results = gen.batch_extract(docs, ctx)
        report = gen.merge_provenance_report(results)
        assert isinstance(report, list)

    def test_report_has_required_keys(self, gen_ctx):
        gen, ctx = gen_ctx
        docs = ["Alice met Bob.", "Carol."]
        results = gen.batch_extract(docs, ctx)
        report = gen.merge_provenance_report(results)
        for entry in report:
            assert "entity_id" in entry
            assert "entity_text" in entry
            assert "entity_type" in entry
            assert "source_doc" in entry
            assert "source_doc_index" in entry

    def test_source_doc_index_correct(self, gen_ctx):
        gen, ctx = gen_ctx
        docs = ["Alice.", "Bob."]
        results = gen.batch_extract(docs, ctx)
        report = gen.merge_provenance_report(results)
        for entry in report:
            assert entry["source_doc_index"] in (0, 1)

    def test_custom_doc_labels(self, gen_ctx):
        gen, ctx = gen_ctx
        docs = ["Alice.", "Bob."]
        results = gen.batch_extract(docs, ctx)
        report = gen.merge_provenance_report(results, doc_labels=["doc_A", "doc_B"])
        labels = {e["source_doc"] for e in report}
        # Labels should be from our custom list
        assert labels <= {"doc_A", "doc_B"}

    def test_empty_results_returns_empty(self, gen_ctx):
        gen, _ = gen_ctx
        report = gen.merge_provenance_report([])
        assert report == []

    def test_total_entries_equals_total_entities(self, gen_ctx):
        gen, ctx = gen_ctx
        docs = ["Alice met Bob.", "Carol runs Acme."]
        results = gen.batch_extract(docs, ctx)
        total_entities = sum(len(r.entities) for r in results)
        report = gen.merge_provenance_report(results)
        assert len(report) == total_entities
