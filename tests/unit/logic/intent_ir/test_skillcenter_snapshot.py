from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
import hashlib
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.intent_ir.source_adapters.snapshot import (
    INSPECTED_SKILLCENTER_PILOT_REVISION,
    SkillCenterSnapshot,
    SkillCenterSnapshotCache,
    SkillCenterSnapshotCacheMiss,
    SkillCenterSnapshotIntegrityError,
    SkillCenterSnapshotValidationError,
    SkillCenterStaleCacheAliasError,
)


_BUNDLE = b"SQLite format 3\x00offline SkillCenter fixture"


def _snapshot(**changes: object) -> SkillCenterSnapshot:
    values: dict[str, object] = {
        "dataset_id": "example/skillcenter",
        "dataset_revision": "f9dd4fec3c86d85ebf116c7408ac5ce602c418a1",
        "repository_file": "pilot/security.sqlite",
        "expected_sha256": hashlib.sha256(_BUNDLE).hexdigest(),
        "expected_size_bytes": len(_BUNDLE),
        "download_producer": "producer:offline-fixture",
    }
    values.update(changes)
    return SkillCenterSnapshot(**values)  # type: ignore[arg-type]


def test_snapshot_is_immutable_deterministic_and_records_pilot_revision() -> None:
    first = _snapshot()
    second = SkillCenterSnapshot.from_dict(first.to_dict())

    assert INSPECTED_SKILLCENTER_PILOT_REVISION == (
        "f9dd4fec3c86d85ebf116c7408ac5ce602c418a1"
    )
    assert first == second
    assert SkillCenterSnapshot.from_json(first.to_json()) == first
    assert first.snapshot_id == second.snapshot_id
    assert first.content_cid.startswith("b")
    assert first.logical_source.endswith(
        "@f9dd4fec3c86d85ebf116c7408ac5ce602c418a1/"
        "pilot/security.sqlite"
    )
    artifact = first.to_artifact()
    assert artifact.content_sha256 == first.expected_sha256
    assert artifact.metadata["dataset_revision"] == first.dataset_revision
    with pytest.raises(FrozenInstanceError):
        first.repository_file = "other.sqlite"  # type: ignore[misc]


@pytest.mark.parametrize(
    "revision",
    ("main", "MAIN", "latest", "refs/heads/pilot"),
)
def test_snapshot_rejects_mutable_revisions(revision: str) -> None:
    with pytest.raises(SkillCenterSnapshotValidationError, match="immutable"):
        _snapshot(dataset_revision=revision)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("repository_file", "../escape.sqlite"),
        ("repository_file", "/absolute.sqlite"),
        ("repository_file", r"nested\escape.sqlite"),
        ("cache_path", "../outside.sqlite"),
        ("cache_path", "/outside.sqlite"),
        ("cache_path", "objects/bundle.partial"),
        ("cache_path", "aliases/not-an-artifact"),
        ("cache_path", "locks/not-an-artifact"),
        ("dataset_id", "../other/dataset"),
    ),
)
def test_snapshot_rejects_path_traversal_and_partial_targets(
    field: str, value: str
) -> None:
    with pytest.raises(SkillCenterSnapshotValidationError):
        _snapshot(**{field: value})


