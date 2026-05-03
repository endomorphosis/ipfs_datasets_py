from __future__ import annotations

import json
import os
from io import BytesIO

os.environ.setdefault("IPFS_DATASETS_AUTO_INSTALL", "false")
os.environ.setdefault("IPFS_AUTO_INSTALL", "false")
os.environ.setdefault("IPFS_DATASETS_PY_MINIMAL_IMPORTS", "1")

import pytest

from ipfs_datasets_py.wallet import AccessDeniedError, ApprovalRequiredError, WalletInvocation, WalletService
from ipfs_datasets_py.wallet.storage import (
    FilecoinEncryptedBlobStore,
    IPFSEncryptedBlobStore,
    LocalEncryptedBlobStore,
    ReplicatedEncryptedBlobStore,
    S3EncryptedBlobStore,
)
from ipfs_datasets_py.wallet.ucan import (
    invocation_from_token,
    invocation_to_token,
    resource_for_export,
    resource_for_location,
    resource_for_record,
)


OWNER = "did:key:owner"
ADVOCATE = "did:key:advocate"
SECOND_CONTROLLER = "did:key:second-controller"


class FakeIPFSBackend:
    def __init__(self) -> None:
        self.blocks: dict[str, bytes] = {}
        self.pinned: list[str] = []

    def add_bytes(self, data: bytes, *, pin: bool = True) -> str:
        cid = f"fakecid-{len(self.blocks) + 1}"
        self.blocks[cid] = data
        if pin:
            self.pinned.append(cid)
        return cid

    def cat(self, cid: str) -> bytes:
        return self.blocks[cid]


class FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}
        self.metadata: dict[tuple[str, str], dict[str, str]] = {}

    def put_object(self, *, Bucket: str, Key: str, Body: bytes, Metadata: dict[str, str]):
        self.objects[(Bucket, Key)] = Body
        self.metadata[(Bucket, Key)] = Metadata

    def get_object(self, *, Bucket: str, Key: str):
        return {"Body": BytesIO(self.objects[(Bucket, Key)])}


class FakeFilecoinBackend:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def store_bytes(self, data: bytes, *, sha256: str) -> str:
        locator = f"piece-{len(self.objects) + 1}-{sha256[:12]}"
        self.objects[locator] = data
        return locator

    def retrieve_bytes(self, locator: str) -> bytes:
        return self.objects[locator]


def test_wallet_add_document_encrypts_and_decrypts_for_owner(tmp_path):
    service = WalletService(storage_dir=tmp_path / "wallet-store")
    wallet = service.create_wallet(owner_did=OWNER)
    source = tmp_path / "benefits.txt"
    source.write_text("SNAP approval letter for household benefits", encoding="utf-8")

    record = service.add_document(wallet.wallet_id, source)

    assert record.data_type == "document"
    assert service.decrypt_record(wallet.wallet_id, record.record_id, actor_did=OWNER) == source.read_bytes()
    manifest = service.get_wallet_manifest(wallet.wallet_id)
    assert manifest["records"][0]["public_descriptor"] == "document"
    assert "benefits.txt" not in service.get_wallet_manifest_canonical(wallet.wallet_id)


def test_unauthorized_delegate_cannot_decrypt_without_grant(tmp_path):
    service = WalletService(storage_dir=tmp_path)
    wallet = service.create_wallet(owner_did=OWNER)
    source = tmp_path / "id.txt"
    source.write_text("private identifier", encoding="utf-8")
    record = service.add_document(wallet.wallet_id, source)

    with pytest.raises(AccessDeniedError):
        service.decrypt_record(wallet.wallet_id, record.record_id, actor_did=ADVOCATE)


def test_analyze_grant_does_not_allow_plaintext_decrypt(tmp_path):
    service = WalletService(storage_dir=tmp_path)
    wallet = service.create_wallet(owner_did=OWNER)
    source = tmp_path / "case-note.txt"
    source.write_text("Housing instability and utility shutoff risk.", encoding="utf-8")
    record = service.add_document(wallet.wallet_id, source)
    grant = service.create_grant(
        wallet_id=wallet.wallet_id,
        issuer_did=OWNER,
        audience_did=ADVOCATE,
        resources=[resource_for_record(wallet.wallet_id, record.record_id)],
        abilities=["record/analyze"],
        caveats={"purpose": "service_matching"},
    )

    artifact = service.analyze_record_summary(
        wallet.wallet_id,
        record.record_id,
        actor_did=ADVOCATE,
        grant_id=grant.grant_id,
    )

    assert artifact.artifact_type == "summary"
    with pytest.raises(AccessDeniedError):
        service.decrypt_record(
            wallet.wallet_id,
            record.record_id,
            actor_did=ADVOCATE,
            grant_id=grant.grant_id,
        )


def test_decrypt_grant_wraps_key_for_delegate(tmp_path):
    service = WalletService(storage_dir=tmp_path)
    wallet = service.create_wallet(owner_did=OWNER)
    source = tmp_path / "medical.txt"
    source.write_text("medical document plaintext", encoding="utf-8")
    record = service.add_document(wallet.wallet_id, source)
    grant = service.create_grant(
        wallet_id=wallet.wallet_id,
        issuer_did=OWNER,
        audience_did=ADVOCATE,
        resources=[resource_for_record(wallet.wallet_id, record.record_id)],
        abilities=["record/decrypt"],
    )

    assert (
        service.decrypt_record(
            wallet.wallet_id,
            record.record_id,
            actor_did=ADVOCATE,
            grant_id=grant.grant_id,
        )
        == b"medical document plaintext"
    )


def test_threshold_approval_required_for_sensitive_decrypt_grant(tmp_path):
    service = WalletService(storage_dir=tmp_path)
    wallet = service.create_wallet(
        owner_did=OWNER,
        controller_dids=[OWNER, SECOND_CONTROLLER],
        governance_policy={"threshold": 2},
    )
    source = tmp_path / "identity.txt"
    source.write_text("identity document plaintext", encoding="utf-8")
    record = service.add_document(wallet.wallet_id, source)
    resource = resource_for_record(wallet.wallet_id, record.record_id)

    with pytest.raises(ApprovalRequiredError):
        service.create_grant(
            wallet_id=wallet.wallet_id,
            issuer_did=OWNER,
            audience_did=ADVOCATE,
            resources=[resource],
            abilities=["record/decrypt"],
        )

    approval = service.request_approval(
        wallet.wallet_id,
        requested_by=OWNER,
        operation="grant/create",
        resources=[resource],
        abilities=["record/decrypt"],
    )
    service.approve_approval(wallet.wallet_id, approval_id=approval.approval_id, approver_did=OWNER)

    with pytest.raises(ApprovalRequiredError):
        service.create_grant(
            wallet_id=wallet.wallet_id,
            issuer_did=OWNER,
            audience_did=ADVOCATE,
            resources=[resource],
            abilities=["record/decrypt"],
            approval_id=approval.approval_id,
        )

    service.approve_approval(
        wallet.wallet_id,
        approval_id=approval.approval_id,
        approver_did=SECOND_CONTROLLER,
    )
    grant = service.create_grant(
        wallet_id=wallet.wallet_id,
        issuer_did=OWNER,
        audience_did=ADVOCATE,
        resources=[resource],
        abilities=["record/decrypt"],
        approval_id=approval.approval_id,
    )

    assert approval.status == "approved"
    assert service.decrypt_record(
        wallet.wallet_id,
        record.record_id,
        actor_did=ADVOCATE,
        grant_id=grant.grant_id,
    ) == b"identity document plaintext"
    manifest = service.get_wallet_manifest(wallet.wallet_id)
    assert manifest["approvals"][0]["approval_id"] == approval.approval_id


