"""Reject malformed peer manifest files before an unbounded artifact read."""
import hashlib
import os

import pytest

from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
from ipfs_datasets_py.logic.software_contracts import codebase_peer_recovery as recovery
from ipfs_datasets_py.logic.software_contracts import codebase_source_training as source


@pytest.mark.parametrize("fault", ["fifo", "oversized", "file_symlink", "directory_symlink", "mutated_body"])
def test_manifest_rejects_nonregular_or_unbounded_body(tmp_path, monkeypatch, fault):
    registry = AutoencoderRegistry(tmp_path / "registry.duckdb", tmp_path / "artifacts")
    raw = b"{}"
    descriptor = {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
    path = registry.artifact_path(descriptor)
    path.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(registry, "verify_artifact", lambda *_: pytest.fail("unbounded general reader invoked"))
    if fault == "fifo":
        os.mkfifo(path)
    elif fault == "oversized":
        path.write_bytes(b"x" * (recovery.MAX_MANIFEST_BYTES + 1))
    elif fault == "file_symlink":
        target = tmp_path / "other.json"; target.write_bytes(raw)
        path.symlink_to(target)
    elif fault == "mutated_body":
        path.write_bytes(b"!?")
    else:
        path.parent.rmdir()
        target = tmp_path / "other"; target.mkdir()
        (target / path.name).write_bytes(raw)
        path.parent.symlink_to(target, target_is_directory=True)
    try:
        with pytest.raises((source.CodebaseFeatureTrainingError, OSError)):
            recovery._read_manifest(registry, descriptor)
    finally:
        registry.close()
