"""Offline reopen of sealed packages, with semantic re-sealing attacks."""
from dataclasses import fields
import hashlib
import json
import os
from pathlib import Path
import socket

import pytest

from ipfs_datasets_py.huggingface import autoencoder_release as release
from ipfs_datasets_py.huggingface.publisher import PublicationFilePlan, PublicationPlan
from tests.unit.huggingface.test_autoencoder_release import checkpoint, compact_checkpoint, build


VARIANT = {"source_languages": ["en"], "target_logic": "typed_deontic"}


def _json(path):
    return json.loads(path.read_bytes())


def _write(path, value):
    path.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n")


def _reseal_outer(package):
    path = package.package_root / "package-manifest.json"
    value = _json(path)
    for row in value["files"]:
        raw = (package.package_root / row["path"]).read_bytes()
        row.update(sha256=hashlib.sha256(raw).hexdigest(), size_bytes=len(raw))
    _write(path, value)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _reopen(package, version, digest=None, variant=VARIANT):
    return release.load_private_resume_release(package.package_root,
        expected_manifest_sha256=digest or package.package_manifest_sha256,
        expected_version_record=version, expected_variant_manifest=variant)


@pytest.mark.parametrize("kind", ["legacy", "compact"])
def test_reopen_exact_package_plan_profile_bytes_and_relocated_closure(checkpoint, compact_checkpoint, tmp_path, monkeypatch, kind):
    selected = checkpoint if kind == "legacy" else compact_checkpoint
    receipt = tmp_path / "evaluation.json"
    receipt.write_bytes(b'{ "evaluation_matches_final": false, "admitted": false }\n')
    package = build(selected, tmp_path / "original", evaluation_receipts=[receipt], audited_parent_commit="a" * 40)
    before = {path.relative_to(package.package_root): path.read_bytes() for path in package.package_root.rglob("*") if path.is_file()}
    import huggingface_hub
    from ipfs_datasets_py.huggingface import publisher
    monkeypatch.setattr(socket.socket, "connect", lambda *a, **k: pytest.fail("network contact"))
    monkeypatch.setattr(socket.socket, "connect_ex", lambda *a, **k: pytest.fail("network contact"))
    monkeypatch.setattr(huggingface_hub, "get_token", lambda *a, **k: pytest.fail("credentials"))
    monkeypatch.setattr(publisher, "PublicationApproval", lambda *a, **k: pytest.fail("approval fabrication"))
    monkeypatch.setattr(release, "build_private_resume_release", lambda *a, **k: pytest.fail("package regeneration"))
    reopened = _reopen(package, selected[1])
    assert reopened == package
    assert reopened.publication_plan.to_dict() == package.publication_plan.to_dict()
    assert reopened.profile == package.profile
    assert reopened.publication_plan.metadata["remote_privacy_verified"] is False
    assert reopened.publication_plan.metadata["upload_ready"] is False
    assert before == {path.relative_to(package.package_root): path.read_bytes() for path in package.package_root.rglob("*") if path.is_file()}
    import shutil
    moved = tmp_path / "restored-from-cas"
    shutil.copytree(package.package_root, moved)
    restored = release.load_private_resume_release(moved, expected_manifest_sha256=package.package_manifest_sha256,
        expected_version_record=selected[1], expected_variant_manifest=VARIANT)
    assert restored.release_root != package.release_root
    assert restored.publication_plan.to_dict() == package.publication_plan.to_dict()
    assert before == {path.relative_to(moved): path.read_bytes() for path in moved.rglob("*") if path.is_file()}