def test_grant_receipt_tracks_sharing_and_survives_snapshot(tmp_path):
    service = WalletService(storage_dir=tmp_path)
    wallet = service.create_wallet(owner_did=OWNER)
    source = tmp_path / "receipt.txt"
    source.write_text("receipt tracked sharing", encoding="utf-8")
    record = service.add_document(wallet.wallet_id, source)
    resource = resource_for_record(wallet.wallet_id, record.record_id)

    grant = service.create_grant(
        wallet_id=wallet.wallet_id,
        issuer_did=OWNER,
        audience_did=ADVOCATE,
        resources=[resource],
        abilities=["record/analyze"],
        caveats={"purpose": "benefits_screening"},
    )
    [receipt] = service.list_grant_receipts(wallet.wallet_id, audience_did=ADVOCATE)

    assert receipt.grant_id == grant.grant_id
    assert receipt.wallet_id == wallet.wallet_id
    assert receipt.audience_did == ADVOCATE
    assert receipt.resources == [resource]
    assert receipt.abilities == ["record/analyze"]
    assert receipt.purpose == "benefits_screening"
    assert receipt.receipt_hash
    assert service.get_wallet_manifest(wallet.wallet_id)["grant_receipts"][0]["receipt_id"] == receipt.receipt_id

    restored = WalletService(storage_dir=tmp_path)
    restored.import_wallet_snapshot(service.export_wallet_snapshot(wallet.wallet_id))
    [restored_receipt] = restored.list_grant_receipts(wallet.wallet_id, status="active")
    assert restored_receipt.to_dict() == receipt.to_dict()

    service.revoke_grant(wallet.wallet_id, grant.grant_id, actor_did=OWNER)
    [revoked_receipt] = service.list_grant_receipts(wallet.wallet_id, status="revoked")
    assert revoked_receipt.receipt_id == receipt.receipt_id


def test_location_claims_are_coarse_and_proof_receipts_hide_precise_point(tmp_path):
    service = WalletService(storage_dir=tmp_path)
    wallet = service.create_wallet(owner_did=OWNER)
    location = service.add_location(wallet.wallet_id, lat=45.515232, lon=-122.678385)
    grant = service.create_grant(
        wallet_id=wallet.wallet_id,
        issuer_did=OWNER,
        audience_did=ADVOCATE,
        resources=[resource_for_location(wallet.wallet_id, location.record_id)],
        abilities=["location/read_coarse", "location/prove_region"],
    )

    claim = service.create_coarse_location_claim(
        wallet.wallet_id,
        location.record_id,
        actor_did=ADVOCATE,
        grant_id=grant.grant_id,
    )
    receipt = service.create_location_region_proof(
        wallet.wallet_id,
        location.record_id,
        actor_did=ADVOCATE,
        region_id="multnomah_county",
        grant_id=grant.grant_id,
    )

    assert claim.public_value == {"lat": 45.52, "lon": -122.68}
    assert receipt.is_simulated is True
    assert receipt.public_inputs == {"region_id": "multnomah_county", "claim": "location_in_region"}
    public_receipt = json.dumps(receipt.to_dict())
    assert "45.515232" not in public_receipt
    assert "-122.678385" not in public_receipt


def test_revoked_grant_fails_future_invocations(tmp_path):
    service = WalletService(storage_dir=tmp_path)
    wallet = service.create_wallet(owner_did=OWNER)
    source = tmp_path / "note.txt"
    source.write_text("private note", encoding="utf-8")
    record = service.add_document(wallet.wallet_id, source)
    grant = service.create_grant(
        wallet_id=wallet.wallet_id,
        issuer_did=OWNER,
        audience_did=ADVOCATE,
        resources=[resource_for_record(wallet.wallet_id, record.record_id)],
        abilities=["record/analyze"],
    )

    service.revoke_grant(wallet.wallet_id, grant.grant_id, actor_did=OWNER)

    with pytest.raises(AccessDeniedError):
        service.analyze_record_summary(
            wallet.wallet_id,
            record.record_id,
            actor_did=ADVOCATE,
            grant_id=grant.grant_id,
        )


