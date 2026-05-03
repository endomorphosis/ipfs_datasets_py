"""High-level data wallet service API."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from .analytics import aggregate_count, contribution_nullifier, make_contribution
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
    AggregateResult,
    AccessRequest,
    AnalyticsConsent,
    AnalyticsContribution,
    AnalyticsTemplate,
    ApprovalRequest,
    AuditEvent,
    DataRecord,
    DataVersion,
    DerivedArtifact,
    Grant,
    KeyWrap,
    LocationClaim,
    ProofReceipt,
    StorageHealthReport,
    StorageRef,
    StorageReplicaStatus,
    Wallet,
    WalletInvocation,
    utc_now,
)
from .multisig import (
    approve_request,
    create_approval_request,
    normalize_governance_policy,
    operation_requires_approval,
    verify_approval,
)
from .proofs import create_simulated_proof_receipt
from .storage import EncryptedBlobStore, LocalEncryptedBlobStore
from .ucan import (
    assert_grant_allows,
    assert_invocation_allows,
    create_invocation,
    resource_for_location,
    resource_for_record,
    resource_for_wallet,
)


class DataWalletService:
    """In-process service for encrypted wallet records and delegated access."""

    def __init__(
        self,
        storage_dir: Optional[str | Path] = None,
        *,
        storage_backend: Optional[EncryptedBlobStore] = None,
    ) -> None:
        self.storage = storage_backend or LocalEncryptedBlobStore(storage_dir)
        self.wallets: Dict[str, Wallet] = {}
        self.records: Dict[str, DataRecord] = {}
        self.versions: Dict[str, DataVersion] = {}
        self.grants: Dict[str, Grant] = {}
        self.invocations: Dict[str, WalletInvocation] = {}
        self.derived_artifacts: Dict[str, DerivedArtifact] = {}
        self.proofs: Dict[str, ProofReceipt] = {}
        self.analytics_consents: Dict[str, AnalyticsConsent] = {}
        self.analytics_contributions: Dict[str, AnalyticsContribution] = {}
        self.analytics_templates: Dict[str, AnalyticsTemplate] = {}
        self.aggregate_results: Dict[str, AggregateResult] = {}
        self.analytics_query_budget_spent: Dict[str, float] = {}
        self.access_requests: Dict[str, AccessRequest] = {}
        self.approval_requests: Dict[str, ApprovalRequest] = {}
        self.audit_events: Dict[str, List[AuditEvent]] = {}
        self._principal_secrets: Dict[str, bytes] = {}

    def create_wallet(
        self,
        owner_did: str,
        device_did: Optional[str] = None,
        *,
        controller_dids: Optional[List[str]] = None,
        governance_policy: Optional[Dict[str, Any]] = None,
    ) -> Wallet:
        device = device_did or owner_did
        controllers = list(controller_dids or [owner_did])
        if owner_did not in controllers:
            controllers = [owner_did, *controllers]
        wallet = Wallet(
            wallet_id=f"wallet-{uuid.uuid4().hex}",
            owner_did=owner_did,
            controller_dids=controllers,
            device_dids=[device],
            default_privacy_policy={
                "location_default": "coarse",
                "analytics_min_cohort_size": 10,
                "analytics_epsilon_budget": 1.0,
            },
            governance_policy=normalize_governance_policy(
                controller_dids=controllers,
                governance_policy=governance_policy,
            ),
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

    def request_approval(
        self,
        wallet_id: str,
        *,
        requested_by: str,
        operation: str,
        resources: List[str],
        abilities: List[str],
        details: Optional[Dict[str, Any]] = None,
        expires_at: Optional[str] = None,
    ) -> ApprovalRequest:
        wallet = self._wallet(wallet_id)
        self._assert_controller(wallet, requested_by)
        request = create_approval_request(
            wallet,
            requested_by=requested_by,
            operation=operation,
            resources=resources,
            abilities=abilities,
            details=details,
            expires_at=expires_at,
        )
        self.approval_requests[request.approval_id] = request
        append_audit_event(
            self.audit_events[wallet_id],
            wallet_id=wallet_id,
            actor_did=requested_by,
            action="approval/request",
            resource=",".join(resources),
            decision="allow",
            details={
                "approval_id": request.approval_id,
                "operation": operation,
                "abilities": abilities,
                "threshold": request.threshold,
            },
        )
        return request

    def approve_approval(
        self,
        wallet_id: str,
        *,
        approval_id: str,
        approver_did: str,
    ) -> ApprovalRequest:
        wallet = self._wallet(wallet_id)
        request = self.approval_requests[approval_id]
        if request.wallet_id != wallet_id:
            raise MissingRecordError(f"Approval request not found for wallet: {approval_id}")
        approve_request(request, approver_did=approver_did)
        append_audit_event(
            self.audit_events[wallet_id],
            wallet_id=wallet_id,
            actor_did=approver_did,
            action="approval/approve",
            resource=",".join(request.resources),
            decision="allow",
            details={
                "approval_id": request.approval_id,
                "approved_count": request.approved_count,
                "threshold": request.threshold,
                "status": request.status,
            },
        )
        return request

    def request_access(
        self,
        wallet_id: str,
        *,
        requester_did: str,
        resources: List[str],
        abilities: List[str],
        purpose: str,
        audience_did: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        expires_at: Optional[str] = None,
    ) -> AccessRequest:
        wallet = self._wallet(wallet_id)
        if not resources or not abilities:
            raise GrantError("Access request requires at least one resource and ability")
        request = AccessRequest(
            request_id=f"access-{uuid.uuid4().hex}",
            wallet_id=wallet_id,
            requester_did=requester_did,
            audience_did=audience_did or requester_did,
            resources=list(resources),
            abilities=list(abilities),
            purpose=purpose,
            details=details or {},
            expires_at=expires_at,
        )
        self.access_requests[request.request_id] = request
        wallet.updated_at = utc_now()
        wallet.manifest_head = sha256_hex(canonical_bytes(self.get_wallet_manifest(wallet_id)))
        append_audit_event(
            self.audit_events[wallet_id],
            wallet_id=wallet_id,
            actor_did=requester_did,
            action="access/request",
            resource=",".join(resources),
            decision="allow",
            details={
                "request_id": request.request_id,
                "abilities": abilities,
                "purpose": purpose,
                "audience_did": request.audience_did,
            },
        )
        return request

    def list_access_requests(
        self,
        wallet_id: str,
        *,
        status: Optional[str] = None,
        requester_did: Optional[str] = None,
        audience_did: Optional[str] = None,
    ) -> List[AccessRequest]:
        self._wallet(wallet_id)
        requests = [
            request
            for request in self.access_requests.values()
            if request.wallet_id == wallet_id
        ]
        if status is not None:
            requests = [request for request in requests if request.status == status]
        if requester_did is not None:
            requests = [request for request in requests if request.requester_did == requester_did]
        if audience_did is not None:
            requests = [request for request in requests if request.audience_did == audience_did]
        return sorted(requests, key=lambda item: item.created_at)

    def approve_access_request(
        self,
        wallet_id: str,
        *,
        request_id: str,
        actor_did: str,
        issuer_secret: Optional[bytes] = None,
        audience_secret: Optional[bytes] = None,
        approval_id: Optional[str] = None,
        issue_invocation: bool = False,
        invocation_expires_at: Optional[str] = None,
    ) -> AccessRequest:
        wallet = self._wallet(wallet_id)
        self._assert_controller(wallet, actor_did)
        request = self._access_request(wallet_id, request_id)
        if request.status != "pending":
            raise GrantError(f"Access request is not pending: {request_id}")
        caveats = {
            "purpose": request.purpose,
            "access_request_id": request.request_id,
            **dict(request.details),
        }
        grant = self.create_grant(
            wallet_id=wallet_id,
            issuer_did=actor_did,
            audience_did=request.audience_did,
            resources=request.resources,
            abilities=request.abilities,
            caveats=caveats,
            expires_at=request.expires_at,
            approval_id=approval_id,
            issuer_secret=issuer_secret,
            audience_secret=audience_secret,
        )
        invocation = None
        if issue_invocation:
            if len(request.resources) != 1 or len(request.abilities) != 1:
                raise GrantError("Invocation issuance requires one resource and one ability")
            invocation = self.issue_invocation(
                wallet_id,
                grant_id=grant.grant_id,
                actor_did=request.audience_did,
                resource=request.resources[0],
                ability=request.abilities[0],
                actor_secret=audience_secret,
                caveats={"purpose": request.purpose, "access_request_id": request.request_id},
                expires_at=invocation_expires_at,
            )
        request.status = "approved"
        request.decided_at = utc_now()
        request.decided_by = actor_did
        request.grant_id = grant.grant_id
        request.invocation_id = invocation.invocation_id if invocation else None
        wallet.updated_at = utc_now()
        wallet.manifest_head = sha256_hex(canonical_bytes(self.get_wallet_manifest(wallet_id)))
        append_audit_event(
            self.audit_events[wallet_id],
            wallet_id=wallet_id,
            actor_did=actor_did,
            action="access/approve",
            resource=",".join(request.resources),
            decision="allow",
            details={
                "request_id": request.request_id,
                "grant_id": request.grant_id,
                "invocation_id": request.invocation_id,
            },
            grant_id=grant.grant_id,
        )
        return request

    def reject_access_request(
        self,
        wallet_id: str,
        *,
        request_id: str,
        actor_did: str,
        reason: Optional[str] = None,
    ) -> AccessRequest:
        wallet = self._wallet(wallet_id)
        self._assert_controller(wallet, actor_did)
        request = self._access_request(wallet_id, request_id)
        if request.status != "pending":
            raise GrantError(f"Access request is not pending: {request_id}")
        request.status = "rejected"
        request.decided_at = utc_now()
        request.decided_by = actor_did
        if reason:
            request.details = {**request.details, "rejection_reason": reason}
        wallet.updated_at = utc_now()
        wallet.manifest_head = sha256_hex(canonical_bytes(self.get_wallet_manifest(wallet_id)))
        append_audit_event(
            self.audit_events[wallet_id],
            wallet_id=wallet_id,
            actor_did=actor_did,
            action="access/reject",
            resource=",".join(request.resources),
            decision="deny",
            details={"request_id": request.request_id, "reason": reason},
        )
        return request

    def add_document(
        self,
        wallet_id: str,
        path: str | Path,
        *,
        actor_did: Optional[str] = None,
        actor_secret: Optional[bytes] = None,
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
            actor_secret=actor_secret,
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
        actor_secret: Optional[bytes] = None,
        private_metadata: Optional[Dict[str, Any]] = None,
        sensitivity: str = "restricted",
        public_descriptor: str = "record",
    ) -> DataRecord:
        wallet = self._wallet(wallet_id)
        actor = actor_did or wallet.owner_did
        self._assert_controller(wallet, actor)
        if actor_secret is not None:
            self.set_principal_secret(actor, actor_secret)

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
        approval_id: Optional[str] = None,
        issuer_secret: Optional[bytes] = None,
        audience_secret: Optional[bytes] = None,
    ) -> Grant:
        wallet = self._wallet(wallet_id)
        self._assert_controller(wallet, issuer_did)
        if issuer_secret is not None:
            self.set_principal_secret(issuer_did, issuer_secret)
        if audience_secret is not None:
            self.set_principal_secret(audience_did, audience_secret)
        if not resources or not abilities:
            raise GrantError("Grant requires at least one resource and ability")
        if approval_id is None:
            approval_id = (caveats or {}).get("approval_id") or (caveats or {}).get("approval_ref")
        if operation_requires_approval(
            wallet,
            operation="grant/create",
            abilities=abilities,
            resources=resources,
            caveats=caveats,
        ):
            verify_approval(
                self.approval_requests,
                approval_id=approval_id,
                operation="grant/create",
                requested_by=issuer_did,
                resources=resources,
                abilities=abilities,
            )
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
        if any(ability in abilities for ability in ("record/decrypt", "record/analyze", "*")):
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

    def issue_invocation(
        self,
        wallet_id: str,
        *,
        grant_id: str,
        actor_did: str,
        resource: str,
        ability: str,
        actor_secret: Optional[bytes] = None,
        caveats: Optional[Dict[str, Any]] = None,
        expires_at: Optional[str] = None,
    ) -> WalletInvocation:
        self._wallet(wallet_id)
        if actor_secret is not None:
            self.set_principal_secret(actor_did, actor_secret)
        grant = self.grants[grant_id]
        invocation = create_invocation(
            grant=grant,
            audience_did=actor_did,
            resource=resource,
            ability=ability,
            signing_secret=self._ensure_principal_secret(actor_did),
            caveats=caveats,
            expires_at=expires_at,
        )
        self.invocations[invocation.invocation_id] = invocation
        append_audit_event(
            self.audit_events[wallet_id],
            wallet_id=wallet_id,
            actor_did=actor_did,
            action="invocation/issue",
            resource=resource,
            decision="allow",
            details={"ability": ability, "invocation_id": invocation.invocation_id},
            grant_id=grant_id,
        )
        return invocation

    def verify_invocation(
        self,
        wallet_id: str,
        invocation: WalletInvocation,
        *,
        actor_did: str,
        resource: str,
        ability: str,
        actor_secret: Optional[bytes] = None,
    ) -> WalletInvocation:
        self._wallet(wallet_id)
        if actor_secret is not None:
            self.set_principal_secret(actor_did, actor_secret)
        grant = self.grants[invocation.grant_id]
        assert_invocation_allows(
            invocation,
            grant,
            audience_did=actor_did,
            resource=resource,
            ability=ability,
            signing_secret=self._ensure_principal_secret(actor_did),
        )
        self.invocations[invocation.invocation_id] = invocation
        append_audit_event(
            self.audit_events[wallet_id],
            wallet_id=wallet_id,
            actor_did=actor_did,
            action="invocation/verify",
            resource=resource,
            decision="allow",
            details={"ability": ability, "invocation_id": invocation.invocation_id},
            grant_id=invocation.grant_id,
        )
        return invocation

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
        actor_secret: Optional[bytes] = None,
    ) -> bytes:
        record = self._record(wallet_id, record_id)
        if actor_secret is not None:
            self.set_principal_secret(actor_did, actor_secret)
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

    def decrypt_record_with_invocation(
        self,
        wallet_id: str,
        record_id: str,
        *,
        actor_did: str,
        invocation: WalletInvocation,
        actor_secret: Optional[bytes] = None,
    ) -> bytes:
        resource = resource_for_record(wallet_id, record_id)
        self.verify_invocation(
            wallet_id,
            invocation,
            actor_did=actor_did,
            resource=resource,
            ability="record/decrypt",
            actor_secret=actor_secret,
        )
        return self.decrypt_record(
            wallet_id,
            record_id,
            actor_did=actor_did,
            grant_id=invocation.grant_id,
            actor_secret=actor_secret,
        )

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

    def create_coarse_location_claim_with_invocation(
        self,
        wallet_id: str,
        record_id: str,
        *,
        actor_did: str,
        invocation: WalletInvocation,
        actor_secret: Optional[bytes] = None,
        precision: int = 2,
    ) -> LocationClaim:
        self.verify_invocation(
            wallet_id,
            invocation,
            actor_did=actor_did,
            resource=resource_for_location(wallet_id, record_id),
            ability="location/read_coarse",
            actor_secret=actor_secret,
        )
        return self.create_coarse_location_claim(
            wallet_id,
            record_id,
            actor_did=actor_did,
            grant_id=invocation.grant_id,
            precision=precision,
        )

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
        actor_secret: Optional[bytes] = None,
        max_chars: int = 200,
    ) -> DerivedArtifact:
        if actor_secret is not None:
            self.set_principal_secret(actor_did, actor_secret)
        if actor_did != self._wallet(wallet_id).owner_did:
            if grant_id is None:
                raise AccessDeniedError("Analysis requires a grant")
            assert_grant_allows(
                self.grants[grant_id],
                audience_did=actor_did,
                resource=resource_for_record(wallet_id, record_id),
                ability="record/analyze",
            )
        record = self._record(wallet_id, record_id)
        if actor_did == self._wallet(wallet_id).owner_did:
            plaintext = self.decrypt_record(wallet_id, record_id, actor_did=actor_did, actor_secret=actor_secret)
        else:
            version = self.versions[record.current_version_id]
            dek = self._unwrap_dek(version, wallet_id, actor_did)
            payload_data = json.loads(self.storage.get(version.encrypted_payload_ref).decode("utf-8"))
            plaintext = decrypt_bytes(
                EncryptedBlob.from_dict(payload_data),
                dek,
                self._payload_aad(wallet_id, record_id, version.version_id, record.data_type),
            )
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

    def analyze_record_summary_with_invocation(
        self,
        wallet_id: str,
        record_id: str,
        *,
        actor_did: str,
        invocation: WalletInvocation,
        actor_secret: Optional[bytes] = None,
        max_chars: int = 200,
    ) -> DerivedArtifact:
        self.verify_invocation(
            wallet_id,
            invocation,
            actor_did=actor_did,
            resource=resource_for_record(wallet_id, record_id),
            ability="record/analyze",
            actor_secret=actor_secret,
        )
        return self.analyze_record_summary(
            wallet_id,
            record_id,
            actor_did=actor_did,
            grant_id=invocation.grant_id,
            actor_secret=actor_secret,
            max_chars=max_chars,
        )

    def create_analytics_consent(
        self,
        wallet_id: str,
        *,
        actor_did: str,
        template_id: str,
        allowed_record_types: List[str],
        allowed_derived_fields: List[str],
        aggregation_policy: Optional[Dict[str, Any]] = None,
        expires_at: Optional[str] = None,
    ) -> AnalyticsConsent:
        wallet = self._wallet(wallet_id)
        self._assert_controller(wallet, actor_did)
        template = self.analytics_templates.get(template_id)
        if template is not None:
            self._assert_active_analytics_template(template)
            template_record_types = set(template.allowed_record_types)
            template_fields = set(template.allowed_derived_fields)
            if not set(allowed_record_types).issubset(template_record_types):
                raise AccessDeniedError("Analytics consent record types exceed template policy")
            if not set(allowed_derived_fields).issubset(template_fields):
                raise AccessDeniedError("Analytics consent fields exceed template policy")
            policy = dict(template.aggregation_policy)
            if aggregation_policy:
                requested_min = int(aggregation_policy.get("min_cohort_size", policy.get("min_cohort_size", 10)))
                template_min = int(policy.get("min_cohort_size", 10))
                if requested_min < template_min:
                    raise AccessDeniedError("Analytics consent cannot lower template min_cohort_size")
                requested_budget = float(aggregation_policy.get("epsilon_budget", policy.get("epsilon_budget", 1.0)))
                template_budget = float(policy.get("epsilon_budget", 1.0))
                if requested_budget > template_budget:
                    raise AccessDeniedError("Analytics consent cannot exceed template epsilon_budget")
                policy.update(aggregation_policy)
        else:
            policy = aggregation_policy or {
                "min_cohort_size": wallet.default_privacy_policy.get("analytics_min_cohort_size", 10),
                "epsilon_budget": wallet.default_privacy_policy.get("analytics_epsilon_budget", 1.0),
                "duplicate_policy": "reject_by_nullifier",
            }
        consent = AnalyticsConsent(
            consent_id=f"consent-{uuid.uuid4().hex}",
            wallet_id=wallet_id,
            template_id=template_id,
            allowed_record_types=list(allowed_record_types),
            allowed_derived_fields=list(allowed_derived_fields),
            aggregation_policy=policy,
            expires_at=expires_at,
        )
        self.analytics_consents[consent.consent_id] = consent
        append_audit_event(
            self.audit_events[wallet_id],
            wallet_id=wallet_id,
            actor_did=actor_did,
            action="analytics/consent_create",
            resource=f"wallet://{wallet_id}/analytics/{consent.consent_id}",
            decision="allow",
            details={
                "template_id": template_id,
                "allowed_record_types": allowed_record_types,
                "allowed_derived_fields": allowed_derived_fields,
            },
        )
        return consent

    def create_analytics_template(
        self,
        *,
        template_id: str,
        title: str,
        purpose: str,
        allowed_record_types: List[str],
        allowed_derived_fields: List[str],
        aggregation_policy: Dict[str, Any],
        created_by: str,
        expires_at: Optional[str] = None,
    ) -> AnalyticsTemplate:
        if template_id in self.analytics_templates:
            raise ValueError(f"Analytics template already exists: {template_id}")
        self._validate_analytics_template_policy(aggregation_policy)
        template = AnalyticsTemplate(
            template_id=template_id,
            title=title,
            purpose=purpose,
            allowed_record_types=list(allowed_record_types),
            allowed_derived_fields=list(allowed_derived_fields),
            aggregation_policy=dict(aggregation_policy),
            created_by=created_by,
            expires_at=expires_at,
        )
        self.analytics_templates[template_id] = template
        return template

    def list_analytics_templates(self, *, include_inactive: bool = False) -> List[AnalyticsTemplate]:
        templates = sorted(self.analytics_templates.values(), key=lambda item: item.template_id)
        if include_inactive:
            return templates
        return [template for template in templates if template.status == "active"]

    def retire_analytics_template(self, template_id: str, *, actor_did: str) -> AnalyticsTemplate:
        template = self._analytics_template(template_id)
        if actor_did != template.created_by:
            raise AccessDeniedError("Only the template creator can retire this analytics template")
        template.status = "retired"
        template.updated_at = utc_now()
        return template

    def revoke_analytics_consent(self, wallet_id: str, consent_id: str, *, actor_did: str) -> AnalyticsConsent:
        wallet = self._wallet(wallet_id)
        self._assert_controller(wallet, actor_did)
        consent = self._analytics_consent(wallet_id, consent_id)
        consent.status = "revoked"
        consent.revoked_at = utc_now()
        append_audit_event(
            self.audit_events[wallet_id],
            wallet_id=wallet_id,
            actor_did=actor_did,
            action="analytics/consent_revoke",
            resource=f"wallet://{wallet_id}/analytics/{consent_id}",
            decision="allow",
            details={"template_id": consent.template_id},
        )
        return consent

    def create_analytics_contribution(
        self,
        wallet_id: str,
        *,
        actor_did: str,
        consent_id: str,
        template_id: str,
        fields: Dict[str, Any],
    ) -> AnalyticsContribution:
        wallet = self._wallet(wallet_id)
        self._assert_controller(wallet, actor_did)
        consent = self._analytics_consent(wallet_id, consent_id)
        template = self.analytics_templates.get(template_id)
        if template is not None:
            self._assert_active_analytics_template(template)
        if consent.status != "active":
            raise AccessDeniedError(f"Analytics consent {consent_id} is not active")
        if consent.expires_at is not None:
            from .ucan import is_expired

            if is_expired(consent.expires_at):
                raise AccessDeniedError(f"Analytics consent {consent_id} has expired")
        if consent.template_id != template_id:
            raise AccessDeniedError("Analytics template does not match consent")
        if template is not None:
            template_fields = set(template.allowed_derived_fields)
            if not set(fields).issubset(template_fields):
                raise AccessDeniedError("Analytics fields exceed template policy")

        requested_fields = set(fields)
        allowed_fields = set(consent.allowed_derived_fields)
        disallowed = requested_fields - allowed_fields
        if disallowed:
            raise AccessDeniedError(f"Analytics fields are not consented: {sorted(disallowed)}")

        nullifier = contribution_nullifier(wallet_id, template_id, consent_id)
        if any(item.nullifier == nullifier for item in self.analytics_contributions.values()):
            raise AccessDeniedError("Duplicate analytics contribution rejected by nullifier")

        proof = create_simulated_proof_receipt(
            wallet_id=wallet_id,
            proof_type="analytics_contribution",
            statement={
                "template_id": template_id,
                "field_names": sorted(fields),
                "consent_id": consent_id,
                "nullifier": nullifier,
            },
            public_inputs={
                "template_id": template_id,
                "field_names": sorted(fields),
                "nullifier": nullifier,
            },
            witness_record_ids=[],
        )
        self.proofs[proof.proof_id] = proof
        contribution = make_contribution(
            template_id=template_id,
            consent_id=consent_id,
            nullifier=nullifier,
            fields=fields,
            proof_id=proof.proof_id,
        )
        self.analytics_contributions[contribution.contribution_id] = contribution
        append_audit_event(
            self.audit_events[wallet_id],
            wallet_id=wallet_id,
            actor_did=actor_did,
            action="analytics/contribute",
            resource=f"wallet://{wallet_id}/analytics/{consent_id}",
            decision="allow",
            details={
                "template_id": template_id,
                "field_names": sorted(fields),
                "proof_id": proof.proof_id,
            },
        )
        return contribution

    def verify_analytics_contribution(self, contribution_id: str) -> bool:
        contribution = self.analytics_contributions[contribution_id]
        proof = self.proofs[contribution.proof_id]
        return (
            proof.proof_type == "analytics_contribution"
            and proof.public_inputs.get("template_id") == contribution.template_id
            and proof.public_inputs.get("nullifier") == contribution.nullifier
            and sorted(contribution.fields) == proof.public_inputs.get("field_names")
        )

    def run_aggregate_count(
        self,
        template_id: str,
        *,
        min_cohort_size: Optional[int] = None,
        epsilon: Optional[float] = None,
        sensitivity: float = 1.0,
        budget_key: Optional[str] = None,
        budget_limit: Optional[float] = None,
        release_exact_count: Optional[bool] = None,
        actor_did: str = "did:service:analytics",
    ) -> AggregateResult:
        if min_cohort_size is None:
            matching_consents = [
                consent for consent in self.analytics_consents.values() if consent.template_id == template_id
            ]
            policy_sizes = [
                int(consent.aggregation_policy.get("min_cohort_size", 10))
                for consent in matching_consents
            ]
            min_cohort_size = max(policy_sizes) if policy_sizes else 10
            template = self.analytics_templates.get(template_id)
            if template is not None:
                self._assert_active_analytics_template(template)
                min_cohort_size = max(
                    min_cohort_size,
                    int(template.aggregation_policy.get("min_cohort_size", 10)),
                )
        spent = None
        if epsilon is not None:
            if epsilon <= 0:
                raise ValueError("epsilon must be greater than zero")
            budget_key = budget_key or f"template:{template_id}"
            if budget_limit is None:
                budget_limit = self._analytics_budget_limit(template_id)
            spent = self._spend_analytics_privacy_budget(
                budget_key=budget_key,
                epsilon=epsilon,
                budget_limit=budget_limit,
            )
        if release_exact_count is None:
            release_exact_count = epsilon is None
        result = aggregate_count(
            template_id=template_id,
            contributions=self.analytics_contributions.values(),
            min_cohort_size=min_cohort_size,
            epsilon=epsilon,
            sensitivity=sensitivity,
            privacy_budget_key=budget_key if epsilon is not None else None,
            privacy_budget_spent=spent,
            release_exact_count=release_exact_count,
        )
        self.aggregate_results[result.result_id] = result
        self._audit_aggregate_query(template_id, result, actor_did=actor_did)
        return result

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
            "grants": [
                grant.to_dict()
                for grant in sorted(self.grants.values(), key=lambda item: item.grant_id)
                if any(resource.startswith(f"wallet://{wallet_id}/") for resource in grant.resources)
            ],
            "invocations": [
                invocation.to_dict()
                for invocation in sorted(self.invocations.values(), key=lambda item: item.invocation_id)
                if invocation.resource.startswith(f"wallet://{wallet_id}/")
            ],
            "approvals": [
                approval.to_dict()
                for approval in sorted(self.approval_requests.values(), key=lambda item: item.approval_id)
                if approval.wallet_id == wallet_id
            ],
            "access_requests": [
                request.to_dict()
                for request in sorted(self.access_requests.values(), key=lambda item: item.request_id)
                if request.wallet_id == wallet_id
            ],
        }

    def export_wallet_snapshot(self, wallet_id: str) -> Dict[str, Any]:
        """Export restorable wallet service state for local repository use."""

        wallet = self._wallet(wallet_id)
        record_ids = sorted(
            record.record_id for record in self.records.values() if record.wallet_id == wallet_id
        )
        version_ids = sorted(self.records[record_id].current_version_id for record_id in record_ids)
        grant_ids = sorted(
            grant.grant_id
            for grant in self.grants.values()
            if any(resource.startswith(f"wallet://{wallet_id}/") for resource in grant.resources)
        )
        invocation_ids = sorted(
            invocation.invocation_id
            for invocation in self.invocations.values()
            if invocation.resource.startswith(f"wallet://{wallet_id}/")
        )
        artifact_ids = sorted(
            artifact.artifact_id
            for artifact in self.derived_artifacts.values()
            if artifact.wallet_id == wallet_id
        )
        proof_ids = sorted(
            proof.proof_id for proof in self.proofs.values() if proof.wallet_id == wallet_id
        )
        consent_ids = sorted(
            consent.consent_id
            for consent in self.analytics_consents.values()
            if consent.wallet_id == wallet_id
        )
        approval_ids = sorted(
            approval.approval_id
            for approval in self.approval_requests.values()
            if approval.wallet_id == wallet_id
        )
        access_request_ids = sorted(
            request.request_id
            for request in self.access_requests.values()
            if request.wallet_id == wallet_id
        )
        return {
            "wallet": wallet.to_dict(),
            "records": [self.records[record_id].to_dict() for record_id in record_ids],
            "versions": [self.versions[version_id].to_dict() for version_id in version_ids],
            "grants": [self.grants[grant_id].to_dict() for grant_id in grant_ids],
            "invocations": [
                self.invocations[invocation_id].to_dict() for invocation_id in invocation_ids
            ],
            "derived_artifacts": [
                self.derived_artifacts[artifact_id].to_dict() for artifact_id in artifact_ids
            ],
            "proofs": [self.proofs[proof_id].to_dict() for proof_id in proof_ids],
            "analytics_consents": [
                self.analytics_consents[consent_id].to_dict() for consent_id in consent_ids
            ],
            "analytics_templates": [
                template.to_dict()
                for template in sorted(self.analytics_templates.values(), key=lambda item: item.template_id)
            ],
            "analytics_contributions": [
                contribution.to_dict()
                for contribution in sorted(
                    self.analytics_contributions.values(),
                    key=lambda item: item.contribution_id,
                )
            ],
            "aggregate_results": [
                result.to_dict()
                for result in sorted(self.aggregate_results.values(), key=lambda item: item.result_id)
            ],
            "analytics_query_budget_spent": dict(sorted(self.analytics_query_budget_spent.items())),
            "approvals": [self.approval_requests[approval_id].to_dict() for approval_id in approval_ids],
            "access_requests": [
                self.access_requests[request_id].to_dict() for request_id in access_request_ids
            ],
            "audit_events": [
                event.to_dict() for event in self.audit_events.get(wallet_id, [])
            ],
            "principal_secret_dids": sorted(
                did
                for did in self._principal_secrets
                if did in set(wallet.controller_dids + wallet.device_dids)
                or any(self.grants[grant_id].audience_did == did for grant_id in grant_ids)
            ),
        }

    def import_wallet_snapshot(self, snapshot: Dict[str, Any]) -> Wallet:
        """Import a snapshot produced by :meth:`export_wallet_snapshot`."""

        wallet_data = snapshot["wallet"]
        wallet = Wallet(**wallet_data)
        self.wallets[wallet.wallet_id] = wallet
        self.audit_events[wallet.wallet_id] = [
            AuditEvent(**event_data) for event_data in snapshot.get("audit_events", [])
        ]
        for did in snapshot.get("principal_secret_dids", []):
            self._ensure_principal_secret(str(did))
        for record_data in snapshot.get("records", []):
            self.records[record_data["record_id"]] = DataRecord(**record_data)
        for version_data in snapshot.get("versions", []):
            payload_ref = version_data["encrypted_payload_ref"]
            metadata_ref = version_data.get("encrypted_metadata_ref")
            key_wraps = [KeyWrap(**wrap) for wrap in version_data.get("key_wraps", [])]
            self.versions[version_data["version_id"]] = DataVersion(
                version_id=version_data["version_id"],
                record_id=version_data["record_id"],
                encrypted_payload_ref=self._storage_ref_from_dict(payload_ref),
                encrypted_metadata_ref=(
                    self._storage_ref_from_dict(metadata_ref) if metadata_ref else None
                ),
                ciphertext_hash=version_data["ciphertext_hash"],
                encryption_suite=version_data["encryption_suite"],
                key_wraps=key_wraps,
                derived_artifact_ids=list(version_data.get("derived_artifact_ids", [])),
                proof_receipt_ids=list(version_data.get("proof_receipt_ids", [])),
                created_at=version_data.get("created_at", utc_now()),
            )
        for grant_data in snapshot.get("grants", []):
            self.grants[grant_data["grant_id"]] = Grant(**grant_data)
        for invocation_data in snapshot.get("invocations", []):
            self.invocations[invocation_data["invocation_id"]] = WalletInvocation(**invocation_data)
        for artifact_data in snapshot.get("derived_artifacts", []):
            ref = self._storage_ref_from_dict(artifact_data["encrypted_payload_ref"])
            self.derived_artifacts[artifact_data["artifact_id"]] = DerivedArtifact(
                artifact_id=artifact_data["artifact_id"],
                wallet_id=artifact_data["wallet_id"],
                source_record_ids=list(artifact_data.get("source_record_ids", [])),
                artifact_type=artifact_data["artifact_type"],
                output_policy=artifact_data["output_policy"],
                encrypted_payload_ref=ref,
                created_at=artifact_data.get("created_at", utc_now()),
            )
        for proof_data in snapshot.get("proofs", []):
            self.proofs[proof_data["proof_id"]] = ProofReceipt(**proof_data)
        for consent_data in snapshot.get("analytics_consents", []):
            self.analytics_consents[consent_data["consent_id"]] = AnalyticsConsent(**consent_data)
        for template_data in snapshot.get("analytics_templates", []):
            self.analytics_templates[template_data["template_id"]] = AnalyticsTemplate(**template_data)
        for contribution_data in snapshot.get("analytics_contributions", []):
            self.analytics_contributions[contribution_data["contribution_id"]] = AnalyticsContribution(
                **contribution_data
            )
        for result_data in snapshot.get("aggregate_results", []):
            self.aggregate_results[result_data["result_id"]] = AggregateResult(**result_data)
        self.analytics_query_budget_spent.update(
            {str(key): float(value) for key, value in snapshot.get("analytics_query_budget_spent", {}).items()}
        )
        for approval_data in snapshot.get("approvals", []):
            self.approval_requests[approval_data["approval_id"]] = ApprovalRequest(**approval_data)
        for request_data in snapshot.get("access_requests", []):
            self.access_requests[request_data["request_id"]] = AccessRequest(**request_data)
        return wallet

    def get_wallet_manifest_canonical(self, wallet_id: str) -> str:
        return canonical_dumps(self.get_wallet_manifest(wallet_id))

    def get_audit_log(self, wallet_id: str) -> List[AuditEvent]:
        self._wallet(wallet_id)
        return list(self.audit_events[wallet_id])

    def verify_record_storage(
        self,
        wallet_id: str,
        record_id: str,
        *,
        include_metadata: bool = True,
    ) -> StorageHealthReport:
        """Verify encrypted payload and metadata replicas without decrypting."""

        record = self._record(wallet_id, record_id)
        version = self.versions[record.current_version_id]
        report = StorageHealthReport(
            wallet_id=wallet_id,
            record_id=record_id,
            version_id=version.version_id,
            payload=self._check_storage_ref(version.encrypted_payload_ref),
            metadata=(
                self._check_storage_ref(version.encrypted_metadata_ref)
                if include_metadata and version.encrypted_metadata_ref is not None
                else []
            ),
        )
        append_audit_event(
            self.audit_events[wallet_id],
            wallet_id=wallet_id,
            actor_did=self._wallet(wallet_id).owner_did,
            action="storage/verify",
            resource=resource_for_record(wallet_id, record_id),
            decision="allow",
            details={
                "version_id": version.version_id,
                "ok": report.ok,
                "payload_replicas": len(report.payload),
                "metadata_replicas": len(report.metadata),
            },
        )
        return report

    def repair_record_storage(
        self,
        wallet_id: str,
        record_id: str,
        *,
        actor_did: str,
        include_metadata: bool = True,
    ) -> StorageHealthReport:
        """Repair encrypted payload and metadata mirrors from a valid replica."""

        wallet = self._wallet(wallet_id)
        self._assert_controller(wallet, actor_did)
        record = self._record(wallet_id, record_id)
        version = self.versions[record.current_version_id]
        report = StorageHealthReport(
            wallet_id=wallet_id,
            record_id=record_id,
            version_id=version.version_id,
            payload=self._repair_storage_ref(version.encrypted_payload_ref),
            metadata=(
                self._repair_storage_ref(version.encrypted_metadata_ref)
                if include_metadata and version.encrypted_metadata_ref is not None
                else []
            ),
        )
        report.repaired = any(status.repaired for status in [*report.payload, *report.metadata])
        wallet.updated_at = utc_now()
        wallet.manifest_head = sha256_hex(canonical_bytes(self.get_wallet_manifest(wallet_id)))
        append_audit_event(
            self.audit_events[wallet_id],
            wallet_id=wallet_id,
            actor_did=actor_did,
            action="storage/repair",
            resource=resource_for_record(wallet_id, record_id),
            decision="allow",
            details={
                "version_id": version.version_id,
                "ok": report.ok,
                "payload_repaired": any(status.repaired for status in report.payload),
                "metadata_repaired": any(status.repaired for status in report.metadata),
            },
        )
        return report

    def _wallet(self, wallet_id: str) -> Wallet:
        if wallet_id not in self.wallets:
            raise MissingRecordError(f"Wallet not found: {wallet_id}")
        return self.wallets[wallet_id]

    def _record(self, wallet_id: str, record_id: str) -> DataRecord:
        if record_id not in self.records or self.records[record_id].wallet_id != wallet_id:
            raise MissingRecordError(f"Record not found: {record_id}")
        return self.records[record_id]

    def _access_request(self, wallet_id: str, request_id: str) -> AccessRequest:
        if request_id not in self.access_requests or self.access_requests[request_id].wallet_id != wallet_id:
            raise MissingRecordError(f"Access request not found: {request_id}")
        return self.access_requests[request_id]

    def _analytics_consent(self, wallet_id: str, consent_id: str) -> AnalyticsConsent:
        if consent_id not in self.analytics_consents or self.analytics_consents[consent_id].wallet_id != wallet_id:
            raise MissingRecordError(f"Analytics consent not found: {consent_id}")
        return self.analytics_consents[consent_id]

    def _analytics_template(self, template_id: str) -> AnalyticsTemplate:
        if template_id not in self.analytics_templates:
            raise MissingRecordError(f"Analytics template not found: {template_id}")
        return self.analytics_templates[template_id]

    def _assert_active_analytics_template(self, template: AnalyticsTemplate) -> None:
        if template.status != "active":
            raise AccessDeniedError(f"Analytics template {template.template_id} is not active")
        if template.expires_at is not None:
            from .ucan import is_expired

            if is_expired(template.expires_at):
                raise AccessDeniedError(f"Analytics template {template.template_id} has expired")

    def _validate_analytics_template_policy(self, policy: Dict[str, Any]) -> None:
        if int(policy.get("min_cohort_size", 0)) <= 0:
            raise ValueError("analytics template min_cohort_size must be greater than zero")
        if float(policy.get("epsilon_budget", 0)) <= 0:
            raise ValueError("analytics template epsilon_budget must be greater than zero")

    def _analytics_budget_limit(self, template_id: str) -> float:
        template = self.analytics_templates.get(template_id)
        if template is not None and "epsilon_budget" in template.aggregation_policy:
            template_limit = float(template.aggregation_policy["epsilon_budget"])
        else:
            template_limit = 1.0
        matching_consents = [
            consent for consent in self.analytics_consents.values() if consent.template_id == template_id
        ]
        limits = [
            float(consent.aggregation_policy["epsilon_budget"])
            for consent in matching_consents
            if "epsilon_budget" in consent.aggregation_policy
        ]
        limits.append(template_limit)
        return min(limits)

    def _spend_analytics_privacy_budget(
        self,
        *,
        budget_key: str,
        epsilon: float,
        budget_limit: float,
    ) -> float:
        if budget_limit <= 0:
            raise ValueError("budget_limit must be greater than zero")
        spent = self.analytics_query_budget_spent.get(budget_key, 0.0)
        next_spent = spent + epsilon
        if next_spent > budget_limit + 1e-12:
            raise AccessDeniedError(
                f"Analytics privacy budget exceeded for {budget_key}: "
                f"{next_spent:.6g} > {budget_limit:.6g}"
            )
        self.analytics_query_budget_spent[budget_key] = next_spent
        return next_spent

    def _audit_aggregate_query(
        self,
        template_id: str,
        result: AggregateResult,
        *,
        actor_did: str,
    ) -> None:
        wallet_ids = sorted(
            {
                consent.wallet_id
                for consent in self.analytics_consents.values()
                if consent.template_id == template_id
            }
        )
        for wallet_id in wallet_ids:
            append_audit_event(
                self.audit_events[wallet_id],
                wallet_id=wallet_id,
                actor_did=actor_did,
                action="analytics/query",
                resource=f"wallet://{wallet_id}/analytics/{template_id}/results/{result.result_id}",
                decision="allow" if result.released else "suppress",
                details={
                    "template_id": template_id,
                    "result_id": result.result_id,
                    "metric": result.metric,
                    "released": result.released,
                    "suppressed": result.suppressed,
                    "min_cohort_size": result.min_cohort_size,
                    "epsilon": result.epsilon,
                    "privacy_budget_key": result.privacy_budget_key,
                    "privacy_budget_spent": result.privacy_budget_spent,
                    "exact_count_released": result.exact_count_released,
                    "cohort_size_released": result.cohort_size_released,
                    "privacy_notes": list(result.privacy_notes),
                },
            )

    def _assert_controller(self, wallet: Wallet, actor_did: str) -> None:
        if actor_did not in wallet.controller_dids and actor_did != wallet.owner_did:
            raise AccessDeniedError(f"{actor_did} is not a wallet controller")

    def _ensure_principal_secret(self, did: str) -> bytes:
        if did not in self._principal_secrets:
            self._principal_secrets[did] = random_key()
        return self._principal_secrets[did]

    def set_principal_secret(self, did: str, secret: bytes) -> None:
        if len(secret) != 32:
            raise ValueError("principal secret must be 32 bytes")
        self._principal_secrets[did] = secret

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

    @staticmethod
    def _storage_ref_from_dict(data: Dict[str, Any]) -> StorageRef:
        payload = dict(data)
        payload["mirrors"] = [
            DataWalletService._storage_ref_from_dict(mirror)
            for mirror in payload.get("mirrors", [])
        ]
        return StorageRef(**payload)

    def _check_storage_ref(self, ref: StorageRef) -> List[StorageReplicaStatus]:
        if hasattr(self.storage, "check_ref"):
            return list(self.storage.check_ref(ref))  # type: ignore[attr-defined]
        try:
            data = self.storage.get(ref)
        except Exception as exc:
            return [
                StorageReplicaStatus(
                    uri=ref.uri,
                    storage_type=ref.storage_type,
                    role="primary",
                    ok=False,
                    size_bytes=ref.size_bytes,
                    sha256=ref.sha256,
                    error=str(exc),
                )
            ]
        return [
            StorageReplicaStatus(
                uri=ref.uri,
                storage_type=ref.storage_type,
                role="primary",
                ok=True,
                size_bytes=len(data),
                sha256=sha256_hex(data),
            )
        ]

    def _repair_storage_ref(self, ref: StorageRef) -> List[StorageReplicaStatus]:
        if hasattr(self.storage, "repair_ref"):
            return list(self.storage.repair_ref(ref))  # type: ignore[attr-defined]
        return self._check_storage_ref(ref)
