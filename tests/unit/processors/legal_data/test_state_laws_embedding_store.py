from __future__ import annotations

from pathlib import Path

import pyarrow.parquet as pq

from ipfs_datasets_py.processors.legal_data.open_us_law_embeddings import (
    deterministic_project,
    fixture_embedding_config,
)
from ipfs_datasets_py.processors.legal_data.state_laws_embedding_store import (
    PART_SCHEMA_VERSION,
    build_state_laws_embedding_store,
)


def _cid(character: str) -> str:
    return f"sha256:{character * 64}"


def _rows() -> list[dict[str, object]]:
    return [
        {
            "chunk_cid": _cid(character),
            "parent_entry_cid": _cid(parent),
            "text": f"Official statute body {index} with enough searchable text.",
            "disposition": "admitted",
            "chunk_id": f"or:1:{index}#chunk=0000",
            "legal_id": f"sl:or:1:{index}",
        }
        for index, (character, parent) in enumerate(
            (("a", "d"), ("b", "e"), ("c", "f")), start=1
        )
    ]


def test_partitioned_embedding_store_writes_direct_rows_and_resumes(tmp_path: Path):
    calls: list[int] = []

    def embed(texts):
        calls.append(len(texts))
        return deterministic_project(texts)

    first = build_state_laws_embedding_store(
        _rows(),
        tmp_path,
        jurisdiction_code="OR",
        config=fixture_embedding_config(batch_size=2),
        embedder=embed,
        rows_per_part=2,
    )

    assert first.row_count == 3
    assert first.part_count == 2
    assert first.executed_part_count == 2
    assert first.resumed_part_count == 0
    assert first.production_ready is False
    assert calls == [2, 1]

    table = pq.read_table(tmp_path / "embeddings/jurisdiction=OR/part-000000.parquet")
    assert table.num_rows == 2
    assert {
        "chunk_cid",
        "document_index",
        "embedding",
        "entry_cid",
        "input_hash",
        "model_id",
        "model_revision",
        "parent_entry_cid",
    }.issubset(table.column_names)
    assert table.column("schema_version").to_pylist() == [
        PART_SCHEMA_VERSION,
        PART_SCHEMA_VERSION,
    ]
    assert all(len(vector) == 384 for vector in table.column("embedding").to_pylist())

    def must_not_run(_texts):  # pragma: no cover - assertion is the behavior
        raise AssertionError("a verified embedding part must resume without inference")

    resumed = build_state_laws_embedding_store(
        _rows(),
        tmp_path,
        jurisdiction_code="OR",
        config=fixture_embedding_config(batch_size=2),
        embedder=must_not_run,
        rows_per_part=2,
    )
    assert resumed.resumed_part_count == 2
    assert resumed.executed_part_count == 0


def test_input_hash_change_rebuilds_only_affected_part(tmp_path: Path):
    rows = _rows()
    build_state_laws_embedding_store(
        rows,
        tmp_path,
        jurisdiction_code="OR",
        config=fixture_embedding_config(batch_size=2),
        rows_per_part=2,
    )
    changed = _rows()
    changed[0]["text"] = "Official statute body changed after a fresh scrape."
    result = build_state_laws_embedding_store(
        changed,
        tmp_path,
        jurisdiction_code="OR",
        config=fixture_embedding_config(batch_size=2),
        rows_per_part=2,
    )
    assert result.executed_part_count == 1
    assert result.resumed_part_count == 1
