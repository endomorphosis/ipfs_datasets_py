from __future__ import annotations

import base64
import hashlib
import hmac
import json
from pathlib import Path
import time

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


def make_magic_ucan(wallet_id: str, *, expires_in_ms: int = 60_000) -> str:
    encoded = base64.urlsafe_b64encode(
        json.dumps(
            {
                "profile": "abby-magic-ucan-v1",
                "walletId": wallet_id,
                "aud": "did:abby:contact:test",
                "capabilities": [
                    {
                        "can": "wallet/recovery/read_encrypted",
                        "with": f"wallet://{wallet_id}/recovery-bundles/*",
                    }
                ],
                "expiresAt": int(time.time() * 1000) + expires_in_ms,
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).decode("ascii").rstrip("=")
    signature = base64.urlsafe_b64encode(
        hmac.new(
            b"test-secret",
            f"abby-magic-ucan-v1.{encoded}".encode("utf-8"),
            hashlib.sha256,
        ).digest()
    ).decode("ascii").rstrip("=")
    return f"abby-magic-ucan-v1.{encoded}.{signature}"


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


def test_wallet_api_delegate_grant_route(tmp_path, monkeypatch):
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
            "abilities": ["record/analyze", "record/share"],
        },
    )
    assert approval_response.status_code == 200
    approval_id = approval_response.json()["approval_id"]

    approval_decision_response = client.post(
        f"/wallets/{wallet_id}/approvals/{approval_id}/approve",
        json={"approver_did": "did:key:owner"},
    )
    assert approval_decision_response.status_code == 200

    parent_grant_response = client.post(
        f"/wallets/{wallet_id}/records/{record_id}/grants",
        json={
            "issuer_did": "did:key:owner",
            "issuer_key_hex": "11" * 32,
            "audience_did": "did:key:delegate",
            "audience_key_hex": "22" * 32,
            "abilities": ["record/analyze", "record/share"],
            "approval_id": approval_id,
            "max_delegation_depth": 1,
            "output_types": ["summary"],
        },
    )
    assert parent_grant_response.status_code == 200
    parent_grant_id = parent_grant_response.json()["grant_id"]

    delegated_grant_response = client.post(
        f"/wallets/{wallet_id}/grants/{parent_grant_id}/delegate",
        json={
            "issuer_did": "did:key:delegate",
            "issuer_key_hex": "22" * 32,
            "audience_did": "did:key:viewer",
            "audience_key_hex": "33" * 32,
            "resources": [f"wallet://{wallet_id}/records/{record_id}"],
            "abilities": ["record/analyze"],
            "caveats": {"purpose": "service_matching", "output_types": ["summary"]},
        },
    )
    assert delegated_grant_response.status_code == 200
    delegated_grant = delegated_grant_response.json()
    assert delegated_grant["audience_did"] == "did:key:viewer"
    assert parent_grant_id in delegated_grant.get("proof_chain", [])


