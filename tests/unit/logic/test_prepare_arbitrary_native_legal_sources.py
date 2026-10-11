"""Source preparation boundaries with explicit producer test doubles only.

Native-format records here test custody and call accounting, not native encoder
execution, useful embeddings or legal fidelity. No model or tensor is loaded.
"""
from copy import deepcopy
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import arbitrary_native_source_cache as cache
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_corpus_manifest as corpus
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_embedding_production as codec
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_embedding_runtime as runtime

_PATH = Path(__file__).parents[3] / "scripts/ops/legal_ir/prepare_arbitrary_native_legal_sources.py"
_SPEC = importlib.util.spec_from_file_location("_bounded_native_source_preparation", _PATH)
helper = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(helper)


def pin(path):
    raw = path.read_bytes()
    return {"path": str(path), "bytes": len(raw), "sha256": sha256(raw).hexdigest()}


def source(tmp_path, text="é may file.\n\nΣ must wait.", prefix="Header naïve.\n", suffix="\nFooter."):
    path = tmp_path / "source.txt"
    path.write_bytes((prefix + text + suffix).encode("utf-8"))
    reference = pin(path)
    start = len(prefix.encode("utf-8"))
    row = {"id": "physical-occurrence:1", "source_text": text,
           "source": {"artifact": {k: reference[k] for k in ("sha256", "bytes")},
             "source_kind": "us_code", "release_id": "source-fixture-v1", "document_id": "usc:test:1",
             "language": "en", "citation": "1 U.S.C. 1", "byte_start": start,
             "byte_end": start + len(text.encode("utf-8")), "normalization": "identity"}}
    return row, {reference["sha256"]: reference}


def config(tmp_path, row, pins, *, mode="reuse", dimension=384):
    requests = tmp_path / "requests.json"
    requests.write_bytes(cache._wire([row]) + b"\n")
    prior = tmp_path / "prior.json"
    prior.write_bytes(b"{}")
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    return {"schema": helper.CONFIG_SCHEMA, "mode": mode, "dimension": dimension,
            "source_requests_pin": pin(requests), "source_artifact_pins": pins,
            "native384_receipt_refs": [pin(prior)] if mode == "reuse" and dimension == 384 else [],
            "native768_report_refs": [pin(prior)] if mode == "reuse" and dimension == 768 else [],
            "snapshot_path": str(snapshot) if mode == "produce384" else None,
            "batch_size": 2 if mode == "produce384" else None}


def explicit_cache_double(monkeypatch, events):
    """Replace cache assembly solely to test the orchestration boundary."""
    def assemble(rows, *, dimension, source_resolver, **kwargs):
        cache._requests(rows, source_resolver)
        events.append({"dimension": dimension, **kwargs})
        return {"status": "ready", "counts": {"requested_rows": len(rows), "ready_rows": len(rows),
                "refused_rows": 0}, "dispositions": [{"id": r["id"], "status": "ready",
                "unavailable_inputs": []} for r in rows], "source_contexts": {}, **cache.FALSE}
    monkeypatch.setattr(cache, "plan_arbitrary_native_source_cache", assemble)


def record_only_receipt(inputs, resolver, kind):
    """A synthetic record fixture; it supplies no model execution attestation."""
    execution = codec.native_execution_profile(batch_size=2)
    execution["kind"] = kind
    return codec.build_embedding_production_receipt(inputs,
        results=[{"input_id": item.input_id, "status": "embedded", "tokens": {
            "input_ids": [101, 1001, 102], "attention_mask": [1, 1, 1], "token_type_ids": [0, 0, 0]},
            "vector": [1.0] + [0.0]*383} for item in inputs], execution=execution,
        model_assets=[{"name": name, "bytes": size, "sha256": digest}
                      for name, (size, digest) in sorted(runtime._PINNED_ASSETS.items())],
        producer={"code_sha256": sha256(Path(runtime.__file__).read_bytes()).hexdigest(),
                  "runtime_versions": {name: "explicit-record-test-double" for name in
                      ("python", "torch", "transformers", "sentence_transformers", "tokenizers")}},
        resolver=resolver)


