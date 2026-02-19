from __future__ import annotations

from pathlib import Path

import pytest

from ipfs_datasets_py.logic.zkp.setup_artifacts import store_groth16_setup_artifacts_in_ipfs


class _FakeIPFSBackend:
    def __init__(self):
        self.added: list[tuple[str, bool, bool]] = []

    def add_path(self, path: str, *, recursive: bool = True, pin: bool = True, chunker=None) -> str:
        self.added.append((path, recursive, pin))
        # Deterministic, test-friendly CID-ish string
        return f"cid:{Path(path).name}"


def test_store_groth16_setup_artifacts_in_ipfs_adds_both_files(tmp_path: Path):
    pk = tmp_path / "proving_key.bin"
    vk = tmp_path / "verifying_key.bin"
    pk.write_bytes(b"pk")
    vk.write_bytes(b"vk")

    manifest = {
        "schema_version": 1,
        "version": 1,
        "proving_key_path": str(pk),
        "verifying_key_path": str(vk),
        "vk_hash_hex": "a" * 64,
    }

    backend = _FakeIPFSBackend()
    out = store_groth16_setup_artifacts_in_ipfs(manifest, backend_instance=backend, pin=True)

    assert out["proving_key_cid"] == "cid:proving_key.bin"
    assert out["verifying_key_cid"] == "cid:verifying_key.bin"

    assert backend.added == [
        (str(pk), False, True),
        (str(vk), False, True),
    ]


def test_store_groth16_setup_artifacts_in_ipfs_rejects_missing_paths(tmp_path: Path):
    manifest = {
        "schema_version": 1,
        "version": 1,
        "proving_key_path": str(tmp_path / "missing_pk.bin"),
        "verifying_key_path": str(tmp_path / "missing_vk.bin"),
        "vk_hash_hex": "a" * 64,
    }

    backend = _FakeIPFSBackend()
    with pytest.raises(FileNotFoundError):
        store_groth16_setup_artifacts_in_ipfs(manifest, backend_instance=backend)
