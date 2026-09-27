"""Legacy municipal, Caselaw, and capped Netherlands adapters."""

from __future__ import annotations

import pyarrow as pa
import pyarrow.parquet as pq

from ipfs_datasets_py.ducklake.legal_search_catalog import (
    assert_catalog_has_no_bodies,
    open_legal_search_catalog,
    register_ir_catalog,
)
from ipfs_datasets_py.ducklake.legal_search_legacy import (
    lookup_legacy_alias,
    register_legacy_pins,
    vector_spaces_for,
)
from ipfs_datasets_py.processors.legal_data.justicedao_release_registry import (
    build_release_registry,
)

_CID = "bafkrei" + ("a" * 44)
_OTHER = "bafkrei" + ("b" * 44)
_IDS = (
    "justicedao/american_municipal_law",
    "justicedao/ipfs_caselaw_access_project",
    "justicedao/dedup_ipfs_caselaw_access_project",
    "justicedao/Caselaw_Access_Project_embeddings",
    "justicedao/ipfs_netherlands_laws_ir",
    "justicedao/ipfs_netherlands_laws",
    "justicedao/ipfs_court_rules",
)


def _write(root, name: str, rows: list[dict]) -> None:
    target = root / "indexes" / name
    target.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows), target)
    body = root / "data" / "body.txt"
    body.parent.mkdir(parents=True, exist_ok=True)
    body.write_text("SECRET_BODY", encoding="utf-8")


def test_legacy_pins_keep_vector_spaces_apart_and_cap_unmatched_dutch_ids(tmp_path) -> None:
    releases = build_release_registry(_IDS)
    by_repo = {item.hf_repo: item for item in releases}
    checkouts = tmp_path / "checkouts"
    _write(
        checkouts / "american_municipal_law",
        "subsection_cids.parquet",
        [{"cid": _CID, "html": "SECRET_BODY", "embedding": [0.1, 0.2]}],
    )
    _write(
        checkouts / "ipfs_caselaw_access_project",
        "opinion_cids.parquet",
        [{"cid": _CID, "text": "SECRET_BODY"}, {"cid": "not-a-cid", "text": "SECRET_BODY"}],
    )
    _write(
        checkouts / "Caselaw_Access_Project_embeddings",
        "centroids.parquet",
        [
            {
                "vector_space_id": "thenlper/gte-small:384",
                "centroid_id": "c0",
                "shard_id": 0,
                "embedding": [0.1],
            },
            {
                "vector_space_id": "Alibaba-NLP/gte-large-en-v1.5:1024",
                "centroid_id": "c1",
                "shard_id": 1,
                "embedding": [0.2],
            },
            {
                "vector_space_id": "Alibaba-NLP/gte-Qwen2-1.5B-instruct:1536",
                "centroid_id": "c2",
                "shard_id": 2,
                "embedding": [0.3],
            },
        ],
    )
    _write(
        checkouts / "ipfs_netherlands_laws",
        "bwbr_alias.parquet",
        [
            {"bwbr_id": "BWBR0002656", "entry_cid": _CID, "text": "SECRET_BODY"},
            {"bwbr_id": "BWBR0000002", "entry_cid": _OTHER, "text": "SECRET_BODY"},
        ],
    )
    connection = open_legal_search_catalog(tmp_path / "legal_search.duckdb")
    try:
        register_ir_catalog(
            connection,
            (by_repo["justicedao/ipfs_netherlands_laws_ir"],),
            (
                {
                    "corpus_id": "country:netherlands",
                    "term_low": "wet",
                    "term_high": "wet",
                    "shard_ordinal": 0,
                    "content_sha256": "ab" * 32,
                    "row_count": 1,
                },
            ),
            ({"corpus_id": "country:netherlands", "entry_cid": _CID, "shard_ordinal": 0},),
        )
        results = register_legacy_pins(connection, releases, checkouts)
        status = {item.hf_repo: item.status for item in results}
        assert status["justicedao/american_municipal_law"] == "registered"
        assert status["justicedao/ipfs_caselaw_access_project"] == "registered"
        assert status["justicedao/Caselaw_Access_Project_embeddings"] == "registered"
        assert status["justicedao/ipfs_netherlands_laws"] == "capped"
        assert status["justicedao/dedup_ipfs_caselaw_access_project"] == "skipped"
        assert status["justicedao/ipfs_court_rules"] == "skipped"
        assert vector_spaces_for(connection, "us:municipal") == (
            ("openai:text-embedding-3-small:1536", False),
        )
        assert set(vector_spaces_for(connection, "us:caselaw-embeddings")) == {
            ("Alibaba-NLP/gte-Qwen2-1.5B-instruct:1536", False),
            ("Alibaba-NLP/gte-large-en-v1.5:1024", False),
            ("thenlper/gte-small:384", False),
        }
        assert lookup_legacy_alias(connection, "BWBR0002656") == (_CID,)
        assert lookup_legacy_alias(connection, "BWBR0000002") == ()
        assert_catalog_has_no_bodies(connection)
        dumped = str(connection.execute("SELECT * FROM document_index").fetchall())
        dumped += str(connection.execute("SELECT * FROM vector_centroid").fetchall())
        dumped += str(connection.execute("SELECT * FROM legacy_alias").fetchall())
        assert "SECRET_BODY" not in dumped
        assert "data/" not in dumped
    finally:
        connection.close()
