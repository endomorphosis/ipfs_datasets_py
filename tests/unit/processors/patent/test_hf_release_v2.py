"""Unit tests for deterministic JusticeDAO patent HF release packaging v2."""

from __future__ import annotations

import hashlib
import inspect
import io
import json
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from ipfs_datasets_py.processors.domains.patent import hf_release_v2 as hf_mod
from ipfs_datasets_py.processors.domains.patent.hf_layout_v2 import (
    ORGANIZATION,
    README_FILENAME,
)
from ipfs_datasets_py.processors.domains.patent.hf_release_v2 import (
    HF_RELEASE_V2_SCHEMA_VERSION,
    QUALITY_REPORT_FILENAME,
    RELEASE_MANIFEST_FILENAME,
    FieldPartition,
    OrphanJoinError,
    PatentHFReleaseV2Error,
    PatentLegalHFReleaseBuilderV2,
    PatentReleaseSafetyError,
    PrivacyReview,
    ReleaseRowV2,
    build_patent_hf_release_v2,
    releases_are_byte_identical,
    stage_patent_hf_release_v2,
    validate_patent_hf_release_v2,
)
from ipfs_datasets_py.processors.domains.patent.release_policy import (
    RightsReview,
    RightsReviewStatus,
    SourceLineage,
)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _lineage(
    *,
    source_id: str = "govinfo/uscode",
    revision: str = "2024-title-35",
    uri: str = "https://www.govinfo.gov/app/details/USCODE-2024-title35",
    body: str = "uscode-2024-title35",
) -> SourceLineage:
    return SourceLineage(
        source_id=source_id,
        source_revision=revision,
        source_uri=uri,
        source_sha256=_sha(body),
        authority="official",
    )


def _rights() -> RightsReview:
    return RightsReview(
        license_expression="public-domain-US-government",
        review_status=RightsReviewStatus.REVIEWED,
        reviewed_by="patent-legal-governance",
        reviewed_at="2026-08-01T00:00:00Z",
        redistribution_allowed=True,
    )


def _privacy() -> PrivacyReview:
    return PrivacyReview(
        review_status="reviewed",
        reviewed_by="patent-legal-privacy",
        reviewed_at="2026-08-01T00:00:00Z",
        privacy_class="public",
    )


def _row(
    *,
    record_id: str,
    config_name: str,
    authoritative: dict | None = None,
    ai_derived: dict | None = None,
    corpus_record_id: str = "",
    source_cid: str = "",
    lineage: SourceLineage | None = None,
    classification: str = "public_official",
    node_id: str = "",
    src_node_id: str = "",
    dst_node_id: str = "",
    document_id: str = "",
    term: str = "",
) -> ReleaseRowV2:
    return ReleaseRowV2(
        record_id=record_id,
        config_name=config_name,
        classification=classification,
        source_lineage=lineage or _lineage(),
        rights_review=_rights(),
        privacy_review=_privacy(),
        fields=FieldPartition(
            authoritative=authoritative or {"text": f"body-{record_id}"},
            ai_derived=ai_derived or {},
        ),
        source_cid=source_cid,
        corpus_record_id=corpus_record_id,
        node_id=node_id,
        src_node_id=src_node_id,
        dst_node_id=dst_node_id,
        document_id=document_id,
        term=term,
    )


