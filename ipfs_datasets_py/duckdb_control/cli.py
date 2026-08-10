"""Fail-closed operational CLI for the DuckDB control plane (DQK-006).

Exposes only typed, non-SQL operator commands:

* ``create`` — bootstrap the control schema (idempotent, receipted)
* ``migrate`` — apply checksummed catalog migrations (idempotent, receipted)
* ``inspect`` — read-only schema / migration / snapshot summary
* ``check`` — integrity check against the migration catalog (fail-closed)
* ``snapshot`` — content-addressed control snapshot (idempotent, receipted)
* ``capabilities`` — capability / version pin status probe

This module never accepts arbitrary SQL. Mutating commands honour
``--dry-run`` (plan + receipts, no state change), emit immutable receipts, and
are idempotent under the same operation scope / idempotency key.

CLI output supports structured (``--format json``) and bounded human text
(``--format text``) modes. Importing this module is inert: no database,
network, or filesystem side effects until an explicit command runs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Final, Mapping, Sequence, TextIO

from ipfs_datasets_py.duckdb_control.capabilities import (
    CAPABILITY_PROBE_SCHEMA,
    ComponentVersions,
    ProbeRequest,
    policy_pin_summary,
    probe_capabilities,
)
from ipfs_datasets_py.duckdb_control.contracts import (
    IdempotencyKey,
    SnapshotId,
    content_identity,
)
from ipfs_datasets_py.duckdb_control.migrations import (
    MemoryMigrationBackend,
    MigrationCatalog,
    MigrationError,
    MigrationReceipt,
    MigrationRunner,
    default_control_plane_migrations,
    schema_digest_for,
)

__all__ = [
    "CLI_SCHEMA",
    "CLI_IMPLEMENTATION_GENERATION",
    "MAX_TEXT_OUTPUT_BYTES",
    "MAX_TEXT_LINE_BYTES",
    "COMMANDS",
    "CliError",
    "ControlStore",
    "CommandResult",
    "build_parser",
    "format_output",
    "main",
    "run",
    "run_command",
]


# ---------------------------------------------------------------------------
# Schema / bounds
# ---------------------------------------------------------------------------

CLI_SCHEMA: Final[str] = "ipfs_datasets_py/duckdb-control-cli@1"
CLI_IMPLEMENTATION_GENERATION: Final[str] = "dqk-006-lane2-attempt1-20260810"

CREATE_RECEIPT_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-control-create-receipt@1"
)
SNAPSHOT_RECEIPT_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-control-snapshot-receipt@1"
)
CHECK_RECEIPT_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-control-check-receipt@1"
)
COMMAND_RESULT_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-control-cli-result@1"
)

# Bounded CLI text: total payload and per-line hard caps (UTF-8 bytes).
MAX_TEXT_OUTPUT_BYTES: Final[int] = 16_384
MAX_TEXT_LINE_BYTES: Final[int] = 512
MAX_JSON_OUTPUT_BYTES: Final[int] = 262_144
_TRUNCATE_MARKER: Final[str] = "…[truncated]"

COMMANDS: Final[tuple[str, ...]] = (
    "create",
    "migrate",
    "inspect",
    "check",
    "snapshot",
    "capabilities",
)

_DEFAULT_NAMESPACE: Final[str] = "duckdb_control"
_DEFAULT_OWNER: Final[str] = "cli-local"
_OUTPUT_FORMATS: Final[frozenset[str]] = frozenset({"json", "text"})


class CliError(ValueError):
    """Fail-closed CLI rejection (bad args, integrity failure, policy)."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utc_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _canonical_json(payload: Any) -> str:
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _receipt_id_for(body: Mapping[str, Any]) -> str:
    return "sha256:" + _sha256_text(_canonical_json(dict(body)))


def _clip_utf8(text: str, *, limit: int) -> str:
    """Clip ``text`` to at most ``limit`` UTF-8 bytes without splitting codepoints."""

    raw = text.encode("utf-8")
    if len(raw) <= limit:
        return text
    marker = _TRUNCATE_MARKER.encode("utf-8")
    if limit <= len(marker):
        return _TRUNCATE_MARKER[:limit]
    budget = limit - len(marker)
    clipped = raw[:budget]
    # Drop any trailing incomplete UTF-8 sequence.
    while clipped and (clipped[-1] & 0xC0) == 0x80:
        clipped = clipped[:-1]
    if clipped and (clipped[-1] & 0xC0) == 0xC0:
        clipped = clipped[:-1]
    return clipped.decode("utf-8", errors="ignore") + _TRUNCATE_MARKER


def _default_catalog() -> MigrationCatalog:
    return MigrationCatalog(
        migrations=default_control_plane_migrations(),
        namespace=_DEFAULT_NAMESPACE,
    )


