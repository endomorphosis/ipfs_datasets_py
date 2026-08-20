"""Unit tests for identity / provenance / content-reference contracts (DQK-004).

Acceptance coverage:

* Identity-bearing source bytes round-trip without normalization drift
* JSON / floating / timestamp edge cases fail closed or normalize stably
* Content references are storage-neutral and tamper evident
"""

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


# ---------------------------------------------------------------------------
# Source digests / identity round-trip
# ---------------------------------------------------------------------------


def test_source_digest_from_bytes_and_parse() -> None:
    data = b"exact-source-bytes\x00\xff"
    digest = c.SourceDigest.from_bytes(data)
    assert digest.digest.startswith("sha256:")
    assert c.parse_source_digest(digest.digest) == digest.digest
    assert c.parse_source_digest(digest.digest[7:]) == digest.digest
    # Case folding of hex is stable.
    upper = "SHA256:" + digest.digest[7:].upper()
    assert c.parse_source_digest(upper) == digest.digest
    with pytest.raises(c.ContractError):
        c.parse_source_digest("md5:not-a-sha")
    with pytest.raises(c.ContractError):
        c.parse_source_digest("sha256:deadbeef")


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
    # Identity over exact source bytes is stable across recomputation.
    assert c.SourceDigest.from_bytes(first).digest == c.SourceDigest.from_bytes(
        second
    ).digest


def test_identity_bearing_binary_payloads_do_not_normalize() -> None:
    """Source digests hash raw bytes; no text/encoding rewrite."""

    raw = b"\x00\x01\xffidentity-bearing\r\n\t "
    d1 = c.SourceDigest.from_bytes(raw)
    d2 = c.SourceDigest.from_bytes(bytes(raw))
    assert d1.digest == d2.digest
    # A single flipped bit must change the digest.
    mutated = bytearray(raw)
    mutated[-1] ^= 0x01
    assert c.SourceDigest.from_bytes(bytes(mutated)).digest != d1.digest


# ---------------------------------------------------------------------------
# JSON / floating / timestamp edge cases
# ---------------------------------------------------------------------------


def test_rejects_nonfinite_floats() -> None:
    with pytest.raises(c.ContractError, match="non-finite"):
        c.canonical_json_bytes({"x": float("nan")})
    with pytest.raises(c.ContractError, match="non-finite"):
        c.canonical_json_bytes({"x": float("inf")})
    with pytest.raises(c.ContractError, match="non-finite"):
        c.canonical_json_bytes({"x": float("-inf")})
    with pytest.raises(c.ContractError, match="non-finite"):
        c.canonical_json_bytes({"nested": [{"y": float("nan")}]})


def test_json_edge_cases_integers_stay_integers() -> None:
    raw = c.canonical_json_bytes({"n": 1, "big": 2**53 + 3, "neg": -7})
    text = raw.decode("utf-8")
    assert '"n":1' in text
    assert '"neg":-7' in text
    # Must not emit 1.0 for int 1.
    assert '"n":1.0' not in text
    # Finite floats remain floats (not coerced to int).
    fraw = c.canonical_json_bytes({"f": 1.5, "z": 0.0})
    ftext = fraw.decode("utf-8")
    assert '"f":1.5' in ftext
    assert c.round_trip_identity_bytes({"f": 1.5, "z": 0.0}) == fraw


def test_canonical_json_rejects_unsafe_types() -> None:
    with pytest.raises(c.ContractError):
        c.canonical_json_bytes({"bad": {1, 2, 3}})  # type: ignore[dict-item]
    with pytest.raises(c.ContractError):
        c.canonical_json_bytes({"bad": object()})  # type: ignore[dict-item]


def test_timestamp_normalization_utc() -> None:
    aware = datetime(2026, 8, 9, 12, 30, 45, 123456, tzinfo=timezone.utc)
    assert c.normalize_timestamp(aware) == "2026-08-09T12:30:45Z"
    offset = aware.astimezone(timezone(timedelta(hours=-5)))
    assert c.normalize_timestamp(offset) == "2026-08-09T12:30:45Z"
    assert c.normalize_timestamp("2026-08-09T12:30:45Z") == "2026-08-09T12:30:45Z"
    assert (
        c.normalize_timestamp("2026-08-09T12:30:45+00:00") == "2026-08-09T12:30:45Z"
    )
    # Offset forms normalize to the same UTC second.
    assert (
        c.normalize_timestamp("2026-08-09T07:30:45-05:00") == "2026-08-09T12:30:45Z"
    )
    with pytest.raises(c.ContractError, match="timezone-aware"):
        c.normalize_timestamp(datetime(2026, 8, 9, 12, 0, 0))
    with pytest.raises(c.ContractError):
        c.normalize_timestamp("")
    with pytest.raises(c.ContractError):
        c.normalize_timestamp("not-a-timestamp")
    with pytest.raises(c.ContractError):
        c.normalize_timestamp(12345)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Schema / snapshot / idempotency