def _public_rows() -> list[ReleaseRowV2]:
    usc = _row(
        record_id="usc:35:101",
        config_name="usc",
        authoritative={
            "citation": "35 U.S.C. § 101",
            "text": "Whoever invents or discovers any new and useful process...",
        },
    )
    claims = _row(
        record_id="claim:US7654321B2:1",
        config_name="claims",
        authoritative={"claim_number": 1, "text": "A system comprising a processor..."},
        lineage=_lineage(
            source_id="uspto/public-pair",
            revision="grant-2020-01-01",
            uri="https://data.uspto.gov/apis/patent-file-wrapper",
            body="uspto-grant-2020",
        ),
        ai_derived={"embedding_hint": "processor system claim"},
    )
    vector = _row(
        record_id="vec:claim:US7654321B2:1",
        config_name="vectors",
        corpus_record_id=claims.record_id,
        source_cid=claims.source_cid,
        authoritative={
            "model_id": "patent-legal-minilm/v2",
            "model_revision": "rev-2026-08-01",
            "embedding_dim": 384,
            "has_embedding": True,
        },
        ai_derived={"embedding_norm": 1.0},
        lineage=claims.source_lineage,
    )
    bm25_doc = _row(
        record_id="bm25doc:claim:US7654321B2:1",
        config_name="bm25_documents",
        corpus_record_id=claims.record_id,
        source_cid=claims.source_cid,
        authoritative={"text_preview": "A system comprising", "token_count": 4},
        lineage=claims.source_lineage,
    )
    bm25_post = _row(
        record_id="bm25post:system",
        config_name="bm25_postings",
        document_id=bm25_doc.record_id,
        term="system",
        source_cid=claims.source_cid,
        authoritative={"tf": 1, "df": 1},
        lineage=claims.source_lineage,
    )
    node_a = _row(
        record_id="node:US7654321B2",
        config_name="graph_nodes",
        node_id="node:US7654321B2",
        source_cid=claims.source_cid,
        authoritative={"label": "US7654321B2", "kind": "patent"},
        lineage=claims.source_lineage,
    )
    node_b = _row(
        record_id="node:US1234567A",
        config_name="graph_nodes",
        node_id="node:US1234567A",
        source_cid=claims.source_cid,
        authoritative={"label": "US1234567A", "kind": "patent"},
        lineage=claims.source_lineage,
    )
    edge = _row(
        record_id="edge:cites:1",
        config_name="graph_edges",
        src_node_id="node:US7654321B2",
        dst_node_id="node:US1234567A",
        source_cid=claims.source_cid,
        authoritative={"relation": "cites"},
        lineage=claims.source_lineage,
    )
    return [usc, claims, vector, bm25_doc, bm25_post, node_a, node_b, edge]


# ---------------------------------------------------------------------------
# Byte stability
# ---------------------------------------------------------------------------


def test_two_builds_are_byte_identical() -> None:
    rows = _public_rows()
    first = build_patent_hf_release_v2(rows, dry_run=True)
    second = build_patent_hf_release_v2(rows, dry_run=True)

    assert releases_are_byte_identical(first, second)
    assert first.release_root_cid == second.release_root_cid
    assert first.source_root_cid == second.source_root_cid
    assert first.index_root_cid == second.index_root_cid
    assert first.layout_bundle_cid == second.layout_bundle_cid
    assert first.manifest_dict() == second.manifest_dict()
    for left, right in zip(first.artifacts, second.artifacts, strict=True):
        assert left.content == right.content
        assert left.sha256 == right.sha256
        assert left.content_cid == right.content_cid


# ---------------------------------------------------------------------------
# Counts / CIDs agree across projections
# ---------------------------------------------------------------------------


def test_counts_and_cids_agree_across_projections() -> None:
    release = build_patent_hf_release_v2(_public_rows(), dry_run=True)
    validation = validate_patent_hf_release_v2(release)

    assert validation["valid"] is True
    manifest = release.manifest_dict()
    quality = release.quality_report_dict()

    assert manifest["config_row_counts"] == dict(release.config_row_counts)
    assert quality["config_row_counts"] == dict(release.config_row_counts)
    assert manifest["total_data_rows"] == release.total_row_count
    assert quality["total_data_rows"] == release.total_row_count
    assert manifest["release_root_cid"] == release.release_root_cid
    assert manifest["source_root_cid"] == release.source_root_cid
    assert manifest["index_root_cid"] == release.index_root_cid
    assert manifest["evaluation_root_cid"] == release.evaluation_root_cid
    assert manifest["layout_bundle_cid"] == release.layout_bundle_cid

    # Vector/BM25/graph rows + synthesized chunk indexes.
    assert release.config_row_counts["usc"] == 1
    assert release.config_row_counts["claims"] == 1
    assert release.config_row_counts["vectors"] == 1
    assert release.config_row_counts["vector_chunk_index"] == 1
    assert release.config_row_counts["bm25_documents"] == 1
    assert release.config_row_counts["bm25_postings"] == 1
    assert release.config_row_counts["graph_nodes"] == 2
    assert release.config_row_counts["graph_edges"] == 1
    assert release.config_row_counts["graph_node_chunk_index"] == 1
    assert release.config_row_counts["graph_edge_chunk_index"] == 1

    for repo in release.repositories:
        entry = next(
            item
            for item in manifest["repositories"]
            if item["repository"] == repo.repository
        )
        assert entry["repo_root_cid"] == repo.repo_root_cid
        assert entry["total_row_count"] == repo.total_row_count