# ---------------------------------------------------------------------------
# Control store (hermetic; no DuckDB import required)
# ---------------------------------------------------------------------------


@dataclass
class ControlStore:
    """In-process control-plane state used by the operational CLI.

    The store owns a :class:`MemoryMigrationBackend` and immutable create /
    snapshot receipt maps. File-backed persistence is intentionally out of
    scope for DQK-006 (connection policy is DQK-005; authority transition is
    later). Tests inject a store; production callers construct one per process.
    """

    catalog: MigrationCatalog = field(default_factory=_default_catalog)
    backend: MemoryMigrationBackend = field(default_factory=MemoryMigrationBackend)
    owner_id: str = _DEFAULT_OWNER
    created: bool = False
    create_receipt: dict[str, Any] | None = None
    snapshots: dict[str, dict[str, Any]] = field(default_factory=dict)
    # idempotency scope "create" | "snapshot" | "migrate" -> key -> receipt
    idempotency: dict[str, dict[str, dict[str, Any]]] = field(default_factory=dict)
    generation: int = 0
    created_at: str = ""

    def runner(self) -> MigrationRunner:
        return MigrationRunner(
            self.catalog, self.backend, owner_id=self.owner_id
        )

    def schema_digest(self) -> str:
        return self.runner().schema_digest()

    def mutation_fingerprint(self) -> str:
        """Stable fingerprint of mutable store state (for dry-run assertions)."""

        payload = {
            "created": self.created,
            "generation": self.generation,
            "applied": dict(self.backend.list_applied()),
            "applied_versions": dict(self.backend.applied_versions()),
            "in_progress": self.backend.get_in_progress(),
            "statements": list(self.backend.statements),
            "receipt_count": len(self.backend.receipts),
            "snapshot_ids": sorted(self.snapshots),
            "create_receipt_id": (
                None
                if self.create_receipt is None
                else self.create_receipt.get("receipt_id")
            ),
        }
        return content_identity(payload)

    def remember_idempotent(
        self, scope: str, key: str, receipt: Mapping[str, Any]
    ) -> None:
        bucket = self.idempotency.setdefault(scope, {})
        bucket[key] = dict(receipt)

    def lookup_idempotent(self, scope: str, key: str) -> dict[str, Any] | None:
        found = self.idempotency.get(scope, {}).get(key)
        return None if found is None else dict(found)


# ---------------------------------------------------------------------------
# Command results
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CommandResult:
    """Bounded, receipt-oriented CLI command result."""

    command: str
    ok: bool
    status: str
    dry_run: bool = False
    receipt: Mapping[str, Any] | None = None
    data: Mapping[str, Any] = field(default_factory=dict)
    error: str | None = None
    exit_code: int = 0

    def to_dict(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "schema": COMMAND_RESULT_SCHEMA,
            "cli_schema": CLI_SCHEMA,
            "implementation_generation": CLI_IMPLEMENTATION_GENERATION,
            "command": self.command,
            "ok": self.ok,
            "status": self.status,
            "dry_run": self.dry_run,
            "exit_code": self.exit_code,
        }
        if self.receipt is not None:
            body["receipt"] = dict(self.receipt)
        if self.data:
            body["data"] = dict(self.data)
        if self.error is not None:
            body["error"] = self.error
        return body


def _ok(
    command: str,
    *,
    status: str,
    dry_run: bool = False,
    receipt: Mapping[str, Any] | None = None,
    data: Mapping[str, Any] | None = None,
    exit_code: int = 0,
) -> CommandResult:
    return CommandResult(
        command=command,
        ok=True,
        status=status,
        dry_run=dry_run,
        receipt=receipt,
        data=dict(data or {}),
        exit_code=exit_code,
    )


def _fail(
    command: str,
    error: str,
    *,
    status: str = "error",
    dry_run: bool = False,
    data: Mapping[str, Any] | None = None,
    exit_code: int = 2,
) -> CommandResult:
    return CommandResult(
        command=command,
        ok=False,
        status=status,
        dry_run=dry_run,
        data=dict(data or {}),
        error=error,
        exit_code=exit_code,
    )