def test_compact_reopen_accepts_historical_descriptive_hashes_but_recomputes_native_identity(compact_checkpoint, tmp_path, monkeypatch):
    original = release._compact_checkpoint_description

    def historical(*args, **kwargs):
        value = original(*args, **kwargs)
        value["source_provenance"]["sha256"] = {key: "a" * 64 for key in value["source_provenance"]["sha256"]}
        return value

    with monkeypatch.context() as patch:
        patch.setattr(release, "_compact_checkpoint_description", historical)
        package = build(compact_checkpoint, tmp_path / "historical")
    reopened = _reopen(package, compact_checkpoint[1])
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_checkpoint import load_checkpoint
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_state_diff import exact_state_snapshot
    original_state = load_checkpoint(compact_checkpoint[0], recover=False)
    restored = load_checkpoint(reopened.release_root / "state.compact", recover=False)
    assert exact_state_snapshot(original_state.state) == exact_state_snapshot(restored.state)
    assert restored.manifest.to_dict() == original_state.manifest.to_dict()
    assert (reopened.release_root / "state.compact").read_bytes() == compact_checkpoint[0].read_bytes()


@pytest.mark.parametrize("target,field,value", [
    ("config.json", "sample_memory_removed", True),
    ("config.json", "checkpoint_file", "state.compact"),
    ("config.json", "variant_manifest", {"source_language": "fr"}),
    ("provenance.json", "variant_manifest", {"source_language": "fr"}),
    ("provenance.json", "evaluation_receipt_sha256", ["a" * 64]),
    ("release-manifest.json", "admitted", True),
    ("release-manifest.json", "constitution_formalized", True),
    ("release-manifest.json", "evaluation_status", "held_out_verified"),
])
def test_rehashed_outer_closure_does_not_accept_cross_file_substitution(checkpoint, tmp_path, target, field, value):
    package = build(checkpoint, tmp_path / "package")
    path = package.release_root / target
    data = _json(path)
    data[field] = value
    _write(path, data)
    digest = _reseal_outer(package)
    release.verify_release_package(package.package_root, expected_manifest_sha256=digest)
    with pytest.raises(release.AutoencoderReleaseError):
        _reopen(package, checkpoint[1], digest)


@pytest.mark.parametrize("change", ["digest", "operation", "repository_type", "upload_ready", "remote_privacy_verified", "approval_status", "cost"])
def test_sealed_plan_must_roundtrip_and_preserve_original_private_operations(checkpoint, tmp_path, change):
    package = build(checkpoint, tmp_path / "package")
    path = package.package_root / "publication-plan.json"
    data = _json(path)
    if change == "digest":
        data["plan_digest"] = "0" * 64
    else:
        if change == "operation":
            data["operations"].pop()
        elif change == "repository_type":
            data["repository_type"] = "dataset"
        elif change == "cost":
            data["cost_receipt"]["upload_bytes"] += 1
        else:
            data["metadata"][change] = "approved" if change == "approval_status" else True
        constructor = {key: value for key, value in data.items() if key in {field.name for field in fields(PublicationPlan)}}
        constructor["operations"] = tuple(PublicationFilePlan(**row) for row in data["operations"])
        data = PublicationPlan(**constructor).to_dict()
    _write(path, data)
    outer_path = package.package_root / "package-manifest.json"
    outer = _json(outer_path)
    outer["publication_plan_digest"] = data["plan_digest"]
    _write(outer_path, outer)
    digest = _reseal_outer(package)
    with pytest.raises(release.AutoencoderReleaseError):
        _reopen(package, checkpoint[1], digest)


def test_required_owner_pins_and_evaluation_filename_bytes(checkpoint, tmp_path):
    evaluation = tmp_path / "eval.json"
    evaluation.write_bytes(b'{"loss":0.25,"admitted":false}\n')
    package = build(checkpoint, tmp_path / "package", evaluation_receipts=[evaluation])
    with pytest.raises(release.AutoencoderReleaseError):
        _reopen(package, checkpoint[1], "0" * 64)
    with pytest.raises(release.AutoencoderReleaseError):
        _reopen(package, checkpoint[1], variant={"source_language": "fr"})
    changed = {**checkpoint[1], "metadata": {"different_selected_version": True}}
    from ipfs_datasets_py.duckdb_control.contracts import content_identity
    from ipfs_datasets_py.duckdb_control.autoencoder_registry import SCHEMA
    changed["version_id"] = content_identity({"schema": SCHEMA, **{key: value for key, value in changed.items() if key != "version_id"}})
    with pytest.raises(release.AutoencoderReleaseError):
        _reopen(package, changed)
    sealed_evaluation, = (package.release_root / "evaluations").iterdir()
    sealed_evaluation.write_bytes(b'{"loss":0.0,"admitted":false}\n')
    with pytest.raises(release.AutoencoderReleaseError, match="evaluation receipt hash"):
        _reopen(package, checkpoint[1], _reseal_outer(package))


