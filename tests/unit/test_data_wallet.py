from __future__ import annotations

import json

import pytest

from ipfs_datasets_py.data_wallet import AccessDeniedError, DataWalletService
from ipfs_datasets_py.data_wallet.ucan import resource_for_location, resource_for_record


OWNER = "did:key:owner"
ADVOCATE = "did:key:advocate"


def test_wallet_add_document_encrypts_and_decrypts_for_owner(tmp_path):
    service = DataWalletService(storage_dir=tmp_path / "wallet-store")
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
    service = DataWalletService(storage_dir=tmp_path)
    wallet = service.create_wallet(owner_did=OWNER)
    source = tmp_path / "id.txt"
    source.write_text("private identifier", encoding="utf-8")
    record = service.add_document(wallet.wallet_id, source)

    with pytest.raises(AccessDeniedError):
        service.decrypt_record(wallet.wallet_id, record.record_id, actor_did=ADVOCATE)


def test_analyze_grant_does_not_allow_plaintext_decrypt(tmp_path):
    service = DataWalletService(storage_dir=tmp_path)
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
    service = DataWalletService(storage_dir=tmp_path)
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


def test_location_claims_are_coarse_and_proof_receipts_hide_precise_point(tmp_path):
    service = DataWalletService(storage_dir=tmp_path)
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
    service = DataWalletService(storage_dir=tmp_path)
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
    service = DataWalletService(storage_dir=tmp_path)
    wallet = service.create_wallet(owner_did=OWNER)
    source = tmp_path / "doc.txt"
    source.write_text("stable manifest", encoding="utf-8")
    service.add_document(wallet.wallet_id, source)

    assert service.get_wallet_manifest_canonical(wallet.wallet_id) == service.get_wallet_manifest_canonical(
        wallet.wallet_id
    )


def test_audit_events_form_hash_chain(tmp_path):
    service = DataWalletService(storage_dir=tmp_path)
    wallet = service.create_wallet(owner_did=OWNER)
    source = tmp_path / "doc.txt"
    source.write_text("audit me", encoding="utf-8")
    record = service.add_document(wallet.wallet_id, source)
    service.decrypt_record(wallet.wallet_id, record.record_id, actor_did=OWNER)

    events = service.get_audit_log(wallet.wallet_id)
    assert len(events) >= 3
    for previous, current in zip(events, events[1:]):
        assert current.hash_prev == previous.hash_self
