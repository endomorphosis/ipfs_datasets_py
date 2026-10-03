"""Bounded native CAS reads; fixtures assert storage behavior, not model quality."""
import os

import pytest

from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry, RegistryError


@pytest.fixture
def artifact(tmp_path):
    with AutoencoderRegistry(tmp_path / "registry.duckdb", tmp_path / "cas") as registry:
        source = tmp_path / "source.json"
        source.write_bytes(b'{"data":"immutable"}')
        reference = registry.stage_artifact(source)
        yield registry, reference, source.read_bytes()


def test_exact_read_is_independent_of_source_and_path_replacement(artifact, monkeypatch):
    registry, reference, body = artifact
    path = registry.artifact_path(reference)
    original = os.read
    replaced = False

    def replace_after_open(fd, count):
        nonlocal replaced
        if not replaced:
            replacement = path.with_name("replacement")
            replacement.write_bytes(b"changed after the descriptor was opened")
            replacement.replace(path)
            replaced = True
        return original(fd, count)

    with monkeypatch.context() as patch:
        patch.setattr(os, "read", replace_after_open)
        assert registry.read_artifact(reference, max_bytes=len(body)) == body
    with pytest.raises(RegistryError, match="regular file"):
        registry.read_artifact(reference, max_bytes=len(body))


@pytest.mark.parametrize("limit", [True, False, 0, -1, 2.5, "64", None])
def test_invalid_consumer_bounds_refuse_before_open(artifact, monkeypatch, limit):
    registry, reference, _ = artifact
    with monkeypatch.context() as patch:
        patch.setattr(os, "open", lambda *a, **k: pytest.fail("invalid bound opened the CAS"))
        with pytest.raises(RegistryError, match="positive exact integer"):
            registry.read_artifact(reference, max_bytes=limit)


def test_effective_bound_is_minimum_of_owner_and_consumer(artifact, monkeypatch):
    registry, reference, body = artifact
    with monkeypatch.context() as patch:
        patch.setattr(os, "open", lambda *a, **k: pytest.fail("oversized descriptor opened the CAS"))
        with pytest.raises(RegistryError, match="consumer read bound"):
            registry.read_artifact(reference, max_bytes=len(body) - 1)
        registry.max_artifact_bytes = len(body) - 1
        with pytest.raises(RegistryError, match="consumer read bound"):
            registry.read_artifact(reference, max_bytes=1024)


@pytest.mark.parametrize("fault", ["fifo", "directory", "oversized", "truncated", "file_symlink", "prefix_symlink", "root_symlink"])
def test_bad_files_refuse_without_reading(artifact, monkeypatch, tmp_path, fault):
    registry, reference, body = artifact
    path = registry.artifact_path(reference)
    if fault in {"prefix_symlink", "root_symlink"}:
        directory = path.parent if fault == "prefix_symlink" else registry.artifact_root
        moved = tmp_path / "moved"
        directory.rename(moved)
        directory.symlink_to(moved, target_is_directory=True)
    else:
        path.unlink()
        if fault == "fifo":
            os.mkfifo(path)
        elif fault == "directory":
            path.mkdir()
        elif fault == "file_symlink":
            target = tmp_path / "alias.json"
            target.write_bytes(body)
            path.symlink_to(target)
        else:
            path.write_bytes(body + b"x" if fault == "oversized" else body[:-1])
    with monkeypatch.context() as patch:
        patch.setattr(os, "read", lambda *a, **k: pytest.fail("nonregular or oversized CAS object was read"))
        with pytest.raises(RegistryError):
            registry.read_artifact(reference, max_bytes=1024)


def test_same_size_corruption_is_hashed_before_return(artifact):
    registry, reference, body = artifact
    registry.artifact_path(reference).write_bytes(b"x" * len(body))
    with pytest.raises(RegistryError, match="digest mismatch"):
        registry.read_artifact(reference, max_bytes=1024)


def test_growth_after_open_never_reads_past_declared_size_plus_one(artifact, monkeypatch):
    registry, reference, body = artifact
    path = registry.artifact_path(reference)
    original = os.read
    counts = []

    def grow(fd, count):
        if not counts:
            with path.open("ab") as stream:
                stream.write(b"x" * 4096)
        counts.append(count)
        return original(fd, count)

    with monkeypatch.context() as patch:
        patch.setattr(os, "read", grow)
        with pytest.raises(RegistryError, match="digest mismatch"):
            registry.read_artifact(reference, max_bytes=1024)
    assert counts == [len(body) + 1]


def test_large_valid_artifact_uses_bounded_reads_and_checks_owner(artifact, monkeypatch, tmp_path):
    registry, _, _ = artifact
    body = b"x" * (2 * 1024**2 + 1)
    source = tmp_path / "large.bin"
    source.write_bytes(body)
    reference = registry.stage_artifact(source)
    original = os.read
    counts = []

    def measured(fd, count):
        counts.append(count)
        return original(fd, count)

    with monkeypatch.context() as patch:
        patch.setattr(os, "read", measured)
        assert registry.read_artifact(reference, max_bytes=len(body)) == body
    assert max(counts) <= 1024**2 and len(counts) == 4
    registry.close()
    with pytest.raises(RegistryError, match="closed"):
        registry.read_artifact(reference, max_bytes=len(body))


@pytest.mark.parametrize("consumer", ["source_generation", "prior_generation", "resident_run", "model_generation", "projection"])
@pytest.mark.parametrize("fault", ["fifo", "oversized", "corrupt"])
def test_model_replay_consumers_use_bounded_native_reader(artifact, monkeypatch, consumer, fault):
    from ipfs_datasets_py.logic.software_contracts import codebase_source_384 as source
    from ipfs_datasets_py.logic.software_contracts import codebase_prior_384 as prior
    from ipfs_datasets_py.logic.software_contracts import codebase_resident_inference as resident
    from ipfs_datasets_py.logic.software_contracts import codebase_model_generation as generation

    registry, reference, body = artifact
    path = registry.artifact_path(reference)
    path.unlink()
    if fault == "fifo":
        os.mkfifo(path)
    else:
        path.write_bytes(b"x" * (len(body) + (1 if fault == "oversized" else 0)))
    monkeypatch.setattr(registry, "get_version", lambda _: {"artifact": reference})
    monkeypatch.setattr(registry, "verify_artifact", lambda *_: pytest.fail("unbounded preliminary hash invoked"))
    with pytest.raises(RegistryError):
        if consumer == "source_generation":
            source._read_generation(registry, "fixture")
        elif consumer == "prior_generation":
            prior.load(None, registry, "fixture")
        elif consumer == "model_generation":
            generation.load_generation(None, registry, "fixture")
        elif consumer == "projection":
            prior.load_projection(None, registry, reference, expected_head=None,
                                  version_id=None, paths=None, embedding_snapshot=None)
        else:
            resident._load_run(None, registry, reference, None, None, None)