def test_wallet_api_revoke_and_emergency_revoke_routes(tmp_path, monkeypatch):
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

    grant_approval_response = client.post(
        f"/wallets/{wallet_id}/approvals",
        json={
            "requested_by": "did:key:owner",
            "operation": "grant/create",
            "resources": [f"wallet://{wallet_id}/records/{record_id}"],
            "abilities": ["record/analyze"],
        },
    )
    assert grant_approval_response.status_code == 200
    grant_approval_id = grant_approval_response.json()["approval_id"]

    grant_approval_decision_response = client.post(
        f"/wallets/{wallet_id}/approvals/{grant_approval_id}/approve",
        json={"approver_did": "did:key:owner"},
    )
    assert grant_approval_decision_response.status_code == 200

    first_grant_response = client.post(
        f"/wallets/{wallet_id}/records/{record_id}/grants",
        json={
            "issuer_did": "did:key:owner",
            "issuer_key_hex": "11" * 32,
            "audience_did": "did:key:guest1",
            "audience_key_hex": "22" * 32,
            "abilities": ["record/analyze"],
            "approval_id": grant_approval_id,
        },
    )
    assert first_grant_response.status_code == 200
    first_grant_id = first_grant_response.json()["grant_id"]

    second_grant_response = client.post(
        f"/wallets/{wallet_id}/records/{record_id}/grants",
        json={
            "issuer_did": "did:key:owner",
            "issuer_key_hex": "11" * 32,
            "audience_did": "did:key:guest2",
            "audience_key_hex": "33" * 32,
            "abilities": ["record/analyze"],
            "approval_id": grant_approval_id,
        },
    )
    assert second_grant_response.status_code == 200
    second_grant_id = second_grant_response.json()["grant_id"]

    revoke_response = client.post(
        f"/wallets/{wallet_id}/grants/{first_grant_id}/revoke",
        json={"actor_did": "did:key:owner"},
    )
    assert revoke_response.status_code == 200
    assert revoke_response.json()["status"] == "revoked"

    emergency_approval_response = client.post(
        f"/wallets/{wallet_id}/approvals",
        json={
            "requested_by": "did:key:owner",
            "operation": "wallet/emergency_revoke",
            "resources": [f"wallet://{wallet_id}"],
            "abilities": [],
        },
    )
    assert emergency_approval_response.status_code == 200
    emergency_approval_id = emergency_approval_response.json()["approval_id"]

    emergency_approval_decision_response = client.post(
        f"/wallets/{wallet_id}/approvals/{emergency_approval_id}/approve",
        json={"approver_did": "did:key:owner"},
    )
    assert emergency_approval_decision_response.status_code == 200

    emergency_revoke_response = client.post(
        f"/wallets/{wallet_id}/emergency-revoke",
        json={
            "actor_did": "did:key:owner",
            "actor_key_hex": "11" * 32,
            "approval_id": emergency_approval_id,
            "rotate_keys": False,
            "reason": "incident response test",
        },
    )
    assert emergency_revoke_response.status_code == 200
    report = emergency_revoke_response.json()
    assert second_grant_id in report["revoked_grant_ids"]
    assert report["revoked_grant_count"] >= 1


def test_wallet_api_admin_mutation_routes(tmp_path, monkeypatch):
    client, _wallet_dir, _blob_dir = make_client(tmp_path, monkeypatch)

    wallet_response = client.post("/wallets", json={"owner_did": "did:key:owner"})
    assert wallet_response.status_code == 200
    wallet_id = wallet_response.json()["wallet_id"]

    def admin_approval(operation: str, requested_by: str = "did:key:owner") -> str:
        approval_response = client.post(
            f"/wallets/{wallet_id}/approvals",
            json={
                "requested_by": requested_by,
                "operation": operation,
                "resources": [f"wallet://{wallet_id}"],
                "abilities": ["wallet/admin"],
            },
        )
        assert approval_response.status_code == 200
        approval_id = approval_response.json()["approval_id"]
        approval_decision_response = client.post(
            f"/wallets/{wallet_id}/approvals/{approval_id}/approve",
            json={"approver_did": requested_by},
        )
        assert approval_decision_response.status_code == 200
        return approval_id

    add_controller_response = client.post(
        f"/wallets/{wallet_id}/controllers",
        json={
            "actor_did": "did:key:owner",
            "controller_did": "did:key:controller2",
            "approval_id": admin_approval("wallet/controller_add"),
        },
    )
    assert add_controller_response.status_code == 200
    assert "did:key:controller2" in add_controller_response.json()["controller_dids"]

    remove_controller_response = client.post(
        f"/wallets/{wallet_id}/controllers/remove",
        json={
            "actor_did": "did:key:owner",
            "controller_did": "did:key:controller2",
            "approval_id": admin_approval("wallet/controller_remove"),
        },
    )
    assert remove_controller_response.status_code == 200
    assert "did:key:controller2" not in remove_controller_response.json()["controller_dids"]

    add_first_device_response = client.post(
        f"/wallets/{wallet_id}/devices",
        json={
            "actor_did": "did:key:owner",
            "device_did": "did:key:device1",
            "approval_id": admin_approval("wallet/device_add"),
        },
    )
    assert add_first_device_response.status_code == 200

    add_second_device_response = client.post(
        f"/wallets/{wallet_id}/devices",
        json={
            "actor_did": "did:key:owner",
            "device_did": "did:key:device2",
            "approval_id": admin_approval("wallet/device_add"),
        },
    )
    assert add_second_device_response.status_code == 200

    revoke_device_response = client.post(
        f"/wallets/{wallet_id}/devices/revoke",
        json={
            "actor_did": "did:key:owner",
            "device_did": "did:key:device2",
            "approval_id": admin_approval("wallet/device_revoke"),
        },
    )
    assert revoke_device_response.status_code == 200
    assert "did:key:device2" not in revoke_device_response.json()["device_dids"]

    recovery_policy_response = client.post(
        f"/wallets/{wallet_id}/recovery-policy",
        json={
            "actor_did": "did:key:owner",
            "contact_dids": ["did:key:recovery1"],
            "threshold": 1,
            "approval_id": admin_approval("wallet/recovery_policy_set"),
        },
    )
    assert recovery_policy_response.status_code == 200
    assert recovery_policy_response.json()["governance_policy"]["recovery_policy"]["threshold"] == 1

    recover_controller_response = client.post(
        f"/wallets/{wallet_id}/controllers/recover",
        json={
            "actor_did": "did:key:recovery1",
            "controller_did": "did:key:controller3",
            "approval_id": admin_approval("wallet/controller_recover", requested_by="did:key:recovery1"),
        },
    )
    assert recover_controller_response.status_code == 200
    assert "did:key:controller3" in recover_controller_response.json()["controller_dids"]


