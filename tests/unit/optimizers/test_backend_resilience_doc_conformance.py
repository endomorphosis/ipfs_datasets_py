"""Conformance checks for backend resilience documentation drift."""

from __future__ import annotations

from pathlib import Path


def _doc(path: str) -> Path:
    """Resolve optimizer docs path by searching upwards for a concrete file."""
    start = Path(__file__).resolve()
    for parent in start.parents:
        candidate = parent / "docs" / "optimizers" / path
        if candidate.exists():
            return candidate
    return start.parents[0] / "docs" / "optimizers" / path


def test_backend_resilience_inventory_mentions_shared_wrapper_and_exceptions() -> None:
    doc = _doc("BACKEND_RESILIENCE_POLICY_INVENTORY.md")
    assert doc.exists(), f"Missing backend resilience inventory doc: {doc}"
    text = doc.read_text(encoding="utf-8")

    required_snippets = (
        "BackendCallPolicy",
        "execute_with_resilience(...)",
        "OptimizerTimeoutError",
        "RetryableBackendError",
        "CircuitBreakerOpenError",
    )
    for snippet in required_snippets:
        assert snippet in text, f"Missing resilience inventory snippet: {snippet}"


def test_backend_resilience_inventory_mentions_core_covered_modules() -> None:
    doc = _doc("BACKEND_RESILIENCE_POLICY_INVENTORY.md")
    text = doc.read_text(encoding="utf-8")

    required_modules = (
        "`graphrag/ontology_generator.py`",
        "`graphrag/ontology_refinement_agent.py`",
        "`agentic/llm_integration.py`",
        "`logic_theorem_optimizer/logic_extractor.py`",
        "`logic_theorem_optimizer/llm_backend.py`",
        "`logic_theorem_optimizer/formula_translation.py`",
        "`llm_lazy_loader.py`",
    )
    for module in required_modules:
        assert module in text, f"Missing covered-module entry in resilience inventory: {module}"


def test_troubleshooting_guide_contains_backend_resilience_exception_map() -> None:
    doc = _doc("TROUBLESHOOTING_GUIDE.md")
    assert doc.exists(), f"Missing troubleshooting guide doc: {doc}"
    text = doc.read_text(encoding="utf-8")

    required_snippets = (
        "## Backend Resilience Exceptions",
        "### `OptimizerTimeoutError`",
        "### `RetryableBackendError`",
        "### `CircuitBreakerOpenError`",
        "Use these exceptions as control signals, not generic failures:",
    )
    for snippet in required_snippets:
        assert snippet in text, f"Missing troubleshooting resilience snippet: {snippet}"
