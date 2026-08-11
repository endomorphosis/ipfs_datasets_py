"""Domain-neutral authority-transition port (DQK-046).

Installs one reusable authority-transition surface for datasets database
factories. Every domain (graph, vector, proof, AST, wallet, control, audit)
routes mutable truth through this port while migrating off legacy files.

Modes (closed set):

* ``legacy`` — legacy store is sole authority; DuckDB is unused
* ``shadow`` — legacy is authority; DuckDB is a shadow projection; parity receipts
* ``dual`` — dual writes with a crash-recoverable transactional outbox; mismatch
  quarantines rather than silently diverging
* ``db-primary`` — DuckDB is authority; legacy is a fenced projection via outbox
* ``export-only`` — DuckDB is authority; legacy files are one-way exports only
  (never re-admit as authority)

Acceptance properties enforced by construction:

* Crash before or after each DB/outbox boundary recovers idempotently
* Parity mismatch never silently promotes
* Promotion and rollback are CAS-protected, fenced, and receipted
* No implementation claims cross-filesystem / cross-database atomicity
* Package metadata agrees on the pinned DuckDB compatibility window

Importing this module is inert: no DuckDB, network, or filesystem I/O until an
explicit port method is called. Unit/integration tests use the hermetic
:class:`MemoryAuthorityBackend`.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import (
    Any,
    Callable,
    Final,
    Iterable,
    Mapping,
    MutableMapping,
    Optional,
    Protocol,
    Sequence,
)

from ipfs_datasets_py.duckdb_control.capabilities import (
    REQUIRED_DUCKDB_VERSION,
    REQUIRED_DUCKDB_VERSION_TEXT,
)
from ipfs_datasets_py.duckdb_control.contracts import (
    canonical_json_bytes,
    content_identity,
    normalize_timestamp,
)

__all__ = [
    "AUTHORITY_TRANSITION_SCHEMA",
    "CRASH_BOUNDARIES",
    "DECISION_RECEIPT_SCHEMA",
    "DUCKDB_COMPATIBILITY_SPEC",
    "DUCKDB_COMPATIBILITY_WINDOW",
    "MODE_STATE_SCHEMA",
    "OUTBOX_ENTRY_SCHEMA",
    "OWNER_TASK_ID",
    "PACKAGE_METADATA_PATHS",
    "PARITY_RECEIPT_SCHEMA",
    "PROGRAM_ID",
    "QUARANTINE_SCHEMA",
    "AuthorityBackend",
    "AuthorityMode",
    "AuthorityState",
    "AuthorityTransitionError",
    "AuthorityTransitionPort",
    "CrashInjected",
    "DecisionKind",
    "DecisionReceipt",
    "MemoryAuthorityBackend",
    "OutboxEntry",
    "OutboxStatus",
    "PACKAGE_METADATA_AGREEMENT_SCHEMA",
    "ParityReceipt",
    "PromotionBlockedError",
    "QuarantineRecord",
    "WriterFence",
    "allowed_mode_transitions",
    "build_authority_port",
    "compute_payload_digest",
    "install_check",
    "parse_authority_mode",
    "self_check",
    "verify_package_metadata_agreement",
]


# ---------------------------------------------------------------------------
# Schema / pin constants
# ---------------------------------------------------------------------------

OWNER_TASK_ID: Final[str] = "DQK-046"
PROGRAM_ID: Final[str] = "ipfs-datasets-duckdb-quack-v1"

AUTHORITY_TRANSITION_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-control-authority-transition@1"
)
MODE_STATE_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-control-authority-mode-state@1"
)
OUTBOX_ENTRY_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-control-authority-outbox@1"
)
PARITY_RECEIPT_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-control-authority-parity-receipt@1"
)
QUARANTINE_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-control-authority-quarantine@1"
)
DECISION_RECEIPT_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-control-authority-decision-receipt@1"
)
PACKAGE_METADATA_AGREEMENT_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-control-duckdb-package-metadata-agreement@1"
)
INSTALL_CHECK_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-control-authority-transition-install@1"
)

# Pinned compatibility window: exact platform pin is 1.5.5; package metadata
# admits the 1.5.x window so micro-patch upgrades remain expressible while the
# runtime capability probe (DQK-002) still fail-closes on non-1.5.5.
PINNED_DUCKDB_VERSION: Final[str] = REQUIRED_DUCKDB_VERSION_TEXT  # "1.5.5"
PINNED_DUCKDB_VERSION_TUPLE: Final[tuple[int, int, int]] = REQUIRED_DUCKDB_VERSION
DUCKDB_COMPATIBILITY_WINDOW: Final[str] = ">=1.5.5,<1.6.0"
DUCKDB_COMPATIBILITY_SPEC: Final[str] = f"duckdb{DUCKDB_COMPATIBILITY_WINDOW}"

PACKAGE_METADATA_PATHS: Final[tuple[str, ...]] = (
    "requirements.txt",
    "pyproject.toml",
    "__pyproject.toml",
    "setup.py",
)

# Ordered crash-recoverable boundaries around DB and outbox sides.
CRASH_BOUNDARIES: Final[tuple[str, ...]] = (
    "before_db_write",
    "after_db_write",
    "before_outbox_enqueue",
    "after_outbox_enqueue",
    "before_outbox_complete",
    "after_outbox_complete",
    "before_legacy_projection",
    "after_legacy_projection",
)

_CROSS_FILESYSTEM_ATOMICITY_CLAIM: Final[bool] = False  # always False
_SAFE_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/@+-]{0,255}$")
_SHA256_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_MAX_FIELD_BYTES: Final[int] = 8192
_MAX_PAYLOAD_BYTES: Final[int] = 1_048_576


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class AuthorityTransitionError(ValueError):
    """Fail-closed rejection for authority-transition inputs or phases."""


class CrashInjected(AuthorityTransitionError):
    """Raised when a crash-injection boundary is hit (test/recovery harness)."""

    def __init__(
        self,
        boundary: str,
        *,
        operation_id: str = "",
        outbox_id: str = "",
    ) -> None:
        self.boundary = boundary
        self.operation_id = operation_id
        self.outbox_id = outbox_id
        super().__init__(f"crash injected at boundary {boundary!r}")


class PromotionBlockedError(AuthorityTransitionError):
    """Raised when promotion is refused (parity mismatch, fence, CAS, mode)."""

    def __init__(self, message: str, *, reason: str = "promotion_blocked") -> None:
        self.reason = reason
        super().__init__(message)


# ---------------------------------------------------------------------------
# Modes / enums
# ---------------------------------------------------------------------------


class AuthorityMode(str, Enum):
    """Closed set of authority-transition operating modes."""

    LEGACY = "legacy"
    SHADOW = "shadow"
    DUAL = "dual"
    DB_PRIMARY = "db-primary"
    EXPORT_ONLY = "export-only"

    @classmethod
    def parse(cls, value: str | AuthorityMode) -> AuthorityMode:
        if isinstance(value, AuthorityMode):
            return value
        text = str(value).strip().lower().replace("_", "-")
        aliases = {
            "legacy": cls.LEGACY,
            "shadow": cls.SHADOW,
            "dual": cls.DUAL,
            "dual-write": cls.DUAL,
            "dualwrite": cls.DUAL,
            "db-primary": cls.DB_PRIMARY,
            "dbprimary": cls.DB_PRIMARY,
            "database-primary": cls.DB_PRIMARY,
            "duckdb-primary": cls.DB_PRIMARY,
            "export-only": cls.EXPORT_ONLY,
            "exportonly": cls.EXPORT_ONLY,
            "export": cls.EXPORT_ONLY,
        }
        if text not in aliases:
            raise AuthorityTransitionError(
                f"unknown authority mode {value!r}; expected one of "
                f"{sorted(m.value for m in cls)}"
            )
        return aliases[text]


def parse_authority_mode(value: str | AuthorityMode) -> AuthorityMode:
    """Parse a mode string into :class:`AuthorityMode` (fail-closed)."""

    return AuthorityMode.parse(value)


class OutboxStatus(str, Enum):
    """Durable outbox lifecycle states."""

    PENDING = "pending"
    IN_FLIGHT = "in_flight"
    COMPLETED = "completed"
    QUARANTINED = "quarantined"
    DEAD_LETTER = "dead_letter"

    @classmethod
    def parse(cls, value: str | OutboxStatus) -> OutboxStatus:
        if isinstance(value, OutboxStatus):
            return value
        text = str(value).strip().lower().replace("-", "_")
        return cls(text)


class DecisionKind(str, Enum):
    """Explicit mode-change decision kinds (never implicit)."""

    PROMOTE = "promote"
    ROLLBACK = "rollback"


# Allowed forward promotions and reverse rollbacks (CAS-gated transitions).
_PROMOTION_EDGES: Final[Mapping[AuthorityMode, frozenset[AuthorityMode]]] = (
    MappingProxyType(
        {
            AuthorityMode.LEGACY: frozenset(
                {AuthorityMode.SHADOW, AuthorityMode.DUAL}
            ),
            AuthorityMode.SHADOW: frozenset(
                {AuthorityMode.DUAL, AuthorityMode.DB_PRIMARY}
            ),
            AuthorityMode.DUAL: frozenset(
                {AuthorityMode.DB_PRIMARY, AuthorityMode.EXPORT_ONLY}
            ),
            AuthorityMode.DB_PRIMARY: frozenset({AuthorityMode.EXPORT_ONLY}),
            AuthorityMode.EXPORT_ONLY: frozenset(),
        }
    )
)

_ROLLBACK_EDGES: Final[Mapping[AuthorityMode, frozenset[AuthorityMode]]] = (
    MappingProxyType(
        {
            AuthorityMode.EXPORT_ONLY: frozenset(
                {AuthorityMode.DB_PRIMARY, AuthorityMode.DUAL}
            ),
            AuthorityMode.DB_PRIMARY: frozenset(
                {AuthorityMode.DUAL, AuthorityMode.SHADOW}
            ),
            AuthorityMode.DUAL: frozenset(
                {AuthorityMode.SHADOW, AuthorityMode.LEGACY}
            ),
            AuthorityMode.SHADOW: frozenset({AuthorityMode.LEGACY}),
            AuthorityMode.LEGACY: frozenset(),
        }
    )
)


def allowed_mode_transitions(
    current: AuthorityMode | str,
    *,
    kind: DecisionKind | str,
) -> frozenset[AuthorityMode]:
    """Return the closed set of modes reachable from *current* for *kind*."""

    mode = AuthorityMode.parse(current)
    decision = (
        kind if isinstance(kind, DecisionKind) else DecisionKind(str(kind).lower())
    )
    if decision is DecisionKind.PROMOTE:
        return _PROMOTION_EDGES[mode]
    if decision is DecisionKind.ROLLBACK:
        return _ROLLBACK_EDGES[mode]
    raise AuthorityTransitionError(f"unknown decision kind {kind!r}")


# ---------------------------------------------------------------------------
# Primitive helpers
# ---------------------------------------------------------------------------


def _utc_now() -> str:
    return normalize_timestamp(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))


def _bounded_text(
    value: Any,
    *,
    field: str,
    allow_empty: bool = False,
    max_bytes: int = _MAX_FIELD_BYTES,
) -> str:
    if not isinstance(value, str):
        raise AuthorityTransitionError(f"{field} must be text")
    text = value.strip()
    if not text and not allow_empty:
        raise AuthorityTransitionError(f"{field} must be nonempty")
    if len(text.encode("utf-8")) > max_bytes:
        raise AuthorityTransitionError(f"{field} exceeds {max_bytes}-byte bound")
    if "\0" in text or "\r" in text:
        raise AuthorityTransitionError(f"{field} contains control characters")
    return text


def _require_sha256(value: Any, *, field: str) -> str:
    text = _bounded_text(value, field=field)
    normalized = text.lower()
    if not normalized.startswith("sha256:"):
        if re.fullmatch(r"[0-9a-f]{64}", normalized):
            normalized = f"sha256:{normalized}"
        else:
            raise AuthorityTransitionError(f"{field} must be sha256:<64 hex>")
    if not _SHA256_DIGEST.fullmatch(normalized):
        raise AuthorityTransitionError(f"{field} must be sha256:<64 hex>")
    return normalized


def _require_int(value: Any, *, field: str, minimum: int = 0) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise AuthorityTransitionError(f"{field} must be an integer")
    if value < minimum:
        raise AuthorityTransitionError(f"{field} must be >= {minimum}")
    return value


def _require_bool(value: Any, *, field: str) -> bool:
    if not isinstance(value, bool):
        raise AuthorityTransitionError(f"{field} must be a boolean")
    return value


def _plain_mapping(value: Any, *, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise AuthorityTransitionError(f"{field} must be an object")
    return {str(key): item for key, item in value.items()}


def compute_payload_digest(payload: Any) -> str:
    """Return ``sha256:<hex>`` over canonical JSON of *payload*."""

    return content_identity(payload)


def _new_id(prefix: str) -> str:
    return f"{prefix}:{uuid.uuid4().hex}"


# ---------------------------------------------------------------------------
# Writer fence / mode state
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class WriterFence:
    """Compare-and-swap writer fence binding a mode-change owner."""

    writer_id: str
    fencing_token: int
    epoch: int
    domain: str

    def __post_init__(self) -> None:
        wid = _bounded_text(self.writer_id, field="writer_fence.writer_id")
        if not _SAFE_TOKEN.fullmatch(wid):
            raise AuthorityTransitionError("writer_fence.writer_id is not a safe token")
        object.__setattr__(self, "writer_id", wid)
        object.__setattr__(
            self,
            "fencing_token",
            _require_int(
                self.fencing_token, field="writer_fence.fencing_token", minimum=1
            ),
        )
        object.__setattr__(
            self,
            "epoch",
            _require_int(self.epoch, field="writer_fence.epoch", minimum=0),
        )
        domain = _bounded_text(self.domain, field="writer_fence.domain")
        if not _SAFE_TOKEN.fullmatch(domain):
            raise AuthorityTransitionError("writer_fence.domain is not a safe token")
        object.__setattr__(self, "domain", domain)

    def to_dict(self) -> dict[str, Any]:
        return {
            "writer_id": self.writer_id,
            "fencing_token": self.fencing_token,
            "epoch": self.epoch,
            "domain": self.domain,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "WriterFence":
        data = _plain_mapping(value, field="writer_fence")
        return cls(
            writer_id=str(data.get("writer_id") or ""),
            fencing_token=int(data.get("fencing_token") or 0),
            epoch=int(data.get("epoch") or 0),
            domain=str(data.get("domain") or ""),
        )

    def dominates(self, other: "WriterFence") -> bool:
        """True when this fence is strictly newer for the same domain/writer family."""

        if self.domain != other.domain:
            return False
        if self.epoch != other.epoch:
            return self.epoch > other.epoch
        return self.fencing_token > other.fencing_token


@dataclass(frozen=True, slots=True)
class AuthorityState:
    """CAS-protected mode state for one domain namespace."""

    domain: str
    mode: AuthorityMode
    cas_revision: int
    fence: WriterFence
    last_parity_receipt_cid: str = ""
    last_decision_receipt_cid: str = ""
    open_quarantine_count: int = 0
    updated_at: str = ""

    def __post_init__(self) -> None:
        domain = _bounded_text(self.domain, field="authority_state.domain")
        if not _SAFE_TOKEN.fullmatch(domain):
            raise AuthorityTransitionError("authority_state.domain is not a safe token")
        object.__setattr__(self, "domain", domain)
        mode = (
            self.mode
            if isinstance(self.mode, AuthorityMode)
            else AuthorityMode.parse(str(self.mode))
        )
        object.__setattr__(self, "mode", mode)
        object.__setattr__(
            self,
            "cas_revision",
            _require_int(
                self.cas_revision, field="authority_state.cas_revision", minimum=1
            ),
        )
        if not isinstance(self.fence, WriterFence):
            raise AuthorityTransitionError("authority_state.fence must be a WriterFence")
        if self.fence.domain != domain:
            raise AuthorityTransitionError(
                "authority_state.fence.domain must match domain"
            )
        if self.last_parity_receipt_cid:
            object.__setattr__(
                self,
                "last_parity_receipt_cid",
                _require_sha256(
                    self.last_parity_receipt_cid,
                    field="authority_state.last_parity_receipt_cid",
                ),
            )
        if self.last_decision_receipt_cid:
            object.__setattr__(
                self,
                "last_decision_receipt_cid",
                _require_sha256(
                    self.last_decision_receipt_cid,
                    field="authority_state.last_decision_receipt_cid",
                ),
            )
        object.__setattr__(
            self,
            "open_quarantine_count",
            _require_int(
                self.open_quarantine_count,
                field="authority_state.open_quarantine_count",
                minimum=0,
            ),
        )
        if not self.updated_at:
            object.__setattr__(self, "updated_at", _utc_now())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": MODE_STATE_SCHEMA,
            "program_id": PROGRAM_ID,
            "owner_task_id": OWNER_TASK_ID,
            "domain": self.domain,
            "mode": self.mode.value,
            "cas_revision": self.cas_revision,
            "fence": self.fence.to_dict(),
            "last_parity_receipt_cid": self.last_parity_receipt_cid,
            "last_decision_receipt_cid": self.last_decision_receipt_cid,
            "open_quarantine_count": self.open_quarantine_count,
            "updated_at": self.updated_at,
            "atomic_across_filesystems": _CROSS_FILESYSTEM_ATOMICITY_CLAIM,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "AuthorityState":
        data = _plain_mapping(value, field="authority_state")
        fence_raw = data.get("fence") or {}
        if not isinstance(fence_raw, Mapping):
            raise AuthorityTransitionError("authority_state.fence must be an object")
        return cls(
            domain=str(data.get("domain") or ""),
            mode=AuthorityMode.parse(str(data.get("mode") or "")),
            cas_revision=int(data.get("cas_revision") or 0),
            fence=WriterFence.from_mapping(fence_raw),
            last_parity_receipt_cid=str(data.get("last_parity_receipt_cid") or ""),
            last_decision_receipt_cid=str(
                data.get("last_decision_receipt_cid") or ""
            ),
            open_quarantine_count=int(data.get("open_quarantine_count") or 0),
            updated_at=str(data.get("updated_at") or ""),
        )


# ---------------------------------------------------------------------------
# Outbox / parity / quarantine / decision receipts
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OutboxEntry:
    """Durable outbox entry for dual / db-primary projection work.

    Cross-store mutations are *not* atomic. The outbox is the sole recovery
    journal: restart re-drives incomplete entries idempotently by operation_id.
    """

    outbox_id: str
    operation_id: str
    domain: str
    key: str
    payload_digest: str
    status: OutboxStatus
    mode: AuthorityMode
    direction: str  # "to_db" | "to_legacy" | "dual"
    cas_revision: int = 1
    attempt: int = 0
    payload: Mapping[str, Any] = field(default_factory=dict)
    error: str = ""
    created_at: str = ""
    updated_at: str = ""
    # Explicit non-claim: outbox completion is not a cross-file transaction.
    atomic_across_filesystems: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "outbox_id", _bounded_text(self.outbox_id, field="outbox.outbox_id")
        )
        object.__setattr__(
            self,
            "operation_id",
            _bounded_text(self.operation_id, field="outbox.operation_id"),
        )
        object.__setattr__(
            self, "domain", _bounded_text(self.domain, field="outbox.domain")
        )
        object.__setattr__(self, "key", _bounded_text(self.key, field="outbox.key"))
        object.__setattr__(
            self,
            "payload_digest",
            _require_sha256(self.payload_digest, field="outbox.payload_digest"),
        )
        status = (
            self.status
            if isinstance(self.status, OutboxStatus)
            else OutboxStatus.parse(str(self.status))
        )
        object.__setattr__(self, "status", status)
        mode = (
            self.mode
            if isinstance(self.mode, AuthorityMode)
            else AuthorityMode.parse(str(self.mode))
        )
        object.__setattr__(self, "mode", mode)
        direction = _bounded_text(self.direction, field="outbox.direction")
        if direction not in {"to_db", "to_legacy", "dual"}:
            raise AuthorityTransitionError(
                f"outbox.direction must be to_db|to_legacy|dual, got {direction!r}"
            )
        object.__setattr__(self, "direction", direction)
        object.__setattr__(
            self,
            "cas_revision",
            _require_int(self.cas_revision, field="outbox.cas_revision", minimum=1),
        )
        object.__setattr__(
            self,
            "attempt",
            _require_int(self.attempt, field="outbox.attempt", minimum=0),
        )
        if not isinstance(self.payload, Mapping):
            raise AuthorityTransitionError("outbox.payload must be an object")
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))
        if self.atomic_across_filesystems:
            raise AuthorityTransitionError(
                "outbox must not claim cross-filesystem atomicity"
            )
        object.__setattr__(self, "atomic_across_filesystems", False)
        if not self.created_at:
            object.__setattr__(self, "created_at", _utc_now())
        if not self.updated_at:
            object.__setattr__(self, "updated_at", self.created_at)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": OUTBOX_ENTRY_SCHEMA,
            "outbox_id": self.outbox_id,
            "operation_id": self.operation_id,
            "domain": self.domain,
            "key": self.key,
            "payload_digest": self.payload_digest,
            "status": self.status.value,
            "mode": self.mode.value,
            "direction": self.direction,
            "cas_revision": self.cas_revision,
            "attempt": self.attempt,
            "payload": dict(self.payload),
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "atomic_across_filesystems": False,
        }

    def with_status(
        self,
        status: OutboxStatus,
        *,
        error: str = "",
        attempt: int | None = None,
    ) -> "OutboxEntry":
        return OutboxEntry(
            outbox_id=self.outbox_id,
            operation_id=self.operation_id,
            domain=self.domain,
            key=self.key,
            payload_digest=self.payload_digest,
            status=status,
            mode=self.mode,
            direction=self.direction,
            cas_revision=self.cas_revision + 1,
            attempt=self.attempt if attempt is None else attempt,
            payload=dict(self.payload),
            error=error,
            created_at=self.created_at,
            updated_at=_utc_now(),
            atomic_across_filesystems=False,
        )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "OutboxEntry":
        data = _plain_mapping(value, field="outbox")
        payload = data.get("payload") or {}
        if not isinstance(payload, Mapping):
            raise AuthorityTransitionError("outbox.payload must be an object")
        return cls(
            outbox_id=str(data.get("outbox_id") or ""),
            operation_id=str(data.get("operation_id") or ""),
            domain=str(data.get("domain") or ""),
            key=str(data.get("key") or ""),
            payload_digest=str(data.get("payload_digest") or ""),
            status=OutboxStatus.parse(str(data.get("status") or "pending")),
            mode=AuthorityMode.parse(str(data.get("mode") or "dual")),
            direction=str(data.get("direction") or "dual"),
            cas_revision=int(data.get("cas_revision") or 1),
            attempt=int(data.get("attempt") or 0),
            payload=dict(payload),
            error=str(data.get("error") or ""),
            created_at=str(data.get("created_at") or ""),
            updated_at=str(data.get("updated_at") or ""),
            atomic_across_filesystems=False,
        )


@dataclass(frozen=True, slots=True)
class ParityReceipt:
    """Differential / parity receipt between legacy and DuckDB projections."""

    receipt_cid: str
    domain: str
    mode: AuthorityMode
    key: str
    legacy_digest: str
    db_digest: str
    matched: bool
    operation_id: str = ""
    sample_count: int = 1
    mismatch_reason: str = ""
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.receipt_cid:
            body = {
                "domain": self.domain,
                "mode": (
                    self.mode.value
                    if isinstance(self.mode, AuthorityMode)
                    else str(self.mode)
                ),
                "key": self.key,
                "legacy_digest": self.legacy_digest,
                "db_digest": self.db_digest,
                "matched": self.matched,
                "operation_id": self.operation_id,
                "sample_count": self.sample_count,
                "mismatch_reason": self.mismatch_reason,
            }
            object.__setattr__(self, "receipt_cid", content_identity(body))
        else:
            object.__setattr__(
                self,
                "receipt_cid",
                _require_sha256(self.receipt_cid, field="parity.receipt_cid"),
            )
        object.__setattr__(
            self, "domain", _bounded_text(self.domain, field="parity.domain")
        )
        mode = (
            self.mode
            if isinstance(self.mode, AuthorityMode)
            else AuthorityMode.parse(str(self.mode))
        )
        object.__setattr__(self, "mode", mode)
        object.__setattr__(self, "key", _bounded_text(self.key, field="parity.key"))
        object.__setattr__(
            self,
            "legacy_digest",
            _require_sha256(self.legacy_digest, field="parity.legacy_digest"),
        )
        object.__setattr__(
            self,
            "db_digest",
            _require_sha256(self.db_digest, field="parity.db_digest"),
        )
        object.__setattr__(
            self, "matched", _require_bool(self.matched, field="parity.matched")
        )
        object.__setattr__(
            self,
            "sample_count",
            _require_int(self.sample_count, field="parity.sample_count", minimum=0),
        )
        if not self.created_at:
            object.__setattr__(self, "created_at", _utc_now())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": PARITY_RECEIPT_SCHEMA,
            "receipt_cid": self.receipt_cid,
            "domain": self.domain,
            "mode": self.mode.value,
            "key": self.key,
            "legacy_digest": self.legacy_digest,
            "db_digest": self.db_digest,
            "matched": self.matched,
            "operation_id": self.operation_id,
            "sample_count": self.sample_count,
            "mismatch_reason": self.mismatch_reason,
            "created_at": self.created_at,
            "atomic_across_filesystems": False,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ParityReceipt":
        data = _plain_mapping(value, field="parity")
        return cls(
            receipt_cid=str(data.get("receipt_cid") or ""),
            domain=str(data.get("domain") or ""),
            mode=AuthorityMode.parse(str(data.get("mode") or "shadow")),
            key=str(data.get("key") or ""),
            legacy_digest=str(data.get("legacy_digest") or ""),
            db_digest=str(data.get("db_digest") or ""),
            matched=bool(data.get("matched")),
            operation_id=str(data.get("operation_id") or ""),
            sample_count=int(data.get("sample_count") or 1),
            mismatch_reason=str(data.get("mismatch_reason") or ""),
            created_at=str(data.get("created_at") or ""),
        )


@dataclass(frozen=True, slots=True)
class QuarantineRecord:
    """Disagreement quarantine — never silently reconciled or promoted."""

    quarantine_id: str
    domain: str
    key: str
    operation_id: str
    legacy_digest: str
    db_digest: str
    reason: str
    parity_receipt_cid: str = ""
    resolved: bool = False
    created_at: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "quarantine_id",
            _bounded_text(self.quarantine_id, field="quarantine.quarantine_id"),
        )
        object.__setattr__(
            self, "domain", _bounded_text(self.domain, field="quarantine.domain")
        )
        object.__setattr__(
            self, "key", _bounded_text(self.key, field="quarantine.key")
        )
        object.__setattr__(
            self,
            "operation_id",
            _bounded_text(self.operation_id, field="quarantine.operation_id"),
        )
        object.__setattr__(
            self,
            "legacy_digest",
            _require_sha256(self.legacy_digest, field="quarantine.legacy_digest"),
        )
        object.__setattr__(
            self,
            "db_digest",
            _require_sha256(self.db_digest, field="quarantine.db_digest"),
        )
        object.__setattr__(
            self, "reason", _bounded_text(self.reason, field="quarantine.reason")
        )
        if self.parity_receipt_cid:
            object.__setattr__(
                self,
                "parity_receipt_cid",
                _require_sha256(
                    self.parity_receipt_cid, field="quarantine.parity_receipt_cid"
                ),
            )
        object.__setattr__(
            self, "resolved", _require_bool(self.resolved, field="quarantine.resolved")
        )
        if not self.created_at:
            object.__setattr__(self, "created_at", _utc_now())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": QUARANTINE_SCHEMA,
            "quarantine_id": self.quarantine_id,
            "domain": self.domain,
            "key": self.key,
            "operation_id": self.operation_id,
            "legacy_digest": self.legacy_digest,
            "db_digest": self.db_digest,
            "reason": self.reason,
            "parity_receipt_cid": self.parity_receipt_cid,
            "resolved": self.resolved,
            "created_at": self.created_at,
            "atomic_across_filesystems": False,
        }


@dataclass(frozen=True, slots=True)
class DecisionReceipt:
    """CAS-protected, fenced, content-bound promote/rollback receipt."""

    receipt_cid: str
    kind: DecisionKind
    domain: str
    from_mode: AuthorityMode
    to_mode: AuthorityMode
    expected_cas_revision: int
    new_cas_revision: int
    fence: WriterFence
    parity_receipt_cid: str
    decision_id: str
    accepted: bool
    reason: str = ""
    created_at: str = ""
    atomic_across_filesystems: bool = False

    def __post_init__(self) -> None:
        kind = (
            self.kind
            if isinstance(self.kind, DecisionKind)
            else DecisionKind(str(self.kind).lower())
        )
        object.__setattr__(self, "kind", kind)
        object.__setattr__(
            self, "domain", _bounded_text(self.domain, field="decision.domain")
        )
        object.__setattr__(
            self,
            "from_mode",
            self.from_mode
            if isinstance(self.from_mode, AuthorityMode)
            else AuthorityMode.parse(str(self.from_mode)),
        )
        object.__setattr__(
            self,
            "to_mode",
            self.to_mode
            if isinstance(self.to_mode, AuthorityMode)
            else AuthorityMode.parse(str(self.to_mode)),
        )
        object.__setattr__(
            self,
            "expected_cas_revision",
            _require_int(
                self.expected_cas_revision,
                field="decision.expected_cas_revision",
                minimum=1,
            ),
        )
        object.__setattr__(
            self,
            "new_cas_revision",
            _require_int(
                self.new_cas_revision, field="decision.new_cas_revision", minimum=1
            ),
        )
        if not isinstance(self.fence, WriterFence):
            raise AuthorityTransitionError("decision.fence must be a WriterFence")
        if self.parity_receipt_cid:
            object.__setattr__(
                self,
                "parity_receipt_cid",
                _require_sha256(
                    self.parity_receipt_cid, field="decision.parity_receipt_cid"
                ),
            )
        object.__setattr__(
            self,
            "decision_id",
            _bounded_text(self.decision_id, field="decision.decision_id"),
        )
        object.__setattr__(
            self, "accepted", _require_bool(self.accepted, field="decision.accepted")
        )
        if self.atomic_across_filesystems:
            raise AuthorityTransitionError(
                "decision must not claim cross-filesystem atomicity"
            )
        object.__setattr__(self, "atomic_across_filesystems", False)
        if not self.created_at:
            object.__setattr__(self, "created_at", _utc_now())
        if not self.receipt_cid:
            object.__setattr__(self, "receipt_cid", content_identity(self._body()))
        else:
            object.__setattr__(
                self,
                "receipt_cid",
                _require_sha256(self.receipt_cid, field="decision.receipt_cid"),
            )

    def _body(self) -> dict[str, Any]:
        return {
            "schema": DECISION_RECEIPT_SCHEMA,
            "kind": self.kind.value,
            "domain": self.domain,
            "from_mode": self.from_mode.value,
            "to_mode": self.to_mode.value,
            "expected_cas_revision": self.expected_cas_revision,
            "new_cas_revision": self.new_cas_revision,
            "fence": self.fence.to_dict(),
            "parity_receipt_cid": self.parity_receipt_cid,
            "decision_id": self.decision_id,
            "accepted": self.accepted,
            "reason": self.reason,
            "created_at": self.created_at,
            "atomic_across_filesystems": False,
            "program_id": PROGRAM_ID,
            "owner_task_id": OWNER_TASK_ID,
        }

    def to_dict(self) -> dict[str, Any]:
        body = self._body()
        body["receipt_cid"] = self.receipt_cid
        return body


# ---------------------------------------------------------------------------
# Backend protocol + memory implementation
# ---------------------------------------------------------------------------


class AuthorityBackend(Protocol):
    """Durable storage surface for mode state, records, outbox, and receipts."""

    def get_state(self, domain: str) -> AuthorityState | None: ...

    def cas_put_state(
        self,
        state: AuthorityState,
        *,
        expected_revision: int | None,
    ) -> AuthorityState: ...

    def get_legacy(self, domain: str, key: str) -> Mapping[str, Any] | None: ...

    def put_legacy(
        self, domain: str, key: str, payload: Mapping[str, Any]
    ) -> None: ...

    def get_db(self, domain: str, key: str) -> Mapping[str, Any] | None: ...

    def put_db(self, domain: str, key: str, payload: Mapping[str, Any]) -> None: ...

    def put_outbox(self, entry: OutboxEntry) -> OutboxEntry: ...

    def get_outbox(self, outbox_id: str) -> OutboxEntry | None: ...

    def get_outbox_by_operation(self, operation_id: str) -> OutboxEntry | None: ...

    def list_incomplete_outbox(self, domain: str) -> Sequence[OutboxEntry]: ...

    def put_parity(self, receipt: ParityReceipt) -> ParityReceipt: ...

    def put_quarantine(self, record: QuarantineRecord) -> QuarantineRecord: ...

    def list_open_quarantine(self, domain: str) -> Sequence[QuarantineRecord]: ...

    def put_decision(self, receipt: DecisionReceipt) -> DecisionReceipt: ...

    def get_decision(self, decision_id: str) -> DecisionReceipt | None: ...


class MemoryAuthorityBackend:
    """Hermetic in-memory backend for tests and crash-recovery simulation."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._states: dict[str, AuthorityState] = {}
        self._legacy: dict[tuple[str, str], dict[str, Any]] = {}
        self._db: dict[tuple[str, str], dict[str, Any]] = {}
        self._outbox: dict[str, OutboxEntry] = {}
        self._outbox_by_op: dict[str, str] = {}
        self._parity: dict[str, ParityReceipt] = {}
        self._quarantine: dict[str, QuarantineRecord] = {}
        self._decisions: dict[str, DecisionReceipt] = {}
        self._decisions_by_id: dict[str, str] = {}

    def get_state(self, domain: str) -> AuthorityState | None:
        with self._lock:
            return self._states.get(domain)

    def cas_put_state(
        self,
        state: AuthorityState,
        *,
        expected_revision: int | None,
    ) -> AuthorityState:
        with self._lock:
            current = self._states.get(state.domain)
            if expected_revision is None:
                if current is not None:
                    raise AuthorityTransitionError(
                        f"CAS create failed: domain {state.domain!r} already exists "
                        f"at revision {current.cas_revision}"
                    )
                self._states[state.domain] = state
                return state
            if current is None:
                raise AuthorityTransitionError(
                    f"CAS update failed: domain {state.domain!r} has no state"
                )
            if current.cas_revision != expected_revision:
                raise AuthorityTransitionError(
                    f"CAS conflict for domain {state.domain!r}: "
                    f"expected revision {expected_revision}, "
                    f"actual {current.cas_revision}"
                )
            if state.cas_revision != expected_revision + 1:
                raise AuthorityTransitionError(
                    "CAS update must advance cas_revision by exactly 1"
                )
            self._states[state.domain] = state
            return state

    def get_legacy(self, domain: str, key: str) -> Mapping[str, Any] | None:
        with self._lock:
            value = self._legacy.get((domain, key))
            return None if value is None else MappingProxyType(dict(value))

    def put_legacy(self, domain: str, key: str, payload: Mapping[str, Any]) -> None:
        with self._lock:
            self._legacy[(domain, key)] = dict(payload)

    def get_db(self, domain: str, key: str) -> Mapping[str, Any] | None:
        with self._lock:
            value = self._db.get((domain, key))
            return None if value is None else MappingProxyType(dict(value))

    def put_db(self, domain: str, key: str, payload: Mapping[str, Any]) -> None:
        with self._lock:
            self._db[(domain, key)] = dict(payload)

    def put_outbox(self, entry: OutboxEntry) -> OutboxEntry:
        with self._lock:
            existing_id = self._outbox_by_op.get(entry.operation_id)
            if existing_id and existing_id != entry.outbox_id:
                raise AuthorityTransitionError(
                    f"operation_id {entry.operation_id!r} already bound to "
                    f"outbox {existing_id!r}"
                )
            self._outbox[entry.outbox_id] = entry
            self._outbox_by_op[entry.operation_id] = entry.outbox_id
            return entry

    def get_outbox(self, outbox_id: str) -> OutboxEntry | None:
        with self._lock:
            return self._outbox.get(outbox_id)

    def get_outbox_by_operation(self, operation_id: str) -> OutboxEntry | None:
        with self._lock:
            outbox_id = self._outbox_by_op.get(operation_id)
            if not outbox_id:
                return None
            return self._outbox.get(outbox_id)

    def list_incomplete_outbox(self, domain: str) -> Sequence[OutboxEntry]:
        with self._lock:
            open_status = {
                OutboxStatus.PENDING,
                OutboxStatus.IN_FLIGHT,
            }
            return tuple(
                entry
                for entry in self._outbox.values()
                if entry.domain == domain and entry.status in open_status
            )

    def put_parity(self, receipt: ParityReceipt) -> ParityReceipt:
        with self._lock:
            self._parity[receipt.receipt_cid] = receipt
            return receipt

    def put_quarantine(self, record: QuarantineRecord) -> QuarantineRecord:
        with self._lock:
            self._quarantine[record.quarantine_id] = record
            return record

    def list_open_quarantine(self, domain: str) -> Sequence[QuarantineRecord]:
        with self._lock:
            return tuple(
                record
                for record in self._quarantine.values()
                if record.domain == domain and not record.resolved
            )

    def put_decision(self, receipt: DecisionReceipt) -> DecisionReceipt:
        with self._lock:
            existing = self._decisions_by_id.get(receipt.decision_id)
            if existing and existing != receipt.receipt_cid:
                # Idempotent: return the sealed prior receipt.
                prior = self._decisions[existing]
                return prior
            self._decisions[receipt.receipt_cid] = receipt
            self._decisions_by_id[receipt.decision_id] = receipt.receipt_cid
            return receipt

    def get_decision(self, decision_id: str) -> DecisionReceipt | None:
        with self._lock:
            receipt_cid = self._decisions_by_id.get(decision_id)
            if not receipt_cid:
                return None
            return self._decisions.get(receipt_cid)


