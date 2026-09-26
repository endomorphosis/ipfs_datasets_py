"""Strict receipt codec tests; synthetic vectors are not native inference evidence."""
from dataclasses import asdict, replace
import hashlib
import json
import struct

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_embedding_production as codec
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_corpus_manifest import (
    EmbeddingProvenance, SourceArtifact, SourceSampleRecord, SourceSpan,
)


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False,
                      separators=(",", ":")).encode("utf-8")


def input_entry(tmp_path, index=1, *, text=None, prefix=b"", suffix=b""):
    text = text or f"The agency shall retain record {index}."
    raw = prefix + text.encode("utf-8") + suffix
    path = tmp_path / f"source-{index}.txt"
    path.write_bytes(raw)
    span = SourceSpan(SourceArtifact(hashlib.sha256(raw).hexdigest(), len(raw)), "us_code",
                      "test-release", f"document-{index}", "en", f"5 USC {index}",
                      len(prefix), len(prefix) + len(text.encode("utf-8")))
    return codec.EmbeddingInput(span, "5", str(index), text, span.citation), path


def resolver_for(entries):
    paths = {item.source.artifact.sha256: path for item, path in entries}
    return lambda ref: paths[ref["sha256"]]


def fixture_receipt(entries, *, results=None):
    """All producer fixtures carry the explicit, ineligible injected profile."""
    assets = [{"name": name, "sha256": hashlib.sha256(name.encode()).hexdigest(), "bytes": 1}
              for name in sorted(("config.json", "tokenizer.json", "tokenizer_config.json", "vocab.txt",
                                  "special_tokens_map.json", "modules.json", "sentence_bert_config.json",
                                  "1_Pooling/config.json", "model.safetensors"))]
    if results is None:
        results = [{"input_id": item.input_id, "status": "embedded",
                    "tokens": {"input_ids": [101, 2000, 102], "attention_mask": [1, 1, 1],
                               "token_type_ids": [0, 0, 0]},
                    "vector": [1.0, -0.0] + [0.0] * 382} for item, _ in entries]
    return codec.build_embedding_production_receipt(
        [item for item, _ in entries], results=results,
        execution={**codec.native_execution_profile(), "kind": "injected_fixture"},
        model_assets=assets,
        producer={"code_sha256": "a" * 64,
                  "runtime_versions": {name: "fixture" for name in ("python", "torch", "transformers", "sentence_transformers", "tokenizers")}},
        resolver=resolver_for(entries))


def declared_native_receipt(receipt):
    """Exercise validation of serialized native *claims*, not native production.

    This hand-edited declaration is not runtime attestation. Actual injected
    producer fixtures cannot enter the native conversion path unchanged.
    """
    data = receipt.to_dict()
    data["execution"]["kind"] = "native"
    return codec.EmbeddingProductionReceipt(canonical(data))


def test_exact_float32_canonical_roundtrip_and_exclusive_save(tmp_path):
    entries = [input_entry(tmp_path, prefix="préface\n".encode(), suffix=b"\nend")]
    receipt = fixture_receipt(entries)
    saved = receipt.save(tmp_path / "receipt.json", resolver=resolver_for(entries))
    loaded = codec.load_embedding_production_receipt(
        saved["path"], expected_sha256=saved["sha256"], expected_size_bytes=saved["bytes"],
        resolver=resolver_for(entries))
    assert loaded.to_bytes() == receipt.to_bytes() == canonical(receipt.to_dict())
    assert loaded.status_counts == {"embedded": 1, "token_limit_exceeded": 0, "missing_input": 0}
    assert loaded.inputs == (entries[0][0],)
    bits = bytes.fromhex(loaded.to_dict()["results"][0]["vector"]["bits"])
    assert bits[:8] == struct.pack(">ff", 1.0, -0.0)
    assert loaded.verification_summary()["runtime_cryptographically_attested"] is False
    assert loaded.verification_summary()["source_authority_authenticated"] is False
    assert loaded.verification_summary()["formal_proof_verified"] is False
    with pytest.raises(FileExistsError):
        receipt.save(saved["path"], resolver=resolver_for(entries))
    with pytest.raises(codec.EmbeddingProductionError):
        codec.load_embedding_production_receipt(saved["path"], expected_sha256="f" * 64,
                                                expected_size_bytes=saved["bytes"])
    with pytest.raises(codec.EmbeddingProductionError):
        codec.load_embedding_production_receipt(saved["path"], expected_sha256=saved["sha256"],
                                                expected_size_bytes=saved["bytes"] + 1)


def test_fixture_never_converts_and_returned_metadata_is_fresh(tmp_path):
    entries = [input_entry(tmp_path)]
    receipt = fixture_receipt(entries)
    receipt.to_dict()["execution"]["kind"] = "native"
    receipt.status_counts["embedded"] = 99
    assert receipt.native_execution_profile is False
    with pytest.raises(codec.EmbeddingProductionError, match="injected fixtures"):
        receipt.to_corpus_records(resolver=resolver_for(entries))
    with pytest.raises((AttributeError, TypeError)):
        receipt._raw = b"{}"


