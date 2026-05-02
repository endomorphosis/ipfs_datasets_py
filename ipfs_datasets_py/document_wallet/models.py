"""Data models for encrypted document wallets."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .manifest import manifest_ref


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def utc_now() -> float:
    return time.time()


@dataclass
class StorageReceipt:
    provider: str
    ref: str
    size_bytes: int
    created_at: float = field(default_factory=utc_now)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class KeyWrap:
    wrap_id: str
    recipient_did: str
    key_id: str
    algorithm: str
    wrapped_key: Dict[str, Any]
    grant_id: Optional[str] = None
    status: str = "active"
    created_at: float = field(default_factory=utc_now)
    expires_at: Optional[float] = None
    purpose: str = "decrypt"


@dataclass
class DocumentVersion:
    version_id: str
    document_id: str
    encrypted_payload_refs: List[StorageReceipt]
    ciphertext_sha256: str
    plaintext_sha256: Optional[str]
    encrypted_metadata: Dict[str, Any]
    key_wraps: List[KeyWrap]
    encryption_suite: str
    created_at: float = field(default_factory=utc_now)
    analysis_refs: List[StorageReceipt] = field(default_factory=list)

    @property
    def version_ref(self) -> str:
        return manifest_ref(self)


@dataclass
class DocumentRecord:
    document_id: str
    wallet_id: str
    current_version_id: str
    public_descriptor: Dict[str, Any] = field(default_factory=dict)
    status: str = "active"
    created_at: float = field(default_factory=utc_now)
    updated_at: float = field(default_factory=utc_now)
    versions: Dict[str, DocumentVersion] = field(default_factory=dict)

    @property
    def current_version(self) -> DocumentVersion:
        return self.versions[self.current_version_id]


@dataclass
class WalletGrant:
    grant_id: str
    issuer_did: str
    audience_did: str
    resources: List[str]
    abilities: List[str]
    caveats: Dict[str, Any] = field(default_factory=dict)
    proof_refs: List[str] = field(default_factory=list)
    status: str = "active"
    created_at: float = field(default_factory=utc_now)
    expires_at: Optional[float] = None
    revoked_at: Optional[float] = None

    @property
    def grant_ref(self) -> str:
        return manifest_ref(
            {
                "grant_id": self.grant_id,
                "issuer_did": self.issuer_did,
                "audience_did": self.audience_did,
                "resources": self.resources,
                "abilities": self.abilities,
                "caveats": self.caveats,
                "proof_refs": self.proof_refs,
                "created_at": self.created_at,
                "expires_at": self.expires_at,
            }
        )


@dataclass
class AuditEvent:
    event_id: str
    wallet_id: str
    actor_did: str
    action: str
    resource: str
    decision: str
    grant_id: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)
    previous_hash: Optional[str] = None
    created_at: float = field(default_factory=utc_now)

    @property
    def event_hash(self) -> str:
        return manifest_ref(self)


@dataclass
class WalletRecord:
    wallet_id: str
    owner_did: str
    controller_dids: List[str]
    recovery_policy: Dict[str, Any] = field(default_factory=dict)
    storage_policy: Dict[str, Any] = field(default_factory=dict)
    manifest_head: Optional[str] = None
    created_at: float = field(default_factory=utc_now)
    updated_at: float = field(default_factory=utc_now)
    documents: Dict[str, DocumentRecord] = field(default_factory=dict)
    grants: Dict[str, WalletGrant] = field(default_factory=dict)
    audit_log: List[AuditEvent] = field(default_factory=list)

    @property
    def wallet_ref(self) -> str:
        return manifest_ref(self)

    def refresh_manifest_head(self) -> str:
        self.updated_at = utc_now()
        self.manifest_head = self.wallet_ref
        return self.manifest_head

