"""DuckDB repository/event port for legacy data-wallet producers (DQK-074).

Integrates wallet repository, service, API, CLI, analytics, audit, and
manifest mutations through a shadow DuckDB projection while encrypted
payload bytes remain in the content-addressed blob store (never DuckDB
or Quack).

Authority model (shadow mode by default):

* **Legacy authority** — wallet JSON envelopes and analytics-ledger.json
  remain the restorable truth for exact round-trips (via
  :class:`LocalWalletRepository`).
* **DuckDB shadow** — redacted public metadata projections only: wallet
  descriptors, storage *references*, audit/grant/approval public fields,
  analytics aggregates.  Plaintext, principal secrets, key wraps, wrapped
  DEKs, and ciphertext blobs are excluded from every query-visible surface.
* **Parity** — every mutation is bound to an idempotent ``operation_id`` and
  emits a :class:`~ipfs_datasets_py.duckdb_control.authority_transition.ParityReceipt`
  comparing legacy and DuckDB digests of the *redacted* projection.

Importing this module is inert: no DuckDB, network, or filesystem I/O.
The default process-local backend is pure Python so integration tests
exercise the full contract without a live DuckDB extension.
"""

from __future__ import annotations

import hashlib
import json
import threading
import uuid
from collections.abc import Mapping, MutableMapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Final, Iterable, Optional, Protocol

from ipfs_datasets_py.duckdb_control.authority_transition import (
    AuthorityBackend,
    AuthorityMode,
    AuthorityTransitionPort,
    MemoryAuthorityBackend,
    ParityReceipt,
    build_authority_port,
    compute_payload_digest,
)
from ipfs_datasets_py.duckdb_control.publication import (
    WALLET_RAW_COLUMNS,
    is_wallet_raw_column,
)

from .manifest import canonical_bytes, canonical_dumps


def _hex_digest(data: bytes) -> str:
    """Hex SHA-256 without importing the cryptography-backed crypto module."""

    return hashlib.sha256(data).hexdigest()

# ---------------------------------------------------------------------------
# Schema / interface pins
# ---------------------------------------------------------------------------

WALLET_DUCKDB_REPOSITORY_INTERFACE: Final = "WalletDuckDBRepository@1"
WALLET_DUCKDB_REPOSITORY_SCHEMA_VERSION: Final = "wallet-duckdb-repository/v1"
WALLET_DATA_DOMAIN: Final = "data-wallet"
OWNER_TASK_ID: Final = "DQK-074"

# Catalog tables for the data-wallet metadata projection (no secret-bearing
# body columns; encrypted bytes stay in the blob store).
WALLET_DATA_CATALOG_NAME: Final = "data_wallet"
WALLET_DATA_CATALOG_TABLES: Final[tuple[str, ...]] = (
    "wallet_snapshots",
    "wallet_records",
    "wallet_versions",
    "wallet_grants",
    "wallet_audit_events",
    "wallet_approvals",
    "analytics_ledger",
    "mutation_events",
    "parity_receipts",
    "encrypted_object_refs",
)

WALLET_DATA_CATALOG_DDL: Final[str] = """
CREATE TABLE IF NOT EXISTS wallet_snapshots (
    wallet_id VARCHAR PRIMARY KEY,
    snapshot_hash VARCHAR NOT NULL,
    projection_digest VARCHAR NOT NULL,
    revision BIGINT NOT NULL,
    record_count INTEGER NOT NULL,
    grant_count INTEGER NOT NULL,
    audit_event_count INTEGER NOT NULL,
    owner_did VARCHAR NOT NULL,
    updated_at VARCHAR NOT NULL,
    schema_version VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS wallet_records (
    record_id VARCHAR PRIMARY KEY,
    wallet_id VARCHAR NOT NULL,
    data_type VARCHAR NOT NULL,
    sensitivity VARCHAR NOT NULL,
    public_descriptor VARCHAR NOT NULL,
    current_version_id VARCHAR NOT NULL,
    status VARCHAR NOT NULL,
    created_at VARCHAR NOT NULL,
    updated_at VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS wallet_versions (
    version_id VARCHAR PRIMARY KEY,
    record_id VARCHAR NOT NULL,
    wallet_id VARCHAR NOT NULL,
    ciphertext_hash VARCHAR NOT NULL,
    encryption_suite VARCHAR NOT NULL,
    payload_uri VARCHAR NOT NULL,
    payload_sha256 VARCHAR NOT NULL,
    payload_size_bytes BIGINT NOT NULL,
    metadata_uri VARCHAR,
    metadata_sha256 VARCHAR,
    key_wrap_count INTEGER NOT NULL,
    created_at VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS wallet_grants (
    grant_id VARCHAR PRIMARY KEY,
    wallet_id VARCHAR NOT NULL,
    issuer_did VARCHAR NOT NULL,
    audience_did VARCHAR NOT NULL,
    status VARCHAR NOT NULL,
    created_at VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS wallet_audit_events (
    event_id VARCHAR PRIMARY KEY,
    wallet_id VARCHAR NOT NULL,
    actor_did VARCHAR NOT NULL,
    action VARCHAR NOT NULL,
    resource VARCHAR NOT NULL,
    decision VARCHAR NOT NULL,
    hash_self VARCHAR NOT NULL,
    hash_prev VARCHAR NOT NULL,
    created_ordinal INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS wallet_approvals (
    approval_id VARCHAR PRIMARY KEY,
    wallet_id VARCHAR NOT NULL,
    operation VARCHAR NOT NULL,
    status VARCHAR NOT NULL,
    created_at VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS analytics_ledger (
    ledger_key VARCHAR PRIMARY KEY,
    ledger_hash VARCHAR NOT NULL,
    projection_digest VARCHAR NOT NULL,
    subject_count INTEGER NOT NULL,
    template_count INTEGER NOT NULL,
    contribution_count INTEGER NOT NULL,
    result_count INTEGER NOT NULL,
    updated_at VARCHAR NOT NULL,
    schema_version VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS mutation_events (
    operation_id VARCHAR PRIMARY KEY,
    wallet_id VARCHAR NOT NULL,
    action VARCHAR NOT NULL,
    resource VARCHAR NOT NULL,
    actor_did VARCHAR NOT NULL,
    decision VARCHAR NOT NULL,
    projection_key VARCHAR NOT NULL,
    projection_digest VARCHAR NOT NULL,
    parity_receipt_cid VARCHAR NOT NULL,
    parity_matched BOOLEAN NOT NULL,
    mode VARCHAR NOT NULL,
    created_at VARCHAR NOT NULL,
    schema_version VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS parity_receipts (
    receipt_cid VARCHAR PRIMARY KEY,
    operation_id VARCHAR NOT NULL,
    projection_key VARCHAR NOT NULL,
    legacy_digest VARCHAR NOT NULL,
    db_digest VARCHAR NOT NULL,
    matched BOOLEAN NOT NULL,
    mismatch_reason VARCHAR NOT NULL,
    mode VARCHAR NOT NULL,
    created_at VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS encrypted_object_refs (
    ref_id VARCHAR PRIMARY KEY,
    wallet_id VARCHAR NOT NULL,
    record_id VARCHAR NOT NULL,
    version_id VARCHAR NOT NULL,
    role VARCHAR NOT NULL,
    uri VARCHAR NOT NULL,
    storage_type VARCHAR NOT NULL,
    sha256 VARCHAR NOT NULL,
    size_bytes BIGINT NOT NULL
);
""".strip()

