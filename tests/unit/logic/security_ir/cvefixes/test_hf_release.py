"""Conformance tests for deterministic local Hugging Face release packaging."""

from __future__ import annotations

from dataclasses import replace
import io
import json

import pyarrow.parquet as pq
import pytest

from ipfs_datasets_py.logic.ir_core.identity import canonical_identity
from ipfs_datasets_py.logic.security_ir.cvefixes.hf_release import (
    BoundedReleaseQueryClient,
    ParquetReleaseConfig,
    ReleaseArtifact,
    ReleaseIntegrityError,
    ReleaseLimitError,
    ReleaseQuery,
    ReleaseSafetyError,
    build_huggingface_release,
    stage_huggingface_release,
    validate_huggingface_release,
)
from ipfs_datasets_py.logic.security_ir.cvefixes.release_policy import (
    LicenseProvenance,
    LicenseReviewStatus,
)
from ipfs_datasets_py.logic.security_ir.cvefixes.schemas import (
    DerivedDataset,
    EvaluationRecord,
    GraphNode,
    PolicyCandidate,
    SourceRecord,
)


def _cid(label: str) -> str:
    return canonical_identity(
        {"label": label}, domain="test", schema_version="test/v1"
    ).cid


SOURCE_CID = _cid("pinned-source")
PARENT_CID = _cid("parent")
CONFIG_CID = _cid("config")


def _bindings(label: str) -> dict[str, object]:
    return {
        "source_cids": (SOURCE_CID,),
        "parent_cids": (_cid(f"parent-{label}"),),
        "config_cid": CONFIG_CID,
    }


def _dataset(*, extra_payload: dict[str, object] | None = None) -> DerivedDataset:
    source = SourceRecord(
        **_bindings("source"),
        source_uri="hf://datasets/hitoshura25/cvefixes",
        source_revision="d4f5c4ea65329d9ccbb8a3b3149e5d06eda5edb2",
        row_key="42",
        payload={"cve_id": "CVE-2026-0042", **(extra_payload or {})},
    )
    node = GraphNode(
        **_bindings("node"),
        node_type="cve",
        payload={"cve_id": "CVE-2026-0042", "language": "python"},
    )
    candidate = PolicyCandidate(
        **_bindings("candidate"),
        effect="deny",
        scope={"operation": "unsafe_deserialize"},
        payload={"cwe_id": "CWE-502"},
    )
    evaluation = EvaluationRecord(
        **_bindings("evaluation"),
        subject_cids=(candidate.cid,),
        metrics={
            "evaluation_schema_version": "cvefixes-leakage-safe-evaluation/v1",
            "measurements": {
                "fixed_negative_accuracy": 1.0,
                "vulnerable_recall": 1.0,
            },
            "promotion_review": {
                "decision": "promote",
                "grants_execution_authority": False,
            },
        },
        payload={
            "authoritative": False,
            "grants_execution_authority": False,
        },
    )
    return DerivedDataset(records=(source, node, candidate, evaluation))


def _license(
    *,
    review_status: LicenseReviewStatus = LicenseReviewStatus.REVIEWED,
    redistribution_allowed: bool = True,
) -> LicenseProvenance:
    reviewed = review_status is LicenseReviewStatus.REVIEWED
    return LicenseProvenance(
        dataset_id="hitoshura25/cvefixes",
        source_revision="d4f5c4ea65329d9ccbb8a3b3149e5d06eda5edb2",
        license_expression="Apache-2.0",
        evidence_url="https://huggingface.co/datasets/hitoshura25/cvefixes",
        review_status=review_status,
        reviewed_by="security-release-review" if reviewed else "",
        reviewed_at="2026-07-29T00:00:00Z" if reviewed else "",
        redistribution_allowed=redistribution_allowed,
    )


def _release(**kwargs):
    return build_huggingface_release(
        _dataset(),
        license_provenance=_license(),
        **kwargs,
    )


def test_build_is_reproducible_and_manifest_binds_every_artifact() -> None:
    first = _release()
    second = _release()

    assert first.release_root == second.release_root
    assert first.release_manifest == second.release_manifest
    assert [
        (item.path, item.sha256, item.content_id) for item in first.artifacts
    ] == [
        (item.path, item.sha256, item.content_id) for item in second.artifacts
    ]
    assert first.artifact("manifest.json").content == second.artifact(
        "manifest.json"
    ).content

    manifest = json.loads(first.artifact("manifest.json").content)
    assert manifest["release_root"] == first.release_root
    assert manifest["derived_dataset_root"] == _dataset().cid
    assert {
        item["path"] for item in manifest["artifacts"]
    } == {item.path for item in first.artifacts if item.path != "manifest.json"}
    assert set(first.release_manifest.shard_cids) == {
        item.content_id for item in first.parquet_artifacts
    }


def test_parquet_configs_are_bounded_strict_and_round_trip_records() -> None:
    release = _release(
        parquet_config=ParquetReleaseConfig(
            max_records=10,
            max_rows_per_shard=1,
            max_shards_per_config=4,
            max_shard_bytes=1_000_000,
            row_group_size=1,
        )
    )
    validation = validate_huggingface_release(release)

    assert validation.valid
    assert validation.row_count == 4
    assert validation.shard_count == 4
    for artifact in release.parquet_artifacts:
        table = pq.read_table(io.BytesIO(artifact.content))
        assert table.num_rows == 1
        assert table.schema.names == [
            "record_id",
            "record_type",
            "authority",
            "source_cids",
            "parent_cids",
            "config_cid",
            "record_json",
        ]
        row = table.to_pylist()[0]
        assert row["record_type"] == artifact.config_name
        assert json.loads(row["record_json"])["record_id"] == row["record_id"]

    infos = json.loads(release.artifact("dataset_infos.json").content)
    assert set(infos["configs"]) == {
        "evaluation",
        "graph_node",
        "policy_candidate",
        "source_record",
    }
    assert sum(
        config["splits"]["train"]["num_examples"]
        for config in infos["configs"].values()
    ) == 4


