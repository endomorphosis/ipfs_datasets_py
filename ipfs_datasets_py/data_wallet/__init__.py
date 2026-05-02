"""User-controlled data wallet primitives.

This package is the reusable core for wallet-backed personal data, UCAN-style
delegation, encrypted storage, location claims, and privacy-preserving analysis
workflows. UI layers should call :class:`DataWalletService` instead of
implementing wallet security semantics locally.
"""

from .exceptions import (
    DataWalletError,
    AccessDeniedError,
    DecryptionError,
    GrantError,
    MissingRecordError,
)
from .models import (
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
from .service import DataWalletService

__all__ = [
    "AccessDeniedError",
    "AuditEvent",
    "DataRecord",
    "DataVersion",
    "DataWalletError",
    "DataWalletService",
    "DecryptionError",
    "DerivedArtifact",
    "Grant",
    "GrantError",
    "KeyWrap",
    "LocationClaim",
    "MissingRecordError",
    "ProofReceipt",
    "StorageRef",
    "Wallet",
]