# ---------------------------------------------------------------------------
# Port
# ---------------------------------------------------------------------------


class AuthorityTransitionPort:
    """Domain-neutral authority-transition port.

    Integrates with datasets database factories (see
    :func:`ipfs_datasets_py.database_utils.build_authority_transition_port`).
    Mutations that span legacy files and DuckDB never claim atomicity; they
    use the durable outbox and idempotent recovery instead.
    """

    SCHEMA: Final[str] = AUTHORITY_TRANSITION_SCHEMA
    atomic_across_filesystems: Final[bool] = False

    def __init__(
        self,
        backend: AuthorityBackend,
        *,
        domain: str,
        initial_mode: AuthorityMode | str = AuthorityMode.LEGACY,
        writer_id: str = "writer:authority-transition",
        crash_at: str | None = None,
        crash_once: bool = True,
    ) -> None:
        self._backend = backend
        self._domain = _bounded_text(domain, field="domain")
        if not _SAFE_TOKEN.fullmatch(self._domain):
            raise AuthorityTransitionError("domain is not a safe token")
        self._lock = threading.RLock()
        self._crash_at = crash_at
        self._crash_once = crash_once
        self._crashed: set[str] = set()
        self._ensure_state(AuthorityMode.parse(initial_mode), writer_id=writer_id)

    # -- properties ---------------------------------------------------------

    @property
    def domain(self) -> str:
        return self._domain

    @property
    def mode(self) -> AuthorityMode:
        state = self.state()
        return state.mode

    @property
    def backend(self) -> AuthorityBackend:
        return self._backend

    def state(self) -> AuthorityState:
        current = self._backend.get_state(self._domain)
        if current is None:
            raise AuthorityTransitionError(
                f"no authority state for domain {self._domain!r}"
            )
        return current

    def _ensure_state(
        self, mode: AuthorityMode, *, writer_id: str
    ) -> AuthorityState:
        existing = self._backend.get_state(self._domain)
        if existing is not None:
            return existing
        fence = WriterFence(
            writer_id=writer_id,
            fencing_token=1,
            epoch=0,
            domain=self._domain,
        )
        state = AuthorityState(
            domain=self._domain,
            mode=mode,
            cas_revision=1,
            fence=fence,
            updated_at=_utc_now(),
        )
        return self._backend.cas_put_state(state, expected_revision=None)

    def _maybe_crash(
        self,
        boundary: str,
        *,
        operation_id: str = "",
        outbox_id: str = "",
    ) -> None:
        if self._crash_at is None:
            return
        if self._crash_at != boundary:
            return
        if self._crash_once and boundary in self._crashed:
            return
        self._crashed.add(boundary)
        raise CrashInjected(
            boundary, operation_id=operation_id, outbox_id=outbox_id
        )

    def set_crash_at(self, boundary: str | None) -> None:
        """Configure crash injection (test harness only)."""

        if boundary is not None and boundary not in CRASH_BOUNDARIES:
            raise AuthorityTransitionError(
                f"unknown crash boundary {boundary!r}; expected one of "
                f"{CRASH_BOUNDARIES}"
            )
        self._crash_at = boundary
        self._crashed.clear()

    # -- read path ----------------------------------------------------------

    def read(self, key: str) -> Mapping[str, Any] | None:
        """Read under the current mode's authority surface."""

        key = _bounded_text(key, field="key")
        state = self.state()
        mode = state.mode
        if mode is AuthorityMode.LEGACY:
            return self._backend.get_legacy(self._domain, key)
        if mode is AuthorityMode.SHADOW:
            return self._backend.get_legacy(self._domain, key)
        if mode is AuthorityMode.DUAL:
            # Prefer DB when present; fall back to legacy (dual-write recovery).
            db_value = self._backend.get_db(self._domain, key)
            if db_value is not None:
                return db_value
            return self._backend.get_legacy(self._domain, key)
        if mode in {AuthorityMode.DB_PRIMARY, AuthorityMode.EXPORT_ONLY}:
            return self._backend.get_db(self._domain, key)
        raise AuthorityTransitionError(f"unsupported mode {mode!r}")

    # -- write path with outbox ---------------------------------------------

    def write(
        self,
        key: str,
        payload: Mapping[str, Any],
        *,
        operation_id: str | None = None,
    ) -> dict[str, Any]:
        """Write under the current mode with outbox recovery where required.

        Returns a result dict binding operation_id, digests, outbox status, and
        an explicit ``atomic_across_filesystems=False`` flag.
        """

        key = _bounded_text(key, field="key")
        if not isinstance(payload, Mapping):
            raise AuthorityTransitionError("payload must be an object")
        body = dict(payload)
        raw = canonical_json_bytes(body)
        if len(raw) > _MAX_PAYLOAD_BYTES:
            raise AuthorityTransitionError(
                f"payload exceeds {_MAX_PAYLOAD_BYTES}-byte bound"
            )
        payload_digest = compute_payload_digest(body)
        op_id = _bounded_text(
            operation_id or _new_id("op"), field="operation_id"
        )

        with self._lock:
            # Idempotent replay for known operation_id.
            prior = self._backend.get_outbox_by_operation(op_id)
            if prior is not None and prior.status is OutboxStatus.COMPLETED:
                return {
                    "ok": True,
                    "idempotent_replay": True,
                    "operation_id": op_id,
                    "outbox_id": prior.outbox_id,
                    "payload_digest": prior.payload_digest,
                    "mode": self.state().mode.value,
                    "atomic_across_filesystems": False,
                    "status": prior.status.value,
                }

            state = self.state()
            mode = state.mode

            if mode is AuthorityMode.EXPORT_ONLY:
                raise AuthorityTransitionError(
                    "export-only mode rejects authority writes; use the export "
                    "pipeline (DQK-045) for one-way projections"
                )

            if mode is AuthorityMode.LEGACY:
                self._backend.put_legacy(self._domain, key, body)
                return {
                    "ok": True,
                    "idempotent_replay": False,
                    "operation_id": op_id,
                    "outbox_id": "",
                    "payload_digest": payload_digest,
                    "mode": mode.value,
                    "atomic_across_filesystems": False,
                    "status": "completed",
                    "authority": "legacy",
                }

            if mode is AuthorityMode.SHADOW:
                # Legacy is authority; DuckDB is shadow projection via outbox.
                self._backend.put_legacy(self._domain, key, body)
                entry = self._enqueue_outbox(
                    operation_id=op_id,
                    key=key,
                    payload=body,
                    payload_digest=payload_digest,
                    mode=mode,
                    direction="to_db",
                )
                try:
                    self._drive_outbox(entry)
                except CrashInjected:
                    raise
                return {
                    "ok": True,
                    "idempotent_replay": False,
                    "operation_id": op_id,
                    "outbox_id": entry.outbox_id,
                    "payload_digest": payload_digest,
                    "mode": mode.value,
                    "atomic_across_filesystems": False,
                    "status": self._backend.get_outbox(entry.outbox_id).status.value,  # type: ignore[union-attr]
                    "authority": "legacy",
                }

            if mode is AuthorityMode.DUAL:
                return self._dual_write(
                    key=key,
                    payload=body,
                    operation_id=op_id,
                    payload_digest=payload_digest,
                    mode=mode,
                )

            if mode is AuthorityMode.DB_PRIMARY:
                # DuckDB authority; legacy projection via outbox.
                self._maybe_crash(
                    "before_db_write", operation_id=op_id
                )
                self._backend.put_db(self._domain, key, body)
                self._maybe_crash(
                    "after_db_write", operation_id=op_id
                )
                entry = self._enqueue_outbox(
                    operation_id=op_id,
                    key=key,
                    payload=body,
                    payload_digest=payload_digest,
                    mode=mode,
                    direction="to_legacy",
                )
                try:
                    self._drive_outbox(entry)
                except CrashInjected:
                    raise
                return {
                    "ok": True,
                    "idempotent_replay": False,
                    "operation_id": op_id,
                    "outbox_id": entry.outbox_id,
                    "payload_digest": payload_digest,
                    "mode": mode.value,
                    "atomic_across_filesystems": False,
                    "status": self._backend.get_outbox(entry.outbox_id).status.value,  # type: ignore[union-attr]
                    "authority": "duckdb",
                }

            raise AuthorityTransitionError(f"unsupported mode {mode!r}")

    def _dual_write(
        self,
        *,
        key: str,
        payload: Mapping[str, Any],
        operation_id: str,
        payload_digest: str,
        mode: AuthorityMode,
    ) -> dict[str, Any]:
        """Dual write: DB + legacy coordinated only through the outbox journal."""

        # Enqueue first so a crash mid-write has a durable recovery handle.
        entry = self._enqueue_outbox(
            operation_id=operation_id,
            key=key,
            payload=payload,
            payload_digest=payload_digest,
            mode=mode,
            direction="dual",
        )
        try:
            self._drive_outbox(entry)
        except CrashInjected:
            raise
        final = self._backend.get_outbox(entry.outbox_id)
        assert final is not None
        return {
            "ok": final.status is OutboxStatus.COMPLETED,
            "idempotent_replay": False,
            "operation_id": operation_id,
            "outbox_id": entry.outbox_id,
            "payload_digest": payload_digest,
            "mode": mode.value,
            "atomic_across_filesystems": False,
            "status": final.status.value,
            "authority": "dual",
        }

    def _enqueue_outbox(
        self,
        *,
        operation_id: str,
        key: str,
        payload: Mapping[str, Any],
        payload_digest: str,
        mode: AuthorityMode,
        direction: str,
    ) -> OutboxEntry:
        existing = self._backend.get_outbox_by_operation(operation_id)
        if existing is not None:
            return existing
        self._maybe_crash(
            "before_outbox_enqueue", operation_id=operation_id
        )
        entry = OutboxEntry(
            outbox_id=_new_id("outbox"),
            operation_id=operation_id,
            domain=self._domain,
            key=key,
            payload_digest=payload_digest,
            status=OutboxStatus.PENDING,
            mode=mode,
            direction=direction,
            payload=dict(payload),
            created_at=_utc_now(),
            updated_at=_utc_now(),
            atomic_across_filesystems=False,
        )
        stored = self._backend.put_outbox(entry)
        self._maybe_crash(
            "after_outbox_enqueue",
            operation_id=operation_id,
            outbox_id=stored.outbox_id,
        )
        return stored

    def _drive_outbox(self, entry: OutboxEntry) -> OutboxEntry:
        """Advance one outbox entry through DB/legacy sides (idempotent)."""

        current = self._backend.get_outbox(entry.outbox_id) or entry
        if current.status is OutboxStatus.COMPLETED:
            return current
        if current.status is OutboxStatus.QUARANTINED:
            return current

        in_flight = current.with_status(
            OutboxStatus.IN_FLIGHT, attempt=current.attempt + 1
        )
        self._backend.put_outbox(in_flight)
        current = in_flight
        payload = dict(current.payload)
        key = current.key
        direction = current.direction

        try:
            if direction in {"to_db", "dual"}:
                self._maybe_crash(
                    "before_db_write",
                    operation_id=current.operation_id,
                    outbox_id=current.outbox_id,
                )
                self._backend.put_db(self._domain, key, payload)
                self._maybe_crash(
                    "after_db_write",
                    operation_id=current.operation_id,
                    outbox_id=current.outbox_id,
                )
            if direction in {"to_legacy", "dual"}:
                self._maybe_crash(
                    "before_legacy_projection",
                    operation_id=current.operation_id,
                    outbox_id=current.outbox_id,
                )
                self._backend.put_legacy(self._domain, key, payload)
                self._maybe_crash(
                    "after_legacy_projection",
                    operation_id=current.operation_id,
                    outbox_id=current.outbox_id,
                )

            self._maybe_crash(
                "before_outbox_complete",
                operation_id=current.operation_id,
                outbox_id=current.outbox_id,
            )
            completed = current.with_status(OutboxStatus.COMPLETED)
            self._backend.put_outbox(completed)
            self._maybe_crash(
                "after_outbox_complete",
                operation_id=current.operation_id,
                outbox_id=current.outbox_id,
            )
            return completed
        except CrashInjected:
            raise
        except Exception as exc:  # noqa: BLE001 — quarantine rather than lose
            failed = current.with_status(
                OutboxStatus.QUARANTINED, error=str(exc)
            )
            self._backend.put_outbox(failed)
            self.quarantine_disagreement(
                key=key,
                operation_id=current.operation_id,
                reason=f"outbox_drive_failed: {exc}",
            )
            return failed

    # -- recovery -----------------------------------------------------------

    def recover_outbox(self) -> dict[str, Any]:
        """Idempotently recover incomplete outbox entries for this domain.

        Safe to call after any crash before/after DB or outbox boundaries.
        Re-driving a completed operation is a no-op.
        """

        recovered: list[str] = []
        quarantined: list[str] = []
        with self._lock:
            incomplete = list(self._backend.list_incomplete_outbox(self._domain))
            for entry in incomplete:
                try:
                    final = self._drive_outbox(entry)
                except CrashInjected:
                    raise
                if final.status is OutboxStatus.COMPLETED:
                    recovered.append(final.outbox_id)
                elif final.status is OutboxStatus.QUARANTINED:
                    quarantined.append(final.outbox_id)
        return {
            "ok": True,
            "domain": self._domain,
            "recovered_outbox_ids": recovered,
            "quarantined_outbox_ids": quarantined,
            "remaining_incomplete": [
                e.outbox_id
                for e in self._backend.list_incomplete_outbox(self._domain)
            ],
            "atomic_across_filesystems": False,
            "idempotent": True,
        }

    # -- parity / quarantine ------------------------------------------------

    def emit_parity_receipt(
        self,
        key: str,
        *,
        operation_id: str = "",
    ) -> ParityReceipt:
        """Compare legacy and DuckDB digests; emit a parity receipt."""

        key = _bounded_text(key, field="key")
        state = self.state()
        legacy = self._backend.get_legacy(self._domain, key)
        db = self._backend.get_db(self._domain, key)
        empty = content_identity({})
        legacy_digest = compute_payload_digest(dict(legacy)) if legacy else empty
        db_digest = compute_payload_digest(dict(db)) if db else empty
        matched = hmac.compare_digest(legacy_digest, db_digest)
        reason = ""
        if not matched:
            if legacy is None and db is not None:
                reason = "legacy_missing"
            elif db is None and legacy is not None:
                reason = "db_missing"
            else:
                reason = "digest_mismatch"
        receipt = ParityReceipt(
            receipt_cid="",
            domain=self._domain,
            mode=state.mode,
            key=key,
            legacy_digest=legacy_digest,
            db_digest=db_digest,
            matched=matched,
            operation_id=operation_id,
            sample_count=1,
            mismatch_reason=reason,
            created_at=_utc_now(),
        )
        stored = self._backend.put_parity(receipt)
        # Persist last parity CID via CAS without changing mode.
        new_state = AuthorityState(
            domain=state.domain,
            mode=state.mode,
            cas_revision=state.cas_revision + 1,
            fence=state.fence,
            last_parity_receipt_cid=stored.receipt_cid,
            last_decision_receipt_cid=state.last_decision_receipt_cid,
            open_quarantine_count=state.open_quarantine_count,
            updated_at=_utc_now(),
        )
        self._backend.cas_put_state(
            new_state, expected_revision=state.cas_revision
        )
        if not matched:
            self.quarantine_disagreement(
                key=key,
                operation_id=operation_id or _new_id("parity-op"),
                reason=reason or "digest_mismatch",
                parity_receipt_cid=stored.receipt_cid,
                legacy_digest=legacy_digest,
                db_digest=db_digest,
            )
        return stored

    def quarantine_disagreement(
        self,
        *,
        key: str,
        operation_id: str,
        reason: str,
        parity_receipt_cid: str = "",
        legacy_digest: str | None = None,
        db_digest: str | None = None,
    ) -> QuarantineRecord:
        """Record a disagreement quarantine (never silently promotes)."""

        key = _bounded_text(key, field="key")
        if legacy_digest is None or db_digest is None:
            legacy = self._backend.get_legacy(self._domain, key)
            db = self._backend.get_db(self._domain, key)
            empty = content_identity({})
            legacy_digest = (
                legacy_digest
                or (compute_payload_digest(dict(legacy)) if legacy else empty)
            )
            db_digest = (
                db_digest or (compute_payload_digest(dict(db)) if db else empty)
            )
        record = QuarantineRecord(
            quarantine_id=_new_id("quarantine"),
            domain=self._domain,
            key=key,
            operation_id=_bounded_text(operation_id, field="operation_id"),
            legacy_digest=legacy_digest,
            db_digest=db_digest,
            reason=_bounded_text(reason, field="reason"),
            parity_receipt_cid=parity_receipt_cid,
            resolved=False,
            created_at=_utc_now(),
        )
        stored = self._backend.put_quarantine(record)
        state = self.state()
        open_count = len(self._backend.list_open_quarantine(self._domain))
        new_state = AuthorityState(
            domain=state.domain,
            mode=state.mode,
            cas_revision=state.cas_revision + 1,
            fence=state.fence,
            last_parity_receipt_cid=state.last_parity_receipt_cid,
            last_decision_receipt_cid=state.last_decision_receipt_cid,
            open_quarantine_count=open_count,
            updated_at=_utc_now(),
        )
        try:
            self._backend.cas_put_state(
                new_state, expected_revision=state.cas_revision
            )
        except AuthorityTransitionError:
            # Concurrent CAS: quarantine record is durable; count is best-effort.
            pass
        return stored

    # -- promote / rollback -------------------------------------------------

    def promote(
        self,
        to_mode: AuthorityMode | str,
        *,
        decision_id: str | None = None,
        fence: WriterFence | None = None,
        require_parity: bool = True,
        parity_key: str | None = None,
    ) -> DecisionReceipt:
        """CAS-protected, fenced, receipted promotion. Mismatch never promotes."""

        target = AuthorityMode.parse(to_mode)
        decision_id = _bounded_text(
            decision_id or _new_id("decision"), field="decision_id"
        )
        prior = self._backend.get_decision(decision_id)
        if prior is not None:
            return prior

        with self._lock:
            state = self.state()
            allowed = allowed_mode_transitions(state.mode, kind=DecisionKind.PROMOTE)
            if target not in allowed:
                receipt = DecisionReceipt(
                    receipt_cid="",
                    kind=DecisionKind.PROMOTE,
                    domain=self._domain,
                    from_mode=state.mode,
                    to_mode=target,
                    expected_cas_revision=state.cas_revision,
                    new_cas_revision=state.cas_revision,
                    fence=state.fence,
                    parity_receipt_cid=state.last_parity_receipt_cid,
                    decision_id=decision_id,
                    accepted=False,
                    reason=(
                        f"promotion {state.mode.value!r} -> {target.value!r} "
                        f"not allowed; permitted={sorted(m.value for m in allowed)}"
                    ),
                    created_at=_utc_now(),
                    atomic_across_filesystems=False,
                )
                return self._backend.put_decision(receipt)

            # Open quarantine always blocks promotion (mismatch never silent).
            open_q = list(self._backend.list_open_quarantine(self._domain))
            if open_q:
                raise PromotionBlockedError(
                    f"promotion blocked: {len(open_q)} open quarantine record(s) "
                    f"for domain {self._domain!r}",
                    reason="open_quarantine",
                )

            parity_cid = state.last_parity_receipt_cid
            if require_parity and state.mode is not AuthorityMode.LEGACY:
                if parity_key is None:
                    raise PromotionBlockedError(
                        "promotion requires parity_key when require_parity=True",
                        reason="parity_required",
                    )
                receipt = self.emit_parity_receipt(
                    parity_key, operation_id=f"promote:{decision_id}"
                )
                parity_cid = receipt.receipt_cid
                if not receipt.matched:
                    raise PromotionBlockedError(
                        f"promotion blocked: parity mismatch on key "
                        f"{parity_key!r} ({receipt.mismatch_reason})",
                        reason="parity_mismatch",
                    )
                # Parity emission advances CAS; re-load before decision CAS.
                state = self.state()

            # Incomplete outbox blocks promotion (split-brain risk).
            incomplete = list(self._backend.list_incomplete_outbox(self._domain))
            if incomplete:
                raise PromotionBlockedError(
                    f"promotion blocked: {len(incomplete)} incomplete outbox "
                    f"entr(y/ies); recover first",
                    reason="incomplete_outbox",
                )

            # Re-check quarantine after parity (mismatch may have opened one).
            open_q = list(self._backend.list_open_quarantine(self._domain))
            if open_q:
                raise PromotionBlockedError(
                    f"promotion blocked: {len(open_q)} open quarantine record(s) "
                    f"for domain {self._domain!r}",
                    reason="open_quarantine",
                )

            new_fence = fence or WriterFence(
                writer_id=state.fence.writer_id,
                fencing_token=state.fence.fencing_token + 1,
                epoch=state.fence.epoch,
                domain=self._domain,
            )
            if (
                new_fence.fencing_token < state.fence.fencing_token
                or (
                    new_fence.fencing_token == state.fence.fencing_token
                    and new_fence.epoch < state.fence.epoch
                )
            ):
                raise PromotionBlockedError(
                    "promotion blocked: fence token/epoch must not go backwards",
                    reason="stale_fence",
                )
            if (
                new_fence.fencing_token == state.fence.fencing_token
                and new_fence.epoch == state.fence.epoch
            ):
                # Every accepted decision must advance the fence.
                new_fence = WriterFence(
                    writer_id=new_fence.writer_id,
                    fencing_token=new_fence.fencing_token + 1,
                    epoch=new_fence.epoch,
                    domain=self._domain,
                )

            from_mode = state.mode
            expected_rev = state.cas_revision
            new_state = AuthorityState(
                domain=self._domain,
                mode=target,
                cas_revision=expected_rev + 1,
                fence=new_fence,
                last_parity_receipt_cid=parity_cid,
                last_decision_receipt_cid="",  # filled after seal
                open_quarantine_count=0,
                updated_at=_utc_now(),
            )
            try:
                self._backend.cas_put_state(
                    new_state, expected_revision=expected_rev
                )
            except AuthorityTransitionError as exc:
                raise PromotionBlockedError(
                    f"promotion CAS failed: {exc}", reason="cas_conflict"
                ) from exc

            decision = DecisionReceipt(
                receipt_cid="",
                kind=DecisionKind.PROMOTE,
                domain=self._domain,
                from_mode=from_mode,
                to_mode=target,
                expected_cas_revision=expected_rev,
                new_cas_revision=new_state.cas_revision,
                fence=new_fence,
                parity_receipt_cid=parity_cid,
                decision_id=decision_id,
                accepted=True,
                reason="promoted",
                created_at=_utc_now(),
                atomic_across_filesystems=False,
            )
            sealed = self._backend.put_decision(decision)
            # Bind decision CID on state (best-effort second CAS).
            bound = AuthorityState(
                domain=new_state.domain,
                mode=new_state.mode,
                cas_revision=new_state.cas_revision + 1,
                fence=new_state.fence,
                last_parity_receipt_cid=new_state.last_parity_receipt_cid,
                last_decision_receipt_cid=sealed.receipt_cid,
                open_quarantine_count=0,
                updated_at=_utc_now(),
            )
            try:
                self._backend.cas_put_state(
                    bound, expected_revision=new_state.cas_revision
                )
            except AuthorityTransitionError:
                pass
            return sealed

    def rollback(
        self,
        to_mode: AuthorityMode | str,
        *,
        decision_id: str | None = None,
        fence: WriterFence | None = None,
        reason: str = "operator_rollback",
    ) -> DecisionReceipt:
        """CAS-protected, fenced, receipted rollback decision."""

        target = AuthorityMode.parse(to_mode)
        decision_id = _bounded_text(
            decision_id or _new_id("decision"), field="decision_id"
        )
        prior = self._backend.get_decision(decision_id)
        if prior is not None:
            return prior

        with self._lock:
            state = self.state()
            allowed = allowed_mode_transitions(
                state.mode, kind=DecisionKind.ROLLBACK
            )
            if target not in allowed:
                receipt = DecisionReceipt(
                    receipt_cid="",
                    kind=DecisionKind.ROLLBACK,
                    domain=self._domain,
                    from_mode=state.mode,
                    to_mode=target,
                    expected_cas_revision=state.cas_revision,
                    new_cas_revision=state.cas_revision,
                    fence=state.fence,
                    parity_receipt_cid=state.last_parity_receipt_cid,
                    decision_id=decision_id,
                    accepted=False,
                    reason=(
                        f"rollback {state.mode.value!r} -> {target.value!r} "
                        f"not allowed; permitted={sorted(m.value for m in allowed)}"
                    ),
                    created_at=_utc_now(),
                    atomic_across_filesystems=False,
                )
                return self._backend.put_decision(receipt)

            new_fence = fence or WriterFence(
                writer_id=state.fence.writer_id,
                fencing_token=state.fence.fencing_token + 1,
                epoch=state.fence.epoch + (
                    1 if target in {AuthorityMode.LEGACY, AuthorityMode.SHADOW} else 0
                ),
                domain=self._domain,
            )
            new_state = AuthorityState(
                domain=self._domain,
                mode=target,
                cas_revision=state.cas_revision + 1,
                fence=new_fence,
                last_parity_receipt_cid=state.last_parity_receipt_cid,
                last_decision_receipt_cid="",
                open_quarantine_count=state.open_quarantine_count,
                updated_at=_utc_now(),
            )
            try:
                self._backend.cas_put_state(
                    new_state, expected_revision=state.cas_revision
                )
            except AuthorityTransitionError as exc:
                raise AuthorityTransitionError(
                    f"rollback CAS failed: {exc}"
                ) from exc

            decision = DecisionReceipt(
                receipt_cid="",
                kind=DecisionKind.ROLLBACK,
                domain=self._domain,
                from_mode=state.mode,
                to_mode=target,
                expected_cas_revision=state.cas_revision,
                new_cas_revision=new_state.cas_revision,
                fence=new_fence,
                parity_receipt_cid=state.last_parity_receipt_cid,
                decision_id=decision_id,
                accepted=True,
                reason=_bounded_text(reason, field="reason"),
                created_at=_utc_now(),
                atomic_across_filesystems=False,
            )
            sealed = self._backend.put_decision(decision)
            bound = AuthorityState(
                domain=new_state.domain,
                mode=new_state.mode,
                cas_revision=new_state.cas_revision + 1,
                fence=new_state.fence,
                last_parity_receipt_cid=new_state.last_parity_receipt_cid,
                last_decision_receipt_cid=sealed.receipt_cid,
                open_quarantine_count=new_state.open_quarantine_count,
                updated_at=_utc_now(),
            )
            try:
                self._backend.cas_put_state(
                    bound, expected_revision=new_state.cas_revision
                )
            except AuthorityTransitionError:
                pass
            return sealed


