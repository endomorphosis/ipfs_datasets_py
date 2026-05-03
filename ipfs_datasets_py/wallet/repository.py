"""Filesystem repository for canonical wallet snapshots."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from .exceptions import MissingRecordError
from .manifest import canonical_dumps
from .service import DataWalletService


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

    def save(self, service: DataWalletService, wallet_id: str) -> Path:
        manifest = service.export_wallet_snapshot(wallet_id)
        path = self.wallet_path(wallet_id)
        path.write_text(canonical_dumps(manifest) + "\n", encoding="utf-8")
        return path

    def load(self, service: DataWalletService, wallet_id: str) -> None:
        path = self.wallet_path(wallet_id)
        if not path.exists():
            raise MissingRecordError(f"Wallet snapshot not found: {wallet_id}")
        service.import_wallet_snapshot(json.loads(path.read_text(encoding="utf-8")))

    def list_wallet_ids(self) -> list[str]:
        return sorted(path.stem for path in self.root.glob("wallet-*.json"))

