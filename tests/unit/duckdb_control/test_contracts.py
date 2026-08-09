"""Unit tests for identity / provenance / content-reference contracts (DQK-004)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

_REPO_ROOT = Path(__file__).resolve().parents[3]
_LOCAL_ACCELERATE = (_REPO_ROOT / "ipfs_accelerate_py").resolve()


def _prefer_sealed_accelerate_checkout() -> None:
    accelerate_paths: list[Path] = []
    for entry in sys.path:
        try:
            path = Path(entry).resolve()
        except OSError:
            continue
        runtime = (
            path
            / "ipfs_accelerate_py"
            / "agent_supervisor"
            / "validation_runtime.py"
        )
        if runtime.is_file() and path not in accelerate_paths:
            accelerate_paths.append(path)
    if not accelerate_paths:
        return
    preferred = next(
        (path for path in accelerate_paths if path != _LOCAL_ACCELERATE),
        accelerate_paths[0],
    )
    if preferred == _LOCAL_ACCELERATE:
        return
    rebuilt: list[str] = [str(preferred)]
    for entry in sys.path:
        try:
            path = Path(entry).resolve()
        except OSError:
            rebuilt.append(entry)
            continue
        if path in {_LOCAL_ACCELERATE, preferred}:
            continue
        rebuilt.append(entry)
    sys.path[:] = rebuilt
    for name in list(sys.modules):
        if name == "ipfs_accelerate_py" or name.startswith("ipfs_accelerate_py."):
            del sys.modules[name]


_prefer_sealed_accelerate_checkout()

import pytest

from ipfs_datasets_py.duckdb_control import contracts as c


def test_source_digest_from_bytes_and_parse() -> None:
    data = b"exact-source-bytes\x00\xff"
    digest = c.SourceDigest.from_bytes(data)
    assert digest.digest.startswith("sha256:")
    assert c.parse_source_digest(digest.digest) == digest.digest
    assert c.parse_source_digest(digest.digest[7:]) == digest.digest


def test_identity_round_trip_no_drift() -> None:
    payload = {
        "schema_id": "ipfs_datasets_py/duckdb-control@1",
        "count": 3,
        "nested": {"b": 2, "a": 1},
        "list": [1, 2, 3],
        "flag": True,
        "empty": None,
    }
    first = c.round_trip_identity_bytes(payload)
    second = c.canonical_json_bytes(payload)
    assert first == second
    # Key order independent.
    scrambled = {
        "list": [1, 2, 3],
        "schema_id": "ipfs_datasets_py/duckdb-control@1",
        "empty": None,
        "flag": True,
        "count": 3,
        "nested": {"a": 1, "b": 2},
    }
    assert c.canonical_json_bytes(scrambled) == first


def test_rejects_nonfinite_floats() -> None:
    with pytest.raises(c.ContractError, match="non-finite"):
        c.canonical_json_bytes({"x": float("nan")})
    with pytest.raises(c.ContractError, match="non-finite"):
        c.canonical_json_bytes({"x": float("inf")})


def test_timestamp_normalization_utc() -> None:
    aware = datetime(2026, 8, 9, 12, 30, 45, 123456, tzinfo=timezone.utc)
    assert c.normalize_timestamp(aware) == "2026-08-09T12:30:45Z"
    offset = aware.astimezone(timezone(timedelta(hours=-5)))
    assert c.normalize_timestamp(offset) == "2026-08-09T12:30:45Z"
    assert c.normalize_timestamp("2026-08-09T12:30:45Z") == "2026-08-09T12:30:45Z"
    with pytest.raises(c.ContractError, match="timezone-aware"):
        c.normalize_timestamp(datetime(2026, 8, 9, 12, 0, 0))


def test_schema_id_and_snapshot() -> None:
    sid = c.SchemaId(value="ipfs_datasets_py/duckdb-control-schema@1")
    assert sid.value.endswith("@1")
    with pytest.raises(c.ContractError):
        c.SchemaId(value="Not A Schema")
    snap = c.SnapshotId(
        value="sha256:" + ("ab" * 32),
        store_generation=7,
        schema_checksum="sha256:" + ("cd" * 32),
    )
    assert snap.identity_id.startswith("sha256:")
    again = c.SnapshotId(
        value="sha256:" + ("ab" * 32),
        store_generation=7,
        schema_checksum="sha256:" + ("cd" * 32),
    )
    assert snap.identity_id == again.identity_id


def test_idempotency_key_stable() -> None:
    key = c.IdempotencyKey(key="op:ingest:batch-1", scope="catalog:main")
    assert key.identity_id == c.IdempotencyKey(
        key="op:ingest:batch-1", scope="catalog:main"
    ).identity_id
    with pytest.raises(c.ContractError):
        c.IdempotencyKey(key="bad key with spaces!")


def test_content_reference_storage_neutral_and_tamper_evident() -> None:
    payload = b"parquet-bytes-example"
    ref = c.ContentReference.from_bytes(
        payload, media_type=c.ContentMediaType.PARQUET
    )
    assert ref.content_id.startswith("sha256:")
    assert ref.byte_size == len(payload)
    ref.verify_bytes(payload)
    with pytest.raises(c.ContractError, match="mismatch"):
        ref.verify_bytes(payload + b"x")
    # Filesystem paths are not authority.
    with pytest.raises(c.ContractError, match="filesystem"):
        c.ContentReference(
            media_type=c.ContentMediaType.PARQUET,
            content_id=ref.content_id,
            byte_size=ref.byte_size,
            source_digest=ref.source_digest,
            location_hint="/var/data/table.parquet",
        )
    # Location hint does not affect identity.
    a = c.ContentReference(
        media_type=c.ContentMediaType.BYTES,
        content_id=ref.content_id,
        byte_size=ref.byte_size,
        source_digest=ref.source_digest,
        location_hint="s3://bucket/key",
    )
    b = c.ContentReference(
        media_type=c.ContentMediaType.BYTES,
        content_id=ref.content_id,
        byte_size=ref.byte_size,
        source_digest=ref.source_digest,
        location_hint="",
    )
    assert a.identity_id == b.identity_id


def test_export_receipt_non_authoritative() -> None:
    snap = c.SnapshotId(value="snap:gen-1", store_generation=1)
    content = c.ContentReference.from_bytes(b"export-body")
    receipt = c.ExportReceipt(
        export_id="export:tasks:jsonl",
        snapshot=snap,
        content=content,
        created_at="2026-08-09T00:00:00Z",
        renderer_version="1",
    )
    assert receipt.non_authoritative is True
    assert receipt.to_dict()["non_authoritative"] is True
    with pytest.raises(c.ContractError, match="non_authoritative"):
        c.ExportReceipt(
            export_id="export:bad",
            snapshot=snap,
            content=content,
            created_at="2026-08-09T00:00:00Z",
            renderer_version="1",
            non_authoritative=False,
        )


def test_json_edge_cases_integers_stay_integers() -> None:
    raw = c.canonical_json_bytes({"n": 1, "big": 2**53 + 3})
    text = raw.decode("utf-8")
    assert '"n":1' in text
    # Must not emit 1.0 for int 1.
    assert '"n":1.0' not in text