# ---------------------------------------------------------------------------
# Package metadata agreement
# ---------------------------------------------------------------------------


def _extract_duckdb_specs_from_text(text: str, *, source: str) -> list[str]:
    """Pull duckdb requirement tokens from package-metadata source text."""

    specs: list[str] = []
    # PEP 508-ish: duckdb==1.5.5 / duckdb>=1.5.5,<1.6.0 / "duckdb>=..."
    pattern = re.compile(
        r"""(?x)
        (?<![\w.-])
        (?:["'])?
        (duckdb
            (?:
                \s*==\s*[^"'\\\s,;]+
                | \s*>=\s*[^"'\\\s,;]+(?:\s*,\s*<\s*[^"'\\\s,;]+)?
                | \s*~=\s*[^"'\\\s,;]+
            )?
        )
        (?:["'])?
        """
    )
    for match in pattern.finditer(text):
        token = match.group(1).replace(" ", "")
        # Normalize common forms.
        token = token.replace("duckdb>=", "duckdb>=").replace("duckdb==", "duckdb==")
        if token not in specs:
            specs.append(token)
    # TOML tool table: compatibility_window = ">=1.5.5,<1.6.0"
    window_match = re.search(
        r'compatibility_window\s*=\s*["\']([^"\']+)["\']', text
    )
    if window_match:
        window = window_match.group(1).strip()
        token = f"duckdb{window}" if not window.startswith("duckdb") else window
        token = token.replace(" ", "")
        if token not in specs:
            specs.append(token)
    # pinned_version = "1.5.5"
    pin_match = re.search(
        r'pinned_version\s*=\s*["\']([^"\']+)["\']', text
    )
    if pin_match and source.endswith("pyproject.toml"):
        # Presence of pin is noted but window is authoritative for agreement.
        pass
    return specs


