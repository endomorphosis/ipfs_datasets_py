"""New-source runtime custody tests using explicit inert native/model fixtures.

The cache verifier is an intentional double here. Actual native-record joins
are tested separately; these controls never attest an encoder or train a model.
"""
from copy import deepcopy
import hashlib
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import arbitrary_native_legal_ir_runtime as runtime
from ipfs_datasets_py.logic.formalization.autoencoder import contextual_legal_ir_runtime as original
from ipfs_datasets_py.logic.formalization.autoencoder import normative_legal_ir_runtime as normative
from .test_contextual_legal_ir_runtime import loader, make_contextual, pin, repin, write


def make_new(tmp_path, monkeypatch, dimension=384, *, duplicate=False):
    data = make_contextual(tmp_path, dimension=dimension)
    data["checkpoint"]["recipe"] = deepcopy(normative._RECIPES["normative-wording-ce"])
    repin(data)
    # New IDs/text are deliberately absent from the selected state's original
    # source binding. Decoder state and saved normalizations remain unchanged.
    texts = ["Législation Ω must preserve the notice.", "New actor may examine the record."]
    if duplicate:
        texts[1] = texts[0]
    document = ("Préface.\n" + texts[0] + "\nNext.\n" + texts[1]).encode("utf-8")
    path = tmp_path / "source-document.txt"
    path.write_bytes(document)
    document_pin = pin(path)
    requests, rows, contexts = [], [], {}
    cursor = 0
    for index, text in enumerate(texts):
        raw = text.encode("utf-8")
        start = document.index(raw, cursor)
        cursor = start + len(raw)
        identifier = "new-occurrence:" + str(index)
        source = {"artifact": {k: document_pin[k] for k in ("bytes", "sha256")},
            "source_kind": "us_code", "release_id": "explicit-inert-fixture/v1", "document_id": "fixture:1",
            "language": "en", "citation": "inert fixture", "byte_start": start, "byte_end": cursor,
            "normalization": "identity"}
        requests.append({"id": identifier, "source_text": text, "source": source})
        vector = [float(offset == index) for offset in range(dimension)]
        rows.append({"id": identifier, "source_text": text, "input": vector})
        source_sha = hashlib.sha256(raw).hexdigest()
        contexts[identifier] = {"source_sha256": source_sha, "segments": [{"source_text": text,
            "source_sha256": source_sha, "embedding_sha256": original._digest(vector), "vector": vector,
            "char_start": 0, "char_end": len(text), "byte_start": 0, "byte_end": len(raw)}]}
    cache = {"dimension": dimension, "rows": rows, "source_contexts": contexts}
    calls = []

    def validate(value, *, source_requests, native384_receipt_refs, native768_report_refs, source_resolver):
        assert source_requests == requests
        assert (native384_receipt_refs is not None) == (dimension == 384)
        assert (native768_report_refs is not None) == (dimension == 768)
        for request in requests:
            # Exercise the actual corpus resolver boundary even though native
            # record validation remains an explicit inert double in this file.
            from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_corpus_manifest as corpus
            resolved = source_resolver(request["source"]["artifact"])
            assert corpus._read_verified(resolved, request["source"]["artifact"], 8 * 1024**2) == document
        calls.append(deepcopy(value))
        return deepcopy(value)

    monkeypatch.setattr(runtime.cache_owner, "validate_arbitrary_native_source_cache", validate)
    native_pin = write(tmp_path / "native-record.json", {"inert_native_record_double": True})
    cache_pin = write(tmp_path / "arbitrary-cache.json", cache)
    base = data["options"]
    options = {"request": dict(base["request"], decoder_contract_id=runtime.DECODER_CONTRACT_ID,
                              training_recipe_name="normative-wording-ce"),
        "checkpoint_pin": base["checkpoint_pin"], "preprocessing_pin": base["preprocessing_pin"],
        "donor_checkpoint_pin": base["donor_checkpoint_pin"], "source_cache_pin": cache_pin,
        "source_requests_pin": write(tmp_path / "source-requests.json", requests),
        "native384_receipt_refs": [native_pin] if dimension == 384 else None,
        "native768_report_refs": [native_pin] if dimension == 768 else None,
        "source_artifact_pins": {document_pin["sha256"]: document_pin},
        "source_owner_pins": {name: pin(path) for name, path in runtime.source_owner_paths().items()},
        "row_ids": ["new-occurrence:1", "new-occurrence:0"]}
    data.update(options=options, new_cache=cache, source_document=path, native_record=Path(native_pin["path"]),
                validator_calls=calls)
    return data


