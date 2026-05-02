from __future__ import annotations

import pytest

from ipfs_datasets_py.document_wallet import (
    DocumentWalletService,
    MemoryStorageAdapter,
    document_resource,
    generate_key,
)
from ipfs_datasets_py.document_wallet.audit import verify_audit_chain
from ipfs_datasets_py.document_wallet.crypto import decrypt_bytes, encrypt_bytes, pack_encrypted_bytes
from ipfs_datasets_py.document_wallet.exceptions import AuthorizationError, KeyUnwrapError
from ipfs_datasets_py.document_wallet.manifest import canonical_json, manifest_ref
from ipfs_datasets_py.document_wallet.models import StorageReceipt
from ipfs_datasets_py.document_wallet.storage import IPFSStorageAdapter


OWNER_DID = "did:key:owner"
DELEGATE_DID = "did:key:delegate"


def test_crypto_round_trip_and_authentication_failure() -> None:
    key = generate_key()
    other_key = generate_key()
    aad = b"wallet:test:doc:test:ver:test"
    encrypted = encrypt_bytes(b"secret document", key, aad=aad)

    assert decrypt_bytes(encrypted, key, aad=aad) == b"secret document"

    with pytest.raises(Exception):
        decrypt_bytes(encrypted, other_key, aad=aad)


def test_manifest_serialization_is_deterministic() -> None:
    left = {"b": [2, {"z": True, "a": None}], "a": 1}
    right = {"a": 1, "b": [2, {"a": None, "z": True}]}

    assert canonical_json(left) == canonical_json(right)
    assert manifest_ref(left) == manifest_ref(right)


def test_owner_can_add_and_decrypt_document_but_storage_has_ciphertext_only() -> None:
    storage = MemoryStorageAdapter()
    service = DocumentWalletService(storage_adapters=[storage])
    owner_key = generate_key()
    wallet = service.create_wallet(owner_did=OWNER_DID)

    document = service.add_document(
        wallet.wallet_id,
        actor_did=OWNER_DID,
        owner_wrapping_key=owner_key,
        content=b"birth certificate plaintext",
        metadata={"title": "Birth certificate"},
        plaintext_hash=True,
    )

    receipt = document.current_version.encrypted_payload_refs[0]
    stored = storage.get(receipt.ref)
    assert b"birth certificate plaintext" not in stored
    assert service.decrypt_document(
        wallet.wallet_id,
        document.document_id,
        actor_did=OWNER_DID,
        wrapping_key=owner_key,
    ) == b"birth certificate plaintext"
    assert document.current_version.plaintext_sha256 is not None
    assert verify_audit_chain(wallet)


def test_analysis_grant_returns_summary_without_plaintext_decrypt_authority() -> None:
    service = DocumentWalletService()
    owner_key = generate_key()
    delegate_key = generate_key()
    wallet = service.create_wallet(owner_did=OWNER_DID)
    document = service.add_document(
        wallet.wallet_id,
        actor_did=OWNER_DID,
        owner_wrapping_key=owner_key,
        content=b"SNAP approval letter. Benefit amount is listed. Case number appears here.",
    )
    resource = document_resource(wallet.wallet_id, document.document_id)

    grant = service.create_grant(
        wallet.wallet_id,
        issuer_did=OWNER_DID,
        audience_did=DELEGATE_DID,
        resources=[resource],
        abilities=["document/analyze"],
        caveats={"output_types": ["summary"]},
        issuer_wrapping_key=owner_key,
        recipient_wrapping_key=delegate_key,
        key_wrap_purpose="analyze",
    )

    result = service.analyze_document(
        wallet.wallet_id,
        document.document_id,
        actor_did=DELEGATE_DID,
        wrapping_key=delegate_key,
    )

    assert result["output_type"] == "summary"
    assert "SNAP approval letter" in result["summary"]
    assert grant.grant_id
    with pytest.raises(AuthorizationError):
        service.decrypt_document(
            wallet.wallet_id,
            document.document_id,
            actor_did=DELEGATE_DID,
            wrapping_key=delegate_key,
        )


def test_revoked_grant_blocks_future_analysis_and_key_wrap() -> None:
    service = DocumentWalletService()
    owner_key = generate_key()
    delegate_key = generate_key()
    wallet = service.create_wallet(owner_did=OWNER_DID)
    document = service.add_document(
        wallet.wallet_id,
        actor_did=OWNER_DID,
        owner_wrapping_key=owner_key,
        content=b"medical appointment summary",
    )
    resource = document_resource(wallet.wallet_id, document.document_id)
    grant = service.create_grant(
        wallet.wallet_id,
        issuer_did=OWNER_DID,
        audience_did=DELEGATE_DID,
        resources=[resource],
        abilities=["document/analyze"],
        caveats={"output_types": ["summary"]},
        issuer_wrapping_key=owner_key,
        recipient_wrapping_key=delegate_key,
        key_wrap_purpose="analyze",
    )

    assert service.analyze_document(
        wallet.wallet_id,
        document.document_id,
        actor_did=DELEGATE_DID,
        wrapping_key=delegate_key,
    )["output_type"] == "summary"

    service.revoke_grant(wallet.wallet_id, actor_did=OWNER_DID, grant_id=grant.grant_id)

    with pytest.raises(AuthorizationError):
        service.analyze_document(
            wallet.wallet_id,
            document.document_id,
            actor_did=DELEGATE_DID,
            wrapping_key=delegate_key,
        )
    assert all(
        key_wrap.status == "revoked"
        for key_wrap in document.current_version.key_wraps
        if key_wrap.grant_id == grant.grant_id
    )


def test_wrong_recipient_key_cannot_unwrap_document() -> None:
    service = DocumentWalletService()
    owner_key = generate_key()
    wallet = service.create_wallet(owner_did=OWNER_DID)
    document = service.add_document(
        wallet.wallet_id,
        actor_did=OWNER_DID,
        owner_wrapping_key=owner_key,
        content=b"tax return",
    )

    with pytest.raises(KeyUnwrapError):
        service.decrypt_document(
            wallet.wallet_id,
            document.document_id,
            actor_did=OWNER_DID,
            wrapping_key=generate_key(),
        )


class FakeIPFSBackend:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def add_bytes(self, data: bytes, *, pin: bool = True) -> str:
        cid = f"fake{len(self.objects)}"
        self.objects[cid] = data
        return cid

    def cat(self, cid: str) -> bytes:
        return self.objects[cid]


def test_ipfs_storage_adapter_uses_backend_without_plaintext() -> None:
    backend = FakeIPFSBackend()
    adapter = IPFSStorageAdapter(backend=backend)
    encrypted = pack_encrypted_bytes(encrypt_bytes(b"private", generate_key(), aad=b"aad"))

    receipt = adapter.put(encrypted)

    assert isinstance(receipt, StorageReceipt)
    assert receipt.provider == "ipfs"
    assert receipt.ref == "ipfs://fake0"
    assert adapter.get(receipt.ref) == encrypted
    assert b"private" not in backend.objects["fake0"]