# Forbidden substrings / keys that must never appear in query publications.
FORBIDDEN_QUERY_KEYS: Final[frozenset[str]] = frozenset(
    {
        "plaintext",
        "principal_secrets",
        "principal_secret",
        "key_wraps",
        "key_wrap",
        "wrapped_dek",
        "ciphertext",
        "ciphertext_blob",
        "encrypted_bundle",
        "encrypted_bytes",
        "encrypted_payload",
        "encrypted_seed",
        "actor_secret",
        "owner_secret",
        "private_key",
        "private_keys",
        "signing_key",
        "signing_payload",
        "seed_phrase",
        "recovery_phrase",
        "mnemonic",
        "wallet_secret",
        "wallet_raw",
        "raw_payload",
        "nonce",  # AEAD nonce of encrypted blobs
    }
) | frozenset(WALLET_RAW_COLUMNS)

# Keys retained on StorageRef projections (references only — no bytes).
_STORAGE_REF_KEYS: Final[frozenset[str]] = frozenset(
    {"uri", "storage_type", "size_bytes", "sha256", "created_at"}
)

ANALYTICS_LEDGER_KEY: Final = "analytics-ledger"
MUTATION_RECEIPT_SCHEMA: Final = "wallet-mutation-receipt/v1"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class WalletDuckDBRepositoryError(ValueError):
    """Raised when a wallet DuckDB repository operation fails closed."""


class WalletPublicationSafetyError(WalletDuckDBRepositoryError):
    """Raised when plaintext, keys, wraps, or encrypted bytes would leak."""


# ---------------------------------------------------------------------------
# Enums / receipts
# ---------------------------------------------------------------------------


class MutationKind(StrEnum):
    """Closed set of data-wallet mutation kinds recorded by the event port."""

    SERVICE = "service"
    REPOSITORY = "repository"
    API = "api"
    CLI = "cli"
    ANALYTICS = "analytics"
    AUDIT = "audit"
    MANIFEST = "manifest"


@dataclass(frozen=True, slots=True)
class MutationReceipt:
    """Idempotent operation receipt bound to a parity comparison."""

    operation_id: str
    wallet_id: str
    action: str
    resource: str
    actor_did: str
    decision: str
    kind: MutationKind
    projection_key: str
    projection_digest: str
    parity_receipt_cid: str
    parity_matched: bool
    mode: str
    payload_digest: str
    idempotent_replay: bool = False
    outbox_id: str = ""
    created_at: str = ""
    schema: str = MUTATION_RECEIPT_SCHEMA
    atomic_across_filesystems: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "operation_id": self.operation_id,
            "wallet_id": self.wallet_id,
            "action": self.action,
            "resource": self.resource,
            "actor_did": self.actor_did,
            "decision": self.decision,
            "kind": self.kind.value if isinstance(self.kind, MutationKind) else str(self.kind),
            "projection_key": self.projection_key,
            "projection_digest": self.projection_digest,
            "parity_receipt_cid": self.parity_receipt_cid,
            "parity_matched": self.parity_matched,
            "mode": self.mode,
            "payload_digest": self.payload_digest,
            "idempotent_replay": self.idempotent_replay,
            "outbox_id": self.outbox_id,
            "created_at": self.created_at,
            "atomic_across_filesystems": False,
        }


# ---------------------------------------------------------------------------
# Redaction / projection helpers
# ---------------------------------------------------------------------------


def _sha256_digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


# Content digests and reference hashes are public; only secret-bearing names fail.
_ALLOWED_HASH_SUFFIXES: Final[tuple[str, ...]] = (
    "_hash",
    "_digest",
    "_sha256",
    "sha256",
    "hash_self",
    "hash_prev",
    "snapshot_hash",
    "ciphertext_hash",  # digest of ciphertext, never the bytes
)


