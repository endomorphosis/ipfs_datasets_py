from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.huggingface.bucket import (
    HuggingFaceBucketError,
    HuggingFaceBucketInventory,
    HuggingFaceBucketObject,
    HuggingFaceBucketStore,
)
from ipfs_datasets_py.huggingface.repository import (
    HuggingFaceRepository,
    HuggingFaceRepositoryError,
    HuggingFaceRepositoryFetcher,
    HuggingFaceRepositoryRevision,
)
from ipfs_datasets_py.huggingface.snapshot import (
    HuggingFaceSnapshot,
    HuggingFaceSnapshotCache,
    HuggingFaceSnapshotIntegrityError,
    HuggingFaceSnapshotValidationError,
    HuggingFaceStaleCacheAliasError,
)
from ipfs_datasets_py.logic.intent_ir.source_adapters.snapshot import (
    SkillCenterSnapshot,
    SkillCenterSnapshotCache,
)

_PAYLOAD = b"SQLite format 3\x00generic immutable Hugging Face source"
_COMMIT = "8a5a3020ab828d7785697fc384bd8d53e2fe7f25"


def _snapshot(**changes: object) -> HuggingFaceSnapshot:
    values: dict[str, object] = {
        "dataset_id": "Publicus/abby-voice",
        "dataset_revision": _COMMIT,
        "repository_file": "sources/audio/abby.wav",
        "expected_sha256": hashlib.sha256(_PAYLOAD).hexdigest(),
        "expected_size_bytes": len(_PAYLOAD),
        "download_producer": "producer:offline-abby-fixture",
    }
    values.update(changes)
    return HuggingFaceSnapshot(**values)  # type: ignore[arg-type]


def test_generic_snapshot_api_preserves_skillcenter_wire_contract() -> None:
    snapshot = _snapshot()

    assert HuggingFaceSnapshot is SkillCenterSnapshot
    assert HuggingFaceSnapshotCache is SkillCenterSnapshotCache
    assert SkillCenterSnapshot.from_json(snapshot.to_json()) == snapshot
    assert snapshot.schema_version == "skillcenter-snapshot/v1"
    assert snapshot.snapshot_id.startswith("skillcenter-snapshot:sha256:")
    assert snapshot.logical_source == (f"hf://datasets/Publicus/abby-voice@{_COMMIT}/sources/audio/abby.wav")
    assert snapshot.to_artifact().content_sha256 == snapshot.expected_sha256


