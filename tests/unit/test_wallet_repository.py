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


def test_local_wallet_repository_persists_analytics_ledger(tmp_path):
    repository = LocalWalletRepository(tmp_path / "repository")
    service = WalletService(storage_dir=tmp_path / "blobs")
    wallet1 = service.create_wallet(owner_did="did:key:owner1")
    wallet2 = service.create_wallet(owner_did="did:key:owner2")
    template = service.create_analytics_template(
        template_id="repository_analytics_v1",
        title="Repository analytics",
        purpose="Persistence coverage",
        allowed_record_types=["location", "need"],
        allowed_derived_fields=["county", "need_category"],
        aggregation_policy={"min_cohort_size": 2, "epsilon_budget": 0.5},
        created_by="did:key:analyst",
    )
    for wallet, owner in [(wallet1, "did:key:owner1"), (wallet2, "did:key:owner2")]:
        consent = service.create_analytics_consent(
            wallet.wallet_id,
            actor_did=owner,
            template_id=template.template_id,
            allowed_record_types=["location", "need"],
            allowed_derived_fields=["county", "need_category"],
        )
        service.create_analytics_contribution(
            wallet.wallet_id,
            actor_did=owner,
            consent_id=consent.consent_id,
            template_id=template.template_id,
            fields={"county": "Multnomah", "need_category": "housing"},
        )
    result = service.run_aggregate_count_by_fields(
        template.template_id,
        group_by=["county", "need_category"],
        epsilon=0.25,
    )

    repository.save_all(service)
    ledger_report = repository.verify_analytics_ledger()
    ledger_payload = json.loads(repository.analytics_ledger_path().read_text(encoding="utf-8"))
    restored = WalletService(storage_dir=tmp_path / "blobs")
    loaded_wallet_ids = repository.load_all(restored)

    assert ledger_report["valid"] is True
    assert ledger_payload["snapshot_type"] == "wallet_repository_analytics_ledger_v1"
    assert ledger_payload["snapshot_hash"] == repository.snapshot_hash(ledger_payload["ledger"])
    assert loaded_wallet_ids == sorted([wallet1.wallet_id, wallet2.wallet_id])
    assert restored.analytics_templates[template.template_id].status == "approved"
    assert len(restored.analytics_consents) == 2
    assert len(restored.analytics_contributions) == 2
    assert restored.aggregate_results[result.result_id].group_by == ["county", "need_category"]
    assert restored.analytics_query_budget_spent[f"template:{template.template_id}:group:county,need_category"] == 0.25


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