def test_wallet_api_recovery_bundle_routes(tmp_path, monkeypatch):
    monkeypatch.setenv("WALLET_MAGIC_LOGIN_SECRET", "test-secret")
    client, _wallet_dir, _blob_dir = make_client(tmp_path, monkeypatch)

    wallet_response = client.post("/wallets", json={"owner_did": "did:key:owner"})
    assert wallet_response.status_code == 200
    wallet_id = wallet_response.json()["wallet_id"]

    store_response = client.post(
        f"/wallets/{wallet_id}/recovery-bundles",
        json={
            "actor_did": "did:key:owner",
            "encrypted_bundle": {"ciphertext": "abc123", "wrapped_key": "keywrap"},
            "wrapping_method": "passphrase",
            "kdf": {"name": "argon2id"},
            "recovery_hint": "local test bundle",
            "public_metadata": {"device": "browser"},
        },
    )
    assert store_response.status_code == 200
    bundle = store_response.json()["bundle"]

    headers = {"authorization": f"Bearer {make_magic_ucan(wallet_id)}"}

    latest_response = client.get(f"/wallets/{wallet_id}/recovery-bundles/latest", headers=headers)
    assert latest_response.status_code == 200
    assert latest_response.json()["bundle"]["bundle_id"] == bundle["bundle_id"]
    assert latest_response.json()["privacy"]["server_can_decrypt"] is False

    get_response = client.get(
        f"/wallets/{wallet_id}/recovery-bundles/{bundle['bundle_id']}",
        headers=headers,
    )
    assert get_response.status_code == 200
    assert get_response.json()["bundle"]["recovery_hint"] == "local test bundle"


def test_wallet_api_record_metadata_and_delete_routes(tmp_path, monkeypatch):
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

    metadata_response = client.patch(
        f"/wallets/{wallet_id}/records/{record_id}/metadata",
        json={
            "actor_did": "did:key:owner",
            "metadata": {
                "fileName": "benefits-letter.txt",
                "privacyProfileStatus": "ready",
                "ipfsCid": "bafybeigdyrztmetadataexample1234567890",
            },
        },
    )
    assert metadata_response.status_code == 200
    assert metadata_response.json()["metadata"]["fileName"] == "benefits-letter.txt"

    records_response = client.get(f"/wallets/{wallet_id}/records")
    assert records_response.status_code == 200
    assert records_response.json()["records"][0]["metadata"]["fileName"] == "benefits-letter.txt"

    delete_response = client.request(
        "DELETE",
        f"/wallets/{wallet_id}/records/{record_id}",
        json={"actor_did": "did:key:owner", "unpin_ipfs": False},
    )
    assert delete_response.status_code == 200
    delete_result = delete_response.json()
    assert delete_result["deleted"] is True
    assert delete_result["metadata_deleted"] is True

    records_after_response = client.get(f"/wallets/{wallet_id}/records")
    assert records_after_response.status_code == 200
    assert records_after_response.json()["records"] == []


