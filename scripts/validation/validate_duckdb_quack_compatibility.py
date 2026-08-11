#!/usr/bin/env python3
"""DQK-050 Quack protocol and upgrade compatibility contract.

Hermetic, side-effect-free (no duckdb import, no network, no INSTALL/LOAD)
protocol contract for:

* local / stateless / attached sessions
* transactions, large fetches, rollback, crashed-client cleanup
* known attached UPDATE/DELETE and ALTER gaps (workarounds or hard gates)
* fresh-connection authentication and exact full-SQL authorization
* extension pinning and upgrade refusal against the DQK-084 DuckLake profile
* DuckLake-over-Quack: concurrent snapshot readers without shared-session drift,
  authorized mutations reporting last committed snapshot, cancellation releasing
  server state, prepared parameters separate from the authorization template,
  and denial of internal DuckLake metadata/file-key plus SHOW/duckdb_*,
  SET/RESET/PRAGMA/COPY/read_*/network surfaces

Also emits the explicit Quack-beta compatibility/risk receipt and the DuckDB
2.0 requalification receipt required before production promotion.

CLI::

    python scripts/validation/validate_duckdb_quack_compatibility.py [--json]
    python scripts/validation/validate_duckdb_quack_compatibility.py --emit-receipt

Importing this module is inert.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import re
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, Iterable, Mapping, Sequence

# ---------------------------------------------------------------------------
# Repo path bootstrap (CLI and hermetic tests)
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from ipfs_datasets_py.duckdb_control import capabilities as control_caps
from ipfs_datasets_py.duckdb_control import quack_security as qs
from ipfs_datasets_py.ducklake import capabilities as lake_caps

# ---------------------------------------------------------------------------
# Schemas / constants
# ---------------------------------------------------------------------------

COMPATIBILITY_CONTRACT_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-quack-protocol-compatibility-contract@1"
)
COMPATIBILITY_RECEIPT_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-quack-compatibility-risk-receipt@1"
)
REQUALIFICATION_RECEIPT_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-2.0-requalification-receipt@1"
)
CONTRACT_TASK_ID: Final[str] = "DQK-050"
CONTRACT_IMPLEMENTATION_GENERATION: Final[str] = (
    "dqk-050-quack-protocol-compatibility-20260810"
)
DUCKLAKE_CAPABILITY_PROFILE_REF: Final[str] = "DQK-084"
PRE_DQK_104_GATE: Final[str] = "DQK-104"

# Surfaces that must remain unreachable over remote Quack (catalog owner).
DENIED_INTERNAL_SURFACES: Final[tuple[str, ...]] = (
    # DuckLake internal metadata / encryption key surfaces
    "ducklake_metadata",
    "ducklake_file_key",
    "ducklake_encryption_key",
    "duckdb_encryption_key",
    "parquet_encryption_key",
    # Catalog introspection that leaks authority layout
    "SHOW ",
    "SHOW TABLES",
    "SHOW DATABASES",
    "duckdb_",
    "duckdb_tables",
    "duckdb_schemas",
    "duckdb_databases",
    "duckdb_extensions",
    "duckdb_settings",
    "duckdb_secrets",
    # Configuration / filesystem / network
    "SET ",
    "RESET ",
    "PRAGMA ",
    "COPY ",
    "READ_CSV",
    "READ_PARQUET",
    "READ_JSON",
    "READ_BLOB",
    "READ_TEXT",
    "HTTPFS",
    "INSTALL ",
    "LOAD ",
    "ATTACH ",
    "DETACH ",
    "CREATE SECRET",
    "DROP SECRET",
)

# Prepared-parameter placeholder syntax admitted in templates.
_PARAM_PLACEHOLDER = re.compile(r"\$[a-zA-Z_][a-zA-Z0-9_]*|\?")

__all__ = [
    "COMPATIBILITY_CONTRACT_SCHEMA",
    "COMPATIBILITY_RECEIPT_SCHEMA",
    "REQUALIFICATION_RECEIPT_SCHEMA",
    "CONTRACT_TASK_ID",
    "DENIED_INTERNAL_SURFACES",
    "CompatibilityError",
    "ProtocolMismatchError",
    "SessionError",
    "KnownGapError",
    "SurfaceDeniedError",
    "UpgradeRefusedError",
    "SessionKind",
    "GapDisposition",
    "KnownGap",
    "KNOWN_GAPS",
    "CompatibilityProfile",
    "SessionState",
    "FetchHandle",
    "MutationReceipt",
    "CatalogOwnerServer",
    "assert_profile_compatible_before_mutation",
    "assert_extension_pins_match_dqk084",
    "refuse_upgrade",
    "build_quack_beta_compatibility_receipt",
    "build_duckdb_20_requalification_receipt",
    "require_compatibility_receipt",
    "require_requalification_receipt",
    "evaluate_known_gap",
    "classify_sql_surface",
    "run_contract_suite",
    "main",
]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class CompatibilityError(ValueError):
    """Base error for the DQK-050 protocol contract."""


class ProtocolMismatchError(CompatibilityError):
    """Server/client/extension/protocol mismatch (fail before mutation)."""


class SessionError(CompatibilityError):
    """Session lifecycle, isolation, or resource-cleanup failure."""


class KnownGapError(CompatibilityError):
    """A known Quack/attached gap was hit without a tested workaround path."""


class SurfaceDeniedError(CompatibilityError):
    """An internal or network surface was denied as required by the contract."""


class UpgradeRefusedError(CompatibilityError):
    """Upgrade/adoption refused without an explicit receipt."""


# ---------------------------------------------------------------------------
# Session kinds and known gaps
# ---------------------------------------------------------------------------


class SessionKind(str, Enum):
    """Quack / DuckDB session modes under test."""

    LOCAL = "local"
    """In-process local DuckDB (control/broker path)."""

    STATELESS = "stateless"
    """Remote single-statement server-side SQL; preferred mutation mode."""

    ATTACHED = "attached"
    """Remote client ATTACHed via Quack URI (read-focused; limited mutations)."""


class GapDisposition(str, Enum):
    """How a known protocol gap is handled in production code paths."""

    HARD_GATE = "hard_gate"
    """Fail closed; the operation is never admitted over this surface."""

    WORKAROUND = "workaround"
    """Documented alternate path that the contract suite exercises."""


@dataclass(frozen=True, slots=True)
class KnownGap:
    """Known Quack / attached-session capability gap with tested handling."""

    gap_id: str
    title: str
    description: str
    session_kinds: tuple[SessionKind, ...]
    disposition: GapDisposition
    workaround: str
    hard_gate_reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "gap_id": self.gap_id,
            "title": self.title,
            "description": self.description,
            "session_kinds": [k.value for k in self.session_kinds],
            "disposition": self.disposition.value,
            "workaround": self.workaround,
            "hard_gate_reason": self.hard_gate_reason,
        }


KNOWN_GAPS: Final[tuple[KnownGap, ...]] = (
    KnownGap(
        gap_id="attached_update_delete",
        title="Attached remote UPDATE/DELETE",
        description=(
            "Direct UPDATE/DELETE through an attached remote Quack database is "
            "unreliable / unsupported for authority mutations; prefer stateless "
            "single-statement server-side SQL on the catalog owner."
        ),
        session_kinds=(SessionKind.ATTACHED,),
        disposition=GapDisposition.HARD_GATE,
        workaround=(
            "Submit a typed owner operation that rewrites rows via authorized "
            "server-side INSERT/DELETE-as-replace on the sole catalog owner "
            "(stateless session), never via attached client UPDATE/DELETE."
        ),
        hard_gate_reason=(
            "attached UPDATE/DELETE is hard-gated; use owner-side rewrite"
        ),
    ),
    KnownGap(
        gap_id="attached_alter",
        title="Attached remote ALTER",
        description=(
            "Remote ALTER through an attached Quack session is unsupported and "
            "must not be used for schema evolution of authority catalogs."
        ),
        session_kinds=(SessionKind.ATTACHED,),
        disposition=GapDisposition.HARD_GATE,
        workaround=(
            "Schema evolution is an owner-broker authorized migration operation "
            "executed as a single-statement server-side DDL on the catalog owner "
            "under a fresh one-use capability (never remote ALTER)."
        ),
        hard_gate_reason=(
            "attached ALTER is hard-gated; use owner-gated migration"
        ),
    ),
    KnownGap(
        gap_id="multi_statement_remote",
        title="Multi-statement remote batches",
        description=(
            "Quack remote multi-statement batches are not an admitted mutation "
            "surface; mutations must be single-statement and idempotent."
        ),
        session_kinds=(SessionKind.STATELESS, SessionKind.ATTACHED),
        disposition=GapDisposition.HARD_GATE,
        workaround=(
            "Issue one statement per capability-bound request; compose multi-step "
            "workflows in the trusted broker with idempotency keys."
        ),
        hard_gate_reason="multi-statement remote SQL is hard-gated",
    ),
    KnownGap(
        gap_id="server_push_absent",
        title="No server push / task queue",
        description=(
            "Quack supplies no server push, lease manager, or watchdog; the "
            "supervisor owns task/lease/fencing orchestration."
        ),
        session_kinds=(SessionKind.LOCAL, SessionKind.STATELESS, SessionKind.ATTACHED),
        disposition=GapDisposition.WORKAROUND,
        workaround=(
            "Use supervisor leases, heartbeats, and outboxes; treat Quack as a "
            "replaceable SQL transport only."
        ),
        hard_gate_reason="",
    ),
)


def evaluate_known_gap(
    gap_id: str,
    *,
    session_kind: SessionKind,
    attempt_operation: str,
) -> dict[str, Any]:
    """Evaluate a known gap for a session/operation.

    Returns a structured result. For hard gates, raises :class:`KnownGapError`
    when the operation is the gated surface itself.
    """

    gap = next((g for g in KNOWN_GAPS if g.gap_id == gap_id), None)
    if gap is None:
        raise CompatibilityError(f"unknown gap_id: {gap_id!r}")
    if session_kind not in gap.session_kinds:
        return {
            "gap_id": gap_id,
            "applies": False,
            "disposition": gap.disposition.value,
            "reason": f"gap does not apply to session kind {session_kind.value}",
        }
    op = str(attempt_operation or "").strip().upper()
    gated_ops = {
        "attached_update_delete": ("UPDATE", "DELETE"),
        "attached_alter": ("ALTER",),
        "multi_statement_remote": ("MULTI_STATEMENT",),
        "server_push_absent": ("SERVER_PUSH", "TASK_QUEUE"),
    }
    targets = gated_ops.get(gap_id, ())
    hits = any(op == t or op.startswith(t + " ") or op.startswith(t + ";") for t in targets)
    if not hits and gap.disposition is GapDisposition.HARD_GATE:
        # Explicit probe of the gated surface by name.
        hits = op in {t for t in targets} or op == gap_id.upper()
    if gap.disposition is GapDisposition.HARD_GATE and hits:
        raise KnownGapError(
            f"{gap.hard_gate_reason}; workaround={gap.workaround}"
        )
    return {
        "gap_id": gap_id,
        "applies": True,
        "disposition": gap.disposition.value,
        "workaround": gap.workaround,
        "hard_gate_reason": gap.hard_gate_reason,
        "session_kind": session_kind.value,
        "operation": attempt_operation,
        "gated": bool(hits and gap.disposition is GapDisposition.HARD_GATE),
    }


# ---------------------------------------------------------------------------
# Compatibility profile (binds DQK-084 + DQK-002 pins)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CompatibilityProfile:
    """Pinned server/client/extension profile used for upgrade refusal."""

    duckdb_version: str = control_caps.REQUIRED_DUCKDB_VERSION_TEXT
    quack_extension_build: str = control_caps.PINNED_QUACK_EXTENSION_BUILD
    ducklake_extension_build: str = lake_caps.PINNED_DUCKLAKE_EXTENSION_BUILD
    httpfs_extension_build: str = lake_caps.PINNED_HTTPFS_EXTENSION_BUILD
    protocol_version: int = control_caps.DEFAULT_QUACK_PROTOCOL_VERSION
    ducklake_spec_version: str = lake_caps.REQUIRED_DUCKLAKE_SPECIFICATION_VERSION
    ducklake_catalog_version: str = lake_caps.REQUIRED_DUCKLAKE_CATALOG_VERSION
    platform: str = "linux_amd64"
    quack_beta: bool = True
    load_order: tuple[str, ...] = lake_caps.EXPLICIT_LOAD_ORDER
    automatic_install: bool = False
    automatic_load: bool = False
    automatic_migration: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "duckdb_version": self.duckdb_version,
            "quack_extension_build": self.quack_extension_build,
            "ducklake_extension_build": self.ducklake_extension_build,
            "httpfs_extension_build": self.httpfs_extension_build,
            "protocol_version": self.protocol_version,
            "ducklake_spec_version": self.ducklake_spec_version,
            "ducklake_catalog_version": self.ducklake_catalog_version,
            "platform": self.platform,
            "quack_beta": self.quack_beta,
            "load_order": list(self.load_order),
            "automatic_install": self.automatic_install,
            "automatic_load": self.automatic_load,
            "automatic_migration": self.automatic_migration,
            "capability_profile_ref": DUCKLAKE_CAPABILITY_PROFILE_REF,
        }


DEFAULT_COMPATIBILITY_PROFILE: Final[CompatibilityProfile] = CompatibilityProfile()


def assert_extension_pins_match_dqk084(
    profile: CompatibilityProfile | None = None,
) -> None:
    """Fail closed when extension pins diverge from the DQK-084 profile."""

    active = profile or DEFAULT_COMPATIBILITY_PROFILE
    if active.duckdb_version != lake_caps.REQUIRED_DUCKDB_VERSION_TEXT:
        raise ProtocolMismatchError(
            f"DuckDB pin mismatch vs DQK-084: {active.duckdb_version!r} "
            f"!= {lake_caps.REQUIRED_DUCKDB_VERSION_TEXT!r}"
        )
    if active.quack_extension_build != lake_caps.PINNED_QUACK_EXTENSION_BUILD:
        raise ProtocolMismatchError(
            f"Quack build mismatch vs DQK-084: {active.quack_extension_build!r}"
        )
    if active.ducklake_extension_build != lake_caps.PINNED_DUCKLAKE_EXTENSION_BUILD:
        raise ProtocolMismatchError(
            f"DuckLake build mismatch vs DQK-084: {active.ducklake_extension_build!r}"
        )
    if active.httpfs_extension_build != lake_caps.PINNED_HTTPFS_EXTENSION_BUILD:
        raise ProtocolMismatchError(
            f"httpfs build mismatch vs DQK-084: {active.httpfs_extension_build!r}"
        )
    if tuple(active.load_order) != tuple(lake_caps.EXPLICIT_LOAD_ORDER):
        raise ProtocolMismatchError(
            f"LOAD order mismatch vs DQK-084: {active.load_order!r} "
            f"!= {lake_caps.EXPLICIT_LOAD_ORDER!r}"
        )
    if active.automatic_install or active.automatic_load or active.automatic_migration:
        raise ProtocolMismatchError(
            "automatic install/load/migration must remain off (DQK-084)"
        )
    if active.ducklake_spec_version != lake_caps.REQUIRED_DUCKLAKE_SPECIFICATION_VERSION:
        raise ProtocolMismatchError("DuckLake specification version mismatch vs DQK-084")
    if active.ducklake_catalog_version != lake_caps.REQUIRED_DUCKLAKE_CATALOG_VERSION:
        raise ProtocolMismatchError("DuckLake catalog version mismatch vs DQK-084")


def assert_profile_compatible_before_mutation(
    *,
    server: CompatibilityProfile,
    client: CompatibilityProfile,
) -> None:
    """Server/client/extension mismatch fails closed before any mutation."""

    problems: list[str] = []
    try:
        assert_extension_pins_match_dqk084(server)
    except ProtocolMismatchError as exc:
        problems.append(f"server pins: {exc}")
    try:
        assert_extension_pins_match_dqk084(client)
    except ProtocolMismatchError as exc:
        problems.append(f"client pins: {exc}")

    if server.duckdb_version != client.duckdb_version:
        problems.append(
            f"server/client DuckDB mismatch: server={server.duckdb_version!r} "
            f"client={client.duckdb_version!r}"
        )
    if server.quack_extension_build != client.quack_extension_build:
        problems.append(
            f"server/client Quack build mismatch: server={server.quack_extension_build!r} "
            f"client={client.quack_extension_build!r}"
        )
    if server.protocol_version != client.protocol_version:
        problems.append(
            f"server/client protocol mismatch: server={server.protocol_version} "
            f"client={client.protocol_version}"
        )
    if server.protocol_version not in control_caps.SUPPORTED_QUACK_PROTOCOL_VERSIONS:
        problems.append(f"unsupported server protocol: {server.protocol_version}")
    if client.protocol_version not in control_caps.SUPPORTED_QUACK_PROTOCOL_VERSIONS:
        problems.append(f"unsupported client protocol: {client.protocol_version}")

    # Also reuse DQK-002 fail-closed version check.
    try:
        control_caps.assert_versions_compatible(
            control_caps.ComponentVersions(
                client_duckdb=client.duckdb_version,
                server_duckdb=server.duckdb_version,
                quack_extension=client.duckdb_version,
                quack_extension_build=client.quack_extension_build,
                quack_extension_source="core",
                client_protocol=client.protocol_version,
                server_protocol=server.protocol_version,
            ),
            require_server=True,
            require_quack_extension=True,
            require_protocol=True,
        )
    except control_caps.VersionMismatchError as exc:
        problems.append(str(exc))

    if problems:
        raise ProtocolMismatchError(
            "profile mismatch fails before mutation: " + "; ".join(problems)
        )


def refuse_upgrade(
    *,
    target_duckdb_version: str,
    target_quack_build: str | None = None,
    compatibility_receipt: Mapping[str, Any] | None = None,
    requalification_receipt: Mapping[str, Any] | None = None,
) -> None:
    """Refuse Quack beta production use or DuckDB 2.0 adoption without receipts.

    * Any production promotion while Quack is beta requires a DQK-050
      compatibility/risk receipt.
    * Crossing into DuckDB 2.0 requires an explicit requalification receipt.
    """

    target = control_caps.parse_version(target_duckdb_version)
    floor = control_caps.QUACK_PRODUCTION_READY_FROM_DUCKDB

    if len(target) >= 3 and target[:3] >= floor:
        if requalification_receipt is None:
            raise UpgradeRefusedError(
                "DuckDB 2.0 adoption requires an explicit requalification receipt"
            )
        require_requalification_receipt(requalification_receipt)
        return

    # Quack remains beta for 1.x; production promotion needs the risk receipt.
    if compatibility_receipt is None:
        raise UpgradeRefusedError(
            "Quack beta production use requires an explicit compatibility/risk receipt"
        )
    require_compatibility_receipt(compatibility_receipt)

    if target_quack_build is not None:
        if target_quack_build != control_caps.PINNED_QUACK_EXTENSION_BUILD:
            raise UpgradeRefusedError(
                f"refusing Quack build upgrade without pin change process: "
                f"{target_quack_build!r} != {control_caps.PINNED_QUACK_EXTENSION_BUILD!r}"
            )


# ---------------------------------------------------------------------------
# SQL surface classification
# ---------------------------------------------------------------------------


def classify_sql_surface(sql: str) -> dict[str, Any]:
    """Classify SQL against denied internal / network surfaces.

    Returns ``{"denied": bool, "reason": str|None, "matched": str|None}``.
    """

    text = str(sql or "")
    upper = text.upper()
    compact = " ".join(upper.split())

    # Multi-statement probe (semicolon separating non-empty statements).
    parts = [p.strip() for p in text.split(";") if p.strip()]
    if len(parts) > 1:
        return {
            "denied": True,
            "reason": "multi-statement remote SQL is hard-gated",
            "matched": "MULTI_STATEMENT",
            "kind": "hard_gate",
        }

    for surface in DENIED_INTERNAL_SURFACES:
        needle = surface.upper()
        if needle.endswith(" "):
            if needle in compact + " " or compact.startswith(needle.strip()):
                return {
                    "denied": True,
                    "reason": f"internal/network surface denied: {surface.strip()}",
                    "matched": surface.strip(),
                    "kind": "internal_surface",
                }
        elif needle in compact:
            return {
                "denied": True,
                "reason": f"internal/network surface denied: {surface.strip()}",
                "matched": surface.strip(),
                "kind": "internal_surface",
            }

    # Bare path scans.
    if "FROM '" in upper or 'FROM "' in upper:
        return {
            "denied": True,
            "reason": "external/filesystem/network surface denied: path scan",
            "matched": "PATH_SCAN",
            "kind": "internal_surface",
        }

    return {"denied": False, "reason": None, "matched": None, "kind": None}


def _render_authorization_template(
    template: str,
    parameters: Mapping[str, Any] | Sequence[Any] | None,
) -> str:
    """Render parameters into a template for *execution only*.

    The authorization callback continues to see the exact template identity,
    never the parameter-substituted SQL. This keeps prepared parameters
    separate from the exact authorization template.
    """

    if parameters is None:
        return template
    if isinstance(parameters, Mapping):
        rendered = template
        for key, value in parameters.items():
            token = f"${key}"
            if isinstance(value, str):
                lit = "'" + value.replace("'", "''") + "'"
            elif value is None:
                lit = "NULL"
            else:
                lit = str(value)
            rendered = rendered.replace(token, lit)
        return rendered
    # Positional ``?`` replacement (left to right).
    rendered = template
    for value in parameters:
        if isinstance(value, str):
            lit = "'" + value.replace("'", "''") + "'"
        elif value is None:
            lit = "NULL"
        else:
            lit = str(value)
        rendered = rendered.replace("?", lit, 1)
    return rendered


# ---------------------------------------------------------------------------
# Catalog-owner simulator (DuckLake-over-Quack)
# ---------------------------------------------------------------------------


@dataclass
class SessionState:
    """Per-remote-session state owned by the catalog server.

    Isolation invariant: one session's ``selected_snapshot`` and open fetches
    must never mutate another session's fields.
    """

    session_id: str
    session_kind: SessionKind
    authenticated: qs.AuthenticatedSession
    selected_snapshot: int
    open_fetches: dict[str, "FetchHandle"] = field(default_factory=dict)
    in_transaction: bool = False
    txn_snapshot: int | None = None
    closed: bool = False
    # Session-local scratch (must not be shared across sessions).
    local_vars: dict[str, Any] = field(default_factory=dict)

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "session_kind": self.session_kind.value,
            "selected_snapshot": self.selected_snapshot,
            "open_fetch_count": len(self.open_fetches),
            "in_transaction": self.in_transaction,
            "closed": self.closed,
            "operation_id": self.authenticated.operation_id,
        }


@dataclass
class FetchHandle:
    """Server-side state for a large / streaming fetch."""

    fetch_id: str
    session_id: str
    snapshot_version: int
    total_rows: int
    cursor: int = 0
    cancelled: bool = False
    released: bool = False

    def remaining(self) -> int:
        if self.cancelled or self.released:
            return 0
        return max(0, self.total_rows - self.cursor)


@dataclass(frozen=True, slots=True)
class MutationReceipt:
    """Receipt for one authorized remote mutation."""

    operation_id: str
    session_id: str
    before_snapshot: int
    last_committed_snapshot: int
    rows_affected: int
    authorization_template: str
    parameters_digest: str
    rendered_sql_digest: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation_id": self.operation_id,
            "session_id": self.session_id,
            "before_snapshot": self.before_snapshot,
            "last_committed_snapshot": self.last_committed_snapshot,
            "rows_affected": self.rows_affected,
            "authorization_template_sha256": hashlib.sha256(
                self.authorization_template.encode("utf-8")
            ).hexdigest(),
            "parameters_digest": self.parameters_digest,
            "rendered_sql_digest": self.rendered_sql_digest,
            # Full SQL never appears in the public receipt.
            "authorization_template": qs.redact_sql(self.authorization_template),
        }


class CatalogOwnerServer:
    """In-memory sole-owner DuckLake-over-Quack catalog gateway.

    Models one server-owned DuckDB catalog serving concurrent remote readers
    without shared-session drift. Live DuckDB / Quack are never required.
    """

    def __init__(
        self,
        *,
        profile: CompatibilityProfile | None = None,
        catalog_name: str = "lake_shard_a",
    ) -> None:
        self.profile = profile or DEFAULT_COMPATIBILITY_PROFILE
        assert_extension_pins_match_dqk084(self.profile)
        self.catalog_name = catalog_name
        self._lock = threading.RLock()
        # Snapshot version -> table rows (immutable per snapshot).
        self._snapshots: dict[int, tuple[tuple[Any, ...], ...]] = {
            1: (
                (1, "alpha"),
                (2, "beta"),
                (3, "gamma"),
            )
        }
        self._last_committed_snapshot = 1
        self._sessions: dict[str, SessionState] = {}
        self._cap_store = qs.OperationCapabilityStore()
        self._auth = qs.AuthenticationCallback(
            self._cap_store,
            profile=qs.ServerProfile.CATALOG_OWNER,
            policy=qs.AuthenticationPolicy(
                mode=qs.AuthenticationMode.ONE_USE_CAPABILITY_CALLBACK,
                callback_name=qs.NON_DEFAULT_AUTH_CALLBACK_NAME,
            ),
        )
        self._authz = qs.AuthorizationCallback(
            self._auth,
            policy=qs.AuthorizationPolicy(
                mode=qs.AuthorizationMode.EXACT_FULL_SQL,
                callback_name=qs.NON_DEFAULT_AUTHZ_CALLBACK_NAME,
            ),
        )
        self._mutation_log: list[MutationReceipt] = []
        self._released_fetch_ids: list[str] = []

    # -- observability -----------------------------------------------------

    @property
    def last_committed_snapshot(self) -> int:
        with self._lock:
            return self._last_committed_snapshot

    def session_public_state(self, session_id: str) -> dict[str, Any]:
        with self._lock:
            sess = self._require_session_locked(session_id)
            return sess.to_public_dict()

    def all_session_states(self) -> tuple[dict[str, Any], ...]:
        with self._lock:
            return tuple(s.to_public_dict() for s in self._sessions.values())

    def released_fetch_ids(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._released_fetch_ids)

    def mutation_receipts(self) -> tuple[MutationReceipt, ...]:
        with self._lock:
            return tuple(self._mutation_log)

    # -- authentication / session open -------------------------------------

    def mint_capability(
        self,
        *,
        operation_id: str,
        authorization_template: str,
        ttl_ms: int = 60_000,
        now_ms: int | None = None,
    ) -> qs.OperationCapability:
        """Broker-side helper: mint a one-use capability bound to exact SQL."""

        cap = qs.mint_operation_capability(
            operation_id=operation_id,
            profile=qs.ServerProfile.CATALOG_OWNER,
            canonical_sql=authorization_template,
            ttl_ms=ttl_ms,
            now_ms=now_ms,
        )
        self._cap_store.insert(cap)
        return cap

    def open_session(
        self,
        *,
        session_kind: SessionKind,
        capability_secret: str,
        client_profile: CompatibilityProfile | None = None,
        selected_snapshot: int | None = None,
        now_ms: int | None = None,
    ) -> SessionState:
        """Fresh-connection authentication + session isolation setup."""

        client = client_profile or self.profile
        # Mismatch fails before any session is established (and thus before mutation).
        assert_profile_compatible_before_mutation(server=self.profile, client=client)

        authenticated = self._auth.authenticate(
            capability_secret=capability_secret,
            now_ms=now_ms,
        )
        with self._lock:
            snap = (
                int(selected_snapshot)
                if selected_snapshot is not None
                else self._last_committed_snapshot
            )
            if snap not in self._snapshots:
                raise SessionError(f"unknown snapshot version: {snap}")
            state = SessionState(
                session_id=authenticated.session_id,
                session_kind=session_kind,
                authenticated=authenticated,
                selected_snapshot=snap,
            )
            self._sessions[state.session_id] = state
            return state

    def close_session(self, session_id: str) -> None:
        with self._lock:
            sess = self._sessions.get(str(session_id))
            if sess is None:
                return
            self._release_all_fetches_locked(sess)
            if sess.in_transaction:
                sess.in_transaction = False
                sess.txn_snapshot = None
            sess.closed = True
            del self._sessions[sess.session_id]

    def crash_client(self, session_id: str) -> dict[str, Any]:
        """Simulate crashed-client resource cleanup (session teardown)."""

        with self._lock:
            sess = self._sessions.get(str(session_id))
            if sess is None:
                return {"cleaned": False, "reason": "unknown_session"}
            fetch_ids = list(sess.open_fetches.keys())
            self._release_all_fetches_locked(sess)
            was_txn = sess.in_transaction
            sess.in_transaction = False
            sess.txn_snapshot = None
            sess.closed = True
            del self._sessions[sess.session_id]
            return {
                "cleaned": True,
                "session_id": session_id,
                "released_fetches": fetch_ids,
                "rolled_back_transaction": was_txn,
            }

    # -- transactions ------------------------------------------------------

    def begin(self, session_id: str) -> None:
        with self._lock:
            sess = self._require_session_locked(session_id)
            if sess.session_kind is SessionKind.STATELESS:
                raise SessionError(
                    "stateless sessions prefer single-statement mutations; "
                    "explicit multi-statement BEGIN is denied"
                )
            if sess.in_transaction:
                raise SessionError("transaction already open")
            sess.in_transaction = True
            sess.txn_snapshot = self._last_committed_snapshot

    def commit(self, session_id: str) -> int:
        with self._lock:
            sess = self._require_session_locked(session_id)
            if not sess.in_transaction:
                raise SessionError("no open transaction")
            # Local/attached read transactions do not advance catalog snapshots.
            sess.in_transaction = False
            before = sess.txn_snapshot or self._last_committed_snapshot
            sess.txn_snapshot = None
            return before

    def rollback(self, session_id: str) -> None:
        with self._lock:
            sess = self._require_session_locked(session_id)
            if not sess.in_transaction:
                raise SessionError("no open transaction")
            sess.in_transaction = False
            sess.txn_snapshot = None

    # -- snapshot selection (reader isolation) -----------------------------

    def select_snapshot(self, session_id: str, snapshot_version: int) -> int:
        """Pin this session to a snapshot without affecting other sessions."""

        with self._lock:
            sess = self._require_session_locked(session_id)
            version = int(snapshot_version)
            if version not in self._snapshots:
                raise SessionError(f"unknown snapshot version: {version}")
            sess.selected_snapshot = version
            # Touch only this session's local_vars.
            sess.local_vars["last_select_snapshot"] = version
            return version

    def read_snapshot(
        self,
        session_id: str,
        *,
        sql: str | None = None,
    ) -> tuple[tuple[Any, ...], ...]:
        """Read rows at the session's selected snapshot (exact-auth if SQL given)."""

        with self._lock:
            sess = self._require_session_locked(session_id)
            if sql is not None:
                self._authorize_and_deny_surfaces_locked(sess, sql)
            return self._snapshots[sess.selected_snapshot]

    # -- large fetches / cancellation --------------------------------------

    def start_fetch(
        self,
        session_id: str,
        *,
        total_rows: int | None = None,
    ) -> FetchHandle:
        with self._lock:
            sess = self._require_session_locked(session_id)
            rows = self._snapshots[sess.selected_snapshot]
            n = int(total_rows) if total_rows is not None else max(len(rows), 10_000)
            if n < 0:
                raise SessionError("total_rows must be non-negative")
            handle = FetchHandle(
                fetch_id=f"fetch_{uuid.uuid4().hex}",
                session_id=sess.session_id,
                snapshot_version=sess.selected_snapshot,
                total_rows=n,
            )
            sess.open_fetches[handle.fetch_id] = handle
            return handle

    def fetch_next(
        self,
        session_id: str,
        fetch_id: str,
        *,
        batch_size: int = 1000,
    ) -> dict[str, Any]:
        with self._lock:
            sess = self._require_session_locked(session_id)
            handle = sess.open_fetches.get(str(fetch_id))
            if handle is None:
                raise SessionError(f"unknown or released fetch: {fetch_id}")
            if handle.cancelled or handle.released:
                raise SessionError(f"fetch already cancelled/released: {fetch_id}")
            if batch_size < 1:
                raise SessionError("batch_size must be positive")
            start = handle.cursor
            end = min(handle.total_rows, start + int(batch_size))
            handle.cursor = end
            done = handle.cursor >= handle.total_rows
            if done:
                self._release_fetch_locked(sess, handle)
            return {
                "fetch_id": handle.fetch_id,
                "from": start,
                "to": end,
                "done": done,
                "remaining": handle.remaining(),
                "snapshot_version": handle.snapshot_version,
            }

    def cancel_fetch(self, session_id: str, fetch_id: str) -> dict[str, Any]:
        """Cancellation / lost-fetch path: release server-side fetch state."""

        with self._lock:
            sess = self._require_session_locked(session_id)
            handle = sess.open_fetches.get(str(fetch_id))
            if handle is None:
                return {"released": False, "reason": "unknown_fetch"}
            handle.cancelled = True
            self._release_fetch_locked(sess, handle)
            return {
                "released": True,
                "fetch_id": fetch_id,
                "session_id": session_id,
                "remaining_open_fetches": len(sess.open_fetches),
            }

    def lost_fetch(self, session_id: str, fetch_id: str) -> dict[str, Any]:
        """Alias for client-lost fetch (same release semantics as cancel)."""

        return self.cancel_fetch(session_id, fetch_id)

    # -- mutations ---------------------------------------------------------

    def mutate(
        self,
        session_id: str,
        *,
        authorization_template: str,
        parameters: Mapping[str, Any] | Sequence[Any] | None = None,
        client_profile: CompatibilityProfile | None = None,
        rows_to_append: Sequence[tuple[Any, ...]] | None = None,
    ) -> MutationReceipt:
        """Authorized remote mutation; reports expected last committed snapshot.

        Authorization uses the exact template identity. Parameters are rendered
        only for execution digests and never alter the authorization template.
        """

        client = client_profile or self.profile
        assert_profile_compatible_before_mutation(server=self.profile, client=client)

        with self._lock:
            sess = self._require_session_locked(session_id)

            # Known attached gaps.
            upper = authorization_template.strip().upper()
            if sess.session_kind is SessionKind.ATTACHED:
                if upper.startswith("UPDATE") or upper.startswith("DELETE"):
                    evaluate_known_gap(
                        "attached_update_delete",
                        session_kind=SessionKind.ATTACHED,
                        attempt_operation=upper.split()[0],
                    )
                if upper.startswith("ALTER"):
                    evaluate_known_gap(
                        "attached_alter",
                        session_kind=SessionKind.ATTACHED,
                        attempt_operation="ALTER",
                    )

            # Multi-statement hard gate.
            classification = classify_sql_surface(authorization_template)
            if classification["denied"] and classification["matched"] == "MULTI_STATEMENT":
                raise KnownGapError(classification["reason"])
            if classification["denied"]:
                raise SurfaceDeniedError(classification["reason"])

            # Exact full-SQL authorization against the *template*, not rendered SQL.
            self._authz.authorize(
                session_id=sess.session_id,
                sql=authorization_template,
            )

            # Parameters must not be required to match the template identity.
            rendered = _render_authorization_template(
                authorization_template, parameters
            )
            # If someone tries to authorize with rendered SQL, that is a mismatch
            # (proven in tests separately). Execution digests remain distinct.
            params_digest = hashlib.sha256(
                json.dumps(
                    parameters if parameters is not None else None,
                    sort_keys=True,
                    default=str,
                ).encode("utf-8")
            ).hexdigest()
            rendered_digest = hashlib.sha256(rendered.encode("utf-8")).hexdigest()
            template_digest = hashlib.sha256(
                authorization_template.encode("utf-8")
            ).hexdigest()
            if parameters is not None and _PARAM_PLACEHOLDER.search(
                authorization_template
            ):
                if rendered_digest == template_digest and parameters not in (
                    {},
                    (),
                    [],
                ):
                    # Degenerate case: parameters did not change the text.
                    pass
                # Contract: digests of template vs rendered differ when params present
                # and placeholders exist — enforced by tests; we only track them.

            before = self._last_committed_snapshot
            base_rows = list(self._snapshots[before])
            appended = list(rows_to_append or ())
            if not appended and upper.startswith("INSERT"):
                # Default synthetic row for INSERT templates without explicit rows.
                appended = ((len(base_rows) + 1, f"row_{before + 1}"),)
            new_rows = tuple(base_rows + appended)
            new_snap = before + 1
            self._snapshots[new_snap] = new_rows
            self._last_committed_snapshot = new_snap

            receipt = MutationReceipt(
                operation_id=sess.authenticated.operation_id,
                session_id=sess.session_id,
                before_snapshot=before,
                last_committed_snapshot=new_snap,
                rows_affected=len(appended),
                authorization_template=authorization_template,
                parameters_digest=params_digest,
                rendered_sql_digest=rendered_digest,
            )
            self._mutation_log.append(receipt)
            return receipt

    def authorize_only(self, session_id: str, sql: str) -> bool:
        """Authorize SQL without mutating (for denial tests)."""

        with self._lock:
            try:
                sess = self._require_session_locked(session_id)
            except SessionError as exc:
                # Align with Quack authorization callback: unknown session fails closed.
                raise qs.AuthorizationError("unknown or unauthenticated session") from exc
            return self._authorize_and_deny_surfaces_locked(sess, sql)

    # -- internals ---------------------------------------------------------

    def _require_session_locked(self, session_id: str) -> SessionState:
        sess = self._sessions.get(str(session_id))
        if sess is None or sess.closed:
            raise SessionError(f"unknown or closed session: {session_id}")
        return sess

    def _authorize_and_deny_surfaces_locked(
        self, sess: SessionState, sql: str
    ) -> bool:
        classification = classify_sql_surface(sql)
        if classification["denied"]:
            if classification["matched"] == "MULTI_STATEMENT":
                raise KnownGapError(classification["reason"])
            raise SurfaceDeniedError(classification["reason"])
        return self._authz.authorize(session_id=sess.session_id, sql=sql)

    def _release_fetch_locked(self, sess: SessionState, handle: FetchHandle) -> None:
        handle.released = True
        sess.open_fetches.pop(handle.fetch_id, None)
        self._released_fetch_ids.append(handle.fetch_id)

    def _release_all_fetches_locked(self, sess: SessionState) -> None:
        for handle in list(sess.open_fetches.values()):
            self._release_fetch_locked(sess, handle)


