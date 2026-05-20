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


def test_wallet_api_mutation_routes(tmp_path, monkeypatch):
    client, _wallet_dir, _blob_dir = make_client(tmp_path, monkeypatch)

    wallet_response = client.post("/wallets", json={"owner_did": "did:key:owner"})
    assert wallet_response.status_code == 200
    wallet_id = wallet_response.json()["wallet_id"]

    document_response = client.post(
        f"/wallets/{wallet_id}/documents/text",
        json={
            "actor_did": "did:key:owner",
            "key_hex": "11" * 32,
            "filename": "benefits.txt",
            "title": "Benefits letter",
            "text": "SNAP approval letter and utility shutoff risk.",
        },
    )
    assert document_response.status_code == 200
    record = document_response.json()

    approval_response = client.post(
        f"/wallets/{wallet_id}/approvals",
        json={
            "requested_by": "did:key:owner",
            "operation": "grant/create",
            "resources": [f"wallet://{wallet_id}/records/{record['record_id']}"],
            "abilities": ["record/analyze"],
        },
    )
    assert approval_response.status_code == 200
    approval = approval_response.json()

    approvals_list_response = client.get(f"/wallets/{wallet_id}/approvals", params={"status": "all"})
    assert approvals_list_response.status_code == 200
    assert [item["approval_id"] for item in approvals_list_response.json()["approvals"]] == [approval["approval_id"]]

    approval_decision_response = client.post(
        f"/wallets/{wallet_id}/approvals/{approval['approval_id']}/approve",
        json={"approver_did": "did:key:owner"},
    )
    assert approval_decision_response.status_code == 200
    assert approval_decision_response.json()["status"] in {"approved", "pending"}

    grant_response = client.post(
        f"/wallets/{wallet_id}/records/{record['record_id']}/grants",
        json={
            "issuer_did": "did:key:owner",
            "issuer_key_hex": "11" * 32,
            "audience_did": "did:key:guest",
            "audience_key_hex": "22" * 32,
            "abilities": ["record/analyze"],
            "approval_id": approval["approval_id"],
            "purpose": "service_matching",
        },
    )
    assert grant_response.status_code == 200
    grant = grant_response.json()
    assert grant["audience_did"] == "did:key:guest"

    access_request_response = client.post(
        f"/wallets/{wallet_id}/access-requests",
        json={
            "record_id": record["record_id"],
            "requester_did": "did:key:guest",
            "audience_did": "did:key:guest",
            "ability": "record/analyze",
            "purpose": "service_matching",
        },
    )
    assert access_request_response.status_code == 200
    access_request = access_request_response.json()

    access_list_response = client.get(f"/wallets/{wallet_id}/access-requests", params={"status": "all"})
    assert access_list_response.status_code == 200
    assert [item["request_id"] for item in access_list_response.json()["requests"]] == [access_request["request_id"]]

    approve_access_response = client.post(
        f"/wallets/{wallet_id}/access-requests/{access_request['request_id']}/approve",
        json={
            "actor_did": "did:key:owner",
            "issuer_key_hex": "11" * 32,
            "audience_key_hex": "22" * 32,
            "issue_invocation": True,
        },
    )
    assert approve_access_response.status_code == 200
    approved_request = approve_access_response.json()
    assert approved_request["status"] == "approved"
    assert approved_request["grant_id"]
    assert approved_request["invocation_token"]


