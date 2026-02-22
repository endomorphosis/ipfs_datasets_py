"""End-to-end integration tests for OntologyPipelineHarness.

Exercises the full Generator → Critic → Mediator refinement loop using
real (non-mocked) components so that wiring bugs are caught early.

All tests use only small fixture texts and rule-based extraction so they
run without any external services or GPU.
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

FIXTURE_TEXTS = {
    "simple": "Alice knows Bob. Bob works at Acme Corporation.",
    "legal": (
        "The Lessor hereby grants the Lessee the right to occupy the premises "
        "located at 123 Main Street.  The Tenant shall pay monthly rent of $1,500."
    ),
    "medical": (
        "Dr. Smith diagnosed the Patient with hypertension and prescribed "
        "Lisinopril.  The Hospital admitted the Patient on Monday."
    ),
}


def _make_context(domain: str = "general"):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
        OntologyGenerationContext,
        ExtractionStrategy,
        DataType,
    )
    return OntologyGenerationContext(
        domain=domain,
        data_source="inline",
        extraction_strategy=ExtractionStrategy.RULE_BASED,
        data_type=DataType.TEXT,
    )


def _make_harness():
    from ipfs_datasets_py.optimizers.graphrag import (
        OntologyPipelineHarness,
        OntologyGenerator,
        OntologyCritic,
        OntologyMediator,
    )
    g = OntologyGenerator()
    c = OntologyCritic(use_llm=False)
    m = OntologyMediator(generator=g, critic=c)
    return OntologyPipelineHarness(generator=g, critic=c, mediator=m), g, c, m


# ---------------------------------------------------------------------------
# OntologyPipelineHarness.run() tests
# ---------------------------------------------------------------------------

class TestOntologyPipelineHarnessRun:
    """Tests for run() method — returns a BaseSession."""

    def test_run_returns_base_session(self):
        from ipfs_datasets_py.optimizers.common import BaseSession
        harness, *_ = _make_harness()
        ctx = _make_context()
        session = harness.run(data=FIXTURE_TEXTS["simple"], context=ctx)
        assert isinstance(session, BaseSession)

    def test_run_has_rounds(self):
        harness, *_ = _make_harness()
        ctx = _make_context()
        session = harness.run(data=FIXTURE_TEXTS["simple"], context=ctx)
        assert len(session.rounds) >= 1

    def test_run_best_score_in_range(self):
        harness, *_ = _make_harness()
        ctx = _make_context()
        session = harness.run(data=FIXTURE_TEXTS["simple"], context=ctx)
        assert 0.0 <= session.best_score <= 1.0

    def test_run_trend_is_valid(self):
        harness, *_ = _make_harness()
        ctx = _make_context()
        session = harness.run(data=FIXTURE_TEXTS["simple"], context=ctx)
        assert session.trend in ("improving", "stable", "declining", "unknown")

    def test_run_legal_domain(self):
        harness, *_ = _make_harness()
        ctx = _make_context(domain="legal")
        session = harness.run(data=FIXTURE_TEXTS["legal"], context=ctx)
        assert len(session.rounds) >= 1
        assert session.best_score >= 0.0

    def test_run_medical_domain(self):
        harness, *_ = _make_harness()
        ctx = _make_context(domain="medical")
        session = harness.run(data=FIXTURE_TEXTS["medical"], context=ctx)
        assert len(session.rounds) >= 1


# ---------------------------------------------------------------------------
# OntologyPipelineHarness.run_and_report() tests
# ---------------------------------------------------------------------------

class TestOntologyPipelineHarnessReport:
    """Tests for run_and_report() — returns a structured dict."""

    def test_report_has_expected_keys(self):
        harness, *_ = _make_harness()
        ctx = _make_context()
        report = harness.run_and_report(data=FIXTURE_TEXTS["simple"], context=ctx)
        for key in ("best_score", "rounds", "converged", "best_ontology", "session"):
            assert key in report, f"Missing key: {key}"

    def test_report_best_score_in_range(self):
        harness, *_ = _make_harness()
        ctx = _make_context()
        report = harness.run_and_report(data=FIXTURE_TEXTS["simple"], context=ctx)
        assert 0.0 <= report["best_score"] <= 1.0

    def test_report_rounds_is_non_negative_int(self):
        harness, *_ = _make_harness()
        ctx = _make_context()
        report = harness.run_and_report(data=FIXTURE_TEXTS["simple"], context=ctx)
        assert isinstance(report["rounds"], int)
        assert report["rounds"] >= 0

    def test_report_converged_is_bool(self):
        harness, *_ = _make_harness()
        ctx = _make_context()
        report = harness.run_and_report(data=FIXTURE_TEXTS["simple"], context=ctx)
        assert isinstance(report["converged"], bool)

    def test_report_best_ontology_has_entities(self):
        harness, *_ = _make_harness()
        ctx = _make_context()
        report = harness.run_and_report(data=FIXTURE_TEXTS["simple"], context=ctx)
        onto = report["best_ontology"]
        if onto is not None:
            assert "entities" in onto
            assert isinstance(onto["entities"], list)

    def test_report_session_is_base_session(self):
        from ipfs_datasets_py.optimizers.common import BaseSession
        harness, *_ = _make_harness()
        ctx = _make_context()
        report = harness.run_and_report(data=FIXTURE_TEXTS["simple"], context=ctx)
        assert isinstance(report["session"], BaseSession)

    def test_two_runs_independent(self):
        """Different data → different sessions; no shared state."""
        harness, *_ = _make_harness()
        ctx1 = _make_context(domain="legal")
        ctx2 = _make_context(domain="medical")
        r1 = harness.run_and_report(data=FIXTURE_TEXTS["legal"], context=ctx1)
        r2 = harness.run_and_report(data=FIXTURE_TEXTS["medical"], context=ctx2)
        assert r1["session"] is not r2["session"]


# ---------------------------------------------------------------------------
# Full pipeline component interaction tests
# ---------------------------------------------------------------------------

class TestPipelineComponentInteraction:
    """Verify Generator → Critic → Mediator interaction is correctly wired."""

    def test_generator_produces_ontology_after_run(self):
        """After harness.run(), the generator should have been called (implicit
        via session rounds containing scores)."""
        harness, *_ = _make_harness()
        ctx = _make_context()
        session = harness.run(data=FIXTURE_TEXTS["simple"], context=ctx)
        # Each round should have a non-None score
        for rnd in session.rounds:
            assert rnd.score is not None

    def test_session_metrics_populated(self):
        harness, *_ = _make_harness()
        ctx = _make_context()
        session = harness.run(data=FIXTURE_TEXTS["simple"], context=ctx)
        d = session.to_dict()
        assert "score_delta" in d
        assert "avg_score" in d
        assert "regression_count" in d

    def test_harness_created_without_config(self):
        """OntologyPipelineHarness should work with minimal constructor args."""
        from ipfs_datasets_py.optimizers.graphrag import (
            OntologyPipelineHarness,
            OntologyGenerator,
            OntologyCritic,
            OntologyMediator,
        )
        g = OntologyGenerator()
        c = OntologyCritic(use_llm=False)
        m = OntologyMediator(generator=g, critic=c)
        h = OntologyPipelineHarness(generator=g, critic=c, mediator=m)
        assert h is not None
