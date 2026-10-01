"""Exact source selectors and finite windows for the generic text chunkers."""
import asyncio
import importlib
from types import SimpleNamespace

import pytest


sut = importlib.import_module("ipfs_datasets_py.ml.embeddings.chunker")


def config(size=16, overlap=0):
    return sut.EmbeddingConfig(model_name="offline-test", chunk_size=size, chunk_overlap=overlap)


def assert_source_chunks(text, chunks):
    assert all(chunk.content and chunk.content == text[chunk.start_index:chunk.end_index]
               for chunk in chunks)
    assert all(0 <= chunk.start_index < chunk.end_index <= len(text) for chunk in chunks)
    assert [chunk.chunk_id for chunk in chunks] == [f"chunk_{i}" for i in range(len(chunks))]


@pytest.mark.parametrize("kind", [sut.FixedSizeChunker, sut.SlidingWindowChunker])
@pytest.mark.parametrize("text,size,overlap", [
    ("short", 16, 4), ("abcdefghijk", 5, 2), ("abcdefghij", 5, 4),
    ("abcdefg hijklmnop", 10, 9), ("  \tαβγ   delta\n  café\u2003 z ", 10, 3),
])
def test_overlapping_windows_terminate_and_point_at_exact_source(kind, text, size, overlap, monkeypatch):
    # Fail an old EOF loop immediately rather than allowing a regression test to
    # allocate unbounded chunks or depend on a wall-clock timeout.
    original_chunk = sut.DocumentChunk
    calls = []

    def bounded_document_chunk(**kwargs):
        calls.append(kwargs)
        assert len(calls) <= len(text) + 1, "overlapping windows failed to advance"
        return original_chunk(**kwargs)

    monkeypatch.setattr(sut, "DocumentChunk", bounded_document_chunk)
    chunks = kind(config(size, overlap)).chunk_text(text)
    assert_source_chunks(text, chunks)
    assert chunks[-1].end_index == len(text.rstrip())
    assert all(len(chunk.content) <= size for chunk in chunks)
    assert chunks[-1].content.endswith(text.rstrip()[-1])
    covered = {i for chunk in chunks for i in range(chunk.start_index, chunk.end_index)}
    assert all(i in covered for i, char in enumerate(text) if not char.isspace())


@pytest.mark.parametrize("kind", [sut.FixedSizeChunker, sut.SlidingWindowChunker, sut.SentenceChunker])
@pytest.mark.parametrize("size", [0, -1, 1.5, True, "10", None])
def test_invalid_chunk_sizes_fail_before_iteration(kind, size):
    with pytest.raises(ValueError, match="chunk_size"):
        kind(config(size))


@pytest.mark.parametrize("kind", [sut.FixedSizeChunker, sut.SlidingWindowChunker])
@pytest.mark.parametrize("overlap", [-1, 8, 9, True, 1.5, "1", None])
def test_invalid_window_overlap_cannot_make_zero_or_negative_progress(kind, overlap):
    with pytest.raises(ValueError, match="chunk_overlap"):
        kind(config(8, overlap))


def test_mutated_zero_step_is_rejected_at_use_time():
    chunker = sut.SlidingWindowChunker(config())
    chunker.step_size = 0
    with pytest.raises(ValueError):
        chunker.chunk_text("unchanged source")
    fixed = sut.FixedSizeChunker(config())
    fixed.chunk_size = 0
    with pytest.raises(ValueError):
        fixed.chunk_text("unchanged source")


@pytest.mark.parametrize("kind", [sut.FixedSizeChunker, sut.SlidingWindowChunker, sut.SentenceChunker])
def test_blank_inputs_do_not_create_empty_chunks(kind):
    chunker = kind(config())
    assert chunker.chunk_text("") == chunker.chunk_text(" \t\r\n\u2003") == []


def test_fallback_retains_abbreviations_decimal_versions_urls_and_punctuation(monkeypatch):
    monkeypatch.setattr(sut, "pysbd", None)
    first = "Dr. García uses e.g. v1.2.3 and 3.14 at https://example.org/a.b?x=1.2."
    text = "  " + first + "\n\tNext result!  Final result? "
    intervals = sut.sentence_source_spans(text)
    assert [text[start:end] for start, end in intervals] == [first, "Next result!", "Final result?"]
    assert text[:intervals[0][0]].isspace() and text[intervals[-1][1]:].isspace()
    assert intervals[0][0] == 2


