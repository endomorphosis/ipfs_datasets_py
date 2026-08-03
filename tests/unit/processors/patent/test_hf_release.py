"""Unit tests for deterministic JusticeDAO patent HF release packaging."""

from __future__ import annotations

import hashlib
import inspect
import io
import json
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from ipfs_datasets_py.processors.domains.patent import hf_release as hf_release_mod
from ipfs_datasets_py.processors.domains.patent.hf_release import (
    DEFAULT_DATASET_REPO_ID,
    HF_RELEASE_SCHEMA_VERSION,
    MANIFEST_FILENAME,
    PatentHFReleaseError,
    PatentLegalHFReleaseBuilder,
    PatentReleaseSafetyError,
    build_patent_hf_release,
    releases_are_byte_identical,
    stage_patent_hf_release,
    validate_patent_hf_release,
)
from ipfs_datasets_py.processors.domains.patent.release_policy import (
    ReleaseCandidate,
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


def _public_candidates() -> list[ReleaseCandidate]:
    return [
        ReleaseCandidate(
            record_id="usc:35:101",
            artifact_kind="usc",
            classification="public_official",
            payload={
                "citation": "35 U.S.C. § 101",
                "text": "Whoever invents or discovers any new and useful process...",
            },
            source_lineage=_lineage(),
            rights_review=_rights(),
        ),
        ReleaseCandidate(
            record_id="cfr:37:1.56",
            artifact_kind="cfr",
            classification="public_official",
            payload={
                "citation": "37 CFR 1.56",
                "text": "Duty to disclose information material to patentability.",
            },
            source_lineage=_lineage(
                source_id="govinfo/cfr",
                revision="2024-title-37",
                uri="https://www.govinfo.gov/app/details/CFR-2024-title37-vol1",
                body="cfr-2024-title37",
            ),
            rights_review=_rights(),
        ),
        ReleaseCandidate(
            record_id="claim:US7654321B2:1",
            artifact_kind="claims",
            classification="public_official",
            payload={"claim_number": 1, "text": "A system comprising a processor..."},
            source_lineage=_lineage(
                source_id="uspto/public-pair",
                revision="grant-2020-01-01",
                uri="https://data.uspto.gov/apis/patent-file-wrapper",
                body="uspto-grant-2020",
            ),
            rights_review=_rights(),
        ),
        ReleaseCandidate(
            record_id="graph:edge:cites:1",
            artifact_kind="graph",
            classification="public_official",
            payload={"src": "US7654321B2", "dst": "US1234567A", "rel": "cites"},
            source_lineage=_lineage(
                source_id="patent-index/graph",
                revision="v1",
                uri="https://patentsview.org/download/data-download-tables",
                body="graph-v1",
            ),
            rights_review=_rights(),
        ),
        ReleaseCandidate(
            record_id="bm25:novelty",
            artifact_kind="bm25",
            classification="public_official",
            payload={"term": "novelty", "df": 42},
            source_lineage=_lineage(
                source_id="patent-index/bm25",
                revision="v1",
                uri="https://example.invalid/bm25/v1",
                body="bm25-v1",
            ),
            rights_review=_rights(),
        ),
        ReleaseCandidate(
            record_id="vec:meta:0",
            artifact_kind="vector_metadata",
            classification="public_official",
            payload={"model": "minilm", "dim": 384, "count": 1},
            source_lineage=_lineage(
                source_id="patent-index/vectors",
                revision="v1",
                uri="https://example.invalid/vectors/v1",
                body="vectors-v1",
            ),
            rights_review=_rights(),
        ),
    ]


def test_two_builds_are_byte_identical() -> None:
    candidates = _public_candidates()
    first = build_patent_hf_release(candidates, dry_run=True)
    second = build_patent_hf_release(candidates, dry_run=True)

    assert releases_are_byte_identical(first, second)
    assert first.release_root_cid == second.release_root_cid
    assert first.manifest_dict() == second.manifest_dict()
    for left, right in zip(first.artifacts, second.artifacts, strict=True):
        assert left.content == right.content
        assert left.sha256 == right.sha256
        assert left.content_cid == right.content_cid


def test_every_artifact_binds_integrity_lineage_classification_rights() -> None:
    release = build_patent_hf_release(_public_candidates(), dry_run=True)
    validation = validate_patent_hf_release(release)

    assert validation["valid"] is True
    assert release.total_row_count == 6
    assert release.dataset_id == DEFAULT_DATASET_REPO_ID
    assert release.schema_version == HF_RELEASE_SCHEMA_VERSION

    for artifact in release.artifacts:
        desc = artifact.descriptor()
        assert desc["sha256"] and len(desc["sha256"]) == 64
        assert desc["content_cid"].startswith("b")
        assert "row_count" in desc
        assert isinstance(desc["source_lineage"], list) and desc["source_lineage"]
        assert isinstance(desc["classifications"], list) and desc["classifications"]
        assert isinstance(desc["rights_reviews"], list) and desc["rights_reviews"]
        for rights in desc["rights_reviews"]:
            assert rights["review_status"] == "reviewed"
            assert rights["redistribution_allowed"] is True
        for cls in desc["classifications"]:
            assert cls in {"public_official", "public_user"}

    manifest = release.manifest_dict()
    assert manifest["uses_hf_api_upload_file"] is False
    assert manifest["upload_path"] is None
    assert manifest["dry_run"] is True
    assert set(manifest["shard_configs"]) == {
        "bm25",
        "cfr",
        "claims",
        "graph",
        "usc",
        "vector_metadata",
    }


def test_parquet_rows_round_trip_policy_bindings() -> None:
    release = build_patent_hf_release(
        _public_candidates(),
        dry_run=True,
        max_rows_per_shard=2,
    )
    assert release.parquet_artifacts
    for artifact in release.parquet_artifacts:
        table = pq.read_table(io.BytesIO(artifact.content))
        assert table.num_rows == artifact.row_count
        assert table.schema.names == [
            "record_id",
            "artifact_kind",
            "classification",
            "record_sha256",
            "source_lineage_json",
            "rights_review_json",
            "record_json",
        ]
        for row in table.to_pylist():
            assert row["classification"] in {"public_official", "public_user"}
            lineage = json.loads(row["source_lineage_json"])
            rights = json.loads(row["rights_review_json"])
            record = json.loads(row["record_json"])
            assert lineage["source_sha256"]
            assert rights["review_status"] == "reviewed"
            assert record["record_id"] == row["record_id"]


def test_private_input_fails_before_staging(tmp_path: Path) -> None:
    private = ReleaseCandidate(
        record_id="app:private:1",
        artifact_kind="applications",
        classification="confidential_application",
        payload={"application_number": "16/999999", "title": "unpublished"},
        source_lineage=_lineage(
            source_id="uspto/private-export",
            revision="matter-1",
            uri="uspto://matter/16-999999",
            body="private-export-1",
        ),
        rights_review=_rights(),
    )
    with pytest.raises(PatentReleaseSafetyError, match="before staging"):
        build_patent_hf_release([private], dry_run=True)

    # Staging path must also refuse non-admitted material.
    with pytest.raises(PatentReleaseSafetyError, match="before staging"):
        build_patent_hf_release(
            [private],
            dry_run=False,
            output_dir=tmp_path / "stage",
        )
    assert not (tmp_path / "stage").exists()


def test_mixed_private_public_fails_before_staging(tmp_path: Path) -> None:
    public = _public_candidates()[0]
    private = ReleaseCandidate(
        record_id="priv:wp:1",
        artifact_kind="office_actions",
        classification="privileged_work_product",
        payload={"summary": "attorney work product"},
        source_lineage=_lineage(
            source_id="tenant/private",
            revision="r1",
            uri="uspto://private/wp/1",
            body="wp-1",
        ),
        rights_review=_rights(),
    )
    with pytest.raises(PatentReleaseSafetyError, match="mixed|private|before staging"):
        build_patent_hf_release([public, private], dry_run=False, output_dir=tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_default_build_stops_at_dry_run(tmp_path: Path) -> None:
    # Signature defaults dry_run=True.
    sig = inspect.signature(build_patent_hf_release)
    assert sig.parameters["dry_run"].default is True

    release = build_patent_hf_release(_public_candidates())
    assert release.dry_run is True
    assert release.staged_root is None
    assert list(tmp_path.iterdir()) == []

    # stage helper also defaults to dry-run (no writes).
    unchanged = stage_patent_hf_release(release, tmp_path)
    assert unchanged.dry_run is True
    assert unchanged.staged_root is None
    assert list(tmp_path.iterdir()) == []


def test_explicit_stage_writes_byte_identical_trees(tmp_path: Path) -> None:
    candidates = _public_candidates()
    out_a = tmp_path / "a"
    out_b = tmp_path / "b"
    release_a = build_patent_hf_release(
        candidates, dry_run=False, output_dir=out_a
    )
    release_b = build_patent_hf_release(
        candidates, dry_run=False, output_dir=out_b
    )

    assert release_a.dry_run is False
    assert release_a.staged_root is not None
    assert releases_are_byte_identical(release_a, release_b)

    files_a = sorted(p.relative_to(out_a).as_posix() for p in out_a.rglob("*") if p.is_file())
    files_b = sorted(p.relative_to(out_b).as_posix() for p in out_b.rglob("*") if p.is_file())
    assert files_a == files_b
    assert MANIFEST_FILENAME in files_a
    for rel in files_a:
        assert (out_a / rel).read_bytes() == (out_b / rel).read_bytes()


def test_no_direct_hf_api_upload_file_path() -> None:
    source = Path(hf_release_mod.__file__).read_text(encoding="utf-8")
    # Documentation may mention the forbidden path; executable imports/calls must not exist.
    assert "from huggingface_hub" not in source
    assert "import huggingface_hub" not in source
    assert "HfApi(" not in source
    assert ".upload_file(" not in source

    # Runtime guard on the builder.
    builder = PatentLegalHFReleaseBuilder()
    builder.build(_public_candidates(), dry_run=True)

    # CLI script must also avoid upload shortcuts.
    cli = (
        Path(__file__).resolve().parents[4]
        / "scripts/ops/legal_data/build_patent_hf_release.py"
    )
    cli_text = cli.read_text(encoding="utf-8")
    assert "upload_file" not in cli_text or "no ``HfApi.upload_file``" in cli_text
    assert "HfApi(" not in cli_text
    assert "huggingface_hub" not in cli_text


def test_stage_requires_output_dir_when_not_dry_run() -> None:
    with pytest.raises(PatentHFReleaseError, match="output_dir"):
        build_patent_hf_release(_public_candidates(), dry_run=False)


def test_builder_rejects_empty_candidates() -> None:
    with pytest.raises(PatentReleaseSafetyError):
        build_patent_hf_release([], dry_run=True)
