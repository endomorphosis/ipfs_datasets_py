"""Conformance tests for the pinned Hugging Face Security IR source."""

from __future__ import annotations

from dataclasses import replace
import hashlib
import io
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ipfs_datasets_py.logic.ir_core.canonical import canonical_json_bytes
from ipfs_datasets_py.logic.ir_core.identity import canonical_identity
from ipfs_datasets_py.logic.security_ir.cvefixes.hf_release import (
    ReleaseArtifact,
    build_huggingface_release,
)
from ipfs_datasets_py.logic.security_ir.cvefixes.hf_source import (
    HuggingFaceSourceCache,
    HuggingFaceSourceCacheMiss,
    HuggingFaceSourceIntegrityError,
    HuggingFaceSourceLimitError,
    HuggingFaceSourceLimits,
    HuggingFaceSourcePin,
    HuggingFaceSourcePinError,
    PolicyLookup,
    load_huggingface_security_ir,
)
from ipfs_datasets_py.logic.security_ir.cvefixes.release_policy import (
    LicenseProvenance,
    LicenseReviewStatus,
)
from ipfs_datasets_py.logic.security_ir.cvefixes.schemas import (
    DerivedDataset,
    EvaluationRecord,
    PolicyCandidate,
    ReleaseManifest,
    SourceRecord,
    canonical_config_cid,
)
from ipfs_datasets_py.logic.security_ir.cvefixes.vocabulary import (
    CVEfixesPolicyAttributes,
    CVEfixesTermKind,
    cvefixes_term,
)


HUB_REVISION = "7" * 40
SOURCE_REVISION = "d4f5c4ea65329d9ccbb8a3b3149e5d06eda5edb2"


def _cid(label: str) -> str:
    return canonical_identity(
        {"label": label}, domain="hf-source-test", schema_version="test/v1"
    ).cid


SOURCE_CID = _cid("source-snapshot")
CONFIG_CID = canonical_config_cid({"hf_source_test": "v1"})


def _term(kind: CVEfixesTermKind, name: str) -> str:
    return cvefixes_term(kind, name).canonical


def _policy_scope() -> dict[str, object]:
    return CVEfixesPolicyAttributes(
        action=_term(
            CVEfixesTermKind.ACTION,
            "construct_path_from_untrusted_input",
        ),
        preconditions=(
            _term(CVEfixesTermKind.PRECONDITION, "attacker_controls_path"),
            _term(CVEfixesTermKind.PRECONDITION, "missing_canonicalization"),
        ),
        effects=(
            _term(CVEfixesTermKind.EFFECT, "read_outside_allowed_root"),
        ),
        mitigations=(
            _term(CVEfixesTermKind.MITIGATION, "canonicalize_and_confine"),
        ),
        language=_term(CVEfixesTermKind.LANGUAGE, "python"),
        scope=_term(CVEfixesTermKind.SCOPE, "filesystem"),
        cve_ids=("CVE-2026-0042",),
        cwe_ids=("CWE-22",),
    ).to_dict()


def _dataset(
    *,
    candidate_payload: dict[str, object] | None = None,
    duplicate_candidate: bool = False,
) -> DerivedDataset:
    source = SourceRecord(
        source_cids=(SOURCE_CID,),
        parent_cids=(_cid("source-parent"),),
        config_cid=CONFIG_CID,
        source_uri="hf://datasets/hitoshura25/cvefixes",
        source_revision=SOURCE_REVISION,
        row_key="CVE-2026-0042:deadbeef",
        payload={
            "content_sha256": "a" * 64,
            "cve_id": "CVE-2026-0042",
        },
    )
    candidate = PolicyCandidate(
        source_cids=(SOURCE_CID,),
        parent_cids=(_cid("candidate-parent"),),
        config_cid=CONFIG_CID,
        effect="deny",
        scope=_policy_scope(),
        payload={"severity": "critical", **(candidate_payload or {})},
    )
    evaluation = EvaluationRecord(
        source_cids=(SOURCE_CID,),
        parent_cids=(_cid("evaluation-parent"),),
        config_cid=CONFIG_CID,
        subject_cids=(candidate.cid,),
        metrics={
            "promotion_review": {
                "decision": "promote",
                "grants_execution_authority": False,
            }
        },
        payload={
            "authoritative": False,
            "grants_execution_authority": False,
        },
    )
    records = [source, candidate, evaluation]
    if duplicate_candidate:
        records.append(
            PolicyCandidate(
                source_cids=(SOURCE_CID,),
                parent_cids=(_cid("candidate-parent-two"),),
                config_cid=CONFIG_CID,
                effect="deny",
                scope=_policy_scope(),
                payload={"severity": "high"},
            )
        )
    return DerivedDataset(records=tuple(records))