def test_export_bundle_requires_grant_and_excludes_plaintext_location(tmp_path):
    service = WalletService(storage_dir=tmp_path)
    wallet = service.create_wallet(owner_did=OWNER)
    source = tmp_path / "notice.txt"
    source.write_text("Eviction notice with confidential case facts", encoding="utf-8")
    document = service.add_document(wallet.wallet_id, source)
    location = service.add_location(wallet.wallet_id, actor_did=OWNER, lat=45.515232, lon=-122.678385)

    with pytest.raises(AccessDeniedError):
        service.create_export_bundle(
            wallet.wallet_id,
            actor_did=ADVOCATE,
            record_ids=[document.record_id, location.record_id],
        )

    grant = service.create_grant(
        wallet_id=wallet.wallet_id,
        issuer_did=OWNER,
        audience_did=ADVOCATE,
        resources=[
            resource_for_record(wallet.wallet_id, document.record_id),
            resource_for_record(wallet.wallet_id, location.record_id),
        ],
        abilities=["export/create"],
    )
    bundle = service.create_export_bundle(
        wallet.wallet_id,
        actor_did=ADVOCATE,
        grant_id=grant.grant_id,
        record_ids=[document.record_id, location.record_id],
    )

    assert bundle["bundle_type"] == "wallet_export_v1"
    assert bundle["bundle_id"] == f"export-{bundle['bundle_hash'][:24]}"
    assert service.verify_export_bundle(bundle) is True
    assert "controller_dids" not in bundle["wallet"]
    assert "device_dids" not in bundle["wallet"]
    assert [record["record_id"] for record in bundle["records"]] == [document.record_id, location.record_id]
    assert all(version["key_wraps"] == [] for version in bundle["versions"])
    public_export = json.dumps(bundle)
    assert "Eviction notice" not in public_export
    assert "45.515232" not in public_export
    assert "-122.678385" not in public_export
    tampered = {**bundle, "records": []}
    assert service.verify_export_bundle(tampered) is False

    imported = WalletService(storage_dir=tmp_path / "imported")
    available_storage = imported.verify_export_bundle_storage(bundle)
    assert available_storage["ok"] is True
    assert available_storage["record_count"] == 2
    broken_storage_bundle = json.loads(json.dumps(bundle))
    broken_storage_bundle["versions"][0]["encrypted_payload_ref"]["uri"] = "local:///missing/export-payload.bin"
    broken_storage_bundle["versions"][0]["encrypted_payload_ref"]["mirrors"] = []
    broken_storage_bundle["bundle_hash"] = imported.export_bundle_hash(broken_storage_bundle)
    broken_storage_bundle["bundle_id"] = f"export-{broken_storage_bundle['bundle_hash'][:24]}"
    missing_storage = imported.verify_export_bundle_storage(broken_storage_bundle)
    assert missing_storage["ok"] is False
    summary = imported.import_export_bundle(bundle)
    assert summary["record_count"] == 2
    assert summary["version_count"] == 2
    assert imported.records[document.record_id].data_type == "document"
    assert imported.records[location.record_id].data_type == "location"
    assert imported.get_audit_log(wallet.wallet_id)[-1].action == "export/import"
    with pytest.raises(AccessDeniedError):
        imported.import_export_bundle(tampered)
    wrong_type = {**bundle, "bundle_type": "not_wallet_export"}
    wrong_type["bundle_hash"] = imported.export_bundle_hash(wrong_type)
    wrong_type["bundle_id"] = f"export-{wrong_type['bundle_hash'][:24]}"
    with pytest.raises(ValueError, match="Unsupported"):
        imported.import_export_bundle(wrong_type)
    missing_versions = {**bundle, "versions": []}
    missing_versions["bundle_hash"] = imported.export_bundle_hash(missing_versions)
    missing_versions["bundle_id"] = f"export-{missing_versions['bundle_hash'][:24]}"
    with pytest.raises(ValueError, match="version"):
        imported.import_export_bundle(missing_versions)

    service.revoke_grant(wallet.wallet_id, grant.grant_id, actor_did=OWNER)
    with pytest.raises(AccessDeniedError):
        service.create_export_bundle(
            wallet.wallet_id,
            actor_did=ADVOCATE,
            grant_id=grant.grant_id,
            record_ids=[document.record_id],
        )


def test_export_bundle_accepts_signed_invocation_and_invocation_caveats(tmp_path):
    service = WalletService(storage_dir=tmp_path)
    delegate_secret = b"d" * 32
    wallet = service.create_wallet(owner_did=OWNER)
    source = tmp_path / "export-note.txt"
    source.write_text("Export through invocation", encoding="utf-8")
    document = service.add_document(wallet.wallet_id, source)
    location = service.add_location(wallet.wallet_id, actor_did=OWNER, lat=45.515232, lon=-122.678385)
    grant = service.create_grant(
        wallet_id=wallet.wallet_id,
        issuer_did=OWNER,
        audience_did=ADVOCATE,
        resources=[resource_for_export(wallet.wallet_id)],
        abilities=["export/create"],
        caveats={"record_ids": [document.record_id, location.record_id]},
        audience_secret=delegate_secret,
    )
    invocation = service.issue_invocation(
        wallet.wallet_id,
        grant_id=grant.grant_id,
        actor_did=ADVOCATE,
        resource=resource_for_export(wallet.wallet_id),
        ability="export/create",
        actor_secret=delegate_secret,
        caveats={"record_ids": [document.record_id]},
    )

    bundle = service.create_export_bundle_with_invocation(
        wallet.wallet_id,
        actor_did=ADVOCATE,
        invocation=invocation,
        actor_secret=delegate_secret,
        record_ids=[document.record_id],
    )

    assert [record["record_id"] for record in bundle["records"]] == [document.record_id]
    with pytest.raises(AccessDeniedError):
        service.create_export_bundle_with_invocation(
            wallet.wallet_id,
            actor_did=ADVOCATE,
            invocation=invocation,
            actor_secret=delegate_secret,
            record_ids=[location.record_id],
        )


def test_revoked_export_grant_blocks_existing_invocation(tmp_path):
    service = WalletService(storage_dir=tmp_path)
    delegate_secret = b"d" * 32
    wallet = service.create_wallet(owner_did=OWNER)
    source = tmp_path / "export-revoke.txt"
    source.write_text("Export should stop after revoke", encoding="utf-8")
    document = service.add_document(wallet.wallet_id, source)
    grant = service.create_grant(
        wallet_id=wallet.wallet_id,
        issuer_did=OWNER,
        audience_did=ADVOCATE,
        resources=[resource_for_export(wallet.wallet_id)],
        abilities=["export/create"],
        caveats={"record_ids": [document.record_id]},
        audience_secret=delegate_secret,
    )
    invocation = service.issue_invocation(
        wallet.wallet_id,
        grant_id=grant.grant_id,
        actor_did=ADVOCATE,
        resource=resource_for_export(wallet.wallet_id),
        ability="export/create",
        actor_secret=delegate_secret,
        caveats={"record_ids": [document.record_id]},
    )

    service.revoke_grant(wallet.wallet_id, grant.grant_id, actor_did=OWNER)

    with pytest.raises(AccessDeniedError, match="not active"):
        service.create_export_bundle_with_invocation(
            wallet.wallet_id,
            actor_did=ADVOCATE,
            invocation=invocation,
            actor_secret=delegate_secret,
            record_ids=[document.record_id],
        )


def test_export_grant_requires_threshold_approval(tmp_path):
    service = WalletService(storage_dir=tmp_path)
    wallet = service.create_wallet(
        owner_did=OWNER,
        controller_dids=[OWNER, SECOND_CONTROLLER],
        governance_policy={"threshold": 2, "approver_dids": [OWNER, SECOND_CONTROLLER]},
    )
    source = tmp_path / "export-approval.txt"
    source.write_text("Export requires approval", encoding="utf-8")
    document = service.add_document(wallet.wallet_id, source)
    export_resource = resource_for_export(wallet.wallet_id)

    with pytest.raises(ApprovalRequiredError):
        service.create_grant(
            wallet_id=wallet.wallet_id,
            issuer_did=OWNER,
            audience_did=ADVOCATE,
            resources=[export_resource],
            abilities=["export/create"],
            caveats={"record_ids": [document.record_id]},
        )

    approval = service.request_approval(
        wallet.wallet_id,
        requested_by=OWNER,
        operation="grant/create",
        resources=[export_resource],
        abilities=["export/create"],
    )
    service.approve_approval(wallet.wallet_id, approval_id=approval.approval_id, approver_did=OWNER)
    service.approve_approval(wallet.wallet_id, approval_id=approval.approval_id, approver_did=SECOND_CONTROLLER)
    grant = service.create_grant(
        wallet_id=wallet.wallet_id,
        issuer_did=OWNER,
        audience_did=ADVOCATE,
        resources=[export_resource],
        abilities=["export/create"],
        caveats={"record_ids": [document.record_id]},
        approval_id=approval.approval_id,
    )

    assert grant.grant_id.startswith("grant-")
    assert grant.abilities == ["export/create"]