def test_dataset_card_documents_source_license_profile_and_limitations() -> None:
    card = _release().artifact("README.md").content.decode()

    assert "hitoshura25/cvefixes" in card
    assert "d4f5c4ea65329d9ccbb8a3b3149e5d06eda5edb2" in card
    assert "Apache-2.0" in card
    assert "License evidence" in card
    assert "## Limitations" in card
    assert "body digests" in card
    assert "non-authoritative" in card
    assert "evaluation-report.json" in card


def test_evaluation_report_is_canonical_and_explicitly_non_authoritative() -> None:
    release = _release()
    report_artifact = release.artifact("evaluation-report.json")
    report = json.loads(report_artifact.content)

    assert report_artifact.content == json.dumps(
        report, ensure_ascii=True, separators=(",", ":"), sort_keys=True
    ).encode()
    assert report["evaluation"]["record_type"] == "evaluation"
    assert report["evaluation"]["metrics"]["promotion_review"]["decision"] == "promote"
    assert report["grants_execution_authority"] is False


def test_validate_only_requires_no_credentials_and_writes_nothing(
    tmp_path, monkeypatch
) -> None:
    for name in ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN", "HF_HOME"):
        monkeypatch.delenv(name, raising=False)
    target = tmp_path / "release"

    result = stage_huggingface_release(
        _release(), target, validate_only=True
    )

    assert result.valid
    assert result.credentials_required is False
    assert not target.exists()


def test_staging_writes_only_the_validated_inventory(tmp_path) -> None:
    release = _release()
    target = tmp_path / "release"

    stage_huggingface_release(release, target, validate_only=False)

    staged = {
        path.relative_to(target).as_posix()
        for path in target.rglob("*")
        if path.is_file()
    }
    assert staged == {item.path for item in release.artifacts}
    assert (target / "manifest.json").read_bytes() == release.artifact(
        "manifest.json"
    ).content
    with pytest.raises(ReleaseSafetyError, match="empty"):
        stage_huggingface_release(release, target, validate_only=False)


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"vulnerable_code": "unsafe()"}, "internal body"),
        ({"hf_token": "not-even-a-real-token"}, "credential"),
        ({"cache_dir": "/tmp/huggingface"}, "cache"),
        ({"metadata": "hf_" + "a" * 30}, "secret-like"),
        ({"artifact": "/home/user/.cache/huggingface"}, "cache path"),
    ],
)
def test_secrets_caches_and_internal_bodies_never_enter_staging(
    payload: dict[str, object], message: str
) -> None:
    with pytest.raises(ReleaseSafetyError, match=message):
        build_huggingface_release(
            _dataset(extra_payload=payload),
            license_provenance=_license(),
        )


def test_unreviewed_or_nonredistributable_license_fails_closed() -> None:
    with pytest.raises(ReleaseSafetyError, match="license"):
        build_huggingface_release(
            _dataset(),
            license_provenance=_license(
                review_status=LicenseReviewStatus.UNREVIEWED,
                redistribution_allowed=False,
            ),
        )


def test_limits_reject_oversized_datasets_and_shards() -> None:
    with pytest.raises(ReleaseLimitError, match="max_records"):
        build_huggingface_release(
            _dataset(),
            license_provenance=_license(),
            parquet_config=ParquetReleaseConfig(
                max_records=3,
                max_rows_per_shard=3,
                row_group_size=1,
            ),
        )
    with pytest.raises(ReleaseLimitError, match="one Parquet row"):
        build_huggingface_release(
            _dataset(),
            license_provenance=_license(),
            parquet_config=ParquetReleaseConfig(
                max_records=10,
                max_rows_per_shard=1,
                max_shard_bytes=100,
                row_group_size=1,
            ),
        )


def test_validation_detects_artifact_tampering() -> None:
    release = _release()
    original = release.artifact("README.md")
    tampered = ReleaseArtifact(
        path=original.path,
        media_type=original.media_type,
        content=original.content + b"\ntampered\n",
    )
    changed = replace(
        release,
        artifacts=tuple(
            tampered if item.path == original.path else item
            for item in release.artifacts
        ),
    )

    with pytest.raises(ReleaseIntegrityError, match="inventory|root"):
        validate_huggingface_release(changed)


def test_bounded_query_client_caps_shards_rows_and_results() -> None:
    release = _release(
        parquet_config=ParquetReleaseConfig(
            max_records=10,
            max_rows_per_shard=1,
            max_shards_per_config=4,
            row_group_size=1,
        )
    )
    client = BoundedReleaseQueryClient(
        release, max_shards=2, max_rows=2, max_results=1
    )

    response = client.query(
        ReleaseQuery(text="cve", max_shards=999, max_rows=999, max_results=999)
    )

    assert response.shards_scanned == 2
    assert response.rows_scanned == 2
    assert len(response.results) == 1
    assert response.truncated_shards
    assert response.truncated_results
    assert response.grants_execution_authority is False
    with pytest.raises(ReleaseLimitError, match="4096"):
        ReleaseQuery(text="x" * 4097)