# ---------------------------------------------------------------------------


def test_schema_id_and_snapshot() -> None:
    sid = c.SchemaId(value="ipfs_datasets_py/duckdb-control-schema@1")
    assert sid.value.endswith("@1")
    assert sid.to_dict()["schema"] == c.SCHEMA_ID_SCHEMA
    with pytest.raises(c.ContractError):
        c.SchemaId(value="Not A Schema")
    with pytest.raises(c.ContractError):
        c.SchemaId(value="")
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
    token_snap = c.SnapshotId(value="snap:gen-42", store_generation=0)
    assert token_snap.value == "snap:gen-42"
    with pytest.raises(c.ContractError):
        c.SnapshotId(value="has spaces")
    with pytest.raises(c.ContractError):
        c.SnapshotId(value="ok", store_generation=-1)
    with pytest.raises(c.ContractError):
        c.SnapshotId(value="ok", store_generation=True)  # type: ignore[arg-type]


def test_idempotency_key_stable() -> None:
    key = c.IdempotencyKey(key="op:ingest:batch-1", scope="catalog:main")
    assert key.identity_id == c.IdempotencyKey(
        key="op:ingest:batch-1", scope="catalog:main"
    ).identity_id
    assert key.to_dict()["scope"] == "catalog:main"
    with pytest.raises(c.ContractError):
        c.IdempotencyKey(key="bad key with spaces!")
    with pytest.raises(c.ContractError):
        c.IdempotencyKey(key="has\nnewline")
    with pytest.raises(c.ContractError):
        c.IdempotencyKey(key="ok", scope="bad scope")
    with pytest.raises(c.ContractError):
        c.IdempotencyKey(key="x" * 600)


# ---------------------------------------------------------------------------
# Content references (IPLD / CAR / Parquet) — storage-neutral, tamper-evident
# ---------------------------------------------------------------------------


