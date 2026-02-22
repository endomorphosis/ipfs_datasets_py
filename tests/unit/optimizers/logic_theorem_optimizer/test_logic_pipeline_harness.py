"""Tests for the BaseHarness-native LogicPipelineHarness."""

from __future__ import annotations

from dataclasses import dataclass

from ipfs_datasets_py.optimizers.common.base_critic import CriticResult
from ipfs_datasets_py.optimizers.common.base_harness import BaseHarness, HarnessConfig
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.logic_harness import LogicPipelineHarness


@dataclass
class _DummyContext:
    domain: str = "general"
    data: object | None = None


class _StubExtractor:
    def extract(self, context):
        return {"statements": ["P -> Q"], "context_domain": getattr(context, "domain", "general")}


class _StubCritic:
    def evaluate_as_base(self, artifact, context):
        _ = artifact
        _ = context
        return CriticResult(score=0.85, feedback=["ok"], dimensions={"soundness": 0.9})


def test_logic_pipeline_harness_is_base_harness_subclass():
    harness = LogicPipelineHarness(
        extractor=_StubExtractor(),
        critic=_StubCritic(),
        config=HarnessConfig(max_rounds=2, target_score=0.8),
    )

    assert isinstance(harness, BaseHarness)


def test_logic_pipeline_harness_run_and_report_with_context_normalization():
    harness = LogicPipelineHarness(
        extractor=_StubExtractor(),
        critic=_StubCritic(),
        config=HarnessConfig(max_rounds=2, target_score=0.8),
    )

    report = harness.run_and_report("sample", _DummyContext(domain="legal"))

    assert report["best_score"] >= 0.8
    assert report["extraction"]["context_domain"] == "legal"
