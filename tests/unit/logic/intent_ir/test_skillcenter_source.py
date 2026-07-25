import hashlib
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.intent_ir import ReviewStatus
from ipfs_datasets_py.logic.intent_ir.source_adapters import (
    SkillCenterBundleReader,
    SkillCenterBundleSchemaError,
    SkillCenterRecordError,
)


def _write_bundle(path: Path, *, oversized: bool = False) -> None:
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
    connection.executemany(
        "INSERT INTO bundle_meta(key, value) VALUES (?, ?)",
        (
            ("bundle_type", "lite"),
            ("created_at", "2026-07-24T00:00:00Z"),
            ("total_skills", "2"),
            ("version", "fixture-v1"),
        ),
    )
    index_rows = (
        (
            "skill-b",
            "security",
            "security",
            "github",
            "https://example.test/b",
            "Skill B",
            3.0,
            "github",
            "en",
            "source-b",
            "primary-b",
        ),
        (
            "skill-a",
            "security",
            "security",
            "github",
            "https://example.test/a",
            "Skill A",
            5.0,
            "github",
            "en",
            "source-a",
            "primary-a",
        ),
    )
    connection.executemany(
        "INSERT INTO skills_index VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        index_rows,
    )
    body_a = "# Skill A\n\nDo not execute this text during ingestion."
    body_b = "x" * 200 if oversized else "# Skill B\n\nA bounded fixture."
    connection.executemany(
        "INSERT INTO skills_content VALUES (?, ?, ?, ?)",
        (
            (
                "skill-a",
                'license_spdx: "MIT"\nlicense_risk: "allow"\n',
                body_a,
                "",
            ),
            (
                "skill-b",
                "license: Complete terms in LICENSE.txt\n",
                body_b,
                "",
            ),
        ),
    )
    connection.commit()
    connection.close()


def test_reader_inspects_and_pages_records_deterministically(tmp_path: Path) -> None:
    path = tmp_path / "bundle.sqlite"
    _write_bundle(path)
    reader = SkillCenterBundleReader(
        path,
        dataset_revision="revision-123",
        repository_file="bundle.sqlite",
    )

    manifest = reader.inspect()
    records = list(reader.iter_records(batch_size=1))

    assert manifest.total_skills == 2
    assert manifest.local_sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    assert [record.skill_id for record in records] == ["skill-a", "skill-b"]
    assert records[0].license_expression == "MIT"
    assert records[0].license_risk == "allow"
    assert records[0].content_sha256 == hashlib.sha256(
        records[0].skill_md.encode("utf-8")
    ).hexdigest()


def test_source_ref_binds_snapshot_bundle_and_skill_body(tmp_path: Path) -> None:
    path = tmp_path / "bundle.sqlite"
    _write_bundle(path)
    record = next(
        SkillCenterBundleReader(
            path,
            dataset_revision="revision-123",
            repository_file="domain bundle.sqlite",
        ).iter_records(limit=1)
    )

    source_ref = record.to_source_ref(
        review_status=ReviewStatus.MACHINE_EXTRACTED
    )
    source_ref.validate()

    assert source_ref.source_revision == "revision-123"
    assert source_ref.container_sha256
    assert "domain%20bundle.sqlite" in source_ref.container_uri
    assert source_ref.review_status is ReviewStatus.MACHINE_EXTRACTED
    assert source_ref.content_cid == record.content_cid

    duplicate_body_from_another_source = replace(
        record,
        skill_id="another-skill",
        source_id="another-source",
        primary_source_id="another-primary",
    )
    assert (
        duplicate_body_from_another_source.to_source_ref().ref_id
        != source_ref.ref_id
    )


def test_entry_cid_is_multiformats_primary_key_independent_of_container(
    tmp_path: Path,
) -> None:
    from multiformats import CID

    path = tmp_path / "bundle.sqlite"
    _write_bundle(path)
    record = next(
        SkillCenterBundleReader(
            path,
            dataset_revision="revision-123",
            repository_file="bundle.sqlite",
        ).iter_records(limit=1)
    )
    repackaged = replace(
        record,
        dataset_revision="revision-456",
        repository_file="repackaged.sqlite",
        bundle_sha256="f" * 64,
    )

    assert repackaged.entry_cid == record.entry_cid
    assert repackaged.entry_identity.multihash_bytes
    decoded = CID.decode(record.entry_cid)
    assert decoded.version == 1
    assert decoded.codec.name == "raw"
    assert decoded.hashfun.name == "sha2-256"
    assert decoded.raw_digest.hex() == record.entry_identity.sha256

    changed = replace(record, title=record.title + " changed")
    assert changed.entry_cid != record.entry_cid


def test_reader_requires_pinned_revision(tmp_path: Path) -> None:
    path = tmp_path / "bundle.sqlite"
    _write_bundle(path)

    with pytest.raises(ValueError, match="dataset_revision"):
        SkillCenterBundleReader(path, dataset_revision="")

    with pytest.raises(ValueError, match="immutable commit"):
        SkillCenterBundleReader(path, dataset_revision="main")


def test_reader_rejects_schema_drift(tmp_path: Path) -> None:
    path = tmp_path / "broken.sqlite"
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE bundle_meta (key TEXT, value TEXT)")
    connection.commit()
    connection.close()

    with pytest.raises(SkillCenterBundleSchemaError, match="Missing SkillCenter"):
        SkillCenterBundleReader(path, dataset_revision="revision-123").inspect()


def test_reader_enforces_text_bounds(tmp_path: Path) -> None:
    path = tmp_path / "bundle.sqlite"
    _write_bundle(path, oversized=True)
    reader = SkillCenterBundleReader(
        path,
        dataset_revision="revision-123",
        max_text_chars=100,
    )

    with pytest.raises(SkillCenterRecordError, match="exceeds max_text_chars"):
        list(reader.iter_records())


def test_reader_filters_by_domain_and_score(tmp_path: Path) -> None:
    path = tmp_path / "bundle.sqlite"
    _write_bundle(path)
    reader = SkillCenterBundleReader(path, dataset_revision="revision-123")

    records = list(
        reader.iter_records(domain="security", minimum_score=4.0)
    )

    assert [record.skill_id for record in records] == ["skill-a"]


def test_reader_rejects_orphaned_bundle_rows(tmp_path: Path) -> None:
    path = tmp_path / "orphaned.sqlite"
    _write_bundle(path)
    connection = sqlite3.connect(path)
    connection.execute(
        "DELETE FROM skills_content WHERE skill_id = ?", ("skill-b",)
    )
    connection.execute(
        "UPDATE bundle_meta SET value = '1' WHERE key = 'total_skills'"
    )
    connection.commit()
    connection.close()

    with pytest.raises(SkillCenterBundleSchemaError, match="row counts disagree"):
        SkillCenterBundleReader(
            path, dataset_revision="revision-123"
        ).inspect()


def test_reader_can_audit_declared_count_mismatch_without_losing_rows(
    tmp_path: Path,
) -> None:
    path = tmp_path / "declared-mismatch.sqlite"
    _write_bundle(path)
    connection = sqlite3.connect(path)
    connection.execute(
        "UPDATE bundle_meta SET value = '99' WHERE key = 'total_skills'"
    )
    connection.commit()
    connection.close()

    reader = SkillCenterBundleReader(
        path,
        dataset_revision="revision-123",
        allow_declared_count_mismatch=True,
    )
    manifest = reader.inspect()

    assert manifest.total_skills == 2
    assert reader.declared_total_skills == 99
    assert len(list(reader.iter_records())) == 2