def test_content_reference_storage_neutral_and_tamper_evident() -> None:
    payload = b"parquet-bytes-example"
    ref = c.ContentReference.from_bytes(
        payload, media_type=c.ContentMediaType.PARQUET
    )
    assert ref.content_id.startswith("sha256:")
    assert ref.byte_size == len(payload)
    assert ref.media_type is c.ContentMediaType.PARQUET
    ref.verify_bytes(payload)
    with pytest.raises(c.ContractError, match="mismatch"):
        ref.verify_bytes(payload + b"x")
    with pytest.raises(c.ContractError, match="mismatch"):
        # Same digest would require identical bytes; size mismatch alone fails.
        short = c.ContentReference(
            media_type=c.ContentMediaType.PARQUET,
            content_id=ref.content_id,
            byte_size=ref.byte_size + 1,
            source_digest=ref.source_digest,
        )
        short.verify_bytes(payload)
    # Filesystem paths are not authority.
    with pytest.raises(c.ContractError, match="filesystem"):
        c.ContentReference(
            media_type=c.ContentMediaType.PARQUET,
            content_id=ref.content_id,
            byte_size=ref.byte_size,
            source_digest=ref.source_digest,
            location_hint="/var/data/table.parquet",
        )
    with pytest.raises(c.ContractError, match="filesystem"):
        c.ContentReference(
            media_type=c.ContentMediaType.PARQUET,
            content_id=ref.content_id,
            byte_size=ref.byte_size,
            source_digest=ref.source_digest,
            location_hint="C:\\data\\table.parquet",
        )
    with pytest.raises(c.ContractError, match="filesystem"):
        c.ContentReference(
            media_type=c.ContentMediaType.PARQUET,
            content_id=ref.content_id,
            byte_size=ref.byte_size,
            source_digest=ref.source_digest,
            location_hint="object/../escape",
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


def test_content_reference_cid_and_media_types() -> None:
    """CIDv0, CIDv1, and closed media types for IPLD/CAR/Parquet."""

    cid_v0 = "QmYwAPJzv5CZsnA625s3Xf2nemtYgPpHdWEz79ojWnPbdG"
    cid_v1 = "bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi"
    for media, cid in (
        (c.ContentMediaType.IPLD_RAW, cid_v0),
        (c.ContentMediaType.IPLD_DAG_CBOR, cid_v1),
        (c.ContentMediaType.CAR, cid_v1),
        (c.ContentMediaType.PARQUET, "sha256:" + ("11" * 32)),
        (c.ContentMediaType.JSON, "sha256:" + ("22" * 32)),
    ):
        ref = c.ContentReference(
            media_type=media,
            content_id=cid,
            byte_size=1,
        )
        assert ref.content_id == cid
        assert ref.media_type is media
    with pytest.raises(c.ContractError):
        c.ContentReference(
            media_type=c.ContentMediaType.CAR,
            content_id="not-a-cid",
            byte_size=1,
        )
    with pytest.raises(c.ContractError):
        c.ContentReference(
            media_type="application/octet-stream",  # type: ignore[arg-type]
            content_id=cid_v1,
            byte_size=1,
        )
    # from_dict / parse round-trip.
    body = b"car-payload"
    original = c.ContentReference.from_bytes(
        body, media_type=c.ContentMediaType.CAR, location_hint="ipfs://baguqeera"
    )
    restored = c.parse_content_reference(original.to_dict())
    assert restored.content_id == original.content_id
    assert restored.media_type is c.ContentMediaType.CAR
    assert restored.identity_id == original.identity_id
    restored.verify_bytes(body)


# ---------------------------------------------------------------------------
# Export receipts
# ---------------------------------------------------------------------------


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
    assert receipt.identity_id.startswith("sha256:")
    # Location hints on the content ref must not drift export identity.
    content_hinted = c.ContentReference(
        media_type=content.media_type,
        content_id=content.content_id,
        byte_size=content.byte_size,
        source_digest=content.source_digest,
        location_hint="s3://exports/tasks.jsonl",
    )
    receipt_hinted = c.ExportReceipt(
        export_id="export:tasks:jsonl",
        snapshot=snap,
        content=content_hinted,
        created_at="2026-08-09T00:00:00Z",
        renderer_version="1",
    )
    assert receipt.identity_id == receipt_hinted.identity_id
    with pytest.raises(c.ContractError, match="non_authoritative"):
        c.ExportReceipt(
            export_id="export:bad",
            snapshot=snap,
            content=content,
            created_at="2026-08-09T00:00:00Z",
            renderer_version="1",
            non_authoritative=False,
        )
    with pytest.raises(c.ContractError):
        c.ExportReceipt(
            export_id="bad id",
            snapshot=snap,
            content=content,
            created_at="2026-08-09T00:00:00Z",
            renderer_version="1",
        )


def test_schema_constants_are_stable() -> None:
    assert c.CONTRACTS_SCHEMA.endswith("@1")
    assert c.SCHEMA_ID_SCHEMA.endswith("@1")
    assert c.SNAPSHOT_ID_SCHEMA.endswith("@1")
    assert c.IDEMPOTENCY_KEY_SCHEMA.endswith("@1")
    assert c.EXPORT_RECEIPT_SCHEMA.endswith("@1")
    assert c.CONTENT_REF_SCHEMA.endswith("@1")
    # content_identity is deterministic for the same payload.
    assert c.content_identity({"a": 1, "b": 2}) == c.content_identity(
        {"b": 2, "a": 1}
    )

def test_parse_cid_accepts_v0_v1_and_digest() -> None:
    cid_v0 = "QmYwAPJzv5CZsnA625s3Xf2nemtYgPpHdWEz79ojWnPbdG"
    cid_v1 = "bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi"
    assert c.parse_cid(cid_v0) == cid_v0
    assert c.parse_cid(cid_v1) == cid_v1
    digest = "sha256:" + ("ab" * 32)
    assert c.parse_cid(digest) == digest
    with pytest.raises(c.ContractError):
        c.parse_cid("Qmshort")
    with pytest.raises(c.ContractError):
        c.parse_cid("")

