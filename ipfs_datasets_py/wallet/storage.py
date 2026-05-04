"""Encrypted byte storage adapters for the data wallet."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional, Protocol, runtime_checkable
from urllib.parse import quote, unquote, urlparse

from .crypto import sha256_hex
from .models import StorageRef, StorageReplicaStatus


@runtime_checkable
class EncryptedBlobStore(Protocol):
    """Minimal storage contract used by the wallet service."""

    def put(self, data: bytes) -> StorageRef: ...

    def get(self, ref: StorageRef) -> bytes: ...


@dataclass(frozen=True)
class WalletStorageBackendConfig:
    """Config for one encrypted wallet storage backend."""

    storage_type: str = "memory"
    root: str | Path | None = None
    bucket: str | None = None
    prefix: str = "wallet/blobs"
    pin: bool = True

    @classmethod
    def from_config(cls, config: str | Mapping[str, Any] | "WalletStorageBackendConfig" | None) -> "WalletStorageBackendConfig":
        if config is None:
            return cls()
        if isinstance(config, cls):
            return config
        if isinstance(config, str):
            return cls(storage_type=config)
        storage_type = str(config.get("type") or config.get("storage_type") or config.get("provider") or "memory")
        return cls(
            storage_type=storage_type,
            root=config.get("root") or config.get("path"),
            bucket=config.get("bucket"),
            prefix=str(config.get("prefix") or "wallet/blobs"),
            pin=bool(config.get("pin", True)),
        )


@dataclass(frozen=True)
class WalletStorageConfig:
    """Config for primary encrypted storage plus optional mirror replicas."""

    primary: WalletStorageBackendConfig = field(default_factory=WalletStorageBackendConfig)
    mirrors: list[WalletStorageBackendConfig] = field(default_factory=list)

    @classmethod
    def from_config(cls, config: str | Mapping[str, Any] | "WalletStorageConfig" | None) -> "WalletStorageConfig":
        if config is None:
            return cls()
        if isinstance(config, cls):
            return config
        if isinstance(config, str):
            return cls(primary=WalletStorageBackendConfig.from_config(config))
        if "primary" in config or "mirrors" in config:
            return cls(
                primary=WalletStorageBackendConfig.from_config(config.get("primary")),
                mirrors=[
                    WalletStorageBackendConfig.from_config(mirror)
                    for mirror in config.get("mirrors", [])
                ],
            )
        return cls(primary=WalletStorageBackendConfig.from_config(config))


def create_encrypted_blob_store(
    config: str | Mapping[str, Any] | WalletStorageConfig | None = None,
    *,
    ipfs_backend: object | None = None,
    s3_client: object | None = None,
    filecoin_backend: object | None = None,
    backends: Mapping[str, object] | None = None,
) -> EncryptedBlobStore:
    """Build an encrypted blob store from app configuration.

    Examples:
        ``create_encrypted_blob_store()``
        ``create_encrypted_blob_store({"type": "local", "root": "/data/wallet"})``
        ``create_encrypted_blob_store({"primary": "memory", "mirrors": [{"type": "s3", "bucket": "b"}]}, s3_client=client)``
    """

    storage_config = WalletStorageConfig.from_config(config)
    backend_map = dict(backends or {})
    primary = _create_backend_store(
        storage_config.primary,
        ipfs_backend=ipfs_backend or backend_map.get("ipfs"),
        s3_client=s3_client or backend_map.get("s3"),
        filecoin_backend=filecoin_backend or backend_map.get("filecoin"),
    )
    mirrors = [
        _create_backend_store(
            mirror,
            ipfs_backend=ipfs_backend or backend_map.get("ipfs"),
            s3_client=s3_client or backend_map.get("s3"),
            filecoin_backend=filecoin_backend or backend_map.get("filecoin"),
        )
        for mirror in storage_config.mirrors
    ]
    return ReplicatedEncryptedBlobStore(primary, mirrors) if mirrors else primary


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


class S3EncryptedBlobStore:
    """Encrypted blob store backed by an S3-compatible client.

    The wallet passes already-encrypted bytes to this adapter. The client is a
    boto3-style object with `put_object` and `get_object` methods.
    """

    def __init__(self, client: object, *, bucket: str, prefix: str = "wallet/blobs") -> None:
        self.client = client
        self.bucket = bucket
        self.prefix = prefix.strip("/")

    def put(self, data: bytes) -> StorageRef:
        digest = sha256_hex(data)
        key = f"{self.prefix}/{digest}.bin" if self.prefix else f"{digest}.bin"
        self.client.put_object(  # type: ignore[attr-defined]
            Bucket=self.bucket,
            Key=key,
            Body=data,
            Metadata={"sha256": digest, "encrypted": "true"},
        )
        return StorageRef(
            uri=f"s3://{self.bucket}/{quote(key)}",
            storage_type="s3",
            size_bytes=len(data),
            sha256=digest,
        )

    def get(self, ref: StorageRef) -> bytes:
        parsed = urlparse(ref.uri)
        if parsed.scheme != "s3":
            raise ValueError(f"Unsupported S3 storage URI: {ref.uri}")
        bucket = parsed.netloc
        key = unquote(parsed.path.lstrip("/"))
        response = self.client.get_object(Bucket=bucket, Key=key)  # type: ignore[attr-defined]
        body = response["Body"]
        data = body.read() if hasattr(body, "read") else body
        if sha256_hex(data) != ref.sha256:
            raise ValueError(f"S3 payload hash mismatch for {ref.uri}")
        return data


class FilecoinEncryptedBlobStore:
    """Encrypted blob store backed by a Filecoin-capable storage backend.

    This adapter intentionally keeps the backend contract small for the first
    wallet slice. A backend may implement `store_bytes(data, sha256=...)` and
    `retrieve_bytes(locator)`, or simpler `put(data)` and `get(locator)` calls.
    The wallet still stores and verifies only encrypted bytes.
    """

    def __init__(self, backend: object) -> None:
        self.backend = backend

    def put(self, data: bytes) -> StorageRef:
        digest = sha256_hex(data)
        if hasattr(self.backend, "store_bytes"):
            locator = self.backend.store_bytes(data, sha256=digest)  # type: ignore[attr-defined]
        elif hasattr(self.backend, "put"):
            locator = self.backend.put(data)  # type: ignore[attr-defined]
        else:
            raise TypeError("Filecoin backend must implement store_bytes or put")
        locator_text = str(locator)
        uri = locator_text if locator_text.startswith("filecoin://") else f"filecoin://{locator_text}"
        return StorageRef(uri=uri, storage_type="filecoin", size_bytes=len(data), sha256=digest)

    def get(self, ref: StorageRef) -> bytes:
        if not ref.uri.startswith("filecoin://"):
            raise ValueError(f"Unsupported Filecoin storage URI: {ref.uri}")
        locator = ref.uri.removeprefix("filecoin://")
        if hasattr(self.backend, "retrieve_bytes"):
            data = self.backend.retrieve_bytes(locator)  # type: ignore[attr-defined]
        elif hasattr(self.backend, "get"):
            data = self.backend.get(locator)  # type: ignore[attr-defined]
        else:
            raise TypeError("Filecoin backend must implement retrieve_bytes or get")
        if sha256_hex(data) != ref.sha256:
            raise ValueError(f"Filecoin payload hash mismatch for {ref.uri}")
        return data


class ReplicatedEncryptedBlobStore:
    """Write encrypted blobs to a primary store and optional mirror stores."""

    def __init__(self, primary: EncryptedBlobStore, mirrors: Optional[Iterable[EncryptedBlobStore]] = None) -> None:
        self.primary = primary
        self.mirrors = list(mirrors or [])

    def put(self, data: bytes) -> StorageRef:
        primary_ref = self.primary.put(data)
        mirror_refs = [mirror.put(data) for mirror in self.mirrors]
        primary_ref.mirrors.extend(mirror_refs)
        return primary_ref

    def get(self, ref: StorageRef) -> bytes:
        errors: list[Exception] = []
        for candidate in [ref, *ref.mirrors]:
            store = self._store_for_ref(candidate)
            if store is None:
                continue
            try:
                return store.get(candidate)
            except Exception as exc:  # pragma: no cover - exercised by fallback tests
                errors.append(exc)
        if errors:
            raise errors[-1]
        raise ValueError(f"No configured store can read {ref.uri}")

    def check_ref(self, ref: StorageRef) -> list[StorageReplicaStatus]:
        """Verify every known replica for this ref without decrypting bytes."""

        return [
            self._check_candidate(role, candidate)
            for role, candidate in self._known_refs(ref)
        ]

    def repair_ref(self, ref: StorageRef) -> list[StorageReplicaStatus]:
        """Repair invalid or missing replicas from any valid encrypted source."""

        data = self.get(ref)
        statuses: list[StorageReplicaStatus] = []

        primary_status = self._check_candidate("primary", ref)
        if primary_status.ok:
            statuses.append(primary_status)
        else:
            primary_ref = self.primary.put(data)
            ref.uri = primary_ref.uri
            ref.storage_type = primary_ref.storage_type
            ref.size_bytes = primary_ref.size_bytes
            ref.sha256 = primary_ref.sha256
            ref.created_at = primary_ref.created_at
            statuses.append(
                StorageReplicaStatus(
                    uri=ref.uri,
                    storage_type=ref.storage_type,
                    role="primary",
                    ok=True,
                    size_bytes=ref.size_bytes,
                    sha256=ref.sha256,
                    repaired=True,
                )
            )

        repaired_mirrors: list[StorageRef] = []
        for mirror_store in self.mirrors:
            existing = next((mirror for mirror in ref.mirrors if _store_matches_ref(mirror_store, mirror)), None)
            if existing is None:
                mirror_ref = mirror_store.put(data)
                mirror_ref.mirrors = []
                repaired_mirrors.append(mirror_ref)
                statuses.append(_status_from_ref("mirror", mirror_ref, repaired=True))
                continue

            status = self._check_candidate("mirror", existing)
            if status.ok:
                repaired_mirrors.append(existing)
                statuses.append(status)
                continue

            mirror_ref = mirror_store.put(data)
            mirror_ref.mirrors = []
            repaired_mirrors.append(mirror_ref)
            statuses.append(_status_from_ref("mirror", mirror_ref, repaired=True))

        ref.mirrors = repaired_mirrors
        return statuses

    def _known_refs(self, ref: StorageRef) -> list[tuple[str, StorageRef]]:
        return [("primary", ref), *[("mirror", mirror) for mirror in ref.mirrors]]

    def _check_candidate(self, role: str, ref: StorageRef) -> StorageReplicaStatus:
        store = self._store_for_ref(ref)
        if store is None:
            return StorageReplicaStatus(
                uri=ref.uri,
                storage_type=ref.storage_type,
                role=role,
                ok=False,
                size_bytes=ref.size_bytes,
                sha256=ref.sha256,
                error="no configured store for replica",
            )
        try:
            data = store.get(ref)
        except Exception as exc:
            return StorageReplicaStatus(
                uri=ref.uri,
                storage_type=ref.storage_type,
                role=role,
                ok=False,
                size_bytes=ref.size_bytes,
                sha256=ref.sha256,
                error=str(exc),
            )
        return StorageReplicaStatus(
            uri=ref.uri,
            storage_type=ref.storage_type,
            role=role,
            ok=True,
            size_bytes=len(data),
            sha256=sha256_hex(data),
        )

    def _store_for_ref(self, ref: StorageRef) -> Optional[EncryptedBlobStore]:
        stores = [self.primary, *self.mirrors]
        for store in stores:
            if _store_matches_ref(store, ref):
                return store
        return None


def _store_matches_ref(store: EncryptedBlobStore, ref: StorageRef) -> bool:
    if isinstance(store, LocalEncryptedBlobStore):
        return ref.storage_type in {"memory", "local"}
    if isinstance(store, IPFSEncryptedBlobStore):
        return ref.storage_type == "ipfs"
    if isinstance(store, S3EncryptedBlobStore):
        return ref.storage_type == "s3"
    if isinstance(store, FilecoinEncryptedBlobStore):
        return ref.storage_type == "filecoin"
    return True


def _create_backend_store(
    config: WalletStorageBackendConfig,
    *,
    ipfs_backend: object | None,
    s3_client: object | None,
    filecoin_backend: object | None,
) -> EncryptedBlobStore:
    storage_type = config.storage_type.lower()
    if storage_type == "memory":
        return LocalEncryptedBlobStore()
    if storage_type == "local":
        if config.root is None:
            raise ValueError("Local wallet storage requires a root path")
        return LocalEncryptedBlobStore(config.root)
    if storage_type == "ipfs":
        return IPFSEncryptedBlobStore(ipfs_backend, pin=config.pin)
    if storage_type == "s3":
        if not config.bucket:
            raise ValueError("S3 wallet storage requires a bucket")
        return S3EncryptedBlobStore(
            s3_client or _default_s3_client(),
            bucket=config.bucket,
            prefix=config.prefix,
        )
    if storage_type == "filecoin":
        if filecoin_backend is None:
            raise ValueError("Filecoin wallet storage requires a backend")
        return FilecoinEncryptedBlobStore(filecoin_backend)
    raise ValueError(f"Unsupported wallet storage type: {config.storage_type}")


def _default_s3_client() -> object:
    try:
        import boto3  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - depends on optional dependency
        raise ValueError("S3 wallet storage requires an explicit client or boto3") from exc
    return boto3.client("s3")


def _status_from_ref(role: str, ref: StorageRef, *, repaired: bool = False) -> StorageReplicaStatus:
    return StorageReplicaStatus(
        uri=ref.uri,
        storage_type=ref.storage_type,
        role=role,
        ok=True,
        size_bytes=ref.size_bytes,
        sha256=ref.sha256,
        repaired=repaired,
    )
