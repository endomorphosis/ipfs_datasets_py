"""Unit tests for shared GraphRAG neighbor runtime."""

from __future__ import annotations

from types import SimpleNamespace

from ipfs_datasets_py.processors.legal_data.lexical_neighbor_runtime import (
    candidate_documents_for_terms,
    documents_by_cid,
    invert_document_terms,
    map_documents_under_pressure,
    worker_limit,
)


def test_documents_by_cid_indexes_entry_and_chunk() -> None:
    doc = SimpleNamespace(entry_cid="e1", chunk_cid="c1")
    mapping = documents_by_cid([doc])
    assert mapping["e1"] is doc
    assert mapping["c1"] is doc


def test_invert_document_terms_skips_non_overlapping() -> None:
    a = SimpleNamespace(
        entry_cid="a",
        fields={"body": SimpleNamespace(terms=("alpha", "law"))},
    )
    b = SimpleNamespace(
        entry_cid="b",
        fields={"body": SimpleNamespace(terms=("law", "beta"))},
    )
    c = SimpleNamespace(
        entry_cid="c",
        fields={"body": SimpleNamespace(terms=("gamma",))},
    )
    inverted = invert_document_terms([a, b, c])
    hits = candidate_documents_for_terms(
        inverted, ("law",), exclude_entry_cid="a"
    )
    assert [doc.entry_cid for doc in hits] == ["b"]


def _triple(value: int) -> int:
    return value * 3


def test_map_documents_under_pressure_preserves_order_with_threads() -> None:
    docs = list(range(20))
    observed: list[int] = []

    def pressure() -> tuple[int, str]:
        observed.append(1)
        return 2, "admitted"

    out = map_documents_under_pressure(
        docs,
        lambda value: value * 3,
        max_workers=2,
        pressure=pressure,
        batch_size=8,
    )
    assert out == [value * 3 for value in docs]
    assert observed


def test_map_documents_under_pressure_picklable_fn_matches_serial() -> None:
    docs = list(range(12))
    out = map_documents_under_pressure(
        docs,
        _triple,
        max_workers=2,
        pressure=lambda: (2, "admitted"),
        batch_size=4,
    )
    assert out == [_triple(value) for value in docs]


def test_worker_limit_collapses_under_pressure() -> None:
    workers, reason = worker_limit(8, lambda: (1, "host_swap_used"))
    assert workers == 1
    assert reason == "host_swap_used"
    workers, reason = worker_limit(8, lambda: (4, "admitted"))
    assert workers == 4
    assert reason == "admitted"


def test_worker_limit_default_follows_heuristic_admission() -> None:
    workers, reason = worker_limit(None, lambda: (10, "admitted"))
    assert workers == 10
    assert reason == "admitted"