def _license() -> LicenseProvenance:
    return LicenseProvenance(
        dataset_id="hitoshura25/cvefixes",
        source_revision=SOURCE_REVISION,
        license_expression="Apache-2.0",
        evidence_url="https://huggingface.co/datasets/hitoshura25/cvefixes",
        review_status=LicenseReviewStatus.REVIEWED,
        reviewed_by="security-release-review",
        reviewed_at="2026-07-29T00:00:00Z",
        redistribution_allowed=True,
    )


def _stage(root: Path, dataset: DerivedDataset | None = None):
    release = build_huggingface_release(
        dataset or _dataset(), license_provenance=_license()
    )
    root.mkdir(parents=True)
    for artifact in release.artifacts:
        path = root / artifact.path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(artifact.content)
    manifest = (root / "manifest.json").read_bytes()
    pin = HuggingFaceSourcePin(
        revision=HUB_REVISION,
        manifest_sha256=hashlib.sha256(manifest).hexdigest(),
        release_root=release.release_root,
    )
    return release, pin


def _rewrite_manifest(root: Path, update) -> HuggingFaceSourcePin:
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    update(manifest)
    content = canonical_json_bytes(manifest)
    manifest_path.write_bytes(content)
    return HuggingFaceSourcePin(
        revision=HUB_REVISION,
        manifest_sha256=hashlib.sha256(content).hexdigest(),
        release_root=manifest["release_root"],
    )


def _replace_descriptor(
    manifest: dict[str, object], path: str, artifact: ReleaseArtifact
) -> None:
    descriptors = manifest["artifacts"]
    assert isinstance(descriptors, list)
    for index, descriptor in enumerate(descriptors):
        if descriptor["path"] == path:
            descriptors[index] = artifact.descriptor()
            return
    raise AssertionError(path)


def test_load_exact_revision_verifies_release_shards_rows_and_dataset(
    tmp_path: Path,
) -> None:
    release, pin = _stage(tmp_path / "snapshot")

    loaded = load_huggingface_security_ir(tmp_path / "snapshot", pin)

    assert loaded.pin == pin
    assert loaded.dataset.cid == release.release_manifest.parent_cids[0]
    assert {record.cid for record in loaded.records} == set(
        release.release_manifest.record_cids
    )
    assert loaded.receipt.verified is True
    assert loaded.receipt.offline is True
    assert loaded.receipt.revision == HUB_REVISION
    assert loaded.receipt.shard_count == len(release.parquet_artifacts)
    assert loaded.receipt.grants_execution_authority is False


@pytest.mark.parametrize(
    "revision",
    ("main", "latest", "refs/heads/release", "A" * 40, "7" * 39),
)
def test_source_pin_rejects_floating_or_noncanonical_revisions(
    revision: str,
) -> None:
    with pytest.raises(HuggingFaceSourcePinError, match="immutable"):
        HuggingFaceSourcePin(
            revision=revision,
            manifest_sha256="a" * 64,
            release_root=_cid("release"),
        )