def test_signed_invocation_allows_delegate_analysis_and_round_trips_token(tmp_path):
    service = WalletService(storage_dir=tmp_path)
    owner_secret = b"o" * 32
    delegate_secret = b"d" * 32
    wallet = service.create_wallet(owner_did=OWNER)
    source = tmp_path / "case-note.txt"
    source.write_text("Eligible for rental assistance and utility support.", encoding="utf-8")
    record = service.add_document(wallet.wallet_id, source, actor_secret=owner_secret)
    grant = service.create_grant(
        wallet_id=wallet.wallet_id,
        issuer_did=OWNER,
        audience_did=ADVOCATE,
        resources=[resource_for_record(wallet.wallet_id, record.record_id)],
        abilities=["record/analyze"],
        issuer_secret=owner_secret,
        audience_secret=delegate_secret,
    )
    invocation = service.issue_invocation(
        wallet.wallet_id,
        grant_id=grant.grant_id,
        actor_did=ADVOCATE,
        resource=resource_for_record(wallet.wallet_id, record.record_id),
        ability="record/analyze",
        actor_secret=delegate_secret,
    )
    token_invocation = invocation_from_token(invocation_to_token(invocation))

    artifact = service.analyze_record_summary_with_invocation(
        wallet.wallet_id,
        record.record_id,
        actor_did=ADVOCATE,
        invocation=token_invocation,
        actor_secret=delegate_secret,
    )
    manifest = service.get_wallet_manifest(wallet.wallet_id)
    actions = [event.action for event in service.get_audit_log(wallet.wallet_id)]

    assert artifact.artifact_type == "summary"
    assert manifest["invocations"][0]["invocation_id"] == invocation.invocation_id
    assert "invocation/issue" in actions
    assert "invocation/verify" in actions


def test_access_request_approval_can_issue_invocation(tmp_path):
    service = WalletService(storage_dir=tmp_path)
    owner_secret = b"o" * 32
    delegate_secret = b"d" * 32
    wallet = service.create_wallet(owner_did=OWNER)
    source = tmp_path / "requested.txt"
    source.write_text("requested access summary", encoding="utf-8")
    record = service.add_document(wallet.wallet_id, source, actor_secret=owner_secret)

    request = service.request_access(
        wallet.wallet_id,
        requester_did=ADVOCATE,
        resources=[resource_for_record(wallet.wallet_id, record.record_id)],
        abilities=["record/analyze"],
        purpose="eligibility_review",
    )
    approved = service.approve_access_request(
        wallet.wallet_id,
        request_id=request.request_id,
        actor_did=OWNER,
        issuer_secret=owner_secret,
        audience_secret=delegate_secret,
        issue_invocation=True,
    )
    restored = WalletService(storage_dir=tmp_path)
    restored.import_wallet_snapshot(service.export_wallet_snapshot(wallet.wallet_id))

    artifact = restored.analyze_record_summary_with_invocation(
        wallet.wallet_id,
        record.record_id,
        actor_did=ADVOCATE,
        invocation=restored.invocations[approved.invocation_id],
        actor_secret=delegate_secret,
    )
    manifest = restored.get_wallet_manifest(wallet.wallet_id)

    assert approved.status == "approved"
    assert approved.grant_id in restored.grants
    assert approved.invocation_id in restored.invocations
    assert manifest["access_requests"][0]["request_id"] == request.request_id
    assert artifact.artifact_type == "summary"


def test_access_request_rejection_records_decision(tmp_path):
    service = WalletService(storage_dir=tmp_path)
    wallet = service.create_wallet(owner_did=OWNER)
    request = service.request_access(
        wallet.wallet_id,
        requester_did=ADVOCATE,
        resources=[resource_for_record(wallet.wallet_id, "rec-missing")],
        abilities=["record/analyze"],
        purpose="screening",
    )

    rejected = service.reject_access_request(
        wallet.wallet_id,
        request_id=request.request_id,
        actor_did=OWNER,
        reason="insufficient purpose",
    )

    assert rejected.status == "rejected"
    assert rejected.decided_by == OWNER
    assert rejected.details["rejection_reason"] == "insufficient purpose"
    assert service.get_wallet_manifest(wallet.wallet_id)["access_requests"][0]["status"] == "rejected"


def test_access_request_revocation_updates_request_and_blocks_invocation(tmp_path):
    service = WalletService(storage_dir=tmp_path)
    owner_secret = b"o" * 32
    delegate_secret = b"d" * 32
    wallet = service.create_wallet(owner_did=OWNER)
    source = tmp_path / "revocable.txt"
    source.write_text("revocable access", encoding="utf-8")
    record = service.add_document(wallet.wallet_id, source, actor_secret=owner_secret)
    request = service.request_access(
        wallet.wallet_id,
        requester_did=ADVOCATE,
        resources=[resource_for_record(wallet.wallet_id, record.record_id)],
        abilities=["record/decrypt"],
        purpose="identity_verification",
    )
    approved = service.approve_access_request(
        wallet.wallet_id,
        request_id=request.request_id,
        actor_did=OWNER,
        issuer_secret=owner_secret,
        audience_secret=delegate_secret,
        issue_invocation=True,
    )

    revoked = service.revoke_access_request(
        wallet.wallet_id,
        request_id=approved.request_id,
        actor_did=OWNER,
        reason="user withdrew consent",
    )

    assert revoked.status == "revoked"
    assert revoked.details["revocation_reason"] == "user withdrew consent"
    assert service.grants[approved.grant_id].status == "revoked"
    assert service.list_access_requests(wallet.wallet_id, status="revoked")[0].request_id == request.request_id
    restored = WalletService(storage_dir=tmp_path)
    restored.import_wallet_snapshot(service.export_wallet_snapshot(wallet.wallet_id))
    assert restored.access_requests[request.request_id].status == "revoked"
    assert restored.grants[approved.grant_id].status == "revoked"
    with pytest.raises(AccessDeniedError, match="not active"):
        service.decrypt_record_with_invocation(
            wallet.wallet_id,
            record.record_id,
            actor_did=ADVOCATE,
            invocation=service.invocations[approved.invocation_id],
            actor_secret=delegate_secret,
        )