def _normalize_idempotency_key(raw: str | None, *, scope: str) -> str | None:
    if raw is None or not str(raw).strip():
        return None
    # Validate through the shared contract; re-raise as CliError.
    try:
        key = IdempotencyKey(key=str(raw).strip(), scope=scope)
    except Exception as exc:  # contracts.ContractError
        raise CliError(f"invalid idempotency key: {exc}") from exc
    return key.key


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_create(
    store: ControlStore,
    *,
    dry_run: bool = False,
    idempotency_key: str | None = None,
) -> CommandResult:
    """Bootstrap control schema by applying pending migrations.

    Idempotent: a second create against an already-bootstrapped store returns
    the prior create receipt without re-applying migrations. With an
    idempotency key, exact prior receipts are returned on retry.
    """

    key = _normalize_idempotency_key(idempotency_key, scope="create")
    if key is not None:
        prior = store.lookup_idempotent("create", key)
        if prior is not None:
            return _ok(
                "create",
                status="idempotent_replay",
                dry_run=dry_run,
                receipt=prior,
                data={"idempotent": True, "replayed": True},
            )

    if store.created and not dry_run:
        receipt = store.create_receipt or _build_create_receipt(
            store, dry_run=False, status="already_created", migrations=()
        )
        if key is not None:
            store.remember_idempotent("create", key, receipt)
        return _ok(
            "create",
            status="already_created",
            dry_run=False,
            receipt=receipt,
            data={"idempotent": True, "created": True},
        )

    runner = store.runner()
    pending = runner.pending()

    if dry_run:
        receipts = runner.apply(dry_run=True)
        receipt = _build_create_receipt(
            store,
            dry_run=True,
            status="dry_run",
            migrations=receipts,
            planned_pending=[m.migration_id for m in pending],
        )
        # Dry-run must not set created / remember durable idempotency.
        return _ok(
            "create",
            status="dry_run",
            dry_run=True,
            receipt=receipt,
            data={
                "pending_count": len(pending),
                "would_apply": [m.migration_id for m in pending],
            },
        )

    receipts = runner.apply(dry_run=False, resume=True)
    store.created = True
    if not store.created_at:
        store.created_at = _utc_iso()
    if store.generation < 1:
        store.generation = 1
    status = "created" if receipts else "already_created"
    receipt = _build_create_receipt(
        store, dry_run=False, status=status, migrations=receipts
    )
    store.create_receipt = receipt
    if key is not None:
        store.remember_idempotent("create", key, receipt)
    return _ok(
        "create",
        status=status,
        dry_run=False,
        receipt=receipt,
        data={
            "applied_count": len(receipts),
            "schema_digest": store.schema_digest(),
            "created": True,
        },
    )


def _build_create_receipt(
    store: ControlStore,
    *,
    dry_run: bool,
    status: str,
    migrations: Sequence[MigrationReceipt],
    planned_pending: Sequence[str] | None = None,
) -> dict[str, Any]:
    migration_payloads = [r.to_dict() for r in migrations]
    body = {
        "schema": CREATE_RECEIPT_SCHEMA,
        "status": status,
        "dry_run": dry_run,
        "namespace": store.catalog.namespace,
        "catalog_digest": store.catalog.digest,
        "schema_digest": (
            store.schema_digest()
            if not dry_run
            else (
                migrations[-1].schema_digest
                if migrations
                else schema_digest_for(())
            )
        ),
        "migration_receipts": migration_payloads,
        "pending_planned": list(planned_pending or ()),
        "owner_id": store.owner_id,
        "created_at": store.created_at or _utc_iso(),
        "generation": store.generation if not dry_run else store.generation,
    }
    body["receipt_id"] = _receipt_id_for(
        {
            "schema": body["schema"],
            "status": body["status"],
            "dry_run": body["dry_run"],
            "namespace": body["namespace"],
            "catalog_digest": body["catalog_digest"],
            "schema_digest": body["schema_digest"],
            "migration_receipt_ids": [
                r.get("receipt_id") for r in migration_payloads
            ],
            "owner_id": body["owner_id"],
            "generation": body["generation"],
        }
    )
    return body


