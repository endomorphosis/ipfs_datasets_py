"""High-level data wallet service API."""

from __future__ import annotations

import json
import re
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .analytics import aggregate_count, aggregate_count_by_fields, contribution_nullifier, make_contribution
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
from .exceptions import (
    AccessDeniedError,
    ApprovalRequiredError,
    DataWalletError,
    GrantError,
    MissingRecordError,
)
from .location import (
    distance_membership_statement,
    haversine_distance_km,
    make_coarse_location_claim,
    region_membership_statement,
    serialize_location,
)
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
    GrantReceipt,
    KeyWrap,
    LocationClaim,
    ProofReceipt,
    StorageHealthReport,
    StorageRef,
    StorageReplicaStatus,
    Wallet,
    WalletStorageHealthReport,
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
from .proofs import ProofBackend, SimulatedProofBackend, create_simulated_proof_receipt
from .storage import EncryptedBlobStore, LocalEncryptedBlobStore
from .ucan import (
    assert_grant_allows,
    assert_invocation_allows,
    create_invocation,
    is_expired,
    record_id_from_resource,
    resource_for_export,
    resource_for_location,
    resource_for_record,
    resource_for_wallet,
)


class DataWalletService:
    """In-process service for encrypted wallet records and delegated access."""

    RECOVERY_APPROVAL_OPERATIONS = {"wallet/controller_recover"}
    REDACTION_PATTERNS = {
        "email": re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE),
        "phone": re.compile(r"\b(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)\d{3}[-.\s]?\d{4}\b"),
        "ssn": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
        "address": re.compile(
            r"\b\d{1,6}\s+[A-Za-z0-9.'-]+(?:\s+[A-Za-z0-9.'-]+){0,5}\s+"
            r"(?:St|Street|Ave|Avenue|Rd|Road|Blvd|Boulevard|Dr|Drive|Ln|Lane|Way|Ct|Court)\b",
            re.IGNORECASE,
        ),
    }
    DERIVED_FACT_KEYWORDS = {
        "housing": ("rent", "eviction", "shelter", "housing", "homeless", "utility", "shutoff"),
        "food": ("snap", "food", "pantry", "meal", "groceries"),
        "health": ("medical", "doctor", "clinic", "medicaid", "medicare", "prescription"),
        "income": ("benefit", "unemployment", "income", "job", "wage", "ssi", "disability"),
    }

    def __init__(
        self,
        storage_dir: Optional[str | Path] = None,
        *,
        storage_backend: Optional[EncryptedBlobStore] = None,
        proof_backend: Optional[ProofBackend] = None,
        allow_simulated_proofs: bool = True,
    ) -> None:
        self.storage = storage_backend or LocalEncryptedBlobStore(storage_dir)
        self.proof_backend = proof_backend or SimulatedProofBackend()
        self.allow_simulated_proofs = allow_simulated_proofs
        self.wallets: Dict[str, Wallet] = {}
        self.records: Dict[str, DataRecord] = {}
        self.versions: Dict[str, DataVersion] = {}
        self.grants: Dict[str, Grant] = {}
        self.grant_receipts: Dict[str, GrantReceipt] = {}
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

    def get_wallet(self, wallet_id: str) -> Wallet:
        return self._wallet(wallet_id)

    def add_controller(
        self,
        wallet_id: str,
        *,
        actor_did: str,
        controller_did: str,
        controller_secret: Optional[bytes] = None,
        approval_id: Optional[str] = None,
    ) -> Wallet:
        wallet = self._wallet(wallet_id)
        self._assert_controller(wallet, actor_did)
        if controller_did in wallet.controller_dids:
            raise ValueError(f"Wallet controller already exists: {controller_did}")
        self._verify_wallet_admin_approval(
            wallet,
            actor_did=actor_did,
            operation="wallet/controller_add",
            approval_id=approval_id,
        )
        if controller_secret is not None:
            self.set_principal_secret(controller_did, controller_secret)
        else:
            self._ensure_principal_secret(controller_did)
        wallet.controller_dids.append(controller_did)
        self._sync_governance_policy_controllers(wallet)
        self._touch_wallet(wallet)
        append_audit_event(
            self.audit_events[wallet_id],
            wallet_id=wallet_id,
            actor_did=actor_did,
            action="wallet/controller_add",
            resource=resource_for_wallet(wallet_id),
            decision="allow",
            details={"controller_did": controller_did},
        )
        return wallet

    def remove_controller(
        self,
        wallet_id: str,
        *,
        actor_did: str,
        controller_did: str,
        approval_id: Optional[str] = None,
    ) -> Wallet:
        wallet = self._wallet(wallet_id)
        self._assert_controller(wallet, actor_did)
        if controller_did == wallet.owner_did:
            raise AccessDeniedError("Cannot remove the wallet owner as a controller")
        if controller_did not in wallet.controller_dids:
            raise MissingRecordError(f"Wallet controller not found: {controller_did}")
        if len(wallet.controller_dids) <= 1:
            raise AccessDeniedError("Wallet must retain at least one controller")
        self._verify_wallet_admin_approval(
            wallet,
            actor_did=actor_did,
            operation="wallet/controller_remove",
            approval_id=approval_id,
        )
        wallet.controller_dids = [did for did in wallet.controller_dids if did != controller_did]
        self._sync_governance_policy_controllers(wallet)
        self._touch_wallet(wallet)
        append_audit_event(
            self.audit_events[wallet_id],
            wallet_id=wallet_id,
            actor_did=actor_did,
            action="wallet/controller_remove",
            resource=resource_for_wallet(wallet_id),
            decision="allow",
            details={"controller_did": controller_did},
        )
        return wallet

    def add_device(
        self,
        wallet_id: str,
        *,
        actor_did: str,
        device_did: str,
        device_secret: Optional[bytes] = None,
        approval_id: Optional[str] = None,
    ) -> Wallet:
        wallet = self._wallet(wallet_id)
        self._assert_controller(wallet, actor_did)
        if device_did in wallet.device_dids:
            raise ValueError(f"Wallet device already exists: {device_did}")
        self._verify_wallet_admin_approval(
            wallet,
            actor_did=actor_did,
            operation="wallet/device_add",
            approval_id=approval_id,
        )
        if device_secret is not None:
            self.set_principal_secret(device_did, device_secret)
        else:
            self._ensure_principal_secret(device_did)
        wallet.device_dids.append(device_did)
        self._touch_wallet(wallet)
        append_audit_event(
            self.audit_events[wallet_id],
            wallet_id=wallet_id,
            actor_did=actor_did,
            action="wallet/device_add",
            resource=resource_for_wallet(wallet_id),
            decision="allow",
            details={"device_did": device_did},
        )
        return wallet

    def revoke_device(
        self,
        wallet_id: str,
        *,
        actor_did: str,
        device_did: str,
        approval_id: Optional[str] = None,
    ) -> Wallet:
        wallet = self._wallet(wallet_id)
        self._assert_controller(wallet, actor_did)
        if device_did not in wallet.device_dids:
            raise MissingRecordError(f"Wallet device not found: {device_did}")
        if len(wallet.device_dids) <= 1:
            raise AccessDeniedError("Wallet must retain at least one device")
        self._verify_wallet_admin_approval(
            wallet,
            actor_did=actor_did,
            operation="wallet/device_revoke",
            approval_id=approval_id,
        )
        wallet.device_dids = [did for did in wallet.device_dids if did != device_did]
        self._touch_wallet(wallet)
        append_audit_event(
            self.audit_events[wallet_id],
            wallet_id=wallet_id,
            actor_did=actor_did,
            action="wallet/device_revoke",
            resource=resource_for_wallet(wallet_id),
            decision="allow",
            details={"device_did": device_did},
        )
        return wallet

    def set_recovery_policy(
        self,
        wallet_id: str,
        *,
        actor_did: str,
        contact_dids: List[str],
        threshold: int = 1,
        approval_id: Optional[str] = None,
    ) -> Wallet:
        """Configure recovery contacts for threshold-authorized root changes."""

        wallet = self._wallet(wallet_id)
        self._assert_controller(wallet, actor_did)
        self._verify_wallet_admin_approval(
            wallet,
            actor_did=actor_did,
            operation="wallet/recovery_policy_set",
            approval_id=approval_id,
        )
        contacts = self._unique_dids(contact_dids, field_name="contact_dids")
        if contacts:
            normalized_threshold = int(threshold)
            if normalized_threshold < 1:
                raise ValueError("Recovery threshold must be at least 1 when contacts are configured")
            if normalized_threshold > len(contacts):
                raise ValueError("Recovery threshold cannot exceed recovery contact count")
            for contact_did in contacts:
                self._ensure_principal_secret(contact_did)
            status = "active"
        else:
            normalized_threshold = 0
            status = "disabled"

        policy = dict(wallet.governance_policy)
        sensitive_operations = set(policy.get("sensitive_operations") or [])
        sensitive_operations.update({"wallet/recovery_policy_set", *self.RECOVERY_APPROVAL_OPERATIONS})
        policy["sensitive_operations"] = sorted(sensitive_operations)
        policy["recovery_policy"] = {
            "contact_dids": contacts,
            "threshold": normalized_threshold,
            "status": status,
            "updated_at": utc_now(),
        }
        wallet.governance_policy = normalize_governance_policy(
            controller_dids=wallet.controller_dids,
            governance_policy=policy,
        )
        self._touch_wallet(wallet)
        append_audit_event(
            self.audit_events[wallet_id],
            wallet_id=wallet_id,
            actor_did=actor_did,
            action="wallet/recovery_policy_set",
            resource=resource_for_wallet(wallet_id),
            decision="allow",
            details={
                "contact_dids": contacts,
                "threshold": normalized_threshold,
                "status": status,
            },
        )
        return wallet

    def recover_controller(
        self,
        wallet_id: str,
        *,
        actor_did: str,
        controller_did: str,
        controller_secret: Optional[bytes] = None,
        approval_id: Optional[str] = None,
    ) -> Wallet:
        """Add a controller using the wallet recovery contact threshold."""

        wallet = self._wallet(wallet_id)
        recovery_policy = self._active_recovery_policy(wallet)
        contact_dids = list(recovery_policy["contact_dids"])
        if actor_did not in set(contact_dids):
            raise AccessDeniedError(f"{actor_did} is not a wallet recovery contact")
        if controller_did in wallet.controller_dids:
            raise ValueError(f"Wallet controller already exists: {controller_did}")

        approval = verify_approval(
            self.approval_requests,
            approval_id=approval_id,
            operation="wallet/controller_recover",
            requested_by=actor_did,
            resources=[resource_for_wallet(wallet_id)],
            abilities=["wallet/admin"],
        )
        if set(approval.approver_dids) != set(contact_dids) or approval.threshold != recovery_policy["threshold"]:
            raise ApprovalRequiredError("Recovery approval does not match active recovery policy")

        if controller_secret is not None:
            self.set_principal_secret(controller_did, controller_secret)
        else:
            self._ensure_principal_secret(controller_did)
        wallet.controller_dids.append(controller_did)
        self._sync_governance_policy_controllers(wallet)
        self._touch_wallet(wallet)
        append_audit_event(
            self.audit_events[wallet_id],
            wallet_id=wallet_id,
            actor_did=actor_did,
            action="wallet/controller_recover",
            resource=resource_for_wallet(wallet_id),
            decision="allow",
            details={
                "controller_did": controller_did,
                "approval_id": approval.approval_id,
                "recovery_threshold": recovery_policy["threshold"],
            },
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
        if self._is_wallet_controller(wallet, requested_by):
            request = create_approval_request(
                wallet,
                requested_by=requested_by,
                operation=operation,
                resources=resources,
                abilities=abilities,
                details=details,
                expires_at=expires_at,
            )
        elif operation in self.RECOVERY_APPROVAL_OPERATIONS:
            request = self._create_recovery_approval_request(
                wallet,
                requested_by=requested_by,
                operation=operation,
                resources=resources,
                abilities=abilities,
                details=details,
                expires_at=expires_at,
            )
        else:
            self._assert_controller(wallet, requested_by)
            raise AccessDeniedError(f"{requested_by} is not allowed to request approval")
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

    def access_request_review_items(
        self,
        wallet_id: str,
        *,
        status: Optional[str] = None,
        requester_did: Optional[str] = None,
        audience_did: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Return access requests with operator-facing approval and grant state."""

        wallet = self._wallet(wallet_id)
        items: List[Dict[str, Any]] = []
        for request in self.list_access_requests(
            wallet_id,
            status=status,
            requester_did=requester_did,
            audience_did=audience_did,
        ):
            approval_required = operation_requires_approval(
                wallet,
                operation="grant/create",
                resources=request.resources,
                abilities=request.abilities,
                caveats={"purpose": request.purpose, **dict(request.details)},
            )
            approval = self._matching_approval(
                wallet_id,
                resources=request.resources,
                abilities=request.abilities,
                operation="grant/create",
            )
            grant = self.grants.get(request.grant_id or "")
            item = request.to_dict()
            item.update(
                {
                    "approval_required": approval_required,
                    "approval_id": approval.approval_id if approval else None,
                    "approval_status": approval.status if approval else None,
                    "approval_threshold": approval.threshold if approval else None,
                    "approval_count": approval.approved_count if approval else 0,
                    "grant_status": grant.status if grant else None,
                }
            )
            items.append(item)
        return items

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

    def revoke_access_request(
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
        if request.status != "approved" or not request.grant_id:
            raise GrantError(f"Access request is not revocable: {request_id}")
        self.revoke_grant(wallet_id, request.grant_id, actor_did=actor_did)
        request.status = "revoked"
        request.decided_at = utc_now()
        request.decided_by = actor_did
        if reason:
            request.details = {**request.details, "revocation_reason": reason}
        wallet.updated_at = utc_now()
        wallet.manifest_head = sha256_hex(canonical_bytes(self.get_wallet_manifest(wallet_id)))
        append_audit_event(
            self.audit_events[wallet_id],
            wallet_id=wallet_id,
            actor_did=actor_did,
            action="access/revoke",
            resource=",".join(request.resources),
            decision="allow",
            details={"request_id": request.request_id, "reason": reason},
            grant_id=request.grant_id,
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
        parent_grant_id: Optional[str] = None,
    ) -> Grant:
        wallet = self._wallet(wallet_id)
        if issuer_secret is not None:
            self.set_principal_secret(issuer_did, issuer_secret)
        if audience_secret is not None:
            self.set_principal_secret(audience_did, audience_secret)
        if not resources or not abilities:
            raise GrantError("Grant requires at least one resource and ability")
        proof_chain: List[str] = []
        if parent_grant_id is None:
            self._assert_controller(wallet, issuer_did)
        else:
            parent_grant = self._delegation_parent_grant(
                wallet_id=wallet_id,
                parent_grant_id=parent_grant_id,
                issuer_did=issuer_did,
                resources=resources,
                abilities=abilities,
                caveats=caveats or {},
                expires_at=expires_at,
            )
            proof_chain = [*parent_grant.proof_chain, parent_grant.grant_id]
        if approval_id is None:
            approval_id = (caveats or {}).get("approval_id") or (caveats or {}).get("approval_ref")
        if parent_grant_id is None and operation_requires_approval(
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
            proof_chain=proof_chain,
            expires_at=expires_at,
        )
        self.grants[grant.grant_id] = grant
        self._ensure_principal_secret(audience_did)
        if any(ability in abilities for ability in ("record/decrypt", "record/analyze", "*")):
            self._wrap_granted_record_keys(wallet_id, issuer_did, audience_did, grant)
        receipt = self._create_grant_receipt(wallet_id, grant)
        wallet.updated_at = utc_now()
        wallet.manifest_head = sha256_hex(canonical_bytes(self.get_wallet_manifest(wallet_id)))
        append_audit_event(
            self.audit_events[wallet_id],
            wallet_id=wallet_id,
            actor_did=issuer_did,
            action="grant/create",
            resource=",".join(resources),
            decision="allow",
            details={
                "abilities": abilities,
                "audience_did": audience_did,
                "parent_grant_id": parent_grant_id,
                "proof_chain": proof_chain,
                "receipt_id": receipt.receipt_id,
                "receipt_hash": receipt.receipt_hash,
            },
            grant_id=grant.grant_id,
        )
        return grant

    def list_grant_receipts(
        self,
        wallet_id: str,
        *,
        audience_did: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[GrantReceipt]:
        self._wallet(wallet_id)
        receipts = [
            receipt
            for receipt in self.grant_receipts.values()
            if receipt.wallet_id == wallet_id
        ]
        if audience_did is not None:
            receipts = [receipt for receipt in receipts if receipt.audience_did == audience_did]
        if status is not None:
            receipts = [receipt for receipt in receipts if receipt.status == status]
        return sorted(receipts, key=lambda item: item.created_at)

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
        self._assert_grant_chain_active(wallet_id, grant)
        record_id = record_id_from_resource(resource)
        data_type = None
        if record_id in self.records and self.records[record_id].wallet_id == wallet_id:
            data_type = self.records[record_id].data_type
        invocation = create_invocation(
            grant=grant,
            audience_did=actor_did,
            resource=resource,
            ability=ability,
            signing_secret=self._ensure_principal_secret(actor_did),
            caveats=caveats,
            expires_at=expires_at,
            record_id=record_id,
            data_type=data_type,
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
        self._assert_grant_chain_active(wallet_id, grant)
        record_id = record_id_from_resource(resource)
        data_type = None
        if record_id in self.records and self.records[record_id].wallet_id == wallet_id:
            data_type = self.records[record_id].data_type
        assert_invocation_allows(
            invocation,
            grant,
            audience_did=actor_did,
            resource=resource,
            ability=ability,
            signing_secret=self._ensure_principal_secret(actor_did),
            record_id=record_id,
            data_type=data_type,
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
        revoked_grant_ids = [
            candidate_id
            for candidate_id, candidate in self.grants.items()
            if candidate_id == grant_id or grant_id in candidate.proof_chain
        ]
        for revoked_grant_id in revoked_grant_ids:
            self.grants[revoked_grant_id].status = "revoked"
        for version in self.versions.values():
            for key_wrap in version.key_wraps:
                if key_wrap.grant_id in revoked_grant_ids:
                    key_wrap.status = "revoked"
        for receipt in self.grant_receipts.values():
            if receipt.wallet_id == wallet_id and receipt.grant_id in revoked_grant_ids:
                receipt.status = "revoked"
        for request in self.access_requests.values():
            if request.wallet_id == wallet_id and request.grant_id in revoked_grant_ids and request.status == "approved":
                request.status = "revoked"
                request.decided_at = utc_now()
                request.decided_by = actor_did
                request.details = {**request.details, "revoked_by_grant_id": grant_id}
        wallet.updated_at = utc_now()
        wallet.manifest_head = sha256_hex(canonical_bytes(self.get_wallet_manifest(wallet_id)))
        append_audit_event(
            self.audit_events[wallet_id],
            wallet_id=wallet_id,
            actor_did=actor_did,
            action="grant/revoke",
            resource=",".join(grant.resources),
            decision="allow",
            details={
                "revoked_grant_ids": revoked_grant_ids,
                "descendant_count": max(0, len(revoked_grant_ids) - 1),
            },
            grant_id=grant_id,
        )
        return grant

    def emergency_revoke(
        self,
        wallet_id: str,
        *,
        actor_did: str,
        actor_secret: Optional[bytes] = None,
        approval_id: Optional[str] = None,
        rotate_keys: bool = True,
        reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        wallet = self._wallet(wallet_id)
        self._assert_controller(wallet, actor_did)
        self._verify_wallet_admin_approval(
            wallet,
            actor_did=actor_did,
            operation="wallet/emergency_revoke",
            approval_id=approval_id,
        )
        if actor_secret is not None:
            self.set_principal_secret(actor_did, actor_secret)

        revoked_grant_ids = self._wallet_grant_ids_for_revocation(wallet_id)
        revoked_grant_id_set = set(revoked_grant_ids)
        for grant_id in revoked_grant_ids:
            self.grants[grant_id].status = "revoked"
        for version in self.versions.values():
            for key_wrap in version.key_wraps:
                if key_wrap.grant_id in revoked_grant_id_set:
                    key_wrap.status = "revoked"
        for receipt in self.grant_receipts.values():
            if receipt.wallet_id == wallet_id and receipt.grant_id in revoked_grant_id_set:
                receipt.status = "revoked"
        for request in self.access_requests.values():
            if request.wallet_id == wallet_id and request.grant_id in revoked_grant_id_set and request.status == "approved":
                request.status = "revoked"
                request.decided_at = utc_now()
                request.decided_by = actor_did
                request.details = {**request.details, "revocation_reason": reason or "emergency_revoke"}

        rotated_record_ids: List[str] = []
        rotation_errors: Dict[str, str] = {}
        if rotate_keys:
            for record_id in sorted(
                record.record_id for record in self.records.values() if record.wallet_id == wallet_id
            ):
                try:
                    self.rotate_record_key(
                        wallet_id,
                        record_id,
                        actor_did=actor_did,
                        actor_secret=actor_secret,
                    )
                    rotated_record_ids.append(record_id)
                except Exception as exc:
                    rotation_errors[record_id] = str(exc)

        self._touch_wallet(wallet)
        report = {
            "wallet_id": wallet_id,
            "revoked_grant_ids": revoked_grant_ids,
            "revoked_grant_count": len(revoked_grant_ids),
            "rotated_record_ids": rotated_record_ids,
            "rotated_record_count": len(rotated_record_ids),
            "rotation_errors": rotation_errors,
            "rotate_keys": rotate_keys,
            "reason": reason,
        }
        append_audit_event(
            self.audit_events[wallet_id],
            wallet_id=wallet_id,
            actor_did=actor_did,
            action="wallet/emergency_revoke",
            resource=resource_for_wallet(wallet_id),
            decision="allow" if not rotation_errors else "partial",
            details=report,
        )
        return report

    def decrypt_record(
        self,
        wallet_id: str,
        record_id: str,
        *,
        actor_did: str,
        grant_id: Optional[str] = None,
        actor_secret: Optional[bytes] = None,
        invocation_caveats: Optional[Dict[str, Any]] = None,
    ) -> bytes:
        record = self._record(wallet_id, record_id)
        if actor_secret is not None:
            self.set_principal_secret(actor_did, actor_secret)
        if actor_did != self._wallet(wallet_id).owner_did:
            operation_caveats = self._operation_caveats(invocation_caveats, output_types=["plaintext"])
            if grant_id is None:
                raise AccessDeniedError("Non-owner decrypt requires a grant")
            grant = self.grants[grant_id]
            self._assert_grant_allows(
                grant,
                wallet_id=wallet_id,
                audience_did=actor_did,
                resource=resource_for_record(wallet_id, record_id),
                ability="record/decrypt",
                invocation_caveats=operation_caveats,
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
            invocation_caveats=invocation.caveats,
        )

    def rotate_record_key(
        self,
        wallet_id: str,
        record_id: str,
        *,
        actor_did: str,
        actor_secret: Optional[bytes] = None,
    ) -> DataVersion:
        """Re-encrypt the current record version with a fresh data key.

        Active key-wrap recipients from the current version are carried forward,
        so existing grants continue to work against the new current version.
        """

        wallet = self._wallet(wallet_id)
        self._assert_controller(wallet, actor_did)
        if actor_secret is not None:
            self.set_principal_secret(actor_did, actor_secret)
        record = self._record(wallet_id, record_id)
        old_version = self.versions[record.current_version_id]
        old_dek = self._unwrap_dek(old_version, wallet_id, actor_did)
        old_payload_aad = self._payload_aad(
            wallet_id,
            record_id,
            old_version.version_id,
            record.data_type,
        )
        plaintext = decrypt_bytes(
            EncryptedBlob.from_dict(json.loads(self.storage.get(old_version.encrypted_payload_ref).decode("utf-8"))),
            old_dek,
            old_payload_aad,
        )
        metadata_plaintext = None
        if old_version.encrypted_metadata_ref is not None:
            metadata_plaintext = decrypt_bytes(
                EncryptedBlob.from_dict(json.loads(self.storage.get(old_version.encrypted_metadata_ref).decode("utf-8"))),
                old_dek,
                old_payload_aad | {"kind": "metadata"},
            )

        new_version_id = f"ver-{uuid.uuid4().hex}"
        new_dek = random_key()
        new_payload_aad = self._payload_aad(wallet_id, record_id, new_version_id, record.data_type)
        encrypted_payload = encrypt_bytes(plaintext, new_dek, new_payload_aad)
        payload_ref = self.storage.put(canonical_bytes(encrypted_payload.to_dict()))
        metadata_ref = None
        if metadata_plaintext is not None:
            encrypted_metadata = encrypt_bytes(
                metadata_plaintext,
                new_dek,
                new_payload_aad | {"kind": "metadata"},
            )
            metadata_ref = self.storage.put(canonical_bytes(encrypted_metadata.to_dict()))

        recipients = sorted(
            {
                key_wrap.recipient_did
                for key_wrap in old_version.key_wraps
                if self._key_wrap_is_active_authorized(key_wrap)
            }
            | {actor_did}
        )
        key_wraps = [
            KeyWrap(
                wrap_id=f"wrap-{uuid.uuid4().hex}",
                record_id=record_id,
                version_id=new_version_id,
                recipient_did=recipient_did,
                wrapped_dek=wrap_key(
                    new_dek,
                    self._ensure_principal_secret(recipient_did),
                    self._wrap_aad(wallet_id, record_id, new_version_id, recipient_did),
                ),
                wrap_algorithm=KEY_WRAP_ALGORITHM,
                grant_id=self._active_key_wrap_grant_id(old_version, recipient_did),
            )
            for recipient_did in recipients
        ]
        version = DataVersion(
            version_id=new_version_id,
            record_id=record_id,
            encrypted_payload_ref=payload_ref,
            encrypted_metadata_ref=metadata_ref,
            ciphertext_hash=payload_ref.sha256,
            encryption_suite=ENCRYPTION_SUITE,
            key_wraps=key_wraps,
            derived_artifact_ids=[],
            proof_receipt_ids=[],
        )
        self.versions[new_version_id] = version
        record.current_version_id = new_version_id
        record.updated_at = utc_now()
        wallet.updated_at = utc_now()
        wallet.manifest_head = sha256_hex(canonical_bytes(self.get_wallet_manifest(wallet_id)))
        append_audit_event(
            self.audit_events[wallet_id],
            wallet_id=wallet_id,
            actor_did=actor_did,
            action="record/key_rotate",
            resource=resource_for_record(wallet_id, record_id),
            decision="allow",
            details={
                "previous_version_id": old_version.version_id,
                "version_id": new_version_id,
                "recipient_count": len(key_wraps),
            },
        )
        return version

    def create_coarse_location_claim(
        self,
        wallet_id: str,
        record_id: str,
        *,
        actor_did: str,
        grant_id: Optional[str] = None,
        precision: int = 2,
        invocation_caveats: Optional[Dict[str, Any]] = None,
    ) -> LocationClaim:
        record = self._record(wallet_id, record_id)
        if record.data_type != "location":
            raise ValueError("Record is not a location record")
        if actor_did != self._wallet(wallet_id).owner_did:
            if grant_id is None:
                raise AccessDeniedError("Coarse location claim requires a grant")
            self._assert_grant_allows(
                self.grants[grant_id],
                wallet_id=wallet_id,
                audience_did=actor_did,
                resource=resource_for_location(wallet_id, record_id),
                ability="location/read_coarse",
                invocation_caveats=invocation_caveats,
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
            invocation_caveats=invocation.caveats,
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
            self._assert_grant_allows(
                self.grants[grant_id],
                wallet_id=wallet_id,
                audience_did=actor_did,
                resource=resource_for_location(wallet_id, record_id),
                ability="location/prove_region",
            )
        raw = self.decrypt_record(wallet_id, record_id, actor_did=self._wallet(wallet_id).owner_did)
        payload = json.loads(raw.decode("utf-8"))
        statement = region_membership_statement(payload["lat"], payload["lon"], region_id)
        public_inputs = {
            "region_id": region_id,
            "claim": "location_in_region",
            "region_policy_hash": sha256_hex(region_id.encode("utf-8")),
        }
        witness = {
            "lat": payload["lat"],
            "lon": payload["lon"],
            "wallet_id": wallet_id,
            "record_id": record_id,
        }
        receipt = self.proof_backend.prove_location_region(
            wallet_id=wallet_id,
            statement=statement,
            public_inputs=public_inputs,
            witness=witness,
            witness_record_ids=[record_id],
        )
        if receipt.is_simulated and not self.allow_simulated_proofs:
            raise DataWalletError("Simulated proofs are disabled for this wallet service")
        if not self.proof_backend.verify(receipt):
            raise DataWalletError("Proof verification failed")
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

    def create_location_distance_proof(
        self,
        wallet_id: str,
        record_id: str,
        *,
        actor_did: str,
        target_id: str,
        target_lat: float,
        target_lon: float,
        max_distance_km: float,
        grant_id: Optional[str] = None,
    ) -> ProofReceipt:
        record = self._record(wallet_id, record_id)
        if record.data_type != "location":
            raise ValueError("Record is not a location record")
        if float(max_distance_km) <= 0:
            raise ValueError("max_distance_km must be positive")
        if actor_did != self._wallet(wallet_id).owner_did:
            if grant_id is None:
                raise AccessDeniedError("Location distance proof requires a grant")
            self._assert_grant_allows(
                self.grants[grant_id],
                wallet_id=wallet_id,
                audience_did=actor_did,
                resource=resource_for_location(wallet_id, record_id),
                ability="location/prove_distance",
            )
        raw = self.decrypt_record(wallet_id, record_id, actor_did=self._wallet(wallet_id).owner_did)
        payload = json.loads(raw.decode("utf-8"))
        distance_km = haversine_distance_km(
            payload["lat"],
            payload["lon"],
            target_lat,
            target_lon,
        )
        if distance_km > float(max_distance_km):
            raise DataWalletError("Location is outside the requested distance threshold")
        statement = distance_membership_statement(
            payload["lat"],
            payload["lon"],
            target_id=target_id,
            target_lat=target_lat,
            target_lon=target_lon,
            max_distance_km=max_distance_km,
        )
        public_inputs = {
            "target_id": target_id,
            "claim": "location_within_distance",
            "max_distance_km": float(max_distance_km),
            "target_policy_hash": statement["target_policy_hash"],
        }
        witness = {
            "lat": payload["lat"],
            "lon": payload["lon"],
            "target_lat": float(target_lat),
            "target_lon": float(target_lon),
            "max_distance_km": float(max_distance_km),
            "wallet_id": wallet_id,
            "record_id": record_id,
        }
        prove_distance = getattr(self.proof_backend, "prove_location_distance", None)
        if not callable(prove_distance):
            raise DataWalletError("Configured proof backend does not support location_distance")
        receipt = prove_distance(
            wallet_id=wallet_id,
            statement=statement,
            public_inputs=public_inputs,
            witness=witness,
            witness_record_ids=[record_id],
        )
        if receipt.is_simulated and not self.allow_simulated_proofs:
            raise DataWalletError("Simulated proofs are disabled for this wallet service")
        if not self.proof_backend.verify(receipt):
            raise DataWalletError("Proof verification failed")
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
        invocation_caveats: Optional[Dict[str, Any]] = None,
    ) -> DerivedArtifact:
        if actor_secret is not None:
            self.set_principal_secret(actor_did, actor_secret)
        if actor_did != self._wallet(wallet_id).owner_did:
            operation_caveats = self._operation_caveats(invocation_caveats, output_types=["summary"])
            if grant_id is None:
                raise AccessDeniedError("Analysis requires a grant")
            self._assert_grant_allows(
                self.grants[grant_id],
                wallet_id=wallet_id,
                audience_did=actor_did,
                resource=resource_for_record(wallet_id, record_id),
                ability="record/analyze",
                invocation_caveats=operation_caveats,
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

    def analyze_document_with_redaction(
        self,
        wallet_id: str,
        record_id: str,
        *,
        actor_did: str,
        grant_id: Optional[str] = None,
        actor_secret: Optional[bytes] = None,
        max_chars: int = 500,
        invocation_caveats: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Create an encrypted redacted-analysis artifact and return safe output."""
        if actor_secret is not None:
            self.set_principal_secret(actor_did, actor_secret)
        if actor_did != self._wallet(wallet_id).owner_did:
            operation_caveats = self._operation_caveats(
                invocation_caveats,
                output_types=["redacted_derived_only"],
            )
            if grant_id is None:
                raise AccessDeniedError("Analysis requires a grant")
            self._assert_grant_allows(
                self.grants[grant_id],
                wallet_id=wallet_id,
                audience_did=actor_did,
                resource=resource_for_record(wallet_id, record_id),
                ability="record/analyze",
                invocation_caveats=operation_caveats,
            )
        record = self._record(wallet_id, record_id)
        if record.data_type != "document":
            raise ValueError("Redacted document analysis requires a document record")
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
        redacted_text, redaction_counts = self._redact_text(text)
        safe_text = redacted_text[:max_chars]
        derived_facts = self._derive_document_facts(redacted_text)
        output = {
            "summary": safe_text,
            "truncated": len(redacted_text) > max_chars,
            "redaction_counts": redaction_counts,
            "derived_facts": derived_facts,
            "source_record_count": 1,
            "raw_text_chars": len(text),
            "output_policy": "redacted_derived_only",
        }
        artifact_key = random_key()
        encrypted = encrypt_bytes(
            canonical_bytes(output),
            artifact_key,
            {"wallet_id": wallet_id, "record_id": record_id, "kind": "redacted_derived"},
        )
        ref = self.storage.put(canonical_bytes(encrypted.to_dict()))
        artifact = DerivedArtifact(
            artifact_id=f"artifact-{uuid.uuid4().hex}",
            wallet_id=wallet_id,
            source_record_ids=[record_id],
            artifact_type="redacted_document_analysis",
            output_policy="redacted_derived_only",
            encrypted_payload_ref=ref,
        )
        self.derived_artifacts[artifact.artifact_id] = artifact
        self.versions[record.current_version_id].derived_artifact_ids.append(artifact.artifact_id)
        append_audit_event(
            self.audit_events[wallet_id],
            wallet_id=wallet_id,
            actor_did=actor_did,
            action="record/analyze_redacted",
            resource=resource_for_record(wallet_id, record_id),
            decision="allow",
            details={
                "artifact_id": artifact.artifact_id,
                "artifact_type": artifact.artifact_type,
                "redaction_counts": redaction_counts,
                "derived_fact_keys": sorted(derived_facts),
            },
            grant_id=grant_id,
        )
        return {"artifact": artifact, "output": output}

    def _redact_text(self, text: str) -> tuple[str, Dict[str, int]]:
        redacted = text
        counts: Dict[str, int] = {}
        for label, pattern in self.REDACTION_PATTERNS.items():
            redacted, count = pattern.subn(f"[REDACTED_{label.upper()}]", redacted)
            counts[label] = count
        return redacted, counts

    def _derive_document_facts(self, redacted_text: str) -> Dict[str, Any]:
        lower = redacted_text.lower()
        categories = [
            category
            for category, keywords in self.DERIVED_FACT_KEYWORDS.items()
            if any(keyword in lower for keyword in keywords)
        ]
        return {
            "need_categories": categories,
            "contains_contact_redactions": any(
                token in redacted_text
                for token in ("[REDACTED_EMAIL]", "[REDACTED_PHONE]", "[REDACTED_ADDRESS]")
            ),
        }

    def create_document_vector_profile(
        self,
        wallet_id: str,
        record_id: str,
        *,
        actor_did: str,
        grant_id: Optional[str] = None,
        actor_secret: Optional[bytes] = None,
        chunk_size_words: int = 80,
        invocation_caveats: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Create an encrypted vector-profile artifact without returning raw text."""
        if actor_secret is not None:
            self.set_principal_secret(actor_did, actor_secret)
        if actor_did != self._wallet(wallet_id).owner_did:
            operation_caveats = self._operation_caveats(
                invocation_caveats,
                output_types=["vector_profile"],
            )
            if grant_id is None:
                raise AccessDeniedError("Vector profile creation requires a grant")
            self._assert_grant_allows(
                self.grants[grant_id],
                wallet_id=wallet_id,
                audience_did=actor_did,
                resource=resource_for_record(wallet_id, record_id),
                ability="record/analyze",
                invocation_caveats=operation_caveats,
            )
        record = self._record(wallet_id, record_id)
        if record.data_type != "document":
            raise ValueError("Document vector profile requires a document record")
        if chunk_size_words < 1:
            raise ValueError("chunk_size_words must be at least 1")
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
        redacted_text, redaction_counts = self._redact_text(text)
        profile = self._derive_vector_profile(redacted_text, chunk_size_words=chunk_size_words)
        output = {
            "output_policy": "encrypted_vector_profile",
            "redaction_counts": redaction_counts,
            "derived_facts": self._derive_document_facts(redacted_text),
            "profile": profile,
            "source_record_count": 1,
            "raw_text_chars": len(text),
        }
        artifact_key = random_key()
        encrypted = encrypt_bytes(
            canonical_bytes(output),
            artifact_key,
            {"wallet_id": wallet_id, "record_id": record_id, "kind": "vector_profile"},
        )
        ref = self.storage.put(canonical_bytes(encrypted.to_dict()))
        artifact = DerivedArtifact(
            artifact_id=f"artifact-{uuid.uuid4().hex}",
            wallet_id=wallet_id,
            source_record_ids=[record_id],
            artifact_type="redacted_document_vector_profile",
            output_policy="encrypted_vector_profile",
            encrypted_payload_ref=ref,
        )
        self.derived_artifacts[artifact.artifact_id] = artifact
        self.versions[record.current_version_id].derived_artifact_ids.append(artifact.artifact_id)
        append_audit_event(
            self.audit_events[wallet_id],
            wallet_id=wallet_id,
            actor_did=actor_did,
            action="record/vector_profile",
            resource=resource_for_record(wallet_id, record_id),
            decision="allow",
            details={
                "artifact_id": artifact.artifact_id,
                "artifact_type": artifact.artifact_type,
                "chunk_count": profile["chunk_count"],
                "feature_keys": sorted(profile["feature_vector"]),
            },
            grant_id=grant_id,
        )
        return {"artifact": artifact, "output": output}

    def analyze_documents_with_redaction(
        self,
        wallet_id: str,
        record_ids: List[str],
        *,
        actor_did: str,
        grant_id: Optional[str] = None,
        actor_secret: Optional[bytes] = None,
        invocation_caveats: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Create an encrypted cross-record derived analysis without returning document text."""
        if actor_secret is not None:
            self.set_principal_secret(actor_did, actor_secret)
        ordered_record_ids = list(dict.fromkeys(record_ids))
        if not ordered_record_ids:
            raise ValueError("At least one record_id is required")

        wallet = self._wallet(wallet_id)
        if actor_did != wallet.owner_did:
            operation_caveats = self._operation_caveats(
                invocation_caveats,
                output_types=["redacted_derived_only"],
            )
            if grant_id is None:
                raise AccessDeniedError("Cross-record analysis requires a grant")
            grant = self.grants[grant_id]
            for record_id in ordered_record_ids:
                self._assert_grant_allows(
                    grant,
                    wallet_id=wallet_id,
                    audience_did=actor_did,
                    resource=resource_for_record(wallet_id, record_id),
                    ability="record/analyze",
                    invocation_caveats=operation_caveats,
                )

        per_record: List[Dict[str, Any]] = []
        combined_counts = {label: 0 for label in self.REDACTION_PATTERNS}
        category_record_counts = {category: 0 for category in self.DERIVED_FACT_KEYWORDS}
        all_categories: set[str] = set()
        total_chars = 0

        for record_id in ordered_record_ids:
            record = self._record(wallet_id, record_id)
            if record.data_type != "document":
                raise ValueError("Cross-record redacted analysis requires document records")
            if actor_did == wallet.owner_did:
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
            redacted_text, redaction_counts = self._redact_text(text)
            facts = self._derive_document_facts(redacted_text)
            categories = set(facts["need_categories"])
            all_categories.update(categories)
            total_chars += len(text)
            for label, count in redaction_counts.items():
                combined_counts[label] = combined_counts.get(label, 0) + count
            for category in categories:
                category_record_counts[category] = category_record_counts.get(category, 0) + 1
            per_record.append(
                {
                    "record_id": record_id,
                    "derived_facts": facts,
                    "redaction_counts": redaction_counts,
                    "raw_text_chars": len(text),
                }
            )

        derived_facts = {
            "need_categories": sorted(all_categories),
            "category_record_counts": {
                category: count
                for category, count in sorted(category_record_counts.items())
                if count > 0
            },
            "contains_contact_redactions": any(count > 0 for count in combined_counts.values()),
        }
        category_text = ", ".join(derived_facts["need_categories"]) if derived_facts["need_categories"] else "none"
        output = {
            "summary": f"Detected need categories across authorized records: {category_text}.",
            "redaction_counts": combined_counts,
            "derived_facts": derived_facts,
            "per_record": per_record,
            "source_record_count": len(ordered_record_ids),
            "source_record_ids": ordered_record_ids,
            "raw_text_chars": total_chars,
            "output_policy": "redacted_derived_only",
        }
        artifact_key = random_key()
        encrypted = encrypt_bytes(
            canonical_bytes(output),
            artifact_key,
            {"wallet_id": wallet_id, "record_ids": ordered_record_ids, "kind": "redacted_cross_record"},
        )
        ref = self.storage.put(canonical_bytes(encrypted.to_dict()))
        artifact = DerivedArtifact(
            artifact_id=f"artifact-{uuid.uuid4().hex}",
            wallet_id=wallet_id,
            source_record_ids=ordered_record_ids,
            artifact_type="redacted_cross_document_analysis",
            output_policy="redacted_derived_only",
            encrypted_payload_ref=ref,
        )
        self.derived_artifacts[artifact.artifact_id] = artifact
        for record_id in ordered_record_ids:
            self.versions[self._record(wallet_id, record_id).current_version_id].derived_artifact_ids.append(
                artifact.artifact_id
            )
        append_audit_event(
            self.audit_events[wallet_id],
            wallet_id=wallet_id,
            actor_did=actor_did,
            action="record/analyze_redacted_batch",
            resource=",".join(resource_for_record(wallet_id, record_id) for record_id in ordered_record_ids),
            decision="allow",
            details={
                "artifact_id": artifact.artifact_id,
                "artifact_type": artifact.artifact_type,
                "source_record_count": len(ordered_record_ids),
                "redaction_counts": combined_counts,
                "derived_fact_keys": sorted(derived_facts),
            },
            grant_id=grant_id,
        )
        return {"artifact": artifact, "output": output}

    def extract_document_text_with_redaction(
        self,
        wallet_id: str,
        record_id: str,
        *,
        actor_did: str,
        grant_id: Optional[str] = None,
        actor_secret: Optional[bytes] = None,
        max_chars: int = 20_000,
        max_bytes: int = 200_000,
        use_ocr: bool = True,
        invocation_caveats: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Extract document text inside the wallet boundary and return only redacted output."""
        if actor_secret is not None:
            self.set_principal_secret(actor_did, actor_secret)
        if max_chars < 1:
            raise ValueError("max_chars must be at least 1")
        if max_bytes < 1:
            raise ValueError("max_bytes must be at least 1")
        if actor_did != self._wallet(wallet_id).owner_did:
            operation_caveats = self._operation_caveats(
                invocation_caveats,
                output_types=["redacted_extracted_text"],
            )
            if grant_id is None:
                raise AccessDeniedError("Text extraction requires a grant")
            self._assert_grant_allows(
                self.grants[grant_id],
                wallet_id=wallet_id,
                audience_did=actor_did,
                resource=resource_for_record(wallet_id, record_id),
                ability="record/analyze",
                invocation_caveats=operation_caveats,
            )
        record = self._record(wallet_id, record_id)
        if record.data_type != "document":
            raise ValueError("Text extraction requires a document record")
        plaintext, metadata = self._decrypt_record_bytes_and_metadata(
            wallet_id,
            record,
            actor_did=actor_did,
            actor_secret=actor_secret,
        )
        extraction = self._extract_document_text_from_bytes(
            plaintext,
            metadata=metadata,
            record_id=record_id,
            max_chars=max_chars,
            max_bytes=max_bytes,
            use_ocr=use_ocr,
        )
        extracted_text = str(extraction.get("text") or "")
        redacted_text, redaction_counts = self._redact_text(extracted_text)
        output = {
            "text": redacted_text,
            "truncated": len(extracted_text) > max_chars,
            "redaction_counts": redaction_counts,
            "derived_facts": self._derive_document_facts(redacted_text),
            "source_record_count": 1,
            "source_record_id": record_id,
            "raw_text_chars": len(extracted_text),
            "original_size_bytes": len(plaintext),
            "extraction": {
                "method": extraction.get("method"),
                "suffix": extraction.get("suffix"),
                "ocr_used": bool(extraction.get("ocr_used")),
                "ocr_engine": extraction.get("ocr_engine"),
                "confidence": extraction.get("confidence"),
                "error": extraction.get("error"),
            },
            "output_policy": "redacted_extracted_text",
        }
        artifact_key = random_key()
        encrypted = encrypt_bytes(
            canonical_bytes(output),
            artifact_key,
            {"wallet_id": wallet_id, "record_id": record_id, "kind": "redacted_text_extraction"},
        )
        ref = self.storage.put(canonical_bytes(encrypted.to_dict()))
        artifact = DerivedArtifact(
            artifact_id=f"artifact-{uuid.uuid4().hex}",
            wallet_id=wallet_id,
            source_record_ids=[record_id],
            artifact_type="redacted_document_text_extraction",
            output_policy="redacted_extracted_text",
            encrypted_payload_ref=ref,
        )
        self.derived_artifacts[artifact.artifact_id] = artifact
        self.versions[record.current_version_id].derived_artifact_ids.append(artifact.artifact_id)
        append_audit_event(
            self.audit_events[wallet_id],
            wallet_id=wallet_id,
            actor_did=actor_did,
            action="record/extract_text_redacted",
            resource=resource_for_record(wallet_id, record_id),
            decision="allow",
            details={
                "artifact_id": artifact.artifact_id,
                "artifact_type": artifact.artifact_type,
                "method": extraction.get("method"),
                "ocr_used": bool(extraction.get("ocr_used")),
                "redaction_counts": redaction_counts,
            },
            grant_id=grant_id,
        )
        return {"artifact": artifact, "output": output}

    def analyze_document_form_with_redaction(
        self,
        wallet_id: str,
        record_id: str,
        *,
        actor_did: str,
        grant_id: Optional[str] = None,
        actor_secret: Optional[bytes] = None,
        max_fields: int = 100,
        use_ocr: bool = False,
        invocation_caveats: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Analyze form structure inside the wallet boundary and return redacted field metadata."""
        if actor_secret is not None:
            self.set_principal_secret(actor_did, actor_secret)
        if max_fields < 1:
            raise ValueError("max_fields must be at least 1")
        if actor_did != self._wallet(wallet_id).owner_did:
            operation_caveats = self._operation_caveats(
                invocation_caveats,
                output_types=["redacted_form_analysis"],
            )
            if grant_id is None:
                raise AccessDeniedError("Form analysis requires a grant")
            self._assert_grant_allows(
                self.grants[grant_id],
                wallet_id=wallet_id,
                audience_did=actor_did,
                resource=resource_for_record(wallet_id, record_id),
                ability="record/analyze",
                invocation_caveats=operation_caveats,
            )
        record = self._record(wallet_id, record_id)
        if record.data_type != "document":
            raise ValueError("Form analysis requires a document record")
        plaintext, metadata = self._decrypt_record_bytes_and_metadata(
            wallet_id,
            record,
            actor_did=actor_did,
            actor_secret=actor_secret,
        )
        analysis = self._analyze_form_from_document_bytes(
            plaintext,
            metadata=metadata,
            record_id=record_id,
            max_fields=max_fields,
            use_ocr=use_ocr,
        )
        output = {
            "output_policy": "redacted_form_analysis",
            "source_record_count": 1,
            "source_record_id": record_id,
            "original_size_bytes": len(plaintext),
            **analysis,
        }
        artifact_key = random_key()
        encrypted = encrypt_bytes(
            canonical_bytes(output),
            artifact_key,
            {"wallet_id": wallet_id, "record_id": record_id, "kind": "redacted_form_analysis"},
        )
        ref = self.storage.put(canonical_bytes(encrypted.to_dict()))
        artifact = DerivedArtifact(
            artifact_id=f"artifact-{uuid.uuid4().hex}",
            wallet_id=wallet_id,
            source_record_ids=[record_id],
            artifact_type="redacted_document_form_analysis",
            output_policy="redacted_form_analysis",
            encrypted_payload_ref=ref,
        )
        self.derived_artifacts[artifact.artifact_id] = artifact
        self.versions[record.current_version_id].derived_artifact_ids.append(artifact.artifact_id)
        append_audit_event(
            self.audit_events[wallet_id],
            wallet_id=wallet_id,
            actor_did=actor_did,
            action="record/analyze_form_redacted",
            resource=resource_for_record(wallet_id, record_id),
            decision="allow",
            details={
                "artifact_id": artifact.artifact_id,
                "artifact_type": artifact.artifact_type,
                "method": analysis["form"]["method"],
                "field_count": analysis["form"]["field_count"],
                "redaction_counts": analysis["redaction_counts"],
            },
            grant_id=grant_id,
        )
        return {"artifact": artifact, "output": output}

    def create_redacted_graphrag(
        self,
        wallet_id: str,
        record_ids: List[str],
        *,
        actor_did: str,
        grant_id: Optional[str] = None,
        actor_secret: Optional[bytes] = None,
        max_chars_per_record: int = 20_000,
        max_bytes_per_record: int = 200_000,
        use_ocr: bool = True,
        invocation_caveats: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Create an encrypted redacted GraphRAG artifact from authorized document records."""
        if actor_secret is not None:
            self.set_principal_secret(actor_did, actor_secret)
        ordered_record_ids = list(dict.fromkeys(record_ids))
        if not ordered_record_ids:
            raise ValueError("At least one record_id is required")
        if max_chars_per_record < 1:
            raise ValueError("max_chars_per_record must be at least 1")
        if max_bytes_per_record < 1:
            raise ValueError("max_bytes_per_record must be at least 1")

        wallet = self._wallet(wallet_id)
        if actor_did != wallet.owner_did:
            operation_caveats = self._operation_caveats(
                invocation_caveats,
                output_types=["redacted_graphrag"],
            )
            if grant_id is None:
                raise AccessDeniedError("GraphRAG creation requires a grant")
            grant = self.grants[grant_id]
            for record_id in ordered_record_ids:
                self._assert_grant_allows(
                    grant,
                    wallet_id=wallet_id,
                    audience_did=actor_did,
                    resource=resource_for_record(wallet_id, record_id),
                    ability="record/analyze",
                    invocation_caveats=operation_caveats,
                )

        per_record: List[Dict[str, Any]] = []
        combined_redactions = {label: 0 for label in self.REDACTION_PATTERNS}
        category_record_counts = {category: 0 for category in self.DERIVED_FACT_KEYWORDS}
        entity_type_counts: Dict[str, int] = {}
        extraction_methods: Dict[str, int] = {}
        total_raw_text_chars = 0

        for record_id in ordered_record_ids:
            record = self._record(wallet_id, record_id)
            if record.data_type != "document":
                raise ValueError("Redacted GraphRAG creation requires document records")
            plaintext, metadata = self._decrypt_record_bytes_and_metadata(
                wallet_id,
                record,
                actor_did=actor_did,
                actor_secret=actor_secret,
            )
            extraction = self._extract_document_text_from_bytes(
                plaintext,
                metadata=metadata,
                record_id=record_id,
                max_chars=max_chars_per_record,
                max_bytes=max_bytes_per_record,
                use_ocr=use_ocr,
            )
            method = str(extraction.get("method") or "unknown")
            extraction_methods[method] = extraction_methods.get(method, 0) + 1
            extracted_text = str(extraction.get("text") or "")
            redacted_text, redaction_counts = self._redact_text(extracted_text)
            facts = self._derive_document_facts(redacted_text)
            record_entity_counts = self._extract_graphrag_entity_type_counts(redacted_text)
            total_raw_text_chars += len(extracted_text)
            for label, count in redaction_counts.items():
                combined_redactions[label] = combined_redactions.get(label, 0) + count
            for category in facts["need_categories"]:
                category_record_counts[category] = category_record_counts.get(category, 0) + 1
            for entity_type, count in record_entity_counts.items():
                entity_type_counts[entity_type] = entity_type_counts.get(entity_type, 0) + count
            per_record.append(
                {
                    "record_id": record_id,
                    "derived_facts": facts,
                    "redaction_counts": redaction_counts,
                    "entity_type_counts": record_entity_counts,
                    "extraction_method": method,
                    "raw_text_chars": len(extracted_text),
                }
            )

        graph = self._build_redacted_graphrag_graph(
            per_record,
            category_record_counts=category_record_counts,
            entity_type_counts=entity_type_counts,
            redaction_counts=combined_redactions,
        )
        output = {
            "output_policy": "redacted_graphrag",
            "graph": graph,
            "per_record": per_record,
            "source_record_ids": ordered_record_ids,
            "source_record_count": len(ordered_record_ids),
            "raw_text_chars": total_raw_text_chars,
            "extraction_methods": dict(sorted(extraction_methods.items())),
        }
        artifact_key = random_key()
        encrypted = encrypt_bytes(
            canonical_bytes(output),
            artifact_key,
            {"wallet_id": wallet_id, "record_ids": ordered_record_ids, "kind": "redacted_graphrag"},
        )
        ref = self.storage.put(canonical_bytes(encrypted.to_dict()))
        artifact = DerivedArtifact(
            artifact_id=f"artifact-{uuid.uuid4().hex}",
            wallet_id=wallet_id,
            source_record_ids=ordered_record_ids,
            artifact_type="redacted_document_graphrag",
            output_policy="redacted_graphrag",
            encrypted_payload_ref=ref,
        )
        self.derived_artifacts[artifact.artifact_id] = artifact
        for record_id in ordered_record_ids:
            self.versions[self._record(wallet_id, record_id).current_version_id].derived_artifact_ids.append(
                artifact.artifact_id
            )
        append_audit_event(
            self.audit_events[wallet_id],
            wallet_id=wallet_id,
            actor_did=actor_did,
            action="record/graphrag_redacted",
            resource=",".join(resource_for_record(wallet_id, record_id) for record_id in ordered_record_ids),
            decision="allow",
            details={
                "artifact_id": artifact.artifact_id,
                "artifact_type": artifact.artifact_type,
                "source_record_count": len(ordered_record_ids),
                "node_count": graph["node_count"],
                "edge_count": graph["edge_count"],
            },
            grant_id=grant_id,
        )
        return {"artifact": artifact, "output": output}

    def _derive_vector_profile(self, redacted_text: str, *, chunk_size_words: int) -> Dict[str, Any]:
        words = re.findall(r"[A-Za-z][A-Za-z'-]*|\[REDACTED_[A-Z_]+\]", redacted_text)
        chunks = [
            " ".join(words[index : index + chunk_size_words])
            for index in range(0, len(words), chunk_size_words)
        ]
        lower = redacted_text.lower()
        feature_vector = {
            category: sum(lower.count(keyword) for keyword in keywords)
            for category, keywords in self.DERIVED_FACT_KEYWORDS.items()
        }
        redaction_features = {
            token.lower().strip("[]"): redacted_text.count(token)
            for token in ("[REDACTED_EMAIL]", "[REDACTED_PHONE]", "[REDACTED_SSN]", "[REDACTED_ADDRESS]")
        }
        feature_vector.update(redaction_features)
        return {
            "profile_type": "redacted_lexical_hash_vector",
            "chunk_size_words": chunk_size_words,
            "chunk_count": len(chunks),
            "chunk_hashes": [
                sha256_hex(canonical_bytes(self._chunk_feature_signature(chunk)))
                for chunk in chunks
            ],
            "feature_vector": feature_vector,
            "word_count": len(words),
        }

    def _chunk_feature_signature(self, chunk_text: str) -> Dict[str, Any]:
        lower = chunk_text.lower()
        signature = {
            category: sum(lower.count(keyword) for keyword in keywords)
            for category, keywords in self.DERIVED_FACT_KEYWORDS.items()
        }
        signature.update(
            {
                token.lower().strip("[]"): chunk_text.count(token)
                for token in ("[REDACTED_EMAIL]", "[REDACTED_PHONE]", "[REDACTED_SSN]", "[REDACTED_ADDRESS]")
            }
        )
        return signature

    def _decrypt_record_bytes_and_metadata(
        self,
        wallet_id: str,
        record: DataRecord,
        *,
        actor_did: str,
        actor_secret: Optional[bytes] = None,
    ) -> tuple[bytes, Dict[str, Any]]:
        if actor_secret is not None:
            self.set_principal_secret(actor_did, actor_secret)
        version = self.versions[record.current_version_id]
        dek = self._unwrap_dek(version, wallet_id, actor_did)
        payload_aad = self._payload_aad(wallet_id, record.record_id, version.version_id, record.data_type)
        payload_data = json.loads(self.storage.get(version.encrypted_payload_ref).decode("utf-8"))
        plaintext = decrypt_bytes(EncryptedBlob.from_dict(payload_data), dek, payload_aad)
        metadata: Dict[str, Any] = {}
        if version.encrypted_metadata_ref is not None:
            metadata_data = json.loads(self.storage.get(version.encrypted_metadata_ref).decode("utf-8"))
            metadata_plaintext = decrypt_bytes(
                EncryptedBlob.from_dict(metadata_data),
                dek,
                payload_aad | {"kind": "metadata"},
            )
            metadata = json.loads(metadata_plaintext.decode("utf-8"))
        return plaintext, metadata

    def _extract_document_text_from_bytes(
        self,
        plaintext: bytes,
        *,
        metadata: Dict[str, Any],
        record_id: str,
        max_chars: int,
        max_bytes: int,
        use_ocr: bool,
    ) -> Dict[str, Any]:
        suffix = self._document_suffix_from_metadata(metadata)
        result: Dict[str, Any] = {}
        with tempfile.TemporaryDirectory(prefix="wallet-document-") as temp_dir:
            temp_path = Path(temp_dir) / f"{record_id}{suffix}"
            temp_path.write_bytes(plaintext)
            try:
                from ipfs_datasets_py.processors.multimedia.attachment_text_extractor import (
                    extract_attachment_text,
                )

                result = extract_attachment_text(
                    temp_path,
                    max_chars=max_chars,
                    max_bytes=max_bytes,
                    use_ocr=use_ocr,
                )
            except Exception as exc:  # pragma: no cover - defensive optional dependency path
                result = {
                    "text": "",
                    "method": "extractor-error",
                    "suffix": suffix,
                    "ocr_used": False,
                    "ocr_engine": None,
                    "confidence": 0.0,
                    "error": str(exc),
                }
        if result.get("text") or result.get("method") not in {"unsupported", "missing", "extractor-error"}:
            return result

        fallback_text = plaintext[:max_bytes].decode("utf-8", errors="replace")
        return {
            "text": fallback_text[:max_chars],
            "method": "utf8-fallback",
            "suffix": suffix,
            "ocr_used": False,
            "ocr_engine": None,
            "confidence": 0.0,
            "error": result.get("error"),
        }

    def _analyze_form_from_document_bytes(
        self,
        plaintext: bytes,
        *,
        metadata: Dict[str, Any],
        record_id: str,
        max_fields: int,
        use_ocr: bool,
    ) -> Dict[str, Any]:
        suffix = self._document_suffix_from_metadata(metadata)
        if suffix == ".pdf":
            with tempfile.TemporaryDirectory(prefix="wallet-form-") as temp_dir:
                temp_path = Path(temp_dir) / f"{record_id}.pdf"
                temp_path.write_bytes(plaintext)
                try:
                    return self._analyze_pdf_form_path(temp_path, max_fields=max_fields, use_ocr=use_ocr)
                except Exception as exc:
                    text_result = self._extract_document_text_from_bytes(
                        plaintext,
                        metadata=metadata,
                        record_id=record_id,
                        max_chars=20_000,
                        max_bytes=200_000,
                        use_ocr=use_ocr,
                    )
                    return self._analyze_text_form_fallback(
                        str(text_result.get("text") or ""),
                        method="text-fallback-after-pdf-error",
                        suffix=suffix,
                        max_fields=max_fields,
                        error=str(exc),
                    )

        text_result = self._extract_document_text_from_bytes(
            plaintext,
            metadata=metadata,
            record_id=record_id,
            max_chars=20_000,
            max_bytes=200_000,
            use_ocr=use_ocr,
        )
        return self._analyze_text_form_fallback(
            str(text_result.get("text") or ""),
            method=str(text_result.get("method") or "text-fallback"),
            suffix=suffix,
            max_fields=max_fields,
            error=text_result.get("error"),
        )

    def _analyze_pdf_form_path(self, pdf_path: Path, *, max_fields: int, use_ocr: bool) -> Dict[str, Any]:
        from ipfs_datasets_py.processors.pdf_form_filler import analyze_pdf_form, classify_pdf

        ocr_provider = None
        if use_ocr:
            try:
                from ipfs_datasets_py.processors.pdf_form_filler import build_tesseract_ocr_provider

                ocr_provider = build_tesseract_ocr_provider()
            except Exception:
                ocr_provider = None
        document_type = classify_pdf(pdf_path, ocr_provider=ocr_provider)
        result = analyze_pdf_form(pdf_path, ocr_provider=ocr_provider)
        fields = [self._safe_form_field(field.to_dict()) for field in result.fields[:max_fields]]
        edges = [
            self._safe_form_edge(edge.to_dict())
            for edge in result.dependency_graph.edges[: max_fields * 3]
        ]
        redacted_page_text, redaction_counts = self._redact_text("\n".join(result.page_text))
        data_type_counts = self._field_data_type_counts(fields)
        required_count = sum(1 for field in fields if field["required"])
        return {
            "form": {
                "method": "pdf_form_analyzer",
                "document_type": document_type,
                "page_count": result.metadata.get("page_count", len(result.page_text)),
                "field_count": len(result.fields),
                "returned_field_count": len(fields),
                "required_field_count": required_count,
                "data_type_counts": data_type_counts,
                "dependency_edge_count": len(result.dependency_graph.edges),
                "ocr_requested": use_ocr,
                "ocr_used": ocr_provider is not None,
            },
            "fields": fields,
            "dependency_edges": edges,
            "derived_facts": self._derive_document_facts(redacted_page_text),
            "redaction_counts": redaction_counts,
            "raw_text_chars": len("\n".join(result.page_text)),
        }

    def _analyze_text_form_fallback(
        self,
        text: str,
        *,
        method: str,
        suffix: str,
        max_fields: int,
        error: Optional[str] = None,
    ) -> Dict[str, Any]:
        redacted_text, redaction_counts = self._redact_text(text)
        fields = self._infer_form_fields_from_text(redacted_text, max_fields=max_fields)
        data_type_counts = self._field_data_type_counts(fields)
        return {
            "form": {
                "method": method,
                "document_type": "text_form_or_document",
                "suffix": suffix,
                "page_count": None,
                "field_count": len(fields),
                "returned_field_count": len(fields),
                "required_field_count": sum(1 for field in fields if field["required"]),
                "data_type_counts": data_type_counts,
                "dependency_edge_count": 0,
                "ocr_requested": False,
                "ocr_used": False,
                "error": error,
            },
            "fields": fields,
            "dependency_edges": [],
            "derived_facts": self._derive_document_facts(redacted_text),
            "redaction_counts": redaction_counts,
            "raw_text_chars": len(text),
        }

    def _infer_form_fields_from_text(self, redacted_text: str, *, max_fields: int) -> List[Dict[str, Any]]:
        fields: List[Dict[str, Any]] = []
        seen: set[str] = set()
        for raw_line in redacted_text.splitlines():
            line = " ".join(raw_line.strip().split())
            if not line or len(line) > 160:
                continue
            match = re.match(r"^(.{2,80}?)(?:\s*[:：]\s*|\s+_{2,}\s*|\s+\[[ xX]?\]\s*)", line)
            if not match:
                continue
            label = match.group(1).strip(" -*\t")
            if not label:
                continue
            normalized = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_") or f"field_{len(fields) + 1}"
            if normalized in seen:
                continue
            seen.add(normalized)
            fields.append(
                {
                    "name": normalized[:80],
                    "label": label,
                    "page_index": None,
                    "data_type": self._infer_form_data_type(label),
                    "required": bool(re.search(r"\b(required|must|mandatory)\b|\*", line, re.IGNORECASE)),
                    "max_chars": None,
                    "multiline": False,
                    "options": [],
                    "source": "text-fallback",
                    "confidence": 0.45,
                    "dependencies": [],
                }
            )
            if len(fields) >= max_fields:
                break
        return fields

    @staticmethod
    def _field_data_type_counts(fields: List[Dict[str, Any]]) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for field in fields:
            data_type = str(field.get("data_type") or "string")
            counts[data_type] = counts.get(data_type, 0) + 1
        return dict(sorted(counts.items()))

    def _safe_form_field(self, field: Dict[str, Any]) -> Dict[str, Any]:
        redacted_name, _ = self._redact_text(str(field.get("name") or ""))
        redacted_label, _ = self._redact_text(str(field.get("label") or ""))
        redacted_options = [self._redact_text(str(option))[0] for option in field.get("options") or []]
        redacted_dependencies = [
            self._redact_text(str(dependency))[0] for dependency in field.get("dependencies") or []
        ]
        return {
            "name": redacted_name,
            "label": redacted_label,
            "page_index": field.get("page_index"),
            "data_type": field.get("data_type") or "string",
            "required": bool(field.get("required")),
            "max_chars": field.get("max_chars"),
            "multiline": bool(field.get("multiline")),
            "options": redacted_options,
            "source": field.get("source") or "unknown",
            "confidence": field.get("confidence"),
            "dependencies": redacted_dependencies,
        }

    def _safe_form_edge(self, edge: Dict[str, Any]) -> Dict[str, Any]:
        source, _ = self._redact_text(str(edge.get("source") or ""))
        target, _ = self._redact_text(str(edge.get("target") or ""))
        return {
            "source": source,
            "target": target,
            "relation": edge.get("relation") or "related",
            "required": bool(edge.get("required", True)),
            "confidence": edge.get("confidence"),
        }

    @staticmethod
    def _infer_form_data_type(label: str) -> str:
        lower = label.lower()
        if any(token in lower for token in ("email", "e-mail")):
            return "email"
        if any(token in lower for token in ("phone", "telephone", "mobile")):
            return "phone"
        if any(token in lower for token in ("date", "dob", "birth")):
            return "date"
        if any(token in lower for token in ("ssn", "social security")):
            return "identifier"
        if any(token in lower for token in ("address", "street", "city", "zip")):
            return "address"
        if any(token in lower for token in ("amount", "income", "rent", "cost", "payment")):
            return "currency"
        if any(token in lower for token in ("yes", "no", "check", "agree")):
            return "boolean"
        if "name" in lower:
            return "person_name"
        return "string"

    def _extract_graphrag_entity_type_counts(self, redacted_text: str) -> Dict[str, int]:
        try:
            from ipfs_datasets_py.processors.graphrag_integrator import GraphRAGIntegrator

            entities = GraphRAGIntegrator().extract_entities(redacted_text)
        except Exception:
            entities = []
        counts: Dict[str, int] = {}
        for entity in entities:
            entity_type = str(getattr(entity, "type", "entity") or "entity")
            counts[entity_type] = counts.get(entity_type, 0) + 1
        return dict(sorted(counts.items()))

    def _build_redacted_graphrag_graph(
        self,
        per_record: List[Dict[str, Any]],
        *,
        category_record_counts: Dict[str, int],
        entity_type_counts: Dict[str, int],
        redaction_counts: Dict[str, int],
    ) -> Dict[str, Any]:
        nodes: List[Dict[str, Any]] = []
        edges: List[Dict[str, Any]] = []
        for item in per_record:
            record_node_id = f"record:{item['record_id']}"
            nodes.append(
                {
                    "id": record_node_id,
                    "kind": "record",
                    "record_id": item["record_id"],
                    "raw_text_chars": item["raw_text_chars"],
                    "extraction_method": item["extraction_method"],
                }
            )
            for category in item["derived_facts"]["need_categories"]:
                category_node_id = f"need:{category}"
                edges.append(
                    {
                        "source": record_node_id,
                        "target": category_node_id,
                        "relation": "has_need_category",
                        "weight": 1,
                    }
                )
            for redaction_type, count in item["redaction_counts"].items():
                if count <= 0:
                    continue
                redaction_node_id = f"redaction:{redaction_type}"
                edges.append(
                    {
                        "source": record_node_id,
                        "target": redaction_node_id,
                        "relation": "contains_redaction_type",
                        "weight": count,
                    }
                )
            for entity_type, count in item["entity_type_counts"].items():
                if count <= 0:
                    continue
                entity_node_id = f"entity_type:{entity_type}"
                edges.append(
                    {
                        "source": record_node_id,
                        "target": entity_node_id,
                        "relation": "mentions_entity_type",
                        "weight": count,
                    }
                )

        for category, count in sorted(category_record_counts.items()):
            if count <= 0:
                continue
            nodes.append(
                {
                    "id": f"need:{category}",
                    "kind": "need_category",
                    "label": category,
                    "record_count": count,
                }
            )
        for redaction_type, count in sorted(redaction_counts.items()):
            if count <= 0:
                continue
            nodes.append(
                {
                    "id": f"redaction:{redaction_type}",
                    "kind": "redaction_type",
                    "label": redaction_type,
                    "count": count,
                }
            )
        for entity_type, count in sorted(entity_type_counts.items()):
            if count <= 0:
                continue
            nodes.append(
                {
                    "id": f"entity_type:{entity_type}",
                    "kind": "entity_type",
                    "label": entity_type,
                    "count": count,
                }
            )

        categories = [category for category, count in sorted(category_record_counts.items()) if count > 0]
        for left_index, left in enumerate(categories):
            for right in categories[left_index + 1 :]:
                cooccurrence = sum(
                    1
                    for item in per_record
                    if left in item["derived_facts"]["need_categories"]
                    and right in item["derived_facts"]["need_categories"]
                )
                if cooccurrence <= 0:
                    continue
                edges.append(
                    {
                        "source": f"need:{left}",
                        "target": f"need:{right}",
                        "relation": "co_occurs_with",
                        "weight": cooccurrence,
                    }
                )

        return {
            "graph_type": "redacted_category_entity_graph",
            "nodes": nodes,
            "edges": edges,
            "node_count": len(nodes),
            "edge_count": len(edges),
            "category_record_counts": {
                key: value for key, value in sorted(category_record_counts.items()) if value > 0
            },
            "entity_type_counts": dict(sorted(entity_type_counts.items())),
            "redaction_counts": dict(sorted(redaction_counts.items())),
        }

    @staticmethod
    def _document_suffix_from_metadata(metadata: Dict[str, Any]) -> str:
        filename = str(metadata.get("filename") or metadata.get("name") or "")
        suffix = Path(filename).suffix.lower()
        if suffix and re.fullmatch(r"\.[a-z0-9][a-z0-9+_-]{0,15}", suffix):
            return suffix
        content_type = str(metadata.get("content_type") or metadata.get("mime_type") or "").lower()
        content_type_suffixes = {
            "application/pdf": ".pdf",
            "text/plain": ".txt",
            "text/markdown": ".md",
            "text/csv": ".csv",
            "text/html": ".html",
            "application/json": ".json",
            "image/png": ".png",
            "image/jpeg": ".jpg",
            "image/tiff": ".tif",
        }
        return content_type_suffixes.get(content_type, ".txt")

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
            invocation_caveats=invocation.caveats,
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
        status: str = "approved",
        expires_at: Optional[str] = None,
    ) -> AnalyticsTemplate:
        if template_id in self.analytics_templates:
            raise ValueError(f"Analytics template already exists: {template_id}")
        self._validate_analytics_template_policy(aggregation_policy)
        normalized_status = self._normalize_analytics_template_status(status)
        template = AnalyticsTemplate(
            template_id=template_id,
            title=title,
            purpose=purpose,
            allowed_record_types=list(allowed_record_types),
            allowed_derived_fields=list(allowed_derived_fields),
            aggregation_policy=dict(aggregation_policy),
            created_by=created_by,
            status=normalized_status,
            expires_at=expires_at,
        )
        self.analytics_templates[template_id] = template
        return template

    def list_analytics_templates(self, *, include_inactive: bool = False) -> List[AnalyticsTemplate]:
        templates = sorted(self.analytics_templates.values(), key=lambda item: item.template_id)
        if include_inactive:
            return templates
        return [template for template in templates if self._analytics_template_is_approved(template)]

    def set_analytics_template_status(
        self,
        template_id: str,
        *,
        actor_did: str,
        status: str,
    ) -> AnalyticsTemplate:
        template = self._analytics_template(template_id)
        if actor_did != template.created_by:
            raise AccessDeniedError("Only the template creator can update this analytics template")
        template.status = self._normalize_analytics_template_status(status)
        template.updated_at = utc_now()
        return template

    def retire_analytics_template(self, template_id: str, *, actor_did: str) -> AnalyticsTemplate:
        return self.set_analytics_template_status(template_id, actor_did=actor_did, status="retired")

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
        template = self.analytics_templates.get(template_id)
        if template is not None:
            self._assert_active_analytics_template(template)
        if min_cohort_size is None:
            matching_consents = [
                consent for consent in self.analytics_consents.values() if consent.template_id == template_id
            ]
            policy_sizes = [
                int(consent.aggregation_policy.get("min_cohort_size", 10))
                for consent in matching_consents
            ]
            min_cohort_size = max(policy_sizes) if policy_sizes else 10
            if template is not None:
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

    def run_aggregate_count_by_fields(
        self,
        template_id: str,
        *,
        group_by: List[str],
        min_cohort_size: Optional[int] = None,
        epsilon: Optional[float] = None,
        sensitivity: float = 1.0,
        budget_key: Optional[str] = None,
        budget_limit: Optional[float] = None,
        release_exact_count: Optional[bool] = None,
        actor_did: str = "did:service:analytics",
    ) -> AggregateResult:
        template = self.analytics_templates.get(template_id)
        if template is not None:
            self._assert_active_analytics_template(template)
            self._assert_analytics_group_by_fields(template, group_by)
        if min_cohort_size is None:
            matching_consents = [
                consent for consent in self.analytics_consents.values() if consent.template_id == template_id
            ]
            policy_sizes = [
                int(consent.aggregation_policy.get("min_cohort_size", 10))
                for consent in matching_consents
            ]
            min_cohort_size = max(policy_sizes) if policy_sizes else 10
            if template is not None:
                min_cohort_size = max(
                    min_cohort_size,
                    int(template.aggregation_policy.get("min_cohort_size", 10)),
                )
        spent = None
        if epsilon is not None:
            if epsilon <= 0:
                raise ValueError("epsilon must be greater than zero")
            budget_key = budget_key or f"template:{template_id}:group:{','.join(group_by)}"
            if budget_limit is None:
                budget_limit = self._analytics_budget_limit(template_id)
            spent = self._spend_analytics_privacy_budget(
                budget_key=budget_key,
                epsilon=epsilon,
                budget_limit=budget_limit,
            )
        if release_exact_count is None:
            release_exact_count = epsilon is None
        result = aggregate_count_by_fields(
            template_id=template_id,
            contributions=self.analytics_contributions.values(),
            group_by=list(group_by),
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
            "grant_receipts": [
                receipt.to_dict()
                for receipt in sorted(self.grant_receipts.values(), key=lambda item: item.receipt_id)
                if receipt.wallet_id == wallet_id
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
        grant_receipt_ids = sorted(
            receipt.receipt_id
            for receipt in self.grant_receipts.values()
            if receipt.wallet_id == wallet_id
        )
        return {
            "wallet": wallet.to_dict(),
            "records": [self.records[record_id].to_dict() for record_id in record_ids],
            "versions": [self.versions[version_id].to_dict() for version_id in version_ids],
            "grants": [self.grants[grant_id].to_dict() for grant_id in grant_ids],
            "grant_receipts": [
                self.grant_receipts[receipt_id].to_dict() for receipt_id in grant_receipt_ids
            ],
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

    def export_analytics_ledger(self) -> Dict[str, Any]:
        """Export durable aggregate analytics state shared across wallets."""

        return {
            "ledger_type": "wallet_analytics_ledger_v1",
            "wallet_ids": sorted(self.wallets),
            "analytics_templates": [
                template.to_dict()
                for template in sorted(self.analytics_templates.values(), key=lambda item: item.template_id)
            ],
            "analytics_consents": [
                consent.to_dict()
                for consent in sorted(self.analytics_consents.values(), key=lambda item: item.consent_id)
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
        }

    def import_analytics_ledger(self, ledger: Dict[str, Any]) -> None:
        """Import durable aggregate analytics state."""

        if ledger.get("ledger_type") not in {None, "wallet_analytics_ledger_v1"}:
            raise ValueError("Unsupported analytics ledger type")
        for template_data in ledger.get("analytics_templates", []):
            self.analytics_templates[template_data["template_id"]] = AnalyticsTemplate(**template_data)
        for consent_data in ledger.get("analytics_consents", []):
            self.analytics_consents[consent_data["consent_id"]] = AnalyticsConsent(**consent_data)
        for contribution_data in ledger.get("analytics_contributions", []):
            self.analytics_contributions[contribution_data["contribution_id"]] = AnalyticsContribution(
                **contribution_data
            )
        for result_data in ledger.get("aggregate_results", []):
            self.aggregate_results[result_data["result_id"]] = AggregateResult(**result_data)
        self.analytics_query_budget_spent.update(
            {str(key): float(value) for key, value in ledger.get("analytics_query_budget_spent", {}).items()}
        )

    def create_export_bundle(
        self,
        wallet_id: str,
        *,
        actor_did: str,
        grant_id: Optional[str] = None,
        record_ids: Optional[List[str]] = None,
        include_proofs: bool = True,
        include_derived_artifacts: bool = True,
        invocation_caveats: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Create a bounded encrypted export bundle for a wallet actor.

        This is a sharing/export view, not a plaintext backup. It includes
        encrypted storage references and only key wraps addressed to the actor.
        """

        wallet = self._wallet(wallet_id)
        requested_ids = (
            list(record_ids)
            if record_ids is not None
            else sorted(
                record.record_id
                for record in self.records.values()
                if record.wallet_id == wallet_id and record.status == "active"
            )
        )
        records = [self._record(wallet_id, record_id) for record_id in requested_ids]

        if actor_did != wallet.owner_did:
            operation_caveats = self._operation_caveats(
                invocation_caveats,
                output_types=["encrypted_export_bundle"],
            )
            if grant_id is None:
                raise AccessDeniedError("Non-owner export requires an export/create grant")
            grant = self.grants[grant_id]
            self._assert_export_grant_allows(
                grant,
                wallet_id=wallet_id,
                actor_did=actor_did,
                record_ids=requested_ids,
                invocation_caveats=operation_caveats,
            )
        versions: List[Dict[str, Any]] = []
        for record in records:
            version = self.versions[record.current_version_id]
            version_data = version.to_dict()
            if actor_did != wallet.owner_did:
                version_data["key_wraps"] = [
                    wrap.to_dict()
                    for wrap in version.key_wraps
                    if wrap.recipient_did == actor_did and wrap.status == "active"
                ]
            versions.append(version_data)

        record_id_set = set(requested_ids)
        artifact_ids = sorted(
            artifact.artifact_id
            for artifact in self.derived_artifacts.values()
            if artifact.wallet_id == wallet_id and any(record_id in record_id_set for record_id in artifact.source_record_ids)
        )
        proof_ids = sorted(
            proof.proof_id
            for proof in self.proofs.values()
            if proof.wallet_id == wallet_id and any(record_id in record_id_set for record_id in proof.witness_record_ids)
        )
        bundle = {
            "bundle_type": "wallet_export_v1",
            "wallet": self._export_wallet_descriptor(wallet, actor_did=actor_did),
            "created_at": utc_now(),
            "actor_did": actor_did,
            "grant_id": grant_id,
            "records": [record.to_dict() for record in records],
            "versions": versions,
            "derived_artifacts": (
                [self.derived_artifacts[artifact_id].to_dict() for artifact_id in artifact_ids]
                if include_derived_artifacts
                else []
            ),
            "proofs": (
                [self.proofs[proof_id].to_dict() for proof_id in proof_ids]
                if include_proofs
                else []
            ),
        }
        bundle_hash = self.export_bundle_hash(bundle)
        bundle["bundle_hash"] = bundle_hash
        bundle["bundle_id"] = f"export-{bundle_hash[:24]}"
        append_audit_event(
            self.audit_events[wallet_id],
            wallet_id=wallet_id,
            actor_did=actor_did,
            action="export/create",
            resource=",".join(resource_for_record(wallet_id, record_id) for record_id in requested_ids),
            decision="allow",
            details={
                "record_ids": requested_ids,
                "include_proofs": include_proofs,
                "include_derived_artifacts": include_derived_artifacts,
                "bundle_id": bundle["bundle_id"],
                "bundle_hash": bundle_hash,
            },
            grant_id=grant_id,
        )
        return bundle

    def export_bundle_hash(self, bundle: Dict[str, Any]) -> str:
        """Return the deterministic hash covered by an export bundle receipt."""

        unsigned = dict(bundle)
        unsigned.pop("bundle_hash", None)
        unsigned.pop("bundle_id", None)
        return sha256_hex(canonical_bytes(unsigned))

    def verify_export_bundle(self, bundle: Dict[str, Any]) -> bool:
        """Verify the bundle's embedded hash without trusting JSON key order."""

        expected = bundle.get("bundle_hash")
        return isinstance(expected, str) and self.export_bundle_hash(bundle) == expected

    def import_export_bundle(self, bundle: Dict[str, Any]) -> Dict[str, Any]:
        """Validate and register an encrypted export bundle.

        This imports encrypted descriptors only. It does not grant plaintext
        access and does not assume the referenced encrypted blobs are locally
        available.
        """

        if not self.verify_export_bundle(bundle):
            raise AccessDeniedError("Export bundle hash verification failed")
        self._validate_export_bundle_shape(bundle)
        wallet_data = dict(bundle.get("wallet") or {})
        wallet_id = str(wallet_data.get("wallet_id") or "")
        if not wallet_id:
            raise ValueError("Export bundle wallet_id is required")
        if wallet_id not in self.wallets:
            self.wallets[wallet_id] = Wallet(
                wallet_id=wallet_id,
                owner_did=str(wallet_data.get("owner_did") or "did:unknown:owner"),
                controller_dids=list(wallet_data.get("controller_dids") or [wallet_data.get("owner_did") or "did:unknown:owner"]),
                device_dids=list(wallet_data.get("device_dids") or []),
                default_privacy_policy=dict(wallet_data.get("default_privacy_policy") or {}),
                governance_policy=dict(wallet_data.get("governance_policy") or {}),
                manifest_head=wallet_data.get("manifest_head"),
                created_at=wallet_data.get("created_at", utc_now()),
                updated_at=wallet_data.get("updated_at", utc_now()),
            )
            self.audit_events[wallet_id] = []

        imported_records = 0
        for record_data in bundle.get("records", []):
            self.records[record_data["record_id"]] = DataRecord(**record_data)
            imported_records += 1

        imported_versions = 0
        for version_data in bundle.get("versions", []):
            payload_ref = version_data["encrypted_payload_ref"]
            metadata_ref = version_data.get("encrypted_metadata_ref")
            self.versions[version_data["version_id"]] = DataVersion(
                version_id=version_data["version_id"],
                record_id=version_data["record_id"],
                encrypted_payload_ref=self._storage_ref_from_dict(payload_ref),
                encrypted_metadata_ref=self._storage_ref_from_dict(metadata_ref) if metadata_ref else None,
                ciphertext_hash=version_data["ciphertext_hash"],
                encryption_suite=version_data["encryption_suite"],
                key_wraps=[KeyWrap(**wrap) for wrap in version_data.get("key_wraps", [])],
                derived_artifact_ids=list(version_data.get("derived_artifact_ids", [])),
                proof_receipt_ids=list(version_data.get("proof_receipt_ids", [])),
                created_at=version_data.get("created_at", utc_now()),
            )
            imported_versions += 1

        imported_artifacts = 0
        for artifact_data in bundle.get("derived_artifacts", []):
            self.derived_artifacts[artifact_data["artifact_id"]] = DerivedArtifact(
                artifact_id=artifact_data["artifact_id"],
                wallet_id=artifact_data["wallet_id"],
                source_record_ids=list(artifact_data.get("source_record_ids", [])),
                artifact_type=artifact_data["artifact_type"],
                output_policy=artifact_data["output_policy"],
                encrypted_payload_ref=self._storage_ref_from_dict(artifact_data["encrypted_payload_ref"]),
                created_at=artifact_data.get("created_at", utc_now()),
            )
            imported_artifacts += 1

        imported_proofs = 0
        for proof_data in bundle.get("proofs", []):
            self.proofs[proof_data["proof_id"]] = ProofReceipt(**proof_data)
            imported_proofs += 1

        append_audit_event(
            self.audit_events[wallet_id],
            wallet_id=wallet_id,
            actor_did=str(bundle.get("actor_did") or "did:unknown:export-recipient"),
            action="export/import",
            resource=f"wallet://{wallet_id}/exports/{bundle.get('bundle_id')}",
            decision="allow",
            details={
                "bundle_id": bundle.get("bundle_id"),
                "bundle_hash": bundle.get("bundle_hash"),
                "record_count": imported_records,
                "version_count": imported_versions,
                "proof_count": imported_proofs,
                "derived_artifact_count": imported_artifacts,
            },
        )
        return {
            "wallet_id": wallet_id,
            "bundle_id": bundle.get("bundle_id"),
            "bundle_hash": bundle.get("bundle_hash"),
            "record_count": imported_records,
            "version_count": imported_versions,
            "proof_count": imported_proofs,
            "derived_artifact_count": imported_artifacts,
        }

    def verify_export_bundle_storage(self, bundle: Dict[str, Any]) -> Dict[str, Any]:
        """Verify local availability of encrypted blobs referenced by a bundle."""

        if not self.verify_export_bundle(bundle):
            raise AccessDeniedError("Export bundle hash verification failed")
        self._validate_export_bundle_shape(bundle)
        wallet_id = str((bundle.get("wallet") or {}).get("wallet_id") or "")
        reports = []
        for record_data in bundle.get("records", []):
            record_id = record_data["record_id"]
            if record_id in self.records and self.records[record_id].wallet_id == wallet_id:
                report = self.verify_record_storage(wallet_id, record_id)
                reports.append(report.to_dict())
                continue
            version_data = next(
                version for version in bundle["versions"] if version["record_id"] == record_id
            )
            payload_status = self._check_storage_ref(
                self._storage_ref_from_dict(version_data["encrypted_payload_ref"])
            )
            metadata_ref = version_data.get("encrypted_metadata_ref")
            metadata_status = (
                self._check_storage_ref(self._storage_ref_from_dict(metadata_ref))
                if metadata_ref
                else []
            )
            report = StorageHealthReport(
                wallet_id=wallet_id,
                record_id=record_id,
                version_id=version_data["version_id"],
                payload=payload_status,
                metadata=metadata_status,
            )
            reports.append(report.to_dict())
        return {
            "bundle_id": bundle.get("bundle_id"),
            "bundle_hash": bundle.get("bundle_hash"),
            "wallet_id": wallet_id,
            "ok": all(report["ok"] for report in reports),
            "record_count": len(reports),
            "reports": reports,
        }

    def _validate_export_bundle_shape(self, bundle: Dict[str, Any]) -> None:
        if bundle.get("bundle_type") != "wallet_export_v1":
            raise ValueError("Unsupported export bundle type")
        if not isinstance(bundle.get("wallet"), dict):
            raise ValueError("Export bundle wallet descriptor is required")
        for key in ("records", "versions", "proofs", "derived_artifacts"):
            if not isinstance(bundle.get(key), list):
                raise ValueError(f"Export bundle {key} must be a list")
        record_ids = {
            str(record.get("record_id"))
            for record in bundle["records"]
            if isinstance(record, dict) and record.get("record_id")
        }
        version_record_ids = {
            str(version.get("record_id"))
            for version in bundle["versions"]
            if isinstance(version, dict) and version.get("record_id")
        }
        if not record_ids:
            raise ValueError("Export bundle must contain at least one record")
        if not version_record_ids:
            raise ValueError("Export bundle must contain at least one version")
        if not version_record_ids.issubset(record_ids):
            raise ValueError("Export bundle versions reference records outside the bundle")

    def _export_wallet_descriptor(self, wallet: Wallet, *, actor_did: str) -> Dict[str, Any]:
        if actor_did == wallet.owner_did:
            return wallet.to_dict()
        return {
            "wallet_id": wallet.wallet_id,
            "owner_did": wallet.owner_did,
            "manifest_head": wallet.manifest_head,
            "created_at": wallet.created_at,
            "updated_at": wallet.updated_at,
        }

    def create_export_bundle_with_invocation(
        self,
        wallet_id: str,
        *,
        actor_did: str,
        invocation: WalletInvocation,
        actor_secret: Optional[bytes] = None,
        record_ids: Optional[List[str]] = None,
        include_proofs: bool = True,
        include_derived_artifacts: bool = True,
    ) -> Dict[str, Any]:
        self.verify_invocation(
            wallet_id,
            invocation,
            actor_did=actor_did,
            resource=resource_for_export(wallet_id),
            ability="export/create",
            actor_secret=actor_secret,
        )
        if record_ids is not None and invocation.caveats.get("record_ids") is not None:
            allowed = set(str(record_id) for record_id in invocation.caveats["record_ids"])
            requested = set(record_ids)
            if not requested.issubset(allowed):
                raise AccessDeniedError("Export invocation does not cover all requested records")
        return self.create_export_bundle(
            wallet_id,
            actor_did=actor_did,
            grant_id=invocation.grant_id,
            record_ids=record_ids,
            include_proofs=include_proofs,
            include_derived_artifacts=include_derived_artifacts,
            invocation_caveats=invocation.caveats,
        )

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
        for receipt_data in snapshot.get("grant_receipts", []):
            self.grant_receipts[receipt_data["receipt_id"]] = GrantReceipt(**receipt_data)
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
        self.import_analytics_ledger(snapshot)
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

        report = self._record_storage_report(wallet_id, record_id, include_metadata=include_metadata)
        append_audit_event(
            self.audit_events[wallet_id],
            wallet_id=wallet_id,
            actor_did=self._wallet(wallet_id).owner_did,
            action="storage/verify",
            resource=resource_for_record(wallet_id, record_id),
            decision="allow",
            details={
                "version_id": report.version_id,
                "ok": report.ok,
                "payload_replicas": len(report.payload),
                "metadata_replicas": len(report.metadata),
            },
        )
        return report

    def verify_wallet_storage(
        self,
        wallet_id: str,
        *,
        include_metadata: bool = True,
    ) -> WalletStorageHealthReport:
        """Verify encrypted payload and metadata replicas for every wallet record."""

        wallet = self._wallet(wallet_id)
        record_ids = sorted(
            record.record_id for record in self.records.values() if record.wallet_id == wallet_id
        )
        report = WalletStorageHealthReport(
            wallet_id=wallet_id,
            record_count=len(record_ids),
            reports=[
                self._record_storage_report(wallet_id, record_id, include_metadata=include_metadata)
                for record_id in record_ids
            ],
        )
        append_audit_event(
            self.audit_events[wallet_id],
            wallet_id=wallet_id,
            actor_did=wallet.owner_did,
            action="storage/verify_wallet",
            resource=resource_for_wallet(wallet_id),
            decision="allow" if report.ok else "warn",
            details={
                "record_count": report.record_count,
                "replica_count": report.replica_count,
                "failed_replica_count": report.failed_replica_count,
                "storage_types": report.storage_types,
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
        report = self._record_storage_repair_report(wallet_id, record_id, include_metadata=include_metadata)
        self._touch_wallet(wallet)
        append_audit_event(
            self.audit_events[wallet_id],
            wallet_id=wallet_id,
            actor_did=actor_did,
            action="storage/repair",
            resource=resource_for_record(wallet_id, record_id),
            decision="allow",
            details={
                "version_id": report.version_id,
                "ok": report.ok,
                "payload_repaired": any(status.repaired for status in report.payload),
                "metadata_repaired": any(status.repaired for status in report.metadata),
            },
        )
        return report

    def repair_wallet_storage(
        self,
        wallet_id: str,
        *,
        actor_did: str,
        include_metadata: bool = True,
    ) -> WalletStorageHealthReport:
        """Repair encrypted payload and metadata mirrors for every wallet record."""

        wallet = self._wallet(wallet_id)
        self._assert_controller(wallet, actor_did)
        record_ids = sorted(
            record.record_id for record in self.records.values() if record.wallet_id == wallet_id
        )
        report = WalletStorageHealthReport(
            wallet_id=wallet_id,
            record_count=len(record_ids),
            reports=[
                self._record_storage_repair_report(wallet_id, record_id, include_metadata=include_metadata)
                for record_id in record_ids
            ],
        )
        self._touch_wallet(wallet)
        append_audit_event(
            self.audit_events[wallet_id],
            wallet_id=wallet_id,
            actor_did=actor_did,
            action="storage/repair_wallet",
            resource=resource_for_wallet(wallet_id),
            decision="allow" if report.ok else "partial",
            details={
                "record_count": report.record_count,
                "replica_count": report.replica_count,
                "failed_replica_count": report.failed_replica_count,
                "repaired_replica_count": report.repaired_replica_count,
                "storage_types": report.storage_types,
            },
        )
        return report

    def _record_storage_report(
        self,
        wallet_id: str,
        record_id: str,
        *,
        include_metadata: bool = True,
    ) -> StorageHealthReport:
        record = self._record(wallet_id, record_id)
        version = self.versions[record.current_version_id]
        return StorageHealthReport(
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

    def _record_storage_repair_report(
        self,
        wallet_id: str,
        record_id: str,
        *,
        include_metadata: bool = True,
    ) -> StorageHealthReport:
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

    def _create_grant_receipt(self, wallet_id: str, grant: Grant) -> GrantReceipt:
        access_request_id = str(grant.caveats.get("access_request_id") or "") or None
        approval_id = str(
            grant.caveats.get("approval_id") or grant.caveats.get("approval_ref") or ""
        ) or None
        payload = {
            "wallet_id": wallet_id,
            "grant_id": grant.grant_id,
            "issuer_did": grant.issuer_did,
            "audience_did": grant.audience_did,
            "resources": list(grant.resources),
            "abilities": list(grant.abilities),
            "purpose": grant.caveats.get("purpose"),
            "caveats": dict(grant.caveats),
            "expires_at": grant.expires_at,
            "approval_id": approval_id,
            "access_request_id": access_request_id,
        }
        receipt = GrantReceipt(
            receipt_id=f"receipt-{uuid.uuid4().hex}",
            wallet_id=wallet_id,
            grant_id=grant.grant_id,
            issuer_did=grant.issuer_did,
            audience_did=grant.audience_did,
            resources=list(grant.resources),
            abilities=list(grant.abilities),
            purpose=grant.caveats.get("purpose"),
            caveats=dict(grant.caveats),
            expires_at=grant.expires_at,
            approval_id=approval_id,
            access_request_id=access_request_id,
            receipt_hash=sha256_hex(canonical_bytes(payload)),
        )
        self.grant_receipts[receipt.receipt_id] = receipt
        return receipt

    def _delegation_parent_grant(
        self,
        *,
        wallet_id: str,
        parent_grant_id: str,
        issuer_did: str,
        resources: List[str],
        abilities: List[str],
        caveats: Dict[str, Any],
        expires_at: Optional[str],
    ) -> Grant:
        if parent_grant_id not in self.grants:
            raise MissingRecordError(f"Parent grant not found: {parent_grant_id}")
        parent = self.grants[parent_grant_id]
        if parent.status != "active":
            raise AccessDeniedError(f"Parent grant is not active: {parent_grant_id}")
        if is_expired(parent.expires_at):
            raise AccessDeniedError(f"Parent grant has expired: {parent_grant_id}")
        self._assert_grant_chain_active(wallet_id, parent)
        if parent.audience_did != issuer_did:
            raise AccessDeniedError("Delegating issuer must be the parent grant audience")
        self._assert_delegation_depth(parent)
        if not self._grant_has_ability(parent, "record/share") and not self._grant_has_ability(parent, "document/share"):
            raise AccessDeniedError("Parent grant does not allow re-delegation")
        if not all(self._grant_covers_resource(parent, resource) for resource in resources):
            raise AccessDeniedError("Delegated resources exceed parent grant")
        for ability in abilities:
            if not self._grant_has_ability(parent, ability):
                raise AccessDeniedError(f"Delegated ability exceeds parent grant: {ability}")
        self._assert_delegation_caveats(parent, caveats)
        self._assert_delegation_expiry(parent, expires_at)
        return parent

    def _wallet_grant_ids_for_revocation(self, wallet_id: str) -> List[str]:
        seed_ids = {
            grant_id
            for grant_id, grant in self.grants.items()
            if grant.status == "active" and self._grant_references_wallet(wallet_id, grant)
        }
        revoked_ids = set(seed_ids)
        changed = True
        while changed:
            changed = False
            for grant_id, grant in self.grants.items():
                if grant.status != "active" or grant_id in revoked_ids:
                    continue
                if any(parent_id in revoked_ids for parent_id in grant.proof_chain):
                    revoked_ids.add(grant_id)
                    changed = True
        return sorted(
            revoked_ids,
            key=lambda grant_id: (
                self.grants[grant_id].created_at,
                len(self.grants[grant_id].proof_chain),
                grant_id,
            ),
        )

    @staticmethod
    def _grant_references_wallet(wallet_id: str, grant: Grant) -> bool:
        prefix = f"wallet://{wallet_id}"
        return "*" in grant.resources or any(str(resource).startswith(prefix) for resource in grant.resources)

    def _assert_grant_allows(
        self,
        grant: Grant,
        *,
        wallet_id: str,
        audience_did: str,
        resource: str,
        ability: str,
        invocation_caveats: Optional[Dict[str, Any]] = None,
    ) -> None:
        record_id = record_id_from_resource(resource)
        data_type = None
        if record_id in self.records and self.records[record_id].wallet_id == wallet_id:
            data_type = self.records[record_id].data_type
        assert_grant_allows(
            grant,
            audience_did=audience_did,
            resource=resource,
            ability=ability,
            invocation_caveats=invocation_caveats,
            record_id=record_id,
            data_type=data_type,
        )
        self._assert_grant_chain_active(wallet_id, grant)

    @staticmethod
    def _operation_caveats(
        invocation_caveats: Optional[Dict[str, Any]],
        **defaults: Any,
    ) -> Dict[str, Any]:
        caveats = dict(invocation_caveats or {})
        for key, value in defaults.items():
            caveats.setdefault(key, value)
        return caveats

    def _assert_grant_chain_active(self, wallet_id: str, grant: Grant) -> None:
        chain: List[Grant] = []
        for parent_grant_id in grant.proof_chain:
            parent = self.grants.get(parent_grant_id)
            if parent is None:
                raise AccessDeniedError(f"Delegation proof is missing parent grant: {parent_grant_id}")
            chain.append(parent)
        chain.append(grant)

        previous: Optional[Grant] = None
        for current in chain:
            if current.status != "active":
                raise AccessDeniedError(f"Delegation grant is not active: {current.grant_id}")
            if is_expired(current.expires_at):
                raise AccessDeniedError(f"Delegation grant has expired: {current.grant_id}")
            if "*" not in current.resources and not any(
                str(resource).startswith(f"wallet://{wallet_id}") for resource in current.resources
            ):
                raise AccessDeniedError("Delegation proof references a different wallet")
            if previous is not None:
                self._assert_delegated_child_grant(previous, current)
            previous = current

    def _assert_delegated_child_grant(self, parent: Grant, child: Grant) -> None:
        if parent.audience_did != child.issuer_did:
            raise AccessDeniedError("Delegated grant issuer must be the parent grant audience")
        self._assert_delegation_depth(parent)
        if not self._grant_has_ability(parent, "record/share") and not self._grant_has_ability(parent, "document/share"):
            raise AccessDeniedError("Parent grant does not allow re-delegation")
        if not all(self._grant_covers_resource(parent, resource) for resource in child.resources):
            raise AccessDeniedError("Delegated resources exceed parent grant")
        for ability in child.abilities:
            if not self._grant_has_ability(parent, ability):
                raise AccessDeniedError(f"Delegated ability exceeds parent grant: {ability}")
        self._assert_delegation_caveats(parent, child.caveats)
        self._assert_delegation_expiry(parent, child.expires_at)

    @staticmethod
    def _grant_has_ability(grant: Grant, ability: str) -> bool:
        return "*" in grant.abilities or ability in grant.abilities

    @staticmethod
    def _grant_covers_resource(grant: Grant, resource: str) -> bool:
        for candidate in grant.resources:
            if candidate == "*" or candidate == resource:
                return True
            if candidate.endswith("/*") and resource.startswith(candidate[:-1]):
                return True
        return False

    def _assert_delegation_depth(self, parent: Grant) -> None:
        max_depth = int(parent.caveats.get("max_delegation_depth", 1))
        child_depth = len(parent.proof_chain) + 1
        if child_depth > max_depth:
            raise AccessDeniedError("Delegation depth exceeds parent grant policy")

    def _assert_delegation_caveats(self, parent: Grant, caveats: Dict[str, Any]) -> None:
        parent_purpose = parent.caveats.get("purpose")
        if parent_purpose is not None and caveats.get("purpose") != parent_purpose:
            raise AccessDeniedError("Delegated grant purpose must match parent grant")
        parent_record_ids = parent.caveats.get("record_ids")
        child_record_ids = caveats.get("record_ids")
        if parent_record_ids is not None and child_record_ids is None:
            raise AccessDeniedError("Delegated grant must preserve parent record_ids caveat")
        if parent_record_ids is not None and child_record_ids is not None:
            allowed = set(str(record_id) for record_id in parent_record_ids)
            requested = set(str(record_id) for record_id in child_record_ids)
            if not requested.issubset(allowed):
                raise AccessDeniedError("Delegated record_ids exceed parent grant")
        self._assert_delegated_subset_caveat(parent, caveats, "data_types")
        self._assert_delegated_subset_caveat(parent, caveats, "output_types")
        if parent.caveats.get("user_presence_required") is True and caveats.get("user_presence_required") is not True:
            raise AccessDeniedError("Delegated grant must preserve parent user_presence_required caveat")
        if parent.caveats.get("require_user_presence") is True and caveats.get("require_user_presence") is not True:
            raise AccessDeniedError("Delegated grant must preserve parent require_user_presence caveat")
        if "max_delegation_depth" in caveats:
            parent_depth = int(parent.caveats.get("max_delegation_depth", 1))
            child_depth = int(caveats["max_delegation_depth"])
            if child_depth > parent_depth:
                raise AccessDeniedError("Delegated max_delegation_depth exceeds parent grant")

    @staticmethod
    def _assert_delegated_subset_caveat(parent: Grant, caveats: Dict[str, Any], key: str) -> None:
        parent_values = parent.caveats.get(key)
        if parent_values is None:
            return
        child_values = caveats.get(key)
        if child_values is None:
            raise AccessDeniedError(f"Delegated grant must preserve parent {key} caveat")
        parent_set = {str(value) for value in parent_values} if not isinstance(parent_values, str) else {parent_values}
        child_set = {str(value) for value in child_values} if not isinstance(child_values, str) else {child_values}
        if not child_set.issubset(parent_set):
            raise AccessDeniedError(f"Delegated {key} exceed parent grant")

    def _assert_delegation_expiry(self, parent: Grant, expires_at: Optional[str]) -> None:
        if parent.expires_at is None:
            return
        if expires_at is None:
            raise AccessDeniedError("Delegated grant must not outlive parent grant")
        if datetime.fromisoformat(expires_at) > datetime.fromisoformat(parent.expires_at):
            raise AccessDeniedError("Delegated grant must not outlive parent grant")

    def _matching_approval(
        self,
        wallet_id: str,
        *,
        resources: List[str],
        abilities: List[str],
        operation: str,
    ) -> Optional[ApprovalRequest]:
        matches = [
            approval
            for approval in self.approval_requests.values()
            if approval.wallet_id == wallet_id
            and approval.operation == operation
            and set(approval.resources) == set(resources)
            and set(approval.abilities) == set(abilities)
        ]
        return sorted(matches, key=lambda item: item.created_at)[-1] if matches else None

    def _analytics_consent(self, wallet_id: str, consent_id: str) -> AnalyticsConsent:
        if consent_id not in self.analytics_consents or self.analytics_consents[consent_id].wallet_id != wallet_id:
            raise MissingRecordError(f"Analytics consent not found: {consent_id}")
        return self.analytics_consents[consent_id]

    def _assert_export_grant_allows(
        self,
        grant: Grant,
        *,
        wallet_id: str,
        actor_did: str,
        record_ids: List[str],
        invocation_caveats: Optional[Dict[str, Any]] = None,
    ) -> None:
        export_resource = resource_for_export(wallet_id)
        if self._grant_has_ability(grant, "export/create") and self._grant_covers_resource(grant, export_resource):
            self._assert_grant_allows(
                grant,
                wallet_id=wallet_id,
                audience_did=actor_did,
                resource=export_resource,
                ability="export/create",
                invocation_caveats=invocation_caveats,
            )
            allowed_record_ids = grant.caveats.get("record_ids")
            if allowed_record_ids is None:
                return
            allowed = set(str(record_id) for record_id in allowed_record_ids)
            requested = set(record_ids)
            if not requested.issubset(allowed):
                raise AccessDeniedError("Export grant does not cover all requested records")
            return
        for record_id in record_ids:
            self._assert_grant_allows(
                grant,
                wallet_id=wallet_id,
                audience_did=actor_did,
                resource=resource_for_record(wallet_id, record_id),
                ability="export/create",
                invocation_caveats=invocation_caveats,
            )

    def _analytics_template(self, template_id: str) -> AnalyticsTemplate:
        if template_id not in self.analytics_templates:
            raise MissingRecordError(f"Analytics template not found: {template_id}")
        return self.analytics_templates[template_id]

    def _assert_active_analytics_template(self, template: AnalyticsTemplate) -> None:
        if not self._analytics_template_is_approved(template):
            raise AccessDeniedError(f"Analytics template {template.template_id} is not active")
        if template.expires_at is not None:
            from .ucan import is_expired

            if is_expired(template.expires_at):
                raise AccessDeniedError(f"Analytics template {template.template_id} has expired")

    def _assert_analytics_group_by_fields(self, template: AnalyticsTemplate, group_by: List[str]) -> None:
        if not group_by:
            raise ValueError("group_by must include at least one field")
        if len(set(group_by)) != len(group_by):
            raise ValueError("group_by fields must be unique")
        disallowed = set(group_by) - set(template.allowed_derived_fields)
        if disallowed:
            raise AccessDeniedError(f"Analytics group_by fields exceed template policy: {sorted(disallowed)}")

    @staticmethod
    def _analytics_template_is_approved(template: AnalyticsTemplate) -> bool:
        return template.status in {"approved", "active"}

    @staticmethod
    def _normalize_analytics_template_status(status: str) -> str:
        normalized = status.lower()
        if normalized == "active":
            return "approved"
        if normalized not in {"draft", "approved", "paused", "retired"}:
            raise ValueError("analytics template status must be draft, approved, paused, or retired")
        return normalized

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
                    "group_by": list(result.group_by),
                    "released_cohort_count": len(result.cohorts),
                    "suppressed_cohort_count": result.suppressed_cohort_count,
                    "privacy_notes": list(result.privacy_notes),
                },
            )

    def _is_wallet_controller(self, wallet: Wallet, actor_did: str) -> bool:
        return actor_did in wallet.controller_dids or actor_did == wallet.owner_did

    def _assert_controller(self, wallet: Wallet, actor_did: str) -> None:
        if not self._is_wallet_controller(wallet, actor_did):
            raise AccessDeniedError(f"{actor_did} is not a wallet controller")

    def _unique_dids(self, dids: List[str], *, field_name: str) -> List[str]:
        unique: List[str] = []
        for did in dids:
            normalized = str(did).strip()
            if not normalized:
                raise ValueError(f"{field_name} cannot contain empty DID values")
            if normalized not in unique:
                unique.append(normalized)
        return unique

    def _active_recovery_policy(self, wallet: Wallet) -> Dict[str, Any]:
        policy = dict(wallet.governance_policy.get("recovery_policy") or {})
        contact_dids = self._unique_dids(list(policy.get("contact_dids") or []), field_name="contact_dids")
        threshold = int(policy.get("threshold") or 0)
        if policy.get("status") != "active" or not contact_dids or threshold < 1:
            raise AccessDeniedError("Wallet recovery policy is not active")
        if threshold > len(contact_dids):
            raise AccessDeniedError("Wallet recovery policy threshold exceeds contact count")
        return {
            "contact_dids": contact_dids,
            "threshold": threshold,
            "status": "active",
        }

    def _create_recovery_approval_request(
        self,
        wallet: Wallet,
        *,
        requested_by: str,
        operation: str,
        resources: List[str],
        abilities: List[str],
        details: Optional[Dict[str, Any]] = None,
        expires_at: Optional[str] = None,
    ) -> ApprovalRequest:
        recovery_policy = self._active_recovery_policy(wallet)
        contact_dids = list(recovery_policy["contact_dids"])
        if requested_by not in set(contact_dids):
            raise AccessDeniedError(f"{requested_by} is not a wallet recovery contact")
        if set(resources) != {resource_for_wallet(wallet.wallet_id)} or set(abilities) != {"wallet/admin"}:
            raise AccessDeniedError("Recovery approval must target wallet/admin for this wallet")
        return ApprovalRequest(
            approval_id=f"approval-{uuid.uuid4().hex}",
            wallet_id=wallet.wallet_id,
            operation=operation,
            requested_by=requested_by,
            resources=list(resources),
            abilities=list(abilities),
            threshold=int(recovery_policy["threshold"]),
            approver_dids=contact_dids,
            details={
                **(details or {}),
                "approval_scope": "wallet_recovery",
            },
            expires_at=expires_at,
        )

    def _touch_wallet(self, wallet: Wallet) -> None:
        wallet.updated_at = utc_now()
        wallet.manifest_head = sha256_hex(canonical_bytes(self.get_wallet_manifest(wallet.wallet_id)))

    def _verify_wallet_admin_approval(
        self,
        wallet: Wallet,
        *,
        actor_did: str,
        operation: str,
        approval_id: Optional[str],
    ) -> None:
        resources = [resource_for_wallet(wallet.wallet_id)]
        abilities = ["wallet/admin"]
        if operation_requires_approval(
            wallet,
            operation=operation,
            resources=resources,
            abilities=abilities,
        ):
            verify_approval(
                self.approval_requests,
                approval_id=approval_id,
                operation=operation,
                requested_by=actor_did,
                resources=resources,
                abilities=abilities,
            )

    def _sync_governance_policy_controllers(self, wallet: Wallet) -> None:
        policy = dict(wallet.governance_policy)
        current_approvers = list(policy.get("approver_dids") or wallet.controller_dids)
        approvers = [
            did for did in wallet.controller_dids if did in set(current_approvers) or did == wallet.owner_did
        ]
        for did in wallet.controller_dids:
            if did not in approvers:
                approvers.append(did)
        policy["approver_dids"] = approvers
        wallet.governance_policy = normalize_governance_policy(
            controller_dids=wallet.controller_dids,
            governance_policy=policy,
        )

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
        record_ids: set[str] = set()
        caveat_record_ids = grant.caveats.get("record_ids") or grant.caveats.get("allowed_record_ids")
        for resource in grant.resources:
            record_id = self._record_id_from_resource(wallet_id, resource)
            if record_id is not None:
                record_ids.add(record_id)
                continue
            if resource == f"wallet://{wallet_id}/records/*":
                if caveat_record_ids is not None:
                    record_ids.update(str(record_id) for record_id in caveat_record_ids)
                else:
                    record_ids.update(
                        record.record_id for record in self.records.values() if record.wallet_id == wallet_id
                    )
        for record_id in sorted(record_ids):
            record = self._record(wallet_id, record_id)
            record_resource = resource_for_record(wallet_id, record_id)
            if not self._grant_has_wrappable_record_ability(grant, audience_did, record_resource, record):
                continue
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

    def _grant_has_wrappable_record_ability(
        self,
        grant: Grant,
        audience_did: str,
        resource: str,
        record: DataRecord,
    ) -> bool:
        for ability in ("record/decrypt", "record/analyze"):
            if not self._grant_has_ability(grant, ability):
                continue
            if grant.audience_did != audience_did or not self._grant_covers_resource(grant, resource):
                continue
            allowed_record_ids = grant.caveats.get("record_ids") or grant.caveats.get("allowed_record_ids")
            if allowed_record_ids is not None and record.record_id not in {str(item) for item in allowed_record_ids}:
                continue
            allowed_data_types = grant.caveats.get("data_types") or grant.caveats.get("allowed_data_types")
            if allowed_data_types is not None and record.data_type not in {str(item) for item in allowed_data_types}:
                continue
            return True
        return False

    def _active_key_wrap_grant_id(self, version: DataVersion, recipient_did: str) -> Optional[str]:
        for key_wrap in version.key_wraps:
            if (
                key_wrap.recipient_did == recipient_did
                and self._key_wrap_is_active_authorized(key_wrap)
            ):
                return key_wrap.grant_id
        return None

    def _key_wrap_is_active_authorized(self, key_wrap: KeyWrap) -> bool:
        if key_wrap.status != "active":
            return False
        if key_wrap.grant_id is None:
            return True
        grant = self.grants.get(key_wrap.grant_id)
        if grant is None or grant.status != "active":
            return False
        try:
            self._assert_grant_chain_active(self.records[key_wrap.record_id].wallet_id, grant)
        except AccessDeniedError:
            return False
        return True

    def _record_id_from_resource(self, wallet_id: str, resource: str) -> Optional[str]:
        prefix = f"wallet://{wallet_id}/records/"
        if not resource.startswith(prefix):
            return None
        suffix = resource[len(prefix) :]
        if "/" in suffix or not suffix or suffix == "*":
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
