"""Country-IR legal search routes terms without storing document bodies."""

from __future__ import annotations

import pytest

import pyarrow as pa
import pyarrow.parquet as pq

from ipfs_datasets_py.ducklake.legal_search_catalog import (
    LegalSearchCatalogError,
    assert_catalog_has_no_bodies,
    load_bm25_term_ranges,
    register_local_country_ir_pins,
    register_local_ir_pins,
    open_legal_search_catalog,
    register_country_ir_catalog,
    register_country_ir_index,
    route_bm25_terms,
)
from ipfs_datasets_py.processors.legal_data.justicedao_release_registry import (
    build_release_registry,
)

_PINS = (
    "justicedao/ipfs_malta_laws_ir",
    "justicedao/ipfs_croatia_laws_ir",
    "justicedao/ipfs_malta_laws-ir",
)
_GOOD_CID = "bafkrei" + ("a" * 44)


def _selected(corpus_id: str):
    releases = build_release_registry(_PINS)
    return next(item for item in releases if item.corpus_id == corpus_id and item.selected)


def test_legal_search_catalog_refuses_control_duckdb(tmp_path) -> None:
    with pytest.raises(LegalSearchCatalogError):
        open_legal_search_catalog(tmp_path / "control.duckdb")
    nested = tmp_path / "nested"
    nested.mkdir()
    with pytest.raises(LegalSearchCatalogError):
        open_legal_search_catalog(nested / "control.duckdb")


def test_two_country_term_ranges_route_without_bodies(tmp_path) -> None:
    malta = _selected("country:malta")
    croatia = _selected("country:croatia")
    hyphen = next(
        item
        for item in build_release_registry(_PINS)
        if item.hf_repo == "justicedao/ipfs_malta_laws-ir"
    )
    connection = open_legal_search_catalog(tmp_path / "legal_search.duckdb")
    try:
        with pytest.raises(LegalSearchCatalogError):
            register_country_ir_catalog(connection, (hyphen,), ())
        counted = register_country_ir_catalog(
            connection,
            (malta, croatia),
            (
                {
                    "corpus_id": "country:malta",
                    "term_low": "act",
                    "term_high": "law",
                    "shard_ordinal": 0,
                    "content_sha256": "ab" * 32,
                    "row_count": 2,
                },
                {
                    "corpus_id": "country:croatia",
                    "term_low": "law",
                    "term_high": "treaty",
                    "shard_ordinal": 3,
                    "content_sha256": "cd" * 32,
                    "row_count": 2,
                },
            ),
            (
                {
                    "corpus_id": "country:malta",
                    "entry_cid": _GOOD_CID,
                    "shard_ordinal": 0,
                },
                {
                    "corpus_id": "country:malta",
                    "entry_cid": "row-1",
                    "shard_ordinal": 0,
                },
            ),
        )
        assert counted == {"ranges": 2, "documents_kept": 1, "documents_omitted": 1}
        assert_catalog_has_no_bodies(connection)
        routes = route_bm25_terms(connection, ("law",))
        assert [(item.corpus_id, item.shard_ordinal) for item in routes] == [
            ("country:croatia", 3),
            ("country:malta", 0),
        ]
        assert all(item.authoritative is False for item in routes)
        assert all(item.ducklake_authoritative is False for item in routes)
        assert all(item.research_only is True for item in routes)
        assert all(not hasattr(item, "body") for item in routes)
        stored = connection.execute("SELECT entry_cid FROM document_index").fetchall()
        assert stored == [(_GOOD_CID,)]
        meta = connection.execute(
            "SELECT authoritative, ducklake_authoritative, quack_attached, research_only "
            "FROM catalog_meta"
        ).fetchone()
        assert meta == (False, False, False, True)
    finally:
        connection.close()


def _write_bm25_index(root, rows: list[dict]) -> None:
    target = root / "indexes" / "bm25_keyword_shards.parquet"
    target.parent.mkdir(parents=True)
    pq.write_table(pa.Table.from_pylist(rows), target)
    body = root / "data" / "bm25" / "postings" / "part-000000.parquet"
    body.parent.mkdir(parents=True)
    body.write_text("SECRET_BODY should never be catalogued", encoding="utf-8")