def test_unicode_clause_spans_keep_absolute_bytes_and_complete_input_provenance(tmp_path):
    row, pins = source(tmp_path)
    inputs, aliases = helper.expand_embedding_inputs([row], pins)
    assert len(inputs) == len(aliases) == 3
    assert [a["role"] for a in aliases] == ["paragraph", "clause", "clause"]
    assert [a["slot"] for a in aliases] == [None, 0, 1]
    start = row["source"]["byte_start"]
    assert inputs[1].source.byte_start == start
    assert inputs[1].source.byte_end == start + len("é may file.".encode())
    assert inputs[2].source.byte_start == start + len("é may file.\n\n".encode())
    for item in inputs:
        assert item.title == row["source"]["document_id"]
        assert item.section == item.citation == item.source.citation == "1 U.S.C. 1"
        assert item.source.artifact.sha256 == row["source"]["artifact"]["sha256"]
        assert item.source.release_id == "source-fixture-v1"
        assert item.input_id.startswith("sha256:") and item.input_id != row["id"]


def test_identical_full_origins_deduplicate_input_ids_but_preserve_caller_occurrences(tmp_path):
    row, pins = source(tmp_path, text="actor may act.")
    other = deepcopy(row)
    other["id"] = "physical-occurrence:2"
    inputs, aliases = helper.expand_embedding_inputs([row, other], pins)
    assert len(inputs) == 1 and len(aliases) == 4
    assert {a["request_id"] for a in aliases} == {row["id"], other["id"]}
    assert {a["input_id"] for a in aliases} == {inputs[0].input_id}


def test_equal_text_at_different_physical_spans_is_not_deduplicated(tmp_path):
    text = "actor may act."
    row, pins = source(tmp_path, text=text, prefix="", suffix="\n\n"+text)
    other = deepcopy(row)
    other["id"] = "physical-occurrence:2"
    other["source"].update(byte_start=len((text+"\n\n").encode()), byte_end=len((text+"\n\n"+text).encode()))
    inputs, aliases = helper.expand_embedding_inputs([row, other], pins)
    assert len(inputs) == 2 and len(aliases) == 4
    assert inputs[0].text == inputs[1].text
    assert inputs[0].input_id != inputs[1].input_id


def test_one_physical_selector_with_contradictory_provenance_is_refused(tmp_path):
    row, pins = source(tmp_path)
    other = deepcopy(row)
    other["id"] = "physical-occurrence:2"
    other["source"]["release_id"] = "contradictory-release"
    with pytest.raises(ValueError, match="contradictory source provenance"):
        helper.expand_embedding_inputs([row, other], pins)


@pytest.mark.parametrize("change", ["text", "offset", "target", "nested_target", "nine_clauses", "duplicate_id"])
def test_malformed_or_target_bearing_requests_refuse_before_any_encoder(tmp_path, monkeypatch, change):
    row, pins = source(tmp_path, text="\n\n".join(["actor may act."]*9) if change == "nine_clauses" else "actor may act.")
    rows = [row]
    if change == "text": row["source_text"] = "actor may ask."
    elif change == "offset": row["source"]["byte_start"] += 1
    elif change == "target": row["target"] = "O(act)"
    elif change == "nested_target": row["source"]["target"] = "O(act)"
    elif change == "duplicate_id": rows.append(deepcopy(row))
    monkeypatch.setattr(runtime, "produce_native_embedding_receipt", lambda *_a, **_k: pytest.fail("encoder called"))
    with pytest.raises(ValueError):
        helper.expand_embedding_inputs(rows, pins)