def _is_forbidden_key(name: str) -> bool:
    lower = str(name).lower()
    # Explicit allow-list for integrity digests and non-secret wrap *counts*.
    if lower in {
        "ciphertext_hash",
        "payload_sha256",
        "metadata_sha256",
        "snapshot_hash",
        "key_wrap_count",
        "wrap_count",
    }:
        return False
    if lower in FORBIDDEN_QUERY_KEYS:
        return True
    if is_wallet_raw_column(lower):
        return True
    # Substring markers for wrap/ciphertext/secret material.
    markers = (
        "plaintext",
        "principal_secret",
        "wrapped_dek",
        "key_wrap",
        "encrypted_bundle",
        "encrypted_bytes",
        "private_key",
        "signing_key",
        "seed_phrase",
        "mnemonic",
        "wallet_raw",
        "raw_payload",
    )
    if any(marker in lower for marker in markers):
        return True
    # "ciphertext" alone (not *_hash) is forbidden.
    if "ciphertext" in lower and not lower.endswith("_hash") and "hash" not in lower:
        return True
    return False


def redact_for_query_publication(value: Any, *, _path: str = "") -> Any:
    """Deep-redact a structure so query publications exclude secrets.

    Removes plaintext, principal secrets, key wraps, wrapped DEKs, and
    encrypted byte fields while preserving storage *references* and public
    metadata needed for parity and analytics.
    """

    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for key, item in value.items():
            key_s = str(key)
            if _is_forbidden_key(key_s):
                continue
            # Drop AEAD ciphertext containers; keep only suite metadata if present.
            if key_s in {"encrypted_payload_ref", "encrypted_metadata_ref", "proof_artifact_ref"}:
                if isinstance(item, Mapping):
                    out[key_s] = _project_storage_ref(item)
                elif item is None:
                    out[key_s] = None
                continue
            if key_s == "mirrors" and isinstance(item, list):
                out[key_s] = [
                    _project_storage_ref(m) if isinstance(m, Mapping) else m for m in item
                ]
                continue
            out[key_s] = redact_for_query_publication(item, _path=f"{_path}.{key_s}")
        return out
    if isinstance(value, (list, tuple)):
        return [redact_for_query_publication(item, _path=_path) for item in value]
    if isinstance(value, (bytes, bytearray)):
        raise WalletPublicationSafetyError(
            f"raw bytes at {_path or '<root>'} must never enter query publications"
        )
    return value


def _project_storage_ref(ref: Mapping[str, Any]) -> dict[str, Any]:
    projected = {k: ref[k] for k in _STORAGE_REF_KEYS if k in ref}
    mirrors = ref.get("mirrors")
    if isinstance(mirrors, list):
        projected["mirrors"] = [
            _project_storage_ref(m) if isinstance(m, Mapping) else m for m in mirrors
        ]
    return projected


