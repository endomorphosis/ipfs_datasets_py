"""Legacy migration scripts stage compact indexes and do not copy bodies."""

from __future__ import annotations

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ipfs_datasets_py.ducklake.legal_search_catalog import open_legal_search_catalog
from ipfs_datasets_py.ducklake.legal_search_legacy import (
    lookup_legacy_alias,
    register_legacy_pins,
    vector_spaces_for,
)
from ipfs_datasets_py.processors.legal_data.justicedao_release_registry import (
    build_release_registry,
)
from ipfs_datasets_py.processors.legal_data.legacy_migration import (
    LegacyMigrationError,
    plan_legacy_migration,
    stage_caselaw,
    stage_municipal,
    stage_netherlands,
)

_CID = "bafkrei" + ("a" * 44)
_OTHER = "bafkrei" + ("b" * 44)


def _write(path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows), path)


def _fixture(root) -> None:
    municipal = root / "american_municipal_law"
    _write(
        municipal / "town_html.parquet",
        [{"cid": _CID, "html": "SECRET_BODY"}],
    )
    _write(
        municipal / "town_citation.parquet",
        [{"cid": _CID, "bluebook_citation": "Town Code sec. 1", "html": "SECRET_BODY"}],
    )
    _write(
        municipal / "town_embeddings.parquet",
        [{"cid": _CID, "embedding": [0.2, 0.3]}],
    )
    _write(
        root / "ipfs_caselaw_access_project" / "opinions.parquet",
        [{"cid": _CID, "text": "SECRET_BODY"}],
    )
    _write(
        root / "dedup_ipfs_caselaw_access_project" / "opinions.parquet",
        [{"cid": _OTHER, "id": "dedup-only"}],
    )
    _write(
        root / "Caselaw_Access_Project_embeddings" / "gte-small_centroids.parquet",
        [{"centroid_id": "c0", "shard_id": 0, "embedding": [0.1, 0.2]}],
    )
    _write(
        root / "ipfs_netherlands_laws" / "laws.parquet",
        [
            {"bwbr_id": "BWBR0002656", "cid": _CID, "text": "SECRET_BODY"},
            {"bwbr_id": "BWBR0000002", "cid": _OTHER, "text": "SECRET_BODY"},
        ],
    )


def test_plan_is_dry_and_caselaw_pin_stays_unresolved(tmp_path) -> None:
    _fixture(tmp_path)
    report = plan_legacy_migration(tmp_path)
    assert report["executed_migration"] is False
    assert report["authoritative"] is False
    assert report["municipal"]["decision"] == "ready_to_stage"
    assert report["municipal"]["cid_count"] == 1
    assert report["municipal"]["fuse_with_bm25"] is False
    assert report["caselaw_text"]["decision"] == "unresolved_duplicate"
    assert report["caselaw_embeddings"]["decision"] == "ready_to_stage"
    assert report["caselaw_embeddings"]["spaces"] == ["thenlper/gte-small:384"]
    assert report["netherlands"]["bwbr_count"] == 2
    assert report["netherlands"]["published_cap"] == "5000 of 42956 BWBR identifiers"


def test_apply_writes_indexes_without_bodies_and_refuses_unresolved_text(tmp_path) -> None:
    _fixture(tmp_path)
    dry = stage_municipal(tmp_path / "american_municipal_law", tmp_path / "staged", apply=False)
    assert dry["bodies_written"] is False
    assert dry["output"] is None
    assert not (tmp_path / "staged").exists()
    staged = stage_municipal(tmp_path / "american_municipal_law", tmp_path / "staged", apply=True)
    municipal_index = tmp_path / "staged" / "american_municipal_law" / "indexes" / "subsection_cids.parquet"
    names = set(pq.read_schema(municipal_index).names)
    assert names == {"cid"}
    assert "SECRET_BODY" not in municipal_index.read_bytes().decode("utf-8", "ignore")
    with pytest.raises(LegacyMigrationError):
        stage_caselaw(tmp_path, tmp_path / "staged", apply=True)
    caselaw = stage_caselaw(
        tmp_path,
        tmp_path / "staged",
        apply=True,
        text_pin="ipfs_caselaw_access_project",
    )
    assert caselaw["bodies_written"] is False
    centroid = (
        tmp_path / "staged" / "Caselaw_Access_Project_embeddings" / "indexes" / "centroids.parquet"
    )
    assert "embedding" not in pq.read_schema(centroid).names
    dutch = stage_netherlands(
        tmp_path / "ipfs_netherlands_laws",
        [_CID],
        tmp_path / "staged",
        apply=True,
    )
    assert dutch["linked"] == 1
    assert dutch["capped"] == 1
    releases = build_release_registry(
        (
            "justicedao/american_municipal_law",
            "justicedao/ipfs_caselaw_access_project",
            "justicedao/Caselaw_Access_Project_embeddings",
            "justicedao/ipfs_netherlands_laws",
            "justicedao/ipfs_netherlands_laws_ir",
        )
    )
    connection = open_legal_search_catalog(tmp_path / "legal_search.duckdb")
    try:
        from ipfs_datasets_py.ducklake.legal_search_catalog import register_ir_catalog

        ir = next(item for item in releases if item.hf_repo.endswith("ipfs_netherlands_laws_ir"))
        register_ir_catalog(
            connection,
            (ir,),
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
        register_legacy_pins(connection, releases, tmp_path / "staged")
        assert vector_spaces_for(connection, "us:municipal") == (
            ("openai:text-embedding-3-small:1536", False),
        )
        assert lookup_legacy_alias(connection, "BWBR0002656") == (_CID,)
        assert lookup_legacy_alias(connection, "BWBR0000002") == ()
    finally:
        connection.close()