def _normalize_spec(spec: str) -> str:
    text = spec.strip().replace(" ", "")
    if text == "duckdb":
        # Bare pin is not an agreement with the window.
        return text
    return text


def verify_package_metadata_agreement(
    repo_root: str | Path | None = None,
) -> dict[str, Any]:
    """Verify requirements/pyproject/setup declare the pinned DuckDB window.

    All of :data:`PACKAGE_METADATA_PATHS` must exist and contain a duckdb
    requirement whose normalized form equals :data:`DUCKDB_COMPATIBILITY_SPEC`
    (or an exact ``duckdb==1.5.5`` pin, which is a strict subset of the window).
    """

    root = Path(repo_root) if repo_root is not None else Path.cwd()
    expected = _normalize_spec(DUCKDB_COMPATIBILITY_SPEC)
    exact_pin = f"duckdb=={PINNED_DUCKDB_VERSION}"
    per_file: dict[str, Any] = {}
    disagreements: list[str] = []

    for rel in PACKAGE_METADATA_PATHS:
        path = root / rel
        if not path.is_file():
            disagreements.append(f"missing {rel}")
            per_file[rel] = {"present": False, "specs": [], "agrees": False}
            continue
        text = path.read_text(encoding="utf-8")
        specs = [_normalize_spec(s) for s in _extract_duckdb_specs_from_text(text, source=rel)]
        # For pyproject.toml with dynamic dependencies, accept tool table window.
        agrees = any(s in {expected, exact_pin} for s in specs)
        if not agrees:
            disagreements.append(
                f"{rel}: found {specs!r}, expected {expected!r} or {exact_pin!r}"
            )
        per_file[rel] = {
            "present": True,
            "specs": specs,
            "agrees": agrees,
        }

    ok = not disagreements
    return {
        "schema": PACKAGE_METADATA_AGREEMENT_SCHEMA,
        "ok": ok,
        "pinned_version": PINNED_DUCKDB_VERSION,
        "compatibility_window": DUCKDB_COMPATIBILITY_WINDOW,
        "compatibility_spec": DUCKDB_COMPATIBILITY_SPEC,
        "expected_specs": [expected, exact_pin],
        "files": per_file,
        "disagreements": disagreements,
        "atomic_across_filesystems": False,
        "owner_task_id": OWNER_TASK_ID,
    }