# ---------------------------------------------------------------------------
# Orphan joins
# ---------------------------------------------------------------------------


def test_orphan_vector_join_rejected() -> None:
    rows = _public_rows()
    orphan = _row(
        record_id="vec:orphan",
        config_name="vectors",
        corpus_record_id="missing:corpus:id",
        authoritative={"model_id": "x", "embedding_dim": 8},
    )
    with pytest.raises(OrphanJoinError, match="orphan"):
        build_patent_hf_release_v2([*rows, orphan], dry_run=True)


def test_orphan_graph_edge_rejected() -> None:
    rows = [r for r in _public_rows() if r.config_name != "graph_edges"]
    bad_edge = _row(
        record_id="edge:orphan",
        config_name="graph_edges",
        src_node_id="node:US7654321B2",
        dst_node_id="node:DOES-NOT-EXIST",
        source_cid=rows[-1].source_cid,
        authoritative={"relation": "cites"},
        lineage=rows[-1].source_lineage,
    )
    with pytest.raises(OrphanJoinError, match="orphan"):
        build_patent_hf_release_v2([*rows, bad_edge], dry_run=True)


def test_quality_report_records_zero_orphans() -> None:
    release = build_patent_hf_release_v2(_public_rows(), dry_run=True)
    quality = release.quality_report_dict()
    assert quality["orphan_check"] == "pass"
    assert quality["orphan_joins"] == 0


# ---------------------------------------------------------------------------
# Authoritative vs AI-derived separation
# ---------------------------------------------------------------------------


def test_authoritative_and_ai_derived_remain_separate() -> None:
    with pytest.raises(PatentHFReleaseV2Error, match="remain separate"):
        FieldPartition(
            authoritative={"text": "official", "score": 1},
            ai_derived={"score": 0.9},
        )

    release = build_patent_hf_release_v2(_public_rows(), dry_run=True)
    quality = release.quality_report_dict()
    assert quality["field_authority_separated"] is True
    assert quality["field_key_overlap"] == []

    # Parquet columns keep partitions distinct.
    claims_repo = release.repository_for_role("corpus")
    claims_art = next(
        a
        for a in claims_repo.artifacts
        if a.config_name == "claims" and a.relative_path.endswith(".parquet")
    )
    table = pq.read_table(io.BytesIO(claims_art.content))
    assert "authoritative_json" in table.schema.names
    assert "ai_derived_json" in table.schema.names
    for row in table.to_pylist():
        auth = json.loads(row["authoritative_json"])
        derived = json.loads(row["ai_derived_json"])
        assert set(auth).isdisjoint(set(derived))
        # AI fields must not appear inside the authoritative object.
        assert "ai_derived" not in auth
        assert "authoritative" not in derived


# ---------------------------------------------------------------------------
# Rights / privacy / source review on every artifact
# ---------------------------------------------------------------------------


