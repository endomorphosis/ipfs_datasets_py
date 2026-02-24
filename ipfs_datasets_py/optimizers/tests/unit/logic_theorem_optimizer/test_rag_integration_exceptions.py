"""Tests for typed exception handling in RAG integration adapter."""

from __future__ import annotations

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.rag_integration import (
    RAGIntegration,
)


class _FailingRAG:
    def query(self, query: str):
        raise ValueError("query failure")


class _FailingIngestRAG:
    def ingest_document(self, doc: str, doc_id: str):
        raise RuntimeError("ingest failure")


def test_retrieve_from_rag_handles_typed_query_error() -> None:
    rag = RAGIntegration()
    rag.rag_system = _FailingRAG()

    context = rag._retrieve_from_rag("All drivers must have licenses", num_documents=2, num_examples=1)

    assert context.query == "All drivers must have licenses"
    assert context.confidence == 0.0
    assert context.relevant_documents == []


def test_add_successful_extraction_handles_typed_ingest_error_and_still_caches() -> None:
    rag = RAGIntegration()
    rag.rag_system = _FailingIngestRAG()

    rag.add_successful_extraction(
        input_text="All drivers must have licenses",
        output_formula="OBLIGATION(driver(X), have_license(X))",
        formalism="TDFOL",
        confidence=0.95,
    )

    cache_key = rag._get_example_cache_key("All drivers must have licenses")
    assert cache_key in rag.example_cache
    assert len(rag.example_cache[cache_key]) == 1
