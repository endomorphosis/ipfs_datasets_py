"""The importer decodes only verified, bounded snapshots of exchange files."""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ipfs_datasets_py.logic.autoformal import span_cache_exchange as exchange
from ipfs_datasets_py.logic.autoformal.span_evidence import SpanEvidenceError


@pytest.fixture
def bundle(tmp_path):
    receipt = exchange.publish_compiled_exchange(
        [
            {
                "source_span_id": "validation-test-span",
                "legal_id": "usc:test:validation",
                "text": "The officer shall retain records.",
                "autoencoder_text": "The duty was omitted.",
                "decompiled": "",
                "agrees": False,
                "cosine_similarity": 0.2,
                "cross_entropy_loss": 1.0,
                "reconstruction_loss": 0.1,
                "retained_observation": "immutable full observation " * 300,
            }
        ],
        tmp_path / "bundle",
        upload=False,
        agent_id="validation-test",
        code_identity="sha256:validation-test",
        model_identity="sha256:synthetic-validation-test",
    )
    path = Path(receipt["manifest"]["path"])
    return path, json.loads(path.read_text())


def _parquet(rows, *, dictionary=True, compression="zstd"):
    sink = pa.BufferOutputStream()
    pq.write_table(
        pa.Table.from_pylist(rows, schema=exchange._schema(exchange.GOAL_COLUMNS)),
        sink,
        use_dictionary=dictionary,
        compression=compression,
    )
    return sink.getvalue().to_pybytes()


def _footer_bytes(raw):
    metadata = pq.ParquetFile(pa.BufferReader(raw)).metadata
    return sum(
        metadata.row_group(i).column(j).total_uncompressed_size
        for i in range(metadata.num_row_groups)
        for j in range(metadata.row_group(i).num_columns)
    )


def test_compressed_footer_expansion_rejected_before_any_row_decode(monkeypatch):
    raw = _parquet([{"task_json": "x" * 100_000} for _ in range(10)], dictionary=False)
    assert len(raw) < 128_000 < _footer_bytes(raw)
    original = pq.ParquetFile

    def footer_only(*args, **kwargs):
        file = original(*args, **kwargs)
        return SimpleNamespace(
            metadata=file.metadata,
            schema_arrow=file.schema_arrow,
            iter_batches=lambda **kw: pytest.fail("rows decoded before footer bound"),
        )

    monkeypatch.setattr(pq, "ParquetFile", footer_only)
    with pytest.raises(SpanEvidenceError, match="footer exceeds decoded"):
        exchange._bounded_parquet_rows(
            raw, exchange.GOAL_COLUMNS, max_rows=10, max_decoded_bytes=128_000
        )


def test_dictionary_expansion_is_bounded_even_when_footer_is_small():
    raw = _parquet([{"task_json": "x" * 8192} for _ in range(512)])
    assert len(raw) < 256_000 and _footer_bytes(raw) < 256_000
    with pytest.raises(SpanEvidenceError, match="expansion exceeds decoded"):
        exchange._bounded_parquet_rows(
            raw, exchange.GOAL_COLUMNS, max_rows=512, max_decoded_bytes=256_000
        )


def test_goal_only_loader_enforces_schema_before_row_validation(tmp_path):
    path = tmp_path / "wrong-schema.parquet"
    pq.write_table(pa.table({"packet_json": ["{}"]}), path)
    with pytest.raises(SpanEvidenceError, match="schema differs"):
        exchange.load_goal_export(path)


def test_goal_only_loader_enforces_row_and_compressed_byte_limits(bundle):
    path, manifest = bundle
    goals = path.parent / manifest["goals"]["filename"]
    count = manifest["goals"]["row_count"]
    assert count > 1
    with pytest.raises(SpanEvidenceError, match="row count exceeds"):
        exchange.load_goal_export(goals, max_rows=count - 1)
    with pytest.raises(SpanEvidenceError, match="bounded regular file"):
        exchange.load_goal_export(goals, max_bytes=10)


def test_goal_only_loader_enforces_decoded_dictionary_limit(tmp_path):
    path = tmp_path / "dictionary.parquet"
    path.write_bytes(_parquet([{"task_json": "x" * 8192} for _ in range(512)]))
    with pytest.raises(SpanEvidenceError, match="expansion exceeds decoded"):
        exchange.load_goal_export(path, max_rows=512, max_decoded_bytes=256_000)