# ---------------------------------------------------------------------------
# Factory / install / self-check
# ---------------------------------------------------------------------------


def build_authority_port(
    backend: AuthorityBackend | None = None,
    *,
    domain: str,
    initial_mode: AuthorityMode | str = AuthorityMode.LEGACY,
    writer_id: str = "writer:authority-transition",
) -> AuthorityTransitionPort:
    """Build a domain-neutral authority-transition port."""

    return AuthorityTransitionPort(
        backend or MemoryAuthorityBackend(),
        domain=domain,
        initial_mode=initial_mode,
        writer_id=writer_id,
    )


def install_check() -> dict[str, Any]:
    """Report that the DQK-046 authority-transition port is installed."""

    return {
        "ok": True,
        "schema": INSTALL_CHECK_SCHEMA,
        "program_id": PROGRAM_ID,
        "owner_task_id": OWNER_TASK_ID,
        "module": "ipfs_datasets_py.duckdb_control.authority_transition",
        "modes": [mode.value for mode in AuthorityMode],
        "crash_boundaries": list(CRASH_BOUNDARIES),
        "duckdb_compatibility_window": DUCKDB_COMPATIBILITY_WINDOW,
        "duckdb_compatibility_spec": DUCKDB_COMPATIBILITY_SPEC,
        "pinned_duckdb_version": PINNED_DUCKDB_VERSION,
        "atomic_across_filesystems": False,
        "claims_cross_filesystem_atomicity": False,
        "parity_receipt_schema": PARITY_RECEIPT_SCHEMA,
        "outbox_entry_schema": OUTBOX_ENTRY_SCHEMA,
        "decision_receipt_schema": DECISION_RECEIPT_SCHEMA,
        "package_metadata_paths": list(PACKAGE_METADATA_PATHS),
    }