def test_wallet_api_location_proof_routes_with_reloaded_snapshot(tmp_path, monkeypatch):
    client, wallet_dir, blob_dir = make_client(tmp_path, monkeypatch)

    service = WalletService(storage_backend=LocalEncryptedBlobStore(blob_dir))
    wallet = service.create_wallet(owner_did="did:key:owner")
    location = service.add_location(
        wallet.wallet_id,
        actor_did="did:key:owner",
        lat=45.5231,
        lon=-122.6765,
    )
    wallet_dir.mkdir(parents=True, exist_ok=True)
    (wallet_dir / f"{wallet.wallet_id}.json").write_text(
        json.dumps(service.export_wallet_snapshot(wallet.wallet_id), sort_keys=True),
        encoding="utf-8",
    )

    region_response = client.post(
        f"/wallets/{wallet.wallet_id}/locations/{location.record_id}/region-proofs",
        json={
            "actor_did": "did:key:owner",
            "region_id": "or-multnomah-county",
        },
    )
    assert region_response.status_code == 200
    assert region_response.json()["proof_type"] == "location_region"
    assert region_response.json()["public_inputs"]["region_id"] == "or-multnomah-county"

    distance_response = client.post(
        f"/wallets/{wallet.wallet_id}/locations/{location.record_id}/distance-proofs",
        json={
            "actor_did": "did:key:owner",
            "target_id": "211-downtown-office",
            "target_lat": 45.5230,
            "target_lon": -122.6760,
            "max_distance_km": 1.0,
        },
    )
    assert distance_response.status_code == 200
    assert distance_response.json()["proof_type"] == "location_distance"
    assert distance_response.json()["public_inputs"]["target_id"] == "211-downtown-office"

    proofs_response = client.get(f"/wallets/{wallet.wallet_id}/proofs")
    assert proofs_response.status_code == 200
    assert len(proofs_response.json()["proofs"]) == 2


def test_wallet_api_document_profile_proof_route(tmp_path, monkeypatch):
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

    proof_response = client.post(
        f"/wallets/{wallet_id}/records/{record_id}/document-profile-proofs",
        json={
            "actor_did": "did:key:owner",
            "public_inputs": {
                "mime_type": "text/plain",
                "profile_methods": ["redacted_graphrag", "vector_profile", {"drop": "me"}],
                "summary": "Benefits document profile",
                "private_text": "should not survive",
            },
        },
    )
    assert proof_response.status_code == 200
    proof = proof_response.json()
    assert proof["proof_type"] == "document_privacy_profile"
    assert proof["public_inputs"]["mime_type"] == "text/plain"
    assert proof["public_inputs"]["profile_methods"] == ["redacted_graphrag", "vector_profile"]
    assert "private_text" not in proof["public_inputs"]
    assert proof["public_inputs"]["privacy_policy"] == "no_plaintext_public_inputs"

    proofs_response = client.get(f"/wallets/{wallet_id}/proofs")
    assert proofs_response.status_code == 200
    assert len(proofs_response.json()["proofs"]) == 1


