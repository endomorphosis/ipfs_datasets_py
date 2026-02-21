"""Regression tests for BaseHarness integration in OntologyPipelineHarness."""

from __future__ import annotations

from ipfs_datasets_py.optimizers.common.base_critic import CriticResult
from ipfs_datasets_py.optimizers.common.base_harness import BaseHarness, HarnessConfig
from ipfs_datasets_py.optimizers.graphrag.ontology_harness import OntologyPipelineHarness


class _StubGenerator:
    def generate_ontology(self, data, context):
        return {"entities": [{"id": "e1", "name": str(data)}], "relationships": [], "metadata": {"domain": "test"}}


class _StubCritic:
    def evaluate(self, artifact, context):
        _ = artifact
        _ = context
        return CriticResult(score=0.9, feedback=["looks good"], dimensions={"quality": 0.9})


class _StubMediator:
    def refine_ontology(self, artifact, feedback):
        _ = feedback
        return artifact


def test_ontology_pipeline_harness_is_base_harness_subclass():
    h = OntologyPipelineHarness(
        generator=_StubGenerator(),
        critic=_StubCritic(),
        mediator=_StubMediator(),
        config=HarnessConfig(max_rounds=2, target_score=0.8),
    )
    assert isinstance(h, BaseHarness)


def test_ontology_pipeline_harness_run_reports_best_ontology():
    h = OntologyPipelineHarness(
        generator=_StubGenerator(),
        critic=_StubCritic(),
        mediator=_StubMediator(),
        config=HarnessConfig(max_rounds=2, target_score=0.8),
    )

    report = h.run_and_report("doc", {"domain": "test"})

    assert report["best_score"] >= 0.8
    assert report["best_ontology"]["entities"][0]["id"] == "e1"
