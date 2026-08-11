"""Filesystem repository for canonical wallet snapshots.

Dual-mode cutover (DQK-075): DuckDB is authoritative for mutable public
metadata (manifests, analytics, audit chain, grants, approvals) while full
JSON envelopes remain a dual-written legacy surface for exact secret-bearing
round-trips. Encrypted payload bytes stay in the configured content-addressed
blob store (never DuckDB or Quack).

Authority model:

* **dual** — dual-write JSON envelopes and DuckDB projections; reads prefer
  DuckDB for public metadata while restore still uses the JSON envelope.
* **db-primary** — DuckDB is the authority surface; JSON is an outbox/export
  projection kept for compatibility until DQK-076.
* **shadow** (DQK-074) — JSON remains authority; DuckDB is a redacted shadow.

Every save is CAS-gated on ``authority_revision`` so a stale service instance
cannot overwrite a newer revision.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Optional

from ipfs_datasets_py.duckdb_control.authority_transition import (
    AuthorityMode,
    DecisionKind,
    DecisionReceipt,
    PromotionBlockedError,
)

from .duckdb_repository import (
    MutationKind,
    MutationReceipt,
    WalletDuckDBRepository,
    build_wallet_duckdb_repository,
    new_operation_id,
)
from .exceptions import DataWalletError, MissingRecordError
from .manifest import canonical_bytes, canonical_dumps
from .service import DataWalletService


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


SNAPSHOT_TYPE = "wallet_repository_snapshot_v1"
ANALYTICS_LEDGER_TYPE = "wallet_repository_analytics_ledger_v1"
ANALYTICS_LEDGER_FILENAME = "analytics-ledger.json"

# Default post-DQK-074 cutover mode: dual-write with DuckDB preferred for
# public metadata reads on the authority port.
DEFAULT_AUTHORITY_MODE: AuthorityMode = AuthorityMode.DUAL


class StaleRevisionError(DataWalletError):
    """Raised when a save would overwrite a newer authoritative revision."""

    def __init__(
        self,
        message: str,
        *,
        wallet_id: str = "",
        expected_revision: int | None = None,
        current_revision: int | None = None,
    ) -> None:
        super().__init__(message)
        self.wallet_id = wallet_id
        self.expected_revision = expected_revision
        self.current_revision = current_revision


class LocalWalletRepository:
    """Persist and restore `DataWalletService` state for one wallet.

    This repository stores wallet manifests and encrypted-blob references. It is
    intended for local development and CLI workflows. Encrypted payload bytes
    remain in the configured blob store.

    When an event port is attached (default: dual-mode in-process port), every
    save emits an idempotent operation id, dual-writes a redacted DuckDB
    projection, and advances a CAS-gated authority revision.
    """

    def __init__(
        self,
        root: str | Path,
        *,
        shadow: WalletDuckDBRepository | bool | None = True,
        authority_mode: AuthorityMode | str | None = None,
    ) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._revisions: dict[str, int] = {}
        self._analytics_revision: int = 0
        self._last_mutation_receipts: list[MutationReceipt] = []
        self._shadow: WalletDuckDBRepository | None
        mode = (
            AuthorityMode.parse(authority_mode)
            if authority_mode is not None
            else DEFAULT_AUTHORITY_MODE
        )
        if shadow is True or shadow is None:
            self._shadow = build_wallet_duckdb_repository(mode=mode)
        elif shadow is False:
            self._shadow = None
        else:
            self._shadow = shadow
            # Honour explicit mode only when the caller also asked for it and
            # the port is still at its constructor mode without prior promote.
            if authority_mode is not None and self._shadow.authority_mode != mode:
                # Best-effort: leave attached port as-is; mode is owned by the
                # shared process-local event port (API/CLI).
                pass

    @property
    def shadow(self) -> WalletDuckDBRepository | None:
        return self._shadow

    @property
    def event_port(self) -> WalletDuckDBRepository | None:
        """Alias for the dual-mode DuckDB event port (DQK-075)."""

        return self._shadow

    @property
    def authority_mode(self) -> AuthorityMode | None:
        if self._shadow is None:
            return None
        return self._shadow.authority_mode

    @property
    def last_mutation_receipts(self) -> list[MutationReceipt]:
        return list(self._last_mutation_receipts)

    def wallet_path(self, wallet_id: str) -> Path:
        return self.root / f"{wallet_id}.json"

    def analytics_ledger_path(self) -> Path:
        return self.root / ANALYTICS_LEDGER_FILENAME

    def snapshot_hash(self, snapshot: dict[str, Any]) -> str:
        return _sha256_hex(canonical_bytes(snapshot))

    def _read_revision_from_disk(self, wallet_id: str) -> int:
        path = self.wallet_path(wallet_id)
        if not path.exists():
            return 0
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return 0
        return int(payload.get("authority_revision") or 0)

    def _read_analytics_revision_from_disk(self) -> int:
        path = self.analytics_ledger_path()
        if not path.exists():
            return 0
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return 0
        return int(payload.get("authority_revision") or 0)

    def current_revision(self, wallet_id: str) -> int:
        """Return the durable authority revision for *wallet_id* (0 if new)."""

        with self._lock:
            rev = self._read_revision_from_disk(wallet_id)
            self._revisions[wallet_id] = rev
            return rev

    def current_analytics_revision(self) -> int:
        with self._lock:
            rev = self._read_analytics_revision_from_disk()
            self._analytics_revision = rev
            return rev

    @contextmanager
    def _exclusive_lock(self, name: str) -> Iterator[None]:
        """Cross-instance exclusive lock for CAS-gated dual-mode writes.

        Threads and processes that share a repository root must serialize
        revision checks and atomic envelope replace so a stale writer cannot
        overwrite a newer revision (DQK-075).
        """

        lock_path = self.root / f".{name}.authority.lock"
        self.root.mkdir(parents=True, exist_ok=True)
        # Open+create outside the flock so concurrent creators do not race the
        # exclusive region itself.
        fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o644)
        try:
            try:
                import fcntl

                fcntl.flock(fd, fcntl.LOCK_EX)
            except (ImportError, OSError):
                # Best-effort fallback: process-local lock only (non-POSIX).
                self._lock.acquire()
                try:
                    yield
                finally:
                    self._lock.release()
                return
            try:
                yield
            finally:
                try:
                    import fcntl

                    fcntl.flock(fd, fcntl.LOCK_UN)
                except (ImportError, OSError):
                    pass
        finally:
            os.close(fd)

    def promote_to_db_primary(
        self,
        *,
        parity_key: str,
        decision_id: str | None = None,
        require_parity: bool = True,
    ) -> DecisionReceipt:
        """Promote the attached event port from dual → db-primary.

        Requires a parity key that already has matching dual-written surfaces.
        """

        if self._shadow is None:
            raise DataWalletError("cannot promote without a DuckDB event port")
        port = self._shadow.authority_port
        if port.mode is AuthorityMode.DB_PRIMARY:
            # Idempotent: already authoritative.
            state = port.state()
            return DecisionReceipt(
                receipt_cid=state.last_decision_receipt_cid or "",
                kind=DecisionKind.PROMOTE,
                domain=port.domain,
                from_mode=AuthorityMode.DB_PRIMARY,
                to_mode=AuthorityMode.DB_PRIMARY,
                expected_cas_revision=state.cas_revision,
                new_cas_revision=state.cas_revision,
                fence=state.fence,
                parity_receipt_cid=state.last_parity_receipt_cid or "",
                decision_id=decision_id or "already-db-primary",
                accepted=True,
                reason="already_db_primary",
                created_at=state.updated_at or "",
                atomic_across_filesystems=False,
            )
        return port.promote(
            AuthorityMode.DB_PRIMARY,
            decision_id=decision_id,
            require_parity=require_parity,
            parity_key=parity_key,
        )

    def ensure_duckdb_authority(
        self,
        wallet_id: str,
        *,
        decision_id: str | None = None,
    ) -> DecisionReceipt | None:
        """Ensure DuckDB is authoritative for *wallet_id* (dual → db-primary).

        No-op when no event port is attached or mode is already db-primary.
        """

        if self._shadow is None:
            return None
        mode = self._shadow.authority_mode
        if mode is AuthorityMode.DB_PRIMARY:
            return None
        if mode is AuthorityMode.DUAL:
            return self.promote_to_db_primary(
                parity_key=f"wallet:{wallet_id}",
                decision_id=decision_id or f"cutover:{wallet_id}",
            )
        if mode is AuthorityMode.SHADOW:
            # Promote shadow → dual first, then dual → db-primary.
            first = self._shadow.authority_port.promote(
                AuthorityMode.DUAL,
                decision_id=f"to-dual:{wallet_id}",
                require_parity=True,
                parity_key=f"wallet:{wallet_id}",
            )
            if not first.accepted:
                raise PromotionBlockedError(
                    first.reason or "shadow→dual promotion rejected",
                    reason=first.reason or "promotion_rejected",
                )
            return self.promote_to_db_primary(
                parity_key=f"wallet:{wallet_id}",
                decision_id=decision_id or f"cutover:{wallet_id}",
            )
        return None

    def save(
        self,
        service: DataWalletService,
        wallet_id: str,
        *,
        operation_id: str | None = None,
        expected_revision: int | None = None,
    ) -> Path:
        path = self._save_wallet_snapshot(
            service,
            wallet_id,
            operation_id=operation_id,
            expected_revision=expected_revision,
        )
        self.save_analytics_ledger(service)
        return path

    def _save_wallet_snapshot(
        self,
        service: DataWalletService,
        wallet_id: str,
        *,
        operation_id: str | None = None,
        expected_revision: int | None = None,
    ) -> Path:
        # Resolve the caller's expected revision outside the exclusive lock so
        # service inspection is not serialized; durable CAS still happens under
        # the flock below.
        if expected_revision is None:
            if hasattr(service, "authority_revision"):
                expected_revision = int(service.authority_revision(wallet_id))
            else:
                expected_revision = self._read_revision_from_disk(wallet_id)

        with self._exclusive_lock(wallet_id):
            current = self._read_revision_from_disk(wallet_id)
            if current == 0:
                # First durable write into this repository root: bootstrap the
                # authority revision even when the service already holds a
                # revision learned from another dual-mode surface.
                new_revision = 1
            elif expected_revision != current:
                raise StaleRevisionError(
                    f"stale authority revision for {wallet_id}: "
                    f"expected {expected_revision}, durable is {current}",
                    wallet_id=wallet_id,
                    expected_revision=expected_revision,
                    current_revision=current,
                )
            else:
                new_revision = current + 1
            snapshot = service.export_wallet_snapshot(wallet_id)
            payload = {
                "snapshot_type": SNAPSHOT_TYPE,
                "wallet_id": wallet_id,
                "snapshot_hash": self.snapshot_hash(snapshot),
                "authority_revision": new_revision,
                "authority_mode": (
                    self._shadow.authority_mode.value if self._shadow is not None else "legacy"
                ),
                "snapshot": snapshot,
            }
            path = self.wallet_path(wallet_id)
            # Unique tmp name so concurrent CAS losers cannot unlink the winner's
            # temp file mid-replace (threads share the same repository root).
            tmp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
            tmp_path.write_text(canonical_dumps(payload) + "\n", encoding="utf-8")
            tmp_path.replace(path)
            self._revisions[wallet_id] = new_revision
            if hasattr(service, "note_authority_revision"):
                service.note_authority_revision(wallet_id, new_revision)
            self._shadow_wallet(
                snapshot,
                operation_id=operation_id,
                authority_revision=new_revision,
            )
            return path

    def save_all(
        self,
        service: DataWalletService,
        *,
        operation_id: str | None = None,
    ) -> list[Path]:
        paths = [
            self._save_wallet_snapshot(
                service,
                wallet_id,
                operation_id=(
                    f"{operation_id}:{wallet_id}" if operation_id else None
                ),
            )
            for wallet_id in sorted(service.wallets)
        ]
        self.save_analytics_ledger(service, operation_id=operation_id)
        return paths

    def save_analytics_ledger(
        self,
        service: DataWalletService,
        *,
        operation_id: str | None = None,
        expected_revision: int | None = None,
    ) -> Path:
        if expected_revision is None:
            expected_revision = self._read_analytics_revision_from_disk()

        with self._exclusive_lock("analytics-ledger"):
            current = self._read_analytics_revision_from_disk()
            if current == 0:
                new_revision = 1
            elif expected_revision != current:
                raise StaleRevisionError(
                    f"stale analytics authority revision: "
                    f"expected {expected_revision}, durable is {current}",
                    wallet_id="",
                    expected_revision=expected_revision,
                    current_revision=current,
                )
            else:
                new_revision = current + 1
            ledger = service.export_analytics_ledger()
            payload = {
                "snapshot_type": ANALYTICS_LEDGER_TYPE,
                "snapshot_hash": self.snapshot_hash(ledger),
                "authority_revision": new_revision,
                "authority_mode": (
                    self._shadow.authority_mode.value if self._shadow is not None else "legacy"
                ),
                "ledger": ledger,
            }
            path = self.analytics_ledger_path()
            tmp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
            tmp_path.write_text(canonical_dumps(payload) + "\n", encoding="utf-8")
            tmp_path.replace(path)
            self._analytics_revision = new_revision
            self._shadow_analytics(
                ledger,
                operation_id=operation_id,
                authority_revision=new_revision,
            )
            return path

    def load(self, service: DataWalletService, wallet_id: str) -> None:
        path = self.wallet_path(wallet_id)
        if not path.exists():
            raise MissingRecordError(f"Wallet snapshot not found: {wallet_id}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        revision = int(payload.get("authority_revision") or 0)
        service.import_wallet_snapshot(self._snapshot_from_payload(payload, wallet_id))
        if hasattr(service, "note_authority_revision"):
            service.note_authority_revision(wallet_id, revision)
        with self._lock:
            self._revisions[wallet_id] = revision
        self.load_analytics_ledger(service, required=False)
        self._verify_authority_projection(service, wallet_id, snapshot_payload=payload)

    def load_all(self, service: DataWalletService) -> list[str]:
        wallet_ids = self.list_wallet_ids()
        for wallet_id in wallet_ids:
            path = self.wallet_path(wallet_id)
            payload = json.loads(path.read_text(encoding="utf-8"))
            revision = int(payload.get("authority_revision") or 0)
            service.import_wallet_snapshot(self._snapshot_from_payload(payload, wallet_id))
            if hasattr(service, "note_authority_revision"):
                service.note_authority_revision(wallet_id, revision)
            with self._lock:
                self._revisions[wallet_id] = revision
            self._verify_authority_projection(service, wallet_id, snapshot_payload=payload)
        self.load_analytics_ledger(service, required=False)
        return wallet_ids

    def load_analytics_ledger(self, service: DataWalletService, *, required: bool = True) -> None:
        path = self.analytics_ledger_path()
        if not path.exists():
            if required:
                raise MissingRecordError("Analytics ledger snapshot not found")
            return
        payload = json.loads(path.read_text(encoding="utf-8"))
        revision = int(payload.get("authority_revision") or 0)
        service.import_analytics_ledger(self._analytics_ledger_from_payload(payload))
        with self._lock:
            self._analytics_revision = revision

    def list_wallet_ids(self) -> list[str]:
        return sorted(path.stem for path in self.root.glob("wallet-*.json"))

    def verify(self, wallet_id: str) -> dict[str, Any]:
        path = self.wallet_path(wallet_id)
        report: dict[str, Any] = {
            "wallet_id": wallet_id,
            "path": str(path),
            "exists": path.exists(),
            "valid": False,
        }
        if not path.exists():
            report["error"] = "Wallet snapshot not found"
            return report
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            report["error"] = f"Invalid JSON: {exc.msg}"
            return report

        if self._is_snapshot_envelope(payload):
            snapshot = payload.get("snapshot")
            if not isinstance(snapshot, dict):
                report["format"] = "envelope"
                report["error"] = "Snapshot envelope is missing a snapshot object"
                return report
            computed_hash = self.snapshot_hash(snapshot)
            expected_hash = payload.get("snapshot_hash")
            authority_revision = int(payload.get("authority_revision") or 0)
            report.update(
                {
                    "format": "envelope",
                    "snapshot_hash": expected_hash,
                    "computed_hash": computed_hash,
                    "authority_revision": authority_revision,
                    "authority_mode": payload.get("authority_mode"),
                    "valid": (
                        payload.get("snapshot_type") == SNAPSHOT_TYPE
                        and payload.get("wallet_id") == wallet_id
                        and expected_hash == computed_hash
                    ),
                }
            )
            if not report["valid"]:
                report["error"] = "Snapshot envelope verification failed"
            # When DuckDB is attached, confirm public-metadata authority surface.
            if report["valid"] and self._shadow is not None:
                projection = self._shadow.get_wallet_projection(wallet_id)
                report["duckdb_projection_present"] = projection is not None
                report["duckdb_authority_mode"] = self._shadow.authority_mode.value
                if projection is None and self._shadow.authority_mode in {
                    AuthorityMode.DUAL,
                    AuthorityMode.DB_PRIMARY,
                }:
                    report["valid"] = False
                    report["error"] = "DuckDB authority projection missing for wallet"
            return report

        if not isinstance(payload, dict):
            report["format"] = "unknown"
            report["error"] = "Snapshot payload is not an object"
            return report
        report.update(
            {
                "format": "legacy",
                "computed_hash": self.snapshot_hash(payload),
                "valid": True,
            }
        )
        return report

    def verify_analytics_ledger(self) -> dict[str, Any]:
        path = self.analytics_ledger_path()
        report: dict[str, Any] = {
            "path": str(path),
            "exists": path.exists(),
            "valid": False,
        }
        if not path.exists():
            report["error"] = "Analytics ledger snapshot not found"
            return report
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            report["error"] = f"Invalid JSON: {exc.msg}"
            return report
        try:
            ledger = self._analytics_ledger_from_payload(payload)
        except Exception as exc:
            report["format"] = "envelope"
            report["error"] = str(exc)
            return report
        computed_hash = self.snapshot_hash(ledger)
        expected_hash = payload.get("snapshot_hash")
        report.update(
            {
                "format": "envelope",
                "snapshot_hash": expected_hash,
                "computed_hash": computed_hash,
                "authority_revision": int(payload.get("authority_revision") or 0),
                "authority_mode": payload.get("authority_mode"),
                "valid": (
                    payload.get("snapshot_type") == ANALYTICS_LEDGER_TYPE
                    and expected_hash == computed_hash
                ),
            }
        )
        if not report["valid"]:
            report["error"] = "Analytics ledger envelope verification failed"
        return report

    def _verify_authority_projection(
        self,
        service: DataWalletService,
        wallet_id: str,
        *,
        snapshot_payload: dict[str, Any] | None = None,
    ) -> None:
        """When DuckDB is dual/db-primary, ensure a projection exists (soft check)."""

        if self._shadow is None:
            return
        mode = self._shadow.authority_mode
        if mode not in {AuthorityMode.DUAL, AuthorityMode.DB_PRIMARY}:
            return
        projection = self._shadow.get_wallet_projection(wallet_id)
        if projection is not None:
            return
        # Projection may be absent after a cold load before first dual write;
        # re-project from the restored service so DuckDB authority is warm.
        try:
            snapshot = service.export_wallet_snapshot(wallet_id)
            self._shadow.shadow_wallet_snapshot(
                snapshot,
                operation_id=new_operation_id("repo-reload"),
                kind=MutationKind.REPOSITORY,
                action="repository/reload_authority",
            )
        except Exception:
            # Soft: load still succeeds from JSON dual surface.
            return

    def _shadow_wallet(
        self,
        snapshot: dict[str, Any],
        *,
        operation_id: str | None = None,
        authority_revision: int | None = None,
    ) -> MutationReceipt | None:
        if self._shadow is None:
            return None
        receipt = self._shadow.shadow_wallet_snapshot(
            snapshot,
            operation_id=operation_id or new_operation_id("repo-wallet"),
            kind=MutationKind.REPOSITORY,
            action="repository/wallet_snapshot",
        )
        # Record revision fence as a separate mutation envelope so concurrent
        # writers can observe the authoritative revision without opening the
        # redacted projection schema.
        if authority_revision is not None:
            wallet = snapshot.get("wallet") if isinstance(snapshot, dict) else None
            wallet_id = ""
            if isinstance(wallet, dict):
                wallet_id = str(wallet.get("wallet_id") or "")
            self._shadow.record_mutation(
                action="repository/authority_revision",
                resource=f"wallet://{wallet_id}/revision",
                wallet_id=wallet_id,
                kind=MutationKind.REPOSITORY,
                operation_id=f"{receipt.operation_id}:rev",
                projection_key=f"wallet-revision:{wallet_id}",
                projection={
                    "projection_type": "wallet_authority_revision_v1",
                    "wallet_id": wallet_id,
                    "authority_revision": authority_revision,
                    "snapshot_digest": receipt.projection_digest,
                    "mode": receipt.mode,
                },
            )
        self._last_mutation_receipts.append(receipt)
        return receipt

    def _shadow_analytics(
        self,
        ledger: dict[str, Any],
        *,
        operation_id: str | None = None,
        authority_revision: int | None = None,
    ) -> MutationReceipt | None:
        if self._shadow is None:
            return None
        receipt = self._shadow.shadow_analytics_ledger(
            ledger,
            operation_id=operation_id or new_operation_id("repo-analytics"),
            kind=MutationKind.ANALYTICS,
            action="repository/analytics_ledger",
        )
        if authority_revision is not None:
            self._shadow.record_mutation(
                action="repository/analytics_authority_revision",
                resource="wallet://analytics/revision",
                wallet_id="",
                kind=MutationKind.ANALYTICS,
                operation_id=f"{receipt.operation_id}:rev",
                projection_key="analytics-revision",
                projection={
                    "projection_type": "wallet_analytics_authority_revision_v1",
                    "authority_revision": authority_revision,
                    "ledger_digest": receipt.projection_digest,
                    "mode": receipt.mode,
                },
            )
        self._last_mutation_receipts.append(receipt)
        return receipt

    def _snapshot_from_payload(self, payload: dict[str, Any], wallet_id: str) -> dict[str, Any]:
        if not self._is_snapshot_envelope(payload):
            return payload
        snapshot = payload.get("snapshot")
        if not isinstance(snapshot, dict):
            raise ValueError("Snapshot envelope is missing a snapshot object")
        expected_hash = payload.get("snapshot_hash")
        computed_hash = self.snapshot_hash(snapshot)
        if payload.get("snapshot_type") != SNAPSHOT_TYPE:
            raise ValueError("Unsupported wallet snapshot type")
        if payload.get("wallet_id") != wallet_id:
            raise ValueError("Wallet snapshot id does not match requested wallet")
        if expected_hash != computed_hash:
            raise ValueError("Wallet snapshot hash verification failed")
        return snapshot

    def _analytics_ledger_from_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("Analytics ledger payload is not an object")
        ledger = payload.get("ledger")
        if not isinstance(ledger, dict):
            raise ValueError("Analytics ledger envelope is missing a ledger object")
        expected_hash = payload.get("snapshot_hash")
        computed_hash = self.snapshot_hash(ledger)
        if payload.get("snapshot_type") != ANALYTICS_LEDGER_TYPE:
            raise ValueError("Unsupported analytics ledger snapshot type")
        if expected_hash != computed_hash:
            raise ValueError("Analytics ledger snapshot hash verification failed")
        return ledger

    def _is_snapshot_envelope(self, payload: Any) -> bool:
        return isinstance(payload, dict) and (
            payload.get("snapshot_type") == SNAPSHOT_TYPE or "snapshot" in payload
        )