def cmd_migrate(
    store: ControlStore,
    *,
    dry_run: bool = False,
    resume: bool = True,
    idempotency_key: str | None = None,
) -> CommandResult:
    """Apply pending catalog migrations (or dry-run the plan)."""

    key = _normalize_idempotency_key(idempotency_key, scope="migrate")
    if key is not None and not dry_run:
        prior = store.lookup_idempotent("migrate", key)
        if prior is not None:
            return _ok(
                "migrate",
                status="idempotent_replay",
                dry_run=False,
                receipt=prior,
                data={"idempotent": True, "replayed": True},
            )

    runner = store.runner()
    pending_before = [m.migration_id for m in runner.pending()]

    if dry_run:
        receipts = runner.apply(dry_run=True, resume=resume)
        receipt = {
            "schema": "ipfs_datasets_py/duckdb-control-migrate-receipt@1",
            "status": "dry_run",
            "dry_run": True,
            "pending_before": pending_before,
            "migration_receipts": [r.to_dict() for r in receipts],
            "schema_digest": (
                receipts[-1].schema_digest if receipts else store.schema_digest()
            ),
            "owner_id": store.owner_id,
            "applied_at": _utc_iso(),
        }
        receipt["receipt_id"] = _receipt_id_for(
            {
                "status": receipt["status"],
                "dry_run": True,
                "pending_before": pending_before,
                "migration_receipt_ids": [
                    r.receipt_id for r in receipts
                ],
                "schema_digest": receipt["schema_digest"],
            }
        )
        return _ok(
            "migrate",
            status="dry_run",
            dry_run=True,
            receipt=receipt,
            data={
                "pending_count": len(pending_before),
                "would_apply": pending_before,
            },
        )

    receipts = runner.apply(dry_run=False, resume=resume)
    if not store.created and receipts:
        store.created = True
        store.created_at = store.created_at or _utc_iso()
        if store.generation < 1:
            store.generation = 1

    status = "applied" if receipts else "noop"
    receipt = {
        "schema": "ipfs_datasets_py/duckdb-control-migrate-receipt@1",
        "status": status,
        "dry_run": False,
        "pending_before": pending_before,
        "migration_receipts": [r.to_dict() for r in receipts],
        "schema_digest": store.schema_digest(),
        "owner_id": store.owner_id,
        "applied_at": _utc_iso(),
        "applied_count": len(receipts),
    }
    receipt["receipt_id"] = _receipt_id_for(
        {
            "status": receipt["status"],
            "dry_run": False,
            "pending_before": pending_before,
            "migration_receipt_ids": [r.receipt_id for r in receipts],
            "schema_digest": receipt["schema_digest"],
            "applied_count": len(receipts),
        }
    )
    if key is not None:
        store.remember_idempotent("migrate", key, receipt)
    if store.create_receipt is None and store.created:
        store.create_receipt = _build_create_receipt(
            store, dry_run=False, status="created", migrations=receipts
        )
    return _ok(
        "migrate",
        status=status,
        dry_run=False,
        receipt=receipt,
        data={
            "applied_count": len(receipts),
            "applied_ids": [r.migration_id for r in receipts],
            "schema_digest": store.schema_digest(),
            "pending_remaining": [m.migration_id for m in runner.pending()],
        },
    )


def cmd_inspect(store: ControlStore) -> CommandResult:
    """Read-only summary of schema, migrations, and snapshots."""

    runner = store.runner()
    applied = dict(runner.backend.list_applied())
    applied_versions = dict(runner.backend.applied_versions())
    pending = [
        {
            "migration_id": m.migration_id,
            "version": m.version,
            "checksum": m.checksum,
            "description": m.description,
        }
        for m in runner.pending()
    ]
    applied_rows = [
        {
            "migration_id": m.migration_id,
            "version": m.version,
            "checksum": applied[m.migration_id],
            "description": m.description,
        }
        for m in store.catalog.migrations
        if m.migration_id in applied
    ]
    data = {
        "namespace": store.catalog.namespace,
        "catalog_digest": store.catalog.digest,
        "schema_digest": store.schema_digest(),
        "created": store.created,
        "created_at": store.created_at or None,
        "generation": store.generation,
        "applied_count": len(applied),
        "pending_count": len(pending),
        "applied": applied_rows,
        "pending": pending,
        "applied_versions": applied_versions,
        "snapshot_count": len(store.snapshots),
        "snapshot_ids": sorted(store.snapshots),
        "in_progress": store.backend.get_in_progress(),
        "policy_pins": dict(policy_pin_summary()),
    }
    return _ok("inspect", status="ok", data=data)


