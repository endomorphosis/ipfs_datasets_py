"""Large-corpus vector and BM25 paths must not materialize Python float lists."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import pytest

from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.graph import (
    iter_structural_edges,
    iter_structural_nodes,
)
from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.parquet_io import (
    write_corpus_shards,
    write_dataframe_chunked,
)
from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.sparse import (
    _graph_nodes_and_edges,
)
from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.vectors import (
    DIMENSION,
    corpus_cid_fingerprint,
    encode_corpus,
    layout_vectors_streaming,
    load_complete_checkpoint,
)


def test_complete_checkpoint_skips_text_and_encoder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom() -> bool:
        raise AssertionError("encoder stack should not load for a finished checkpoint")

    monkeypatch.setattr(
        "ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.vectors.ensure_embedding_stack",
        _boom,
    )
    n = 4
    matrix = np.arange(n * DIMENSION, dtype=np.float32).reshape(n, DIMENSION)
    ckpt = tmp_path / "country.npy"
    np.save(ckpt, matrix)
    (tmp_path / "country.json").write_text(
        json.dumps({"n": n, "done": n, "dimension": DIMENSION}) + "\n",
        encoding="utf-8",
    )
    corpus = pd.DataFrame({"title": ["x"] * n, "body": ["y"] * n})
    loaded = encode_corpus(corpus, checkpoint_path=str(ckpt))
    assert encode_corpus.last_checkpoint_hit is True
    assert loaded.shape == (n, DIMENSION)
    assert loaded.flags["C_CONTIGUOUS"]
    assert loaded.flags["WRITEABLE"]
    np.testing.assert_array_equal(loaded, matrix)
    loaded[0, 0] += 1.0
    assert loaded[0, 0] != matrix[0, 0]
    assert load_complete_checkpoint(str(ckpt), n + 1) is None


def _tiny_corpus(n: int = 8) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "entry_cid": [f"cid-{i}" for i in range(n)],
            "document_index": list(range(n)),
            "record_type": ["law"] * n,
            "title": [f"Title {i}" for i in range(n)],
            "law_cid": [f"law-{i}" for i in range(n)],
            "instrument_id": [f"inst-{i}" for i in range(n)],
            "law_id": [f"lawid-{i}" for i in range(n)],
            "language": ["pl"] * n,
            "jurisdiction": ["pl"] * n,
        }
    )


def test_streaming_vector_layout_matches_parquet_schema_and_resumes(tmp_path: Path) -> None:
    corpus = _tiny_corpus()
    rng = np.random.default_rng(7)
    embeddings = rng.normal(size=(len(corpus), DIMENSION)).astype(np.float32)
    out = tmp_path / "shards"
    laid = layout_vectors_streaming(corpus, embeddings, out)
    assert laid["stats"]["n_vectors"] == len(corpus)
    assert laid["stats"]["status"] == "embedded"
    assert laid["stats"]["assignment"] == "recursive_spherical_kmeans"
    assert "vectors" not in laid
    parts = sorted(out.glob("part-*.parquet"))
    assert parts
    seen: list[str] = []
    for path in parts:
        table = pq.read_table(path)
        assert table.schema.field("embedding").type == pq.read_schema(path).field("embedding").type
        assert str(table.schema.field("embedding").type).startswith("list<")
        assert "double" in str(table.schema.field("embedding").type)
        frame = table.to_pandas()
        seen.extend(frame["entry_cid"].tolist())
        norms = np.linalg.norm(np.stack(frame["embedding"].to_numpy()), axis=1)
        np.testing.assert_allclose(norms, 1.0, rtol=1e-4, atol=1e-4)
    assert sorted(seen) == sorted(corpus["entry_cid"].tolist())

    resumed = layout_vectors_streaming(corpus, None, out)
    assert resumed["stats"]["n_vectors"] == len(corpus)
    assert resumed["prewritten_dir"] == str(out)

    changed = corpus.copy()
    changed.loc[0, "entry_cid"] = "cid-other"
    with pytest.raises(ValueError):
        layout_vectors_streaming(changed, None, out)


def test_spilled_bm25_matches_in_memory_builder(tmp_path: Path) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.bm25_spill import spill_bm25_layout
    from ipfs_datasets_py.retrieval.hf_graphrag.bm25 import BM25LayoutConfig, build_bm25_layout

    rows = [
        {
            "entry_cid": "cid-a",
            "title": "Dog Act",
            "body": "The dog-act applies to dogs and birds.",
            "record_type": "law",
            "document_index": 0,
        },
        {
            "entry_cid": "cid-b",
            "title": "Cat Act",
            "body": "The cat and the dog act share terms.",
            "record_type": "law",
            "document_index": 1,
        },
        {
            "entry_cid": "cid-c",
            "title": "Bird Act",
            "body": "Birds dogs and the dog-act again.",
            "record_type": "statute",
            "document_index": 2,
        },
    ]
    reference_rows = [dict(row) for row in rows]
    ref_dir = tmp_path / "ref"
    got_dir = tmp_path / "got"
    work_dir = tmp_path / "work"
    build_bm25_layout(reference_rows, ref_dir, config=BM25LayoutConfig(max_documents=10))
    spill_bm25_layout(rows, got_dir, work_dir=work_dir, fingerprint="bm25-test")
    assert rows == []

    def _concat(root: Path, relative: str) -> list[dict]:
        tables = [pq.read_table(path) for path in sorted((root / relative).glob("part-*.parquet"))]
        return [dict(item) for table in tables for item in table.to_pylist()]

    assert _concat(got_dir, "data/bm25/documents") == _concat(ref_dir, "data/bm25/documents")
    assert _concat(got_dir, "data/bm25/postings") == _concat(ref_dir, "data/bm25/postings")


def test_streaming_layout_fingerprint_tracks_entry_cids() -> None:
    frame = _tiny_corpus(2)
    first = corpus_cid_fingerprint(frame)
    frame.loc[1, "entry_cid"] = "cid-changed"
    assert corpus_cid_fingerprint(frame) != first


def _graph_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "entry_cid": "law-cid",
                "record_type": "law",
                "instrument_id": "inst-1",
                "instrument_title": "Dog Act",
                "law_cid": "law-cid",
                "article_number": "",
                "title": "Dog Act",
                "source_id": "inst-1",
                "jurisdiction": "fr",
                "language": "fr",
                "source_type": "case",
                "law_status": "in_force",
                "eli": "",
                "official_identifier": "",
                "identifier": "",
            },
            {
                "entry_cid": "art-1",
                "record_type": "article",
                "instrument_id": "inst-1",
                "instrument_title": "Dog Act",
                "law_cid": "law-cid",
                "article_number": "1",
                "title": "Article 1",
                "source_id": "inst-1-article-1",
                "jurisdiction": "fr",
                "language": "fr",
                "source_type": "case",
                "law_status": "in_force",
                "eli": "eli:fr:1",
                "official_identifier": "  ",
                "identifier": "ECLI:FR:1",
            },
            {
                "entry_cid": "sec-2",
                "record_type": "section",
                "instrument_id": "inst-1",
                "instrument_title": "Dog Act",
                "law_cid": "law-cid",
                "article_number": "2",
                "title": "Section 2",
                "source_id": "inst-1-section-2",
                "jurisdiction": "fr",
                "language": "fr",
                "source_type": "case",
                "law_status": "in_force",
                "eli": "",
                "official_identifier": "CE:2",
                "identifier": "other",
            },
        ]
    )


def test_streamed_graph_matches_in_memory_nodes_and_edges(tmp_path: Path) -> None:
    frame = _graph_frame()
    path = tmp_path / "corpus.parquet"
    frame.to_parquet(path, index=False)
    nodes, edges = _graph_nodes_and_edges(frame)

    def _node_key(row: dict) -> tuple:
        return (row["node_cid"], row["node_type"], row["label"], row.get("entry_cid"))

    def _edge_key(row: dict) -> tuple:
        return (
            row["edge_cid"],
            row["edge_type"],
            row["source_node_cid"],
            row["target_node_cid"],
            row["retrieval_method"],
            float(row["score"]),
        )

    assert sorted(_node_key(row) for row in iter_structural_nodes(path)) == sorted(
        _node_key(row) for row in nodes
    )
    assert sorted(_edge_key(row) for row in iter_structural_edges(path)) == sorted(
        _edge_key(row) for row in edges
    )


def test_corpus_shards_stream_without_a_full_frame(tmp_path: Path) -> None:
    frame = _tiny_corpus(10)
    frame["body"] = [f"body {i}" for i in range(10)]
    frame["record_type"] = ["law" if i % 2 == 0 else "article" for i in range(10)]
    source = tmp_path / "corpus.parquet"
    frame.to_parquet(source, index=False)
    out = tmp_path / "shards"
    rows, stats = write_corpus_shards(source, out, "data/corpus", max_rows=3)
    assert stats == {"n_rows": 10, "n_laws": 5, "n_articles": 5}
    assert len(rows) == 4
    loaded = pd.concat(
        [pd.read_parquet(out / f"part-{i:06d}.parquet") for i in range(4)],
        ignore_index=True,
    )
    pd.testing.assert_frame_equal(
        loaded.reset_index(drop=True),
        frame.reset_index(drop=True),
        check_dtype=False,
    )


def test_chunked_parquet_write_matches_rows(tmp_path: Path) -> None:
    frame = _tiny_corpus(10)
    frame["body"] = [f"body {i}" for i in range(10)]
    path = tmp_path / "corpus.parquet"
    write_dataframe_chunked(frame, path, rows_per_group=3)
    loaded = pd.read_parquet(path)
    pd.testing.assert_frame_equal(
        loaded.reset_index(drop=True),
        frame.reset_index(drop=True),
        check_dtype=False,
    )


def test_streamed_normalize_matches_in_memory_order(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.normalize import (
        _empty_articles,
        build_corpus,
    )
    from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.reconstruct import (
        article_sort_key,
    )
    from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir import stream_corpus
    from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.stream_corpus import (
        article_sort_key_hex,
        stream_laws_corpus,
    )

    keys = [
        ("", "z"),
        ("2", "a"),
        ("10", "b"),
        ("Section 1", "m"),
        ("٢", "a"),
    ]
    ordered = sorted(keys, key=lambda item: article_sort_key(*item))
    hexes = [article_sort_key_hex(*item) for item in ordered]
    assert hexes == sorted(hexes)

    split = (
        "Section 1. Definitions for the streamed municipal fixture, long enough to keep.\n"
        "Section 2. Procedure for the streamed municipal fixture, long enough to keep."
    )
    plain = "A whole instrument body with no headings, long enough to keep as one law."
    rows = [
        {"id": "m-split", "title": "Split ordinance", "text": split, "language": "en", "jurisdiction": "Fixture"},
        {"id": "a-plain", "title": "Plain ordinance", "text": plain, "language": "en", "jurisdiction": "Fixture"},
        {"id": "m-split", "title": "Split ordinance", "text": split, "language": "en", "jurisdiction": "Fixture"},
    ]
    laws = pd.DataFrame(rows)
    meta = {
        "source_dataset": "justicedao/american_municipal_law_norm",
        "source_revision": "rev-stream",
        "laws_sha256": "abc",
        "articles_sha256": None,
        "schema_surprises": [],
        "n_laws_source": len(laws),
    }
    expected, _report = build_corpus(laws, _empty_articles(), meta)
    source = tmp_path / "laws.parquet"
    laws.to_parquet(source, index=False)
    streamed, report = stream_laws_corpus(source, meta, tmp_path / "corpus.parquet", batch_rows=1)
    assert int(report["n_out"]) == len(expected)
    assert int(report["drops"]["duplicate_cid"]) >= 1
    got = pd.read_parquet(tmp_path / "corpus.parquet")
    columns = ["entry_cid", "record_type", "instrument_id", "article_number", "body", "document_index"]
    pd.testing.assert_frame_equal(
        got[columns].reset_index(drop=True),
        expected[columns].reset_index(drop=True),
        check_dtype=False,
    )
    assert "rn" not in got.columns
    monkeypatch.setattr(stream_corpus, "STREAM_LAYOUT_MIN_ROWS", 1)
    slim = stream_corpus.load_corpus_frame(tmp_path / "corpus.parquet")
    assert "body" not in slim.columns
    assert list(slim.columns) == ["entry_cid", "document_index"]
    assert slim.attrs["body_parquet"].endswith("corpus.parquet")


def test_external_key_sort_merges_runs_and_keeps_the_first_row(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Duplicate cids collapse without a window, including across a fan-in boundary."""
    import pyarrow as pa

    from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir import stream_corpus

    monkeypatch.setattr(stream_corpus, "_MERGE_FANIN", 2)
    monkeypatch.setattr(stream_corpus, "_RUN_ROWS", 3)
    schema = pa.schema(
        [
            ("entry_cid", pa.string()),
            ("instrument_id", pa.string()),
            ("sort_key", pa.string()),
            ("source_id", pa.string()),
            ("part_id", pa.int32()),
            ("row_in_file", pa.int32()),
        ]
    )
    groups = [
        [
            ("A", "m", "b", "a0", 0, 0),
            ("A", "a", "a", "a1", 0, 1),
        ],
        [
            ("B", "m", "a", "b0", 1, 0),
            ("B", "m", "a", "b1", 1, 1),
        ],
        [
            ("C", None, "a", "c0", 2, 0),
            ("A", "z", "a", "a2", 2, 0),
        ],
    ]
    keys = tmp_path / "keys"
    keys.mkdir()
    for part_id, rows in enumerate(groups):
        columns = list(zip(*rows))
        table = pa.Table.from_arrays(
            [pa.array(col, type=schema.field(i).type) for i, col in enumerate(columns)],
            schema=schema,
        )
        pq.write_table(table, keys / f"keys-{part_id:05d}.parquet")
    samples = stream_corpus._window_sort_keys(keys, tmp_path / "winners.parquet", tmp_path / "sort")
    winners = pq.read_table(tmp_path / "winners.parquet").to_pylist()
    assert winners == [
        {"part_id": 0, "row_in_file": 1, "document_index": 0},
        {"part_id": 1, "row_in_file": 0, "document_index": 1},
        {"part_id": 2, "row_in_file": 0, "document_index": 2},
    ]
    assert samples == ["a0", "a2", "b1"]