def test_wallet_api_generate_record_metadata_route(tmp_path, monkeypatch):
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

    generate_response = client.post(
        f"/wallets/{wallet_id}/records/{record_id}/metadata/generate",
        json={
            "actor_did": "did:key:owner",
            "actor_key_hex": "11" * 32,
            "file_name": "benefits.txt",
            "mime_type": "text/plain",
            "provider": "hf_inference_api",
        },
    )
    assert generate_response.status_code == 200
    payload = generate_response.json()
    metadata = payload["record"]["metadata"]
    assert metadata["privacyProfileStatus"] == "profiled"
    assert metadata["privacyProfileProofId"]
    assert metadata["privacyProfileSummary"]
    assert metadata["privacyProfileLabels"]
    assert metadata["privacyProfilePublicInputs"]["mime_type"] == "text/plain"
    assert payload["proof"]["proof_type"] == "document_privacy_profile"

    proofs_response = client.get(f"/wallets/{wallet_id}/proofs")
    assert proofs_response.status_code == 200
    assert len(proofs_response.json()["proofs"]) >= 1


def test_wallet_api_analytics_template_and_consent_routes(tmp_path, monkeypatch):
    client, wallet_dir, blob_dir = make_client(tmp_path, monkeypatch)

    service = WalletService(storage_backend=LocalEncryptedBlobStore(blob_dir))
    wallet = service.create_wallet(owner_did="did:key:owner")
    service.create_analytics_template(
        template_id="housing-needs-v1",
        title="Housing needs study",
        purpose="aggregate housing planning",
        allowed_record_types=["document"],
        allowed_derived_fields=["privacyProfileSummary", "privacyProfileLabels"],
        aggregation_policy={"min_cohort_size": 10, "epsilon_budget": 1.0},
        created_by="did:key:analyst",
        status="approved",
    )
    wallet_dir.mkdir(parents=True, exist_ok=True)
    (wallet_dir / f"{wallet.wallet_id}.json").write_text(
        json.dumps(service.export_wallet_snapshot(wallet.wallet_id), sort_keys=True),
        encoding="utf-8",
    )

    templates_response = client.get("/analytics/templates")
    assert templates_response.status_code == 200
    assert [item["template_id"] for item in templates_response.json()["templates"]] == ["housing-needs-v1"]

    consent_response = client.post(
        f"/wallets/{wallet.wallet_id}/analytics/consents/from-template",
        json={
            "actor_did": "did:key:owner",
            "template_id": "housing-needs-v1",
        },
    )
    assert consent_response.status_code == 200
    consent = consent_response.json()
    assert consent["template_id"] == "housing-needs-v1"
    assert consent["status"] == "active"

    list_consents_response = client.get(f"/wallets/{wallet.wallet_id}/analytics/consents")
    assert list_consents_response.status_code == 200
    assert len(list_consents_response.json()["consents"]) == 1

    revoke_response = client.post(
        f"/wallets/{wallet.wallet_id}/analytics/consents/{consent['consent_id']}/revoke",
        json={"actor_did": "did:key:owner"},
    )
    assert revoke_response.status_code == 200
    assert revoke_response.json()["status"] == "revoked"


def test_wallet_api_missing_person_dead_drop_routes(tmp_path, monkeypatch):
    client, _wallet_dir, _blob_dir = make_client(tmp_path, monkeypatch)
    monkeypatch.setattr(wallet_api, "_send_dead_drop_email", lambda **_: {"message_id": "msg-123"})

    wallet_response = client.post("/wallets", json={"owner_did": "did:key:owner"})
    assert wallet_response.status_code == 200
    wallet_id = wallet_response.json()["wallet_id"]

    save_response = client.put(
        f"/wallets/{wallet_id}/dead-drops/missing-person",
        json={
            "actor_did": "did:key:owner",
            "enabled": True,
            "to_email": "missing@police.portlandoregon.gov",
            "subject": "Missing person report dead drop bundle",
            "body": "Please review the attached bundle.",
            "bundle": {"wallet_id": wallet_id, "records": []},
            "bundle_filename": "dead-drop.json",
            "due_at": "2026-05-20T12:00:00+00:00",
            "last_check_in_at": "2026-05-20T10:00:00+00:00",
        },
    )
    assert save_response.status_code == 200
    saved = save_response.json()
    assert saved["enabled"] is True
    assert saved["armed_at"]

    get_response = client.get(f"/wallets/{wallet_id}/dead-drops/missing-person")
    assert get_response.status_code == 200
    assert get_response.json()["bundle_filename"] == "dead-drop.json"

    send_response = client.post(
        f"/wallets/{wallet_id}/dead-drops/missing-person",
        json={
            "actor_did": "did:key:owner",
            "to_email": "missing@police.portlandoregon.gov",
            "subject": "Missing person report dead drop bundle",
            "body": "Please review the attached bundle.",
            "bundle": {"wallet_id": wallet_id, "records": []},
            "bundle_filename": "manual-send.json",
        },
    )
    assert send_response.status_code == 200
    assert send_response.json()["message_id"] == "msg-123"

    dispatch_response = client.post(
        f"/wallets/{wallet_id}/dead-drops/missing-person/dispatch",
        json={"actor_did": "did:key:owner"},
    )
    assert dispatch_response.status_code == 200
    assert dispatch_response.json()["message_id"] == "msg-123"

    persisted_response = client.get(f"/wallets/{wallet_id}/dead-drops/missing-person")
    assert persisted_response.status_code == 200
    persisted = persisted_response.json()
    assert persisted["last_message_id"] == "msg-123"
    assert persisted["last_sent_at"]
    assert persisted["last_dispatched_reason"] == "manual"


