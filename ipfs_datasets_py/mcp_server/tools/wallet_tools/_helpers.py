from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable

from ipfs_datasets_py.wallet import WalletService
from ipfs_datasets_py.wallet.storage import LocalEncryptedBlobStore


def default_wallet_dir() -> Path:
    return Path.home() / ".ipfs_datasets" / "wallet" / "manifests"


def default_blob_dir() -> Path:
    return Path.home() / ".ipfs_datasets" / "wallet" / "blobs"


def wallet_path(wallet_dir: Path, wallet_id: str) -> Path:
    return wallet_dir / f"{wallet_id}.json"


def key_from_optional_hex(value: str | None) -> bytes | None:
    if not value:
        return None
    raw = bytes.fromhex(value)
    if len(raw) != 32:
        raise ValueError("wallet key must decode to 32 bytes")
    return raw


def service(blob_dir: Path) -> WalletService:
    return WalletService(storage_backend=LocalEncryptedBlobStore(blob_dir))


def save(service_obj: WalletService, wallet_dir: Path, wallet_id: str) -> Path:
    wallet_dir.mkdir(parents=True, exist_ok=True)
    path = wallet_path(wallet_dir, wallet_id)
    path.write_text(
        json.dumps(service_obj.export_wallet_snapshot(wallet_id), sort_keys=True, indent=2),
        encoding="utf-8",
    )
    return path


def save_all(service_obj: WalletService, wallet_dir: Path, wallet_ids: Iterable[str]) -> None:
    for wallet_id in sorted(set(wallet_ids)):
        save(service_obj, wallet_dir, wallet_id)


def load(wallet_dir: Path, blob_dir: Path, wallet_id: str) -> WalletService:
    service_obj = service(blob_dir)
    snapshot = json.loads(wallet_path(wallet_dir, wallet_id).read_text(encoding="utf-8"))
    service_obj.import_wallet_snapshot(snapshot)
    return service_obj


def load_all(wallet_dir: Path, blob_dir: Path) -> WalletService:
    service_obj = service(blob_dir)
    if not wallet_dir.exists():
        return service_obj
    for path in sorted(wallet_dir.glob("wallet-*.json")):
        service_obj.import_wallet_snapshot(json.loads(path.read_text(encoding="utf-8")))
    return service_obj


def parse_fields(fields: Dict[str, Any] | None) -> Dict[str, Any]:
    return dict(fields or {})


def aggregate_result_summary(result: Any) -> Dict[str, Any]:
    return {
        "result_id": result.result_id,
        "template_id": result.template_id,
        "metric": result.metric,
        "released": result.released,
        "suppressed": result.suppressed,
        "count": result.count if result.exact_count_released else None,
        "noisy_count": result.noisy_count if result.released else None,
        "min_cohort_size": result.min_cohort_size,
        "epsilon": result.epsilon,
        "privacy_budget_key": result.privacy_budget_key,
        "privacy_budget_spent": result.privacy_budget_spent,
        "privacy_notes": list(result.privacy_notes),
    }

