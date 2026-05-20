from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from ipfs_datasets_py.wallet import WalletService
from ipfs_datasets_py.wallet.api import router
import ipfs_datasets_py.wallet.api as wallet_api
from ipfs_datasets_py.wallet.storage import LocalEncryptedBlobStore


def make_client(tmp_path, monkeypatch):
    wallet_dir = tmp_path / "wallets"
    blob_dir = tmp_path / "blobs"
    monkeypatch.setattr(wallet_api, "default_wallet_dir", lambda: wallet_dir)
    monkeypatch.setattr(wallet_api, "default_blob_dir", lambda: blob_dir)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app), wallet_dir, blob_dir


def test_wallet_api_create_and_get_wallet(tmp_path, monkeypatch):
    client, wallet_dir, _blob_dir = make_client(tmp_path, monkeypatch)

    response = client.post(
        "/wallets",
        json={"owner_did": "did:key:owner", "controller_dids": ["did:key:owner"], "approval_threshold": 1},
    )

    assert response.status_code == 200
    created = response.json()
    assert created["owner_did"] == "did:key:owner"
    assert (wallet_dir / f"{created['wallet_id']}.json").exists()

    fetched = client.get(f"/wallets/{created['wallet_id']}")
    assert fetched.status_code == 200
    assert fetched.json()["wallet_id"] == created["wallet_id"]


def test_wallet_api_lists_core_wallet_state(tmp_path, monkeypatch):
    client, wallet_dir, blob_dir = make_client(tmp_path, monkeypatch)
    service = WalletService(storage_backend=LocalEncryptedBlobStore(blob_dir))
    wallet = service.create_wallet(owner_did="did:key:owner")

    document_path = tmp_path / "document.txt"
    document_path.write_text("Example document", encoding="utf-8")
    service.add_document(wallet.wallet_id, document_path, actor_did="did:key:owner")
    service.request_access(
        wallet.wallet_id,
        requester_did="did:key:guest",
        audience_did="did:key:guest",
        resources=[f"wallet://{wallet.wallet_id}"],
        abilities=["wallet/read"],
        purpose="demo",
    )
    service.create_grant(
        wallet_id=wallet.wallet_id,
        issuer_did="did:key:owner",
        audience_did="did:key:guest",
        resources=[f"wallet://{wallet.wallet_id}"],
        abilities=["wallet/read"],
    )
    wallet_dir.mkdir(parents=True, exist_ok=True)
    (wallet_dir / f"{wallet.wallet_id}.json").write_text(
        json.dumps(service.export_wallet_snapshot(wallet.wallet_id), sort_keys=True),
        encoding="utf-8",
    )

    records_response = client.get(f"/wallets/{wallet.wallet_id}/records", params={"data_type": "document"})
    assert records_response.status_code == 200
    assert len(records_response.json()["records"]) == 1

    audit_response = client.get(f"/wallets/{wallet.wallet_id}/audit")
    assert audit_response.status_code == 200
    assert len(audit_response.json()["events"]) >= 3

    access_response = client.get(
        f"/wallets/{wallet.wallet_id}/access-requests",
        params={"status": "all", "audience_did": "did:key:guest"},
    )
    assert access_response.status_code == 200
    assert len(access_response.json()["requests"]) == 1

    receipts_response = client.get(
        f"/wallets/{wallet.wallet_id}/grant-receipts",
        params={"status": "all", "audience_did": "did:key:guest"},
    )
    assert receipts_response.status_code == 200
    assert len(receipts_response.json()["receipts"]) == 1

    proofs_response = client.get(f"/wallets/{wallet.wallet_id}/proofs")
    assert proofs_response.status_code == 200
    assert proofs_response.json()["proofs"] == []