def test_wallet_api_saved_service_routes(tmp_path, monkeypatch):
    client, _wallet_dir, _blob_dir = make_client(tmp_path, monkeypatch)

    wallet_response = client.post("/wallets", json={"owner_did": "did:key:owner"})
    assert wallet_response.status_code == 200
    wallet_id = wallet_response.json()["wallet_id"]

    save_response = client.post(
        f"/wallets/{wallet_id}/portal/saved-services",
        json={
            "actor_did": "did:key:owner",
            "service_doc_id": "service-doc-123",
            "source_content_cid": "bafyservicecontentcid1234567890",
            "source_page_cid": "bafyservicepagecid1234567890",
            "title": "Rental assistance",
            "provider_name": "Provider One",
            "program_name": "Housing Help",
            "source_url": "https://example.org/service",
            "label": "top match",
            "reason": "Matches housing need",
            "priority": "high",
            "status": "saved",
            "private_notes_record_id": "record-notes-1",
            "metadata": {"category": "housing"},
        },
    )
    assert save_response.status_code == 200
    saved = save_response.json()
    assert saved["service_doc_id"] == "service-doc-123"
    assert saved["priority"] == "high"

    list_response = client.get(
        f"/wallets/{wallet_id}/portal/saved-services",
        params={"status": "saved"},
    )
    assert list_response.status_code == 200
    payload = list_response.json()
    assert len(payload["saved_services"]) == 1
    assert payload["saved_services"][0]["saved_service_id"] == saved["saved_service_id"]


def test_wallet_api_service_interaction_routes(tmp_path, monkeypatch):
    client, _wallet_dir, _blob_dir = make_client(tmp_path, monkeypatch)

    wallet_response = client.post("/wallets", json={"owner_did": "did:key:owner"})
    assert wallet_response.status_code == 200
    wallet_id = wallet_response.json()["wallet_id"]

    create_response = client.post(
        f"/wallets/{wallet_id}/portal/interactions",
        json={
            "actor_did": "did:key:owner",
            "service_doc_id": "service-doc-123",
            "interaction_type": "call",
            "channel": "phone",
            "provider_name": "Provider One",
            "program_name": "Housing Help",
            "counterparty_name": "Case Worker",
            "counterparty_contact": "worker@example.org",
            "status": "completed",
            "outcome": "Scheduled intake",
            "metadata": {"duration_minutes": 15},
        },
    )
    assert create_response.status_code == 200
    created = create_response.json()
    assert created["interaction_type"] == "call"
    assert created["channel"] == "phone"

    list_response = client.get(
        f"/wallets/{wallet_id}/portal/interactions",
        params={"service_doc_id": "service-doc-123", "interaction_type": "call", "status": "completed"},
    )
    assert list_response.status_code == 200
    payload = list_response.json()
    assert len(payload["interactions"]) == 1
    assert payload["interactions"][0]["interaction_id"] == created["interaction_id"]