def test_manifest_drift_and_missing_shards_fail_closed(tmp_path: Path) -> None:
    root = tmp_path / "snapshot"
    release, pin = _stage(root)
    manifest_path = root / "manifest.json"
    manifest_path.write_bytes(manifest_path.read_bytes() + b"\n")

    with pytest.raises(
        HuggingFaceSourceIntegrityError, match="manifest digest"
    ):
        load_huggingface_security_ir(root, pin)

    manifest_path.write_bytes(release.artifact("manifest.json").content)
    (root / release.parquet_artifacts[0].path).unlink()
    with pytest.raises(
        HuggingFaceSourceIntegrityError, match="missing"
    ):
        load_huggingface_security_ir(root, pin)


def test_row_tampering_is_detected_even_with_rehashed_transport_metadata(
    tmp_path: Path,
) -> None:
    root = tmp_path / "snapshot"
    release, _ = _stage(root)
    original = next(
        artifact
        for artifact in release.parquet_artifacts
        if artifact.config_name == "policy_candidate"
    )
    shard_path = root / original.path
    table = pq.read_table(shard_path)
    rows = table.to_pylist()
    rows[0]["record_json"] = rows[0]["record_json"].replace(
        '"severity":"critical"', '"severity":"high"'
    )
    output = io.BytesIO()
    pq.write_table(
        pa.Table.from_pylist(rows, schema=table.schema),
        output,
        compression="zstd",
    )
    content = output.getvalue()
    shard_path.write_bytes(content)
    changed = ReleaseArtifact(
        path=original.path,
        media_type=original.media_type,
        content=content,
        config_name=original.config_name,
        row_count=original.row_count,
    )

    def update(manifest: dict[str, object]) -> None:
        _replace_descriptor(manifest, original.path, changed)
        old = ReleaseManifest.from_dict(manifest["release_manifest"])
        shard_cids = tuple(
            changed.content_id if cid == original.content_id else cid
            for cid in old.shard_cids
        )
        manifest["release_manifest"] = ReleaseManifest(
            source_cids=old.source_cids,
            parent_cids=old.parent_cids,
            config_cid=old.config_cid,
            payload=old.payload,
            dataset_id=old.dataset_id,
            profile=old.profile,
            record_cids=old.record_cids,
            shard_cids=shard_cids,
        ).to_dict()

    pin = _rewrite_manifest(root, update)
    with pytest.raises(
        HuggingFaceSourceIntegrityError, match="canonical row"
    ):
        load_huggingface_security_ir(root, pin)


def test_meta_index_pointer_tampering_fails_closed(
    tmp_path: Path,
) -> None:
    root = tmp_path / "snapshot"
    release, _ = _stage(root)
    original = release.artifact("indexes/corpus_chunks.parquet")
    table = pq.read_table(root / original.path)
    rows = table.to_pylist()
    assert len(rows) > 1
    rows[0]["relative_path"] = rows[1]["relative_path"]
    output = io.BytesIO()
    pq.write_table(
        pa.Table.from_pylist(rows, schema=table.schema),
        output,
        compression="zstd",
    )
    content = output.getvalue()
    (root / original.path).write_bytes(content)
    changed = ReleaseArtifact(
        path=original.path,
        media_type=original.media_type,
        content=content,
        config_name=original.config_name,
        row_count=original.row_count,
    )

    def update(manifest: dict[str, object]) -> None:
        _replace_descriptor(manifest, original.path, changed)
        indexes = manifest["indexes"]
        assert isinstance(indexes, dict)
        indexes["corpus_chunks"] = changed.descriptor()

    pin = _rewrite_manifest(root, update)
    with pytest.raises(
        HuggingFaceSourceIntegrityError, match="meta-index"
    ):
        load_huggingface_security_ir(root, pin)


