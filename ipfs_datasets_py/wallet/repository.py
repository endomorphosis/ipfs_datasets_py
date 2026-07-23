"""Filesystem repository for canonical wallet snapshots."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .exceptions import MissingRecordError
from .crypto import sha256_hex
from .manifest import canonical_bytes, canonical_dumps
from .service import DataWalletService


SNAPSHOT_TYPE = "wallet_repository_snapshot_v1"
ANALYTICS_LEDGER_TYPE = "wallet_repository_analytics_ledger_v1"
ANALYTICS_LEDGER_FILENAME = "analytics-ledger.json"


class LocalWalletRepository:
    """Persist and restore `DataWalletService` state for one wallet.

    This repository stores wallet manifests and encrypted-blob references. It is
    intended for local development and CLI workflows. Encrypted payload bytes
    remain in the configured blob store.
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def wallet_path(self, wallet_id: str) -> Path:
        return self.root / f"{wallet_id}.json"

    def analytics_ledger_path(self) -> Path:
        return self.root / ANALYTICS_LEDGER_FILENAME

    def snapshot_hash(self, snapshot: dict[str, Any]) -> str:
        return sha256_hex(canonical_bytes(snapshot))

    def save(self, service: DataWalletService, wallet_id: str) -> Path:
        path = self._save_wallet_snapshot(service, wallet_id)
        self.save_analytics_ledger(service)
        return path

    def _save_wallet_snapshot(self, service: DataWalletService, wallet_id: str) -> Path:
        snapshot = service.export_wallet_snapshot(wallet_id)
        payload = {
            "snapshot_type": SNAPSHOT_TYPE,
            "wallet_id": wallet_id,
            "snapshot_hash": self.snapshot_hash(snapshot),
            "snapshot": snapshot,
        }
        path = self.wallet_path(wallet_id)
        tmp_path = path.with_name(f".{path.name}.tmp")
        tmp_path.write_text(canonical_dumps(payload) + "\n", encoding="utf-8")
        tmp_path.replace(path)
        return path

    def save_all(self, service: DataWalletService) -> list[Path]:
        paths = [self._save_wallet_snapshot(service, wallet_id) for wallet_id in sorted(service.wallets)]
        self.save_analytics_ledger(service)
        return paths

    def save_analytics_ledger(self, service: DataWalletService) -> Path:
        ledger = service.export_analytics_ledger()
        payload = {
            "snapshot_type": ANALYTICS_LEDGER_TYPE,
            "snapshot_hash": self.snapshot_hash(ledger),
            "ledger": ledger,
        }
        path = self.analytics_ledger_path()
        tmp_path = path.with_name(f".{path.name}.tmp")
        tmp_path.write_text(canonical_dumps(payload) + "\n", encoding="utf-8")
        tmp_path.replace(path)
        return path

    def load(self, service: DataWalletService, wallet_id: str) -> None:
        path = self.wallet_path(wallet_id)
        if not path.exists():
            raise MissingRecordError(f"Wallet snapshot not found: {wallet_id}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        service.import_wallet_snapshot(self._snapshot_from_payload(payload, wallet_id))
        self.load_analytics_ledger(service, required=False)

    def load_all(self, service: DataWalletService) -> list[str]:
        wallet_ids = self.list_wallet_ids()
        for wallet_id in wallet_ids:
            path = self.wallet_path(wallet_id)
            payload = json.loads(path.read_text(encoding="utf-8"))
            service.import_wallet_snapshot(self._snapshot_from_payload(payload, wallet_id))
        self.load_analytics_ledger(service, required=False)
        return wallet_ids

    def load_analytics_ledger(self, service: DataWalletService, *, required: bool = True) -> None:
        path = self.analytics_ledger_path()
        if not path.exists():
            if required:
                raise MissingRecordError("Analytics ledger snapshot not found")
            return
        payload = json.loads(path.read_text(encoding="utf-8"))
        service.import_analytics_ledger(self._analytics_ledger_from_payload(payload))

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
            report.update(
                {
                    "format": "envelope",
                    "snapshot_hash": expected_hash,
                    "computed_hash": computed_hash,
                    "valid": (
                        payload.get("snapshot_type") == SNAPSHOT_TYPE
                        and payload.get("wallet_id") == wallet_id
                        and expected_hash == computed_hash
                    ),
                }
            )
            if not report["valid"]:
                report["error"] = "Snapshot envelope verification failed"
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
                "valid": (
                    payload.get("snapshot_type") == ANALYTICS_LEDGER_TYPE
                    and expected_hash == computed_hash
                ),
            }
        )
        if not report["valid"]:
            report["error"] = "Analytics ledger envelope verification failed"
        return report

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