def test_access_request_listing_filters_for_review_inbox(tmp_path):
    service = WalletService(storage_dir=tmp_path)
    wallet = service.create_wallet(owner_did=OWNER)
    first = service.request_access(
        wallet.wallet_id,
        requester_did=ADVOCATE,
        resources=[resource_for_record(wallet.wallet_id, "rec-one")],
        abilities=["record/analyze"],
        purpose="screening",
    )
    second = service.request_access(
        wallet.wallet_id,
        requester_did="did:key:researcher",
        audience_did="did:key:analytics-service",
        resources=[resource_for_record(wallet.wallet_id, "rec-two")],
        abilities=["record/analyze"],
        purpose="aggregate_planning",
    )
    service.reject_access_request(
        wallet.wallet_id,
        request_id=second.request_id,
        actor_did=OWNER,
        reason="not needed",
    )

    assert [request.request_id for request in service.list_access_requests(wallet.wallet_id)] == [
        first.request_id,
        second.request_id,
    ]
    assert [request.request_id for request in service.list_access_requests(wallet.wallet_id, status="pending")] == [
        first.request_id,
    ]
    assert [
        request.request_id
        for request in service.list_access_requests(
            wallet.wallet_id,
            status="rejected",
            audience_did="did:key:analytics-service",
        )
    ] == [second.request_id]


def test_access_request_review_items_include_approval_and_grant_state(tmp_path):
    service = WalletService(storage_dir=tmp_path)
    owner_secret = b"o" * 32
    delegate_secret = b"d" * 32
    wallet = service.create_wallet(
        owner_did=OWNER,
        controller_dids=[OWNER, SECOND_CONTROLLER],
        governance_policy={"threshold": 2, "approver_dids": [OWNER, SECOND_CONTROLLER]},
    )
    source = tmp_path / "threshold-access.txt"
    source.write_text("threshold access text", encoding="utf-8")
    record = service.add_document(wallet.wallet_id, source, actor_secret=owner_secret)
    resource = resource_for_record(wallet.wallet_id, record.record_id)
    access_request = service.request_access(
        wallet.wallet_id,
        requester_did=ADVOCATE,
        resources=[resource],
        abilities=["record/decrypt"],
        purpose="identity_verification",
    )

    [pending_item] = service.access_request_review_items(wallet.wallet_id, status="pending")
    assert pending_item["request_id"] == access_request.request_id
    assert pending_item["approval_required"] is True
    assert pending_item["approval_id"] is None
    assert pending_item["approval_count"] == 0
    assert pending_item["grant_status"] is None

    approval = service.request_approval(
        wallet.wallet_id,
        requested_by=OWNER,
        operation="grant/create",
        resources=[resource],
        abilities=["record/decrypt"],
    )
    service.approve_approval(wallet.wallet_id, approval_id=approval.approval_id, approver_did=OWNER)

    [partial_item] = service.access_request_review_items(wallet.wallet_id, status="pending")
    assert partial_item["approval_id"] == approval.approval_id
    assert partial_item["approval_status"] == "pending"
    assert partial_item["approval_threshold"] == 2
    assert partial_item["approval_count"] == 1

    service.approve_approval(wallet.wallet_id, approval_id=approval.approval_id, approver_did=SECOND_CONTROLLER)
    service.approve_access_request(
        wallet.wallet_id,
        request_id=access_request.request_id,
        actor_did=OWNER,
        issuer_secret=owner_secret,
        audience_secret=delegate_secret,
        approval_id=approval.approval_id,
    )

    [approved_item] = service.access_request_review_items(wallet.wallet_id, status="approved")
    assert approved_item["approval_status"] == "approved"
    assert approved_item["approval_count"] == 2
    assert approved_item["grant_status"] == "active"


def test_invocation_rejects_tampering_wrong_ability_and_revoked_grant(tmp_path):
    service = WalletService(storage_dir=tmp_path)
    owner_secret = b"o" * 32
    delegate_secret = b"d" * 32
    wallet = service.create_wallet(owner_did=OWNER)
    source = tmp_path / "case-note.txt"
    source.write_text("Private document", encoding="utf-8")
    record = service.add_document(wallet.wallet_id, source, actor_secret=owner_secret)
    grant = service.create_grant(
        wallet_id=wallet.wallet_id,
        issuer_did=OWNER,
        audience_did=ADVOCATE,
        resources=[resource_for_record(wallet.wallet_id, record.record_id)],
        abilities=["record/analyze"],
        issuer_secret=owner_secret,
        audience_secret=delegate_secret,
    )
    invocation = service.issue_invocation(
        wallet.wallet_id,
        grant_id=grant.grant_id,
        actor_did=ADVOCATE,
        resource=resource_for_record(wallet.wallet_id, record.record_id),
        ability="record/analyze",
        actor_secret=delegate_secret,
    )
    tampered = WalletInvocation(**(invocation.to_dict() | {"caveats": {"tampered": True}}))

    with pytest.raises(AccessDeniedError, match="capability"):
        service.verify_invocation(
            wallet.wallet_id,
            invocation,
            actor_did=ADVOCATE,
            resource=resource_for_record(wallet.wallet_id, record.record_id),
            ability="record/decrypt",
            actor_secret=delegate_secret,
        )
    with pytest.raises(AccessDeniedError, match="signature"):
        service.verify_invocation(
            wallet.wallet_id,
            tampered,
            actor_did=ADVOCATE,
            resource=resource_for_record(wallet.wallet_id, record.record_id),
            ability="record/analyze",
            actor_secret=delegate_secret,
        )

    service.revoke_grant(wallet.wallet_id, grant.grant_id, actor_did=OWNER)
    with pytest.raises(AccessDeniedError, match="not active"):
        service.verify_invocation(
            wallet.wallet_id,
            invocation,
            actor_did=ADVOCATE,
            resource=resource_for_record(wallet.wallet_id, record.record_id),
            ability="record/analyze",
            actor_secret=delegate_secret,
        )


def test_invocation_snapshot_preserves_verifiable_invocation(tmp_path):
    service = WalletService(storage_dir=tmp_path)
    owner_secret = b"o" * 32
    delegate_secret = b"d" * 32
    wallet = service.create_wallet(owner_did=OWNER)
    source = tmp_path / "note.txt"
    source.write_text("Snapshot invocation", encoding="utf-8")
    record = service.add_document(wallet.wallet_id, source, actor_secret=owner_secret)
    grant = service.create_grant(
        wallet_id=wallet.wallet_id,
        issuer_did=OWNER,
        audience_did=ADVOCATE,
        resources=[resource_for_record(wallet.wallet_id, record.record_id)],
        abilities=["record/analyze"],
        issuer_secret=owner_secret,
        audience_secret=delegate_secret,
    )
    invocation = service.issue_invocation(
        wallet.wallet_id,
        grant_id=grant.grant_id,
        actor_did=ADVOCATE,
        resource=resource_for_record(wallet.wallet_id, record.record_id),
        ability="record/analyze",
        actor_secret=delegate_secret,
    )
    snapshot = service.export_wallet_snapshot(wallet.wallet_id)
    restored = WalletService(storage_dir=tmp_path)
    restored.import_wallet_snapshot(snapshot)

    restored.verify_invocation(
        wallet.wallet_id,
        restored.invocations[invocation.invocation_id],
        actor_did=ADVOCATE,
        resource=resource_for_record(wallet.wallet_id, record.record_id),
        ability="record/analyze",
        actor_secret=delegate_secret,
    )