def test_resolver_is_defensive_and_refuses_generation_change_with_same_bytes(tmp_path):
    row, pins = source(tmp_path)
    resolver = helper.source_resolver(pins)
    locator = resolver(row["source"]["artifact"])
    original = Path(locator).read_bytes()
    first = next(iter(pins.values()))
    selected = Path(first["path"])
    pins[first["sha256"]]["path"] = "/untrusted/changed/path"
    assert resolver(row["source"]["artifact"]) == locator
    assert Path(locator).read_bytes() == original
    replacement = tmp_path / "replacement"
    replacement.write_bytes(original)
    os.replace(replacement, selected)
    with pytest.raises(ValueError, match="generation changed"):
        resolver(row["source"]["artifact"])


def test_resolver_contract_is_accepted_by_actual_corpus_and_producer_validators(tmp_path):
    row, pins = source(tmp_path)
    resolver = helper.source_resolver(pins)
    artifact = row["source"]["artifact"]
    locator = resolver(artifact)
    assert type(locator) is str and Path(locator).is_absolute()
    assert corpus._read_verified(locator, artifact, helper.MAX_SOURCE_ARTIFACT_BYTES) == Path(locator).read_bytes()
    inputs, _ = helper.expand_embedding_inputs([row], pins)
    # This is the real input/source validator, without a model or tokenization.
    checked = codec.validate_embedding_inputs(inputs, resolver=resolver)
    assert [item.to_dict() for item in checked] == [item.to_dict() for item in inputs]


@pytest.mark.parametrize("alias_kind", ["symlink", "hardlink"])
def test_source_aliases_are_refused(tmp_path, alias_kind):
    _, pins = source(tmp_path)
    reference = next(iter(pins.values()))
    alias = tmp_path / "alias"
    if alias_kind == "symlink":
        alias.symlink_to(reference["path"])
        reference["path"] = str(alias)
    else:
        os.link(reference["path"], alias)
    with pytest.raises(ValueError):
        helper.source_resolver(pins)


@pytest.mark.parametrize("dimension", [384, 768])
def test_reuse_never_calls_encoder_and_has_no_production_or_semantic_authority(tmp_path, monkeypatch, dimension):
    row, pins = source(tmp_path)
    cfg = config(tmp_path, row, pins, dimension=dimension)
    events = []
    explicit_cache_double(monkeypatch, events)
    monkeypatch.setattr(runtime, "produce_native_embedding_receipt", lambda *_a, **_k: pytest.fail("encoder called"))
    result = helper.prepare(cfg, output_directory=tmp_path/"out")
    assert result["status"] == "completed" and result["source_cache_status"] == "ready"
    assert result["actual_native384_encoded_input_count"] == result["native384_producer_calls_started"] == 0
    assert result["native384_producer_calls_returned"] == result["optimizer_calls"] == result["decoder_calls"] == 0
    assert result["expanded_encoder_input_aliases"] == []
    assert all(result[name] is False for name in helper._FALSE)
    assert result["encoder_executed_by_cache_adapter"] is False
    assert result["native384_production_executed_by_helper"] is result["native768_production_executed_by_helper"] is False
    assert all(value == 0 for value in result["admission_masks"].values()) and result["formal_output"] is None
    assert len(events) == 1
    key = "native384_receipt_refs" if dimension == 384 else "native768_report_refs"
    assert events[0][key] == cfg[key]
    assert json.loads((tmp_path/"out/summary.json").read_bytes()) == result


def test_explicit_producer_record_double_keeps_exact_receipt_bytes_and_real_call_arguments(tmp_path, monkeypatch):
    row, pins = source(tmp_path)
    cfg = config(tmp_path, row, pins, mode="produce384")
    events, receipts = [], []
    explicit_cache_double(monkeypatch, events)
    def explicit_producer_double(inputs, *, resolver, snapshot_path, batch_size):
        assert snapshot_path == cfg["snapshot_path"] and batch_size == 2
        receipt = record_only_receipt(inputs, resolver, "native")
        receipts.append(receipt)
        return receipt
    monkeypatch.setattr(runtime, "produce_native_embedding_receipt", explicit_producer_double)
    result = helper.prepare(cfg, output_directory=tmp_path/"out")
    assert result["native384_producer_calls_started"] == result["native384_producer_calls_returned"] == 1
    assert result["actual_native384_encoded_input_count"] == result["unique_native384_inputs_requested"] == 3
    reference = result["native_receipt_refs"][0]
    assert Path(reference["path"]).read_bytes() == receipts[0].to_bytes()
    assert pin(Path(reference["path"])) == reference
    assert events[0]["native384_receipt_refs"] == [reference]
    assert result["encoder_execution_attested"] is result["source_semantics_verified"] is False


