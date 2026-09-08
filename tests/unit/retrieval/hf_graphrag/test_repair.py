"""Range-routed BM25/CID locator repair: disjoint globally sorted shards."""

from __future__ import annotations

from pathlib import Path

import pyarrow.parquet as pq
import pytest

from ipfs_datasets_py.retrieval.hf_graphrag.artifacts import write_zstd_parquet
from ipfs_datasets_py.retrieval.hf_graphrag.engine import (
    GraphragEngineError,
    covering_locator_rows,
    diagnose_range_routing,
    nest_exploded_postings,
    repair_graphrag_range_routing,
    write_standard_compact_indexes,
    write_term_sorted_posting_shards,
)
def _cell(term: str, docs: list[int], *, chunk: int = 0, count: int = 1) -> dict:
    return {
        "body_frequencies": [1] * len(docs),
        "corpus_frequency": len(docs),
        "document_frequency": len(docs),
        "document_indices": list(docs),
        "document_lengths": [10] * len(docs),
        "idf": 1.5,
        "posting_chunk_count": count,
        "posting_chunk_index": chunk,
        "schema_version": "hf-graphrag-bm25-posting/v1",
        "term": term,
        "title_frequencies": [0] * len(docs),
    }


def _write_posting_shard(path: Path, cells: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    write_zstd_parquet(path, cells)


def test_overlapping_posting_ranges_fail_index_then_repair(tmp_path: Path) -> None:
    postings = tmp_path / "data" / "bm25" / "postings"
    # Internally sorted, but ranges overlap and both cover "foia".
    _write_posting_shard(
        postings / "part-000000.parquet",
        [_cell("etiologic", [1]), _cell("gormley", [2])],
    )
    _write_posting_shard(
        postings / "part-000001.parquet",
        [_cell("agency", [0]), _cell("foia", [3, 4, 5]), _cell("privacy", [6])],
    )

    diagnosis = diagnose_range_routing(tmp_path, families=("bm25_postings",))
    assert diagnosis["bm25_postings"].ok is False
    assert diagnosis["bm25_postings"].overlapping_pairs >= 1

    with pytest.raises(GraphragEngineError, match="overlap|not sorted"):
        write_standard_compact_indexes(tmp_path, families=("bm25_postings",))

    results = repair_graphrag_range_routing(
        tmp_path, families=("bm25_postings",), max_rows=2
    )
    assert results["bm25_postings"].rewritten is True
    assert results["bm25_postings"].diagnosis_after.ok is True

    locator = pq.read_table(tmp_path / "indexes" / "bm25_keyword_shards.parquet")
    rows = locator.to_pylist()
    covering = covering_locator_rows(rows, "foia")
    assert len(covering) == 1
    table = pq.read_table(tmp_path / covering[0]["relative_path"])
    terms = table.column("term").to_pylist()
    assert "foia" in terms
    assert terms == sorted(terms)
    first_keys = [str(row["first_key"]) for row in rows]
    assert first_keys == sorted(first_keys)
    for previous, current in zip(rows, rows[1:]):
        assert previous["last_key"] < current["first_key"]


def test_oversized_singleton_posting_group_is_renested(tmp_path: Path) -> None:
    documents = tmp_path / "data" / "bm25" / "documents"
    postings = tmp_path / "data" / "bm25" / "postings"
    documents.mkdir(parents=True)
    write_zstd_parquet(
        documents / "part-000000.parquet",
        [{"entry_cid": f"bafkreidoc{index:032d}", "document_index": index} for index in range(20)],
    )
    _write_posting_shard(
        postings / "part-000000.parquet",
        [_cell("(1)", [index]) for index in range(20)],
    )
    results = repair_graphrag_range_routing(
        tmp_path, families=("bm25_postings",), max_rows=8, force=True
    )
    assert results["bm25_postings"].rewritten is True
    assert results["bm25_postings"].diagnosis_after.ok is True
    table = pq.read_table(next((tmp_path / "data" / "bm25" / "postings").glob("*.parquet")))
    rows = table.to_pylist()
    assert all(row["term"] == "(1)" for row in rows)
    assert sum(len(row["document_indices"]) for row in rows) == 20
    assert len(rows) == 1


def test_inverted_posting_shard_is_rewritten(tmp_path: Path) -> None:
    postings = tmp_path / "data" / "bm25" / "postings"
    _write_posting_shard(
        postings / "part-000000.parquet",
        [_cell("gormley", [1]), _cell("etiologic", [2])],
    )
    diagnosis = diagnose_range_routing(tmp_path, families=("bm25_postings",))
    assert diagnosis["bm25_postings"].inverted_ranges == 1
    assert diagnosis["bm25_postings"].internally_unsorted == 1

    repair_graphrag_range_routing(tmp_path, families=("bm25_postings",))
    after = diagnose_range_routing(tmp_path, families=("bm25_postings",))
    assert after["bm25_postings"].ok is True
    table = pq.read_table(postings / "part-000000.parquet")
    assert table.column("term").to_pylist() == ["etiologic", "gormley"]


def test_write_term_sorted_posting_shards_keeps_term_atomic(tmp_path: Path) -> None:
    dest = tmp_path / "data" / "bm25" / "postings"
    cells = [
        _cell("foia", [0, 1], chunk=0, count=2),
        _cell("agency", [0]),
        _cell("foia", [2, 3], chunk=1, count=2),
        _cell("privacy", [4]),
    ]
    written = write_term_sorted_posting_shards(cells, dest, max_rows=3)
    assert len(written) == 2
    first = pq.read_table(written[0]).column("term").to_pylist()
    second = pq.read_table(written[1]).column("term").to_pylist()
    # "foia" has two cells and must not split across shards.
    assert first == ["agency", "foia", "foia"]
    assert second == ["privacy"]

    write_standard_compact_indexes(tmp_path, families=("bm25_postings",))
    rows = pq.read_table(tmp_path / "indexes" / "bm25_keyword_shards.parquet").to_pylist()
    assert len(covering_locator_rows(rows, "foia")) == 1
    assert covering_locator_rows(rows, "foia")[0]["first_key"] == "agency"


def test_exploded_postings_are_nested_and_sorted(tmp_path: Path) -> None:
    postings = tmp_path / "data" / "bm25" / "postings"
    _write_posting_shard(
        postings / "part-000000.parquet",
        [
            {"term": "foia", "document_index": 1, "tf": 2},
            {"term": "agency", "document_index": 0, "tf": 1},
        ],
    )
    _write_posting_shard(
        postings / "part-000001.parquet",
        [
            {"term": "foia", "document_index": 0, "tf": 3},
            {"term": "privacy", "document_index": 2, "tf": 1},
        ],
    )
    repair_graphrag_range_routing(
        tmp_path, families=("bm25_postings",), document_count=3, max_rows=2
    )
    files = sorted(postings.glob("part-*.parquet"))
    terms = []
    for path in files:
        table = pq.read_table(path)
        assert "document_indices" in table.schema.names
        terms.extend(table.column("term").to_pylist())
    assert terms == sorted(terms)
    foia_rows = []
    for path in files:
        for row in pq.read_table(path).to_pylist():
            if row["term"] == "foia":
                foia_rows.append(row)
    assert len(foia_rows) == 1
    assert foia_rows[0]["document_indices"] == [0, 1]


def test_write_standard_compact_indexes_repair_flag(tmp_path: Path) -> None:
    postings = tmp_path / "data" / "bm25" / "postings"
    _write_posting_shard(
        postings / "part-000000.parquet",
        [_cell("etiologic", [1]), _cell("gormley", [2])],
    )
    _write_posting_shard(
        postings / "part-000001.parquet",
        [_cell("agency", [0]), _cell("foia", [3])],
    )
    written = write_standard_compact_indexes(
        tmp_path, families=("bm25_postings",), repair=True
    )
    assert written["bm25_postings"].row_count >= 1
    rows = pq.read_table(tmp_path / "indexes" / "bm25_keyword_shards.parquet").to_pylist()
    assert len(covering_locator_rows(rows, "foia")) == 1


def test_nest_then_pack_is_the_future_build_path(tmp_path: Path) -> None:
    hits = [
        {"term": "foia", "document_index": 0, "tf": 2},
        {"term": "agency", "document_index": 0, "tf": 1},
        {"term": "foia", "document_index": 1, "tf": 1},
    ]
    cells = nest_exploded_postings(hits, document_count=2, document_lengths={0: 4, 1: 3})
    dest = tmp_path / "data" / "bm25" / "postings"
    write_term_sorted_posting_shards(cells, dest, max_rows=4096)
    write_standard_compact_indexes(tmp_path, families=("bm25_postings",))
    rows = pq.read_table(tmp_path / "indexes" / "bm25_keyword_shards.parquet").to_pylist()
    assert len(rows) == 1
    assert rows[0]["first_key"] == "agency"
    assert rows[0]["last_key"] == "foia"
    assert len(covering_locator_rows(rows, "foia")) == 1


def test_repair_cli_diagnose_exit_code(tmp_path: Path) -> None:
    from ipfs_datasets_py.retrieval.hf_graphrag.repair import _cli

    postings = tmp_path / "data" / "bm25" / "postings"
    _write_posting_shard(postings / "part-000000.parquet", [_cell("foia", [0])])
    assert _cli(["diagnose", str(tmp_path), "--family", "bm25_postings"]) == 0
    _write_posting_shard(
        postings / "part-000001.parquet",
        [_cell("etiologic", [1]), _cell("gormley", [2])],
    )
    assert _cli(["diagnose", str(tmp_path), "--family", "bm25_postings"]) == 1


def test_repair_uses_resource_aware_process_map(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from ipfs_datasets_py.processors.legal_data.host_worker_budget import TokenizePoolPlan
    from ipfs_datasets_py.retrieval.hf_graphrag import repair as repair_mod

    mapped: list[tuple[str, int]] = []

    def fake_plan(*, per_task_budget=None, requested=None):
        return TokenizePoolPlan(
            workers=4,
            reason="test",
            cpu_count=8,
            mem_available_bytes=16 * 1024**3,
            per_task_budget_bytes=1024**3,
        )

    def fake_map(func, chunks, **kwargs):
        mapped.append((getattr(func, "__name__", str(func)), len(list(chunks))))
        return [func(chunk) for chunk in chunks]

    monkeypatch.setattr(repair_mod, "tokenize_process_pool_size", fake_plan)
    monkeypatch.setattr(repair_mod, "ordered_process_map", fake_map)

    postings = tmp_path / "data" / "bm25" / "postings"
    for index in range(20):
        _write_posting_shard(
            postings / f"part-{index:06d}.parquet",
            [_cell("agency", [index]), _cell("privacy", [index + 100])],
        )
    repair_graphrag_range_routing(tmp_path, families=("bm25_postings",))
    names = {name for name, _count in mapped}
    assert "_index_file_batch" in names
    assert "_write_shard_batch" in names
    assert "_scan_key_file_batch" in names
    assert any(count > 1 for name, count in mapped if name == "_index_file_batch")