def test_bundle_hash_check_and_decoder_consume_same_snapshot(bundle, monkeypatch):
    path, manifest = bundle
    census_path = path.parent / manifest["census"]["filename"]
    original = exchange._bounded_parquet_rows
    calls = []

    def decode_snapshot(raw, columns, **kwargs):
        calls.append(exchange._sha(raw))
        if columns == exchange.CENSUS_COLUMNS:
            # Replacing the path after its hash was checked cannot substitute
            # new bytes underneath the Parquet decoder.
            census_path.write_bytes(b"path replaced after snapshot verification")
        return original(raw, columns, **kwargs)

    monkeypatch.setattr(exchange, "_bounded_parquet_rows", decode_snapshot)
    loaded = exchange.load_exchange_bundle(path)
    assert loaded["census_rows"][0]["source_span_id"] == "validation-test-span"
    assert calls == [manifest["census"]["sha256"], manifest["goals"]["sha256"]]
    assert exchange._sha(census_path.read_bytes()) != manifest["census"]["sha256"]


def test_bundle_limit_counts_manifest_too(bundle):
    path, manifest = bundle
    payload_bytes = manifest["census"]["bytes"] + manifest["goals"]["bytes"]
    with pytest.raises(SpanEvidenceError, match="byte count exceeds"):
        exchange.load_exchange_bundle(path, max_bytes=payload_bytes)


def test_json_evidence_size_checked_before_json_expansion(bundle, monkeypatch):
    path, manifest = bundle
    monkeypatch.setattr(exchange, "_MAX_ROW_BYTES", 1)
    original = exchange._object
    calls = []

    def observe(raw):
        calls.append(raw)
        return original(raw)

    monkeypatch.setattr(exchange, "_object", observe)
    with pytest.raises(SpanEvidenceError, match="row byte bound"):
        exchange.load_exchange_bundle(path)
    # Only the bounded manifest is parsed; the oversized row JSON is not.
    assert (
        len(calls) == 1
        and json.loads(calls[0])["schema"] == exchange.EXCHANGE_MANIFEST_SCHEMA
    )


def test_decoded_limit_is_shared_across_both_parquet_objects(bundle):
    path, manifest = bundle
    files = [path.parent / manifest[kind]["filename"] for kind in ("census", "goals")]
    decoded = [pq.read_table(file).nbytes for file in files]
    estimates = [_footer_bytes(file.read_bytes()) for file in files]
    bound = max(*decoded, *estimates) + 1
    assert bound < sum(decoded)
    with pytest.raises(SpanEvidenceError, match="decoded byte bound"):
        exchange.load_exchange_bundle(path, max_decoded_bytes=bound)


@pytest.mark.parametrize(
    "filename",
    [
        "../escape.parquet",
        "..",
        "sub/path.parquet",
        "x\\y.parquet",
        "sealed-spans.parquet",
    ],
)
def test_manifest_rejects_unsafe_or_protected_local_filenames(bundle, filename):
    path, manifest = bundle
    manifest["census"]["filename"] = filename
    path.write_text(exchange._json(manifest))
    with pytest.raises(SpanEvidenceError):
        exchange.load_exchange_bundle(path)


def test_manifest_rejects_symlinked_artifact(bundle):
    path, manifest = bundle
    census = path.parent / manifest["census"]["filename"]
    original = census.with_name("saved.parquet")
    census.rename(original)
    census.symlink_to(original)
    with pytest.raises(SpanEvidenceError, match="symlink"):
        exchange.load_exchange_bundle(path)


def test_snapshot_refuses_fifo_without_waiting_for_a_writer(tmp_path):
    fifo = tmp_path / "not-a-regular-file"
    os.mkfifo(fifo)
    with pytest.raises(SpanEvidenceError, match="bounded regular file"):
        exchange._read_regular_snapshot(fifo, max_bytes=100)


def test_snapshot_refuses_in_place_mutation_while_reading(tmp_path, monkeypatch):
    path = tmp_path / "mutable.json"
    path.write_bytes(b"original bytes")
    original = os.fdopen

    class MutatingRead:
        def __init__(self, *args, **kwargs):
            self.file = original(*args, **kwargs)

        def __enter__(self):
            self.file.__enter__()
            return self

        def __exit__(self, *args):
            return self.file.__exit__(*args)

        def fileno(self):
            return self.file.fileno()

        def read(self, amount):
            raw = self.file.read(amount)
            path.write_bytes(b"modified while reading")
            return raw

    monkeypatch.setattr(os, "fdopen", MutatingRead)
    with pytest.raises(SpanEvidenceError, match="changed while reading"):
        exchange._read_regular_snapshot(path, max_bytes=100)


@pytest.mark.parametrize(
    "kwargs", [{"max_rows": 0}, {"max_bytes": True}, {"max_decoded_bytes": -1}]
)
def test_bundle_refuses_invalid_bounds_before_reading_files(tmp_path, kwargs):
    with pytest.raises(SpanEvidenceError, match="positive integer"):
        exchange.load_exchange_bundle(tmp_path / "absent.manifest.json", **kwargs)
