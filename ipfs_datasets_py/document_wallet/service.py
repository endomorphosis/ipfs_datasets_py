"""High-level service API for encrypted document wallets."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .analysis import summarize_text_bytes
from .audit import record_audit_event
from .crypto import (
    AES256_GCM,
    KEY_WRAP_AES256_GCM,
    EncryptedBytes,
    decrypt_bytes,
    encrypt_bytes,
    generate_key,
    pack_encrypted_bytes,
    sha256_hex,
    unpack_encrypted_bytes,
    unwrap_key,
    wrap_key,
)
from .exceptions import AuthorizationError, DocumentNotFoundError, KeyUnwrapError, WalletNotFoundError
from .models import (
    DocumentRecord,
    DocumentVersion,
    KeyWrap,
    WalletGrant,
    WalletRecord,
    new_id,
    utc_now,
)
from .storage import MemoryStorageAdapter, WalletStorageAdapter
from .ucan import AccessDecision, GrantRevocationStore, WalletGrantVerifier, document_resource, wallet_resource


class DocumentWalletService:
    """In-process service for wallet operations.

    Persistence beyond the encrypted blobs is intentionally in-memory for the
    first vertical slice. Manifests are deterministic and can be persisted by a
    later repository or database adapter without changing callers.
    """

    def __init__(
        self,
        *,
        storage_adapters: Optional[Iterable[WalletStorageAdapter]] = None,
        revocations: Optional[GrantRevocationStore] = None,
    ) -> None:
        self.storage_adapters: List[WalletStorageAdapter] = list(storage_adapters or [MemoryStorageAdapter()])
        self.wallets: Dict[str, WalletRecord] = {}
        self.revocations = revocations or GrantRevocationStore()
        self.verifier = WalletGrantVerifier(self.revocations)

    def create_wallet(
        self,
        *,
        owner_did: str,
        controller_dids: Optional[List[str]] = None,
        recovery_policy: Optional[Dict[str, Any]] = None,
        storage_policy: Optional[Dict[str, Any]] = None,
    ) -> WalletRecord:
        wallet = WalletRecord(
            wallet_id=new_id("wallet"),
            owner_did=owner_did,
            controller_dids=list(controller_dids or [owner_did]),
            recovery_policy=recovery_policy or {},
            storage_policy=storage_policy or {},
        )
        wallet.refresh_manifest_head()
        self.wallets[wallet.wallet_id] = wallet
        record_audit_event(
            wallet,
            actor_did=owner_did,
            action="wallet/create",
            resource=wallet_resource(wallet.wallet_id),
            decision="allow",
        )
        return wallet

    def load_wallet(self, wallet_id: str) -> WalletRecord:
        try:
            return self.wallets[wallet_id]
        except KeyError as exc:
            raise WalletNotFoundError(f"wallet not found: {wallet_id}") from exc

    def add_document(
        self,
        wallet_id: str,
        *,
        actor_did: str,
        owner_wrapping_key: bytes,
        content: Optional[bytes] = None,
        path: Optional[str | Path] = None,
        metadata: Optional[Dict[str, Any]] = None,
        public_descriptor: Optional[Dict[str, Any]] = None,
        plaintext_hash: bool = False,
    ) -> DocumentRecord:
        wallet = self.load_wallet(wallet_id)
        self._require_owner_or_grant(wallet, actor_did=actor_did, resource=wallet_resource(wallet_id), ability="document/add")
        if content is None:
            if path is None:
                raise ValueError("either content or path must be provided")
            content = Path(path).read_bytes()

        document_id = new_id("doc")
        version_id = new_id("ver")
        dek = generate_key()
        resource = document_resource(wallet_id, document_id)
        aad = self._document_aad(wallet_id, document_id, version_id)

        encrypted_payload = encrypt_bytes(content, dek, aad=aad)
        packed_payload = pack_encrypted_bytes(encrypted_payload)
        receipts = [adapter.put(packed_payload) for adapter in self.storage_adapters]
        encrypted_metadata = encrypt_bytes(
            json.dumps(metadata or {}, sort_keys=True).encode("utf-8"),
            dek,
            aad=aad + b":metadata",
        )
        owner_wrap = self._make_key_wrap(
            recipient_did=actor_did,
            key_id=f"{actor_did}#local",
            dek=dek,
            wrapping_key=owner_wrapping_key,
            aad=aad,
            purpose="decrypt",
        )

        version = DocumentVersion(
            version_id=version_id,
            document_id=document_id,
            encrypted_payload_refs=receipts,
            ciphertext_sha256=sha256_hex(packed_payload),
            plaintext_sha256=sha256_hex(content) if plaintext_hash else None,
            encrypted_metadata=encrypted_metadata.to_dict(),
            key_wraps=[owner_wrap],
            encryption_suite=AES256_GCM,
        )
        document = DocumentRecord(
            document_id=document_id,
            wallet_id=wallet_id,
            current_version_id=version_id,
            public_descriptor=public_descriptor or {"content_type": "application/octet-stream"},
            versions={version_id: version},
        )
        wallet.documents[document_id] = document
        wallet.refresh_manifest_head()
        record_audit_event(
            wallet,
            actor_did=actor_did,
            action="document/add",
            resource=resource,
            decision="allow",
            details={"document_id": document_id, "version_id": version_id},
        )
        return document

    def create_grant(
        self,
        wallet_id: str,
        *,
        issuer_did: str,
        audience_did: str,
        resources: List[str],
        abilities: List[str],
        caveats: Optional[Dict[str, Any]] = None,
        recipient_wrapping_key: Optional[bytes] = None,
        issuer_wrapping_key: Optional[bytes] = None,
        key_wrap_purpose: str = "decrypt",
    ) -> WalletGrant:
        wallet = self.load_wallet(wallet_id)
        for resource in resources:
            self._require_owner_or_grant(wallet, actor_did=issuer_did, resource=resource, ability="grant/create")
        grant = WalletGrant(
            grant_id=new_id("grant"),
            issuer_did=issuer_did,
            audience_did=audience_did,
            resources=list(resources),
            abilities=list(abilities),
            caveats=caveats or {},
            expires_at=(caveats or {}).get("expires_at"),
        )
        wallet.grants[grant.grant_id] = grant

        if recipient_wrapping_key is not None:
            if issuer_wrapping_key is None:
                raise ValueError("issuer_wrapping_key is required when recipient_wrapping_key is provided")
            self._add_grant_key_wraps(
                wallet,
                grant=grant,
                issuer_did=issuer_did,
                issuer_wrapping_key=issuer_wrapping_key,
                recipient_wrapping_key=recipient_wrapping_key,
                purpose=key_wrap_purpose,
            )

        wallet.refresh_manifest_head()
        record_audit_event(
            wallet,
            actor_did=issuer_did,
            action="grant/create",
            resource=",".join(resources),
            decision="allow",
            grant_id=grant.grant_id,
            details={"audience_did": audience_did, "abilities": abilities},
        )
        return grant

    def revoke_grant(self, wallet_id: str, *, actor_did: str, grant_id: str) -> WalletGrant:
        wallet = self.load_wallet(wallet_id)
        grant = wallet.grants[grant_id]
        self._require_owner_or_grant(wallet, actor_did=actor_did, resource=wallet_resource(wallet_id), ability="grant/revoke")
        grant.status = "revoked"
        grant.revoked_at = utc_now()
        self.revocations.revoke(grant_id, revoked_at=grant.revoked_at)
        for document in wallet.documents.values():
            for version in document.versions.values():
                for key_wrap in version.key_wraps:
                    if key_wrap.grant_id == grant_id:
                        key_wrap.status = "revoked"
        wallet.refresh_manifest_head()
        record_audit_event(
            wallet,
            actor_did=actor_did,
            action="grant/revoke",
            resource=wallet_resource(wallet_id),
            decision="allow",
            grant_id=grant_id,
        )
        return grant

    def decrypt_document(
        self,
        wallet_id: str,
        document_id: str,
        *,
        actor_did: str,
        wrapping_key: bytes,
    ) -> bytes:
        wallet, document, version = self._get_current_version(wallet_id, document_id)
        resource = document_resource(wallet_id, document_id)
        decision = self._require_owner_or_grant(wallet, actor_did=actor_did, resource=resource, ability="document/decrypt")
        plaintext = self._decrypt_version(version, wallet_id=wallet_id, actor_did=actor_did, wrapping_key=wrapping_key)
        record_audit_event(
            wallet,
            actor_did=actor_did,
            action="document/decrypt",
            resource=resource,
            decision="allow",
            grant_id=decision.grant_id,
        )
        return plaintext

    def analyze_document(
        self,
        wallet_id: str,
        document_id: str,
        *,
        actor_did: str,
        wrapping_key: bytes,
        output_type: str = "summary",
    ) -> Dict[str, Any]:
        wallet, document, version = self._get_current_version(wallet_id, document_id)
        resource = document_resource(wallet_id, document_id)
        decision = self._require_owner_or_grant(
            wallet,
            actor_did=actor_did,
            resource=resource,
            ability="document/analyze",
            context={"output_type": output_type},
        )
        plaintext = self._decrypt_version(
            version,
            wallet_id=wallet_id,
            actor_did=actor_did,
            wrapping_key=wrapping_key,
            allowed_purposes={"decrypt", "analyze"},
        )
        if output_type != "summary":
            raise AuthorizationError(f"unsupported analysis output type: {output_type}")
        result = summarize_text_bytes(plaintext)
        record_audit_event(
            wallet,
            actor_did=actor_did,
            action="document/analyze",
            resource=resource,
            decision="allow",
            grant_id=decision.grant_id,
            details={"output_type": output_type},
        )
        return result

    def list_documents(self, wallet_id: str, *, actor_did: str) -> List[Dict[str, Any]]:
        wallet = self.load_wallet(wallet_id)
        self._require_owner_or_grant(wallet, actor_did=actor_did, resource=f"{wallet_resource(wallet_id)}/documents", ability="wallet/read")
        return [
            {
                "document_id": document.document_id,
                "current_version_id": document.current_version_id,
                "public_descriptor": document.public_descriptor,
                "status": document.status,
            }
            for document in wallet.documents.values()
        ]

    def _require_owner_or_grant(
        self,
        wallet: WalletRecord,
        *,
        actor_did: str,
        resource: str,
        ability: str,
        context: Optional[Dict[str, object]] = None,
    ):
        if actor_did in wallet.controller_dids:
            return AccessDecision(True, "owner/controller", None)
        return self.verifier.require(
            wallet.grants.values(),
            actor_did=actor_did,
            resource=resource,
            ability=ability,
            context=context,
        )

    def _get_current_version(self, wallet_id: str, document_id: str):
        wallet = self.load_wallet(wallet_id)
        try:
            document = wallet.documents[document_id]
        except KeyError as exc:
            raise DocumentNotFoundError(f"document not found: {document_id}") from exc
        return wallet, document, document.current_version

    def _decrypt_version(
        self,
        version: DocumentVersion,
        *,
        wallet_id: str,
        actor_did: str,
        wrapping_key: bytes,
        allowed_purposes: Optional[set[str]] = None,
    ) -> bytes:
        allowed_purposes = allowed_purposes or {"decrypt"}
        aad = self._document_aad(wallet_id, version.document_id, version.version_id)
        for key_wrap in version.key_wraps:
            if key_wrap.recipient_did != actor_did:
                continue
            if key_wrap.status != "active":
                continue
            if key_wrap.purpose not in allowed_purposes:
                continue
            if key_wrap.expires_at is not None and utc_now() > float(key_wrap.expires_at):
                continue
            try:
                dek = unwrap_key(EncryptedBytes.from_dict(key_wrap.wrapped_key), wrapping_key, aad=aad)
                packed = self._fetch_first_payload(version)
                if sha256_hex(packed) != version.ciphertext_sha256:
                    raise KeyUnwrapError("stored ciphertext hash does not match manifest")
                return decrypt_bytes(unpack_encrypted_bytes(packed), dek, aad=aad)
            except KeyUnwrapError:
                continue
        raise KeyUnwrapError("no active key wrap could decrypt this document")

    def _fetch_first_payload(self, version: DocumentVersion) -> bytes:
        if not version.encrypted_payload_refs:
            raise DocumentNotFoundError("document version has no encrypted payload refs")
        receipt = version.encrypted_payload_refs[0]
        for adapter in self.storage_adapters:
            if adapter.provider == receipt.provider:
                return adapter.get(receipt.ref)
        raise DocumentNotFoundError(f"no storage adapter configured for provider: {receipt.provider}")

    def _make_key_wrap(
        self,
        *,
        recipient_did: str,
        key_id: str,
        dek: bytes,
        wrapping_key: bytes,
        aad: bytes,
        grant_id: Optional[str] = None,
        purpose: str,
        expires_at: Optional[float] = None,
    ) -> KeyWrap:
        return KeyWrap(
            wrap_id=new_id("wrap"),
            recipient_did=recipient_did,
            key_id=key_id,
            algorithm=KEY_WRAP_AES256_GCM,
            wrapped_key=wrap_key(dek, wrapping_key, aad=aad).to_dict(),
            grant_id=grant_id,
            purpose=purpose,
            expires_at=expires_at,
        )

    def _add_grant_key_wraps(
        self,
        wallet: WalletRecord,
        *,
        grant: WalletGrant,
        issuer_did: str,
        issuer_wrapping_key: bytes,
        recipient_wrapping_key: bytes,
        purpose: str,
    ) -> None:
        for resource in grant.resources:
            parts = resource.split("/documents/")
            if len(parts) != 2:
                continue
            document_id = parts[1].split("/", 1)[0]
            if document_id not in wallet.documents:
                continue
            document = wallet.documents[document_id]
            version = document.current_version
            dek = self._unwrap_for_actor(
                version,
                wallet_id=wallet.wallet_id,
                actor_did=issuer_did,
                wrapping_key=issuer_wrapping_key,
            )
            version.key_wraps.append(
                self._make_key_wrap(
                    recipient_did=grant.audience_did,
                    key_id=f"{grant.audience_did}#delegated",
                    dek=dek,
                    wrapping_key=recipient_wrapping_key,
                    aad=self._document_aad(wallet.wallet_id, document_id, version.version_id),
                    grant_id=grant.grant_id,
                    purpose=purpose,
                    expires_at=grant.expires_at,
                )
            )

    def _unwrap_for_actor(
        self,
        version: DocumentVersion,
        *,
        wallet_id: str,
        actor_did: str,
        wrapping_key: bytes,
    ) -> bytes:
        aad = self._document_aad(wallet_id, version.document_id, version.version_id)
        for key_wrap in version.key_wraps:
            if key_wrap.recipient_did == actor_did and key_wrap.status == "active":
                return unwrap_key(EncryptedBytes.from_dict(key_wrap.wrapped_key), wrapping_key, aad=aad)
        raise KeyUnwrapError("issuer cannot unwrap document key")

    @staticmethod
    def _document_aad(wallet_id: str, document_id: str, version_id: str) -> bytes:
        return f"document-wallet:{wallet_id}:{document_id}:{version_id}".encode("utf-8")