def test_large_complete_checkpoint_stays_a_memmap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom() -> bool:
        raise AssertionError("encoder stack should not load for a finished large checkpoint")

    monkeypatch.setattr(
        "ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.vectors.SEQUENTIAL_LAYOUT_MIN_ROWS",
        4,
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.vectors.STREAM_LAYOUT_MIN_ROWS",
        4,
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.vectors.ensure_embedding_stack",
        _boom,
    )
    n = 4
    matrix = np.arange(n * DIMENSION, dtype=np.float32).reshape(n, DIMENSION)
    ckpt = tmp_path / "country.npy"
    np.save(ckpt, matrix)
    (tmp_path / "country.json").write_text(
        json.dumps({"n": n, "done": n, "dimension": DIMENSION}) + "\n",
        encoding="utf-8",
    )
    assert load_complete_checkpoint(str(ckpt), n) is None
    corpus = pd.DataFrame(
        {"entry_cid": [f"cid-{i}" for i in range(n)], "document_index": list(range(n))}
    )
    loaded = encode_corpus(corpus, checkpoint_path=str(ckpt))
    assert encode_corpus.last_checkpoint_hit is True
    assert isinstance(loaded, np.memmap)
    assert loaded.shape == (n, DIMENSION)
    np.testing.assert_array_equal(np.asarray(loaded), matrix)