def test_injected_offline_fetcher_uses_atomic_verified_promotion(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot()
    calls: list[Path] = []

    def offline_fetcher(
        requested: SkillCenterSnapshot, destination: Path
    ) -> None:
        assert requested is snapshot
        assert destination != tmp_path / snapshot.cache_path
        assert destination.name.endswith(".partial")
        calls.append(destination)
        destination.write_bytes(_BUNDLE)

    cache = SkillCenterSnapshotCache(tmp_path, fetcher=offline_fetcher)
    path = cache.materialize(snapshot)

    assert path == tmp_path / snapshot.cache_path
    assert path.read_bytes() == _BUNDLE
    assert not calls[0].exists()
    assert cache.materialize(snapshot) == path
    assert len(calls) == 1
    alias = json.loads(cache.alias_path(snapshot).read_text(encoding="utf-8"))
    assert alias["snapshot_id"] == snapshot.snapshot_id
    assert alias["snapshot"]["cache_path"] == snapshot.cache_path


@pytest.mark.parametrize(
    "payload",
    (_BUNDLE[:-1], _BUNDLE[:-1] + b"x"),
)
def test_fetch_rejects_partial_or_hash_mismatched_bytes(
    tmp_path: Path, payload: bytes
) -> None:
    snapshot = _snapshot()
    cache = SkillCenterSnapshotCache(
        tmp_path, fetcher=lambda _snapshot, destination: destination.write_bytes(payload)
    )

    with pytest.raises(SkillCenterSnapshotIntegrityError, match="mismatch"):
        cache.materialize(snapshot)

    assert not cache.cache_path(snapshot).exists()
    assert not cache.alias_path(snapshot).exists()
    assert not list(cache.cache_path(snapshot).parent.glob("*.partial"))


def test_cache_hit_is_rehashed_and_tampering_is_rejected(tmp_path: Path) -> None:
    snapshot = _snapshot()
    cache = SkillCenterSnapshotCache(
        tmp_path, fetcher=lambda _snapshot, _destination: _BUNDLE
    )
    path = cache.materialize(snapshot)
    path.write_bytes(b"x" * len(_BUNDLE))

    with pytest.raises(SkillCenterSnapshotIntegrityError, match="sha256 mismatch"):
        cache.materialize(snapshot)


def test_stale_alias_is_rejected_instead_of_retargeted(tmp_path: Path) -> None:
    snapshot = _snapshot()
    cache = SkillCenterSnapshotCache(
        tmp_path, fetcher=lambda _snapshot, _destination: _BUNDLE
    )
    cache.materialize(snapshot)
    stale = replace(
        snapshot,
        expected_sha256=hashlib.sha256(b"different").hexdigest(),
        expected_size_bytes=len(b"different"),
        cache_path="objects/other",
    )

    with pytest.raises(SkillCenterStaleCacheAliasError, match="stale"):
        cache.materialize(stale)


def test_alias_with_traversal_is_rejected(tmp_path: Path) -> None:
    snapshot = _snapshot()
    cache = SkillCenterSnapshotCache(
        tmp_path, fetcher=lambda _snapshot, _destination: _BUNDLE
    )
    cache.materialize(snapshot)
    alias_path = cache.alias_path(snapshot)
    alias = json.loads(alias_path.read_text(encoding="utf-8"))
    alias["snapshot"]["cache_path"] = "../outside"
    alias_path.write_text(json.dumps(alias), encoding="utf-8")

    with pytest.raises(SkillCenterStaleCacheAliasError, match="invalid"):
        cache.materialize(snapshot)


def test_dangling_alias_symlink_is_rejected(tmp_path: Path) -> None:
    snapshot = _snapshot()
    cache = SkillCenterSnapshotCache(
        tmp_path, fetcher=lambda _snapshot, _destination: _BUNDLE
    )
    cache.alias_path(snapshot).symlink_to(tmp_path / "missing-alias.json")

    with pytest.raises(SkillCenterStaleCacheAliasError, match="regular file"):
        cache.materialize(snapshot)


def test_cache_rejects_symlinked_object_directory(
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "cache"
    cache = SkillCenterSnapshotCache(root, fetcher=lambda *_args: _BUNDLE)
    (root / "objects").symlink_to(outside, target_is_directory=True)

    with pytest.raises(SkillCenterSnapshotValidationError, match="symlink"):
        cache.materialize(_snapshot())
    assert not list(outside.iterdir())


def test_offline_cache_miss_never_attempts_network(tmp_path: Path) -> None:
    cache = SkillCenterSnapshotCache(tmp_path)

    with pytest.raises(SkillCenterSnapshotCacheMiss, match="offline cache miss"):
        cache.materialize(_snapshot())
