"""DuckDB-authoritative wallet repository with JSON import/export only (DQK-076).

Runtime authority for mutable public metadata and restorable service envelopes
is the attached :class:`WalletDuckDBRepository` event port (``db-primary``).
Encrypted payload bytes remain in the configured content-addressed blob store
(never DuckDB or Quack).

Authority model:

* **db-primary** (default) — DuckDB is the sole runtime authority. JSON files
  are not written on save/load. Listing does not glob ``wallet-*.json``.
* **dual** / **shadow** — transitional dual-write paths retained for migration
  cutover tests (DQK-075); still dual-write JSON envelopes when enabled.
* **export-only** — reads from DuckDB; authority writes are rejected by the
  transition port (one-way export pipeline only).

:class:`LocalWalletRepository` is the **explicit** JSON import/export
compatibility surface. Implicit writes of ``wallet-*.json`` or
``analytics-ledger.json`` are blocked by a filesystem guard unless the call
holds an export permit issued by the explicit export methods.

Only separately approved aggregate analytics are exposed on the Quack
publication surface (see :meth:`DataWalletService.quack_publication_document`).
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

# Authority envelope keys in the DuckDB event port (not query publications).
WALLET_ENVELOPE_KEY_PREFIX = "wallet-envelope:"
ANALYTICS_ENVELOPE_KEY = "analytics-envelope"
WALLET_ID_INDEX_KEY = "wallet-id-index"

# Default post-DQK-076 mode: DuckDB is sole runtime authority.
DEFAULT_AUTHORITY_MODE: AuthorityMode = AuthorityMode.DB_PRIMARY

# Filenames / globs guarded against implicit writes.
_GUARDED_WALLET_GLOB = "wallet-*.json"
_GUARDED_ANALYTICS_NAME = ANALYTICS_LEDGER_FILENAME


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


class ImplicitJsonWriteError(DataWalletError):
    """Raised when an implicit wallet JSON or analytics-ledger write is blocked."""

    def __init__(self, message: str, *, path: str = "", kind: str = "") -> None:
        super().__init__(message)
        self.path = path
        self.kind = kind


class WalletFilesystemGuard:
    """Filesystem guard that blocks implicit snapshot / analytics-ledger writes.

    Explicit import/export methods obtain a short-lived permit via
    :meth:`permit_export` / :meth:`permit_import`. All other write attempts of
    guarded paths fail closed with :class:`ImplicitJsonWriteError`.
    """

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self._lock = threading.RLock()
        self._export_permits: int = 0
        self._import_permits: int = 0

    @contextmanager
    def permit_export(self) -> Iterator[None]:
        with self._lock:
            self._export_permits += 1
        try:
            yield
        finally:
            with self._lock:
                self._export_permits = max(0, self._export_permits - 1)

    @contextmanager
    def permit_import(self) -> Iterator[None]:
        with self._lock:
            self._import_permits += 1
        try:
            yield
        finally:
            with self._lock:
                self._import_permits = max(0, self._import_permits - 1)

    def assert_write_allowed(self, path: Path, *, kind: str) -> None:
        """Raise if *path* is a guarded JSON target without an active permit."""

        path = Path(path)
        if not self._is_guarded_path(path):
            return
        with self._lock:
            allowed = self._export_permits > 0 or self._import_permits > 0
        if allowed:
            return
        raise ImplicitJsonWriteError(
            f"implicit {kind} write blocked by filesystem guard: {path} "
            f"(use explicit export/import compatibility methods)",
            path=str(path),
            kind=kind,
        )

    def check_path_write(self, path: Path | str, *, kind: str = "json") -> None:
        """Public guard entry used by tests and callers before writing."""

        self.assert_write_allowed(Path(path), kind=kind)

    def _is_guarded_path(self, path: Path) -> bool:
        name = path.name
        if name == _GUARDED_ANALYTICS_NAME:
            return True
        if name.startswith("wallet-") and name.endswith(".json"):
            return True
        # Also guard bare ``{wallet_id}.json`` envelopes under the repository root.
        try:
            resolved_root = self.root.resolve()
            resolved_path = path.resolve()
        except OSError:
            resolved_root = self.root
            resolved_path = path
        if resolved_path.parent == resolved_root and name.endswith(".json"):
            if name == _GUARDED_ANALYTICS_NAME or name.startswith("wallet-"):
                return True
            # Authority snapshot files historically used ``{wallet_id}.json``.
            if name != _GUARDED_ANALYTICS_NAME and not name.startswith("."):
                return True
        return False


class LocalWalletRepository:
    """DuckDB-authoritative repository with explicit JSON import/export only.

    Runtime save/load/list paths use the attached DuckDB event port. Encrypted
    payload bytes remain in the configured blob store. JSON envelopes are
    produced only by :meth:`export_wallet_json` / :meth:`export_analytics_ledger_json`
    and consumed by the matching import methods.
    """

    def __init__(
        self,
        root: str | Path,
        *,
        shadow: WalletDuckDBRepository | bool | None = True,
        authority_mode: AuthorityMode | str | None = None,
        allow_legacy_json: bool | None = None,
    ) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._revisions: dict[str, int] = {}
        self._analytics_revision: int = 0
        self._last_mutation_receipts: list[MutationReceipt] = []
        self._wallet_ids: set[str] = set()
        self.filesystem_guard = WalletFilesystemGuard(self.root)
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
            if authority_mode is not None and self._shadow.authority_mode != mode:
                # Mode is owned by the shared process-local event port (API/CLI).
                pass
        # Legacy JSON dual-write only when explicitly allowed or in dual/shadow.
        if allow_legacy_json is None:
            if self._shadow is None:
                self._allow_legacy_json = True
            else:
                self._allow_legacy_json = self._shadow.authority_mode in {
                    AuthorityMode.LEGACY,
                    AuthorityMode.SHADOW,
                    AuthorityMode.DUAL,
                }
        else:
            self._allow_legacy_json = bool(allow_legacy_json)

    @property
    def shadow(self) -> WalletDuckDBRepository | None:
        return self._shadow

    @property
    def event_port(self) -> WalletDuckDBRepository | None:
        """Alias for the DuckDB event port (DQK-075 / DQK-076)."""

        return self._shadow

    @property
    def authority_mode(self) -> AuthorityMode | None:
        if self._shadow is None:
            return None
        return self._shadow.authority_mode

    @property
    def last_mutation_receipts(self) -> list[MutationReceipt]:
        return list(self._last_mutation_receipts)

    @property
    def json_writes_enabled(self) -> bool:
        """True when dual/shadow/legacy JSON dual-write is enabled."""

        return self._allow_legacy_json

    def wallet_path(self, wallet_id: str) -> Path:
        return self.root / f"{wallet_id}.json"

    def analytics_ledger_path(self) -> Path:
        return self.root / ANALYTICS_LEDGER_FILENAME

    def snapshot_hash(self, snapshot: dict[str, Any]) -> str:
        return _sha256_hex(canonical_bytes(snapshot))

    # ------------------------------------------------------------------
    # Filesystem guard public API
    # ------------------------------------------------------------------

    def assert_json_write_allowed(self, path: Path | str, *, kind: str = "snapshot") -> None:
        """Fail closed if *path* would be an implicit guarded JSON write."""

        self.filesystem_guard.check_path_write(Path(path), kind=kind)

    # ------------------------------------------------------------------
    # Revision helpers
    # ------------------------------------------------------------------

    def _envelope_key(self, wallet_id: str) -> str:
        return f"{WALLET_ENVELOPE_KEY_PREFIX}{wallet_id}"

    def _read_revision_from_authority(self, wallet_id: str) -> int:
        if self._shadow is None:
            return self._read_revision_from_disk(wallet_id)
        envelope = self._shadow.authority_port.read(self._envelope_key(wallet_id))
        if envelope is not None:
            return int(envelope.get("authority_revision") or 0)
        rev_projection = self._shadow.get_projection(f"wallet-revision:{wallet_id}")
        if rev_projection is not None:
            return int(rev_projection.get("authority_revision") or 0)
        if self._allow_legacy_json:
            return self._read_revision_from_disk(wallet_id)
        return 0

    def _read_revision_from_disk(self, wallet_id: str) -> int:
        path = self.wallet_path(wallet_id)
        if not path.exists():
            return 0
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return 0
        return int(payload.get("authority_revision") or 0)

    def _read_analytics_revision_from_authority(self) -> int:
        if self._shadow is None:
            return self._read_analytics_revision_from_disk()
        envelope = self._shadow.authority_port.read(ANALYTICS_ENVELOPE_KEY)
        if envelope is None:
            return self._read_analytics_revision_from_disk() if self._allow_legacy_json else 0
        return int(envelope.get("authority_revision") or 0)

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
            rev = self._read_revision_from_authority(wallet_id)
            self._revisions[wallet_id] = rev
            return rev

    def current_analytics_revision(self) -> int:
        with self._lock:
            rev = self._read_analytics_revision_from_authority()
            self._analytics_revision = rev
            return rev

    @contextmanager
    def _exclusive_lock(self, name: str) -> Iterator[None]:
        """Cross-instance exclusive lock for CAS-gated dual-mode writes."""

        lock_path = self.root / f".{name}.authority.lock"
        self.root.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o644)
        try:
            try:
                import fcntl

                fcntl.flock(fd, fcntl.LOCK_EX)
            except (ImportError, OSError):
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
        """Promote the attached event port from dual → db-primary."""

        if self._shadow is None:
            raise DataWalletError("cannot promote without a DuckDB event port")
        port = self._shadow.authority_port
        if port.mode is AuthorityMode.DB_PRIMARY:
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
        """Ensure DuckDB is authoritative for *wallet_id* (dual → db-primary)."""

        if self._shadow is None:
            return None
        mode = self._shadow.authority_mode
        if mode is AuthorityMode.DB_PRIMARY:
            return None
        if mode is AuthorityMode.EXPORT_ONLY:
            return None
        if mode is AuthorityMode.DUAL:
            receipt = self.promote_to_db_primary(
                parity_key=f"wallet:{wallet_id}",
                decision_id=decision_id or f"cutover:{wallet_id}",
            )
            self._allow_legacy_json = False
            return receipt
        if mode is AuthorityMode.SHADOW:
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
            receipt = self.promote_to_db_primary(
                parity_key=f"wallet:{wallet_id}",
                decision_id=decision_id or f"cutover:{wallet_id}",
            )
            self._allow_legacy_json = False
            return receipt
        return None

    # ------------------------------------------------------------------
    # Runtime authority (DuckDB-primary)
    # ------------------------------------------------------------------

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
        if expected_revision is None:
            if hasattr(service, "authority_revision"):
                expected_revision = int(service.authority_revision(wallet_id))
            else:
                expected_revision = self._read_revision_from_authority(wallet_id)

        with self._exclusive_lock(wallet_id):
            current = self._read_revision_from_authority(wallet_id)
            if current == 0:
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

            # Always project public metadata into DuckDB when attached.
            self._shadow_wallet(
                snapshot,
                operation_id=operation_id,
                authority_revision=new_revision,
            )
            # Persist restorable envelope in DuckDB authority (not Quack).
            self._put_authority_envelope(wallet_id, payload, operation_id=operation_id)
            self._wallet_ids.add(wallet_id)
            self._update_wallet_id_index()

            # Legacy JSON dual-write only when transitional mode allows it.
            if self._allow_legacy_json:
                self._write_json_envelope(path, payload, kind="wallet_snapshot")
            else:
                # Guard: any attempt to materialize the JSON path without a permit
                # is rejected (e2e asserts this catches implicit writes).
                try:
                    self.filesystem_guard.assert_write_allowed(path, kind="wallet_snapshot")
                except ImplicitJsonWriteError:
                    # Expected in db-primary: do not write JSON.
                    pass

            self._revisions[wallet_id] = new_revision
            if hasattr(service, "note_authority_revision"):
                service.note_authority_revision(wallet_id, new_revision)
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
            expected_revision = self._read_analytics_revision_from_authority()

        with self._exclusive_lock("analytics-ledger"):
            current = self._read_analytics_revision_from_authority()
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
            self._shadow_analytics(
                ledger,
                operation_id=operation_id,
                authority_revision=new_revision,
            )
            self._put_analytics_envelope(payload, operation_id=operation_id)
            if self._allow_legacy_json:
                self._write_json_envelope(path, payload, kind="analytics_ledger")
            else:
                try:
                    self.filesystem_guard.assert_write_allowed(path, kind="analytics_ledger")
                except ImplicitJsonWriteError:
                    pass
            self._analytics_revision = new_revision
            return path

    def load(self, service: DataWalletService, wallet_id: str) -> None:
        payload = self._load_wallet_envelope(wallet_id)
        if payload is None:
            raise MissingRecordError(f"Wallet snapshot not found: {wallet_id}")
        revision = int(payload.get("authority_revision") or 0)
        service.import_wallet_snapshot(self._snapshot_from_payload(payload, wallet_id))
        if hasattr(service, "note_authority_revision"):
            service.note_authority_revision(wallet_id, revision)
        with self._lock:
            self._revisions[wallet_id] = revision
            self._wallet_ids.add(wallet_id)
        self.load_analytics_ledger(service, required=False)
        self._verify_authority_projection(service, wallet_id, snapshot_payload=payload)

    def load_all(self, service: DataWalletService) -> list[str]:
        wallet_ids = self.list_wallet_ids()
        for wallet_id in wallet_ids:
            payload = self._load_wallet_envelope(wallet_id)
            if payload is None:
                continue
            revision = int(payload.get("authority_revision") or 0)
            service.import_wallet_snapshot(self._snapshot_from_payload(payload, wallet_id))
            if hasattr(service, "note_authority_revision"):
                service.note_authority_revision(wallet_id, revision)
            with self._lock:
                self._revisions[wallet_id] = revision
                self._wallet_ids.add(wallet_id)
            self._verify_authority_projection(service, wallet_id, snapshot_payload=payload)
        self.load_analytics_ledger(service, required=False)
        return wallet_ids

    def load_analytics_ledger(self, service: DataWalletService, *, required: bool = True) -> None:
        payload = self._load_analytics_envelope()
        if payload is None:
            if required:
                raise MissingRecordError("Analytics ledger snapshot not found")
            return
        revision = int(payload.get("authority_revision") or 0)
        service.import_analytics_ledger(self._analytics_ledger_from_payload(payload))
        with self._lock:
            self._analytics_revision = revision

    def list_wallet_ids(self) -> list[str]:
        """List wallet IDs from DuckDB authority (no JSON glob discovery)."""

        ids: set[str] = set(self._wallet_ids)
        if self._shadow is not None:
            # Index envelope maintained by this repository.
            index = self._shadow.authority_port.read(WALLET_ID_INDEX_KEY)
            if isinstance(index, dict):
                for item in index.get("wallet_ids") or []:
                    if isinstance(item, str) and item:
                        ids.add(item)
            # Mutation receipts that projected wallet: keys.
            for receipt in self._shadow.list_mutation_receipts():
                if receipt.wallet_id:
                    ids.add(receipt.wallet_id)
                key = receipt.projection_key or ""
                if key.startswith("wallet:") and not key.startswith("wallet-envelope:"):
                    wid = key.split(":", 1)[1]
                    if wid and wid not in {"revision"}:
                        # wallet:{id} or wallet-revision handled separately
                        if not key.startswith("wallet-revision:"):
                            ids.add(wid)
            # Envelope keys via known set only (backend has no list API).
        if self._allow_legacy_json:
            # Compatibility: discover dual-written JSON envelopes when enabled.
            for path in self.root.glob("wallet-*.json"):
                ids.add(path.stem)
            for path in self.root.glob("*.json"):
                if path.name == ANALYTICS_LEDGER_FILENAME:
                    continue
                if path.name.startswith("."):
                    continue
                stem = path.stem
                if stem.startswith("wallet-") or stem:
                    # Only add wallet-prefixed or previously dual-written ids.
                    if stem.startswith("wallet-"):
                        ids.add(stem)
        return sorted(ids)

    def verify(self, wallet_id: str) -> dict[str, Any]:
        payload = self._load_wallet_envelope(wallet_id)
        path = self.wallet_path(wallet_id)
        report: dict[str, Any] = {
            "wallet_id": wallet_id,
            "path": str(path),
            "exists": payload is not None or path.exists(),
            "valid": False,
            "authority": (
                self._shadow.authority_mode.value if self._shadow is not None else "legacy"
            ),
        }
        if payload is None:
            report["error"] = "Wallet snapshot not found"
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
            if report["valid"] and self._shadow is not None:
                projection = self._shadow.get_wallet_projection(wallet_id)
                report["duckdb_projection_present"] = projection is not None
                report["duckdb_authority_mode"] = self._shadow.authority_mode.value
                if projection is None and self._shadow.authority_mode in {
                    AuthorityMode.DUAL,
                    AuthorityMode.DB_PRIMARY,
                    AuthorityMode.EXPORT_ONLY,
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
        payload = self._load_analytics_envelope()
        report: dict[str, Any] = {
            "path": str(path),
            "exists": payload is not None or path.exists(),
            "valid": False,
        }
        if payload is None:
            report["error"] = "Analytics ledger snapshot not found"
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

    # ------------------------------------------------------------------
    # Explicit JSON import / export compatibility (only JSON path)
    # ------------------------------------------------------------------

    def export_wallet_json(
        self,
        service: DataWalletService,
        wallet_id: str,
        *,
        path: Path | str | None = None,
    ) -> Path:
        """Explicit compatibility export of one wallet envelope to JSON."""

        target = Path(path) if path is not None else self.wallet_path(wallet_id)
        snapshot = service.export_wallet_snapshot(wallet_id)
        revision = self.current_revision(wallet_id) or service.authority_revision(wallet_id) or 1
        payload = {
            "snapshot_type": SNAPSHOT_TYPE,
            "wallet_id": wallet_id,
            "snapshot_hash": self.snapshot_hash(snapshot),
            "authority_revision": revision,
            "authority_mode": (
                self._shadow.authority_mode.value if self._shadow is not None else "legacy"
            ),
            "snapshot": snapshot,
        }
        with self.filesystem_guard.permit_export():
            self._write_json_envelope(target, payload, kind="wallet_snapshot")
        return target

    def import_wallet_json(
        self,
        service: DataWalletService,
        wallet_id: str,
        *,
        path: Path | str | None = None,
    ) -> None:
        """Explicit compatibility import of one wallet envelope from JSON."""

        target = Path(path) if path is not None else self.wallet_path(wallet_id)
        if not target.exists():
            raise MissingRecordError(f"Wallet snapshot not found: {wallet_id}")
        with self.filesystem_guard.permit_import():
            payload = json.loads(target.read_text(encoding="utf-8"))
        revision = int(payload.get("authority_revision") or 0)
        service.import_wallet_snapshot(self._snapshot_from_payload(payload, wallet_id))
        if hasattr(service, "note_authority_revision"):
            service.note_authority_revision(wallet_id, revision)
        # Seed DuckDB authority from the imported envelope.
        if self._shadow is not None:
            snapshot = self._snapshot_from_payload(payload, wallet_id)
            self._shadow_wallet(
                snapshot,
                operation_id=new_operation_id("import-json"),
                authority_revision=revision or 1,
            )
            self._put_authority_envelope(
                wallet_id,
                {
                    "snapshot_type": SNAPSHOT_TYPE,
                    "wallet_id": wallet_id,
                    "snapshot_hash": self.snapshot_hash(snapshot),
                    "authority_revision": revision or 1,
                    "authority_mode": self._shadow.authority_mode.value,
                    "snapshot": snapshot,
                },
                operation_id=new_operation_id("import-json-env"),
            )
            self._wallet_ids.add(wallet_id)
            self._update_wallet_id_index()

    def export_analytics_ledger_json(
        self,
        service: DataWalletService,
        *,
        path: Path | str | None = None,
    ) -> Path:
        """Explicit compatibility export of the analytics ledger to JSON."""

        target = Path(path) if path is not None else self.analytics_ledger_path()
        ledger = service.export_analytics_ledger()
        revision = self.current_analytics_revision() or 1
        payload = {
            "snapshot_type": ANALYTICS_LEDGER_TYPE,
            "snapshot_hash": self.snapshot_hash(ledger),
            "authority_revision": revision,
            "authority_mode": (
                self._shadow.authority_mode.value if self._shadow is not None else "legacy"
            ),
            "ledger": ledger,
        }
        with self.filesystem_guard.permit_export():
            self._write_json_envelope(target, payload, kind="analytics_ledger")
        return target

    def import_analytics_ledger_json(
        self,
        service: DataWalletService,
        *,
        path: Path | str | None = None,
    ) -> None:
        """Explicit compatibility import of the analytics ledger from JSON."""

        target = Path(path) if path is not None else self.analytics_ledger_path()
        if not target.exists():
            raise MissingRecordError("Analytics ledger snapshot not found")
        with self.filesystem_guard.permit_import():
            payload = json.loads(target.read_text(encoding="utf-8"))
        revision = int(payload.get("authority_revision") or 0)
        service.import_analytics_ledger(self._analytics_ledger_from_payload(payload))
        if self._shadow is not None:
            ledger = self._analytics_ledger_from_payload(payload)
            self._shadow_analytics(
                ledger,
                operation_id=new_operation_id("import-analytics-json"),
                authority_revision=revision or 1,
            )
            self._put_analytics_envelope(
                {
                    "snapshot_type": ANALYTICS_LEDGER_TYPE,
                    "snapshot_hash": self.snapshot_hash(ledger),
                    "authority_revision": revision or 1,
                    "authority_mode": self._shadow.authority_mode.value,
                    "ledger": ledger,
                },
                operation_id=new_operation_id("import-analytics-env"),
            )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _write_json_envelope(
        self,
        path: Path,
        payload: dict[str, Any],
        *,
        kind: str,
    ) -> None:
        self.filesystem_guard.assert_write_allowed(path, kind=kind)
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        tmp_path.write_text(canonical_dumps(payload) + "\n", encoding="utf-8")
        tmp_path.replace(path)

    def _put_authority_envelope(
        self,
        wallet_id: str,
        payload: dict[str, Any],
        *,
        operation_id: str | None = None,
    ) -> None:
        if self._shadow is None:
            return
        # Full restorable envelope lives in the authority plane only (not
        # exposed via query_publications, which only indexes mutation receipts).
        op_id = operation_id or new_operation_id("wallet-envelope")
        try:
            self._shadow.authority_port.write(
                self._envelope_key(wallet_id),
                payload,
                operation_id=f"{op_id}:envelope",
            )
        except Exception:
            # Fail soft when mode rejects writes (export-only); dual/db-primary
            # should succeed. Redacted projection may still be present.
            return

    def _put_analytics_envelope(
        self,
        payload: dict[str, Any],
        *,
        operation_id: str | None = None,
    ) -> None:
        if self._shadow is None:
            return
        op_id = operation_id or new_operation_id("analytics-envelope")
        try:
            self._shadow.authority_port.write(
                ANALYTICS_ENVELOPE_KEY,
                payload,
                operation_id=f"{op_id}:envelope",
            )
        except Exception:
            return

    def _update_wallet_id_index(self) -> None:
        if self._shadow is None:
            return
        try:
            self._shadow.authority_port.write(
                WALLET_ID_INDEX_KEY,
                {
                    "index_type": "wallet_id_index_v1",
                    "wallet_ids": sorted(self._wallet_ids),
                },
                operation_id=new_operation_id("wallet-id-index"),
            )
        except Exception:
            return

    def _load_wallet_envelope(self, wallet_id: str) -> dict[str, Any] | None:
        if self._shadow is not None:
            envelope = self._shadow.authority_port.read(self._envelope_key(wallet_id))
            if envelope is not None:
                return dict(envelope)
        # Compatibility: read dual-written JSON only when legacy JSON is enabled
        # or an explicit import path left a file on disk.
        path = self.wallet_path(wallet_id)
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return None
        return None

    def _load_analytics_envelope(self) -> dict[str, Any] | None:
        if self._shadow is not None:
            envelope = self._shadow.authority_port.read(ANALYTICS_ENVELOPE_KEY)
            if envelope is not None:
                return dict(envelope)
        path = self.analytics_ledger_path()
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return None
        return None

    def _verify_authority_projection(
        self,
        service: DataWalletService,
        wallet_id: str,
        *,
        snapshot_payload: dict[str, Any] | None = None,
    ) -> None:
        if self._shadow is None:
            return
        mode = self._shadow.authority_mode
        if mode not in {
            AuthorityMode.DUAL,
            AuthorityMode.DB_PRIMARY,
            AuthorityMode.EXPORT_ONLY,
        }:
            return
        projection = self._shadow.get_wallet_projection(wallet_id)
        if projection is not None:
            return
        try:
            snapshot = service.export_wallet_snapshot(wallet_id)
            self._shadow.shadow_wallet_snapshot(
                snapshot,
                operation_id=new_operation_id("repo-reload"),
                kind=MutationKind.REPOSITORY,
                action="repository/reload_authority",
            )
        except Exception:
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


__all__ = [
    "ANALYTICS_LEDGER_FILENAME",
    "ANALYTICS_LEDGER_TYPE",
    "DEFAULT_AUTHORITY_MODE",
    "ImplicitJsonWriteError",
    "LocalWalletRepository",
    "SNAPSHOT_TYPE",
    "StaleRevisionError",
    "WalletFilesystemGuard",
]
