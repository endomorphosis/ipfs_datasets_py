from __future__ import annotations

import json
import os

os.environ.setdefault("IPFS_DATASETS_AUTO_INSTALL", "false")
os.environ.setdefault("IPFS_AUTO_INSTALL", "false")
os.environ.setdefault("IPFS_DATASETS_PY_MINIMAL_IMPORTS", "1")

import pytest

from ipfs_datasets_py.wallet import AccessDeniedError, ApprovalRequiredError, WalletService
from ipfs_datasets_py.wallet.storage import IPFSEncryptedBlobStore
from ipfs_datasets_py.wallet.ucan import resource_for_location, resource_for_record


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