def test_wallet_api_service_plan_routes(tmp_path, monkeypatch):
    client, _wallet_dir, _blob_dir = make_client(tmp_path, monkeypatch)

    wallet_response = client.post("/wallets", json={"owner_did": "did:key:owner"})
    assert wallet_response.status_code == 200
    wallet_id = wallet_response.json()["wallet_id"]

    create_response = client.post(
        f"/wallets/{wallet_id}/portal/plans",
        json={
            "actor_did": "did:key:owner",
            "service_doc_id": "service-doc-123",
            "source_content_cid": "bafyservicecontentcid1234567890",
            "service_title": "Rental assistance",
            "provider_name": "Provider One",
            "goal": "Submit application",
            "steps": ["Call provider", "Gather income documents"],
            "documents_needed": ["ID", "Pay stubs"],
            "questions_to_ask": ["Eligibility window?"],
            "status": "active",
        },
    )
    assert create_response.status_code == 200
    created = create_response.json()
    assert created["goal"] == "Submit application"

    update_response = client.patch(
        f"/wallets/{wallet_id}/portal/plans/{created['plan_id']}",
        json={
            "actor_did": "did:key:owner",
            "status": "pending",
            "appointment_at": "2026-05-21T09:00:00+00:00",
            "related_interaction_ids": ["interaction-1"],
        },
    )
    assert update_response.status_code == 200
    updated = update_response.json()
    assert updated["status"] == "pending"
    assert updated["appointment_at"] == "2026-05-21T09:00:00+00:00"

    list_response = client.get(
        f"/wallets/{wallet_id}/portal/plans",
        params={"service_doc_id": "service-doc-123", "status": "pending"},
    )
    assert list_response.status_code == 200
    payload = list_response.json()
    assert len(payload["plans"]) == 1
    assert payload["plans"][0]["plan_id"] == created["plan_id"]


def test_wallet_api_service_plan_share_grant_route(tmp_path, monkeypatch):
    client, _wallet_dir, _blob_dir = make_client(tmp_path, monkeypatch)

    wallet_response = client.post("/wallets", json={"owner_did": "did:key:owner"})
    assert wallet_response.status_code == 200
    wallet_id = wallet_response.json()["wallet_id"]

    create_plan = client.post(
        f"/wallets/{wallet_id}/portal/plans",
        json={
            "actor_did": "did:key:owner",
            "service_doc_id": "service-doc-123",
            "source_content_cid": "bafyservicecontentcid1234567890",
            "service_title": "Rental assistance",
            "provider_name": "Provider One",
            "goal": "Submit application",
        },
    )
    assert create_plan.status_code == 200
    plan_id = create_plan.json()["plan_id"]

    share_response = client.post(
        f"/wallets/{wallet_id}/portal/plans/{plan_id}/share-grants",
        json={
            "actor_did": "did:key:owner",
            "audience_did": "did:key:worker",
            "audience_key_hex": "22" * 32,
            "issuer_key_hex": "11" * 32,
            "scopes": ["service_summary", "schedule"],
            "worker_name": "Case Worker",
        },
    )
    assert share_response.status_code == 200
    payload = share_response.json()
    assert payload["grant_id"]
    assert payload["plan_id"] == plan_id
    assert payload["interaction_id"]
    assert payload["grant"]["abilities"] == ["service_plan/read"]
    assert payload["receipt"]["grant_id"] == payload["grant_id"]
    assert payload["interaction"]["interaction_type"] == "shared_service_plan"


def test_wallet_api_ops_health_route(tmp_path, monkeypatch):
    client, _wallet_dir, _blob_dir = make_client(tmp_path, monkeypatch)

    wallet_response = client.post("/wallets", json={"owner_did": "did:key:owner"})
    assert wallet_response.status_code == 200

    response = client.get("/ops/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["wallet_count"] == 1
    assert payload["check_count"] >= 1
    assert isinstance(payload["checks"], list)