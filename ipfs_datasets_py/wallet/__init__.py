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
    AnalyticsConsent,
    AnalyticsContribution,
    ApprovalRequest,
    AuditEvent,
    DataRecord,
    DataVersion,
    DerivedArtifact,
    Grant,
    KeyWrap,
    LocationClaim,
    ProofReceipt,
    StorageRef,
    Wallet,
)
from .multisig import operation_requires_approval
from .service import DataWalletService
from .storage import IPFSEncryptedBlobStore, LocalEncryptedBlobStore

WalletService = DataWalletService

__all__ = [
    "AccessDeniedError",
    "AggregateResult",
    "AnalyticsConsent",
    "AnalyticsContribution",
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
    "IPFSEncryptedBlobStore",
    "KeyWrap",
    "LocalEncryptedBlobStore",
    "LocationClaim",
    "MissingRecordError",
    "ProofReceipt",
    "StorageRef",
    "Wallet",
    "WalletService",
    "operation_requires_approval",
]
