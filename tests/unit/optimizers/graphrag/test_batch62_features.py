"""Batch 62: OntologyPipeline.run_async, OntologyMediator.get_recommendation_stats,
OntologyOptimizer.export_score_chart, OntologyGenerator.extract_with_coref,
OntologyHarness integration test.
"""
from __future__ import annotations

import asyncio
import pytest

from ipfs_datasets_py.optimizers.graphrag.ontology_pipeline import OntologyPipeline, PipelineResult
from ipfs_datasets_py.optimizers.graphrag.ontology_mediator import OntologyMediator
from ipfs_datasets_py.optimizers.graphrag.ontology_critic import CriticScore, OntologyCritic
from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    OntologyGenerator,
    OntologyGenerationContext,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_optimizer import (
    OntologyOptimizer,
    OptimizationReport,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ctx():
    return OntologyGenerationContext(data_source="test", data_type="text", domain="test")


def _score(**kwargs):
    defaults = dict(
        completeness=0.7, consistency=0.7, clarity=0.6, granularity=0.5,
        domain_alignment=0.4, recommendations=["Add more entity properties"],
    )
    defaults.update(kwargs)
    return CriticScore(**defaults)


def _make_mediator():
    gen = OntologyGenerator()
    critic = OntologyCritic(use_llm=False)
    return OntologyMediator(generator=gen, critic=critic, max_rounds=3)


def _make_report(score, ontology=None):
    return OptimizationReport(
        average_score=score, trend="stable", improvement_rate=0.0,
        recommendations=[], best_ontology=ontology, worst_ontology=None,
    )


def _ontology(n: int = 2):
    return {
        "entities": [
            {"id": f"e{i}", "type": "Person", "text": f"Name{i}", "properties": {}}
            for i in range(n)
        ],
        "relationships": [],
        "metadata": {},
        "domain": "test",
    }


# ---------------------------------------------------------------------------
# OntologyPipeline.run_async
# ---------------------------------------------------------------------------

class TestRunAsync:
    def test_returns_coroutine(self):
        pipeline = OntologyPipeline(domain="test")
        coro = pipeline.run_async("Alice works at ACME.")
        assert asyncio.iscoroutine(coro)
        # clean up
        coro.close()

    @pytest.mark.asyncio
    async def test_returns_pipeline_result(self):
        pipeline = OntologyPipeline(domain="test")
        result = await pipeline.run_async("Alice works at ACME.", data_source="t")
        assert isinstance(result, PipelineResult)

    @pytest.mark.asyncio
    async def test_result_has_ontology(self):
        pipeline = OntologyPipeline(domain="test")
        result = await pipeline.run_async("Bob must pay Alice by Friday.")
        assert "entities" in result.ontology

    @pytest.mark.asyncio
    async def test_refine_false_works(self):
        pipeline = OntologyPipeline(domain="test")
        result = await pipeline.run_async("text", refine=False)
        assert result is not None

    @pytest.mark.asyncio
    async def test_async_result_matches_sync(self):
        text = "Alice and Bob are partners."
        pipeline = OntologyPipeline(domain="test")
        sync_result = pipeline.run(text, data_source="s1")
        async_result = await pipeline.clone().run_async(text, data_source="s1")
        # Same entity count (same algorithm, same text)
        assert len(async_result.ontology.get("entities", [])) == len(
            sync_result.ontology.get("entities", [])
        )


# ---------------------------------------------------------------------------
# OntologyMediator.get_recommendation_stats
# ---------------------------------------------------------------------------

class TestGetRecommendationStats:
    def test_returns_empty_before_refine(self):
        mediator = _make_mediator()
        assert mediator.get_recommendation_stats() == {}

    def test_single_recommendation_tracked(self):
        mediator = _make_mediator()
        score = _score(recommendations=["Add entity properties"])
        mediator.refine_ontology(_ontology(), score, _ctx())
        stats = mediator.get_recommendation_stats()
        assert "Add entity properties" in stats
        assert stats["Add entity properties"] == 1

    def test_repeated_recommendation_counted(self):
        mediator = _make_mediator()
        score = _score(recommendations=["Fix naming conventions"])
        mediator.refine_ontology(_ontology(), score, _ctx())
        mediator.refine_ontology(_ontology(), score, _ctx())
        stats = mediator.get_recommendation_stats()
        assert stats["Fix naming conventions"] == 2

    def test_multiple_unique_recommendations(self):
        mediator = _make_mediator()
        score = _score(recommendations=["Add properties", "Fix naming"])
        mediator.refine_ontology(_ontology(), score, _ctx())
        stats = mediator.get_recommendation_stats()
        assert "Add properties" in stats
        assert "Fix naming" in stats

    def test_returns_copy(self):
        mediator = _make_mediator()
        score = _score(recommendations=["R1"])
        mediator.refine_ontology(_ontology(), score, _ctx())
        stats = mediator.get_recommendation_stats()
        stats["R1"] = 999
        # Internal state not mutated
        assert mediator.get_recommendation_stats()["R1"] == 1

    def test_empty_recommendations_no_change(self):
        mediator = _make_mediator()
        score = _score(recommendations=[])
        mediator.refine_ontology(_ontology(), score, _ctx())
        assert mediator.get_recommendation_stats() == {}


# ---------------------------------------------------------------------------
# OntologyOptimizer.export_score_chart
# ---------------------------------------------------------------------------

class TestExportScoreChart:
    def test_raises_on_empty_history(self):
        opt = OntologyOptimizer()
        with pytest.raises(ValueError):
            opt.export_score_chart()

    def test_returns_base64_string(self):
        opt = OntologyOptimizer()
        opt._history.append(_make_report(0.7))
        opt._history.append(_make_report(0.8))
        result = opt.export_score_chart()
        assert isinstance(result, str)
        # Base64 PNG starts with iVBOR
        assert len(result) > 100

    def test_single_point_history(self):
        opt = OntologyOptimizer()
        opt._history.append(_make_report(0.5))
        result = opt.export_score_chart()
        assert result is not None

    def test_filepath_returns_none(self, tmp_path):
        opt = OntologyOptimizer()
        opt._history.append(_make_report(0.6))
        opt._history.append(_make_report(0.75))
        path = str(tmp_path / "chart.png")
        result = opt.export_score_chart(filepath=path)
        assert result is None
        import os
        assert os.path.exists(path)

    def test_output_is_valid_base64(self):
        import base64
        opt = OntologyOptimizer()
        opt._history.append(_make_report(0.5))
        raw = opt.export_score_chart()
        # Should not raise
        decoded = base64.b64decode(raw)
        assert decoded[:4] == b'\x89PNG'


# ---------------------------------------------------------------------------
# OntologyGenerator.extract_with_coref
# ---------------------------------------------------------------------------

class TestExtractWithCoref:
    @pytest.fixture
    def gen(self):
        return OntologyGenerator()

    def test_returns_extraction_result(self, gen):
        result = gen.extract_with_coref("Alice works here. She is a lawyer.", _ctx())
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import EntityExtractionResult
        assert isinstance(result, EntityExtractionResult)

    def test_coref_resolved_metadata(self, gen):
        result = gen.extract_with_coref("Alice works here. She is a lawyer.", _ctx())
        assert result.metadata.get("coref_resolved") is True

    def test_pronoun_text_does_not_cause_crash(self, gen):
        result = gen.extract_with_coref("He said she told them it was fine.", _ctx())
        assert result is not None

    def test_empty_text(self, gen):
        result = gen.extract_with_coref("", _ctx())
        assert result is not None

    def test_entities_present_in_coref_text(self, gen):
        text = "Alice is a lawyer. She works at ACME Corp."
        result = gen.extract_with_coref(text, _ctx())
        assert isinstance(result.entities, list)


# ---------------------------------------------------------------------------
# OntologyHarness integration test (no mocks)
# ---------------------------------------------------------------------------

class TestOntologyHarnessIntegration:
    def test_pipeline_full_run_no_mocks(self):
        """Integration: pipeline produces a valid result with no mocks."""
        pipeline = OntologyPipeline(domain="legal")
        text = (
            "Alice Johnson is a senior attorney at Johnson & Partners LLP. "
            "She represents Bob Smith, the defendant, in a breach of contract case. "
            "The plaintiff, ACME Corporation, claims Bob violated a non-disclosure agreement."
        )
        result = pipeline.run(text, data_source="integration_test")
        assert isinstance(result, PipelineResult)
        assert result.score is not None
        assert 0.0 <= result.score.overall <= 1.0

    def test_pipeline_run_batch_integration(self):
        """Integration: run_batch processes multiple docs."""
        pipeline = OntologyPipeline(domain="test")
        docs = [
            "Alice works at ACME.",
            "Bob must pay Carol by Friday.",
        ]
        results = pipeline.run_batch(docs, data_source="batch_test")
        assert len(results) == 2
        for r in results:
            assert isinstance(r, PipelineResult)