def test_sequential_layout_reads_strings_from_parquet(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.vectors.SEQUENTIAL_LAYOUT_MIN_ROWS",
        4,
    )
    monkeypatch.setattr(
        "ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.vectors.MAX_ROWS_PER_FILE",
        4,
    )
    n = 8
    full = pd.DataFrame(
        {
            "entry_cid": [f"cid-{i}" for i in range(n)],
            "document_index": list(range(n)),
            "title": [f"Title {i}" for i in range(n)],
            "record_type": ["law"] * n,
            "law_cid": [f"law-{i}" for i in range(n)],
            "instrument_id": [f"inst-{i}" for i in range(n)],
            "law_id": [f"lawid-{i}" for i in range(n)],
            "language": ["en"] * n,
            "jurisdiction": ["us"] * n,
            "body": [f"body {i} is long enough" for i in range(n)],
        }
    )
    corpus_path = tmp_path / "corpus.parquet"
    full.to_parquet(corpus_path, index=False)
    slim = full[["entry_cid", "document_index"]].copy()
    slim.attrs["body_parquet"] = str(corpus_path)
    matrix = np.random.default_rng(3).normal(size=(n, DIMENSION)).astype(np.float32)
    stored = tmp_path / "emb.npy"
    np.save(stored, matrix)
    embeddings = np.load(stored, mmap_mode="r")
    real = np.ascontiguousarray

    def _guard(array, dtype=None, *, like=None):
        del like
        shape = getattr(np.asarray(array), "shape", None)
        if shape == (n, DIMENSION):
            raise AssertionError("sequential layout copied the full embedding matrix")
        if dtype is None:
            return real(array)
        return real(array, dtype=dtype)

    monkeypatch.setattr(np, "ascontiguousarray", _guard)
    out = tmp_path / "shards"
    laid = layout_vectors_streaming(slim, embeddings, out)
    assert laid["stats"]["assignment"] == "sequential_row_chunks"
    assert laid["stats"]["layout"] == "sequential_row_chunks"
    assert laid["stats"]["n_vectors"] == n
    assert laid["stats"]["shard_count"] == 2
    assert "vectors" not in laid
    parts = sorted(out.glob("part-*.parquet"))
    assert [path.name for path in parts] == ["part-000000.parquet", "part-000001.parquet"]
    seen: list[str] = []
    titles: list[str] = []
    for part, (lo, hi) in zip(parts, ((0, 4), (4, 8))):
        got = pq.read_table(part).to_pandas()
        assert len(got) == 4
        faiss = [int(value) for value in got["faiss_id"].tolist()]
        assert set(faiss) == set(range(lo, hi))
        seen.extend(got["entry_cid"].tolist())
        titles.extend(got["title"].tolist())
        norms = np.linalg.norm(np.stack(got["embedding"].to_numpy()), axis=1)
        np.testing.assert_allclose(norms, 1.0, rtol=1e-4, atol=1e-4)
    assert sorted(seen) == sorted(full["entry_cid"].tolist())
    assert sorted(titles) == sorted(full["title"].tolist())
    assert stored.stat().st_size == (tmp_path / "emb.npy").stat().st_size
    resumed = layout_vectors_streaming(slim, None, out)
    assert resumed["stats"]["n_vectors"] == n
    assert resumed["stats"]["assignment"] == "sequential_row_chunks"