def test_every_artifact_carries_rights_privacy_source_review() -> None:
    release = build_patent_hf_release_v2(_public_rows(), dry_run=True)
    assert release.schema_version == HF_RELEASE_V2_SCHEMA_VERSION
    assert release.organization == ORGANIZATION

    for artifact in release.artifacts:
        desc = artifact.descriptor()
        assert desc["sha256"] and len(desc["sha256"]) == 64
        assert desc["content_cid"].startswith("b")
        assert isinstance(desc["source_lineage"], list) and desc["source_lineage"]
        assert isinstance(desc["rights_reviews"], list) and desc["rights_reviews"]
        assert isinstance(desc["privacy_reviews"], list) and desc["privacy_reviews"]
        for rights in desc["rights_reviews"]:
            assert rights["review_status"] == "reviewed"
            assert rights["redistribution_allowed"] is True
        for privacy in desc["privacy_reviews"]:
            assert privacy["review_status"] == "reviewed"
            assert privacy["privacy_class"] == "public"
        for lineage in desc["source_lineage"]:
            assert lineage["source_sha256"]
            assert lineage["source_id"]

    manifest = release.manifest_dict()
    assert manifest["uses_hf_api_upload_file"] is False
    assert manifest["upload_path"] is None
    assert manifest["dry_run"] is True
    assert RELEASE_MANIFEST_FILENAME in {
        a.relative_path for a in release.support_artifacts
    }
    assert QUALITY_REPORT_FILENAME in {
        a.relative_path for a in release.support_artifacts
    }

    # Multi-repo layout cards present.
    corpus = release.repository_for_role("corpus")
    assert any(a.relative_path == README_FILENAME for a in corpus.artifacts)


# ---------------------------------------------------------------------------
# Private / mixed fails before staging
# ---------------------------------------------------------------------------


def test_private_input_fails_before_staging(tmp_path: Path) -> None:
    private = {
        "record_id": "app:private:1",
        "config_name": "applications",
        "classification": "confidential_application",
        "payload": {"application_number": "16/999999", "title": "unpublished"},
        "source_lineage": _lineage(
            source_id="uspto/private-export",
            revision="matter-1",
            uri="uspto://matter/16-999999",
            body="private-export-1",
        ).to_dict(),
        "rights_review": _rights().to_dict(),
        "privacy_review": _privacy().to_dict(),
    }
    with pytest.raises(PatentReleaseSafetyError, match="before staging|private"):
        build_patent_hf_release_v2([private], dry_run=True)

    with pytest.raises(PatentReleaseSafetyError, match="before staging|private"):
        build_patent_hf_release_v2(
            [private],
            dry_run=False,
            output_dir=tmp_path / "stage",
        )
    assert not (tmp_path / "stage").exists()


def test_mixed_private_public_fails_before_staging(tmp_path: Path) -> None:
    public = _public_rows()[0]
    private_lineage = _lineage(
        source_id="tenant/private",
        revision="r1",
        uri="uspto://private/wp/1",
        body="wp-1",
    )
    with pytest.raises(PatentReleaseSafetyError, match="private|before staging"):
        build_patent_hf_release_v2(
            [
                public.to_dict(),
                {
                    "record_id": "priv:wp:1",
                    "config_name": "office_actions",
                    "classification": "privileged_work_product",
                    "fields": {
                        "authoritative": {"summary": "attorney work product"},
                        "ai_derived": {},
                    },
                    "source_lineage": private_lineage.to_dict(),
                    "rights_review": _rights().to_dict(),
                    "privacy_review": _privacy().to_dict(),
                },
            ],
            dry_run=False,
            output_dir=tmp_path,
        )
    assert list(tmp_path.iterdir()) == []


def test_unreviewed_rights_fail_before_staging() -> None:
    bad = {
        "record_id": "usc:35:102",
        "config_name": "usc",
        "classification": "public_official",
        "fields": {"authoritative": {"text": "x"}, "ai_derived": {}},
        "source_lineage": _lineage().to_dict(),
        "rights_review": {
            "license_expression": "public-domain-US-government",
            "review_status": "unreviewed",
            "reviewed_by": "",
            "reviewed_at": "",
            "redistribution_allowed": False,
            "notes": "",
        },
        "privacy_review": _privacy().to_dict(),
    }
    with pytest.raises(PatentReleaseSafetyError, match="rights|before staging"):
        build_patent_hf_release_v2([bad], dry_run=True)


# ---------------------------------------------------------------------------
# Dry-run default / staging / no upload
# ---------------------------------------------------------------------------


def test_default_build_stops_at_dry_run(tmp_path: Path) -> None:
    sig = inspect.signature(build_patent_hf_release_v2)
    assert sig.parameters["dry_run"].default is True

    release = build_patent_hf_release_v2(_public_rows())
    assert release.dry_run is True
    assert release.staged_root is None
    assert list(tmp_path.iterdir()) == []

    unchanged = stage_patent_hf_release_v2(release, tmp_path)
    assert unchanged.dry_run is True
    assert unchanged.staged_root is None
    assert list(tmp_path.iterdir()) == []