def cmd_check(store: ControlStore) -> CommandResult:
    """Fail-closed integrity check of applied migrations vs catalog."""

    issues: list[str] = []
    runner = store.runner()
    try:
        pending = runner.pending()
    except MigrationError as exc:
        issues.append(str(exc))
        pending = ()

    applied = dict(store.backend.list_applied())
    known = {m.migration_id: m for m in store.catalog.migrations}

    for migration_id, checksum in applied.items():
        migration = known.get(migration_id)
        if migration is None:
            msg = f"unknown applied migration {migration_id!r}"
            if msg not in issues:
                issues.append(msg)
            continue
        if checksum != migration.checksum:
            issues.append(
                f"checksum drift for {migration_id}: "
                f"stored {checksum}, catalog {migration.checksum}"
            )

    in_progress = store.backend.get_in_progress()
    if in_progress is not None and in_progress not in known:
        issues.append(f"in-progress marker {in_progress!r} is not in catalog")

    # Contiguous applied versions from catalog order.
    applied_versions = [
        m.version for m in store.catalog.migrations if m.migration_id in applied
    ]
    if applied_versions:
        expected = list(
            range(applied_versions[0], applied_versions[0] + len(applied_versions))
        )
        if applied_versions != expected:
            issues.append(
                f"applied versions are not contiguous: {applied_versions}"
            )

    schema_digest = (
        store.schema_digest()
        if not any("unknown applied" in i or "checksum drift" in i for i in issues)
        else None
    )
    try:
        if schema_digest is None and not issues:
            schema_digest = store.schema_digest()
        elif schema_digest is None and not any(
            "unknown" in i or "checksum" in i for i in issues
        ):
            schema_digest = store.schema_digest()
    except MigrationError as exc:
        issues.append(str(exc))
        schema_digest = None

    ok = not issues
    receipt = {
        "schema": CHECK_RECEIPT_SCHEMA,
        "status": "ok" if ok else "failed",
        "ok": ok,
        "issue_count": len(issues),
        "issues": issues,
        "schema_digest": schema_digest,
        "pending_count": len(pending),
        "pending_ids": [m.migration_id for m in pending],
        "applied_count": len(applied),
        "catalog_digest": store.catalog.digest,
        "namespace": store.catalog.namespace,
        "checked_at": _utc_iso(),
    }
    receipt["receipt_id"] = _receipt_id_for(
        {
            "status": receipt["status"],
            "ok": ok,
            "issues": issues,
            "schema_digest": schema_digest,
            "catalog_digest": store.catalog.digest,
            "applied_count": len(applied),
            "pending_count": len(pending),
        }
    )
    if ok:
        return _ok(
            "check",
            status="ok",
            receipt=receipt,
            data={
                "ok": True,
                "schema_digest": schema_digest,
                "pending_count": len(pending),
            },
        )
    return CommandResult(
        command="check",
        ok=False,
        status="failed",
        receipt=receipt,
        data={"ok": False, "issue_count": len(issues)},
        error="; ".join(issues) if issues else "integrity check failed",
        exit_code=1,
    )


def cmd_snapshot(
    store: ControlStore,
    *,
    dry_run: bool = False,
    idempotency_key: str | None = None,
) -> CommandResult:
    """Capture a content-addressed control snapshot (idempotent, receipted)."""

    key = _normalize_idempotency_key(idempotency_key, scope="snapshot")
    if key is not None:
        prior = store.lookup_idempotent("snapshot", key)
        if prior is not None:
            prior_snap = prior.get("snapshot") if isinstance(prior, Mapping) else None
            prior_id = (
                prior_snap.get("value")
                if isinstance(prior_snap, Mapping)
                else prior.get("body_digest")
            )
            return _ok(
                "snapshot",
                status="idempotent_replay",
                dry_run=dry_run,
                receipt=prior,
                data={
                    "idempotent": True,
                    "replayed": True,
                    "snapshot_id": prior_id,
                },
            )

    if not store.created and not store.backend.list_applied():
        # Allow snapshot of empty state only as dry-run plan, else fail closed
        # so operators must create/migrate first for durable snapshots.
        if not dry_run:
            raise CliError(
                "cannot snapshot: control store is not created; run create/migrate first"
            )

    applied = dict(store.backend.list_applied())
    schema_digest = store.schema_digest()
    # Schema digest for SnapshotId.schema_checksum must be sha256:... form.
    # Our migration digest is schema-digest:sha256:<hex>; map to content digest.
    schema_checksum = (
        "sha256:" + schema_digest.split("sha256:", 1)[-1]
        if "sha256:" in schema_digest
        else schema_digest
    )
    body = {
        "namespace": store.catalog.namespace,
        "catalog_digest": store.catalog.digest,
        "schema_digest": schema_digest,
        "applied": applied,
        "applied_versions": dict(store.backend.applied_versions()),
        "generation": store.generation,
        "created": store.created,
        "created_at": store.created_at or None,
    }
    body_digest = content_identity(body)
    snapshot_id = SnapshotId(
        value=body_digest,
        store_generation=store.generation,
        schema_checksum=schema_checksum,
    )

    if dry_run:
        receipt = {
            "schema": SNAPSHOT_RECEIPT_SCHEMA,
            "status": "dry_run",
            "dry_run": True,
            "snapshot": snapshot_id.to_dict(),
            "body_digest": body_digest,
            "schema_digest": schema_digest,
            "generation": store.generation,
            "created_at": _utc_iso(),
            "body": body,
        }
        receipt["receipt_id"] = _receipt_id_for(
            {
                "status": "dry_run",
                "dry_run": True,
                "snapshot_value": snapshot_id.value,
                "body_digest": body_digest,
                "schema_digest": schema_digest,
            }
        )
        return _ok(
            "snapshot",
            status="dry_run",
            dry_run=True,
            receipt=receipt,
            data={
                "snapshot_id": snapshot_id.value,
                "would_persist": True,
            },
        )

    # Idempotent by content: same body digest returns existing snapshot receipt.
    existing = store.snapshots.get(snapshot_id.value)
    if existing is not None:
        if key is not None:
            store.remember_idempotent("snapshot", key, existing)
        return _ok(
            "snapshot",
            status="idempotent_replay",
            dry_run=False,
            receipt=existing,
            data={
                "idempotent": True,
                "replayed": True,
                "snapshot_id": snapshot_id.value,
            },
        )

    store.generation = max(1, store.generation + 1)
    # Rebind generation into body after bump for durable record.
    body = dict(body)
    body["generation"] = store.generation
    body_digest = content_identity(body)
    schema_checksum = (
        "sha256:" + schema_digest.split("sha256:", 1)[-1]
        if "sha256:" in schema_digest
        else schema_digest
    )
    snapshot_id = SnapshotId(
        value=body_digest,
        store_generation=store.generation,
        schema_checksum=schema_checksum,
    )
    created_at = _utc_iso()
    receipt = {
        "schema": SNAPSHOT_RECEIPT_SCHEMA,
        "status": "created",
        "dry_run": False,
        "snapshot": snapshot_id.to_dict(),
        "body_digest": body_digest,
        "schema_digest": schema_digest,
        "generation": store.generation,
        "created_at": created_at,
        "body": body,
    }
    receipt["receipt_id"] = _receipt_id_for(
        {
            "status": "created",
            "dry_run": False,
            "snapshot_value": snapshot_id.value,
            "body_digest": body_digest,
            "schema_digest": schema_digest,
            "generation": store.generation,
            "created_at": created_at,
        }
    )
    store.snapshots[snapshot_id.value] = receipt
    if key is not None:
        store.remember_idempotent("snapshot", key, receipt)
    return _ok(
        "snapshot",
        status="created",
        dry_run=False,
        receipt=receipt,
        data={
            "snapshot_id": snapshot_id.value,
            "generation": store.generation,
            "schema_digest": schema_digest,
        },
    )


