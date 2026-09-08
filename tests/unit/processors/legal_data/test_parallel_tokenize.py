"""Determinism and serial fallback for resource-aware tokenize."""

from __future__ import annotations

from ipfs_datasets_py.processors.legal_data.parallel_tokenize import (
    chunk_items,
    tokenize_indexable_batch,
)
from ipfs_datasets_py.processors.legal_data.uscode_tokenizer import tokenize_legal_text


def test_chunk_items_covers_the_sequence() -> None:
    assert chunk_items(list(range(5)), 2) == [[0, 1], [2, 3], [4]]


def test_tokenize_batch_matches_serial_legal_tokenizer() -> None:
    texts = [
        "The Environmental Protection Agency amends 40 CFR 52.21.",
        "See 5 U.S.C. § 552 for the records statute.",
        "Notice of proposed rulemaking.",
    ]
    serial = [
        tokenize_legal_text(text, drop_stopwords=True).indexable_terms for text in texts
    ]
    batched = tokenize_indexable_batch(texts, drop_stopwords=True, workers=1)
    assert batched == serial