def project_wallet_snapshot_for_query(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Project a full wallet snapshot into a query-safe shadow document.

    Exact restorable state stays in legacy JSON; this projection is the
    authority-port payload used for shadow writes and parity digests.
    """

    if not isinstance(snapshot, Mapping):
        raise WalletDuckDBRepositoryError("wallet snapshot must be an object")

    wallet = snapshot.get("wallet") or {}
    if not isinstance(wallet, Mapping):
        raise WalletDuckDBRepositoryError("wallet snapshot missing wallet object")

    records = list(snapshot.get("records") or [])
    versions_raw = list(snapshot.get("versions") or [])
    grants = list(snapshot.get("grants") or [])
    audit_events = list(snapshot.get("audit_events") or [])
    approvals = list(snapshot.get("approvals") or [])

    projected_versions: list[dict[str, Any]] = []
    encrypted_refs: list[dict[str, Any]] = []
    for version in versions_raw:
        if not isinstance(version, Mapping):
            continue
        payload_ref = version.get("encrypted_payload_ref") or {}
        metadata_ref = version.get("encrypted_metadata_ref")
        key_wraps = version.get("key_wraps") or []
        wrap_count = len(key_wraps) if isinstance(key_wraps, list) else 0
        projected_versions.append(
            {
                "version_id": version.get("version_id"),
                "record_id": version.get("record_id"),
                "ciphertext_hash": version.get("ciphertext_hash"),
                "encryption_suite": version.get("encryption_suite"),
                "payload_uri": (payload_ref or {}).get("uri") if isinstance(payload_ref, Mapping) else None,
                "payload_sha256": (payload_ref or {}).get("sha256") if isinstance(payload_ref, Mapping) else None,
                "payload_size_bytes": (payload_ref or {}).get("size_bytes") if isinstance(payload_ref, Mapping) else None,
                "metadata_uri": (
                    metadata_ref.get("uri") if isinstance(metadata_ref, Mapping) else None
                ),
                "metadata_sha256": (
                    metadata_ref.get("sha256") if isinstance(metadata_ref, Mapping) else None
                ),
                "key_wrap_count": wrap_count,
                "derived_artifact_ids": list(version.get("derived_artifact_ids") or []),
                "proof_receipt_ids": list(version.get("proof_receipt_ids") or []),
                "created_at": version.get("created_at"),
            }
        )
        if isinstance(payload_ref, Mapping) and payload_ref.get("uri"):
            encrypted_refs.append(
                {
                    "ref_id": f"payload:{version.get('version_id')}",
                    "record_id": version.get("record_id"),
                    "version_id": version.get("version_id"),
                    "role": "payload",
                    **_project_storage_ref(payload_ref),
                }
            )
        if isinstance(metadata_ref, Mapping) and metadata_ref.get("uri"):
            encrypted_refs.append(
                {
                    "ref_id": f"metadata:{version.get('version_id')}",
                    "record_id": version.get("record_id"),
                    "version_id": version.get("version_id"),
                    "role": "metadata",
                    **_project_storage_ref(metadata_ref),
                }
            )

    # Public-ish collections — strip forbidden keys recursively.
    public_sections = {
        "records": [redact_for_query_publication(r) for r in records if isinstance(r, Mapping)],
        "grants": [redact_for_query_publication(g) for g in grants if isinstance(g, Mapping)],
        "grant_receipts": [
            redact_for_query_publication(g)
            for g in (snapshot.get("grant_receipts") or [])
            if isinstance(g, Mapping)
        ],
        "invocations": [
            redact_for_query_publication(i)
            for i in (snapshot.get("invocations") or [])
            if isinstance(i, Mapping)
        ],
        "derived_artifacts": [
            redact_for_query_publication(a)
            for a in (snapshot.get("derived_artifacts") or [])
            if isinstance(a, Mapping)
        ],
        "proofs": [
            redact_for_query_publication(p)
            for p in (snapshot.get("proofs") or [])
            if isinstance(p, Mapping)
        ],
        "analytics_consents": [
            redact_for_query_publication(c)
            for c in (snapshot.get("analytics_consents") or [])
            if isinstance(c, Mapping)
        ],
        "approvals": [redact_for_query_publication(a) for a in approvals if isinstance(a, Mapping)],
        "access_requests": [
            redact_for_query_publication(a)
            for a in (snapshot.get("access_requests") or [])
            if isinstance(a, Mapping)
        ],
        "audit_events": [
            redact_for_query_publication(e) for e in audit_events if isinstance(e, Mapping)
        ],
        "world_id_bindings": [
            redact_for_query_publication(b)
            for b in (snapshot.get("world_id_bindings") or [])
            if isinstance(b, Mapping)
        ],
        "saved_services": [
            redact_for_query_publication(s)
            for s in (snapshot.get("saved_services") or [])
            if isinstance(s, Mapping)
        ],
        "service_interactions": [
            redact_for_query_publication(s)
            for s in (snapshot.get("service_interactions") or [])
            if isinstance(s, Mapping)
        ],
        "service_plans": [
            redact_for_query_publication(s)
            for s in (snapshot.get("service_plans") or [])
            if isinstance(s, Mapping)
        ],
        "record_metadata": [
            redact_for_query_publication(m)
            for m in (snapshot.get("record_metadata") or [])
            if isinstance(m, Mapping)
        ],
        # Recovery bundles: public metadata only — never encrypted_bundle body.
        "recovery_bundles": [
            {
                "bundle_id": b.get("bundle_id"),
                "wallet_id": b.get("wallet_id"),
                "wrapping_method": b.get("wrapping_method"),
                "recovery_hint": b.get("recovery_hint"),
                "public_metadata": redact_for_query_publication(b.get("public_metadata") or {}),
                "created_at": b.get("created_at"),
            }
            for b in (snapshot.get("recovery_bundles") or [])
            if isinstance(b, Mapping)
        ],
    }

    projection = {
        "projection_type": "wallet_query_projection_v1",
        "schema_version": WALLET_DUCKDB_REPOSITORY_SCHEMA_VERSION,
        "wallet_id": wallet.get("wallet_id"),
        "wallet": redact_for_query_publication(dict(wallet)),
        "versions": projected_versions,
        "encrypted_object_refs": encrypted_refs,
        "counts": {
            "records": len(records),
            "versions": len(projected_versions),
            "grants": len(grants),
            "audit_events": len(audit_events),
            "approvals": len(approvals),
            "wraps_excluded": sum(
                len(v.get("key_wraps") or [])
                for v in versions_raw
                if isinstance(v, Mapping)
            ),
        },
        # principal_secrets intentionally omitted from query publications
        "principal_holder_count": len(snapshot.get("principal_secret_dids") or []),
        **public_sections,
    }
    assert_query_publication_safe(projection)
    return projection


def project_analytics_ledger_for_query(ledger: Mapping[str, Any]) -> dict[str, Any]:
    """Project an analytics ledger into a query-safe shadow document."""

    if not isinstance(ledger, Mapping):
        raise WalletDuckDBRepositoryError("analytics ledger must be an object")
    projection = {
        "projection_type": "wallet_analytics_ledger_projection_v1",
        "schema_version": WALLET_DUCKDB_REPOSITORY_SCHEMA_VERSION,
        "ledger_type": ledger.get("ledger_type"),
        "subject_count": ledger.get("subject_count"),
        "subject_id_policy": ledger.get("subject_id_policy"),
        "analytics_templates": [
            redact_for_query_publication(t)
            for t in (ledger.get("analytics_templates") or [])
            if isinstance(t, Mapping)
        ],
        "analytics_consents": [
            redact_for_query_publication(c)
            for c in (ledger.get("analytics_consents") or [])
            if isinstance(c, Mapping)
        ],
        "analytics_contributions": [
            redact_for_query_publication(c)
            for c in (ledger.get("analytics_contributions") or [])
            if isinstance(c, Mapping)
        ],
        "aggregate_results": [
            redact_for_query_publication(r)
            for r in (ledger.get("aggregate_results") or [])
            if isinstance(r, Mapping)
        ],
        "analytics_query_budget_spent": dict(
            sorted((ledger.get("analytics_query_budget_spent") or {}).items())
        ),
    }
    # Never carry private wallet_ids list into query publications.
    assert_query_publication_safe(projection)
    return projection


def assert_query_publication_safe(document: Any, *, path: str = "$") -> None:
    """Fail closed if forbidden keys or raw bytes appear in a publication."""

    if isinstance(document, Mapping):
        for key, value in document.items():
            key_s = str(key)
            if _is_forbidden_key(key_s):
                raise WalletPublicationSafetyError(
                    f"forbidden key {key_s!r} at {path} in query publication"
                )
            assert_query_publication_safe(value, path=f"{path}.{key_s}")
        return
    if isinstance(document, (list, tuple)):
        for index, item in enumerate(document):
            assert_query_publication_safe(item, path=f"{path}[{index}]")
        return
    if isinstance(document, (bytes, bytearray)):
        raise WalletPublicationSafetyError(
            f"raw bytes at {path} must never enter query publications"
        )
    if isinstance(document, str):
        # Detect hex-looking 32-byte secrets and base64 ciphertext blobs is
        # heuristic; structural key exclusion is the primary defense.
        return


def projection_digest(projection: Mapping[str, Any]) -> str:
    """Stable content digest of a query projection."""

    return _sha256_digest(canonical_bytes(dict(projection)))


def new_operation_id(prefix: str = "op") -> str:
    """Allocate a fresh idempotent operation id."""

    return f"{prefix}:{uuid.uuid4().hex}"


# ---------------------------------------------------------------------------
# Optional DuckDB connection protocol
# ---------------------------------------------------------------------------


class _DuckDBConnection(Protocol):
    def execute(self, query: str, parameters: Any = None) -> Any: ...

    def executemany(self, query: str, parameters: Any = None) -> Any: ...


# ---------------------------------------------------------------------------
# Repository / event port
# ---------------------------------------------------------------------------


@dataclass
class WalletDuckDBRepository:
    """Shadow DuckDB event port for data-wallet producers.

    Parameters
    ----------
    mode:
        Authority mode; defaults to ``shadow`` (JSON remains authority).
    backend:
        Optional shared :class:`AuthorityBackend` (defaults to memory).
    connection:
        Optional live DuckDB connection that receives catalog DDL + row upserts.
    domain:
        Authority-transition domain token (default ``data-wallet``).
    """

    mode: AuthorityMode | str = AuthorityMode.SHADOW
    backend: AuthorityBackend | None = None
    connection: Any | None = None
    domain: str = WALLET_DATA_DOMAIN
    writer_id: str = "writer:data-wallet"
    _port: AuthorityTransitionPort = field(init=False, repr=False)
    _lock: threading.RLock = field(default_factory=threading.RLock, init=False, repr=False)
    _mutation_index: dict[str, MutationReceipt] = field(
        default_factory=dict, init=False, repr=False
    )
    _revisions: dict[str, int] = field(default_factory=dict, init=False, repr=False)
    _installed_ddl: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        backend = self.backend if self.backend is not None else MemoryAuthorityBackend()
        object.__setattr__(self, "backend", backend)
        mode = (
            self.mode
            if isinstance(self.mode, AuthorityMode)
            else AuthorityMode.parse(str(self.mode))
        )
        object.__setattr__(self, "mode", mode)
        port = build_authority_port(
            backend,
            domain=self.domain,
            initial_mode=mode,
            writer_id=self.writer_id,
        )
        object.__setattr__(self, "_port", port)
        if self.connection is not None:
            self.install_catalog(self.connection)

    # -- properties ---------------------------------------------------------

    @property
    def interface(self) -> str:
        return WALLET_DUCKDB_REPOSITORY_INTERFACE

    @property
    def schema_version(self) -> str:
        return WALLET_DUCKDB_REPOSITORY_SCHEMA_VERSION

    @property
    def authority_port(self) -> AuthorityTransitionPort:
        return self._port

    @property
    def authority_mode(self) -> AuthorityMode:
        return self._port.mode

    # -- catalog ------------------------------------------------------------

    def install_catalog(self, connection: Any | None = None) -> dict[str, Any]:
        """Install wallet data-wallet catalog DDL on a DuckDB connection."""

        conn = connection if connection is not None else self.connection
        if conn is None:
            return {
                "ok": True,
                "installed": False,
                "reason": "no_connection",
                "tables": list(WALLET_DATA_CATALOG_TABLES),
                "schema_version": WALLET_DUCKDB_REPOSITORY_SCHEMA_VERSION,
            }
        with self._lock:
            for statement in WALLET_DATA_CATALOG_DDL.split(";"):
                sql = statement.strip()
                if sql:
                    conn.execute(sql)
            self._installed_ddl = True
        return {
            "ok": True,
            "installed": True,
            "tables": list(WALLET_DATA_CATALOG_TABLES),
            "schema_version": WALLET_DUCKDB_REPOSITORY_SCHEMA_VERSION,
            "catalog": WALLET_DATA_CATALOG_NAME,
        }

    # -- mutation recording -------------------------------------------------

    def record_mutation(
        self,
        *,
        action: str,
        resource: str,
        wallet_id: str = "",
        actor_did: str = "",
        decision: str = "allow",
        kind: MutationKind | str = MutationKind.SERVICE,
        operation_id: str | None = None,
        projection: Mapping[str, Any] | None = None,
        projection_key: str | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> MutationReceipt:
        """Record one idempotent mutation with a parity receipt.

        When *projection* is omitted a minimal mutation envelope is written so
        every service mutation still obtains an operation id + parity receipt.
        Callers that hold a full snapshot should pass a query projection
        produced by :func:`project_wallet_snapshot_for_query`.
        """

        op_id = operation_id or new_operation_id("op")
        kind_enum = kind if isinstance(kind, MutationKind) else MutationKind(str(kind))
        key = projection_key or (
            f"wallet:{wallet_id}" if wallet_id else f"mutation:{kind_enum.value}"
        )

        with self._lock:
            prior = self._mutation_index.get(op_id)
            if prior is not None:
                return MutationReceipt(
                    operation_id=prior.operation_id,
                    wallet_id=prior.wallet_id,
                    action=prior.action,
                    resource=prior.resource,
                    actor_did=prior.actor_did,
                    decision=prior.decision,
                    kind=prior.kind,
                    projection_key=prior.projection_key,
                    projection_digest=prior.projection_digest,
                    parity_receipt_cid=prior.parity_receipt_cid,
                    parity_matched=prior.parity_matched,
                    mode=prior.mode,
                    payload_digest=prior.payload_digest,
                    idempotent_replay=True,
                    outbox_id=prior.outbox_id,
                    created_at=prior.created_at,
                )

            if projection is None:
                body = {
                    "projection_type": "wallet_mutation_envelope_v1",
                    "schema_version": WALLET_DUCKDB_REPOSITORY_SCHEMA_VERSION,
                    "wallet_id": wallet_id,
                    "action": action,
                    "resource": resource,
                    "actor_did": actor_did,
                    "decision": decision,
                    "kind": kind_enum.value,
                    "details": redact_for_query_publication(dict(details or {})),
                }
            else:
                body = redact_for_query_publication(dict(projection))
            assert_query_publication_safe(body)
            digest = projection_digest(body)

            write_result = self._port.write(key, body, operation_id=op_id)
            parity = self._port.emit_parity_receipt(key, operation_id=op_id)

            receipt = MutationReceipt(
                operation_id=op_id,
                wallet_id=wallet_id or "",
                action=action,
                resource=resource,
                actor_did=actor_did or "",
                decision=decision,
                kind=kind_enum,
                projection_key=key,
                projection_digest=digest,
                parity_receipt_cid=parity.receipt_cid,
                parity_matched=bool(parity.matched),
                mode=str(write_result.get("mode") or self._port.mode.value),
                payload_digest=str(write_result.get("payload_digest") or digest),
                idempotent_replay=bool(write_result.get("idempotent_replay")),
                outbox_id=str(write_result.get("outbox_id") or ""),
                created_at=_utc_now(),
            )
            self._mutation_index[op_id] = receipt
            self._revisions[key] = self._revisions.get(key, 0) + 1
            self._mirror_mutation_rows(receipt, body)
            return receipt

    def record_service_mutation(
        self,
        *,
        wallet_id: str,
        action: str,
        resource: str,
        actor_did: str = "",
        decision: str = "allow",
        details: Mapping[str, Any] | None = None,
        operation_id: str | None = None,
        service: Any | None = None,
    ) -> MutationReceipt:
        """Record a service-layer mutation; optionally project full wallet state."""

        projection: Mapping[str, Any] | None = None
        projection_key = f"wallet:{wallet_id}" if wallet_id else None
        if service is not None and wallet_id and wallet_id in getattr(service, "wallets", {}):
            try:
                snapshot = service.export_wallet_snapshot(wallet_id)
                projection = project_wallet_snapshot_for_query(snapshot)
            except Exception:
                # Fail soft on projection (e.g. mid-import); still record envelope.
                projection = None
        return self.record_mutation(
            action=action,
            resource=resource,
            wallet_id=wallet_id,
            actor_did=actor_did,
            decision=decision,
            kind=MutationKind.SERVICE,
            operation_id=operation_id,
            projection=projection,
            projection_key=projection_key,
            details=details,
        )

    def shadow_wallet_snapshot(
        self,
        snapshot: Mapping[str, Any],
        *,
        operation_id: str | None = None,
        kind: MutationKind | str = MutationKind.REPOSITORY,
        action: str = "repository/wallet_snapshot",
        actor_did: str = "",
    ) -> MutationReceipt:
        """Shadow-project one wallet snapshot and emit parity."""

        wallet = snapshot.get("wallet") if isinstance(snapshot, Mapping) else None
        wallet_id = ""
        if isinstance(wallet, Mapping):
            wallet_id = str(wallet.get("wallet_id") or "")
        if not wallet_id:
            wallet_id = str(snapshot.get("wallet_id") or "")
        if not wallet_id:
            raise WalletDuckDBRepositoryError("snapshot missing wallet_id")
        projection = project_wallet_snapshot_for_query(snapshot)
        return self.record_mutation(
            action=action,
            resource=f"wallet://{wallet_id}/manifest",
            wallet_id=wallet_id,
            actor_did=actor_did,
            kind=kind,
            operation_id=operation_id,
            projection=projection,
            projection_key=f"wallet:{wallet_id}",
        )

    def shadow_analytics_ledger(
        self,
        ledger: Mapping[str, Any],
        *,
        operation_id: str | None = None,
        kind: MutationKind | str = MutationKind.ANALYTICS,
        action: str = "repository/analytics_ledger",
        actor_did: str = "",
    ) -> MutationReceipt:
        """Shadow-project the analytics ledger and emit parity."""

        projection = project_analytics_ledger_for_query(ledger)
        return self.record_mutation(
            action=action,
            resource="wallet://analytics/ledger",
            wallet_id="",
            actor_did=actor_did,
            kind=kind,
            operation_id=operation_id,
            projection=projection,
            projection_key=ANALYTICS_LEDGER_KEY,
        )

    def shadow_service(
        self,
        service: Any,
        wallet_id: str,
        *,
        operation_id: str | None = None,
        kind: MutationKind | str = MutationKind.REPOSITORY,
        action: str = "repository/wallet_snapshot",
        actor_did: str = "",
    ) -> MutationReceipt:
        """Export + shadow a live service wallet."""

        snapshot = service.export_wallet_snapshot(wallet_id)
        return self.shadow_wallet_snapshot(
            snapshot,
            operation_id=operation_id,
            kind=kind,
            action=action,
            actor_did=actor_did,
        )

    def shadow_service_analytics(
        self,
        service: Any,
        *,
        operation_id: str | None = None,
        kind: MutationKind | str = MutationKind.ANALYTICS,
        action: str = "repository/analytics_ledger",
        actor_did: str = "",
        redact_subjects: bool = True,
    ) -> MutationReceipt:
        ledger = service.export_analytics_ledger(redact_subjects=redact_subjects)
        return self.shadow_analytics_ledger(
            ledger,
            operation_id=operation_id,
            kind=kind,
            action=action,
            actor_did=actor_did,
        )

    # -- reads / query publications -----------------------------------------

    def get_projection(self, key: str) -> Mapping[str, Any] | None:
        """Read the authoritative projection for *key* under the current mode."""

        return self._port.read(key)

    def get_wallet_projection(self, wallet_id: str) -> Mapping[str, Any] | None:
        return self.get_projection(f"wallet:{wallet_id}")

    def get_analytics_ledger_projection(self) -> Mapping[str, Any] | None:
        return self.get_projection(ANALYTICS_LEDGER_KEY)

    def list_mutation_receipts(self) -> list[MutationReceipt]:
        with self._lock:
            return list(self._mutation_index.values())

    def get_mutation_receipt(self, operation_id: str) -> MutationReceipt | None:
        with self._lock:
            return self._mutation_index.get(operation_id)

    def query_publications(self) -> dict[str, Any]:
        """Return all shadow projections as a query publication document.

        Guarantees no plaintext, keys, wraps, or encrypted bytes.
        """

        with self._lock:
            backend = self.backend
            assert backend is not None
            # Collect keys from mutation index projection keys.
            keys = sorted({r.projection_key for r in self._mutation_index.values()})
            publications: dict[str, Any] = {}
            for key in keys:
                value = self._port.read(key)
                if value is not None:
                    safe = redact_for_query_publication(dict(value))
                    assert_query_publication_safe(safe)
                    publications[key] = safe
            document = {
                "publication_type": "wallet_query_publication_v1",
                "schema_version": WALLET_DUCKDB_REPOSITORY_SCHEMA_VERSION,
                "domain": self.domain,
                "mode": self._port.mode.value,
                "publications": publications,
                "mutation_count": len(self._mutation_index),
            }
            assert_query_publication_safe(document)
            return document

    def list_parity_receipts(self) -> list[ParityReceipt]:
        backend = self.backend
        assert backend is not None
        # MemoryAuthorityBackend stores parities privately; re-emit from mutations.
        receipts: list[ParityReceipt] = []
        for mutation in self.list_mutation_receipts():
            if not mutation.parity_receipt_cid:
                continue
            # Reconstruct a minimal parity view from the mutation receipt.
            receipts.append(
                ParityReceipt(
                    receipt_cid=mutation.parity_receipt_cid,
                    domain=self.domain,
                    mode=AuthorityMode.parse(mutation.mode),
                    key=mutation.projection_key,
                    legacy_digest=mutation.projection_digest
                    if mutation.parity_matched
                    else mutation.payload_digest,
                    db_digest=mutation.projection_digest,
                    matched=mutation.parity_matched,
                    operation_id=mutation.operation_id,
                    created_at=mutation.created_at,
                )
            )
        return receipts

    # -- round-trip helpers (legacy JSON exactness is caller's job) ---------

    def verify_wallet_json_round_trip(
        self,
        original_snapshot: Mapping[str, Any],
        restored_snapshot: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Verify two full wallet snapshots are byte-identical canonically."""

        left = canonical_dumps(dict(original_snapshot))
        right = canonical_dumps(dict(restored_snapshot))
        matched = left == right
        return {
            "matched": matched,
            "original_digest": _sha256_digest(left.encode("utf-8")),
            "restored_digest": _sha256_digest(right.encode("utf-8")),
            "kind": "wallet_json",
        }

    def verify_analytics_ledger_round_trip(
        self,
        original_ledger: Mapping[str, Any],
        restored_ledger: Mapping[str, Any],
    ) -> dict[str, Any]:
        left = canonical_dumps(dict(original_ledger))
        right = canonical_dumps(dict(restored_ledger))
        matched = left == right
        return {
            "matched": matched,
            "original_digest": _sha256_digest(left.encode("utf-8")),
            "restored_digest": _sha256_digest(right.encode("utf-8")),
            "kind": "analytics_ledger",
        }

    # -- internal DuckDB row mirror -----------------------------------------

    def _mirror_mutation_rows(
        self, receipt: MutationReceipt, projection: Mapping[str, Any]
    ) -> None:
        conn = self.connection
        if conn is None:
            return
        if not self._installed_ddl:
            self.install_catalog(conn)
        now = receipt.created_at or _utc_now()
        conn.execute(
            """
            INSERT OR REPLACE INTO mutation_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                receipt.operation_id,
                receipt.wallet_id,
                receipt.action,
                receipt.resource,
                receipt.actor_did,
                receipt.decision,
                receipt.projection_key,
                receipt.projection_digest,
                receipt.parity_receipt_cid,
                receipt.parity_matched,
                receipt.mode,
                now,
                WALLET_DUCKDB_REPOSITORY_SCHEMA_VERSION,
            ],
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO parity_receipts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                receipt.parity_receipt_cid,
                receipt.operation_id,
                receipt.projection_key,
                receipt.projection_digest if receipt.parity_matched else "",
                receipt.projection_digest,
                receipt.parity_matched,
                "" if receipt.parity_matched else "digest_mismatch",
                receipt.mode,
                now,
            ],
        )
        if projection.get("projection_type") == "wallet_query_projection_v1":
            self._mirror_wallet_projection(conn, projection, receipt)
        elif projection.get("projection_type") == "wallet_analytics_ledger_projection_v1":
            self._mirror_analytics_projection(conn, projection, receipt)

    def _mirror_wallet_projection(
        self, conn: Any, projection: Mapping[str, Any], receipt: MutationReceipt
    ) -> None:
        wallet = projection.get("wallet") or {}
        counts = projection.get("counts") or {}
        revision = self._revisions.get(receipt.projection_key, 1)
        conn.execute(
            """
            INSERT OR REPLACE INTO wallet_snapshots VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                projection.get("wallet_id"),
                _hex_digest(canonical_bytes(dict(projection))),
                receipt.projection_digest,
                revision,
                int(counts.get("records") or 0),
                int(counts.get("grants") or 0),
                int(counts.get("audit_events") or 0),
                (wallet or {}).get("owner_did") if isinstance(wallet, Mapping) else "",
                receipt.created_at,
                WALLET_DUCKDB_REPOSITORY_SCHEMA_VERSION,
            ],
        )
        for record in projection.get("records") or []:
            if not isinstance(record, Mapping):
                continue
            conn.execute(
                """
                INSERT OR REPLACE INTO wallet_records VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    record.get("record_id"),
                    record.get("wallet_id"),
                    record.get("data_type"),
                    record.get("sensitivity"),
                    record.get("public_descriptor"),
                    record.get("current_version_id"),
                    record.get("status"),
                    record.get("created_at"),
                    record.get("updated_at"),
                ],
            )
        for version in projection.get("versions") or []:
            if not isinstance(version, Mapping):
                continue
            conn.execute(
                """
                INSERT OR REPLACE INTO wallet_versions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    version.get("version_id"),
                    version.get("record_id"),
                    projection.get("wallet_id"),
                    version.get("ciphertext_hash"),
                    version.get("encryption_suite"),
                    version.get("payload_uri"),
                    version.get("payload_sha256"),
                    version.get("payload_size_bytes") or 0,
                    version.get("metadata_uri"),
                    version.get("metadata_sha256"),
                    int(version.get("key_wrap_count") or 0),
                    version.get("created_at"),
                ],
            )
        for ref in projection.get("encrypted_object_refs") or []:
            if not isinstance(ref, Mapping):
                continue
            conn.execute(
                """
                INSERT OR REPLACE INTO encrypted_object_refs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    ref.get("ref_id"),
                    projection.get("wallet_id"),
                    ref.get("record_id"),
                    ref.get("version_id"),
                    ref.get("role"),
                    ref.get("uri"),
                    ref.get("storage_type"),
                    ref.get("sha256"),
                    ref.get("size_bytes") or 0,
                ],
            )
        for grant in projection.get("grants") or []:
            if not isinstance(grant, Mapping):
                continue
            conn.execute(
                """
                INSERT OR REPLACE INTO wallet_grants VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    grant.get("grant_id"),
                    projection.get("wallet_id"),
                    grant.get("issuer_did"),
                    grant.get("audience_did"),
                    grant.get("status"),
                    grant.get("created_at"),
                ],
            )
        for ordinal, event in enumerate(projection.get("audit_events") or []):
            if not isinstance(event, Mapping):
                continue
            conn.execute(
                """
                INSERT OR REPLACE INTO wallet_audit_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    event.get("event_id"),
                    event.get("wallet_id") or projection.get("wallet_id"),
                    event.get("actor_did"),
                    event.get("action"),
                    event.get("resource"),
                    event.get("decision"),
                    event.get("hash_self"),
                    event.get("hash_prev"),
                    ordinal,
                ],
            )
        for approval in projection.get("approvals") or []:
            if not isinstance(approval, Mapping):
                continue
            conn.execute(
                """
                INSERT OR REPLACE INTO wallet_approvals VALUES (?, ?, ?, ?, ?)
                """,
                [
                    approval.get("approval_id"),
                    projection.get("wallet_id"),
                    approval.get("operation") or approval.get("operation_type") or "",
                    approval.get("status"),
                    approval.get("created_at"),
                ],
            )

    def _mirror_analytics_projection(
        self, conn: Any, projection: Mapping[str, Any], receipt: MutationReceipt
    ) -> None:
        conn.execute(
            """
            INSERT OR REPLACE INTO analytics_ledger VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                ANALYTICS_LEDGER_KEY,
                _hex_digest(canonical_bytes(dict(projection))),
                receipt.projection_digest,
                int(projection.get("subject_count") or 0),
                len(projection.get("analytics_templates") or []),
                len(projection.get("analytics_contributions") or []),
                len(projection.get("aggregate_results") or []),
                receipt.created_at,
                WALLET_DUCKDB_REPOSITORY_SCHEMA_VERSION,
            ],
        )