def cmd_capabilities(
    *,
    enable_quack: bool = False,
    enable_vss: bool = False,
    versions: ComponentVersions | None = None,
    observe: Callable[[], ComponentVersions] | None = None,
    fail_closed: bool = True,
) -> CommandResult:
    """Probe DuckDB / Quack / VSS capability status (no SQL surface)."""

    request = ProbeRequest(
        enable_quack=enable_quack,
        enable_vss=enable_vss,
        require_server=False,
        require_protocol=enable_quack,
    )
    result = probe_capabilities(
        request,
        versions=versions,
        observe=observe,
        fail_closed=fail_closed,
    )
    payload = dict(result.as_mapping())
    # Ensure probe schema is present for operators / receipts.
    payload.setdefault("schema", CAPABILITY_PROBE_SCHEMA)
    status = "ok" if result.ok else "failed"
    exit_code = 0 if result.ok else 1
    if result.ok:
        return _ok(
            "capabilities",
            status=status,
            receipt=payload,
            data={
                "ok": True,
                "pins": dict(policy_pin_summary()),
                "quack_beta": result.quack_beta,
                "transport": dict(result.transport.as_mapping()),
            },
            exit_code=exit_code,
        )
    return CommandResult(
        command="capabilities",
        ok=False,
        status=status,
        receipt=payload,
        data={
            "ok": False,
            "mismatches": list(result.mismatches),
            "pins": dict(policy_pin_summary()),
        },
        error="; ".join(result.mismatches) or "capability probe failed",
        exit_code=exit_code,
    )


# ---------------------------------------------------------------------------
# Output formatting (bounded text + structured JSON)
# ---------------------------------------------------------------------------


def format_output(
    result: CommandResult | Mapping[str, Any],
    *,
    fmt: str = "json",
) -> str:
    """Render a command result as bounded text or structured JSON."""

    mode = (fmt or "json").strip().lower()
    if mode not in _OUTPUT_FORMATS:
        raise CliError(f"unsupported output format {fmt!r}; use json or text")

    payload = result.to_dict() if isinstance(result, CommandResult) else dict(result)

    if mode == "json":
        text = _canonical_json(payload)
        raw = text.encode("utf-8")
        if len(raw) > MAX_JSON_OUTPUT_BYTES:
            # Prefer a truncated structured envelope over unbounded dump.
            slim = {
                "schema": COMMAND_RESULT_SCHEMA,
                "ok": payload.get("ok"),
                "status": payload.get("status"),
                "command": payload.get("command"),
                "error": "result exceeded JSON output bound",
                "truncated": True,
                "original_bytes": len(raw),
                "bound_bytes": MAX_JSON_OUTPUT_BYTES,
            }
            return _canonical_json(slim)
        return text

    # Bounded human-readable text mode.
    lines: list[str] = [
        f"command: {payload.get('command')}",
        f"status: {payload.get('status')}",
        f"ok: {payload.get('ok')}",
        f"dry_run: {payload.get('dry_run', False)}",
    ]
    if payload.get("error"):
        lines.append(f"error: {payload['error']}")
    receipt = payload.get("receipt")
    if isinstance(receipt, Mapping):
        rid = receipt.get("receipt_id") or receipt.get("schema")
        if rid:
            lines.append(f"receipt: {rid}")
        if receipt.get("schema_digest"):
            lines.append(f"schema_digest: {receipt['schema_digest']}")
        if receipt.get("snapshot") and isinstance(receipt["snapshot"], Mapping):
            lines.append(f"snapshot: {receipt['snapshot'].get('value')}")
    data = payload.get("data")
    if isinstance(data, Mapping):
        for key in (
            "schema_digest",
            "applied_count",
            "pending_count",
            "snapshot_id",
            "generation",
            "created",
            "ok",
        ):
            if key in data:
                lines.append(f"{key}: {data[key]}")
        pins = data.get("pins")
        if isinstance(pins, Mapping):
            lines.append(
                "pins: duckdb={duckdb} quack={quack_build} vss={vss_build}".format(
                    **{
                        "duckdb": pins.get("duckdb"),
                        "quack_build": pins.get("quack_build"),
                        "vss_build": pins.get("vss_build"),
                    }
                )
            )

    clipped_lines = [
        _clip_utf8(line, limit=MAX_TEXT_LINE_BYTES) for line in lines
    ]
    text = "\n".join(clipped_lines) + "\n"
    return _clip_utf8(text, limit=MAX_TEXT_OUTPUT_BYTES)