def test_wallet_api_storage_and_snapshot_routes(tmp_path, monkeypatch):
    client, _wallet_dir, _blob_dir = make_client(tmp_path, monkeypatch)

    wallet_response = client.post("/wallets", json={"owner_did": "did:key:owner"})
    assert wallet_response.status_code == 200
    wallet_id = wallet_response.json()["wallet_id"]

    document_response = client.post(
        f"/wallets/{wallet_id}/documents/text",
        json={
            "actor_did": "did:key:owner",
            "key_hex": "11" * 32,
            "filename": "benefits.txt",
            "text": "SNAP approval letter and utility shutoff risk.",
        },
    )
    assert document_response.status_code == 200
    record_id = document_response.json()["record_id"]

    snapshot_verify_response = client.get(f"/wallets/{wallet_id}/snapshot")
    assert snapshot_verify_response.status_code == 200
    assert snapshot_verify_response.json()["valid"] is True

    snapshots_list_response = client.get("/wallets/snapshots")
    assert snapshots_list_response.status_code == 200
    assert wallet_id in snapshots_list_response.json()["wallet_ids"]

    snapshot_save_response = client.post(f"/wallets/{wallet_id}/snapshot")
    assert snapshot_save_response.status_code == 200
    assert snapshot_save_response.json()["wallet_id"] == wallet_id

    snapshot_load_response = client.post(f"/wallets/{wallet_id}/snapshot/load")
    assert snapshot_load_response.status_code == 200
    assert snapshot_load_response.json()["loaded"] is True

    record_storage_response = client.get(f"/wallets/{wallet_id}/records/{record_id}/storage")
    assert record_storage_response.status_code == 200
    assert record_storage_response.json()["ok"] is True

    wallet_storage_response = client.get(f"/wallets/{wallet_id}/storage")
    assert wallet_storage_response.status_code == 200
    assert wallet_storage_response.json()["record_count"] == 1

    rotate_key_response = client.post(
        f"/wallets/{wallet_id}/records/{record_id}/rotate-key",
        json={"actor_did": "did:key:owner", "actor_key_hex": "11" * 32},
    )
    assert rotate_key_response.status_code == 200
    assert rotate_key_response.json()["record_id"] == record_id

    repair_record_response = client.post(
        f"/wallets/{wallet_id}/records/{record_id}/storage/repair",
        json={"actor_did": "did:key:owner"},
    )
    assert repair_record_response.status_code == 200
    assert repair_record_response.json()["ok"] is True

    repair_wallet_response = client.post(
        f"/wallets/{wallet_id}/storage/repair",
        json={"actor_did": "did:key:owner"},
    )
    assert repair_wallet_response.status_code == 200
    assert repair_wallet_response.json()["record_count"] == 1


def test_wallet_api_invocation_decrypt_and_analysis_routes(tmp_path, monkeypatch):
    client, _wallet_dir, _blob_dir = make_client(tmp_path, monkeypatch)

    wallet_response = client.post("/wallets", json={"owner_did": "did:key:owner"})
    assert wallet_response.status_code == 200
    wallet_id = wallet_response.json()["wallet_id"]

    document_response = client.post(
        f"/wallets/{wallet_id}/documents/text",
        json={
            "actor_did": "did:key:owner",
            "key_hex": "11" * 32,
            "filename": "benefits.txt",
            "text": "SNAP approval letter and utility shutoff risk.",
        },
    )
    assert document_response.status_code == 200
    record_id = document_response.json()["record_id"]

    approval_response = client.post(
        f"/wallets/{wallet_id}/approvals",
        json={
            "requested_by": "did:key:owner",
            "operation": "grant/create",
            "resources": [f"wallet://{wallet_id}/records/{record_id}"],
            "abilities": ["record/analyze", "record/decrypt"],
        },
    )
    assert approval_response.status_code == 200
    approval_id = approval_response.json()["approval_id"]

    approval_decision_response = client.post(
        f"/wallets/{wallet_id}/approvals/{approval_id}/approve",
        json={"approver_did": "did:key:owner"},
    )
    assert approval_decision_response.status_code == 200

    grant_response = client.post(
        f"/wallets/{wallet_id}/records/{record_id}/grants",
        json={
            "issuer_did": "did:key:owner",
            "issuer_key_hex": "11" * 32,
            "audience_did": "did:key:guest",
            "audience_key_hex": "22" * 32,
            "abilities": ["record/analyze", "record/decrypt"],
            "approval_id": approval_id,
            "output_types": ["summary", "plaintext", "redacted_derived_only"],
        },
    )
    assert grant_response.status_code == 200
    grant_id = grant_response.json()["grant_id"]

    analysis_invocation_response = client.post(
        f"/wallets/{wallet_id}/records/{record_id}/analysis-invocations",
        json={
            "grant_id": grant_id,
            "actor_did": "did:key:guest",
            "actor_key_hex": "22" * 32,
            "user_present": True,
        },
    )
    assert analysis_invocation_response.status_code == 200
    analysis_token = analysis_invocation_response.json()["token"]

    decrypt_invocation_response = client.post(
        f"/wallets/{wallet_id}/records/{record_id}/decrypt-invocations",
        json={
            "grant_id": grant_id,
            "actor_did": "did:key:guest",
            "actor_key_hex": "22" * 32,
            "user_present": True,
        },
    )
    assert decrypt_invocation_response.status_code == 200
    decrypt_token = decrypt_invocation_response.json()["token"]

    decrypt_response = client.post(
        f"/wallets/{wallet_id}/records/{record_id}/decrypt",
        json={
            "actor_did": "did:key:guest",
            "actor_key_hex": "22" * 32,
            "invocation_token": decrypt_token,
        },
    )
    assert decrypt_response.status_code == 200
    assert decrypt_response.json()["text"].startswith("SNAP approval")

    analyze_response = client.post(
        f"/wallets/{wallet_id}/records/{record_id}/analyze",
        json={
            "actor_did": "did:key:guest",
            "actor_key_hex": "22" * 32,
            "invocation_token": analysis_token,
            "max_chars": 120,
        },
    )
    assert analyze_response.status_code == 200
    assert analyze_response.json()["artifact_id"]

    redacted_response = client.post(
        f"/wallets/{wallet_id}/records/{record_id}/analyze/redacted",
        json={
            "actor_did": "did:key:guest",
            "actor_key_hex": "22" * 32,
            "grant_id": grant_id,
            "max_chars": 120,
        },
    )
    assert redacted_response.status_code == 200
    assert redacted_response.json()["artifact"]


