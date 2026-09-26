"""Offline private resume packages preserve bytes and reuse publisher plans."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import socket
import struct
import zlib

import pytest

from ipfs_datasets_py.duckdb_control.autoencoder_registry import SCHEMA as REGISTRY_SCHEMA
from ipfs_datasets_py.duckdb_control.contracts import content_identity
from ipfs_datasets_py.huggingface.autoencoder_release import (
    AutoencoderReleaseError,
    build_private_resume_release,
    verify_release_package,
)
from ipfs_datasets_py.huggingface.publisher import PublicationPlan


@pytest.fixture
def checkpoint(tmp_path: Path) -> tuple[Path, dict]:
    source = tmp_path / "pinned.state.json"
    source.write_bytes(b'{\n  "feature_embedding_weights": {"The agency shall preserve records.": [0.1, -0.0]},\n  "sample_memory": {"original source text": [1, 2]}, "optimizer_metadata": {"epoch": 9}\n}\n')
    artifact = {"sha256": hashlib.sha256(source.read_bytes()).hexdigest(), "bytes": source.stat().st_size}
    identity = {"schema": REGISTRY_SCHEMA, "variant_id": "english-legacy", "artifact": artifact,
                "metadata": {"fixture": True}, "parent_version_id": None}
    version = {key: value for key, value in identity.items() if key != "schema"}
    version["version_id"] = content_identity(identity)
    return source, version


def build(checkpoint, destination: Path, **options):
    source, version = checkpoint
    return build_private_resume_release(
        version, source, destination, repo_id="review-owner/private-autoencoder",
        variant_manifest={"source_languages": ["en"], "target_logic": "typed_deontic"},
        **options,
    )


def test_deterministic_package_preserves_complete_checkpoint_and_source_inode(checkpoint, tmp_path: Path) -> None:
    source, version = checkpoint
    archive = tmp_path / "archive.state.json"
    os.link(source, archive)
    before = source.read_bytes()
    inode = source.stat().st_ino
    first = build(checkpoint, tmp_path / "first")
    second = build(checkpoint, tmp_path / "second")
    assert first.package_manifest_sha256 == second.package_manifest_sha256
    # Captured from the existing v1 builder before compact support. New binary
    # packages must not silently change old release/plan identities.
    assert first.package_manifest_sha256 == "6b6b9cb772598e27121c98c0d8d3c03bb3e1a5598aab6c61f0ce93a2ad67da39"
    assert first.publication_plan.plan_digest == "75269c026fa361bf0f012404bb0d3d73147e473032afcd370d92b0200d65616c"
    assert first.publication_plan.plan_digest == second.publication_plan.plan_digest
    assert first.publication_plan.to_dict() == second.publication_plan.to_dict()
    assert isinstance(first.publication_plan, PublicationPlan)
    assert first.publication_plan.repository_type == "model"
    assert first.publication_plan.remote_write_contacted is False
    assert first.publication_plan.metadata["required_repository_private"] is True
    assert first.publication_plan.metadata["upload_ready"] is False
    assert first.publication_plan.metadata["approval_status"] == "exact_plan_human_approval_required"
    assert (first.release_root / "state.json").read_bytes() == before
    assert source.read_bytes() == archive.read_bytes() == before
    assert source.stat().st_ino == archive.stat().st_ino == inode
    assert (first.release_root / "state.json").stat().st_ino != inode
    manifest = json.loads((first.release_root / "release-manifest.json").read_bytes())
    assert manifest["identities"]["checkpoint_file_sha256"] == version["artifact"]["sha256"]
    assert manifest["identities"]["registry_version_id"] == version["version_id"]
    assert manifest["identities"]["logical_state_identity"] is None
    assert manifest["identities"]["huggingface_commit_sha"] is None
    assert manifest["evaluation_status"] == "not_supplied"
    assert manifest["admitted"] is False
    assert manifest["constitution_formalized"] is False
    assert "No evaluation evidence was supplied" in (first.package_root / "README.md").read_text()
    assert all(item.remote_path.startswith(first.publication_plan.release_prefix + "/") for item in first.publication_plan.operations)
    assert any(item.relative_path == "release-manifest.json" for item in first.publication_plan.operations)
    verify_release_package(first.package_root, expected_manifest_sha256=first.package_manifest_sha256)


def test_public_and_inference_profiles_fail_before_creation(checkpoint, tmp_path: Path) -> None:
    for label, options in (
        ("public", {"private": False}),
        ("inference", {"checkpoint_profile": "inference"}),
        ("not_boolean", {"private": "true"}),
    ):
        with pytest.raises(AutoencoderReleaseError, match="only exact_resume_private"):
            build(checkpoint, tmp_path / label, **options)
        assert not (tmp_path / label).exists()


def test_no_destination_overwrite_and_no_source_hash_substitution(checkpoint, tmp_path: Path) -> None:
    existing = tmp_path / "existing"
    existing.mkdir()
    sentinel = existing / "keep"
    sentinel.write_text("untouched")
    with pytest.raises(FileExistsError):
        build(checkpoint, existing)
    assert sentinel.read_text() == "untouched"
    source, _ = checkpoint
    source.write_bytes(source.read_bytes() + b" ")
    with pytest.raises(AutoencoderReleaseError, match="immutable version artifact"):
        build(checkpoint, tmp_path / "bad-digest")
    assert not (tmp_path / "bad-digest").exists()


def test_evaluation_files_are_frozen_and_identity_is_distinct(checkpoint, tmp_path: Path) -> None:
    evaluation = tmp_path / "evaluation.json"
    evaluation.write_bytes(b'{ "admitted": false, "legal_ir_target_count": 3 }\n')
    supplied = {"state_cid": "sha256:" + "a" * 64}
    result = build(checkpoint, tmp_path / "release", state_identity=supplied, evaluation_receipts=[evaluation])
    files = list((result.release_root / "evaluations").glob("*.json"))
    assert len(files) == 1 and files[0].read_bytes() == evaluation.read_bytes()
    manifest = json.loads((result.release_root / "release-manifest.json").read_text())
    assert manifest["identities"]["logical_state_identity"] == supplied
    assert manifest["identities"]["logical_state_identity_status"] == "caller_supplied_not_recomputed"
    assert manifest["evaluation_status"] == "supplied_not_revalidated"
    assert "Frozen evaluation receipts included: 1" in (result.package_root / "README.md").read_text()


def test_closure_rejects_traversal_extra_files_and_symlinks(checkpoint, tmp_path: Path) -> None:
    result = build(checkpoint, tmp_path / "release")
    manifest_path = result.package_root / "package-manifest.json"
    original = manifest_path.read_bytes()
    manifest = json.loads(original)
    manifest["files"][0]["path"] = "../pinned.state.json"
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(AutoencoderReleaseError, match="unsafe manifest path"):
        verify_release_package(result.package_root)
    manifest_path.write_bytes(original)
    extra = result.package_root / "unlisted"
    extra.write_text("untracked")
    with pytest.raises(AutoencoderReleaseError, match="exact file closure"):
        verify_release_package(result.package_root)
    extra.unlink()
    extra.symlink_to(checkpoint[0])
    with pytest.raises(AutoencoderReleaseError, match="symlink"):
        verify_release_package(result.package_root)


def test_offline_builder_never_calls_network_or_constructs_approval(checkpoint, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import huggingface_hub
    from ipfs_datasets_py.huggingface import publisher
    monkeypatch.setattr(socket.socket, "connect", lambda *a, **k: pytest.fail("network access"))
    monkeypatch.setattr(huggingface_hub, "get_token", lambda *a, **k: pytest.fail("credential access"))
    monkeypatch.setattr(publisher, "PublicationApproval", lambda *a, **k: pytest.fail("invented approval"))
    result = build(checkpoint, tmp_path / "release")
    assert result.publication_plan.dry_run is True
    assert result.publication_plan.audited_parent_commit == ""
    assert result.publication_plan.metadata["remote_privacy_verified"] is False


def test_tampered_registry_identity_rejected(checkpoint, tmp_path: Path) -> None:
    source, version = checkpoint
    changed = {**version, "variant_id": "another-language"}
    with pytest.raises(AutoencoderReleaseError, match="registry version identity"):
        build((source, changed), tmp_path / "release")


def test_sparse_manifest_cannot_be_packaged_as_complete_weights(checkpoint, tmp_path: Path) -> None:
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_sparse_checkpoint import SCHEMA

    source, version = checkpoint
    # Even a registered artifact with no storage-kind metadata must be checked.
    source.write_text(json.dumps({"schema": SCHEMA, "parent": {"sha256": "a" * 64, "bytes": 1}}))
    version = {**version, "artifact": {
        "sha256": hashlib.sha256(source.read_bytes()).hexdigest(), "bytes": source.stat().st_size,
    }}
    version["version_id"] = content_identity({"schema": REGISTRY_SCHEMA, **{
        key: version[key] for key in ("variant_id", "artifact", "metadata", "parent_version_id")
    }})
    with pytest.raises(AutoencoderReleaseError, match="verified full materialization"):
        build((source, version), tmp_path / "sparse-release")
    assert not (tmp_path / "sparse-release").exists()


def test_canonical_singular_language_and_contradiction(checkpoint, tmp_path: Path) -> None:
    source, version = checkpoint
    variant = {"source_language": "en", "target_formal_language": "typed_deontic",
               "jurisdiction": "us-federal", "model_variant": "restart12"}
    result = build_private_resume_release(version, source, tmp_path / "release",
                                         repo_id="review-owner/private-autoencoder", variant_manifest=variant)
    assert '  - "en"' in (result.package_root / "README.md").read_text()
    assert "Declared source languages: en." in (result.package_root / "README.md").read_text()
    with pytest.raises(AutoencoderReleaseError, match="declarations contradict"):
        build_private_resume_release(version, source, tmp_path / "contradictory",
                                     repo_id="review-owner/private-autoencoder",
                                     variant_manifest={**variant, "source_languages": ["fr"]})


@pytest.mark.parametrize("payload", [b'{"loss": NaN}', b'{"admitted":false,"admitted":true}'])
def test_invalid_evaluation_json_rejected_before_package(checkpoint, tmp_path: Path, payload: bytes) -> None:
    evaluation = tmp_path / "evaluation.json"
    evaluation.write_bytes(payload)
    with pytest.raises(AutoencoderReleaseError):
        build(checkpoint, tmp_path / "release", evaluation_receipts=[evaluation])
    assert not (tmp_path / "release").exists()


def _version_for(source: Path):
    artifact = {"sha256": hashlib.sha256(source.read_bytes()).hexdigest(), "bytes": source.stat().st_size}
    version = {"variant_id": "english-compact-fixture", "artifact": artifact,
               "metadata": {"fixture": True, "checkpoint_storage": "full"}, "parent_version_id": None}
    version["version_id"] = content_identity({"schema": REGISTRY_SCHEMA, **version})
    return version


@pytest.fixture
def compact_checkpoint(tmp_path):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import ModalAutoencoderTrainingState
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_checkpoint import serialize_checkpoint

    state = ModalAutoencoderTrainingState(
        feature_embedding_weights={"source-like feature key!": [-0.0, 0.12345678901234568, 5e-324],
                                   "empty": [], "é/last": [2.0]},
        feature_family_logits={"source-like feature key!": {"deontic": -0.0}},
        decoded_embeddings={"sample memory retained": [-0.0, 0.75]},
        applied_todo_ids=["second", "first", "second"],
    )
    state.legal_ir_view_logits["fixture-change"] = 0.125
    state.applied_leanstral_guidance_ids.append("fixture-not-guidance")
    source = tmp_path / "owner-final.compact"
    source.write_bytes(serialize_checkpoint(
        state, metric_lineage={"schema": "fixture-metric-v1"},
        metadata={"reason": "fixture-only", "nested": {"ordered": ["second", "first"], "zero": -0.0}},
    ))
    return source, _version_for(source)


def test_compact_package_preserves_complete_native_state_revision_bits_and_bytes(compact_checkpoint, tmp_path):
    from ipfs_datasets_py.huggingface.autoencoder_release import COMPACT_SCHEMA, COMPACT_PACKAGE_SCHEMA
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_checkpoint import load_checkpoint, serialize_checkpoint
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_state_diff import exact_state_snapshot

    source, version = compact_checkpoint
    original = source.read_bytes()
    before = load_checkpoint(source, recover=False, allow_json=False)
    assert before.state.state_revision == before.manifest.revision == 2
    first = build(compact_checkpoint, tmp_path / "compact-release")
    second = build(compact_checkpoint, tmp_path / "compact-repeat")
    assert first.package_manifest_sha256 == second.package_manifest_sha256
    assert first.publication_plan.to_dict() == second.publication_plan.to_dict()
    packaged = first.release_root / "state.compact"
    assert packaged.read_bytes() == source.read_bytes() == original
    assert packaged.stat().st_ino != source.stat().st_ino
    assert not (first.release_root / "state.json").exists()
    restored = load_checkpoint(packaged, recover=False, allow_json=False)
    assert exact_state_snapshot(restored.state) == exact_state_snapshot(before.state)
    assert exact_state_snapshot(restored.state)["component_count"] == 38
    assert restored.state.to_json() == before.state.to_json()
    assert restored.manifest.to_dict() == before.manifest.to_dict()
    assert restored.state.applied_todo_ids == ["second", "first", "second"]
    assert list(restored.state.feature_embedding_weights) == list(before.state.feature_embedding_weights)
    for key, values in before.state.feature_embedding_weights.items():
        assert b"".join(struct.pack(">d", x) for x in restored.state.feature_embedding_weights[key]) == b"".join(struct.pack(">d", x) for x in values)
    assert struct.pack(">d", restored.state.feature_embedding_weights["source-like feature key!"][0]) == struct.pack(">d", -0.0)
    assert restored.state.decoded_embeddings["sample memory retained"] == [-0.0, 0.75]
    assert serialize_checkpoint(restored.state, metric_lineage=restored.manifest.metric_lineage,
                                metadata=restored.manifest.metadata) == original
    manifest = json.loads((first.release_root / "release-manifest.json").read_bytes())
    provenance = json.loads((first.release_root / "provenance.json").read_bytes())
    config = json.loads((first.release_root / "config.json").read_bytes())
    assert manifest["schema_version"] == first.profile.canonical_release_schema == COMPACT_SCHEMA
    assert manifest["identities"]["logical_state_identity"] == before.state.state_identity_record().to_dict()
    assert manifest["identities"]["logical_state_identity_status"] == "native_compact_recomputed"
    assert manifest["identities"]["metric_state_identity"] == before.state.state_identity_record(
        metric_lineage=before.manifest.metric_lineage).to_dict()
    checkpoint = manifest["checkpoint"]
    assert checkpoint == provenance["checkpoint"] == config["checkpoint"]
    assert checkpoint["schema_version"] == before.manifest.schema_version
    assert checkpoint["state_schema_version"] == before.manifest.state_schema_version
    assert checkpoint["revision"] == 2 and checkpoint["float_precision"] == "float64"
    assert checkpoint["loader"]["callable"] == "load_checkpoint"
    assert checkpoint["loader"]["kwargs"] == {"recover": False, "allow_json": False}
    assert checkpoint["source_provenance"]["scope"] == "descriptive_files_not_runtime_attestation"
    assert len(checkpoint["source_provenance"]["sha256"]) == 3
    assert config["checkpoint_file"] == checkpoint["path"] == "state.compact"
    assert config["schema_version"] == "autoencoder-private-resume-config/v2"
    closure = verify_release_package(first.package_root, expected_manifest_sha256=first.package_manifest_sha256)
    assert closure["schema_version"] == COMPACT_PACKAGE_SCHEMA
    plan = first.publication_plan
    assert plan.schema_version == "legal-autoencoder-hf-publication-plan/v1"
    assert any(op.relative_path == "state.compact" and op.sha256 == version["artifact"]["sha256"] for op in plan.operations)
    assert all(op.remote_path.startswith(plan.release_prefix + "/") for op in plan.operations)
    assert plan.metadata["checkpoint_format"] == "modal_autoencoder_compact"
    assert plan.metadata["upload_ready"] is False and plan.remote_write_contacted is False
    assert manifest["admitted"] is False and manifest["constitution_formalized"] is False
    card = (first.package_root / "README.md").read_text()
    assert "load_checkpoint(path, recover=False, allow_json=False)" in card
    assert "no Arrow sidecar" in card and "not JSON" in card
    assert "No evaluation evidence was supplied" in card


def test_compact_state_identity_is_recomputed_and_caller_mismatch_rejected(compact_checkpoint, tmp_path):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_checkpoint import load_checkpoint
    expected = load_checkpoint(compact_checkpoint[0], recover=False).state.state_identity_record().to_dict()
    result = build(compact_checkpoint, tmp_path / "matching", state_identity=expected)
    assert json.loads((result.release_root / "release-manifest.json").read_text())["identities"]["logical_state_identity"] == expected
    with pytest.raises(AutoencoderReleaseError, match="supplied state identity differs"):
        build(compact_checkpoint, tmp_path / "mismatch", state_identity={**expected, "revision": expected["revision"] + 1})
    assert not (tmp_path / "mismatch").exists()


def _malformed_compact(raw, change):
    """Independent malformed framing, with checksums repaired where intended."""
    header = struct.Struct(">8sHHIQ32s32s")
    magic, version, flags, manifest_size, _, _, _ = header.unpack_from(raw)
    manifest_bytes = raw[header.size:header.size + manifest_size]
    payload = raw[header.size + manifest_size:]
    if change == "duplicate_manifest_key":
        manifest_bytes = manifest_bytes.replace(b'"metadata":', b'"metadata":{},"metadata":', 1)
    elif change == "nonfinite_metadata":
        manifest = json.loads(manifest_bytes)
        manifest["metadata"]["invalid_numeric_metadata"] = float("nan")
        manifest_bytes = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    elif change == "duplicate_index_key":
        expanded = zlib.decompress(payload)
        index_size, = struct.unpack_from(">I", expanded)
        index = expanded[4:4 + index_size]
        changed_index = index.replace(b'"metadata":', b'"metadata":{},"metadata":', 1)
        payload = zlib.compress(struct.pack(">I", len(changed_index)) + changed_index + expanded[4 + index_size:], level=9)
        manifest = json.loads(manifest_bytes)
        manifest["payload_checksum"] = hashlib.sha256(payload).hexdigest()
        manifest_bytes = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    else:
        raise AssertionError(change)
    return header.pack(magic, version, flags, len(manifest_bytes), len(payload),
                       hashlib.sha256(manifest_bytes).digest(), hashlib.sha256(payload).digest()) + manifest_bytes + payload


@pytest.mark.parametrize("change", ["checksum", "truncated", "trailing", "duplicate_manifest_key",
                                    "duplicate_index_key", "nonfinite_metadata", "delta", "float32"])
def test_invalid_or_nonfull_compact_checkpoint_cannot_create_release(compact_checkpoint, tmp_path, change):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_checkpoint import (
        load_checkpoint, serialize_checkpoint, serialize_delta,
    )
    source, _ = compact_checkpoint
    raw = source.read_bytes()
    if change == "checksum":
        raw = raw[:-1] + bytes([raw[-1] ^ 1])
    elif change == "truncated":
        raw = raw[:-10]
    elif change == "trailing":
        raw += b"unexpected"
    elif change == "delta":
        base = load_checkpoint(source, recover=False).state
        changed = base.copy()
        changed.legal_ir_view_logits["delta-only"] = 1.0
        raw = serialize_delta(base, changed)
    elif change == "float32":
        loaded = load_checkpoint(source, recover=False)
        raw = serialize_checkpoint(loaded.state, float_precision="float32")
    else:
        raw = _malformed_compact(raw, change)
    source.write_bytes(raw)
    with pytest.raises(AutoencoderReleaseError):
        build((source, _version_for(source)), tmp_path / "invalid")
    assert not (tmp_path / "invalid").exists()
    assert source.read_bytes() == raw


def test_compact_package_has_no_credentials_network_approval_or_sidecar_dependency(compact_checkpoint, tmp_path, monkeypatch):
    import huggingface_hub
    from ipfs_datasets_py.huggingface import publisher
    monkeypatch.setattr(socket.socket, "connect", lambda *a, **k: pytest.fail("network access"))
    monkeypatch.setattr(huggingface_hub, "get_token", lambda *a, **k: pytest.fail("credential access"))
    monkeypatch.setattr(publisher, "PublicationApproval", lambda *a, **k: pytest.fail("invented approval"))
    result = build(compact_checkpoint, tmp_path / "offline")
    assert result.publication_plan.dry_run is True
    assert result.publication_plan.metadata["remote_privacy_verified"] is False
    assert not any(path.suffix == ".arrow" for path in result.package_root.rglob("*"))


def test_compact_input_byte_bound_is_checked_before_package_creation(compact_checkpoint, tmp_path, monkeypatch):
    from ipfs_datasets_py.huggingface import autoencoder_release as release
    monkeypatch.setattr(release, "MAX_COMPACT_CHECKPOINT_BYTES", compact_checkpoint[1]["artifact"]["bytes"] - 1)
    with pytest.raises(AutoencoderReleaseError, match="input bound"):
        build(compact_checkpoint, tmp_path / "too-large")
    assert not (tmp_path / "too-large").exists()
