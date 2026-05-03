"""Encrypted byte storage adapters for the data wallet."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional, Protocol, runtime_checkable

from .crypto import sha256_hex
from .models import StorageRef


@runtime_checkable
class EncryptedBlobStore(Protocol):
    """Minimal storage contract used by the wallet service."""

    def put(self, data: bytes) -> StorageRef: ...

    def get(self, ref: StorageRef) -> bytes: ...


class LocalEncryptedBlobStore:
    """Content-addressed local encrypted blob store.

    The store is suitable for tests, local development, and a local encrypted
    cache. Production replication adapters can mirror the same encrypted bytes
    to IPFS, S3, or Filecoin.
    """

    def __init__(self, root: Optional[str | Path] = None) -> None:
        self.root = Path(root) if root is not None else None
        self._memory: Dict[str, bytes] = {}
        if self.root is not None:
            self.root.mkdir(parents=True, exist_ok=True)

    def put(self, data: bytes) -> StorageRef:
        digest = sha256_hex(data)
        if self.root is None:
            uri = f"memory://{digest}"
            self._memory[uri] = data
            storage_type = "memory"
        else:
            path = self.root / f"{digest}.bin"
            path.write_bytes(data)
            uri = f"local://{path}"
            storage_type = "local"
        return StorageRef(uri=uri, storage_type=storage_type, size_bytes=len(data), sha256=digest)

    def get(self, ref: StorageRef) -> bytes:
        if ref.uri.startswith("memory://"):
            return self._memory[ref.uri]
        if ref.uri.startswith("local://"):
            return Path(ref.uri[len("local://") :]).read_bytes()
        raise ValueError(f"Unsupported storage URI: {ref.uri}")


class IPFSEncryptedBlobStore:
    """Encrypted blob store backed by an `ipfs_backend_router` backend.

    The wallet only sends encrypted bytes to IPFS. Plaintext encryption happens
    before this adapter is called.
    """

    def __init__(self, backend: object | None = None, *, pin: bool = True) -> None:
        if backend is None:
            from ipfs_datasets_py.ipfs_backend_router import get_ipfs_backend

            backend = get_ipfs_backend()
        self.backend = backend
        self.pin = pin

    def put(self, data: bytes) -> StorageRef:
        cid = self.backend.add_bytes(data, pin=self.pin)  # type: ignore[attr-defined]
        return StorageRef(
            uri=f"ipfs://{cid}",
            storage_type="ipfs",
            size_bytes=len(data),
            sha256=sha256_hex(data),
        )

    def get(self, ref: StorageRef) -> bytes:
        if not ref.uri.startswith("ipfs://"):
            raise ValueError(f"Unsupported IPFS storage URI: {ref.uri}")
        cid = ref.uri[len("ipfs://") :]
        data = self.backend.cat(cid)  # type: ignore[attr-defined]
        if sha256_hex(data) != ref.sha256:
            raise ValueError(f"IPFS payload hash mismatch for {cid}")
        return data
