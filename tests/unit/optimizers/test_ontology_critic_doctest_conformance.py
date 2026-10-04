"""Conformance checks for OntologyCritic doctest reference coverage."""

from __future__ import annotations

from pathlib import Path


def _doc(path: str) -> Path:
    start = Path(__file__).resolve()
    for parent in start.parents:
        candidate = parent / "docs" / "optimizers" / path
        if candidate.exists():
            return candidate
    return start.parents[0] / "docs" / "optimizers" / path


def test_ontology_critic_doctest_reference_exists() -> None:
    doc = _doc("ONTOLOGY_CRITIC_DOCTEST_REFERENCE.md")
    assert doc.exists(), f"Missing OntologyCritic doctest reference doc: {doc}"


def test_ontology_critic_stable_public_methods_are_documented_with_doctests() -> None:
    doc = _doc("ONTOLOGY_CRITIC_DOCTEST_REFERENCE.md")
    text = doc.read_text(encoding="utf-8")

    required_methods = (
        "evaluate_ontology",
        "evaluate",
        "evaluate_batch",
        "evaluate_batch_parallel",
        "explain_score",
        "weighted_overall",
        "evaluate_with_rubric",
        "compare_ontologies",
        "compare_versions",
        "calibrate_thresholds",
        "score_trend",
        "emit_dimension_histogram",
        "compare_with_baseline",
        "summarize_batch_results",
        "compare_batch",
        "critical_weaknesses",
        "top_dimension",
        "bottom_dimension",
        "score_range",
    )

    for method_name in required_methods:
        section_header = f"## `{method_name}`"
        if method_name in {"top_dimension", "bottom_dimension"}:
            section_header = "## `top_dimension` / `bottom_dimension`"
        assert section_header in text, f"Missing doctest section for method: {method_name}"

    assert ">>>" in text, "Doctest reference must contain doctest prompts"