def test_injected_fixture_receipt_cannot_be_qualified_as_native_production(tmp_path, monkeypatch):
    row, pins = source(tmp_path)
    cfg = config(tmp_path, row, pins, mode="produce384")
    monkeypatch.setattr(runtime, "produce_native_embedding_receipt", lambda inputs, **kw:
                        record_only_receipt(inputs, kw["resolver"], "injected_fixture"))
    monkeypatch.setattr(cache, "plan_arbitrary_native_source_cache", lambda *_a, **_k: pytest.fail("cache assembled"))
    with pytest.raises(ValueError, match="diagnostic fixtures refused"):
        helper.prepare(cfg, output_directory=tmp_path/"out")
    failure = json.loads((tmp_path/"out/failure-summary.json").read_bytes())
    assert failure["status"] == "failed" and failure["actual_native384_encoded_input_count"] == 0
    assert all(failure[name] is False for name in helper._FALSE)
    assert not (tmp_path/"out/source-cache.json").exists()


def test_fixed_owner_chunks_respect_256_inputs_without_losing_physical_occurrences(tmp_path, monkeypatch):
    paragraph = "\n\n".join("actor may act." for _ in range(8))
    separator = "\nSECTION\n"
    row, pins = source(tmp_path, text=paragraph, prefix="", suffix=(separator+paragraph)*39)
    rows = []
    width = len(paragraph.encode())
    for index in range(40):
        current = deepcopy(row)
        current["id"] = "physical-occurrence:" + str(index)
        start = index*len((paragraph+separator).encode())
        current["source"].update(byte_start=start, byte_end=start+width)
        rows.append(current)
    cfg = config(tmp_path, row, pins, mode="produce384")
    requests_path = Path(cfg["source_requests_pin"]["path"])
    requests_path.write_bytes(cache._wire(rows)+b"\n")
    cfg["source_requests_pin"] = pin(requests_path)
    batches, events = [], []
    explicit_cache_double(monkeypatch, events)
    def explicit_producer_double(inputs, **kwargs):
        batches.append([item.input_id for item in inputs])
        return record_only_receipt(inputs, kwargs["resolver"], "native")
    monkeypatch.setattr(runtime, "produce_native_embedding_receipt", explicit_producer_double)
    result = helper.prepare(cfg, output_directory=tmp_path/"out")
    assert [len(batch) for batch in batches] == [256, 104]
    assert len(set(identity for batch in batches for identity in batch)) == 360
    assert result["unique_native384_inputs_requested"] == result["actual_native384_encoded_input_count"] == 360
    assert len(result["expanded_encoder_input_aliases"]) == 360
    assert len(result["native_receipt_refs"]) == result["native384_producer_calls_returned"] == 2


def test_source_generation_change_after_production_retains_receipt_and_truthful_failure(tmp_path, monkeypatch):
    row, pins = source(tmp_path)
    cfg = config(tmp_path, row, pins, mode="produce384")
    source_path = Path(next(iter(pins.values()))["path"])
    def explicit_producer_double(inputs, **kwargs):
        receipt = record_only_receipt(inputs, kwargs["resolver"], "native")
        replacement = tmp_path/"new-source-generation"
        replacement.write_bytes(source_path.read_bytes())
        os.replace(replacement, source_path)
        return receipt
    monkeypatch.setattr(runtime, "produce_native_embedding_receipt", explicit_producer_double)
    with pytest.raises(ValueError, match="generation changed"):
        helper.prepare(cfg, output_directory=tmp_path/"out")
    assert (tmp_path/"out/native384-receipt-001.json").is_file()
    failure = json.loads((tmp_path/"out/failure-summary.json").read_bytes())
    assert failure["actual_native384_encoded_input_count"] == 3
    assert failure["native384_producer_calls_started"] == failure["native384_producer_calls_returned"] == 1
    assert not (tmp_path/"out/source-cache.json").exists()


