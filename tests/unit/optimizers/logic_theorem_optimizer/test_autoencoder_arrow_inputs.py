"""Bounded IPC, exact bit reconciliation, and genuine mapped numeric views."""
from dataclasses import replace
import hashlib
import json
import os
import struct

import numpy as np
import pyarrow as pa
import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_arrow_inputs as codec
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_embedding_production as production_codec
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_corpus_manifest import SourceArtifact, SourceSpan


@pytest.fixture
def declared_native_profile_fixture(tmp_path):
    """Synthetic contract data; no assertion of native inference or attestation."""
    inputs, paths = [], {}
    for index in (1, 2):
        raw = f"The agency shall retain document {index}.".encode()
        artifact = SourceArtifact(hashlib.sha256(raw).hexdigest(), len(raw))
        path = tmp_path / f"source-{index}.txt"
        path.write_bytes(raw)
        paths[artifact.sha256] = path
        span = SourceSpan(artifact, "us_code", "fixture", f"doc-{index}", "en", f"5 USC {index}", 0, len(raw))
        inputs.append(production_codec.EmbeddingInput(span, "5", str(index), raw.decode(), span.citation))
    resolver = lambda ref: paths[ref["sha256"]]
    vector = [struct.unpack("<f", struct.pack("<f", value))[0] for value in (.6, .8)] + [0.0] * 381 + [-0.0]
    assets = [{"name": name, "sha256": "a" * 64, "bytes": 1} for name in sorted([
        "config.json", "tokenizer.json", "tokenizer_config.json", "special_tokens_map.json", "vocab.txt",
        "modules.json", "1_Pooling/config.json", "sentence_bert_config.json", "model.safetensors"])]
    receipt = production_codec.build_embedding_production_receipt(inputs,
        results=[{"input_id": item.input_id, "status": "embedded", "vector": vector,
                  "tokens": {"input_ids": [101, 102], "attention_mask": [1, 1], "token_type_ids": [0, 0]}}
                 for item in inputs],
        execution={**production_codec.native_execution_profile(), "kind": "injected_fixture"},
        model_assets=assets, producer={"code_sha256": "b" * 64, "runtime_versions": {
            name: "fixture" for name in ("python", "torch", "transformers", "sentence_transformers", "tokenizers")}},
        resolver=resolver)
    data = receipt.to_dict()
    data["execution"]["kind"] = "native"
    receipt = production_codec.EmbeddingProductionReceipt(
        json.dumps(data, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode())
    assert receipt.verification_summary()["runtime_computation_proven"] is False
    return receipt.to_corpus_records(resolver=resolver), receipt, resolver, paths


def seal(tmp_path, fixture, name="inputs.arrow"):
    records, production, resolver, _ = fixture
    saved = codec.write_embedding_inputs_ipc(records, tmp_path / name, production=production, resolver=resolver)
    return saved


def load(saved, fixture, **overrides):
    records, production, resolver, _ = fixture
    args = {"expected_sha256": saved["sha256"], "expected_size_bytes": saved["bytes"],
            "production": production, "records": records, "resolver": resolver, **overrides}
    return codec.load_embedding_inputs_ipc(saved["path"], **args)


def descriptor(path):
    raw = path.read_bytes()
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def test_deterministic_exact_bits_and_actual_readonly_mapped_views(tmp_path, declared_native_profile_fixture):
    fixture = declared_native_profile_fixture
    records, production, _, _ = fixture
    first, second = seal(tmp_path, fixture), seal(tmp_path, fixture, "second.arrow")
    assert {k: v for k, v in first.items() if k != "path"} == {k: v for k, v in second.items() if k != "path"}
    assert first["production_sha256"] == production.sha256
    with load(first, fixture) as mapped:
        assert mapped.record_ids == tuple(item.record_id for item in records)
        assert {k: mapped.statistics[k] for k in ("row_accesses", "scalar_accesses", "array_exports")} == {
            "row_accesses": 0, "scalar_accesses": 0, "array_exports": 0}
        row = mapped.row(records[0].record_id)
        array = row.readonly_array()
        another = mapped.row(records[0].record_id).readonly_array()
        assert type(row) is codec.MappedEmbeddingVector
        assert array.dtype == np.float32 and array.shape == (384,)
        assert np.shares_memory(array, another)
        assert array.ctypes.data >= mapped._file_buffer.address
        assert array.ctypes.data + array.nbytes <= mapped._file_buffer.address + mapped._file_buffer.size
        assert array.tobytes() == struct.pack("<384f", *records[0].sample.embedding_vector)
        assert np.signbit(array[-1])
        assert type(row[0]) is float and row[0] == records[0].sample.embedding_vector[0]
        assert row[True] == records[0].sample.embedding_vector[1]
        assert row[False] == records[0].sample.embedding_vector[0]
        with pytest.raises(TypeError):
            row[[0, 1]]
        assert list(row) == list(records[0].sample.embedding_vector)
        assert type(row[1:]) is codec.MappedEmbeddingVector
        assert np.shares_memory(row[1:].readonly_array(), array)
        with pytest.raises(ValueError):
            array[0] = 1.0
        with pytest.raises(ValueError):
            array.setflags(write=True)
        with pytest.raises(TypeError):
            row[0] = 1.0
        assert mapped.verification_summary()["whole_training_zero_copy"] is False
        assert mapped.verify_unchanged()["artifact_unchanged"] is True
        summary = mapped.verification_summary()
        summary["read_only"] = False
        assert mapped.verification_summary()["read_only"] is True


def test_owner_close_invalidates_sequences_and_releases_fd_but_keeps_export_safe(tmp_path, declared_native_profile_fixture):
    mapped = load(seal(tmp_path, declared_native_profile_fixture), declared_native_profile_fixture)
    row = mapped.row(mapped.record_ids[0])
    exported = row.readonly_array()
    original = exported.tobytes()
    fd = mapped._fd
    mapped.close()
    mapped.close()
    assert mapped.statistics["closed"] is True
    assert row._array is None
    with pytest.raises(OSError):
        os.fstat(fd)
    for action in (lambda: len(row), lambda: row[0], row.readonly_array, mapped.verify_unchanged,
                   lambda: mapped.row(mapped.record_ids[0])):
        with pytest.raises(codec.ArrowInputError, match="closed"):
            action()
    assert exported.tobytes() == original and not exported.flags.writeable


@pytest.mark.parametrize("change", ["size", "sha", "order", "missing", "vector", "source", "producer"])
def test_loader_rejects_artifact_or_source_binding_changes(tmp_path, declared_native_profile_fixture, change):
    fixture = declared_native_profile_fixture
    records, production, resolver, paths = fixture
    saved = seal(tmp_path, fixture)
    overrides = {}
    if change == "size":
        overrides["expected_size_bytes"] = saved["bytes"] + 1
    elif change == "sha":
        overrides["expected_sha256"] = "0" * 64
    elif change == "order":
        overrides["records"] = records[::-1]
    elif change == "missing":
        overrides["records"] = records[:1]
    elif change == "vector":
        sample = replace(records[0].sample, embedding_vector=records[0].sample.embedding_vector[:-1] + (0.0,))
        overrides["records"] = (replace(records[0], sample=sample), records[1])
    elif change == "source":
        next(iter(paths.values())).write_text("tampered source")
    else:
        data = production.to_dict()
        data["producer"]["code_sha256"] = "c" * 64
        overrides["production"] = production_codec.EmbeddingProductionReceipt(
            json.dumps(data, sort_keys=True, separators=(",", ":")).encode())
    with pytest.raises(codec.ArrowInputError):
        load(saved, fixture, **overrides)


def rewrite(saved, path, *, compression=None, metadata=None, columns=None):
    original = pa.ipc.open_file(saved["path"])
    batch = original.get_batch(0)
    schema = batch.schema if metadata is None else batch.schema.with_metadata(metadata)
    if columns is not None:
        batch = pa.record_batch(columns, schema=schema)
    else:
        batch = pa.record_batch(list(batch.columns), schema=schema)
    with pa.ipc.new_file(path, schema, options=pa.ipc.IpcWriteOptions(compression=compression)) as writer:
        writer.write_batch(batch)
    return descriptor(path)


@pytest.mark.parametrize("change", ["record_order", "zero_sign", "metadata_extra", "receipt", "row_count", "duplicate_metadata"])
def test_loader_checks_every_row_and_closed_metadata_even_with_updated_artifact_hash(tmp_path, declared_native_profile_fixture, change):
    saved = seal(tmp_path, declared_native_profile_fixture)
    reader = pa.ipc.open_file(saved["path"])
    batch = reader.get_batch(0)
    kwargs = {}
    if change == "record_order":
        kwargs["columns"] = [batch.column(0).take(pa.array([1, 0])), batch.column(1)]
    elif change == "zero_sign":
        values = batch.column(1).values.to_pylist()
        values[383] = 0.0
        kwargs["columns"] = [batch.column(0), pa.FixedSizeListArray.from_arrays(pa.array(values, type=pa.float32()),
                                                                              type=batch.schema.field(1).type)]
    else:
        metadata = dict(batch.schema.metadata)
        if change == "metadata_extra":
            metadata[b"extra"] = b"not allowed"
        elif change == "receipt":
            metadata[b"production_sha256"] = b"0" * 64
        elif change == "row_count":
            metadata[b"row_count"] = b"9999999999999999999999"
        else:
            metadata = pa.KeyValueMetadata([*metadata.items(), (b"row_count", b"2")])
        kwargs["metadata"] = metadata
    forged = rewrite(saved, tmp_path / "forged.arrow", **kwargs)
    with pytest.raises(codec.ArrowInputError):
        load(forged, declared_native_profile_fixture)


def test_compression_rejected_before_arrow_decodes_any_batch(tmp_path, declared_native_profile_fixture, monkeypatch):
    if not pa.Codec.is_available("lz4"):
        pytest.skip("LZ4 not available")
    saved = seal(tmp_path, declared_native_profile_fixture)
    compressed = rewrite(saved, tmp_path / "compressed.arrow", compression="lz4")
    monkeypatch.setattr(pa.ipc, "open_file", lambda *_: pytest.fail("compressed artifact reached Arrow decoder"))
    with pytest.raises(codec.ArrowInputError, match="compressed"):
        load(compressed, declared_native_profile_fixture)


def test_forged_large_batch_length_rejected_before_arrow_decode(tmp_path, declared_native_profile_fixture, monkeypatch):
    saved = seal(tmp_path, declared_native_profile_fixture)
    raw = bytearray(open(saved["path"], "rb").read())
    footer_size = struct.unpack_from("<I", raw, len(raw) - 10)[0]
    footer = codec._FlatBuffer(raw[-10 - footer_size:-10])
    blocks, _ = footer.vector(footer.root, 3, 24)
    offset = footer.number("<q", blocks)
    metadata_size = footer.number("<i", blocks + 8)
    message = codec._FlatBuffer(raw[offset + 8:offset + metadata_size])
    batch = message.indirect(message.field(message.root, 2))
    position = message.field(batch, 0)
    struct.pack_into("<q", raw, offset + 8 + position, 2**62)
    path = tmp_path / "oversized-declaration.arrow"
    path.write_bytes(raw)
    monkeypatch.setattr(pa.ipc, "open_file", lambda *_: pytest.fail("oversized artifact reached Arrow decoder"))
    with pytest.raises(codec.ArrowInputError, match="row or numeric byte count"):
        load(descriptor(path), declared_native_profile_fixture)


@pytest.mark.parametrize("change", ["bytes", "replace", "truncate", "unlink"])
def test_boundary_recheck_detects_changed_or_replaced_staged_artifact(tmp_path, declared_native_profile_fixture, change):
    saved = seal(tmp_path, declared_native_profile_fixture)
    with load(saved, declared_native_profile_fixture) as mapped:
        path = tmp_path / "inputs.arrow"
        if change == "bytes":
            with path.open("r+b") as handle:
                handle.seek(200)
                handle.write(b"changed")
        elif change == "replace":
            replacement = tmp_path / "replacement.arrow"
            replacement.write_bytes(path.read_bytes())
            replacement.replace(path)
        elif change == "truncate":
            path.write_bytes(b"short")
        else:
            path.unlink()
        with pytest.raises(codec.ArrowInputError, match="changed|available"):
            mapped.verify_unchanged()


def test_exclusive_seal_cleanup_bounds_symlinks_and_failure_fd_cleanup(tmp_path, declared_native_profile_fixture, monkeypatch):
    saved = seal(tmp_path, declared_native_profile_fixture)
    with pytest.raises(FileExistsError):
        seal(tmp_path, declared_native_profile_fixture)
    link = tmp_path / "link.arrow"
    link.symlink_to(saved["path"])
    with pytest.raises(codec.ArrowInputError):
        load({**saved, "path": str(link)}, declared_native_profile_fixture)
    with pytest.raises(codec.ArrowInputError, match="byte bound"):
        load(saved, declared_native_profile_fixture, expected_size_bytes=codec.MAX_ARTIFACT_BYTES + 1)
    with pytest.raises(codec.ArrowInputError, match="1 through 256"):
        load(saved, declared_native_profile_fixture, records=())
    before = len(os.listdir("/proc/self/fd"))
    for _ in range(4):
        with pytest.raises(codec.ArrowInputError):
            load(saved, declared_native_profile_fixture, expected_sha256="0" * 64)
    assert len(os.listdir("/proc/self/fd")) == before
    records, production, resolver, _ = declared_native_profile_fixture
    def fail_publish(*args):
        raise OSError("injected publication failure")
    monkeypatch.setattr(os, "link", fail_publish)
    with pytest.raises(OSError, match="publication failure"):
        codec.write_embedding_inputs_ipc(records, tmp_path / "failed.arrow", production=production, resolver=resolver)
    assert not (tmp_path / "failed.arrow").exists()
    assert not list(tmp_path.glob(".failed.arrow.*"))