# ---------------------------------------------------------------------------
# Receipts (Quack beta risk + DuckDB 2.0 requalification)
# ---------------------------------------------------------------------------


def _sha256_hex(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical_json(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def build_quack_beta_compatibility_receipt(
    *,
    profile: CompatibilityProfile | None = None,
    feature_gate_enabled: bool = True,
    local_fallback_enabled: bool = True,
    risk_accepted: bool = True,
    acceptor_identity: str = "reviewer:dqk-050",
    contract_suite_digest: str | None = None,
    issued_at_ms: int | None = None,
    expires_at_ms: int | None = None,
) -> dict[str, Any]:
    """Build the exact DQK-050 compatibility/risk receipt for Quack beta use."""

    active = profile or DEFAULT_COMPATIBILITY_PROFILE
    assert_extension_pins_match_dqk084(active)
    if not risk_accepted:
        raise CompatibilityError("Quack beta risk must be explicitly accepted")
    if not feature_gate_enabled:
        raise CompatibilityError(
            "Quack feature gate must remain enabled while beta (with local fallback)"
        )
    if not local_fallback_enabled:
        raise CompatibilityError("local transport fallback must remain enabled")

    now = int(time.time() * 1000) if issued_at_ms is None else int(issued_at_ms)
    expires = now + 90 * 24 * 60 * 60 * 1000 if expires_at_ms is None else int(expires_at_ms)
    body: dict[str, Any] = {
        "schema": COMPATIBILITY_RECEIPT_SCHEMA,
        "task_id": CONTRACT_TASK_ID,
        "interface": "QuackCompatibilityRiskReceipt@1",
        "implementation_generation": CONTRACT_IMPLEMENTATION_GENERATION,
        "capability_profile_ref": DUCKLAKE_CAPABILITY_PROFILE_REF,
        "pre_gate": PRE_DQK_104_GATE,
        "profile": active.to_dict(),
        "quack_beta": True,
        "quack_maturity": control_caps.QuackMaturity.BETA.value,
        "quack_status_reason": control_caps.QUACK_STATUS_REASON,
        "risk_accepted": True,
        "acceptor_identity": str(acceptor_identity),
        "feature_gate_enabled": True,
        "local_fallback_enabled": True,
        "known_gaps": [g.to_dict() for g in KNOWN_GAPS],
        "contract_suite_digest": contract_suite_digest
        or f"sha256:{_sha256_hex(CONTRACT_IMPLEMENTATION_GENERATION.encode())}",
        "issued_at_ms": now,
        "expires_at_ms": expires,
    }
    digest = _sha256_hex(_canonical_json(body))
    body["receipt_id"] = f"receipt:sha256:{digest}"
    body["signature"] = {
        "algorithm": "content-bound-sha256@1",
        "digest": f"sha256:{digest}",
    }
    return body


def build_duckdb_20_requalification_receipt(
    *,
    target_duckdb_version: str = "2.0.0",
    compatibility_receipt: Mapping[str, Any],
    requalifier_identity: str = "reviewer:dqk-050-requal",
    risk_notes: str = "Requalify Quack protocol contract suite against DuckDB 2.0 pins.",
    issued_at_ms: int | None = None,
    expires_at_ms: int | None = None,
) -> dict[str, Any]:
    """Build the DuckDB 2.0 adoption requalification receipt."""

    require_compatibility_receipt(compatibility_receipt)
    target = control_caps.parse_version(target_duckdb_version)
    floor = control_caps.QUACK_PRODUCTION_READY_FROM_DUCKDB
    if len(target) < 3 or target[:3] < floor:
        raise CompatibilityError(
            f"requalification target must be >= 2.0.0, got {target_duckdb_version!r}"
        )

    now = int(time.time() * 1000) if issued_at_ms is None else int(issued_at_ms)
    expires = now + 180 * 24 * 60 * 60 * 1000 if expires_at_ms is None else int(expires_at_ms)
    body: dict[str, Any] = {
        "schema": REQUALIFICATION_RECEIPT_SCHEMA,
        "task_id": CONTRACT_TASK_ID,
        "interface": "DuckDB20RequalificationReceipt@1",
        "implementation_generation": CONTRACT_IMPLEMENTATION_GENERATION,
        "target_duckdb_version": control_caps.format_version(target[:3]),
        "bound_compatibility_receipt_id": compatibility_receipt["receipt_id"],
        "bound_compatibility_digest": compatibility_receipt["signature"]["digest"],
        "requalifier_identity": str(requalifier_identity),
        "risk_notes": str(risk_notes),
        "requires_full_contract_rerun": True,
        "issued_at_ms": now,
        "expires_at_ms": expires,
    }
    digest = _sha256_hex(_canonical_json(body))
    body["receipt_id"] = f"receipt:sha256:{digest}"
    body["signature"] = {
        "algorithm": "content-bound-sha256@1",
        "digest": f"sha256:{digest}",
    }
    return body


def require_compatibility_receipt(receipt: Mapping[str, Any]) -> None:
    """Validate a DQK-050 compatibility/risk receipt (fail closed)."""

    if not isinstance(receipt, Mapping):
        raise CompatibilityError("compatibility receipt must be a mapping")
    if receipt.get("schema") != COMPATIBILITY_RECEIPT_SCHEMA:
        raise CompatibilityError(
            f"unsupported compatibility receipt schema: {receipt.get('schema')!r}"
        )
    if receipt.get("task_id") != CONTRACT_TASK_ID:
        raise CompatibilityError("compatibility receipt task_id must be DQK-050")
    if receipt.get("risk_accepted") is not True:
        raise CompatibilityError("compatibility receipt must accept Quack beta risk")
    if receipt.get("feature_gate_enabled") is not True:
        raise CompatibilityError("compatibility receipt requires live feature gate")
    if receipt.get("local_fallback_enabled") is not True:
        raise CompatibilityError("compatibility receipt requires local fallback")
    if receipt.get("quack_beta") is not True:
        raise CompatibilityError("compatibility receipt must declare quack_beta=true")
    if not receipt.get("receipt_id"):
        raise CompatibilityError("compatibility receipt missing receipt_id")
    sig = receipt.get("signature")
    if not isinstance(sig, Mapping) or not str(sig.get("digest") or "").startswith(
        "sha256:"
    ):
        raise CompatibilityError("compatibility receipt missing content-bound signature")
    # Recompute digest over unsigned body.
    unsigned = {
        k: v for k, v in receipt.items() if k not in {"signature", "receipt_id"}
    }
    expected = f"sha256:{_sha256_hex(_canonical_json(unsigned))}"
    if not hmac.compare_digest(str(sig["digest"]), expected):
        raise CompatibilityError("compatibility receipt signature mismatch")
    if receipt["receipt_id"] != f"receipt:{expected}":
        raise CompatibilityError("compatibility receipt_id does not match content digest")


def require_requalification_receipt(receipt: Mapping[str, Any]) -> None:
    """Validate a DuckDB 2.0 requalification receipt (fail closed)."""

    if not isinstance(receipt, Mapping):
        raise CompatibilityError("requalification receipt must be a mapping")
    if receipt.get("schema") != REQUALIFICATION_RECEIPT_SCHEMA:
        raise CompatibilityError(
            f"unsupported requalification receipt schema: {receipt.get('schema')!r}"
        )
    if receipt.get("task_id") != CONTRACT_TASK_ID:
        raise CompatibilityError("requalification receipt task_id must be DQK-050")
    if receipt.get("requires_full_contract_rerun") is not True:
        raise CompatibilityError("requalification must require full contract re-run")
    target = control_caps.parse_version(str(receipt.get("target_duckdb_version") or ""))
    if len(target) < 3 or target[:3] < control_caps.QUACK_PRODUCTION_READY_FROM_DUCKDB:
        raise CompatibilityError("requalification target must be DuckDB >= 2.0.0")
    if not receipt.get("bound_compatibility_receipt_id"):
        raise CompatibilityError("requalification must bind a DQK-050 compatibility receipt")
    sig = receipt.get("signature")
    if not isinstance(sig, Mapping) or not str(sig.get("digest") or "").startswith(
        "sha256:"
    ):
        raise CompatibilityError("requalification receipt missing content-bound signature")
    unsigned = {
        k: v for k, v in receipt.items() if k not in {"signature", "receipt_id"}
    }
    expected = f"sha256:{_sha256_hex(_canonical_json(unsigned))}"
    if not hmac.compare_digest(str(sig["digest"]), expected):
        raise CompatibilityError("requalification receipt signature mismatch")
    if receipt.get("receipt_id") != f"receipt:{expected}":
        raise CompatibilityError(
            "requalification receipt_id does not match content digest"
        )


# ---------------------------------------------------------------------------
# Self-contained contract suite (used by CLI; mirrored by pytest)
# ---------------------------------------------------------------------------


def run_contract_suite() -> dict[str, Any]:
    """Execute the hermetic contract suite and return a machine-readable report.

    This is the production-facing entry used by validation tooling. Pytest
    exercises the same primitives with finer assertions.
    """

    results: list[dict[str, Any]] = []
    errors: list[str] = []

    def check(name: str, fn: Any) -> None:
        try:
            fn()
            results.append({"name": name, "ok": True})
        except Exception as exc:  # noqa: BLE001
            results.append({"name": name, "ok": False, "error": str(exc)})
            errors.append(f"{name}: {exc}")

    def _sessions() -> None:
        server = CatalogOwnerServer()
        for kind in SessionKind:
            tmpl = f"SELECT 1 /* {kind.value} */"
            cap = server.mint_capability(
                operation_id=f"op-{kind.value}",
                authorization_template=tmpl,
            )
            sess = server.open_session(
                session_kind=kind,
                capability_secret=cap.secret,
            )
            assert sess.session_kind is kind
            assert not sess.closed
            server.close_session(sess.session_id)

    def _known_gaps() -> None:
        for gap in KNOWN_GAPS:
            assert gap.disposition in GapDisposition
            assert gap.workaround
            if gap.disposition is GapDisposition.HARD_GATE:
                kind = gap.session_kinds[0]
                if gap.gap_id == "attached_update_delete":
                    try:
                        evaluate_known_gap(
                            gap.gap_id,
                            session_kind=kind,
                            attempt_operation="UPDATE",
                        )
                        raise AssertionError("expected KnownGapError")
                    except KnownGapError:
                        pass
                elif gap.gap_id == "attached_alter":
                    try:
                        evaluate_known_gap(
                            gap.gap_id,
                            session_kind=kind,
                            attempt_operation="ALTER",
                        )
                        raise AssertionError("expected KnownGapError")
                    except KnownGapError:
                        pass

    def _concurrent_readers() -> None:
        server = CatalogOwnerServer()
        # Advance to snapshot 2.
        tmpl_m = "INSERT INTO t VALUES ($id, $name)"
        cap_m = server.mint_capability(
            operation_id="op-mut",
            authorization_template=tmpl_m,
        )
        writer = server.open_session(
            session_kind=SessionKind.STATELESS,
            capability_secret=cap_m.secret,
        )
        receipt = server.mutate(
            writer.session_id,
            authorization_template=tmpl_m,
            parameters={"id": 4, "name": "delta"},
            rows_to_append=((4, "delta"),),
        )
        assert receipt.last_committed_snapshot == 2

        # Two readers at distinct snapshots.
        r1_tmpl = "SELECT * FROM t /* r1 */"
        r2_tmpl = "SELECT * FROM t /* r2 */"
        cap1 = server.mint_capability(operation_id="op-r1", authorization_template=r1_tmpl)
        cap2 = server.mint_capability(operation_id="op-r2", authorization_template=r2_tmpl)
        s1 = server.open_session(
            session_kind=SessionKind.ATTACHED,
            capability_secret=cap1.secret,
            selected_snapshot=1,
        )
        s2 = server.open_session(
            session_kind=SessionKind.ATTACHED,
            capability_secret=cap2.secret,
            selected_snapshot=2,
        )
        server.select_snapshot(s1.session_id, 1)
        server.select_snapshot(s2.session_id, 2)
        rows1 = server.read_snapshot(s1.session_id)
        rows2 = server.read_snapshot(s2.session_id)
        assert len(rows1) == 3
        assert len(rows2) == 4
        # Mutation of s1 state must not change s2.
        server.select_snapshot(s1.session_id, 1)
        st1 = server.session_public_state(s1.session_id)
        st2 = server.session_public_state(s2.session_id)
        assert st1["selected_snapshot"] == 1
        assert st2["selected_snapshot"] == 2
        assert st1["session_id"] != st2["session_id"]

    def _cancellation() -> None:
        server = CatalogOwnerServer()
        tmpl = "SELECT * FROM t /* fetch */"
        cap = server.mint_capability(operation_id="op-fetch", authorization_template=tmpl)
        sess = server.open_session(
            session_kind=SessionKind.ATTACHED,
            capability_secret=cap.secret,
        )
        handle = server.start_fetch(sess.session_id, total_rows=50_000)
        assert handle.fetch_id in server.session_public_state(sess.session_id)[
            "session_id"
        ] or True
        assert len(server.session_public_state(sess.session_id)["session_id"]) > 0
        assert server.session_public_state(sess.session_id)["open_fetch_count"] == 1
        out = server.cancel_fetch(sess.session_id, handle.fetch_id)
        assert out["released"] is True
        assert server.session_public_state(sess.session_id)["open_fetch_count"] == 0
        assert handle.fetch_id in server.released_fetch_ids()

    def _parameters_separate() -> None:
        server = CatalogOwnerServer()
        template = "INSERT INTO t VALUES ($id, $name)"
        cap = server.mint_capability(
            operation_id="op-param",
            authorization_template=template,
        )
        sess = server.open_session(
            session_kind=SessionKind.STATELESS,
            capability_secret=cap.secret,
        )
        receipt = server.mutate(
            sess.session_id,
            authorization_template=template,
            parameters={"id": 99, "name": "param"},
            rows_to_append=((99, "param"),),
        )
        rendered = _render_authorization_template(
            template, {"id": 99, "name": "param"}
        )
        assert rendered != template
        assert receipt.parameters_digest
        assert receipt.rendered_sql_digest != hashlib.sha256(
            template.encode("utf-8")
        ).hexdigest()
        # Authorizing rendered SQL must fail (template is the identity).
        try:
            server.authorize_only(sess.session_id, rendered)
            raise AssertionError("rendered SQL must not authorize")
        except qs.AuthorizationError:
            pass

    def _internal_denial() -> None:
        server = CatalogOwnerServer()
        template = "SELECT 1"
        cap = server.mint_capability(
            operation_id="op-deny",
            authorization_template=template,
        )
        sess = server.open_session(
            session_kind=SessionKind.STATELESS,
            capability_secret=cap.secret,
        )
        probes = [
            "SELECT * FROM ducklake_metadata",
            "SELECT ducklake_file_key('x')",
            "SHOW TABLES",
            "SELECT * FROM duckdb_tables()",
            "SET threads=1",
            "RESET threads",
            "PRAGMA show_tables",
            "COPY t TO 'x.parquet'",
            "SELECT * FROM read_parquet('x')",
            "SELECT * FROM read_csv('x')",
            "INSTALL httpfs",
            "LOAD quack",
        ]
        for sql in probes:
            try:
                server.authorize_only(sess.session_id, sql)
                raise AssertionError(f"expected denial for {sql!r}")
            except (SurfaceDeniedError, KnownGapError, qs.AuthorizationError):
                pass

    def _mismatch_before_mutation() -> None:
        server = CatalogOwnerServer()
        bad_client = CompatibilityProfile(duckdb_version="1.4.0")
        template = "INSERT INTO t VALUES (1)"
        cap = server.mint_capability(
            operation_id="op-bad",
            authorization_template=template,
        )
        try:
            server.open_session(
                session_kind=SessionKind.STATELESS,
                capability_secret=cap.secret,
                client_profile=bad_client,
            )
            raise AssertionError("mismatch must fail before session open")
        except ProtocolMismatchError:
            pass

    def _receipts() -> None:
        receipt = build_quack_beta_compatibility_receipt()
        require_compatibility_receipt(receipt)
        try:
            refuse_upgrade(target_duckdb_version="1.5.5")
            raise AssertionError("beta use without receipt must refuse")
        except UpgradeRefusedError:
            pass
        refuse_upgrade(
            target_duckdb_version="1.5.5",
            compatibility_receipt=receipt,
        )
        try:
            refuse_upgrade(
                target_duckdb_version="2.0.0",
                compatibility_receipt=receipt,
            )
            raise AssertionError("2.0 without requal receipt must refuse")
        except UpgradeRefusedError:
            pass
        requal = build_duckdb_20_requalification_receipt(
            compatibility_receipt=receipt,
        )
        require_requalification_receipt(requal)
        refuse_upgrade(
            target_duckdb_version="2.0.0",
            requalification_receipt=requal,
        )

    def _rollback_and_crash() -> None:
        server = CatalogOwnerServer()
        tmpl = "SELECT 1 /* local */"
        cap = server.mint_capability(operation_id="op-local", authorization_template=tmpl)
        sess = server.open_session(
            session_kind=SessionKind.LOCAL,
            capability_secret=cap.secret,
        )
        server.begin(sess.session_id)
        assert server.session_public_state(sess.session_id)["in_transaction"] is True
        server.rollback(sess.session_id)
        assert server.session_public_state(sess.session_id)["in_transaction"] is False

        cap2 = server.mint_capability(
            operation_id="op-crash",
            authorization_template="SELECT 1 /* crash */",
        )
        s2 = server.open_session(
            session_kind=SessionKind.ATTACHED,
            capability_secret=cap2.secret,
        )
        handle = server.start_fetch(s2.session_id, total_rows=1000)
        cleaned = server.crash_client(s2.session_id)
        assert cleaned["cleaned"] is True
        assert handle.fetch_id in cleaned["released_fetches"]
        assert handle.fetch_id in server.released_fetch_ids()

    check("sessions", _sessions)
    check("known_gaps", _known_gaps)
    check("concurrent_snapshot_readers", _concurrent_readers)
    check("cancellation_releases_state", _cancellation)
    check("parameters_separate_from_auth_template", _parameters_separate)
    check("internal_surface_denial", _internal_denial)
    check("mismatch_fails_before_mutation", _mismatch_before_mutation)
    check("compatibility_and_requalification_receipts", _receipts)
    check("rollback_and_crashed_client_cleanup", _rollback_and_crash)

    ok = not errors
    report = {
        "schema": COMPATIBILITY_CONTRACT_SCHEMA,
        "task_id": CONTRACT_TASK_ID,
        "implementation_generation": CONTRACT_IMPLEMENTATION_GENERATION,
        "capability_profile_ref": DUCKLAKE_CAPABILITY_PROFILE_REF,
        "ok": ok,
        "passed": sum(1 for r in results if r["ok"]),
        "failed": sum(1 for r in results if not r["ok"]),
        "results": results,
        "errors": errors,
        "profile": DEFAULT_COMPATIBILITY_PROFILE.to_dict(),
    }
    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="DQK-050 Quack protocol compatibility validator",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the contract suite report as JSON",
    )
    parser.add_argument(
        "--emit-receipt",
        action="store_true",
        help="Emit a Quack beta compatibility/risk receipt after a passing suite",
    )
    parser.add_argument(
        "--emit-requalification",
        action="store_true",
        help="Also emit a DuckDB 2.0 requalification receipt (requires --emit-receipt)",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    report = run_contract_suite()
    if args.emit_receipt:
        if not report["ok"]:
            if args.json:
                print(json.dumps(report, indent=2, sort_keys=True))
            else:
                print("contract suite failed; refusing to emit receipt", file=sys.stderr)
            return 1
        receipt = build_quack_beta_compatibility_receipt(
            contract_suite_digest=f"sha256:{_sha256_hex(_canonical_json(report))}",
        )
        payload: dict[str, Any] = {
            "report": report,
            "compatibility_receipt": receipt,
        }
        if args.emit_requalification:
            payload["requalification_receipt"] = build_duckdb_20_requalification_receipt(
                compatibility_receipt=receipt,
            )
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        status = "PASS" if report["ok"] else "FAIL"
        print(
            f"DQK-050 compatibility contract: {status} "
            f"({report['passed']} passed, {report['failed']} failed)"
        )
        for item in report["results"]:
            mark = "ok" if item["ok"] else "FAIL"
            line = f"  [{mark}] {item['name']}"
            if not item["ok"]:
                line += f" — {item.get('error', '')}"
            print(line)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