def test_compact_bm25_index_registers_without_reading_bodies(tmp_path) -> None:
    malta = _selected("country:malta")
    croatia = _selected("country:croatia")
    malta_root = tmp_path / "malta"
    croatia_root = tmp_path / "croatia"
    _write_bm25_index(
        malta_root,
        [
            {
                "first_key": "act",
                "last_key": "law",
                "sha256": "ab" * 32,
                "row_count": 2,
                "shard_id": 0,
                "kind": "bm25_postings",
                "relative_path": "data/bm25/postings/part-000000.parquet",
                "text": "SECRET_BODY",
            }
        ],
    )
    _write_bm25_index(
        croatia_root,
        [
            {
                "first_key": "law",
                "last_key": "treaty",
                "sha256": "cd" * 32,
                "row_count": 2,
                "shard_id": 3,
                "kind": "bm25_postings",
                "relative_path": "data/corpus/part-000000.parquet",
                "text": "SECRET_BODY",
            }
        ],
    )
    connection = open_legal_search_catalog(tmp_path / "legal_search.duckdb")
    try:
        register_country_ir_index(connection, malta, malta_root)
        register_country_ir_index(connection, croatia, croatia_root)
        assert_catalog_has_no_bodies(connection)
        routes = route_bm25_terms(connection, ("law",))
        assert [(item.corpus_id, item.shard_ordinal) for item in routes] == [
            ("country:croatia", 3),
            ("country:malta", 0),
        ]
        stored = connection.execute(
            "SELECT content_sha256 FROM shard_locator ORDER BY content_sha256"
        ).fetchall()
        assert stored == [(("ab" * 32),), (("cd" * 32),)]
        dumped = str(connection.execute("SELECT * FROM shard_locator").fetchall())
        dumped += str(connection.execute("SELECT * FROM bm25_term_range").fetchall())
        assert "SECRET_BODY" not in dumped
        assert "data/" not in dumped
    finally:
        connection.close()


def test_compact_bm25_index_rejects_missing_or_wrong_kind(tmp_path) -> None:
    malta = _selected("country:malta")
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(LegalSearchCatalogError):
        load_bm25_term_ranges(empty, malta.corpus_id)
    indexed = tmp_path / "wrong-kind"
    _write_bm25_index(
        indexed,
        [
            {
                "first_key": "act",
                "last_key": "law",
                "sha256": "ab" * 32,
                "row_count": 2,
                "shard_id": 0,
                "kind": "corpus",
            }
        ],
    )
    with pytest.raises(LegalSearchCatalogError):
        load_bm25_term_ranges(indexed, malta.corpus_id)


def test_local_checkouts_register_one_selected_pin_at_a_time(tmp_path) -> None:
    dataset_ids = (
        "justicedao/ipfs_malta_laws_ir",
        "justicedao/ipfs_croatia_laws_ir",
        "justicedao/ipfs_germany_laws_ir",
        "justicedao/ipfs_france_laws_ir",
        "justicedao/ipfs_malta_laws-ir",
        "justicedao/ipfs_uscode",
    )
    releases = build_release_registry(dataset_ids)
    checkouts = tmp_path / "checkouts"
    _write_bm25_index(
        checkouts / "ipfs_malta_laws_ir",
        [
            {
                "first_key": "act",
                "last_key": "law",
                "sha256": "ab" * 32,
                "row_count": 2,
                "shard_id": 0,
                "kind": "bm25_postings",
                "relative_path": "data/bm25/postings/part-000000.parquet",
                "text": "SECRET_BODY",
            }
        ],
    )
    _write_bm25_index(
        checkouts / "ipfs_croatia_laws_ir",
        [
            {
                "first_key": "law",
                "last_key": "treaty",
                "sha256": "cd" * 32,
                "row_count": 2,
                "shard_id": 3,
                "kind": "bm25_postings",
            }
        ],
    )
    (checkouts / "ipfs_germany_laws_ir").mkdir(parents=True)
    (checkouts / "ipfs_germany_laws_ir" / "data").mkdir()
    (checkouts / "ipfs_germany_laws_ir" / "data" / "body.txt").write_text(
        "SECRET_BODY",
        encoding="utf-8",
    )
    _write_bm25_index(
        checkouts / "ipfs_malta_laws-ir",
        [
            {
                "first_key": "act",
                "last_key": "zzz",
                "sha256": "ef" * 32,
                "row_count": 1,
                "shard_id": 9,
                "kind": "bm25_postings",
            }
        ],
    )
    connection = open_legal_search_catalog(tmp_path / "legal_search.duckdb")
    try:
        results = register_local_country_ir_pins(connection, releases, checkouts)
        by_repo = {item.hf_repo: item for item in results}
        assert by_repo["justicedao/ipfs_croatia_laws_ir"].status == "registered"
        assert by_repo["justicedao/ipfs_croatia_laws_ir"].ranges == 1
        assert by_repo["justicedao/ipfs_malta_laws_ir"].status == "registered"
        assert by_repo["justicedao/ipfs_germany_laws_ir"].status == "missing_index"
        assert by_repo["justicedao/ipfs_france_laws_ir"].status == "not_checked_out"
        assert by_repo["justicedao/ipfs_malta_laws-ir"].status == "skipped"
        assert by_repo["justicedao/ipfs_uscode"].status == "skipped"
        stored = {
            row[0]
            for row in connection.execute("SELECT hf_repo FROM corpus_release").fetchall()
        }
        assert stored == {
            "justicedao/ipfs_croatia_laws_ir",
            "justicedao/ipfs_malta_laws_ir",
        }
        routes = route_bm25_terms(connection, ("law",))
        assert [item.corpus_id for item in routes] == [
            "country:croatia",
            "country:malta",
        ]
        dumped = str(connection.execute("SELECT * FROM bm25_term_range").fetchall())
        assert "SECRET_BODY" not in dumped
        assert "ef" * 32 not in str(
            connection.execute("SELECT content_sha256 FROM shard_locator").fetchall()
        )
    finally:
        connection.close()


