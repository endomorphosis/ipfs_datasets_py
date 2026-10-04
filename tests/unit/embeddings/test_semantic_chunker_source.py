"""Exercise the public semantic adapter without network/model dependencies."""
import subprocess
import sys

import pytest

from ipfs_datasets_py.ml.embeddings.chunker import Chunker, SemanticChunker
from ipfs_datasets_py.ml.embeddings.schema import EmbeddingConfig
from ipfs_datasets_py.ml.embeddings.semantic_boundaries import SemanticBoundaryError


def test_optional_engines_are_not_imported_for_pure_grouping():
    code = '''import sys
from ipfs_datasets_py.ml.embeddings import semantic_boundaries
assert "ipfs_datasets_py.ml.embeddings.core" not in sys.modules
assert "ipfs_datasets_py.ml.embeddings.create_embeddings" not in sys.modules
'''
    subprocess.run([sys.executable, "-c", code], check=True)


def test_legacy_chunker_alias_is_stable_after_submodule_import():
    code = '''from importlib import import_module
import_module("ipfs_datasets_py.ml.embeddings.chunker")
from ipfs_datasets_py.ml.embeddings import SemanticChunker, Chunker, chunker
assert chunker is Chunker and callable(chunker)
'''
    subprocess.run([sys.executable, "-c", code], check=True)


def test_configured_vectors_really_change_boundaries_and_preserve_text():
    text = "  Install TLS.\nRequire HTTPS.  Bake bread. "
    calls = []

    def embedder(texts):
        calls.append(texts)
        return [[1, 0], [1, 0], [0, 1]]

    c = Chunker(resources={"embedder": embedder}, metadata={
        "chunking_strategy": "semantic", "chunk_size": 100, "min_chars": 0})
    chunks = c.chunk_text(text)
    assert len(chunks) == 2
    assert "".join(chunk.content for chunk in chunks) == text
    assert len(calls) == 1 and len(calls[0]) == 3
    assert all(chunk.content == text[chunk.start_index:chunk.end_index] for chunk in chunks)
    assert all(chunk.metadata["embeddings_used"] for chunk in chunks)
    assert all(not chunk.metadata["semantic_correctness_verified"] for chunk in chunks)
    assert c.chunker.last_diagnostics["boundaries"][-1]["reason"] == "similarity_below_threshold"


def test_unconfigured_semantics_are_explicit_sentence_fallback():
    c = SemanticChunker(EmbeddingConfig(model_name="no-network"))
    chunks = c.chunk_text("First sentence. Second sentence.")
    assert chunks and all(x.metadata["embedding_status"] == "not_configured" for x in chunks)
    assert all(not x.metadata["embeddings_used"] for x in chunks)


def test_runtime_failure_is_visible_and_can_fail_closed():
    def broken(texts):
        raise RuntimeError("test backend failed")

    text = "First sentence. Second sentence."
    c = SemanticChunker(embedder=broken)
    assert "".join(x.content for x in c.chunk_text(text)) == text
    assert c.last_diagnostics["embedding_status"] == "structural_fallback"
    assert not c.last_diagnostics["embeddings_used"]
    with pytest.raises(SemanticBoundaryError, match="embedding_failed"):
        SemanticChunker(embedder=broken, on_embedding_error="raise").chunk_text(text)


def test_token_overflow_is_preserved_and_never_sent_to_embedder():
    calls = []
    c = SemanticChunker(embedder=lambda rows: calls.append(rows), embedding_eligible=lambda text: False)
    text = "α" * 400 + "."
    chunks = c.chunk_text(text)
    assert calls == []
    assert chunks[0].content == text and chunks[0].metadata["opaque_atom"]
    assert chunks[0].metadata["token_budget_checked"]
    assert not chunks[0].metadata["embeddings_used"]


def test_sentence_backend_receipt_reports_actual_fallback(monkeypatch):
    from importlib import import_module
    module = import_module("ipfs_datasets_py.ml.embeddings.chunker")
    monkeypatch.setattr(module, "pysbd", None)
    result = module.sentence_source_spans_with_diagnostics("Full vs. masked images. Retry.")
    assert result["backend"] == "source-punctuation-fallback/v1"
    assert result["fallback_reason"] == "splitter_unavailable"
    assert result["spans"] == [(0, 23), (24, 30)]


def test_optional_splitter_cannot_make_wrapped_sentence_fragments(monkeypatch):
    from importlib import import_module
    from types import SimpleNamespace
    module = import_module("ipfs_datasets_py.ml.embeddings.chunker")
    text = "Before this, the file pruned slashes via its split\ninvocation. Retry."
    split = text.index("invocation")
    last = text.index("Retry")
    spans = [SimpleNamespace(start=a, end=b, sent=text[a:b])
             for a, b in [(0, split), (split, last), (last, len(text))]]
    monkeypatch.setattr(module, "pysbd", SimpleNamespace(Segmenter=lambda **kwargs:
        SimpleNamespace(segment=lambda text: spans)))
    result = module.sentence_source_spans_with_diagnostics(text)
    assert [text[a:b] for a, b in result["spans"]] == [
        "Before this, the file pruned slashes via its split\ninvocation.", "Retry."]
    assert result["nonterminal_wraps_coalesced"] == 1
