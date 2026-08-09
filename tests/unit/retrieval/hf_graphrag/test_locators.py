"""Unit tests for direct CID-to-corpus and CID-to-vector locators (USCIR-011).

Acceptance: lookup fetches only the containing artifact/page, rejects
overlapping/gapped ranges, handles missing keys explicitly, and is
deterministic.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ipfs_datasets_py.retrieval.hf_graphrag.locators import (
    KIND_CORPUS,
    KIND_VECTORS,
    LOCATOR_FIXTURE_SCHEMA_VERSION,
    LOCATOR_INDEX_SCHEMA_VERSION,
    LOCATOR_SCHEMA_VERSION,
    KeyLocatorIndex,
    LocatorHit,
    LocatorKindError,
    LocatorPageError,
    LocatorRangeError,
    LocatorRow,
    MissingKeyError,
    build_corpus_locator,
    build_dual_cid_locators,
    build_locator_rows_from_keys,
    build_vector_locator,
    example_locator_fixture_payload,
    load_locator_fixture,
    locators_from_fixture,
    normalize_locator_kind,
    page_locator_rows,
    sort_locator_rows,
    validate_locator_ranges,
)
from ipfs_datasets_py.retrieval.hf_graphrag.schema import (
    MAX_ROUTING_ROWS_PER_INDEX,
    content_sha256,
)

FIXTURE_PATH = (
    Path(__file__).resolve().parents[3]
    / "fixtures"
    / "hf_graphrag"
    / "locator_rows.json"
)

_DIGEST = content_sha256("locator-test-shard")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _row(
    first: str,
    last: str,
    *,
    shard_id: int,
    kind: str = KIND_CORPUS,
    path: str | None = None,
    row_count: int = 2,
    page_index: int = 0,
) -> dict[str, object]:
    relative = path or f"data/{kind}/part-{shard_id:06d}.parquet"
    return {
        "first_key": first,
        "kind": kind,
        "last_key": last,
        "page_index": page_index,
        "relative_path": relative,
        "row_count": row_count,
        "schema_version": LOCATOR_SCHEMA_VERSION,
        "sha256": _DIGEST,
        "shard_id": shard_id,
        "size_bytes": 128,
    }


# ---------------------------------------------------------------------------
# Fixture integrity
# ---------------------------------------------------------------------------


def test_locator_fixture_is_sealed_and_loadable() -> None:
    assert FIXTURE_PATH.is_file()
    payload = load_locator_fixture(FIXTURE_PATH)
    assert payload["schema_version"] == LOCATOR_FIXTURE_SCHEMA_VERSION
    assert isinstance(payload["entry_cids"], list)
    assert len(payload["entry_cids"]) == 6
    assert len(payload["corpus_rows"]) == payload["expected"]["corpus_shard_count"]
    assert len(payload["vector_rows"]) == payload["expected"]["vector_shard_count"]

    dual = locators_from_fixture(payload)
    assert dual.corpus.kind == KIND_CORPUS
    assert dual.vectors.kind == KIND_VECTORS
    # Fingerprints are deterministic for the sealed fixture rows.
    assert dual.corpus.fingerprint() == dual.corpus.fingerprint()
    assert dual.vectors.fingerprint() == dual.vectors.fingerprint()
    assert len(dual.corpus.fingerprint()) == 64

    # Golden file matches the pure generator (no wall-clock / path drift).
    generated = example_locator_fixture_payload()
    assert generated["schema_version"] == payload["schema_version"]
    assert generated["entry_cids"] == payload["entry_cids"]
    assert generated["expected"] == payload["expected"]
    assert generated["corpus_rows"] == payload["corpus_rows"]
    assert generated["vector_rows"] == payload["vector_rows"]


def test_example_fixture_payload_is_deterministic() -> None:
    first = example_locator_fixture_payload()
    second = example_locator_fixture_payload()
    assert first == second
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


# ---------------------------------------------------------------------------
# Row schema
# ---------------------------------------------------------------------------


def test_locator_row_round_trip_and_contains() -> None:
    row = LocatorRow.from_mapping(
        _row("entry-a", "entry-c", shard_id=0, kind=KIND_CORPUS)
    )
    assert row.contains("entry-a")
    assert row.contains("entry-b")
    assert row.contains("entry-c")
    assert not row.contains("entry-d")
    again = LocatorRow.from_mapping(row.to_dict())
    assert again.to_dict() == row.to_dict()
    compact = row.to_compact_index_row()
    restored = LocatorRow.from_compact_index_row(compact)
    assert restored.first_key == row.first_key
    assert restored.relative_path == row.relative_path


def test_locator_row_rejects_inverted_range() -> None:
    with pytest.raises(LocatorRangeError, match="inverted/gapped"):
        LocatorRow.from_mapping(
            _row("entry-z", "entry-a", shard_id=0)
        )


def test_normalize_locator_kind_aliases() -> None:
    assert normalize_locator_kind("corpus") == KIND_CORPUS
    assert normalize_locator_kind("vectors") == KIND_VECTORS
    assert normalize_locator_kind("embedding") == KIND_VECTORS
    with pytest.raises(LocatorKindError):
        normalize_locator_kind("bm25")


# ---------------------------------------------------------------------------
# Range validation: overlap / gap / dense shard ids
# ---------------------------------------------------------------------------


def test_validate_rejects_overlapping_ranges() -> None:
    rows = [
        LocatorRow.from_mapping(_row("a", "c", shard_id=0)),
        LocatorRow.from_mapping(_row("c", "e", shard_id=1)),  # boundary overlap
    ]
    with pytest.raises(LocatorRangeError, match="overlap"):
        validate_locator_ranges(rows)


def test_validate_rejects_gapped_shard_id_sequence() -> None:
    rows = [
        LocatorRow.from_mapping(_row("a", "b", shard_id=0)),
        LocatorRow.from_mapping(_row("c", "d", shard_id=2)),  # gap: missing 1
    ]
    with pytest.raises(LocatorRangeError, match="gaps|dense"):
        validate_locator_ranges(rows, require_dense_shard_ids=True)


def test_validate_rejects_misordered_shard_ids_even_without_key_overlap() -> None:
    rows = [
        LocatorRow.from_mapping(_row("c", "d", shard_id=0, path="data/corpus/part-000000.parquet")),
        LocatorRow.from_mapping(_row("a", "b", shard_id=1, path="data/corpus/part-000001.parquet")),
    ]
    # After sort by first_key: shard 1 then shard 0 → mis-ordered sequence.
    with pytest.raises(LocatorRangeError, match="gapped or mis-ordered|gaps"):
        validate_locator_ranges(rows)


def test_validate_accepts_ordered_non_overlapping_ranges() -> None:
    rows = [
        LocatorRow.from_mapping(_row("c", "d", shard_id=1, path="data/corpus/part-000001.parquet")),
        LocatorRow.from_mapping(_row("a", "b", shard_id=0, path="data/corpus/part-000000.parquet")),
    ]
    ordered = validate_locator_ranges(rows)
    assert [row.shard_id for row in ordered] == [0, 1]
    assert ordered[0].first_key == "a"
    assert ordered[1].first_key == "c"


def test_validate_rejects_duplicate_path_or_shard() -> None:
    rows = [
        LocatorRow.from_mapping(_row("a", "b", shard_id=0, path="data/corpus/part-000000.parquet")),
        LocatorRow.from_mapping(_row("c", "d", shard_id=0, path="data/corpus/part-000001.parquet")),
    ]
    with pytest.raises(LocatorRangeError, match="duplicate locator shard_id"):
        validate_locator_ranges(rows)

    rows = [
        LocatorRow.from_mapping(_row("a", "b", shard_id=0, path="data/corpus/same.parquet")),
        LocatorRow.from_mapping(_row("c", "d", shard_id=1, path="data/corpus/same.parquet")),
    ]
    with pytest.raises(LocatorRangeError, match="duplicate locator relative_path"):
        validate_locator_ranges(rows)


def test_page_locator_rows_respects_bound() -> None:
    keys = [f"k-{index:04d}" for index in range(5)]
    rows = build_locator_rows_from_keys(
        keys,
        kind=KIND_CORPUS,
        data_dir="data/corpus",
        max_rows_per_shard=1,
    )
    pages = page_locator_rows(rows, max_rows_per_page=2)
    assert len(pages) == 3
    assert all(len(page) <= 2 for page in pages)
    assert pages[0][0].page_index == 0
    assert pages[1][0].page_index == 1

    with pytest.raises(LocatorPageError, match="exceeds bound"):
        KeyLocatorIndex.from_rows(rows, kind=KIND_CORPUS, max_rows=1)


# ---------------------------------------------------------------------------
# Lookup: single containing artifact, missing keys, determinism
# ---------------------------------------------------------------------------


def test_locate_returns_only_containing_artifact() -> None:
    rows = build_locator_rows_from_keys(
        ["a", "b", "c", "d", "e", "f"],
        kind=KIND_CORPUS,
        data_dir="data/corpus",
        max_rows_per_shard=2,
    )
    index = build_corpus_locator(rows)

    hit = index.locate("c")
    assert isinstance(hit, LocatorHit)
    assert hit.key == "c"
    assert hit.row.first_key == "c"
    assert hit.row.last_key == "d"
    assert hit.relative_path == "data/corpus/part-000001.parquet"
    # Exactly one artifact — not the whole family.
    artifacts = index.containing_artifacts(["c", "d", "a"])
    assert [row.relative_path for row in artifacts] == [
        "data/corpus/part-000000.parquet",
        "data/corpus/part-000001.parquet",
    ]
    assert len(artifacts) == 2


def test_locate_missing_key_raises_explicitly() -> None:
    index = build_corpus_locator(
        build_locator_rows_from_keys(
            ["a", "b", "c", "d"],
            kind=KIND_CORPUS,
            data_dir="data/corpus",
            max_rows_per_shard=2,
        )
    )
    with pytest.raises(MissingKeyError, match="not covered"):
        index.locate("missing-key")
    with pytest.raises(MissingKeyError):
        index.locate("0-before-all")
    with pytest.raises(MissingKeyError):
        index.locate("z-after-all")
    # Gap between inclusive ranges is also a miss (a-b then c-d is contiguous
    # keys here; use a key that falls between non-adjacent ranges).
    gapped = build_corpus_locator(
        [
            _row("a", "b", shard_id=0),
            _row("d", "e", shard_id=1),
        ]
    )
    with pytest.raises(MissingKeyError):
        gapped.locate("c")
    assert gapped.covers("a") is True
    assert gapped.covers("c") is False


def test_locate_many_strict_and_nonstrict() -> None:
    index = build_corpus_locator(
        build_locator_rows_from_keys(
            ["a", "b", "c", "d"],
            kind=KIND_CORPUS,
            data_dir="data/corpus",
            max_rows_per_shard=2,
        )
    )
    hits = index.locate_many(["b", "c"])
    assert [hit.key for hit in hits] == ["b", "c"]
    with pytest.raises(MissingKeyError):
        index.locate_many(["b", "missing"])
    partial = index.locate_many(["b", "missing", "c"], strict=False)
    assert [hit.key for hit in partial] == ["b", "c"]


def test_lookup_is_deterministic_regardless_of_input_row_order() -> None:
    base = build_locator_rows_from_keys(
        ["m", "n", "o", "p", "q", "r"],
        kind=KIND_VECTORS,
        data_dir="data/vectors",
        max_rows_per_shard=2,
    )
    forward = build_vector_locator(base)
    reversed_rows = list(reversed(base))
    backward = build_vector_locator(reversed_rows)
    assert forward.to_dicts() == backward.to_dicts()
    assert forward.fingerprint() == backward.fingerprint()
    assert forward.locate("o").to_dict() == backward.locate("o").to_dict()
    # sort_locator_rows is itself order-independent.
    assert sort_locator_rows(reversed_rows) == sort_locator_rows(base)


def test_build_from_keys_rejects_unsorted_or_duplicate() -> None:
    with pytest.raises(LocatorRangeError, match="sorted ascending"):
        build_locator_rows_from_keys(
            ["b", "a"],
            kind=KIND_CORPUS,
            data_dir="data/corpus",
        )
    with pytest.raises(LocatorRangeError, match="duplicate key"):
        build_locator_rows_from_keys(
            ["a", "a"],
            kind=KIND_CORPUS,
            data_dir="data/corpus",
        )


# ---------------------------------------------------------------------------
# Dual corpus + vector surface
# ---------------------------------------------------------------------------


def test_dual_cid_locators_hydrate_only_containing_pages() -> None:
    payload = load_locator_fixture(FIXTURE_PATH)
    dual = locators_from_fixture(payload)

    hit_corpus = dual.locate_corpus("entry-cid-0003")
    hit_vector = dual.locate_vector("entry-cid-0003")
    assert hit_corpus.kind == KIND_CORPUS
    assert hit_vector.kind == KIND_VECTORS
    assert hit_corpus.relative_path == "data/corpus/part-000001.parquet"
    # vectors max_rows_per_shard=3 → 0001-0003 in shard 0
    assert hit_vector.relative_path == "data/vectors/part-000000.parquet"

    expected = payload["expected"]["hydrate_entry_cid_0003"]
    hydrated = dual.hydrate_artifacts(["entry-cid-0003"])
    assert [row.relative_path for row in hydrated["corpus"]] == expected["corpus_paths"]
    assert [row.relative_path for row in hydrated["vectors"]] == expected["vector_paths"]
    # Never fetch the full family for a single key.
    assert len(hydrated["corpus"]) == 1
    assert len(hydrated["vectors"]) == 1

    with pytest.raises(MissingKeyError):
        dual.locate_corpus(payload["expected"]["missing_key"])


def test_dual_cid_locators_multi_key_minimal_fetch_set() -> None:
    dual = build_dual_cid_locators(
        corpus_rows=build_locator_rows_from_keys(
            ["a", "b", "c", "d", "e", "f"],
            kind=KIND_CORPUS,
            data_dir="data/corpus",
            max_rows_per_shard=2,
        ),
        vector_rows=build_locator_rows_from_keys(
            ["a", "b", "c", "d", "e", "f"],
            kind=KIND_VECTORS,
            data_dir="data/vectors",
            max_rows_per_shard=2,
        ),
    )
    # Keys in shard 0 and shard 2 only — skip middle shard.
    hydrated = dual.hydrate_artifacts(["a", "f"])
    corpus_paths = [row.relative_path for row in hydrated["corpus"]]
    assert corpus_paths == [
        "data/corpus/part-000000.parquet",
        "data/corpus/part-000002.parquet",
    ]
    assert "data/corpus/part-000001.parquet" not in corpus_paths


def test_kind_mismatch_fails_closed() -> None:
    with pytest.raises(LocatorKindError):
        build_corpus_locator(
            [_row("a", "b", shard_id=0, kind=KIND_VECTORS)]
        )


def test_index_schema_version_and_empty_miss() -> None:
    empty = KeyLocatorIndex.from_rows((), kind=KIND_CORPUS)
    assert empty.schema_version == LOCATOR_INDEX_SCHEMA_VERSION
    assert len(empty) == 0
    with pytest.raises(MissingKeyError, match="empty"):
        empty.locate("anything")
    assert empty.to_dict()["row_count"] == 0


def test_physical_routing_bound_constant() -> None:
    assert MAX_ROUTING_ROWS_PER_INDEX == 4096