def test_explicit_stage_writes_byte_identical_trees(tmp_path: Path) -> None:
    rows = _public_rows()
    out_a = tmp_path / "a"
    out_b = tmp_path / "b"
    release_a = build_patent_hf_release_v2(
        rows, dry_run=False, output_dir=out_a
    )
    release_b = build_patent_hf_release_v2(
        rows, dry_run=False, output_dir=out_b
    )

    assert release_a.dry_run is False
    assert release_a.staged_root is not None
    assert releases_are_byte_identical(release_a, release_b)

    files_a = sorted(
        p.relative_to(out_a).as_posix() for p in out_a.rglob("*") if p.is_file()
    )
    files_b = sorted(
        p.relative_to(out_b).as_posix() for p in out_b.rglob("*") if p.is_file()
    )
    assert files_a == files_b
    assert RELEASE_MANIFEST_FILENAME in files_a
    assert any("patent-legal-corpus" in rel for rel in files_a)
    assert any("patent-legal-vectors" in rel for rel in files_a)
    assert any("patent-legal-bm25" in rel for rel in files_a)
    assert any("patent-legal-knowledge-graph" in rel for rel in files_a)
    for rel in files_a:
        assert (out_a / rel).read_bytes() == (out_b / rel).read_bytes()


def test_no_direct_hf_api_upload_file_path() -> None:
    source = Path(hf_mod.__file__).read_text(encoding="utf-8")
    assert "from huggingface_hub" not in source
    assert "import huggingface_hub" not in source
    assert "HfApi(" not in source
    assert ".upload_file(" not in source

    builder = PatentLegalHFReleaseBuilderV2()
    builder.build(_public_rows(), dry_run=True)

    cli = (
        Path(__file__).resolve().parents[4]
        / "scripts/ops/legal_data/build_patent_hf_release_v2.py"
    )
    cli_text = cli.read_text(encoding="utf-8")
    assert "upload_file" not in cli_text or "no ``HfApi.upload_file``" in cli_text
    assert "HfApi(" not in cli_text
    assert "huggingface_hub" not in cli_text


def test_stage_requires_output_dir_when_not_dry_run() -> None:
    with pytest.raises(PatentHFReleaseV2Error, match="output_dir"):
        build_patent_hf_release_v2(_public_rows(), dry_run=False)


def test_builder_rejects_empty_rows() -> None:
    with pytest.raises(PatentReleaseSafetyError):
        build_patent_hf_release_v2([], dry_run=True)


def test_parquet_round_trip_field_partitions() -> None:
    release = build_patent_hf_release_v2(
        _public_rows(),
        dry_run=True,
        max_rows_per_shard=2,
    )
    corpus = release.repository_for_role("corpus")
    parquet_arts = [
        a for a in corpus.artifacts if a.relative_path.endswith(".parquet")
    ]
    assert parquet_arts
    for artifact in parquet_arts:
        table = pq.read_table(io.BytesIO(artifact.content))
        assert table.num_rows == artifact.row_count
        names = set(table.schema.names)
        assert {
            "record_id",
            "config_name",
            "classification",
            "source_cid",
            "authoritative_json",
            "ai_derived_json",
            "source_lineage_json",
            "rights_review_json",
            "privacy_review_json",
            "record_json",
        } <= names
        for row in table.to_pylist():
            assert row["classification"] in {"public_official", "public_user"}
            lineage = json.loads(row["source_lineage_json"])
            rights = json.loads(row["rights_review_json"])
            privacy = json.loads(row["privacy_review_json"])
            record = json.loads(row["record_json"])
            assert lineage["source_sha256"]
            assert rights["review_status"] == "reviewed"
            assert privacy["review_status"] == "reviewed"
            assert record["record_id"] == row["record_id"]
            # Nested field authority remains partitioned in record_json.
            assert "authoritative" in record["fields"]
            assert "ai_derived" in record["fields"]