def test_manifest_serialization_is_stable(tmp_path):
    service = WalletService(storage_dir=tmp_path)
    wallet = service.create_wallet(owner_did=OWNER)
    source = tmp_path / "doc.txt"
    source.write_text("stable manifest", encoding="utf-8")
    service.add_document(wallet.wallet_id, source)

    assert service.get_wallet_manifest_canonical(wallet.wallet_id) == service.get_wallet_manifest_canonical(
        wallet.wallet_id
    )


def test_audit_events_form_hash_chain(tmp_path):
    service = WalletService(storage_dir=tmp_path)
    wallet = service.create_wallet(owner_did=OWNER)
    source = tmp_path / "doc.txt"
    source.write_text("audit me", encoding="utf-8")
    record = service.add_document(wallet.wallet_id, source)
    service.decrypt_record(wallet.wallet_id, record.record_id, actor_did=OWNER)

    events = service.get_audit_log(wallet.wallet_id)
    assert len(events) >= 3
    for previous, current in zip(events, events[1:]):
        assert current.hash_prev == previous.hash_self


def test_ipfs_storage_backend_stores_only_encrypted_payloads(tmp_path):
    fake_ipfs = FakeIPFSBackend()
    service = WalletService(storage_backend=IPFSEncryptedBlobStore(fake_ipfs))
    wallet = service.create_wallet(owner_did=OWNER)
    source = tmp_path / "secret.txt"
    source.write_text("plain secret should not be in ipfs bytes", encoding="utf-8")

    record = service.add_document(wallet.wallet_id, source)
    version = service.versions[record.current_version_id]

    assert version.encrypted_payload_ref.storage_type == "ipfs"
    assert version.encrypted_payload_ref.uri.startswith("ipfs://fakecid-")
    assert fake_ipfs.pinned
    assert b"plain secret" not in b"".join(fake_ipfs.blocks.values())
    assert service.decrypt_record(wallet.wallet_id, record.record_id, actor_did=OWNER) == source.read_bytes()


def test_ipfs_storage_backend_rejects_hash_mismatch():
    fake_ipfs = FakeIPFSBackend()
    store = IPFSEncryptedBlobStore(fake_ipfs)
    ref = store.put(b"encrypted bytes")
    cid = ref.uri.removeprefix("ipfs://")
    fake_ipfs.blocks[cid] = b"tampered bytes"

    with pytest.raises(ValueError, match="hash mismatch"):
        store.get(ref)


def test_s3_and_filecoin_stores_round_trip_encrypted_bytes():
    s3_client = FakeS3Client()
    s3_store = S3EncryptedBlobStore(s3_client, bucket="wallet-test", prefix="encrypted")
    filecoin_backend = FakeFilecoinBackend()
    filecoin_store = FilecoinEncryptedBlobStore(filecoin_backend)

    s3_ref = s3_store.put(b"encrypted payload")
    filecoin_ref = filecoin_store.put(b"encrypted payload")

    assert s3_ref.uri.startswith("s3://wallet-test/encrypted/")
    assert filecoin_ref.uri.startswith("filecoin://piece-")
    assert s3_store.get(s3_ref) == b"encrypted payload"
    assert filecoin_store.get(filecoin_ref) == b"encrypted payload"


def test_replicated_storage_records_mirrors_and_keeps_plaintext_out(tmp_path):
    fake_ipfs = FakeIPFSBackend()
    s3_client = FakeS3Client()
    filecoin_backend = FakeFilecoinBackend()
    storage = ReplicatedEncryptedBlobStore(
        LocalEncryptedBlobStore(tmp_path / "primary"),
        mirrors=[
            IPFSEncryptedBlobStore(fake_ipfs),
            S3EncryptedBlobStore(s3_client, bucket="wallet-test"),
            FilecoinEncryptedBlobStore(filecoin_backend),
        ],
    )
    service = WalletService(storage_backend=storage)
    wallet = service.create_wallet(owner_did=OWNER)
    owner_secret = b"r" * 32
    source = tmp_path / "replicated.txt"
    source.write_text("replicated plaintext must stay encrypted", encoding="utf-8")

    record = service.add_document(wallet.wallet_id, source, actor_secret=owner_secret)
    version = service.versions[record.current_version_id]
    mirror_types = {mirror.storage_type for mirror in version.encrypted_payload_ref.mirrors}

    assert version.encrypted_payload_ref.storage_type == "local"
    assert mirror_types == {"ipfs", "s3", "filecoin"}
    assert b"replicated plaintext" not in b"".join(fake_ipfs.blocks.values())
    assert b"replicated plaintext" not in b"".join(s3_client.objects.values())
    assert b"replicated plaintext" not in b"".join(filecoin_backend.objects.values())
    manifest = service.export_wallet_snapshot(wallet.wallet_id)
    assert {mirror["storage_type"] for mirror in manifest["versions"][0]["encrypted_payload_ref"]["mirrors"]} == mirror_types
    restored = WalletService(storage_backend=storage)
    restored.import_wallet_snapshot(manifest)
    restored.set_principal_secret(OWNER, owner_secret)
    assert restored.decrypt_record(wallet.wallet_id, record.record_id, actor_did=OWNER) == source.read_bytes()


def test_replicated_storage_reads_from_mirror_when_primary_fails():
    fake_ipfs = FakeIPFSBackend()
    s3_client = FakeS3Client()
    storage = ReplicatedEncryptedBlobStore(
        IPFSEncryptedBlobStore(fake_ipfs),
        mirrors=[S3EncryptedBlobStore(s3_client, bucket="wallet-test")],
    )
    ref = storage.put(b"encrypted payload")
    cid = ref.uri.removeprefix("ipfs://")
    fake_ipfs.blocks[cid] = b"tampered primary"

    assert storage.get(ref) == b"encrypted payload"


