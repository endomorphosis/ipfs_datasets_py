from __future__ import annotations

import json
import os

os.environ.setdefault("IPFS_DATASETS_AUTO_INSTALL", "false")
os.environ.setdefault("IPFS_AUTO_INSTALL", "false")
os.environ.setdefault("IPFS_DATASETS_PY_MINIMAL_IMPORTS", "1")

import pytest

from ipfs_datasets_py.wallet import LocalWalletRepository, WalletService
from ipfs_datasets_py.wallet.crypto import random_key


OWNER = "did:key:owner"


def test_local_wallet_repository_saves_atomically_and_loads_all(tmp_path):
    owner_secret = random_key()
    storage_dir = tmp_path / "blobs"
    repository = LocalWalletRepository(tmp_path / "repository")
    service = WalletService(storage_dir=storage_dir)
    wallet = service.create_wallet(owner_did=OWNER)
    record = service.add_record(
        wallet.wallet_id,
        data_type="document",
        plaintext=b"persisted wallet repository payload",
        actor_did=OWNER,
        actor_secret=owner_secret,
        private_metadata={"filename": "repository.txt"},
    )

    [path] = repository.save_all(service)
    payload = json.loads(path.read_text(encoding="utf-8"))
    report = repository.verify(wallet.wallet_id)

    assert path.exists()
    assert not path.with_name(f".{path.name}.tmp").exists()
    assert payload["snapshot_type"] == "wallet_repository_snapshot_v1"
    assert payload["wallet_id"] == wallet.wallet_id
    assert payload["snapshot_hash"] == repository.snapshot_hash(payload["snapshot"])
    assert report["valid"] is True
    assert report["snapshot_hash"] == payload["snapshot_hash"]
    assert repository.list_wallet_ids() == [wallet.wallet_id]

    restored = WalletService(storage_dir=storage_dir)
    loaded_wallet_ids = repository.load_all(restored)
    plaintext = restored.decrypt_record(
        wallet.wallet_id,
        record.record_id,
        actor_did=OWNER,
        actor_secret=owner_secret,
    )

    assert loaded_wallet_ids == [wallet.wallet_id]
    assert plaintext == b"persisted wallet repository payload"


def test_local_wallet_repository_rejects_tampered_snapshot(tmp_path):
    repository = LocalWalletRepository(tmp_path / "repository")
    service = WalletService(storage_dir=tmp_path / "blobs")
    wallet = service.create_wallet(owner_did=OWNER)
    path = repository.save(service, wallet.wallet_id)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["snapshot"]["wallet"]["owner_did"] = "did:key:attacker"
    path.write_text(json.dumps(payload), encoding="utf-8")

    report = repository.verify(wallet.wallet_id)

    assert report["valid"] is False
    assert report["snapshot_hash"] != report["computed_hash"]
    with pytest.raises(ValueError, match="hash verification"):
        repository.load(WalletService(storage_dir=tmp_path / "blobs"), wallet.wallet_id)