def test_declared_native_record_binding_rechecks_sources_and_exact_vectors(tmp_path):
    entries = [input_entry(tmp_path, index) for index in (1, 2)]
    receipt = declared_native_receipt(fixture_receipt(entries))
    records = receipt.to_corpus_records(resolver=resolver_for(entries))
    assert all(record.embedding_provenance == EmbeddingProvenance(codec.MODEL_ID, codec.MODEL_REVISION, receipt.sha256)
               for record in records)
    assert records[0].sample.embedding_vector[:2] == (1.0, -0.0)
    assert struct.pack(">d", records[0].sample.embedding_vector[1]) == struct.pack(">d", -0.0)
    assert receipt.verify_records(records[::-1], resolver=resolver_for(entries))["supplied_records_verified"] == 2
    # A batch may select a subset without requiring unconsumed source artifacts.
    assert receipt.verify_records(records[:1], resolver=resolver_for(entries[:1]))["source_inputs_verified"] == 1
    with pytest.raises(codec.EmbeddingProductionError, match="cover all"):
        receipt.verify_records(records[:1], resolver=resolver_for(entries[:1]), allow_subset=False)
    with pytest.raises(codec.EmbeddingProductionError, match="duplicate"):
        receipt.verify_records([records[0], records[0]], resolver=resolver_for(entries))
    changed = replace(records[0], sample=replace(records[0].sample,
                       embedding_vector=(1.0, 0.0) + records[0].sample.embedding_vector[2:]))
    with pytest.raises(codec.EmbeddingProductionError, match="differs"):
        receipt.verify_records([changed], resolver=resolver_for(entries))
    wrong_receipt = replace(records[0], embedding_provenance=replace(records[0].embedding_provenance, artifact_sha256="b" * 64))
    with pytest.raises(codec.EmbeddingProductionError, match="differs"):
        receipt.verify_records([wrong_receipt], resolver=resolver_for(entries))
    entries[0][1].write_text("tampered")
    with pytest.raises(codec.EmbeddingProductionError, match="source bytes"):
        receipt.verify_records(records[:1], resolver=resolver_for(entries))


def test_closed_missing_and_oversized_dispositions(tmp_path):
    entries = [input_entry(tmp_path, index) for index in (1, 2, 3)]
    tokens = {"input_ids": [100] * 513, "attention_mask": [1] * 513, "token_type_ids": None}
    results = fixture_receipt(entries).to_dict()["results"]
    results[0]["vector"] = [1.0] + [0.0] * 383
    results[1] = {"input_id": entries[1][0].input_id, "status": "token_limit_exceeded",
                  "tokens": codec.token_input_digest(tokens), "vector": None}
    results[2] = {"input_id": entries[2][0].input_id, "status": "missing_input", "tokens": None, "vector": None}
    entries[2][1].unlink()
    receipt = fixture_receipt(entries, results=results)
    assert receipt.status_counts == dict.fromkeys(codec.STATUSES, 1)
    assert receipt.validate_sources(resolver_for(entries))["source_inputs_verified"] == 2
    assert len(declared_native_receipt(receipt).to_corpus_records(resolver=resolver_for(entries))) == 1
    assert receipt.to_dict()["results"][1]["tokens"]["sha256"] == hashlib.sha256(canonical(tokens)).hexdigest()


@pytest.mark.parametrize("mutate", [
    lambda d: d.update(extra=1),
    lambda d: d["model"].update(revision="0" * 40),
    lambda d: d["model"].update(dimension=384.0),
    lambda d: d["execution"].update(truncation=True),
    lambda d: d["execution"].update(eval_mode=1),
    lambda d: d["execution"].update(device="cuda"),
    lambda d: d["execution"].update(max_tokens=1024),
    lambda d: d["execution"].update(batch_size=0),
    lambda d: d["execution"].update(batch_size=17),
    lambda d: d["execution"].update(batch_size=True),
    lambda d: d["execution"].update(dtype="float16"),
    lambda d: d["execution"].update(cpu_threads=2),
    lambda d: d["execution"].update(seed=1),
    lambda d: d["execution"].update(extra="x"),
    lambda d: d["producer"]["runtime_versions"].update(extra="x"),
    lambda d: d["producer"].update(code_sha256="bad"),
    lambda d: d["model_assets"][0].update(bytes=True),
    lambda d: d["model_assets"][0].update(name="../config.json"),
    lambda d: d["model_assets"].pop(),
    lambda d: d["model_assets"].append(d["model_assets"][0]),
    lambda d: d["qualification"].update(runtime_cryptographically_attested=True),
    lambda d: d["status_counts"].update(embedded=True),
    lambda d: d["status_counts"].update(embedded=2),
    lambda d: d["status_counts"].update(other=0),
    lambda d: d["results"][0].update(input_id="sha256:" + "0" * 64),
    lambda d: d["results"][0].update(status="truncated"),
    lambda d: d["results"][0]["tokens"].update(extra=[]),
    lambda d: d["results"][0]["tokens"].update(input_ids=[True, 2, 3]),
    lambda d: d["results"][0]["tokens"].update(input_ids=[1, -1, 3]),
    lambda d: d["results"][0]["tokens"].update(attention_mask=[1, 1]),
    lambda d: d["results"][0]["tokens"].update(token_type_ids=[0]),
    lambda d: d["results"][0]["vector"].update(bits="7fc00000" + "00000000" * 383),
    lambda d: d["results"][0]["vector"].update(bits="7f800000" + "00000000" * 383),
    lambda d: d["results"][0]["vector"].update(bits="00000000" * 384),
    lambda d: d["results"][0]["vector"].update(dimension=383),
    lambda d: d["inputs"][0].update(text="changed"),
    lambda d: d["inputs"][0]["source"].update(normalization="whitespace-v1"),
    lambda d: d["results"].clear(),
])
def test_closed_schema_rejects_invalid_values(tmp_path, mutate):
    data = fixture_receipt([input_entry(tmp_path)]).to_dict()
    mutate(data)
    with pytest.raises(codec.EmbeddingProductionError):
        codec.EmbeddingProductionReceipt(canonical(data))