def test_reopen_rejects_duplicate_json_and_sidecar_checkpoint_substitution(compact_checkpoint, tmp_path):
    package = build(compact_checkpoint, tmp_path / "package")
    path = package.release_root / "config.json"
    raw = path.read_bytes()
    path.write_bytes(raw.replace(b'"admitted":false', b'"admitted":true,"admitted":false'))
    with pytest.raises(release.AutoencoderReleaseError, match="duplicate"):
        _reopen(package, compact_checkpoint[1], _reseal_outer(package))
    path.write_bytes(raw)
    manifest = _json(package.release_root / "release-manifest.json")
    manifest["checkpoint"]["revision"] += 1
    _write(package.release_root / "release-manifest.json", manifest)
    with pytest.raises(release.AutoencoderReleaseError):
        _reopen(package, compact_checkpoint[1], _reseal_outer(package))


def test_descriptor_bounds_precede_checkpoint_read(checkpoint, tmp_path):
    package = build(checkpoint, tmp_path / "package")
    path = package.package_root / "package-manifest.json"
    value = _json(path)
    value["files"][0]["size_bytes"] = 256 * 1024 * 1024 + 1
    _write(path, value)
    with pytest.raises(release.AutoencoderReleaseError, match="bounded restore"):
        _reopen(package, checkpoint[1], hashlib.sha256(path.read_bytes()).hexdigest())


def test_compact_cannot_drop_recomputed_logical_identity(compact_checkpoint, tmp_path):
    package = build(compact_checkpoint, tmp_path / "package")
    path = package.release_root / "provenance.json"
    value = _json(path)
    value["identities"]["logical_state_identity"] = None
    _write(path, value)
    with pytest.raises(release.AutoencoderReleaseError, match="native logical identity"):
        _reopen(package, compact_checkpoint[1], _reseal_outer(package))


@pytest.mark.parametrize("extra", ["fifo", "symlink", "empty_directories", "depth", "path_bytes"])
def test_bounded_namespace_rejects_unlisted_specials_and_excess_directories_before_hashing(
    checkpoint, tmp_path, monkeypatch, extra,
):
    package = build(checkpoint, tmp_path / "package")
    if extra == "fifo":
        os.mkfifo(package.package_root / "unlisted-fifo")
    elif extra == "symlink":
        (package.package_root / "unlisted-alias").symlink_to(checkpoint[0])
    elif extra == "empty_directories":
        for index in range(257):
            (package.package_root / f"empty-{index}").mkdir()
    else:
        path = package.package_root
        for index in range(9 if extra == "depth" else 5):
            path /= str(index) if extra == "depth" else str(index) + "x" * 219
            path.mkdir()
    monkeypatch.setattr(release, "_descriptor", lambda *a, **k: pytest.fail("namespace must fail before file hashing"))
    with pytest.raises(release.AutoencoderReleaseError, match="namespace"):
        _reopen(package, checkpoint[1])


def test_strong_reopen_never_uses_unbounded_rglob(checkpoint, tmp_path, monkeypatch):
    package = build(checkpoint, tmp_path / "package")
    monkeypatch.setattr(Path, "rglob", lambda *a, **k: pytest.fail("unbounded recursive enumeration"))
    entries = release._bounded_package_paths(package.package_root)
    assert type(entries) is tuple and len(entries) <= 256
    assert all(type(path) is type(package.package_root) for path in entries)
    assert _reopen(package, checkpoint[1]) == package
