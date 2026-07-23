from __future__ import annotations

import io
import os

os.environ.setdefault("IPFS_DATASETS_AUTO_INSTALL", "false")
os.environ.setdefault("IPFS_AUTO_INSTALL", "false")
os.environ.setdefault("IPFS_DATASETS_PY_MINIMAL_IMPORTS", "1")


class FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}

    def put_object(self, *, Bucket: str, Key: str, Body: bytes, Metadata: dict[str, str]) -> None:
        assert Metadata["encrypted"] == "true"
        self.objects[(Bucket, Key)] = Body

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, io.BytesIO]:
        return {"Body": io.BytesIO(self.objects[(Bucket, Key)])}


class FakeFilecoinBackend:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def store_bytes(self, data: bytes, *, sha256: str) -> str:
        locator = f"deal-{sha256[:12]}"
        self.objects[locator] = data
        return locator

    def retrieve_bytes(self, locator: str) -> bytes:
        return self.objects[locator]


def test_wallet_storage_factory_defaults_to_memory_store() -> None:
    from ipfs_datasets_py.wallet.storage import LocalEncryptedBlobStore, create_encrypted_blob_store

    store = create_encrypted_blob_store()
    ref = store.put(b"encrypted wallet bytes")

    assert isinstance(store, LocalEncryptedBlobStore)
    assert ref.storage_type == "memory"
    assert store.get(ref) == b"encrypted wallet bytes"


def test_wallet_storage_factory_builds_local_store(tmp_path) -> None:
    from ipfs_datasets_py.wallet.storage import LocalEncryptedBlobStore, create_encrypted_blob_store

    store = create_encrypted_blob_store({"type": "local", "root": tmp_path / "wallet-blobs"})
    ref = store.put(b"local encrypted bytes")

    assert isinstance(store, LocalEncryptedBlobStore)
    assert ref.storage_type == "local"
    assert store.get(ref) == b"local encrypted bytes"


def test_wallet_storage_factory_builds_replicated_s3_mirror() -> None:
    from ipfs_datasets_py.wallet.storage import ReplicatedEncryptedBlobStore, create_encrypted_blob_store

    s3 = FakeS3Client()
    store = create_encrypted_blob_store(
        {
            "primary": "memory",
            "mirrors": [{"type": "s3", "bucket": "wallet-backup", "prefix": "docs"}],
        },
        s3_client=s3,
    )
    ref = store.put(b"replicated encrypted bytes")

    assert isinstance(store, ReplicatedEncryptedBlobStore)
    assert ref.storage_type == "memory"
    assert [mirror.storage_type for mirror in ref.mirrors] == ["s3"]
    assert store.get(ref) == b"replicated encrypted bytes"
    assert [status.ok for status in store.check_ref(ref)] == [True, True]


def test_wallet_storage_factory_builds_filecoin_store() -> None:
    from ipfs_datasets_py.wallet.storage import FilecoinEncryptedBlobStore, create_encrypted_blob_store

    backend = FakeFilecoinBackend()
    store = create_encrypted_blob_store("filecoin", filecoin_backend=backend)
    ref = store.put(b"filecoin encrypted bytes")

    assert isinstance(store, FilecoinEncryptedBlobStore)
    assert ref.storage_type == "filecoin"
    assert ref.uri.startswith("filecoin://deal-")
    assert store.get(ref) == b"filecoin encrypted bytes"


def test_wallet_storage_factory_rejects_unconfigured_s3() -> None:
    import pytest
    from ipfs_datasets_py.wallet.storage import create_encrypted_blob_store

    with pytest.raises(ValueError, match="S3 wallet storage requires a bucket"):
        create_encrypted_blob_store("s3")