def test_unreturned_producer_call_does_not_claim_zero_encoder_work(tmp_path, monkeypatch):
    row, pins = source(tmp_path)
    cfg = config(tmp_path, row, pins, mode="produce384")
    def interrupted(*_args, **_kwargs):
        raise RuntimeError("explicit interrupted producer double")
    monkeypatch.setattr(runtime, "produce_native_embedding_receipt", interrupted)
    with pytest.raises(RuntimeError):
        helper.prepare(cfg, output_directory=tmp_path/"out")
    failure = json.loads((tmp_path/"out/failure-summary.json").read_bytes())
    assert failure["native384_producer_calls_started"] == 1
    assert failure["native384_producer_calls_returned"] == 0
    assert failure["actual_native384_encoded_input_count"] is None
    assert failure["optimizer_calls"] == failure["decoder_calls"] == 0


@pytest.mark.parametrize("change", ["extra_target", "width8", "width384_as768", "batch_bool", "batch17", "prior_lane"])
def test_closed_production_config_has_no_width_padding_or_implicit_fallback(tmp_path, monkeypatch, change):
    row, pins = source(tmp_path)
    cfg = config(tmp_path, row, pins, mode="produce384")
    if change == "extra_target": cfg["target"] = "O(act)"
    elif change == "width8": cfg["dimension"] = 8
    elif change == "width384_as768": cfg["dimension"] = 768
    elif change == "batch_bool": cfg["batch_size"] = True
    elif change == "batch17": cfg["batch_size"] = 17
    else: cfg["native384_receipt_refs"] = [pin(tmp_path/"prior.json")]
    monkeypatch.setattr(runtime, "produce_native_embedding_receipt", lambda *_a, **_k: pytest.fail("encoder called"))
    with pytest.raises(ValueError):
        helper.prepare(cfg, output_directory=tmp_path/"out")
    assert not (tmp_path/"out").exists()


def test_existing_output_directory_is_preserved_and_no_producer_runs(tmp_path, monkeypatch):
    row, pins = source(tmp_path)
    cfg = config(tmp_path, row, pins, mode="produce384")
    output = tmp_path / "out"
    output.mkdir()
    marker = output / "keep"
    marker.write_bytes(b"old evidence")
    monkeypatch.setattr(runtime, "produce_native_embedding_receipt", lambda *_a, **_k: pytest.fail("encoder called"))
    with pytest.raises(FileExistsError):
        helper.prepare(cfg, output_directory=output)
    assert marker.read_bytes() == b"old evidence" and list(output.iterdir()) == [marker]


def test_bounded_document_reads_and_unused_artifact_pins_refuse(tmp_path, monkeypatch):
    row, pins = source(tmp_path)
    monkeypatch.setattr(helper, "MAX_SOURCE_ARTIFACT_BYTES", 8)
    with pytest.raises(ValueError):
        helper.expand_embedding_inputs([row], pins)
    monkeypatch.setattr(helper, "MAX_SOURCE_ARTIFACT_BYTES", 8*1024**2)
    unused = tmp_path/"unused.txt"
    unused.write_bytes(b"another unselected document")
    reference = pin(unused)
    pins[reference["sha256"]] = reference
    with pytest.raises(ValueError, match="unused source artifact"):
        helper.expand_embedding_inputs([row], pins)


def test_config_reader_rejects_duplicate_json_keys_and_exact_pin_drift(tmp_path):
    path = tmp_path / "config.json"
    path.write_bytes(b'{"schema":"a","schema":"b"}')
    reference = pin(path)
    with pytest.raises(ValueError, match="JSON"):
        helper.read_config(reference)
    path.write_bytes(b"{}")
    with pytest.raises(ValueError):
        helper.read_config(reference)
