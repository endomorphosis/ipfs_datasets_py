"""Offline campaign transport: exact bytes, bounded namespaces and no execution."""
from dataclasses import fields
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket

import pytest

from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
from ipfs_datasets_py.huggingface import autoencoder_campaign_release as release
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_autoencoder_checkpoint as checkpoint
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_autoencoder_sparse_checkpoint as sparse
from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_campaign_package_inputs import _page
from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_campaign_shared_sparse_arrow import _forbid_native


def _forbidden(*args, **kwargs):
    pytest.fail("campaign transport invoked model/state execution, owner construction or network")


@pytest.fixture(autouse=True)
def no_native(monkeypatch):
    _forbid_native(monkeypatch)
    monkeypatch.setattr(checkpoint, "deserialize_checkpoint", _forbidden)
    monkeypatch.setattr(sparse, "resolve_checkpoint", _forbidden)
    monkeypatch.setattr(socket.socket, "connect", _forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", _forbidden)


@pytest.fixture
def page(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    with AutoencoderRegistry(source / "owner.duckdb", source / "artifacts") as registry:
        value = _page(registry, source / "inputs")
    return value


def _build(page, path, **kwargs):
    return release.build_campaign_package(page.generation_artifact, page.plan_artifact, path,
        **{**page.kwargs(), **kwargs})


def _read(root):
    return json.loads((root / release.MANIFEST_NAME).read_bytes())


def _digest(root):
    return hashlib.sha256((root / release.MANIFEST_NAME).read_bytes()).hexdigest()


def _seal(root, manifest):
    raw = json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()
    (root / release.MANIFEST_NAME).write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def _verify(root, digest=None, **kwargs):
    return release.verify_campaign_package(root, expected_manifest_sha256=digest or _digest(root), **kwargs)


def _bytes(root):
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def _blob(root, descriptor):
    return root / "blobs" / descriptor["sha256"][:2] / descriptor["sha256"]


def test_repeat_build_deduplicates_exact_bytes_and_identity(page, tmp_path, monkeypatch):
    copied = []
    original = release._copy_blob

    def copy(source, ref, directory):
        copied.append(ref["sha256"])
        return original(source, ref, directory)

    monkeypatch.setattr(release, "_copy_blob", copy)
    left, right = tmp_path / "left", tmp_path / "right"
    first = _build(page, left)
    per_build = list(copied)
    second = _build(page, right)
    manifest = _read(left)
    assert first["package_id"] == second["package_id"]
    assert first["package_manifest_artifact"] == second["package_manifest_artifact"]
    assert _bytes(left) == _bytes(right)
    assert per_build == [row["sha256"] for row in manifest["artifacts"]]
    assert copied == per_build * 2 and len(per_build) == len(set(per_build))
    assert first["blob_count"] == len(manifest["artifacts"])
    assert first["payload_bytes"] == sum(row["bytes"] for row in manifest["artifacts"])
    assert first["package_bytes"] == sum(map(len, _bytes(left).values()))
    for row in manifest["artifacts"]:
        assert _blob(left, row).read_bytes() == page.store.paths[row["sha256"]].read_bytes()
    assert manifest["generation_artifact"] == page.generation_artifact
    assert manifest["plan_artifact"] == page.plan_artifact
    assert manifest["variant_record"] == page.variant_record
    assert manifest["version_records"] == page.version_records
    assert manifest["run_records"] == page.run_records
    for key in ("checkpoint_semantic_replay_verified", "execution_source_manifest_verified", "execution_authorized",
                "full_source_payload_closure", "completion_history_exported", "source_authority_authenticated",
                "global_holdout_verified", "full_federal_corpus_complete", "constitution_formalized", "formalized",
                "admitted", "publication_performed", "training_performed", "weights_constructed"):
        assert first["qualification"][key] is False


def test_move_and_restore_without_original_paths_or_registry(page, tmp_path, monkeypatch):
    original, moved, restored = (tmp_path / name for name in ("original", "moved", "restored"))
    built = _build(page, original)
    expected = _bytes(original)
    original.rename(moved)
    # Delete both the original owner and detached source store after capture.
    # Only package blobs may be read from this point onward.
    shutil.rmtree(tmp_path / "source")
    monkeypatch.setattr(AutoencoderRegistry, "__init__", _forbidden)
    digest = built["package_manifest_artifact"]["sha256"]
    reopened = _verify(moved, digest)
    result = release.restore_campaign_package(moved, restored, expected_manifest_sha256=digest)
    assert result["package_id"] == reopened["package_id"] == built["package_id"]
    assert _bytes(moved) == _bytes(restored) == expected
    assert result["qualification"]["historical_absolute_paths_used"] is False
    assert result["qualification"]["execution_authorized"] is False


@pytest.mark.parametrize("field", [
    "max_control_bytes", "max_blobs", "max_blob_bytes", "max_total_bytes",
    "max_directories", "max_namespace_entries", "max_path_depth", "max_path_bytes",
])
def test_exact_namespace_and_byte_limits_pass_one_less_fails(page, tmp_path, field):
    root = tmp_path / "package"
    report = _build(page, root)
    manifest = _read(root)
    entries = list(root.rglob("*"))
    actual = {
        "max_control_bytes": (root / release.MANIFEST_NAME).stat().st_size,
        "max_blobs": len(manifest["artifacts"]),
        "max_blob_bytes": max(row["bytes"] for row in manifest["artifacts"]),
        "max_total_bytes": sum(row["bytes"] for row in manifest["artifacts"]),
        "max_directories": sum(path.is_dir() for path in entries),
        "max_namespace_entries": len(entries),
        "max_path_depth": max(len(path.relative_to(root).parts) for path in entries),
        "max_path_bytes": max(len(path.relative_to(root).as_posix().encode()) for path in entries),
    }[field]
    exact = release.CampaignPackageLimits(**{field: actual})
    assert _verify(root, limits=exact)["package_id"] == report["package_id"]
    assert actual > 1
    with pytest.raises(release.CampaignPackageError):
        _verify(root, limits=release.CampaignPackageLimits(**{field: actual - 1}))


def test_invalid_and_mutated_limits_cannot_raise_format_ceilings(page, tmp_path):
    for field in fields(release.CampaignPackageLimits):
        for value in (True, 0, field.default + 1):
            with pytest.raises(release.CampaignPackageError):
                release.CampaignPackageLimits(**{field.name: value})
    limits = release.CampaignPackageLimits()
    object.__setattr__(limits, "max_blobs", 5000)
    with pytest.raises(release.CampaignPackageError):
        _build(page, tmp_path / "never-created", limits=limits)
    assert not (tmp_path / "never-created").exists()


@pytest.mark.parametrize("field", ["max_control_bytes", "max_blobs", "max_blob_bytes", "max_total_bytes", "max_directories", "max_namespace_entries"])
def test_bounded_preparation_rejects_before_destination_creation(page, tmp_path, field):
    destination = tmp_path / "never-created"
    with pytest.raises(release.CampaignPackageError):
        _build(page, destination, limits=release.CampaignPackageLimits(**{field: 1}))
    assert not destination.exists()


@pytest.mark.parametrize("change", ["extra_file", "empty_directory", "deep_empty_directory", "symlink", "fifo", "missing", "corrupt"])
def test_exact_namespace_rejects_missing_extra_special_or_changed_blobs(page, tmp_path, change, monkeypatch):
    root = tmp_path / "package"
    built = _build(page, root)
    digest = built["package_manifest_artifact"]["sha256"]
    manifest = _read(root)
    if change == "extra_file":
        (root / "unlisted").write_bytes(b"unexpected")
    elif change == "empty_directory":
        (root / "empty").mkdir()
    elif change == "deep_empty_directory":
        (root / "blobs" / "unexpected" / "a" / "b").mkdir(parents=True)
    elif change == "symlink":
        (root / "external").symlink_to(tmp_path / "source", target_is_directory=True)
    elif change == "fifo":
        os.mkfifo(root / "named-pipe")
    else:
        target = _blob(root, manifest["artifacts"][0])
        if change == "missing":
            target.unlink()
        else:
            data = target.read_bytes()
            target.write_bytes(bytes([data[0] ^ 1]) + data[1:])
    if change != "corrupt":
        monkeypatch.setattr(release, "_inspect", _forbidden)
    with pytest.raises(release.CampaignPackageError):
        _verify(root, digest)


@pytest.mark.parametrize("change", ["unknown_field", "unknown_role", "changed_coverage", "claimed_admission", "duplicate_blob", "unsafe_locator", "raised_limit"])
def test_resealed_control_cannot_expand_typed_closure_or_qualification(page, tmp_path, change):
    root = tmp_path / "package"
    _build(page, root)
    manifest = _read(root)
    if change == "unknown_field":
        manifest["files"] = []
    elif change == "unknown_role":
        manifest["artifacts"][0]["roles"] = ["unverified-flat-file"]
    elif change == "changed_coverage":
        manifest["coverage"]["selected_training_input_count"] += 1
    elif change == "claimed_admission":
        manifest["qualification"]["admitted"] = True
    elif change == "duplicate_blob":
        manifest["artifacts"].append(dict(manifest["artifacts"][0]))
    elif change == "unsafe_locator":
        manifest["artifacts"][0]["path"] = "../../outside"
    else:
        manifest["limits"]["max_blobs"] += 1
    with pytest.raises(release.CampaignPackageError):
        _verify(root, _seal(root, manifest))


def test_coherent_extra_blob_is_not_authorized_by_flat_manifest(page, tmp_path, monkeypatch):
    root = tmp_path / "package"
    _build(page, root)
    manifest = _read(root)
    unrelated = b"not a typed dependency\n"
    ref = {"sha256": hashlib.sha256(unrelated).hexdigest(), "bytes": len(unrelated), "roles": ["corpus_source"]}
    path = _blob(root, ref)
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(unrelated)
    manifest["artifacts"].append(ref)
    manifest["artifacts"].sort(key=lambda row: row["sha256"])
    original = release._hash_file

    def only_authorized(path, descriptor):
        assert descriptor["sha256"] != ref["sha256"], "generic hashing authorized an extra flat blob"
        return original(path, descriptor)

    monkeypatch.setattr(release, "_hash_file", only_authorized)
    with pytest.raises(release.CampaignPackageError, match="closure"):
        _verify(root, _seal(root, manifest))


@pytest.mark.parametrize("role", ["corpus_source", "embedding_receipt", "base_checkpoint"])
def test_missing_template_or_job_dependency_cannot_fall_back_to_historical_paths(page, tmp_path, role):
    root = tmp_path / "package"
    _build(page, root)
    manifest = _read(root)
    row = next(row for row in manifest["artifacts"] if role in row["roles"])
    _blob(root, row).unlink()
    # Preserve otherwise complete directory structure; no original CAS fallback.
    with pytest.raises(release.CampaignPackageError):
        _verify(root)


@pytest.mark.parametrize("operation", ["build", "restore"])
def test_existing_or_aliased_destination_is_never_adopted(page, tmp_path, operation):
    source = tmp_path / "package"
    built = _build(page, source)
    existing = tmp_path / "existing"
    existing.mkdir()
    marker = existing / "keep"
    marker.write_bytes(b"user data")
    real = tmp_path / "real"
    real.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(real, target_is_directory=True)
    for destination in (existing, alias / "new"):
        with pytest.raises(release.CampaignPackageError):
            if operation == "build":
                _build(page, destination)
            else:
                release.restore_campaign_package(source, destination,
                    expected_manifest_sha256=built["package_manifest_artifact"]["sha256"])
    assert marker.read_bytes() == b"user data" and not (real / "new").exists()


@pytest.mark.parametrize("operation", ["build", "restore"])
def test_stream_interruption_retains_destination_and_retry_refuses_it(page, tmp_path, monkeypatch, operation):
    original = tmp_path / "package"
    built = _build(page, original)
    destination = tmp_path / "interrupted"
    copy = release._copy_blob
    calls = []

    def interrupted(source, ref, directory):
        copy(source, ref, directory)
        calls.append(ref["sha256"])
        raise RuntimeError("injected copy interruption")

    def run():
        if operation == "build":
            return _build(page, destination)
        return release.restore_campaign_package(original, destination,
            expected_manifest_sha256=built["package_manifest_artifact"]["sha256"])

    with monkeypatch.context() as local:
        local.setattr(release, "_copy_blob", interrupted)
        with pytest.raises(RuntimeError, match="injected copy interruption"):
            run()
    assert len(calls) == 1 and destination.is_dir()
    assert not (destination / release.MANIFEST_NAME).exists()
    incomplete = _bytes(destination)
    with pytest.raises(release.CampaignPackageError):
        run()
    assert _bytes(destination) == incomplete


@pytest.mark.parametrize("operation", ["build", "restore"])
def test_later_copy_cannot_conceal_earlier_source_mutation(page, tmp_path, monkeypatch, operation):
    source = tmp_path / "package"
    built = _build(page, source)
    destination = tmp_path / "rejected"
    original = release._copy_blob
    copied = []

    def copy(path, ref, directory):
        original(path, ref, directory)
        copied.append(Path(path))
        if len(copied) == 2:
            data = copied[0].read_bytes()
            copied[0].write_bytes(bytes([data[0] ^ 1]) + data[1:])

    monkeypatch.setattr(release, "_copy_blob", copy)
    with pytest.raises(release.CampaignPackageError):
        if operation == "build":
            _build(page, destination)
        else:
            release.restore_campaign_package(source, destination,
                expected_manifest_sha256=built["package_manifest_artifact"]["sha256"])
    assert len(copied) >= 2
    assert not (destination / release.MANIFEST_NAME).exists()


def test_destination_corruption_during_copy_is_rejected_on_reopen(page, tmp_path, monkeypatch):
    original = release._copy_blob
    changed = False

    def copy(source, ref, directory):
        nonlocal changed
        original(source, ref, directory)
        if not changed:
            changed = True
            # Use the already-open destination descriptor, never an external path.
            path = "blobs/" + ref["sha256"][:2] + "/" + ref["sha256"]
            fd = os.open(path, os.O_WRONLY | os.O_NOFOLLOW, dir_fd=directory)
            try:
                os.write(fd, b"!")
            finally:
                os.close(fd)

    monkeypatch.setattr(release, "_copy_blob", copy)
    with pytest.raises(release.CampaignPackageError):
        _build(page, tmp_path / "rejected")
    assert changed


@pytest.mark.parametrize("form", ["whitespace", "duplicate_key", "nonfinite"])
def test_noncanonical_manifest_rejected_even_with_matching_digest(page, tmp_path, form):
    root = tmp_path / "package"
    _build(page, root)
    path = root / release.MANIFEST_NAME
    raw = path.read_bytes()
    if form == "whitespace":
        raw += b"\n"
    elif form == "duplicate_key":
        raw = b'{"schema_version":"ignored",' + raw[1:]
    else:
        raw = b'{"nonfinite":NaN,' + raw[1:]
    path.write_bytes(raw)
    with pytest.raises(release.CampaignPackageError):
        _verify(root)


def test_restore_rejects_descendant_destination_without_mutating_source(page, tmp_path):
    root = tmp_path / "package"
    report = _build(page, root)
    before = _bytes(root)
    with pytest.raises(release.CampaignPackageError, match="outside"):
        release.restore_campaign_package(root, root / "nested-copy",
            expected_manifest_sha256=report["package_manifest_artifact"]["sha256"])
    assert not (root / "nested-copy").exists()
    assert _bytes(root) == before


@pytest.mark.parametrize("digest", [None, True, "a" * 63, "A" * 64, "0" * 64])
def test_verification_requires_exact_external_manifest_digest(page, tmp_path, digest):
    root = tmp_path / "package"
    _build(page, root)
    with pytest.raises(release.CampaignPackageError):
        release.verify_campaign_package(root, expected_manifest_sha256=digest)