def test_wallet_api_export_routes(tmp_path, monkeypatch):
    client, _wallet_dir, _blob_dir = make_client(tmp_path, monkeypatch)

    wallet_response = client.post("/wallets", json={"owner_did": "did:key:owner"})
    assert wallet_response.status_code == 200
    wallet_id = wallet_response.json()["wallet_id"]

    document_response = client.post(
        f"/wallets/{wallet_id}/documents/text",
        json={
            "actor_did": "did:key:owner",
            "key_hex": "11" * 32,
            "filename": "benefits.txt",
            "text": "Benefits approval document.",
        },
    )
    assert document_response.status_code == 200
    record_id = document_response.json()["record_id"]

    approval_response = client.post(
        f"/wallets/{wallet_id}/approvals",
        json={
            "requested_by": "did:key:owner",
            "operation": "grant/create",
            "resources": [f"wallet://{wallet_id}/exports"],
            "abilities": ["export/create"],
        },
    )
    assert approval_response.status_code == 200
    approval_id = approval_response.json()["approval_id"]

    approval_decision_response = client.post(
        f"/wallets/{wallet_id}/approvals/{approval_id}/approve",
        json={"approver_did": "did:key:owner"},
    )
    assert approval_decision_response.status_code == 200

    grant_response = client.post(
        f"/wallets/{wallet_id}/exports/grants",
        json={
            "issuer_did": "did:key:owner",
            "issuer_key_hex": "11" * 32,
            "audience_did": "did:key:guest",
            "audience_key_hex": "22" * 32,
            "record_ids": [record_id],
            "approval_id": approval_id,
        },
    )
    assert grant_response.status_code == 200
    grant_id = grant_response.json()["grant_id"]

    invocation_response = client.post(
        f"/wallets/{wallet_id}/exports/invocations",
        json={
            "grant_id": grant_id,
            "actor_did": "did:key:guest",
            "actor_key_hex": "22" * 32,
            "record_ids": [record_id],
            "user_present": True,
        },
    )
    assert invocation_response.status_code == 200
    invocation = invocation_response.json()
    assert invocation["actor_did"] == "did:key:guest"
    assert invocation["invocation_token"]

    bundle_response = client.post(
        f"/wallets/{wallet_id}/exports",
        json={
            "actor_did": "did:key:guest",
            "actor_key_hex": "22" * 32,
            "invocation_token": invocation["invocation_token"],
            "record_ids": [record_id],
            "include_proofs": False,
            "include_derived_artifacts": False,
        },
    )
    assert bundle_response.status_code == 200
    bundle = bundle_response.json()
    assert bundle["bundle_type"] == "wallet_export_v1"
    assert [item["record_id"] for item in bundle["records"]] == [record_id]

    verify_response = client.post("/exports/verify", json={"bundle": bundle})
    assert verify_response.status_code == 200
    assert verify_response.json()["valid"] is True

    storage_response = client.post("/exports/storage", json={"bundle": bundle})
    assert storage_response.status_code == 200
    assert storage_response.json()["ok"] is True
    assert storage_response.json()["record_count"] == 1

    import_response = client.post("/exports/import", json={"bundle": bundle})
    assert import_response.status_code == 200
    assert import_response.json()["wallet_id"] == wallet_id
    assert import_response.json()["record_count"] == 1