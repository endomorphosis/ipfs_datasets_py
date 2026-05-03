"""Canonical wallet package for user-controlled encrypted data."""

from __future__ import annotations

from .exceptions import (
    AccessDeniedError,
    ApprovalRequiredError,
    DataWalletError,
    DecryptionError,
    GrantError,
    MissingRecordError,
)
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
)
from .multisig import operation_requires_approval
from .privacy import AnalyticsPrivacyPolicy
from .service import DataWalletService
from .storage import (
    FilecoinEncryptedBlobStore,
    IPFSEncryptedBlobStore,
    LocalEncryptedBlobStore,
    ReplicatedEncryptedBlobStore,
    S3EncryptedBlobStore,
)

WalletService = DataWalletService

__all__ = [
    "AccessDeniedError",
    "AccessRequest",
    "AggregateResult",
    "AnalyticsConsent",
    "AnalyticsPrivacyPolicy",
    "AnalyticsContribution",
    "AnalyticsTemplate",
    "ApprovalRequest",
    "ApprovalRequiredError",
    "AuditEvent",
    "DataRecord",
    "DataVersion",
    "DataWalletError",
    "DataWalletService",
    "DecryptionError",
    "DerivedArtifact",
    "Grant",
    "GrantError",
    "FilecoinEncryptedBlobStore",
    "IPFSEncryptedBlobStore",
    "KeyWrap",
    "LocalEncryptedBlobStore",
    "LocationClaim",
    "MissingRecordError",
    "ProofReceipt",
    "ReplicatedEncryptedBlobStore",
    "S3EncryptedBlobStore",
    "StorageHealthReport",
    "StorageRef",
    "StorageReplicaStatus",
    "Wallet",
    "WalletInvocation",
    "WalletService",
    "operation_requires_approval",
]
