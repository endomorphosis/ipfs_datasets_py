"""High-level data wallet service API."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from .audit import append_audit_event
from .crypto import (
    ENCRYPTION_SUITE,
    KEY_WRAP_ALGORITHM,
    EncryptedBlob,
    b64decode,
    b64encode,
    decrypt_bytes,
    encrypt_bytes,
    random_key,
    sha256_hex,
    unwrap_key,
    wrap_key,
)
from .exceptions import AccessDeniedError, GrantError, MissingRecordError
from .location import make_coarse_location_claim, region_membership_statement, serialize_location
from .manifest import canonical_bytes, canonical_dumps
from .models import (
    AuditEvent,
    DataRecord,
    DataVersion,
    DerivedArtifact,
    Grant,
    KeyWrap,
    LocationClaim,
    ProofReceipt,
    Wallet,
    utc_now,
)
from .proofs import create_simulated_proof_receipt
from .storage import LocalEncryptedBlobStore
from .ucan import assert_grant_allows, resource_for_location, resource_for_record, resource_for_wallet


class DataWalletService:
    """In-process service for encrypted wallet records and delegated access."""

    def __init__(self, storage_dir: Optional[str | Path] = None) -> None:
        self.storage = LocalEncryptedBlobStore(storage_dir)
        self.wallets: Dict[str, Wallet] = {}
        self.records: Dict[str, DataRecord] = {}
        self.versions: Dict[str, DataVersion] = {}
        self.grants: Dict[str, Grant] = {}
        self.derived_artifacts: Dict[str, DerivedArtifact] = {}
        self.proofs: Dict[str, ProofReceipt] = {}
        self.audit_events: Dict[str, List[AuditEvent]] = {}
        self._principal_secrets: Dict[str, bytes] = {}

    def create_wallet(self, owner_did: str, device_did: Optional[str] = None) -> Wallet:
        device = device_did or owner_did
        wallet = Wallet(
            wallet_id=f"wallet-{uuid.uuid4().hex}",
            owner_did=owner_did,
            controller_dids=[owner_did],
            device_dids=[device],
            default_privacy_policy={
                "location_default": "coarse",
                "analytics_min_cohort_size": 10,
            },
        )
        self.wallets[wallet.wallet_id] = wallet
        self.audit_events[wallet.wallet_id] = []
        self._ensure_principal_secret(owner_did)
        self._ensure_principal_secret(device)
        append_audit_event(
            self.audit_events[wallet.wallet_id],
            wallet_id=wallet.wallet_id,
            actor_did=owner_did,
            action="wallet/create",
            resource=resource_for_wallet(wallet.wallet_id),
            decision="allow",
        )
        return wallet

    def add_document(
        self,
        wallet_id: str,
        path: str | Path,
        *,
        actor_did: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        sensitivity: str = "restricted",
    ) -> DataRecord:
        path_obj = Path(path)
        plaintext = path_obj.read_bytes()
        private_metadata = {"filename": path_obj.name, **(metadata or {})}
        return self.add_record(
            wallet_id,
            data_type="document",
            plaintext=plaintext,
            actor_did=actor_did,
            private_metadata=private_metadata,
            sensitivity=sensitivity,
            public_descriptor="document",
        )

    def add_location(
        self,
        wallet_id: str,
        *,
        lat: float,
        lon: float,
        actor_did: Optional[str] = None,
        source: str = "user",
        accuracy_m: float | None = None,
    ) -> DataRecord:
        plaintext = serialize_location(lat, lon, source=source, accuracy_m=accuracy_m)
        private_metadata = {"source": source, "accuracy_m": accuracy_m}
        return self.add_record(
            wallet_id,
            data_type="location",
            plaintext=plaintext,
            actor_did=actor_did,
            private_metadata=private_metadata,
            sensitivity="restricted",
            public_descriptor="location",
        )

    def add_record(
        self,
        wallet_id: str,
        *,
        data_type: str,
        plaintext: bytes,
        actor_did: Optional[str] = None,
        private_metadata: Optional[Dict[str, Any]] = None,
        sensitivity: str = "restricted",
        public_descriptor: str = "record",
    ) -> DataRecord:
        wallet = self._wallet(wallet_id)
        actor = actor_did or wallet.owner_did
        self._assert_controller(wallet, actor)

        record_id = f"rec-{uuid.uuid4().hex}"
        version_id = f"ver-{uuid.uuid4().hex}"
        dek = random_key()
        payload_aad = self._payload_aad(wallet_id, record_id, version_id, data_type)
        encrypted_payload = encrypt_bytes(plaintext, dek, payload_aad)
        payload_ref = self.storage.put(canonical_bytes(encrypted_payload.to_dict()))

        metadata_ref = None
        if private_metadata:
            encrypted_metadata = encrypt_bytes(canonical_bytes(private_metadata), dek, payload_aad | {"kind": "metadata"})
            metadata_ref = self.storage.put(canonical_bytes(encrypted_metadata.to_dict()))

        wrap_aad = self._wrap_aad(wallet_id, record_id, version_id, actor)
        key_wrap = KeyWrap(
            wrap_id=f"wrap-{uuid.uuid4().hex}",
            record_id=record_id,
            version_id=version_id,
            recipient_did=actor,
            wrapped_dek=wrap_key(dek, self._ensure_principal_secret(actor), wrap_aad),
            wrap_algorithm=KEY_WRAP_ALGORITHM,
        )
        version = DataVersion(
            version_id=version_id,
            record_id=record_id,
            encrypted_payload_ref=payload_ref,
            encrypted_metadata_ref=metadata_ref,
            ciphertext_hash=payload_ref.sha256,
            encryption_suite=ENCRYPTION_SUITE,
            key_wraps=[key_wrap],
        )
        record = DataRecord(
            record_id=record_id,
            wallet_id=wallet_id,
            data_type=data_type,
            sensitivity=sensitivity,
            public_descriptor=public_descriptor,
            current_version_id=version_id,
        )
        self.records[record_id] = record
        self.versions[version_id] = version
        wallet.updated_at = utc_now()
        wallet.manifest_head = sha256_hex(canonical_bytes(self.get_wallet_manifest(wallet_id)))
        append_audit_event(
            self.audit_events[wallet_id],
            wallet_id=wallet_id,
            actor_did=actor,
            action="record/add",
            resource=resource_for_record(wallet_id, record_id),
            decision="allow",
            details={"data_type": data_type},
        )
        return record

    def create_grant(
        self,
        *,
        wallet_id: str,
        issuer_did: str,
        audience_did: str,
        resources: List[str],
        abilities: List[str],
        caveats: Optional[Dict[str, Any]] = None,
        expires_at: Optional[str] = None,
    ) -> Grant:
        wallet = self._wallet(wallet_id)
        self._assert_controller(wallet, issuer_did)
        if not resources or not abilities:
            raise GrantError("Grant requires at least one resource and ability")
        grant = Grant(
            grant_id=f"grant-{uuid.uuid4().hex}",
            issuer_did=issuer_did,
            audience_did=audience_did,
            resources=list(resources),
            abilities=list(abilities),
            caveats=caveats or {},
            expires_at=expires_at,
        )
        self.grants[grant.grant_id] = grant
        self._ensure_principal_secret(audience_did)
        if "record/decrypt" in abilities or "*" in abilities:
            self._wrap_granted_record_keys(wallet_id, issuer_did, audience_did, grant)
        append_audit_event(
            self.audit_events[wallet_id],
            wallet_id=wallet_id,
            actor_did=issuer_did,
            action="grant/create",
            resource=",".join(resources),
            decision="allow",
            details={"abilities": abilities, "audience_did": audience_did},
            grant_id=grant.grant_id,
        )
        return grant

    def revoke_grant(self, wallet_id: str, grant_id: str, *, actor_did: str) -> Grant:
        wallet = self._wallet(wallet_id)
        self._assert_controller(wallet, actor_did)
        grant = self.grants[grant_id]
        grant.status = "revoked"
        append_audit_event(
            self.audit_events[wallet_id],
            wallet_id=wallet_id,
            actor_did=actor_did,
            action="grant/revoke",
            resource=",".join(grant.resources),
            decision="allow",
            grant_id=grant_id,
        )
        return grant

    def decrypt_record(
        self,
        wallet_id: str,
        record_id: str,
        *,
        actor_did: str,
        grant_id: Optional[str] = None,
    ) -> bytes:
        record = self._record(wallet_id, record_id)
        if actor_did != self._wallet(wallet_id).owner_did:
            if grant_id is None:
                raise AccessDeniedError("Non-owner decrypt requires a grant")
            grant = self.grants[grant_id]
            assert_grant_allows(
                grant,
                audience_did=actor_did,
                resource=resource_for_record(wallet_id, record_id),
                ability="record/decrypt",
            )
        version = self.versions[record.current_version_id]
        dek = self._unwrap_dek(version, wallet_id, actor_did)
        payload_data = json.loads(self.storage.get(version.encrypted_payload_ref).decode("utf-8"))
        plaintext = decrypt_bytes(
            EncryptedBlob.from_dict(payload_data),
            dek,
            self._payload_aad(wallet_id, record_id, version.version_id, record.data_type),
        )
        append_audit_event(
            self.audit_events[wallet_id],
            wallet_id=wallet_id,
            actor_did=actor_did,
            action="record/decrypt",
            resource=resource_for_record(wallet_id, record_id),
            decision="allow",
            grant_id=grant_id,
        )
        return plaintext

    def create_coarse_location_claim(
        self,
        wallet_id: str,
        record_id: str,
        *,
        actor_did: str,
        grant_id: Optional[str] = None,
        precision: int = 2,
    ) -> LocationClaim:
        record = self._record(wallet_id, record_id)
        if record.data_type != "location":
            raise ValueError("Record is not a location record")
        if actor_did != self._wallet(wallet_id).owner_did:
            if grant_id is None:
                raise AccessDeniedError("Coarse location claim requires a grant")
            assert_grant_allows(
                self.grants[grant_id],
                audience_did=actor_did,
                resource=resource_for_location(wallet_id, record_id),
                ability="location/read_coarse",
            )
        raw = self.decrypt_record(wallet_id, record_id, actor_did=self._wallet(wallet_id).owner_did)
        payload = json.loads(raw.decode("utf-8"))
        claim = make_coarse_location_claim(record_id, payload["lat"], payload["lon"], precision)
        append_audit_event(
            self.audit_events[wallet_id],
            wallet_id=wallet_id,
            actor_did=actor_did,
            action="location/read_coarse",
            resource=resource_for_location(wallet_id, record_id),
            decision="allow",
            grant_id=grant_id,
        )
        return claim

    def create_location_region_proof(
        self,
        wallet_id: str,
        record_id: str,
        *,
        actor_did: str,
        region_id: str,
        grant_id: Optional[str] = None,
    ) -> ProofReceipt:
        record = self._record(wallet_id, record_id)
        if record.data_type != "location":
            raise ValueError("Record is not a location record")
        if actor_did != self._wallet(wallet_id).owner_did:
            if grant_id is None:
                raise AccessDeniedError("Location proof requires a grant")
            assert_grant_allows(
                self.grants[grant_id],
                audience_did=actor_did,
                resource=resource_for_location(wallet_id, record_id),
                ability="location/prove_region",
            )
        raw = self.decrypt_record(wallet_id, record_id, actor_did=self._wallet(wallet_id).owner_did)
        payload = json.loads(raw.decode("utf-8"))
        statement = region_membership_statement(payload["lat"], payload["lon"], region_id)
        receipt = create_simulated_proof_receipt(
            wallet_id=wallet_id,
            proof_type="location_region",
            statement=statement,
            public_inputs={"region_id": region_id, "claim": "location_in_region"},
            witness_record_ids=[record_id],
        )
        self.proofs[receipt.proof_id] = receipt
        self.versions[record.current_version_id].proof_receipt_ids.append(receipt.proof_id)
        append_audit_event(
            self.audit_events[wallet_id],
            wallet_id=wallet_id,
            actor_did=actor_did,
            action="proof/create",
            resource=resource_for_location(wallet_id, record_id),
            decision="allow",
            details={"proof_type": receipt.proof_type, "is_simulated": receipt.is_simulated},
            grant_id=grant_id,
        )
        return receipt

    def analyze_record_summary(
        self,
        wallet_id: str,
        record_id: str,
        *,
        actor_did: str,
        grant_id: Optional[str] = None,
        max_chars: int = 200,
    ) -> DerivedArtifact:
        if actor_did != self._wallet(wallet_id).owner_did:
            if grant_id is None:
                raise AccessDeniedError("Analysis requires a grant")
            assert_grant_allows(
                self.grants[grant_id],
                audience_did=actor_did,
                resource=resource_for_record(wallet_id, record_id),
                ability="record/analyze",
            )
        plaintext = self.decrypt_record(wallet_id, record_id, actor_did=self._wallet(wallet_id).owner_did)
        text = plaintext.decode("utf-8", errors="replace")
        summary = {"summary": text[:max_chars], "truncated": len(text) > max_chars}
        artifact_key = random_key()
        encrypted = encrypt_bytes(canonical_bytes(summary), artifact_key, {"wallet_id": wallet_id, "record_id": record_id, "kind": "derived"})
        ref = self.storage.put(canonical_bytes(encrypted.to_dict()))
        artifact = DerivedArtifact(
            artifact_id=f"artifact-{uuid.uuid4().hex}",
            wallet_id=wallet_id,
            source_record_ids=[record_id],
            artifact_type="summary",
            output_policy="derived_only",
            encrypted_payload_ref=ref,
        )
        self.derived_artifacts[artifact.artifact_id] = artifact
        self.versions[self._record(wallet_id, record_id).current_version_id].derived_artifact_ids.append(artifact.artifact_id)
        append_audit_event(
            self.audit_events[wallet_id],
            wallet_id=wallet_id,
            actor_did=actor_did,
            action="record/analyze",
            resource=resource_for_record(wallet_id, record_id),
            decision="allow",
            details={"artifact_id": artifact.artifact_id, "artifact_type": artifact.artifact_type},
            grant_id=grant_id,
        )
        return artifact

    def get_wallet_manifest(self, wallet_id: str) -> Dict[str, Any]:
        wallet = self._wallet(wallet_id)
        records = [record for record in self.records.values() if record.wallet_id == wallet_id]
        versions = [
            self.versions[record.current_version_id].to_dict()
            for record in sorted(records, key=lambda item: item.record_id)
        ]
        return {
            "wallet": wallet.to_dict(),
            "records": [record.to_dict() for record in sorted(records, key=lambda item: item.record_id)],
            "versions": versions,
        }

    def get_wallet_manifest_canonical(self, wallet_id: str) -> str:
        return canonical_dumps(self.get_wallet_manifest(wallet_id))

    def get_audit_log(self, wallet_id: str) -> List[AuditEvent]:
        self._wallet(wallet_id)
        return list(self.audit_events[wallet_id])

    def _wallet(self, wallet_id: str) -> Wallet:
        if wallet_id not in self.wallets:
            raise MissingRecordError(f"Wallet not found: {wallet_id}")
        return self.wallets[wallet_id]

    def _record(self, wallet_id: str, record_id: str) -> DataRecord:
        if record_id not in self.records or self.records[record_id].wallet_id != wallet_id:
            raise MissingRecordError(f"Record not found: {record_id}")
        return self.records[record_id]

    def _assert_controller(self, wallet: Wallet, actor_did: str) -> None:
        if actor_did not in wallet.controller_dids and actor_did != wallet.owner_did:
            raise AccessDeniedError(f"{actor_did} is not a wallet controller")

    def _ensure_principal_secret(self, did: str) -> bytes:
        if did not in self._principal_secrets:
            self._principal_secrets[did] = random_key()
        return self._principal_secrets[did]

    def _payload_aad(self, wallet_id: str, record_id: str, version_id: str, data_type: str) -> Dict[str, str]:
        return {
            "wallet_id": wallet_id,
            "record_id": record_id,
            "version_id": version_id,
            "data_type": data_type,
        }

    def _wrap_aad(self, wallet_id: str, record_id: str, version_id: str, recipient_did: str) -> Dict[str, str]:
        return {
            "wallet_id": wallet_id,
            "record_id": record_id,
            "version_id": version_id,
            "recipient_did": recipient_did,
        }

    def _unwrap_dek(self, version: DataVersion, wallet_id: str, actor_did: str) -> bytes:
        for key_wrap in version.key_wraps:
            if key_wrap.recipient_did != actor_did or key_wrap.status != "active":
                continue
            return unwrap_key(
                key_wrap.wrapped_dek,
                self._ensure_principal_secret(actor_did),
                self._wrap_aad(wallet_id, key_wrap.record_id, key_wrap.version_id, actor_did),
            )
        raise AccessDeniedError(f"No active key wrap for {actor_did}")

    def _wrap_granted_record_keys(
        self,
        wallet_id: str,
        issuer_did: str,
        audience_did: str,
        grant: Grant,
    ) -> None:
        for resource in grant.resources:
            record_id = self._record_id_from_resource(wallet_id, resource)
            if record_id is None:
                continue
            record = self._record(wallet_id, record_id)
            version = self.versions[record.current_version_id]
            dek = self._unwrap_dek(version, wallet_id, issuer_did)
            key_wrap = KeyWrap(
                wrap_id=f"wrap-{uuid.uuid4().hex}",
                record_id=record_id,
                version_id=version.version_id,
                recipient_did=audience_did,
                wrapped_dek=wrap_key(
                    dek,
                    self._ensure_principal_secret(audience_did),
                    self._wrap_aad(wallet_id, record_id, version.version_id, audience_did),
                ),
                wrap_algorithm=KEY_WRAP_ALGORITHM,
                grant_id=grant.grant_id,
                expires_at=grant.expires_at,
            )
            version.key_wraps.append(key_wrap)

    def _record_id_from_resource(self, wallet_id: str, resource: str) -> Optional[str]:
        prefix = f"wallet://{wallet_id}/records/"
        if not resource.startswith(prefix):
            return None
        suffix = resource[len(prefix) :]
        if "/" in suffix or not suffix:
            return None
        return suffix