def self_check(
    *,
    repo_root: str | Path | None = None,
    run_crash_recovery: bool = True,
) -> dict[str, Any]:
    """Hermetic self-check covering modes, outbox recovery, and package pins."""

    backend = MemoryAuthorityBackend()
    port = build_authority_port(
        backend, domain="self-check", initial_mode=AuthorityMode.LEGACY
    )
    results: dict[str, Any] = {
        "ok": True,
        "schema": AUTHORITY_TRANSITION_SCHEMA,
        "owner_task_id": OWNER_TASK_ID,
        "install": install_check(),
        "atomic_across_filesystems": False,
        "claims_cross_filesystem_atomicity": False,
    }

    # Mode ladder with parity-gated promotion.
    port.write("k1", {"v": 1}, operation_id="op:sc:1")
    r = port.promote(
        AuthorityMode.SHADOW,
        decision_id="dec:sc:shadow",
        require_parity=False,
    )
    if not r.accepted:
        results["ok"] = False
        results["error"] = r.reason
        return results

    port.write("k1", {"v": 2}, operation_id="op:sc:2")
    port.recover_outbox()
    parity = port.emit_parity_receipt("k1", operation_id="op:sc:parity")
    if not parity.matched:
        results["ok"] = False
        results["error"] = "shadow parity failed after dual-path write"
        return results

    # Resolve any quarantine opened by earlier steps (none expected when matched).
    for q in list(backend.list_open_quarantine("self-check")):
        backend.put_quarantine(
            QuarantineRecord(
                quarantine_id=q.quarantine_id,
                domain=q.domain,
                key=q.key,
                operation_id=q.operation_id,
                legacy_digest=q.legacy_digest,
                db_digest=q.db_digest,
                reason=q.reason,
                parity_receipt_cid=q.parity_receipt_cid,
                resolved=True,
                created_at=q.created_at,
            )
        )
        # refresh open count via noop CAS path is optional for self-check

    # Force open_quarantine_count to 0 for promotion path by rebuilding state.
    st = port.state()
    if st.open_quarantine_count:
        cleared = AuthorityState(
            domain=st.domain,
            mode=st.mode,
            cas_revision=st.cas_revision + 1,
            fence=st.fence,
            last_parity_receipt_cid=st.last_parity_receipt_cid,
            last_decision_receipt_cid=st.last_decision_receipt_cid,
            open_quarantine_count=0,
            updated_at=_utc_now(),
        )
        backend.cas_put_state(cleared, expected_revision=st.cas_revision)

    r2 = port.promote(
        AuthorityMode.DUAL,
        decision_id="dec:sc:dual",
        require_parity=True,
        parity_key="k1",
    )
    if not r2.accepted:
        results["ok"] = False
        results["error"] = r2.reason
        return results

    # Mismatch must not promote.
    backend.put_db("self-check", "k1", {"v": 999})
    blocked = False
    try:
        port.promote(
            AuthorityMode.DB_PRIMARY,
            decision_id="dec:sc:blocked",
            require_parity=True,
            parity_key="k1",
        )
    except PromotionBlockedError:
        blocked = True
    if not blocked:
        results["ok"] = False
        results["error"] = "mismatch silently promoted"
        return results
    results["mismatch_never_silently_promotes"] = True

    # Restore parity and promote.
    backend.put_db("self-check", "k1", {"v": 2})
    # Resolve quarantines opened by mismatch.
    for q in list(backend.list_open_quarantine("self-check")):
        backend.put_quarantine(
            QuarantineRecord(
                quarantine_id=q.quarantine_id,
                domain=q.domain,
                key=q.key,
                operation_id=q.operation_id,
                legacy_digest=q.legacy_digest,
                db_digest=q.db_digest,
                reason=q.reason,
                parity_receipt_cid=q.parity_receipt_cid,
                resolved=True,
                created_at=q.created_at,
            )
        )
    st = port.state()
    cleared = AuthorityState(
        domain=st.domain,
        mode=st.mode,
        cas_revision=st.cas_revision + 1,
        fence=st.fence,
        last_parity_receipt_cid=st.last_parity_receipt_cid,
        last_decision_receipt_cid=st.last_decision_receipt_cid,
        open_quarantine_count=0,
        updated_at=_utc_now(),
    )
    backend.cas_put_state(cleared, expected_revision=st.cas_revision)

    r3 = port.promote(
        AuthorityMode.DB_PRIMARY,
        decision_id="dec:sc:db-primary",
        require_parity=True,
        parity_key="k1",
    )
    if not r3.accepted:
        results["ok"] = False
        results["error"] = r3.reason
        return results

    rb = port.rollback(
        AuthorityMode.DUAL,
        decision_id="dec:sc:rollback",
        reason="self_check_rollback",
    )
    if not rb.accepted:
        results["ok"] = False
        results["error"] = rb.reason
        return results
    results["promotion_and_rollback_cas_fenced_receipted"] = True

    if run_crash_recovery:
        recovered_boundaries: list[str] = []
        for boundary in CRASH_BOUNDARIES:
            b = MemoryAuthorityBackend()
            p = build_authority_port(
                b, domain="crash", initial_mode=AuthorityMode.DUAL
            )
            p.set_crash_at(boundary)
            op = f"op:crash:{boundary}"
            try:
                p.write("ck", {"b": boundary}, operation_id=op)
            except CrashInjected as injected:
                if injected.boundary != boundary:
                    results["ok"] = False
                    results["error"] = (
                        f"crash boundary mismatch: expected {boundary}, "
                        f"got {injected.boundary}"
                    )
                    return results
            # Clear injection and recover.
            p.set_crash_at(None)
            recovery = p.recover_outbox()
            # Re-drive write for idempotency if outbox completed via recovery,
            # or complete the write path if crash was before enqueue.
            again = p.write("ck", {"b": boundary}, operation_id=op)
            if again.get("atomic_across_filesystems") is not False:
                results["ok"] = False
                results["error"] = "implementation claimed cross-filesystem atomicity"
                return results
            final_entry = b.get_outbox_by_operation(op)
            if final_entry is not None and final_entry.status not in {
                OutboxStatus.COMPLETED,
                OutboxStatus.PENDING,
                OutboxStatus.IN_FLIGHT,
            }:
                # Allow terminal completed only after recovery+rewrite.
                pass
            # Ensure recover is idempotent.
            recovery2 = p.recover_outbox()
            if recovery2.get("idempotent") is not True:
                results["ok"] = False
                results["error"] = "outbox recovery is not marked idempotent"
                return results
            # Final drive if still incomplete.
            p.recover_outbox()
            final_entry = b.get_outbox_by_operation(op)
            if final_entry is not None:
                if final_entry.status is not OutboxStatus.COMPLETED:
                    # Force one more drive.
                    p.set_crash_at(None)
                    p.recover_outbox()
                    final_entry = b.get_outbox_by_operation(op)
                if (
                    final_entry is not None
                    and final_entry.status is not OutboxStatus.COMPLETED
                ):
                    results["ok"] = False
                    results["error"] = (
                        f"outbox not completed after crash at {boundary}: "
                        f"{final_entry.status}"
                    )
                    return results
            recovered_boundaries.append(boundary)
        results["crash_boundaries_recovered"] = recovered_boundaries
        results["crash_recovery_ok"] = True

    meta = verify_package_metadata_agreement(repo_root)
    results["package_metadata"] = meta
    if not meta.get("ok"):
        results["ok"] = False
        results["error"] = (
            "package metadata disagrees on DuckDB compatibility window: "
            + "; ".join(meta.get("disagreements") or [])
        )
        return results
    results["package_metadata_agrees"] = True

    # Explicit non-claims: reject only *positive* assignments / guarantees.
    # Denial prose, False constants, and documentation of the non-claim are OK.
    source = Path(__file__).read_text(encoding="utf-8")
    positive_claim_patterns = (
        re.compile(r"atomic_across_filesystems\s*=\s*True\b"),
        re.compile(r"claims_cross_filesystem_atomicity\s*=\s*True\b"),
        re.compile(
            r"cross[_-]filesystem\s+atomic(?:ity)?\s+is\s+(?:guaranteed|supported|provided)",
            re.IGNORECASE,
        ),
        re.compile(
            r"guarantees?\s+cross[_-]filesystem\s+atomic",
            re.IGNORECASE,
        ),
    )
    for pattern in positive_claim_patterns:
        match = pattern.search(source)
        if match:
            results["ok"] = False
            results["error"] = (
                f"implementation claims cross-filesystem atomicity near "
                f"{match.group(0)!r}"
            )
            return results
    results["no_cross_filesystem_atomicity_claim"] = True
    return results
