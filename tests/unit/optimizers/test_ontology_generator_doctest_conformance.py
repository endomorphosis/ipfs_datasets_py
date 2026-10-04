"""Conformance checks for OntologyGenerator doctest reference coverage."""

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


def test_ontology_generator_doctest_reference_exists() -> None:
    doc = _doc("ONTOLOGY_GENERATOR_DOCTEST_REFERENCE.md")
    assert doc.exists(), f"Missing OntologyGenerator doctest reference doc: {doc}"


def test_ontology_generator_stable_public_methods_are_documented_with_doctests() -> None:
    doc = _doc("ONTOLOGY_GENERATOR_DOCTEST_REFERENCE.md")
    text = doc.read_text(encoding="utf-8")

    required_methods = (
        "extract_entities",
        "infer_relationships",
        "extract_entities_from_file",
        "batch_extract",
        "extract_entities_streaming",
        "extract_entities_with_spans",
        "extract_with_coref",
        "extract_with_context_windows",
        "generate_ontology",
        "__call__",
        "generate_ontology_rich",
        "generate_with_feedback",
        "generate_synthetic_ontology",
        "batch_extract_with_spans",
        "extract_keyphrases",
        "extract_noun_phrases",
        "merge_results",
        "deduplicate_entities",
        "anonymize_entities",
        "tag_entities",
        "score_entity",
        "describe_result",
        "result_summary_dict",
        "extract_entities_async",
        "extract_batch_async",
        "infer_relationships_async",
        "extract_with_streaming_async",
    )

    for method_name in required_methods:
        section_header = f"## `{method_name}`"
        assert section_header in text, f"Missing doctest section for method: {method_name}"

    # Ensure we keep actual doctest prompts in the reference.
    assert ">>>" in text, "Doctest reference must contain doctest prompts"
