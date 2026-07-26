from __future__ import annotations

import sqlite3
from pathlib import Path

import pyarrow.parquet as parquet
import pytest

from ipfs_datasets_py.logic.intent_ir.graphrag.skillcenter_bm25 import (
    SkillCenterBM25Config,
    SkillCenterBM25Error,
    SkillCenterBM25Index,
    build_skillcenter_bm25_index,
)
from ipfs_datasets_py.logic.intent_ir.source_adapters.skillcenter import (
    SkillCenterBundleReader,
)


def _write_bundle(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE bundle_meta (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE skills_index (
            skill_id TEXT PRIMARY KEY,
            domain TEXT,
            profile TEXT,
            source_type TEXT,
            source_url TEXT,
            title TEXT,
            overall_score REAL,
            skill_kind TEXT,
            language TEXT,
            source_id TEXT,
            primary_source_id TEXT
        );
        CREATE TABLE skills_content (
            skill_id TEXT PRIMARY KEY,
            metadata_yaml TEXT,
            skill_md TEXT,
            library_md TEXT
        );
        """
    )
    rows = (
        (
            "skill-alpha",
            "Rotate API credentials",
            "# Rotate\n\nRotate an API credential and verify the new key.",
            True,
        ),
        (
            "skill-beta",
            "API key verification",
            "# Verify\n\nVerify an API key after secure rotation.",
            True,
        ),
        (
            "skill-gamma",
            "Render an image",
            "# Render\n\nCreate a raster image with a transparent background.",
            True,
        ),
        (
            "skill-quarantined",
            "Unknown terms",
            "# Unknown\n\nThis source has no declared license.",
            False,
        ),
    )
    connection.executemany(
        "INSERT INTO bundle_meta(key, value) VALUES (?, ?)",
        (
            ("bundle_type", "lite"),
            ("created_at", "2026-07-25T00:00:00Z"),
            ("total_skills", str(len(rows))),
            ("version", "fixture-v1"),
        ),
    )
    for index, (skill_id, title, body, allowed) in enumerate(rows):
        connection.execute(
            "INSERT INTO skills_index VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                skill_id,
                "security",
                "security",
                "github",
                f"https://example.test/{skill_id}",
                title,
                5.0 - index,
                "skill-md",
                "en",
                f"source-{skill_id}",
                f"primary-{skill_id}",
            ),
        )
        connection.execute(
            "INSERT INTO skills_content VALUES (?, ?, ?, ?)",
            (
                skill_id,
                (
                    "license_spdx: MIT\nlicense_risk: allow\n"
                    if allowed
                    else "description: no declared license\n"
                ),
                body,
                "",
            ),
        )
    connection.commit()
    connection.close()


def _reader(tmp_path: Path) -> SkillCenterBundleReader:
    path = tmp_path / "security.sqlite"
    _write_bundle(path)
    return SkillCenterBundleReader(
        path,
        dataset_id="example/skillcenter",
        dataset_revision="revision-123",
        repository_file="security.sqlite",
    )


def test_build_load_and_search_persisted_bag_of_words(tmp_path: Path) -> None:
    reader = _reader(tmp_path)
    output = tmp_path / "bm25"
    summary = build_skillcenter_bm25_index(
        (reader,),
        output_dir=output,
    )
    index = SkillCenterBM25Index.load(output)
    hits = index.search("rotate API credential and verify", k=2)

    assert summary.source_records == 4
    assert summary.indexed_skills == 3
    assert summary.vocabulary_size > 10
    assert summary.posting_count > summary.vocabulary_size
    assert index.summary == summary
    assert {hit.skill_id for hit in hits} == {"skill-alpha", "skill-beta"}
    assert all(hit.score > 0 for hit in hits)
    assert all(hit.proof_authority is False for hit in hits)
    assert "credential" in hits[0].matched_terms

    neighbors = index.skill_neighbors("skill-alpha", k=2)
    assert neighbors[0].skill_id == "skill-beta"
    assert all(hit.skill_id != "skill-alpha" for hit in neighbors)

    for filename in ("documents.parquet", "terms.parquet", "postings.parquet"):
        columns = set(parquet.read_schema(output / filename).names)
        assert not {
            "skill_md",
            "library_md",
            "metadata_yaml",
            "text",
        } & columns


def test_existing_bm25_is_reused_and_drift_is_rejected(tmp_path: Path) -> None:
    reader = _reader(tmp_path)
    output = tmp_path / "bm25"
    first = build_skillcenter_bm25_index((reader,), output_dir=output)
    second = build_skillcenter_bm25_index((reader,), output_dir=output)
    assert first == second

    with pytest.raises(SkillCenterBM25Error, match="different inputs"):
        build_skillcenter_bm25_index(
            (reader,),
            output_dir=output,
            config=SkillCenterBM25Config(k1=1.2),
        )


def test_bm25_load_rejects_tampered_postings(tmp_path: Path) -> None:
    reader = _reader(tmp_path)
    output = tmp_path / "bm25"
    build_skillcenter_bm25_index((reader,), output_dir=output)
    postings = output / "postings.parquet"
    postings.write_bytes(postings.read_bytes() + b"tampered")

    with pytest.raises(SkillCenterBM25Error, match="descriptor"):
        SkillCenterBM25Index.load(output)