def test_unknown_dataset_schema_fails_closed(tmp_path: Path) -> None:
    root = tmp_path / "snapshot"
    release, _ = _stage(root)
    infos_path = root / "dataset_infos.json"
    infos = json.loads(infos_path.read_bytes())
    infos["schema_version"] = "future-and-unsupported/v99"
    infos_content = canonical_json_bytes(infos)
    infos_path.write_bytes(infos_content)
    replacement = ReleaseArtifact(
        path="dataset_infos.json",
        media_type="application/json",
        content=infos_content,
    )

    pin = _rewrite_manifest(
        root,
        lambda manifest: _replace_descriptor(
            manifest, "dataset_infos.json", replacement
        ),
    )
    with pytest.raises(
        HuggingFaceSourceIntegrityError, match="dataset_infos schema"
    ):
        load_huggingface_security_ir(root, pin)


def test_candidate_cannot_smuggle_authority_from_verified_rows(
    tmp_path: Path,
) -> None:
    root = tmp_path / "snapshot"
    _, pin = _stage(
        root,
        _dataset(candidate_payload={"grants_execution_authority": True}),
    )

    with pytest.raises(
        HuggingFaceSourceIntegrityError, match="cannot grant candidate authority"
    ):
        load_huggingface_security_ir(root, pin)


def test_policy_lookup_and_declarations_are_bounded_and_non_authoritative(
    tmp_path: Path,
) -> None:
    root = tmp_path / "snapshot"
    _, pin = _stage(root, _dataset(duplicate_candidate=True))
    loaded = load_huggingface_security_ir(root, pin)

    response = loaded.lookup_policies(
        PolicyLookup(
            effect="deny",
            cwe_id="CWE-22",
            language="python",
            max_results=10,
        ),
        limits=HuggingFaceSourceLimits(max_results=1),
    )

    assert len(response.candidates) == 1
    assert response.candidates_scanned == 2
    assert response.truncated is True
    assert response.revision == HUB_REVISION
    assert response.grants_execution_authority is False

    results = loaded.security_ir_declarations(
        PolicyLookup(cve_id="CVE-2026-0042", max_results=1)
    )
    assert len(results) == 1
    assert results[0].authority == "candidate"
    assert results[0].grants_execution_authority is False
    policy_metadata = results[0].declaration.policies[0].attributes
    assert policy_metadata["security.cvefixes.adapter"][
        "requires_authoritative_adoption"
    ] is True


def test_resource_limits_fail_before_unbounded_scan(tmp_path: Path) -> None:
    root = tmp_path / "snapshot"
    _, pin = _stage(root)

    with pytest.raises(HuggingFaceSourceLimitError, match="shard limit"):
        load_huggingface_security_ir(
            root, pin, limits=HuggingFaceSourceLimits(max_shards=1)
        )


def test_offline_cache_preserves_and_reverifies_revision_identity(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    _, pin = _stage(source_root)
    calls = 0

    def fetcher(requested: HuggingFaceSourcePin, destination: Path) -> Path:
        nonlocal calls
        calls += 1
        assert requested == pin
        return source_root

    cache = HuggingFaceSourceCache(tmp_path / "cache", fetcher=fetcher)
    fetched = cache.materialize(pin)
    cached = cache.load(pin)

    assert calls == 1
    assert fetched.receipt.offline is False
    assert cached.receipt.offline is True
    assert cached.pin.revision == HUB_REVISION
    marker = json.loads(
        (cache.path_for(pin) / cache._MARKER).read_bytes()
    )
    assert marker["pin"]["revision"] == HUB_REVISION

    foreign = replace(pin, revision="8" * 40)
    with pytest.raises(HuggingFaceSourceCacheMiss, match="offline cache miss"):
        cache.load(foreign)

    cached_manifest = cache.path_for(pin) / "manifest.json"
    cached_manifest.write_bytes(cached_manifest.read_bytes() + b"\n")
    with pytest.raises(
        HuggingFaceSourceIntegrityError, match="manifest digest"
    ):
        cache.load(pin)


def test_offline_cache_without_fetcher_never_attempts_network(
    tmp_path: Path,
) -> None:
    _, pin = _stage(tmp_path / "source")
    cache = HuggingFaceSourceCache(tmp_path / "cache")

    with pytest.raises(HuggingFaceSourceCacheMiss, match="offline cache miss"):
        cache.materialize(pin)