# ---------------------------------------------------------------------------
# Argparse surface (no SQL arguments)
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m ipfs_datasets_py.duckdb_control.cli",
        description=(
            "Fail-closed DuckDB control-plane CLI. "
            "Typed operations only; arbitrary SQL is rejected."
        ),
    )
    # Shared options accepted before *or* after the subcommand name.
    # Subparser defaults use SUPPRESS so they do not clobber values set on
    # the root parser (argparse otherwise resets dests to subparser defaults).
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--format",
        dest="output_format",
        choices=sorted(_OUTPUT_FORMATS),
        default=argparse.SUPPRESS,
        help="Output mode: structured json (default) or bounded text",
    )
    common.add_argument(
        "--owner-id",
        default=argparse.SUPPRESS,
        help="Migration lock owner identity",
    )
    parser.add_argument(
        "--format",
        dest="output_format",
        choices=sorted(_OUTPUT_FORMATS),
        default="json",
        help="Output mode: structured json (default) or bounded text",
    )
    parser.add_argument(
        "--owner-id",
        default=_DEFAULT_OWNER,
        help="Migration lock owner identity",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    p_create = sub.add_parser(
        "create",
        parents=[common],
        help="Bootstrap control schema (idempotent, receipted)",
    )
    p_create.add_argument(
        "--dry-run",
        action="store_true",
        help="Plan create without mutating store state",
    )
    p_create.add_argument(
        "--idempotency-key",
        default=None,
        help="Caller-supplied idempotency key for create",
    )

    p_migrate = sub.add_parser(
        "migrate",
        parents=[common],
        help="Apply pending checksummed migrations",
    )
    p_migrate.add_argument(
        "--dry-run",
        action="store_true",
        help="Plan migrations without mutating store state",
    )
    p_migrate.add_argument(
        "--no-resume",
        action="store_true",
        help="Fail closed on interrupted migration instead of resuming",
    )
    p_migrate.add_argument(
        "--idempotency-key",
        default=None,
        help="Caller-supplied idempotency key for migrate",
    )

    sub.add_parser(
        "inspect",
        parents=[common],
        help="Read-only schema/migration/snapshot summary",
    )

    sub.add_parser(
        "check",
        parents=[common],
        help="Integrity check of applied migrations vs catalog",
    )

    p_snapshot = sub.add_parser(
        "snapshot",
        parents=[common],
        help="Content-addressed control snapshot (idempotent)",
    )
    p_snapshot.add_argument(
        "--dry-run",
        action="store_true",
        help="Plan snapshot without persisting it",
    )
    p_snapshot.add_argument(
        "--idempotency-key",
        default=None,
        help="Caller-supplied idempotency key for snapshot",
    )

    p_caps = sub.add_parser(
        "capabilities",
        parents=[common],
        help="Probe DuckDB/Quack/VSS capability and pin status",
    )
    p_caps.add_argument(
        "--enable-quack",
        action="store_true",
        help="Request Quack transport feature gate",
    )
    p_caps.add_argument(
        "--enable-vss",
        action="store_true",
        help="Request VSS index feature gate",
    )
    p_caps.add_argument(
        "--fail-open",
        action="store_true",
        help="Do not fail the process on version mismatches (default: fail closed)",
    )

    return parser


def _reject_sql_argv(argv: Sequence[str]) -> None:
    """Fail closed if argv appears to smuggle raw SQL.

    The CLI never accepts a SQL body. Common smuggling flags and SQL keywords
    as free arguments are rejected before dispatch.
    """

    forbidden_flags = {
        "--sql",
        "--query",
        "--execute",
        "--statement",
        "-c",
        "--command-sql",
    }
    # Free-form SQL statement smuggling (not the typed ``create`` subcommand).
    for arg in argv:
        lower = arg.strip().lower()
        if lower in forbidden_flags or lower.startswith("--sql="):
            raise CliError(
                f"arbitrary SQL is not accepted by this CLI (flag {arg!r})"
            )
        if ";" in arg and any(
            token in lower for token in ("select ", "insert ", "update ", "delete ")
        ):
            raise CliError("arbitrary SQL is not accepted by this CLI")


def run_command(
    command: str,
    store: ControlStore,
    *,
    dry_run: bool = False,
    resume: bool = True,
    idempotency_key: str | None = None,
    enable_quack: bool = False,
    enable_vss: bool = False,
    fail_closed: bool = True,
    versions: ComponentVersions | None = None,
    observe: Callable[[], ComponentVersions] | None = None,
) -> CommandResult:
    """Dispatch a typed command against ``store`` (or capability probe)."""

    name = (command or "").strip().lower()
    if name not in COMMANDS:
        raise CliError(
            f"unknown command {command!r}; expected one of {', '.join(COMMANDS)}"
        )

    if name == "create":
        return cmd_create(
            store, dry_run=dry_run, idempotency_key=idempotency_key
        )
    if name == "migrate":
        return cmd_migrate(
            store,
            dry_run=dry_run,
            resume=resume,
            idempotency_key=idempotency_key,
        )
    if name == "inspect":
        return cmd_inspect(store)
    if name == "check":
        return cmd_check(store)
    if name == "snapshot":
        return cmd_snapshot(
            store, dry_run=dry_run, idempotency_key=idempotency_key
        )
    if name == "capabilities":
        return cmd_capabilities(
            enable_quack=enable_quack,
            enable_vss=enable_vss,
            versions=versions,
            observe=observe,
            fail_closed=fail_closed,
        )
    raise CliError(f"unhandled command {name!r}")


def run(
    argv: Sequence[str] | None = None,
    *,
    store: ControlStore | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    versions: ComponentVersions | None = None,
    observe: Callable[[], ComponentVersions] | None = None,
) -> int:
    """Parse argv, run one command, write bounded output, return exit code."""

    import contextlib

    out = stdout if stdout is not None else sys.stdout
    err = stderr if stderr is not None else sys.stderr
    args_list = list(sys.argv[1:] if argv is None else argv)

    try:
        _reject_sql_argv(args_list)
        parser = build_parser()
        # Redirect so --help / usage honour injected streams under test.
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            ns = parser.parse_args(args_list)
    except CliError as exc:
        payload = _fail("unknown", str(exc)).to_dict()
        print(format_output(payload, fmt="json"), file=err)
        return 2
    except SystemExit as exc:
        # argparse already printed help/usage to the redirected streams.
        code = exc.code
        if code is None:
            return 0
        return int(code) if not isinstance(code, bool) else (1 if code else 0)

    active = store if store is not None else ControlStore(owner_id=ns.owner_id)
    if store is None:
        active.owner_id = str(ns.owner_id or _DEFAULT_OWNER)

    fmt = getattr(ns, "output_format", "json") or "json"
    dry_run = bool(getattr(ns, "dry_run", False))
    resume = not bool(getattr(ns, "no_resume", False))
    idempotency_key = getattr(ns, "idempotency_key", None)
    enable_quack = bool(getattr(ns, "enable_quack", False))
    enable_vss = bool(getattr(ns, "enable_vss", False))
    fail_closed = not bool(getattr(ns, "fail_open", False))

    try:
        result = run_command(
            ns.command,
            active,
            dry_run=dry_run,
            resume=resume,
            idempotency_key=idempotency_key,
            enable_quack=enable_quack,
            enable_vss=enable_vss,
            fail_closed=fail_closed,
            versions=versions,
            observe=observe,
        )
    except CliError as exc:
        result = _fail(ns.command, str(exc), dry_run=dry_run)
    except MigrationError as exc:
        result = _fail(ns.command, str(exc), dry_run=dry_run, status="migration_error")
    except Exception as exc:  # pragma: no cover - unexpected; still fail closed
        result = _fail(ns.command, f"unexpected error: {exc}", dry_run=dry_run)

    rendered = format_output(result, fmt=fmt)
    print(rendered, file=out, end="" if rendered.endswith("\n") else "\n")
    return int(result.exit_code)


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for ``python -m ipfs_datasets_py.duckdb_control.cli``."""

    return run(argv)


if __name__ == "__main__":
    raise SystemExit(main())
