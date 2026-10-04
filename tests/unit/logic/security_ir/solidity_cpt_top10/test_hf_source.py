"""Conformance tests for offline Hugging Face snapshot ingestion."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from ipfs_datasets_py.logic.ir_core.canonical import canonical_json_bytes
from ipfs_datasets_py.logic.security_ir.solidity_cpt_top10 import hf_source
from ipfs_datasets_py.logic.security_ir.solidity_cpt_top10.hf_source import (
    CacheManifest,
    HuggingFaceSnapshotIngestor,
    HuggingFaceSourceCache,
    HuggingFaceSourceCacheMiss,
    HuggingFaceSourceIntegrityError,
    HuggingFaceSourceLimitError,
    HuggingFaceSourceLimits,
)
from ipfs_datasets_py.logic.security_ir.solidity_cpt_top10.source_snapshot import (
    DEFAULT_ROW_BOUNDS,
    PINNED_SOURCE_SNAPSHOT,
    QuarantineReason,
    SourceSnapshotVerificationError,
)


def _observation() -> dict:
    return PINNED_SOURCE_SNAPSHOT.observation_dict()


def _row(index: int) -> dict:
    text = f"contract C{index} {{ function f{index}() public {{}} }}"
    return {
        "text": text,
        "source": "etherscan",
        "address": "0x" + f"{index + 1:040x}",
        "name": f"C{index}",
        "compiler": "v0.8.24",
        "license": "MIT",
        "path": f"contracts/C{index}.sol",
        "n_chars": len(text),
    }


def _small_ingest(
    monkeypatch: pytest.MonkeyPatch,
    rows,
    *,
    trusted_rows=None,
):
    monkeypatch.setattr(hf_source, "SOLIDITY_CPT_ROW_COUNT", 2)
    monkeypatch.setattr(
        hf_source,
        "verify_source_snapshot",
        lambda observation: SimpleNamespace(
            row_count=2,
            receipt_id=PINNED_SOURCE_SNAPSHOT.cid,
        ),
    )
    monkeypatch.setattr(
        hf_source,
        "verify_shard_bytes",
        lambda content, observation, verification_method="injected_bytes": SimpleNamespace(
            receipt_id=PINNED_SOURCE_SNAPSHOT.cid
        ),
    )
    trusted = list(rows) if trusted_rows is None else trusted_rows
    monkeypatch.setattr(
        HuggingFaceSnapshotIngestor,
        "_verified_parquet_rows",
        lambda self, content, expected_rows: iter(trusted),
    )
    return HuggingFaceSnapshotIngestor().ingest_rows(
        _observation(),
        rows,
        shard_content=b"verified fixture bytes",
    )


def test_snapshot_metadata_is_verified_before_stream_is_touched() -> None:
    touched = False

    class ExplodesOnIteration:
        def __iter__(self):
            nonlocal touched
            touched = True
            raise AssertionError("metadata drift must fail before row access")

    observation = _observation()
    observation["revision"] = "0" * 40

    with pytest.raises(SourceSnapshotVerificationError, match="revision"):
        HuggingFaceSnapshotIngestor().ingest_rows(
            observation,
            ExplodesOnIteration(),
            shard_content=b"",
        )
    assert touched is False


def test_short_stream_and_late_iterator_failure_are_atomic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    short = _small_ingest(
        monkeypatch,
        [_row(0)],
        trusted_rows=[_row(0), _row(1)],
    )
    assert short.admitted is False
    assert short.rows == ()
    assert short.source_bodies == ()
    assert short.receipt is None
    assert any(item.reason is QuarantineReason.TRUNCATED for item in short.diagnostics)

    def fails_late():
        yield _row(0)
        raise RuntimeError("SOURCE-SENTINEL must never reach diagnostics")

    failed = _small_ingest(
        monkeypatch,
        fails_late(),
        trusted_rows=[_row(0), _row(1)],
    )
    assert failed.admitted is False
    assert failed.rows == ()
    assert {item.reason for item in failed.diagnostics} >= {
        QuarantineReason.MALFORMED,
        QuarantineReason.TRUNCATED,
    }
    assert "SOURCE-SENTINEL" not in json.dumps([item.to_dict() for item in failed.diagnostics])


def test_successful_injected_stream_binds_exact_receipt_and_separate_bodies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _small_ingest(monkeypatch, [_row(0), _row(1)])

    assert result.admitted is True
    assert result.diagnostics == ()
    assert result.receipt is not None
    assert result.receipt.verified is True
    assert result.receipt.grants_authority is False
    assert result.receipt.source_snapshot_cid == PINNED_SOURCE_SNAPSHOT.cid
    assert result.receipt.config_cid == DEFAULT_ROW_BOUNDS.config_cid
    assert result.receipt.row_ids == tuple(item.row_id for item in result.rows)
    assert result.receipt.source_body_cids == tuple(item.content_cid for item in result.source_bodies)
    assert all("text" not in item.to_dict() for item in result.rows)


def test_duplicate_extra_and_unknown_authority_inputs_are_quarantined(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    duplicate = _small_ingest(monkeypatch, [_row(0), _row(0)])
    assert duplicate.admitted is False
    assert duplicate.rows == ()
    assert any(item.reason is QuarantineReason.DUPLICATE for item in duplicate.diagnostics)

    extra = _small_ingest(monkeypatch, [_row(0), _row(1), _row(2)])
    assert extra.admitted is False
    assert any(item.code == "solidity_cpt.stream.extra_rows" for item in extra.diagnostics)

    authority = _row(1)
    authority["authority"] = "allow"
    rejected = _small_ingest(monkeypatch, [_row(0), authority])
    assert rejected.admitted is False
    assert any(item.reason is QuarantineReason.UNKNOWN_AUTHORITY for item in rejected.diagnostics)
    assert rejected.rows == ()


def test_quarantine_count_and_messages_remain_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class CountingRows:
        def __init__(self) -> None:
            self.consumed = 0

        def __iter__(self):
            return self

        def __next__(self):
            if self.consumed >= 5:
                raise StopIteration
            self.consumed += 1
            return None

    monkeypatch.setattr(hf_source, "SOLIDITY_CPT_ROW_COUNT", 5)
    monkeypatch.setattr(
        hf_source,
        "verify_source_snapshot",
        lambda observation: SimpleNamespace(
            row_count=5,
            receipt_id=PINNED_SOURCE_SNAPSHOT.cid,
        ),
    )
    monkeypatch.setattr(
        hf_source,
        "verify_shard_bytes",
        lambda content, observation, verification_method="injected_bytes": SimpleNamespace(
            receipt_id=PINNED_SOURCE_SNAPSHOT.cid
        ),
    )
    monkeypatch.setattr(
        HuggingFaceSnapshotIngestor,
        "_verified_parquet_rows",
        lambda self, content, expected_rows: iter([None] * 5),
    )
    limits = HuggingFaceSourceLimits(
        max_rows=5,
        max_quarantines=2,
        max_diagnostics=2,
    )
    supplied = CountingRows()
    result = HuggingFaceSnapshotIngestor(limits=limits).ingest_rows(
        _observation(),
        supplied,
        shard_content=b"verified fixture bytes",
    )

    assert result.admitted is False
    assert supplied.consumed == 2
    assert len(result.diagnostics) == 2
    assert all(len(item.message) <= DEFAULT_ROW_BOUNDS.max_diagnostic_chars for item in result.diagnostics)


def test_cache_reloads_and_rehashes_every_persisted_body(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _small_ingest(monkeypatch, [_row(0), _row(1)])
    cache = HuggingFaceSourceCache(tmp_path / "cache")
    pin = cache.store(result)
    first = cache.load(pin)

    assert first.receipt == result.receipt
    with pytest.raises(HuggingFaceSourceIntegrityError, match="out-of-band"):
        cache.load()
    with pytest.raises(HuggingFaceSourceIntegrityError, match="out-of-band pin"):
        cache.load(replace(pin, config_cid=result.rows[0].raw_row_cid))
    manifest = json.loads((cache.path / "manifest.json").read_bytes())
    body_path = cache.path / manifest["bodies"][0]["path"]
    original = body_path.read_bytes()
    body_path.write_bytes(b"X" + original[1:])

    with pytest.raises(HuggingFaceSourceIntegrityError, match="identity mismatch"):
        cache.load(pin)


def test_cache_rehashes_nested_rows_and_manifest_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _small_ingest(monkeypatch, [_row(0), _row(1)])
    cache = HuggingFaceSourceCache(tmp_path / "cache")
    pin = cache.store(result)
    manifest_path = cache.path / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    manifest["rows"][0]["name"] = "Changed"
    manifest_path.write_bytes(canonical_json_bytes(manifest))

    with pytest.raises(Exception, match="row_id"):
        cache.load(pin)

    cache_root = tmp_path / "cache-two"
    second_cache = HuggingFaceSourceCache(cache_root)
    second_pin = second_cache.store(result)
    second_manifest = json.loads((second_cache.path / "manifest.json").read_bytes())
    second_manifest.pop("manifest_id")
    (second_cache.path / "manifest.json").write_bytes(canonical_json_bytes(second_manifest))
    with pytest.raises(HuggingFaceSourceIntegrityError, match="unknown or missing"):
        second_cache.load(second_pin)


def test_cache_without_explicit_fetcher_is_offline_only(tmp_path: Path) -> None:
    cache = HuggingFaceSourceCache(tmp_path / "cache")

    with pytest.raises(HuggingFaceSourceCacheMiss, match="offline"):
        cache.load()
    with pytest.raises(HuggingFaceSourceCacheMiss, match="offline"):
        cache.materialize(observation=_observation())


def test_limits_reject_invalid_or_subpin_values() -> None:
    with pytest.raises(HuggingFaceSourceLimitError, match="max_rows"):
        HuggingFaceSourceLimits(max_rows=1)
    with pytest.raises(HuggingFaceSourceLimitError, match="max_diagnostics"):
        HuggingFaceSourceLimits(max_quarantines=1, max_diagnostics=2)
