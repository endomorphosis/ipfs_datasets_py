"""Tests for OntologyHarness.run_sessions with real generator + critic."""

from ipfs_datasets_py.optimizers.graphrag import (
    OntologyHarness,
    OntologyGenerationContext,
    DataType,
    ExtractionStrategy,
)


def _make_context(domain: str) -> OntologyGenerationContext:
    return OntologyGenerationContext(
        data_source="test",
        data_type=DataType.TEXT,
        domain=domain,
        extraction_strategy=ExtractionStrategy.RULE_BASED,
    )


def test_harness_run_sessions_real_components():
    """Harness should run real sessions and return aggregated BatchResult."""
    harness = OntologyHarness(parallelism=1, max_retries=0)

    docs = [
        "Alice works for Acme Corp.",
        "Bob manages the New York office for Acme.",
    ]
    contexts = [_make_context("legal"), _make_context("legal")]

    result = harness.run_sessions(docs, contexts, num_sessions_per_source=1)

    assert result.total_sessions == 2
    assert result.success_rate == 1.0
    assert len(result.sessions) == 2
    assert result.average_score >= 0.0
    assert result.best_session is not None