def test_generic_and_skillcenter_cache_share_existing_alias(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot()
    generic_cache = HuggingFaceSnapshotCache(
        tmp_path,
        fetcher=lambda _snapshot, _destination: _PAYLOAD,
    )
    cached = generic_cache.materialize(snapshot)

    legacy_cache = SkillCenterSnapshotCache(tmp_path)
    legacy_snapshot = SkillCenterSnapshot.from_dict(snapshot.to_dict())

    assert legacy_cache.materialize(legacy_snapshot) == cached
    assert cached.read_bytes() == _PAYLOAD


def test_cache_hit_never_calls_network_or_fetcher(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    snapshot = _snapshot()
    warm_cache = HuggingFaceSnapshotCache(
        tmp_path,
        fetcher=lambda _snapshot, _destination: _PAYLOAD,
    )
    expected_path = warm_cache.materialize(snapshot)
    calls: list[str] = []

    def forbidden_fetcher(*_args: object, **_kwargs: object) -> bytes:
        calls.append("fetcher")
        raise AssertionError("a verified cache hit must not fetch")

    def forbidden_network(*_args: object, **_kwargs: object) -> str:
        calls.append("network")
        raise AssertionError("a verified cache hit must not access the network")

    monkeypatch.setattr(
        "huggingface_hub.hf_hub_download",
        forbidden_network,
    )
    offline_cache = HuggingFaceSnapshotCache(
        tmp_path,
        fetcher=forbidden_fetcher,
    )

    assert offline_cache.materialize(snapshot) == expected_path
    assert calls == []


def test_generic_cache_rehashes_hit_and_rejects_tamper(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot()
    warm_cache = HuggingFaceSnapshotCache(
        tmp_path,
        fetcher=lambda _snapshot, _destination: _PAYLOAD,
    )
    cached = warm_cache.materialize(snapshot)
    cached.write_bytes(b"x" * len(_PAYLOAD))

    def forbidden_fetcher(*_args: object) -> bytes:
        raise AssertionError("cache tampering must fail closed, not refetch")

    with pytest.raises(HuggingFaceSnapshotIntegrityError, match="sha256 mismatch"):
        HuggingFaceSnapshotCache(tmp_path, fetcher=forbidden_fetcher).materialize(snapshot)


@pytest.mark.parametrize(
    "revision",
    ("main", "MAIN", "master", "MaStEr", "latest", "refs/heads/feature"),
)
def test_generic_snapshot_rejects_mutable_revision(revision: str) -> None:
    with pytest.raises(HuggingFaceSnapshotValidationError, match="immutable"):
        _snapshot(dataset_revision=revision)


def test_generic_cache_rejects_tampered_alias_without_refetch(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot()
    cache = HuggingFaceSnapshotCache(
        tmp_path,
        fetcher=lambda _snapshot, _destination: _PAYLOAD,
    )
    cache.materialize(snapshot)
    alias_path = cache.alias_path(snapshot)
    alias = json.loads(alias_path.read_text(encoding="utf-8"))
    alias["snapshot"]["repository_file"] = "../outside.wav"
    alias_path.write_text(json.dumps(alias), encoding="utf-8")

    with pytest.raises(HuggingFaceStaleCacheAliasError, match="invalid"):
        HuggingFaceSnapshotCache(
            tmp_path,
            fetcher=lambda *_args: pytest.fail("must not refetch"),
        ).materialize(snapshot)


class _RepositoryClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def repo_info(self, **kwargs: str) -> dict[str, str]:
        self.calls.append(kwargs)
        return {"sha": _COMMIT}


def test_repository_resolves_mutable_lookup_to_pinned_snapshot() -> None:
    client = _RepositoryClient()
    repository = HuggingFaceRepository("Publicus/abby-voice", client=client)

    snapshot = repository.snapshot(
        revision="main",
        repository_file="sources/audio/abby.wav",
        expected_sha256=hashlib.sha256(_PAYLOAD).hexdigest(),
        expected_size_bytes=len(_PAYLOAD),
    )

    assert snapshot.dataset_revision == _COMMIT
    assert client.calls == [
        {
            "repo_id": "Publicus/abby-voice",
            "revision": "main",
            "repo_type": "dataset",
        }
    ]


def test_repository_revision_receipt_rejects_mutable_ref() -> None:
    with pytest.raises(HuggingFaceRepositoryError, match="commit SHA"):
        HuggingFaceRepositoryRevision(
            repository_id="Publicus/abby-voice",
            requested_revision="main",
            commit_sha="main",
        )


def test_injected_repository_fetcher_receives_only_pinned_identity(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot()
    source = tmp_path / "hub-source"
    source.write_bytes(_PAYLOAD)
    calls: list[dict[str, object]] = []

    def download(**kwargs: object) -> str:
        calls.append(kwargs)
        return str(source)

    cache = HuggingFaceSnapshotCache(
        tmp_path / "cache",
        fetcher=HuggingFaceRepositoryFetcher(
            download=download,
            local_files_only=True,
        ),
    )

    assert cache.materialize(snapshot).read_bytes() == _PAYLOAD
    assert calls == [
        {
            "repo_id": snapshot.dataset_id,
            "filename": snapshot.repository_file,
            "revision": _COMMIT,
            "repo_type": "dataset",
            "local_files_only": True,
        }
    ]


def _bucket_object(path: str, payload: bytes) -> HuggingFaceBucketObject:
    return HuggingFaceBucketObject(
        path=path,
        size_bytes=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
        etag=f"etag-{path}",
        media_type="Audio/WAV",
    )


def test_bucket_inventory_digest_is_order_independent_and_complete() -> None:
    first = _bucket_object("raw/a.wav", b"a")
    second = _bucket_object("raw/b.wav", b"bb")

    forward = HuggingFaceBucketInventory(
        bucket_id="Publicus/abby-voice",
        prefix="raw",
        objects=(first, second),
    )
    reverse = HuggingFaceBucketInventory(
        bucket_id="Publicus/abby-voice",
        prefix="raw",
        objects=(second, first),
    )

    assert forward.canonical_bytes() == reverse.canonical_bytes()
    assert forward.inventory_sha256 == reverse.inventory_sha256
    assert forward.inventory_digest == forward.inventory_sha256
    assert HuggingFaceBucketInventory.from_json(forward.to_json()) == forward
    assert forward.object_count == 2
    assert forward.total_size_bytes == 3
    assert forward.to_dict()["objects"][0] == {
        "etag": "etag-raw/a.wav",
        "media_type": "audio/wav",
        "path": "raw/a.wav",
        "sha256": hashlib.sha256(b"a").hexdigest(),
        "size_bytes": 1,
    }


class _BucketClient:
    def __init__(
        self,
        rows: list[dict[str, object]],
        *,
        downloads: dict[str, bytes] | None = None,
    ) -> None:
        self.rows = rows
        self.downloads = downloads or {}
        self.calls: list[dict[str, str]] = []

    def list_bucket_tree(self, **kwargs: str) -> dict[str, object]:
        self.calls.append(kwargs)
        return {"objects": self.rows}

    def download_bucket_file(self, *, bucket_id: str, path: str, destination: Path) -> int:
        self.calls.append(
            {
                "bucket_id": bucket_id,
                "path": path,
                "destination": str(destination),
            }
        )
        return destination.write_bytes(self.downloads[path])


def test_bucket_store_uses_injected_read_only_inventory_client() -> None:
    item = _bucket_object("raw/a.wav", b"a")
    client = _BucketClient([item.to_dict()])
    store = HuggingFaceBucketStore("Publicus/abby-voice", client=client)

    inventory = store.inventory(prefix="raw")

    assert inventory.objects == (item,)
    assert client.calls == [{"bucket_id": "Publicus/abby-voice", "prefix": "raw"}]
    assert not hasattr(store, "upload")
    assert not hasattr(store, "delete")
    assert not hasattr(store, "move")


def test_bucket_store_fetches_verifies_and_atomically_promotes(
    tmp_path: Path,
) -> None:
    item = _bucket_object("raw/a.wav", b"a")
    client = _BucketClient([], downloads={item.path: b"a"})
    store = HuggingFaceBucketStore("Publicus/abby-voice", client=client)
    destination = tmp_path / "downloads" / "a.wav"

    assert store.fetch(item, destination) == destination
    assert destination.read_bytes() == b"a"
    assert client.calls[0]["bucket_id"] == "Publicus/abby-voice"
    assert client.calls[0]["path"] == item.path
    assert client.calls[0]["destination"].endswith(".partial")
    assert not list(destination.parent.glob("*.partial"))


def test_bucket_store_rejects_tampered_download(
    tmp_path: Path,
) -> None:
    item = _bucket_object("raw/a.wav", b"a")
    client = _BucketClient([], downloads={item.path: b"x"})
    destination = tmp_path / "a.wav"

    with pytest.raises(HuggingFaceBucketError, match="sha256 mismatch"):
        HuggingFaceBucketStore("Publicus/abby-voice", client=client).fetch(item, destination)

    assert not destination.exists()
    assert not list(tmp_path.glob("*.partial"))


@pytest.mark.parametrize(
    "row",
    (
        {
            "path": "../escape.wav",
            "size_bytes": 1,
            "sha256": hashlib.sha256(b"a").hexdigest(),
            "etag": "etag",
            "media_type": "audio/wav",
        },
        {
            "path": "raw/a.wav",
            "size_bytes": 1,
            "sha256": "short",
            "etag": "etag",
            "media_type": "audio/wav",
        },
        {
            "path": "raw/a.wav",
            "size_bytes": 1,
            "etag": "etag",
            "media_type": "audio/wav",
        },
    ),
)
def test_bucket_inventory_rejects_unsafe_or_incomplete_rows(
    row: dict[str, object],
) -> None:
    client = _BucketClient([row])

    with pytest.raises(HuggingFaceBucketError):
        HuggingFaceBucketStore("Publicus/abby-voice", client=client).inventory(prefix="raw")


def test_bucket_inventory_rejects_duplicate_paths() -> None:
    item = _bucket_object("raw/a.wav", b"a")

    with pytest.raises(HuggingFaceBucketError, match="unique"):
        HuggingFaceBucketInventory(
            bucket_id="Publicus/abby-voice",
            prefix="raw",
            objects=(item, item),
        )
