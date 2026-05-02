"""Storage adapters for encrypted wallet payloads."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional, Protocol

from .crypto import sha256_hex
from .exceptions import StorageError
from .models import StorageReceipt


class WalletStorageAdapter(Protocol):
    provider: str

    def put(self, data: bytes) -> StorageReceipt: ...

    def get(self, ref: str) -> bytes: ...


class MemoryStorageAdapter:
    """In-memory encrypted blob store for tests and ephemeral workflows."""

    provider = "memory"

    def __init__(self) -> None:
        self._objects: Dict[str, bytes] = {}

    def put(self, data: bytes) -> StorageReceipt:
        digest = sha256_hex(data)
        ref = f"memory://{digest}"
        self._objects[ref] = data
        return StorageReceipt(provider=self.provider, ref=ref, size_bytes=len(data))

    def get(self, ref: str) -> bytes:
        try:
            return self._objects[ref]
        except KeyError as exc:
            raise StorageError(f"memory object not found: {ref}") from exc


class LocalFileStorageAdapter:
    """Filesystem-backed encrypted blob store."""

    provider = "local"

    def __init__(self, base_path: str | Path) -> None:
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)

    def put(self, data: bytes) -> StorageReceipt:
        digest = sha256_hex(data)
        path = self.base_path / f"{digest}.bin"
        path.write_bytes(data)
        return StorageReceipt(
            provider=self.provider,
            ref=f"local://{path}",
            size_bytes=len(data),
            metadata={"sha256": digest},
        )

    def get(self, ref: str) -> bytes:
        if not ref.startswith("local://"):
            raise StorageError(f"invalid local storage ref: {ref}")
        path = Path(ref.removeprefix("local://"))
        if not path.exists():
            raise StorageError(f"local object not found: {path}")
        return path.read_bytes()


class IPFSStorageAdapter:
    """IPFS encrypted blob adapter using `ipfs_backend_router` or an injected backend."""

    provider = "ipfs"

    def __init__(self, backend: Optional[object] = None, *, pin: bool = True) -> None:
        self.backend = backend
        self.pin = pin

    def _backend(self) -> object:
        if self.backend is not None:
            return self.backend
        from ipfs_datasets_py import ipfs_backend_router

        return ipfs_backend_router.get_ipfs_backend()

    def put(self, data: bytes) -> StorageReceipt:
        backend = self._backend()
        try:
            cid = backend.add_bytes(data, pin=self.pin)
        except Exception as exc:
            raise StorageError(f"failed to add encrypted payload to IPFS: {exc}") from exc
        return StorageReceipt(
            provider=self.provider,
            ref=f"ipfs://{cid}",
            size_bytes=len(data),
            metadata={"cid": cid, "pin": self.pin},
        )

    def get(self, ref: str) -> bytes:
        if not ref.startswith("ipfs://"):
            raise StorageError(f"invalid IPFS storage ref: {ref}")
        cid = ref.removeprefix("ipfs://")
        backend = self._backend()
        try:
            return backend.cat(cid)
        except Exception as exc:
            raise StorageError(f"failed to retrieve encrypted payload from IPFS: {exc}") from exc