@pytest.mark.parametrize("raw", [b'{"schema":1,"schema":1}', b'{"value":NaN}',
                                  b'{"value":Infinity}', b'{"value":-Infinity}', b'\xff', b'[]'])
def test_rejects_duplicate_nonfinite_and_malformed_json(raw):
    with pytest.raises(codec.EmbeddingProductionError):
        codec.EmbeddingProductionReceipt(raw)


def test_rejects_noncanonical_bytes_and_serialized_byte_bound(tmp_path, monkeypatch):
    receipt = fixture_receipt([input_entry(tmp_path)])
    with pytest.raises(codec.EmbeddingProductionError, match="noncanonical"):
        codec.EmbeddingProductionReceipt(receipt.to_bytes() + b"\n")
    monkeypatch.setattr(codec, "MAX_BYTES", len(receipt.to_bytes()) - 1)
    with pytest.raises(codec.EmbeddingProductionError, match="byte bound"):
        codec.EmbeddingProductionReceipt(receipt.to_bytes())


@pytest.mark.parametrize("value", [0.1, float("nan"), float("inf"), True, 1])
def test_builder_rejects_lossy_or_nonfinite_float32(tmp_path, value):
    entries = [input_entry(tmp_path)]
    results = [{"input_id": entries[0][0].input_id, "status": "embedded",
                "tokens": {"input_ids": [101], "attention_mask": [1], "token_type_ids": None},
                "vector": [1.0, value] + [0.0] * 382}]
    with pytest.raises(codec.EmbeddingProductionError):
        fixture_receipt(entries, results=results)


def test_source_and_input_construction_boundaries(tmp_path):
    entry = input_entry(tmp_path, text="é carries exact UTF-8.")
    item, path = entry
    assert codec.validate_embedding_inputs([item], resolver=resolver_for([entry])) == (item,)
    with pytest.raises(codec.EmbeddingProductionError, match="selector differs"):
        codec.validate_embedding_inputs([replace(item, text="different")], resolver=resolver_for([entry]))
    with pytest.raises(codec.EmbeddingProductionError, match="normalization"):
        replace(item, source=replace(item.source, normalization="whitespace-v1"))
    with pytest.raises(codec.EmbeddingProductionError, match="UTF-8"):
        codec.validate_embedding_inputs([replace(item, source=replace(item.source, byte_start=1))], resolver=resolver_for([entry]))
    with pytest.raises(codec.EmbeddingProductionError, match="bounded"):
        replace(item, text="x" * (codec.MAX_TEXT_BYTES + 1))
    with pytest.raises(codec.EmbeddingProductionError, match="count"):
        codec.validate_embedding_inputs([item] * 257, resolver=resolver_for([entry]))
    with pytest.raises(codec.EmbeddingProductionError, match="duplicate"):
        codec.validate_embedding_inputs([item, item], resolver=resolver_for([entry]))
    path.unlink()
    with pytest.raises(codec.EmbeddingProductionError, match="source bytes"):
        codec.validate_embedding_inputs([item], resolver=resolver_for([entry]))


def test_load_rejects_symlink_and_source_normalization_is_identity(tmp_path):
    entries = [input_entry(tmp_path, text="The  agency\nshall retain records.")]
    receipt = fixture_receipt(entries)
    path = tmp_path / "receipt.json"
    saved = receipt.save(path, resolver=resolver_for(entries))
    link = tmp_path / "linked.json"
    link.symlink_to(path)
    with pytest.raises(codec.EmbeddingProductionError):
        codec.load_embedding_production_receipt(link, expected_sha256=saved["sha256"], expected_size_bytes=saved["bytes"])
    assert receipt.inputs[0].text == "The  agency\nshall retain records."