def test_record_storage_health_detects_and_repairs_bad_mirrors(tmp_path):
    fake_ipfs = FakeIPFSBackend()
    s3_client = FakeS3Client()
    storage = ReplicatedEncryptedBlobStore(
        LocalEncryptedBlobStore(tmp_path / "primary"),
        mirrors=[
            IPFSEncryptedBlobStore(fake_ipfs),
            S3EncryptedBlobStore(s3_client, bucket="wallet-test"),
        ],
    )
    service = WalletService(storage_backend=storage)
    wallet = service.create_wallet(owner_did=OWNER)
    source = tmp_path / "repair.txt"
    source.write_text("repair plaintext must remain encrypted", encoding="utf-8")
    record = service.add_document(wallet.wallet_id, source, metadata={"title": "Repair me"})
    version = service.versions[record.current_version_id]

    assert service.verify_record_storage(wallet.wallet_id, record.record_id).ok is True
    ipfs_payload = next(mirror for mirror in version.encrypted_payload_ref.mirrors if mirror.storage_type == "ipfs")
    fake_ipfs.blocks[ipfs_payload.uri.removeprefix("ipfs://")] = b"tampered encrypted payload"
    s3_client.objects.clear()

    broken = service.verify_record_storage(wallet.wallet_id, record.record_id)
    assert broken.ok is False
    assert any(not status.ok and status.storage_type == "ipfs" for status in broken.payload)
    assert any(not status.ok and status.storage_type == "s3" for status in broken.payload)

    repaired = service.repair_record_storage(wallet.wallet_id, record.record_id, actor_did=OWNER)
    assert repaired.ok is True
    assert repaired.repaired is True
    assert any(status.repaired and status.storage_type == "ipfs" for status in repaired.payload)
    assert any(status.repaired and status.storage_type == "s3" for status in repaired.metadata)
    assert b"repair plaintext" not in b"".join(fake_ipfs.blocks.values())
    assert b"repair plaintext" not in b"".join(s3_client.objects.values())
    assert service.verify_record_storage(wallet.wallet_id, record.record_id).ok is True
    assert service.get_audit_log(wallet.wallet_id)[-1].action == "storage/verify"
    assert any(event.action == "storage/repair" for event in service.get_audit_log(wallet.wallet_id))


def test_record_storage_repair_restores_missing_primary_from_mirror(tmp_path):
    s3_client = FakeS3Client()
    storage = ReplicatedEncryptedBlobStore(
        LocalEncryptedBlobStore(tmp_path / "primary"),
        mirrors=[S3EncryptedBlobStore(s3_client, bucket="wallet-test")],
    )
    service = WalletService(storage_backend=storage)
    wallet = service.create_wallet(owner_did=OWNER)
    source = tmp_path / "primary-repair.txt"
    source.write_text("primary repair plaintext", encoding="utf-8")
    record = service.add_document(wallet.wallet_id, source)
    version = service.versions[record.current_version_id]
    primary_path = version.encrypted_payload_ref.uri.removeprefix("local://")

    os.unlink(primary_path)
    broken = service.verify_record_storage(wallet.wallet_id, record.record_id, include_metadata=False)
    assert broken.ok is False
    assert broken.payload[0].role == "primary"

    repaired = service.repair_record_storage(
        wallet.wallet_id,
        record.record_id,
        actor_did=OWNER,
        include_metadata=False,
    )
    assert repaired.ok is True
    assert repaired.payload[0].repaired is True
    assert service.decrypt_record(wallet.wallet_id, record.record_id, actor_did=OWNER) == source.read_bytes()


def test_analytics_contribution_requires_consented_fields(tmp_path):
    service = WalletService(storage_dir=tmp_path)
    wallet = service.create_wallet(owner_did=OWNER)
    consent = service.create_analytics_consent(
        wallet.wallet_id,
        actor_did=OWNER,
        template_id="housing_needs_by_county_v1",
        allowed_record_types=["location", "need"],
        allowed_derived_fields=["county", "need_category"],
        aggregation_policy={"min_cohort_size": 2},
    )

    contribution = service.create_analytics_contribution(
        wallet.wallet_id,
        actor_did=OWNER,
        consent_id=consent.consent_id,
        template_id="housing_needs_by_county_v1",
        fields={"county": "Multnomah", "need_category": "housing"},
    )

    assert service.verify_analytics_contribution(contribution.contribution_id) is True
    assert "wallet_id" not in contribution.to_dict()
    with pytest.raises(AccessDeniedError, match="not consented"):
        service.create_analytics_contribution(
            wallet.wallet_id,
            actor_did=OWNER,
            consent_id=consent.consent_id,
            template_id="housing_needs_by_county_v1",
            fields={"county": "Multnomah", "precise_lat": 45.515232},
        )


def test_analytics_template_constrains_consent_and_snapshot(tmp_path):
    service = WalletService(storage_dir=tmp_path)
    wallet = service.create_wallet(owner_did=OWNER)
    template = service.create_analytics_template(
        template_id="housing_template_v1",
        title="Housing needs",
        purpose="County-level housing service planning",
        allowed_record_types=["location", "need"],
        allowed_derived_fields=["county", "need_category"],
        aggregation_policy={"min_cohort_size": 5, "epsilon_budget": 0.5},
        created_by="did:key:analyst",
    )

    assert template.template_id == "housing_template_v1"
    assert [item.template_id for item in service.list_analytics_templates()] == ["housing_template_v1"]

    with pytest.raises(AccessDeniedError, match="fields exceed template"):
        service.create_analytics_consent(
            wallet.wallet_id,
            actor_did=OWNER,
            template_id=template.template_id,
            allowed_record_types=["location"],
            allowed_derived_fields=["county", "precise_lat"],
        )

    with pytest.raises(AccessDeniedError, match="min_cohort_size"):
        service.create_analytics_consent(
            wallet.wallet_id,
            actor_did=OWNER,
            template_id=template.template_id,
            allowed_record_types=["location"],
            allowed_derived_fields=["county"],
            aggregation_policy={"min_cohort_size": 2, "epsilon_budget": 0.5},
        )

    consent = service.create_analytics_consent(
        wallet.wallet_id,
        actor_did=OWNER,
        template_id=template.template_id,
        allowed_record_types=["location"],
        allowed_derived_fields=["county"],
    )
    assert consent.aggregation_policy["min_cohort_size"] == 5
    assert consent.aggregation_policy["epsilon_budget"] == 0.5

    snapshot = service.export_wallet_snapshot(wallet.wallet_id)
    restored = WalletService(storage_dir=tmp_path / "restored")
    restored.import_wallet_snapshot(snapshot)
    assert restored.list_analytics_templates()[0].template_id == template.template_id


def test_retired_analytics_template_blocks_new_contributions(tmp_path):
    service = WalletService(storage_dir=tmp_path)
    wallet = service.create_wallet(owner_did=OWNER)
    template = service.create_analytics_template(
        template_id="retired_template_v1",
        title="Retired study",
        purpose="Test retired template behavior",
        allowed_record_types=["location"],
        allowed_derived_fields=["county"],
        aggregation_policy={"min_cohort_size": 2, "epsilon_budget": 0.5},
        created_by="did:key:analyst",
    )
    consent = service.create_analytics_consent(
        wallet.wallet_id,
        actor_did=OWNER,
        template_id=template.template_id,
        allowed_record_types=["location"],
        allowed_derived_fields=["county"],
    )
    service.retire_analytics_template(template.template_id, actor_did="did:key:analyst")

    with pytest.raises(AccessDeniedError, match="not active"):
        service.create_analytics_contribution(
            wallet.wallet_id,
            actor_did=OWNER,
            consent_id=consent.consent_id,
            template_id=template.template_id,
            fields={"county": "Multnomah"},
        )