@pytest.mark.parametrize("first,second", [
    ("Compare full vs. masked images.", "Keep context."),
    ("See the report (cf. #2170) for details.", "Keep context."),
    ("Keep the explanation (i.e. continuation) intact.", "Next result!"),
    ("The vendor is Acme Inc.", "It supplies updates."),
])
def test_fallback_handles_parenthesized_abbreviations_and_real_sentence_endings(monkeypatch, first, second):
    monkeypatch.setattr(sut, "pysbd", None)
    text = first + "  " + second
    assert [text[start:end] for start, end in sut.sentence_source_spans(text)] == [first, second]


def test_sentence_groups_use_original_whitespace_and_repeated_text_offsets(monkeypatch):
    monkeypatch.setattr(sut, "pysbd", None)
    text = " \tSame.\n\nSame.  Same!\tFin. "
    chunks = sut.SentenceChunker(config(12)).chunk_text(text)
    assert_source_chunks(text, chunks)
    assert [chunk.content for chunk in chunks] == ["Same.\n\nSame.", "Same!\tFin."]
    assert [(chunk.start_index, chunk.end_index) for chunk in chunks] == [(2, 14), (16, 26)]


def test_oversize_sentence_stays_atomic_with_explicit_metadata(monkeypatch):
    monkeypatch.setattr(sut, "pysbd", None)
    text = "Small.  " + "λ" * 30 + ".  Tail!"
    metadata = {"source": "fixture"}
    chunks = sut.SentenceChunker(config(12)).chunk_text(text, metadata)
    assert_source_chunks(text, chunks)
    assert [chunk.content for chunk in chunks] == ["Small.", "λ" * 30 + ".", "Tail!"]
    assert chunks[1].metadata == {"source": "fixture", "oversize_atomic_sentence": True, "chunk_size_limit": 12}
    assert metadata == {"source": "fixture"}
    assert "oversize_atomic_sentence" not in chunks[0].metadata


def test_character_span_splitter_is_used_without_searching_repeated_strings(monkeypatch):
    calls = []

    class Segmenter:
        def __init__(self, **kwargs):
            assert kwargs == {"language": "en", "clean": False, "char_span": True}

        def segment(self, text):
            calls.append(text)
            return [SimpleNamespace(start=2, end=8, sent=text[2:8]),
                    SimpleNamespace(start=8, end=13, sent=text[8:13])]

    monkeypatch.setattr(sut, "pysbd", SimpleNamespace(Segmenter=Segmenter))
    text = "  Echo. Echo. "
    assert sut.sentence_source_spans(text) == [(2, 7), (8, 13)]
    assert calls == [text]


@pytest.mark.parametrize("bad_rows", [
    ["First.", "Second."],
    [SimpleNamespace(start=0, end=6, sent="rewritten")],
    [SimpleNamespace(start=7, end=14, sent="Second.")],
    [SimpleNamespace(start=0, end=100, sent="First. Second.")],
])
def test_invalid_optional_selectors_fall_back_without_omitting_source(monkeypatch, bad_rows):
    monkeypatch.setattr(sut, "pysbd", SimpleNamespace(Segmenter=lambda **kwargs:
        SimpleNamespace(segment=lambda text: bad_rows)))
    text = "First. Second."
    assert sut.sentence_source_spans(text) == [(0, 6), (7, 14)]


def test_old_optional_splitter_without_char_span_support_uses_fallback(monkeypatch):
    def unsupported(**kwargs):
        raise TypeError("char_span unavailable")
    monkeypatch.setattr(sut, "pysbd", SimpleNamespace(Segmenter=unsupported))
    assert sut.sentence_source_spans("First. Second.") == [(0, 6), (7, 14)]


def test_real_optional_splitter_selectors_when_installed():
    if sut.pysbd is None:
        pytest.skip("optional pysbd is not installed")
    text = " \tDr. García reads v1.2.3.\nAgain.  Again! "
    chunks = sut.SentenceChunker(config(28)).chunk_text(text)
    assert_source_chunks(text, chunks)
    intervals = sut.sentence_source_spans(text)
    assert all(text[start:end].strip() == text[start:end] for start, end in intervals)
    assert all(not text[end:next_start].strip() for (_, end), (next_start, _) in zip(intervals, intervals[1:]))


@pytest.mark.parametrize("kind", [sut.FixedSizeChunker, sut.SlidingWindowChunker, sut.SentenceChunker])
def test_async_chunking_preserves_the_same_source_slices(kind):
    text = "  αβ.\nNext sentence!  "
    chunker = kind(config(12, 3))

    async def collect():
        return [chunk async for chunk in chunker.chunk_text_async(text)]

    actual = asyncio.run(collect())
    expected = chunker.chunk_text(text)
    assert [row.to_dict() for row in actual] == [row.to_dict() for row in expected]
    assert_source_chunks(text, actual)