@pytest.mark.parametrize("dimension", [384, 768])
def test_new_occurrences_prepare_without_old_inventory_or_model(tmp_path, monkeypatch, loader, dimension):
    data = make_new(tmp_path, monkeypatch, dimension)
    before = Path(data["options"]["preprocessing_pin"]["path"]).read_bytes()
    plan = runtime.prepare_arbitrary_native_legal_ir_runtime(**data["options"])
    assert loader["loads"] == loader["calls"] == []
    assert plan["row_ids"] == ["new-occurrence:1", "new-occurrence:0"]
    assert plan["source_inputs"]["rows"] == list(reversed(data["new_cache"]["rows"]))
    assert plan["decoder_contract"]["arbitrary_new_source_inputs_supported"] is True
    assert plan["decoder_contract"]["target_representability_verified"] is False
    assert plan["source_cache_binding"]["selected_occurrences"] == 2
    assert plan["source_cache_binding"]["selected_clauses"] == 2
    assert set(plan["source_owner_receipts"]) == set(runtime.SOURCE_OWNER_NAMES)
    assert len(plan["source_artifact_receipts"]) == 1
    assert all(value is False for value in plan["authority"].values())
    assert Path(data["options"]["preprocessing_pin"]["path"]).read_bytes() == before


def test_same_prose_at_distinct_offsets_preserves_both_occurrences(tmp_path, monkeypatch, loader):
    data = make_new(tmp_path, monkeypatch, duplicate=True)
    plan = runtime.prepare_arbitrary_native_legal_ir_runtime(**data["options"])
    assert len(plan["source_inputs"]["rows"]) == 2
    assert [row["id"] for row in plan["row_receipts"]] == data["options"]["row_ids"]
    assert [row["row_index"] for row in plan["row_receipts"]] == [1, 0]
    assert loader["loads"] == []


@pytest.mark.parametrize("dimension", [384, 768])
def test_lazy_decode_keeps_saved_state_and_source_only_packet(tmp_path, monkeypatch, loader, dimension):
    data = make_new(tmp_path, monkeypatch, dimension)
    before = Path(data["options"]["checkpoint_pin"]["path"]).read_bytes()
    handle = runtime.open_arbitrary_native_legal_ir_autoencoder(**data["options"])
    assert len(loader["loads"]) == 1 and loader["calls"] == []
    assert handle.describe()["decoder_contract_id"] == runtime.DECODER_CONTRACT_ID
    observed = handle.infer_cached()
    assert observed["schema"] == "arbitrary-native-legal-ir-candidate-inference/v1"
    assert observed["model_inference_executed"] is True
    assert observed["original_targets_accessed"] is False
    assert all(value is False for value in observed["authority"].values())
    assert set(loader["calls"][0]["source_inputs"]) == {"rows", "contexts"}
    assert loader["calls"][0]["options"] == {"output_cap": 512, "deadline_seconds": 120, "batch_size": 8}
    assert Path(data["options"]["checkpoint_pin"]["path"]).read_bytes() == before


@pytest.mark.parametrize("change", ["width8", "dimension_role", "wrong_contract", "extra_request", "wrong_checkpoint",
    "cross_width_native", "missing_native", "duplicate_native", "unused_source_artifact", "missing_source_artifact",
    "bad_source_hash", "missing_owner", "foreign_owner", "unknown_row", "duplicate_row", "cache_width", "target_row",
    "target_segment", "offset_bool", "vector_nan", "vector_not_unit", "duplicate_cache_id"])