def test_analytics_duplicate_nullifier_rejected_even_with_new_consent(tmp_path):
    service = WalletService(storage_dir=tmp_path)
    wallet = service.create_wallet(owner_did=OWNER)
    consent1 = service.create_analytics_consent(
        wallet.wallet_id,
        actor_did=OWNER,
        template_id="food_needs_by_county_v1",
        allowed_record_types=["location", "need"],
        allowed_derived_fields=["county"],
    )
    service.create_analytics_contribution(
        wallet.wallet_id,
        actor_did=OWNER,
        consent_id=consent1.consent_id,
        template_id="food_needs_by_county_v1",
        fields={"county": "Lane"},
    )
    consent2 = service.create_analytics_consent(
        wallet.wallet_id,
        actor_did=OWNER,
        template_id="food_needs_by_county_v1",
        allowed_record_types=["location", "need"],
        allowed_derived_fields=["county"],
    )

    with pytest.raises(AccessDeniedError, match="Duplicate"):
        service.create_analytics_contribution(
            wallet.wallet_id,
            actor_did=OWNER,
            consent_id=consent2.consent_id,
            template_id="food_needs_by_county_v1",
            fields={"county": "Lane"},
        )


def test_aggregate_count_suppresses_small_cohorts_and_releases_threshold(tmp_path):
    service = WalletService(storage_dir=tmp_path)
    wallet1 = service.create_wallet(owner_did="did:key:owner1")
    wallet2 = service.create_wallet(owner_did="did:key:owner2")
    template_id = "utility_needs_by_county_v1"

    consent1 = service.create_analytics_consent(
        wallet1.wallet_id,
        actor_did="did:key:owner1",
        template_id=template_id,
        allowed_record_types=["location", "need"],
        allowed_derived_fields=["county"],
        aggregation_policy={"min_cohort_size": 2},
    )
    service.create_analytics_contribution(
        wallet1.wallet_id,
        actor_did="did:key:owner1",
        consent_id=consent1.consent_id,
        template_id=template_id,
        fields={"county": "Multnomah"},
    )

    suppressed = service.run_aggregate_count(template_id)
    assert suppressed.released is False
    assert suppressed.suppressed is True
    assert suppressed.count is None
    assert suppressed.cohort_size == 1

    consent2 = service.create_analytics_consent(
        wallet2.wallet_id,
        actor_did="did:key:owner2",
        template_id=template_id,
        allowed_record_types=["location", "need"],
        allowed_derived_fields=["county"],
        aggregation_policy={"min_cohort_size": 2},
    )
    service.create_analytics_contribution(
        wallet2.wallet_id,
        actor_did="did:key:owner2",
        consent_id=consent2.consent_id,
        template_id=template_id,
        fields={"county": "Multnomah"},
    )

    released = service.run_aggregate_count(template_id)
    assert released.released is True
    assert released.suppressed is False
    assert released.count == 2
    assert released.cohort_size == 2


def test_differentially_private_aggregate_count_suppresses_exact_counts(tmp_path):
    service = WalletService(storage_dir=tmp_path)
    wallet1 = service.create_wallet(owner_did="did:key:owner1")
    wallet2 = service.create_wallet(owner_did="did:key:owner2")
    template_id = "dp_utility_needs_by_county_v1"

    for wallet, owner in [(wallet1, "did:key:owner1"), (wallet2, "did:key:owner2")]:
        consent = service.create_analytics_consent(
            wallet.wallet_id,
            actor_did=owner,
            template_id=template_id,
            allowed_record_types=["location", "need"],
            allowed_derived_fields=["county"],
            aggregation_policy={"min_cohort_size": 2, "epsilon_budget": 0.5},
        )
        service.create_analytics_contribution(
            wallet.wallet_id,
            actor_did=owner,
            consent_id=consent.consent_id,
            template_id=template_id,
            fields={"county": "Multnomah"},
        )

    result = service.run_aggregate_count(template_id, epsilon=0.25)

    assert result.released is True
    assert result.count is None
    assert result.cohort_size == 0
    assert result.noisy_count is not None
    assert result.noisy_count >= 0
    assert result.epsilon == 0.25
    assert result.privacy_budget_key == f"template:{template_id}"
    assert result.privacy_budget_spent == 0.25
    assert result.exact_count_released is False
    assert result.cohort_size_released is False
    assert "differential-privacy:laplace" in result.privacy_notes
    events = service.get_audit_log(wallet1.wallet_id)
    query_events = [event for event in events if event.action == "analytics/query"]
    assert query_events[-1].decision == "allow"
    assert query_events[-1].details["result_id"] == result.result_id
    assert query_events[-1].details["privacy_budget_spent"] == 0.25


def test_differentially_private_aggregate_count_enforces_query_budget(tmp_path):
    service = WalletService(storage_dir=tmp_path)
    wallet1 = service.create_wallet(owner_did="did:key:owner1")
    wallet2 = service.create_wallet(owner_did="did:key:owner2")
    template_id = "dp_food_needs_by_county_v1"

    for wallet, owner in [(wallet1, "did:key:owner1"), (wallet2, "did:key:owner2")]:
        consent = service.create_analytics_consent(
            wallet.wallet_id,
            actor_did=owner,
            template_id=template_id,
            allowed_record_types=["location", "need"],
            allowed_derived_fields=["county"],
            aggregation_policy={"min_cohort_size": 2, "epsilon_budget": 0.3},
        )
        service.create_analytics_contribution(
            wallet.wallet_id,
            actor_did=owner,
            consent_id=consent.consent_id,
            template_id=template_id,
            fields={"county": "Lane"},
        )

    first = service.run_aggregate_count(template_id, epsilon=0.2)
    assert first.privacy_budget_spent == 0.2

    with pytest.raises(AccessDeniedError, match="privacy budget exceeded"):
        service.run_aggregate_count(template_id, epsilon=0.2)


def test_differentially_private_aggregate_count_suppresses_small_cohorts(tmp_path):
    service = WalletService(storage_dir=tmp_path)
    wallet = service.create_wallet(owner_did=OWNER)
    template_id = "dp_small_cohort_v1"
    consent = service.create_analytics_consent(
        wallet.wallet_id,
        actor_did=OWNER,
        template_id=template_id,
        allowed_record_types=["location", "need"],
        allowed_derived_fields=["county"],
        aggregation_policy={"min_cohort_size": 2, "epsilon_budget": 0.5},
    )
    service.create_analytics_contribution(
        wallet.wallet_id,
        actor_did=OWNER,
        consent_id=consent.consent_id,
        template_id=template_id,
        fields={"county": "Lane"},
    )

    result = service.run_aggregate_count(template_id, epsilon=0.25)

    assert result.released is False
    assert result.suppressed is True
    assert result.count is None
    assert result.noisy_count is None
    assert result.cohort_size == 0
    assert result.exact_count_released is False
    assert result.cohort_size_released is False
    assert "suppressed-small-cohort" in result.privacy_notes
    query_events = [event for event in service.get_audit_log(wallet.wallet_id) if event.action == "analytics/query"]
    assert query_events[-1].decision == "suppress"
    assert query_events[-1].details["suppressed"] is True
