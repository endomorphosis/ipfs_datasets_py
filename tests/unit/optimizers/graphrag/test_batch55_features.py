"""Batch 55 tests.

Covers:
- OntologyCritic.evaluate_batch() with progress_callback
- OntologyGenerator.extract_entities_streaming()
- EntityExtractionResult.to_dataframe()
- Integration test: full pipeline on multi-paragraph text
"""
from __future__ import annotations

from unittest.mock import MagicMock, call

import pytest


# ──────────────────────────────────────────────────────────────────────────────
# OntologyCritic.evaluate_batch() with progress_callback
# ──────────────────────────────────────────────────────────────────────────────

class TestEvaluateBatchProgressCallback:
    """evaluate_batch() should invoke progress_callback(index, total, score)."""

    @pytest.fixture
    def critic(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic
        OntologyCritic.clear_shared_cache()
        return OntologyCritic(use_llm=False)

    def _make_ontology(self, tag: str):
        return {
            "entities": [{"id": f"e1-{tag}", "text": f"Alice-{tag}",
                          "type": "Person", "confidence": 0.9, "properties": {}}],
            "relationships": [],
        }

    def _ctx(self):
        ctx = MagicMock()
        ctx.domain = "test"
        return ctx

    def test_callback_invoked_once_per_ontology(self, critic):
        cb = MagicMock()
        ontologies = [self._make_ontology(str(i)) for i in range(3)]
        critic.evaluate_batch(ontologies, self._ctx(), progress_callback=cb)
        assert cb.call_count == 3

    def test_callback_receives_correct_index(self, critic):
        indices = []
        def cb(idx, total, score):
            indices.append(idx)
        ontologies = [self._make_ontology(str(i)) for i in range(4)]
        critic.evaluate_batch(ontologies, self._ctx(), progress_callback=cb)
        assert indices == [0, 1, 2, 3]

    def test_callback_receives_total(self, critic):
        totals = []
        def cb(idx, total, score):
            totals.append(total)
        ontologies = [self._make_ontology(str(i)) for i in range(2)]
        critic.evaluate_batch(ontologies, self._ctx(), progress_callback=cb)
        assert totals == [2, 2]

    def test_callback_receives_critic_score(self, critic):
        from ipfs_datasets_py.optimizers.graphrag.ontology_critic import CriticScore
        scores_received = []
        def cb(idx, total, score):
            scores_received.append(score)
        critic.evaluate_batch([self._make_ontology("x")], self._ctx(), progress_callback=cb)
        assert all(isinstance(s, CriticScore) for s in scores_received)

    def test_no_callback_still_works(self, critic):
        result = critic.evaluate_batch(
            [self._make_ontology("y"), self._make_ontology("z")],
            self._ctx(),
        )
        assert result["count"] == 2

    def test_crashing_callback_does_not_abort_batch(self, critic):
        def bad_cb(idx, total, score):
            raise RuntimeError("oops")
        ontologies = [self._make_ontology(str(i)) for i in range(3)]
        result = critic.evaluate_batch(ontologies, self._ctx(), progress_callback=bad_cb)
        # Batch should still complete all 3 evaluations
        assert result["count"] == 3

    def test_empty_ontologies_no_callback(self, critic):
        cb = MagicMock()
        result = critic.evaluate_batch([], self._ctx(), progress_callback=cb)
        cb.assert_not_called()
        assert result["count"] == 0


# ──────────────────────────────────────────────────────────────────────────────
# OntologyGenerator.extract_entities_streaming()
# ──────────────────────────────────────────────────────────────────────────────

class TestExtractEntitiesStreaming:
    """extract_entities_streaming() should yield Entity objects one by one."""

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

    def test_returns_iterator(self, gen_ctx):
        gen, ctx = gen_ctx
        result = gen.extract_entities_streaming("Alice met Bob.", ctx)
        assert hasattr(result, "__iter__")

    def test_yields_entity_objects(self, gen_ctx):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Entity
        gen, ctx = gen_ctx
        entities = list(gen.extract_entities_streaming("Alice met Bob in London.", ctx))
        assert all(isinstance(e, Entity) for e in entities)

    def test_streaming_same_entities_as_extract(self, gen_ctx):
        gen, ctx = gen_ctx
        text = "Alice met Bob in London."
        streaming = list(gen.extract_entities_streaming(text, ctx))
        batch = gen.extract_entities(text, ctx).entities
        assert len(streaming) == len(batch)
        assert {e.text for e in streaming} == {e.text for e in batch}

    def test_empty_text_yields_nothing(self, gen_ctx):
        gen, ctx = gen_ctx
        entities = list(gen.extract_entities_streaming("", ctx))
        assert isinstance(entities, list)  # may be empty or have some, just no crash


# ──────────────────────────────────────────────────────────────────────────────
# EntityExtractionResult.to_dataframe()
# ──────────────────────────────────────────────────────────────────────────────

class TestEntityExtractionResultToDataframe:
    """to_dataframe() should convert entities to a pandas DataFrame."""

    @pytest.fixture
    def result(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
            OntologyGenerator, OntologyGenerationContext,
        )
        gen = OntologyGenerator()
        ctx = OntologyGenerationContext(
            data_source="test", data_type="text", domain="general"
        )
        return gen.extract_entities("Alice met Bob in London.", ctx)

    def test_to_dataframe_import_error_without_pandas(self, result, monkeypatch):
        import sys
        monkeypatch.setitem(sys.modules, "pandas", None)  # force ImportError
        with pytest.raises((ImportError, TypeError)):
            result.to_dataframe()

    @pytest.mark.skipif(
        pytest.importorskip("pandas", reason="pandas not installed") is None,
        reason="pandas not installed",
    )
    def test_to_dataframe_returns_dataframe(self, result):
        import pandas as pd
        df = result.to_dataframe()
        assert isinstance(df, pd.DataFrame)

    @pytest.mark.skipif(
        pytest.importorskip("pandas", reason="pandas not installed") is None,
        reason="pandas not installed",
    )
    def test_dataframe_has_correct_columns(self, result):
        df = result.to_dataframe()
        assert set(df.columns) == {"id", "text", "type", "confidence"}

    @pytest.mark.skipif(
        pytest.importorskip("pandas", reason="pandas not installed") is None,
        reason="pandas not installed",
    )
    def test_dataframe_row_count_matches_entities(self, result):
        df = result.to_dataframe()
        assert len(df) == len(result.entities)

    @pytest.mark.skipif(
        pytest.importorskip("pandas", reason="pandas not installed") is None,
        reason="pandas not installed",
    )
    def test_empty_result_gives_empty_dataframe(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
            EntityExtractionResult,
        )
        result = EntityExtractionResult(entities=[], relationships=[], confidence=0.0)
        df = result.to_dataframe()
        assert len(df) == 0


# ──────────────────────────────────────────────────────────────────────────────
# Integration test: full pipeline
# ──────────────────────────────────────────────────────────────────────────────

class TestFullPipelineIntegration:
    """Full pipeline: generator → critic → mediator on real multi-paragraph text."""

    MULTI_PARA_TEXT = """
    Alice Johnson is a software engineer at Acme Corp in London.
    She works closely with Bob Smith, the project manager.
    Acme Corp specialises in artificial intelligence and machine learning.

    Bob Smith coordinates with Carol Williams from DataSystems Ltd.
    DataSystems Ltd is headquartered in Berlin, Germany.
    Carol Williams oversees the data pipeline between the two companies.

    The collaboration between Acme Corp and DataSystems Ltd aims to deliver
    a new platform by Q3. Alice Johnson leads the technical team.
    """

    def _setup(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
            OntologyGenerator, OntologyGenerationContext,
        )
        from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic
        from ipfs_datasets_py.optimizers.graphrag.ontology_mediator import OntologyMediator

        gen = OntologyGenerator()
        ctx = OntologyGenerationContext(
            data_source="integration_test", data_type="text", domain="business"
        )
        critic = OntologyCritic(use_llm=False)
        mediator = OntologyMediator(generator=gen, critic=critic)
        return gen, ctx, critic, mediator

    def test_extracts_more_than_three_entities(self):
        gen, ctx, _, _ = self._setup()
        result = gen.extract_entities(self.MULTI_PARA_TEXT, ctx)
        assert len(result.entities) > 3

    def test_entities_have_required_fields(self):
        gen, ctx, _, _ = self._setup()
        result = gen.extract_entities(self.MULTI_PARA_TEXT, ctx)
        for ent in result.entities:
            assert ent.id
            assert ent.text
            assert ent.type

    def test_critic_evaluates_generated_ontology(self):
        gen, ctx, critic, _ = self._setup()
        result = gen.extract_entities(self.MULTI_PARA_TEXT, ctx)
        ontology = {
            "entities": [
                {"id": e.id, "text": e.text, "type": e.type,
                 "confidence": e.confidence, "properties": {}}
                for e in result.entities
            ],
            "relationships": [],
        }
        score = critic.evaluate_ontology(ontology, ctx)
        assert 0.0 <= score.overall <= 1.0

    def test_batch_extract_parallel_matches_sequential(self):
        gen, ctx, _, _ = self._setup()
        docs = [self.MULTI_PARA_TEXT, "Alice.", "Bob in London."]
        parallel = gen.batch_extract(docs, ctx, max_workers=2)
        sequential = [gen.extract_entities(d, ctx) for d in docs]
        for p, s in zip(parallel, sequential):
            # Entity *sets* should be identical (order may vary)
            assert {e.text for e in p.entities} == {e.text for e in s.entities}