def test_boundary_refuses_before_numerical_load(tmp_path, monkeypatch, loader, change):
    data = make_new(tmp_path, monkeypatch)
    options = data["options"]
    request = options["request"]
    cache = data["new_cache"]
    if change == "width8": request["dimension"] = 8
    elif change == "dimension_role": request["dimension_role"] = "latent"
    elif change == "wrong_contract": request["decoder_contract_id"] = normative.DECODER_CONTRACT_ID
    elif change == "extra_request": request["gold"] = []
    elif change == "wrong_checkpoint": request["checkpoint_sha256"] = "f" * 64
    elif change == "cross_width_native": options["native768_report_refs"] = options["native384_receipt_refs"]
    elif change == "missing_native": options["native384_receipt_refs"] = None
    elif change == "duplicate_native": options["native384_receipt_refs"] *= 2
    elif change == "unused_source_artifact":
        path = tmp_path / "unused.txt"; path.write_bytes(b"unused source")
        reference = pin(path); options["source_artifact_pins"][reference["sha256"]] = reference
    elif change == "missing_source_artifact": options["source_artifact_pins"] = {}
    elif change == "bad_source_hash":
        reference = next(iter(options["source_artifact_pins"].values()))
        options["source_artifact_pins"] = {"f" * 64: reference}
    elif change == "missing_owner": options["source_owner_pins"].pop("arbitrary_native_source_cache")
    elif change == "foreign_owner":
        path = tmp_path / "foreign-owner.py"; path.write_bytes(b"# foreign\n")
        options["source_owner_pins"]["arbitrary_native_source_cache"] = pin(path)
    elif change == "unknown_row": options["row_ids"] = ["absent-occurrence"]
    elif change == "duplicate_row": options["row_ids"] *= 2
    elif change == "cache_width": cache["dimension"] = 768
    elif change == "target_row": cache["rows"][0]["target"] = {}
    elif change == "target_segment": cache["source_contexts"][cache["rows"][0]["id"]]["segments"][0]["gold"] = {}
    elif change == "offset_bool": cache["source_contexts"][cache["rows"][0]["id"]]["segments"][0]["byte_start"] = False
    elif change == "vector_nan":
        # Strict serialization refuses NaN before the runtime reads it.
        Path(options["source_cache_pin"]["path"]).write_bytes(b'{"dimension":NaN}')
        options["source_cache_pin"] = pin(options["source_cache_pin"]["path"])
    elif change == "vector_not_unit": cache["rows"][0]["input"][0] = 2.
    elif change == "duplicate_cache_id": cache["rows"][1]["id"] = cache["rows"][0]["id"]
    if change not in ("vector_nan",):
        options["source_cache_pin"] = write(Path(options["source_cache_pin"]["path"]), cache)
    with pytest.raises(ValueError):
        runtime.open_arbitrary_native_legal_ir_autoencoder(**options)
    assert loader["loads"] == loader["calls"] == []


@pytest.mark.parametrize("which", ["source_document", "native_record"])
def test_changed_source_or_native_receipt_blocks_later_generation(tmp_path, monkeypatch, loader, which):
    data = make_new(tmp_path, monkeypatch)
    handle = runtime.open_arbitrary_native_legal_ir_autoencoder(**data["options"])
    with data[which].open("ab") as stream:
        stream.write(b" ")
    with pytest.raises(ValueError):
        handle.infer_cached()
    assert loader["calls"] == []


def test_post_generation_refusal_keeps_detached_diagnostic(tmp_path, monkeypatch, loader):
    data = make_new(tmp_path, monkeypatch)
    handle = runtime.open_arbitrary_native_legal_ir_autoencoder(**data["options"])
    loader["after_infer"] = lambda: data["source_document"].write_bytes(b"changed document")
    with pytest.raises(runtime.ArbitraryNativeLegalRuntimeError) as captured:
        handle.infer_cached()
    error = captured.value
    assert error.model_load_performed and error.model_inference_started and error.model_inference_executed
    assert error.raw_candidate_report["scope"] == "inert boundary observation"


def test_model_input_mutation_is_refused(tmp_path, monkeypatch, loader):
    data = make_new(tmp_path, monkeypatch)
    handle = runtime.open_arbitrary_native_legal_ir_autoencoder(**data["options"])
    loader["mutate_inputs"] = True
    with pytest.raises(runtime.ArbitraryNativeLegalRuntimeError, match="mutated source-only"):
        handle.infer_cached()


def test_foreign_cache_module_after_capture_refuses_before_validator(tmp_path, monkeypatch, loader):
    data = make_new(tmp_path, monkeypatch)
    captured = runtime._capture(**data["options"], deadline_seconds=120,
                                max_reference_bytes=runtime.MAX_REFERENCE_BYTES)
    monkeypatch.setitem(sys.modules, runtime.cache_owner.__name__,
                        SimpleNamespace(__file__=str(tmp_path / "foreign-cache.py")))
    with pytest.raises(ValueError, match="source owner origin differs"):
        runtime._prepare(captured)
    assert data["validator_calls"] == []
    assert loader["loads"] == loader["calls"] == []