def _index(root, repo: str, low: str, high: str, ordinal: int, digest: str) -> None:
    _write_bm25_index(
        root / repo,
        [
            {
                "first_key": low,
                "last_key": high,
                "sha256": digest,
                "row_count": 2,
                "shard_id": ordinal,
                "kind": "bm25_postings",
                "relative_path": "data/bm25/postings/part.parquet",
                "text": "SECRET_BODY",
            }
        ],
    )


def test_local_publicus_and_patent_pins_use_the_same_compact_index(tmp_path) -> None:
    dataset_ids = (
        "justicedao/ipfs_uscode",
        "justicedao/ipfs_state_laws",
        "justicedao/open-us-law-sparse-graphrag",
        "justicedao/federal-register-full-graphrag-v20260810",
        "justicedao/ipfs_federal_register",
        "justicedao/patent-legal-ir-graphrag",
        "justicedao/patent-legal-bm25",
        "justicedao/ipfs_court_rules",
    )
    releases = build_release_registry(dataset_ids)
    checkouts = tmp_path / "checkouts"
    _index(checkouts, "ipfs_uscode", "section", "section", 0, "11" * 32)
    _index(checkouts, "ipfs_state_laws", "section", "section", 1, "22" * 32)
    _index(checkouts, "open-us-law-sparse-graphrag", "ordinance", "ordinance", 2, "33" * 32)
    _index(checkouts, "federal-register-full-graphrag-v20260810", "register", "register", 4, "44" * 32)
    _index(checkouts, "ipfs_federal_register", "register", "zzz", 8, "55" * 32)
    _index(checkouts, "patent-legal-ir-graphrag", "mpep", "mpep", 5, "66" * 32)
    _index(checkouts, "patent-legal-bm25", "claim", "zzz", 9, "77" * 32)
    _index(checkouts, "ipfs_court_rules", "rule", "rule", 6, "88" * 32)
    connection = open_legal_search_catalog(tmp_path / "legal_search.duckdb")
    try:
        results = register_local_ir_pins(connection, releases, checkouts)
        by_repo = {item.hf_repo: item.status for item in results}
        assert by_repo["justicedao/ipfs_uscode"] == "registered"
        assert by_repo["justicedao/ipfs_state_laws"] == "registered"
        assert by_repo["justicedao/open-us-law-sparse-graphrag"] == "registered"
        assert by_repo["justicedao/federal-register-full-graphrag-v20260810"] == "registered"
        assert by_repo["justicedao/patent-legal-ir-graphrag"] == "registered"
        assert by_repo["justicedao/ipfs_federal_register"] == "skipped"
        assert by_repo["justicedao/patent-legal-bm25"] == "skipped"
        assert by_repo["justicedao/ipfs_court_rules"] == "skipped"
        stored = {
            row[0]
            for row in connection.execute("SELECT hf_repo FROM corpus_release").fetchall()
        }
        assert stored == {
            "justicedao/ipfs_uscode",
            "justicedao/ipfs_state_laws",
            "justicedao/open-us-law-sparse-graphrag",
            "justicedao/federal-register-full-graphrag-v20260810",
            "justicedao/patent-legal-ir-graphrag",
        }
        section = [item.corpus_id for item in route_bm25_terms(connection, ("section",))]
        assert section == ["us:code", "us:state-statutes"]
        assert [item.corpus_id for item in route_bm25_terms(connection, ("mpep",))] == [
            "us:patent"
        ]
        assert [item.corpus_id for item in route_bm25_terms(connection, ("register",))] == [
            "us:federal-register"
        ]
        hashes = {
            row[0]
            for row in connection.execute("SELECT content_sha256 FROM shard_locator").fetchall()
        }
        assert "55" * 32 not in hashes
        assert "77" * 32 not in hashes
        assert "88" * 32 not in hashes
        dumped = str(connection.execute("SELECT * FROM bm25_term_range").fetchall())
        assert "SECRET_BODY" not in dumped
        assert "data/" not in dumped
        assert all(item.research_only is True for item in route_bm25_terms(connection, ("section",)))
    finally:
        connection.close()