def build_wallet_duckdb_repository(
    *,
    mode: AuthorityMode | str = AuthorityMode.SHADOW,
    backend: AuthorityBackend | None = None,
    connection: Any | None = None,
    domain: str = WALLET_DATA_DOMAIN,
) -> WalletDuckDBRepository:
    """Factory for the data-wallet DuckDB event port."""

    return WalletDuckDBRepository(
        mode=mode,
        backend=backend,
        connection=connection,
        domain=domain,
    )


__all__ = [
    "ANALYTICS_LEDGER_KEY",
    "FORBIDDEN_QUERY_KEYS",
    "MUTATION_RECEIPT_SCHEMA",
    "MutationKind",
    "MutationReceipt",
    "OWNER_TASK_ID",
    "WALLET_DATA_CATALOG_DDL",
    "WALLET_DATA_CATALOG_NAME",
    "WALLET_DATA_CATALOG_TABLES",
    "WALLET_DATA_DOMAIN",
    "WALLET_DUCKDB_REPOSITORY_INTERFACE",
    "WALLET_DUCKDB_REPOSITORY_SCHEMA_VERSION",
    "WalletDuckDBRepository",
    "WalletDuckDBRepositoryError",
    "WalletPublicationSafetyError",
    "assert_query_publication_safe",
    "build_wallet_duckdb_repository",
    "new_operation_id",
    "project_analytics_ledger_for_query",
    "project_wallet_snapshot_for_query",
    "projection_digest",
    "redact_for_query_publication",
]
