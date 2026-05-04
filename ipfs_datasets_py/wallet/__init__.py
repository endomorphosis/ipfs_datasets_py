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
)
from .multisig import operation_requires_approval
from .privacy import AnalyticsPrivacyPolicy
from .proofs import (
    DeterministicLocationRegionProofBackend,
    ProofBackend,
    ProofBackendRegistry,
    SimulatedProofBackend,
)
from .repository import LocalWalletRepository
from .service import DataWalletService
from .storage import (
    FilecoinEncryptedBlobStore,
    IPFSEncryptedBlobStore,
    LocalEncryptedBlobStore,
    ReplicatedEncryptedBlobStore,
    S3EncryptedBlobStore,
    WalletStorageBackendConfig,
    WalletStorageConfig,
    create_encrypted_blob_store,
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
    "DeterministicLocationRegionProofBackend",
    "DerivedArtifact",
    "Grant",
    "GrantReceipt",
    "GrantError",
    "FilecoinEncryptedBlobStore",
    "IPFSEncryptedBlobStore",
    "KeyWrap",
    "LocalEncryptedBlobStore",
    "LocalWalletRepository",
    "LocationClaim",
    "MissingRecordError",
    "ProofReceipt",
    "ProofBackend",
    "ProofBackendRegistry",
    "ReplicatedEncryptedBlobStore",
    "S3EncryptedBlobStore",
    "SimulatedProofBackend",
    "StorageHealthReport",
    "StorageRef",
    "StorageReplicaStatus",
    "Wallet",
    "WalletInvocation",
    "WalletService",
    "WalletStorageHealthReport",
    "WalletStorageBackendConfig",
    "WalletStorageConfig",
    "create_encrypted_blob_store",
    "operation_requires_approval",
]
