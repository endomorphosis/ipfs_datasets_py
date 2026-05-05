"""Dataclasses for wallet state, grants, proofs, and audit records."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class StorageRef:
    """Reference to encrypted bytes in a storage backend."""

    uri: str
    storage_type: str
    size_bytes: int
    sha256: str
    mirrors: List["StorageRef"] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["mirrors"] = [mirror.to_dict() for mirror in self.mirrors]
        return data


@dataclass
class StorageReplicaStatus:
    """Integrity status for one encrypted storage replica."""

    uri: str
    storage_type: str
    role: str
    ok: bool
    size_bytes: Optional[int] = None
    sha256: Optional[str] = None
    error: Optional[str] = None
    repaired: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class StorageHealthReport:
    """Integrity report for encrypted payload and metadata replicas."""

    wallet_id: str
    record_id: str
    version_id: str
    payload: List[StorageReplicaStatus] = field(default_factory=list)
    metadata: List[StorageReplicaStatus] = field(default_factory=list)
    repaired: bool = False
    created_at: str = field(default_factory=utc_now)

    @property
    def ok(self) -> bool:
        statuses = [*self.payload, *self.metadata]
        return bool(statuses) and all(status.ok for status in statuses)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "wallet_id": self.wallet_id,
            "record_id": self.record_id,
            "version_id": self.version_id,
            "payload": [status.to_dict() for status in self.payload],
            "metadata": [status.to_dict() for status in self.metadata],
            "ok": self.ok,
            "repaired": self.repaired,
            "created_at": self.created_at,
        }


@dataclass
class WalletStorageHealthReport:
    """Integrity summary for every encrypted record in a wallet."""

    wallet_id: str
    record_count: int
    reports: List[StorageHealthReport] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now)

    @property
    def ok(self) -> bool:
        return all(report.ok for report in self.reports)

    @property
    def replica_count(self) -> int:
        return sum(len(report.payload) + len(report.metadata) for report in self.reports)

    @property
    def failed_replica_count(self) -> int:
        return sum(
            1
            for report in self.reports
            for status in [*report.payload, *report.metadata]
            if not status.ok
        )

    @property
    def repaired(self) -> bool:
        return any(report.repaired for report in self.reports)

    @property
    def repaired_replica_count(self) -> int:
        return sum(
            1
            for report in self.reports
            for status in [*report.payload, *report.metadata]
            if status.repaired
        )

    @property
    def storage_types(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for report in self.reports:
            for status in [*report.payload, *report.metadata]:
                counts[status.storage_type] = counts.get(status.storage_type, 0) + 1
        return dict(sorted(counts.items()))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "wallet_id": self.wallet_id,
            "record_count": self.record_count,
            "reports": [report.to_dict() for report in self.reports],
            "ok": self.ok,
            "replica_count": self.replica_count,
            "failed_replica_count": self.failed_replica_count,
            "repaired": self.repaired,
            "repaired_replica_count": self.repaired_replica_count,
            "storage_types": self.storage_types,
            "created_at": self.created_at,
        }


@dataclass
class KeyWrap:
    """A document/data encryption key wrapped to a recipient principal."""

    wrap_id: str
    record_id: str
    version_id: str
    recipient_did: str
    wrapped_dek: str
    wrap_algorithm: str
    grant_id: Optional[str] = None
    created_at: str = field(default_factory=utc_now)
    expires_at: Optional[str] = None
    status: str = "active"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DataVersion:
    """Immutable encrypted version of one wallet data record."""

    version_id: str
    record_id: str
    encrypted_payload_ref: StorageRef
    encrypted_metadata_ref: Optional[StorageRef]
    ciphertext_hash: str
    encryption_suite: str
    key_wraps: List[KeyWrap] = field(default_factory=list)
    derived_artifact_ids: List[str] = field(default_factory=list)
    proof_receipt_ids: List[str] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["encrypted_payload_ref"] = self.encrypted_payload_ref.to_dict()
        data["encrypted_metadata_ref"] = (
            self.encrypted_metadata_ref.to_dict() if self.encrypted_metadata_ref else None
        )
        data["key_wraps"] = [wrap.to_dict() for wrap in self.key_wraps]
        return data


@dataclass
class DataRecord:
    """A typed wallet record such as a document, location, or profile fact."""

    record_id: str
    wallet_id: str
    data_type: str
    sensitivity: str
    public_descriptor: str
    current_version_id: str
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    status: str = "active"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Wallet:
    """Wallet authority and high-level state."""

    wallet_id: str
    owner_did: str
    controller_dids: List[str]
    device_dids: List[str]
    default_privacy_policy: Dict[str, Any] = field(default_factory=dict)
    governance_policy: Dict[str, Any] = field(default_factory=dict)
    manifest_head: Optional[str] = None
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Grant:
    """UCAN-style wallet grant with capabilities and caveats."""

    grant_id: str
    issuer_did: str
    audience_did: str
    resources: List[str]
    abilities: List[str]
    caveats: Dict[str, Any] = field(default_factory=dict)
    proof_chain: List[str] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now)
    expires_at: Optional[str] = None
    status: str = "active"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class WalletInvocation:
    """Signed UCAN-style invocation of one grant capability."""

    invocation_id: str
    grant_id: str
    audience_did: str
    resource: str
    ability: str
    caveats: Dict[str, Any] = field(default_factory=dict)
    issued_at: str = field(default_factory=utc_now)
    expires_at: Optional[str] = None
    nonce: str = ""
    signature: str = ""
    issuer_did: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class GrantReceipt:
    """Durable, owner-facing receipt for a wallet sharing grant."""

    receipt_id: str
    wallet_id: str
    grant_id: str
    issuer_did: str
    audience_did: str
    resources: List[str]
    abilities: List[str]
    purpose: Optional[str]
    caveats: Dict[str, Any]
    receipt_hash: str
    created_at: str = field(default_factory=utc_now)
    expires_at: Optional[str] = None
    status: str = "active"
    approval_id: Optional[str] = None
    access_request_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ApprovalRequest:
    """Threshold approval request for sensitive wallet operations."""

    approval_id: str
    wallet_id: str
    operation: str
    requested_by: str
    resources: List[str]
    abilities: List[str]
    threshold: int
    approver_dids: List[str]
    approvals: Dict[str, str] = field(default_factory=dict)
    status: str = "pending"
    created_at: str = field(default_factory=utc_now)
    expires_at: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)

    @property
    def approved_count(self) -> int:
        approvers = set(self.approver_dids)
        return len([did for did in self.approvals if did in approvers])

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AccessRequest:
    """Delegate-originated request for wallet data access."""

    request_id: str
    wallet_id: str
    requester_did: str
    audience_did: str
    resources: List[str]
    abilities: List[str]
    purpose: str
    status: str = "pending"
    created_at: str = field(default_factory=utc_now)
    expires_at: Optional[str] = None
    decided_at: Optional[str] = None
    decided_by: Optional[str] = None
    grant_id: Optional[str] = None
    invocation_id: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DerivedArtifact:
    """Encrypted derived output produced from one or more wallet records."""

    artifact_id: str
    wallet_id: str
    source_record_ids: List[str]
    artifact_type: str
    output_policy: str
    encrypted_payload_ref: StorageRef
    created_at: str = field(default_factory=utc_now)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["encrypted_payload_ref"] = self.encrypted_payload_ref.to_dict()
        return data


@dataclass
class ProofReceipt:
    """Receipt for a privacy-preserving proof or simulated proof."""

    proof_id: str
    wallet_id: str
    proof_type: str
    statement: Dict[str, Any]
    verifier_id: str
    public_inputs: Dict[str, Any]
    proof_hash: str
    witness_record_ids: List[str]
    is_simulated: bool
    proof_system: str = "simulated"
    circuit_id: Optional[str] = None
    verifier_digest: Optional[str] = None
    proof_artifact_ref: Optional[str] = None
    verification_status: str = "verified"
    created_at: str = field(default_factory=utc_now)
    expires_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AnalyticsTemplate:
    """Approved aggregate analytics study template."""

    template_id: str
    title: str
    purpose: str
    allowed_record_types: List[str]
    allowed_derived_fields: List[str]
    aggregation_policy: Dict[str, Any]
    created_by: str
    status: str = "approved"
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    expires_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AnalyticsConsent:
    """Consent for a bounded aggregate analytics template."""

    consent_id: str
    wallet_id: str
    template_id: str
    allowed_record_types: List[str]
    allowed_derived_fields: List[str]
    aggregation_policy: Dict[str, Any]
    created_at: str = field(default_factory=utc_now)
    expires_at: Optional[str] = None
    revoked_at: Optional[str] = None
    status: str = "active"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AnalyticsContribution:
    """Privacy-preserving contribution for one analytics template."""

    contribution_id: str
    template_id: str
    consent_id: str
    nullifier: str
    fields: Dict[str, Any]
    proof_id: str
    created_at: str = field(default_factory=utc_now)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AggregateResult:
    """Released or suppressed aggregate analytics result."""

    result_id: str
    template_id: str
    metric: str
    released: bool
    suppressed: bool
    count: Optional[int]
    cohort_size: int
    min_cohort_size: int
    privacy_notes: List[str]
    noisy_count: Optional[float] = None
    epsilon: Optional[float] = None
    noise: Optional[float] = None
    noise_sensitivity: Optional[float] = None
    privacy_budget_key: Optional[str] = None
    privacy_budget_spent: Optional[float] = None
    exact_count_released: bool = True
    cohort_size_released: bool = True
    group_by: List[str] = field(default_factory=list)
    cohorts: List[Dict[str, Any]] = field(default_factory=list)
    suppressed_cohort_count: int = 0
    created_at: str = field(default_factory=utc_now)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class LocationClaim:
    """Derived location claim safe to expose under an appropriate grant."""

    claim_type: str
    public_value: Dict[str, Any]
    source_record_id: str
    precision: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AuditEvent:
    """Append-only audit event chained by hash."""

    event_id: str
    wallet_id: str
    actor_did: str
    action: str
    resource: str
    decision: str
    hash_prev: str
    hash_self: str
    details: Dict[str, Any] = field(default_factory=dict)
    grant_id: Optional[str] = None
    created_at: str = field(default_factory=utc_now)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
