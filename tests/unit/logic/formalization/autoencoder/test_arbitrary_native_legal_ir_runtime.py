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


# Occurrence-v2 artifact facade controls. Cache/native and numerical functions
# are explicit inert doubles; the prior numerical12/36 qualification is separate.
def _occurrence_facade_v2_fixture(tmp_path, monkeypatch, loader, *, duplicate=False):
    data = make_new(tmp_path, monkeypatch, duplicate=duplicate)
    data["options"]["request"]["decoder_contract_id"] = runtime.DECODER_CONTRACT_ID_V2
    from ipfs_datasets_py.logic.formalization.autoencoder import contextual_legal_ir_numeric as numeric
    control = dict(calls=[], after=None, error=None, observed=True, status="eos", change=None, reports=[])
    def infer(model, source_inputs, **options):
        control["calls"].append(dict(source_inputs=deepcopy(source_inputs), options=dict(options)))
        if control["error"] is not None: raise control["error"]
        observed = control["observed"];status = control["status"]
        report = dict(schema="contextual-legal-ir-occurrence-inference/v1", dimension=data["dimension"],
            row_count=len(source_inputs["rows"]), source_inputs_sha256=original._digest(source_inputs),
            source_contexts_sha256=original._digest(source_inputs["contexts"]),
            predictions=[dict(id=row["id"],token_ids=[] if status in ("eos","deadline") else [3],
                eos_reached=status=="eos",generation_status=status) for row in source_inputs["rows"]],
            greedy_calls_started=int(observed),greedy_calls_returned=int(observed),
            model_inference_executed=observed,greedy_generation_executed=observed,
            execution_completed=status!="deadline",eos_completed=status=="eos",decoded_IR_valid=None,task_satisfied=None)
        if control["change"] is not None:control["change"](report)
        control["reports"].append(report)
        if control["after"] is not None:control["after"]()
        return report
    monkeypatch.setattr(numeric,"infer_contextual_legal_model_occurrences_v1",infer)
    data["v2"],data["numeric"] = control,numeric
    return data


def test_occurrence_facade_v2_prepare_is_lazy_and_explicit(tmp_path,monkeypatch,loader):
    data = _occurrence_facade_v2_fixture(tmp_path,monkeypatch,loader,duplicate=True)
    def forbidden(*args,**kwargs):raise AssertionError("numerical owner selected during preparation")
    monkeypatch.setattr(original,"_numeric_owner",forbidden)
    plan = runtime.prepare_arbitrary_native_legal_ir_runtime_v2(**data["options"])
    assert plan["schema"] == runtime.SCHEMA_V2
    assert plan["decoder_contract_id"] == runtime.DECODER_CONTRACT_ID_V2
    assert plan["decoder_contract"]["numeric_entrypoint"] == "infer_contextual_legal_model_occurrences_v1"
    assert plan["input_contract"]["exact_binary32_occurrence_vectors"] is True
    assert plan["source_inputs"]["rows"] == list(reversed(data["new_cache"]["rows"]))
    assert loader["loads"] == loader["calls"] == data["v2"]["calls"] == []
    assert plan["native_ir_schema_version"] is plan["decoder_profile_id"] is plan["decoder_format_id"] is None
    assert all(value is False for value in plan["authority"].values())


def test_occurrence_facade_v2_legacy_dispatch_and_policy_stay_fixed(tmp_path,monkeypatch,loader):
    data = _occurrence_facade_v2_fixture(tmp_path,monkeypatch,loader)
    old = deepcopy(data["options"]);old["request"]["decoder_contract_id"] = runtime.DECODER_CONTRACT_ID
    report = runtime.open_arbitrary_native_legal_ir_autoencoder(**old).infer_cached()
    assert report["schema"] == "arbitrary-native-legal-ir-candidate-inference/v1"
    assert len(loader["calls"]) == 1 and data["v2"]["calls"] == []
    count = len(loader["loads"])
    for operation,options in ((runtime.open_arbitrary_native_legal_ir_autoencoder,data["options"]),
                              (runtime.open_arbitrary_native_legal_ir_autoencoder_v2,old)):
        with pytest.raises(ValueError):operation(**options)
    for operation,options in ((runtime.prepare_arbitrary_native_legal_ir_runtime,old),
                              (runtime.prepare_arbitrary_native_legal_ir_runtime_v2,data["options"])):
        for key in ("_decoder_contract_id","_plan_schema","_source_packet_owner"):
            with pytest.raises(ValueError):operation(**dict(options,**{key:runtime.DECODER_CONTRACT_ID_V2}))
    assert len(loader["loads"]) == count


def test_occurrence_facade_v2_dispatch_preserves_distinct_uses(tmp_path,monkeypatch,loader):
    data = _occurrence_facade_v2_fixture(tmp_path,monkeypatch,loader,duplicate=True)
    handle = runtime.open_arbitrary_native_legal_ir_autoencoder_v2(**data["options"])
    assert len(loader["loads"]) == 1 and data["v2"]["calls"] == []
    report = handle.infer_cached();call = data["v2"]["calls"][0]
    assert loader["calls"] == []
    assert report["schema"] == "arbitrary-native-legal-ir-candidate-inference/v2"
    assert report["runtime_selection"]["schema"] == "arbitrary-native-legal-ir-description/v2"
    assert report["runtime_selection"]["decoder_contract_id"] == runtime.DECODER_CONTRACT_ID_V2
    assert [row["id"] for row in call["source_inputs"]["rows"]] == data["options"]["row_ids"]
    assert call["source_inputs"]["rows"][0]["source_text"] == call["source_inputs"]["rows"][1]["source_text"]
    assert call["source_inputs"]["rows"][0]["input"] != call["source_inputs"]["rows"][1]["input"]
    assert call["options"] == dict(output_cap=512,deadline_seconds=120,batch_size=8)
    assert report["numerical_api_call_started"] is report["numerical_api_call_returned"] is True
    assert report["model_inference_executed"] is True
    assert all(value is False for value in report["authority"].values())


def test_occurrence_facade_v2_exact_f32_preflight_precedes_restore(tmp_path,monkeypatch,loader):
    for index,kind in enumerate(("paragraph_int","clause_int","paragraph_nonf32","clause_nonf32")):
        data = _occurrence_facade_v2_fixture(tmp_path/str(index),monkeypatch,loader)
        row = data["new_cache"]["rows"][0];segment = data["new_cache"]["source_contexts"][row["id"]]["segments"][0]
        vector = [1]+[0.]*(data["dimension"]-1) if kind.endswith("int") else [.1,(1.-.1**2)**.5]+[0.]*(data["dimension"]-2)
        if kind.startswith("paragraph"):row["input"] = vector
        else:segment.update(vector=vector,embedding_sha256=original._digest(vector))
        data["options"]["source_cache_pin"] = write(Path(data["options"]["source_cache_pin"]["path"]),data["new_cache"])
        count = len(loader["loads"])
        with pytest.raises(ValueError,match="float32"):
            runtime.open_arbitrary_native_legal_ir_autoencoder_v2(**data["options"])
        assert len(loader["loads"]) == count and data["v2"]["calls"] == []


def test_occurrence_facade_v2_utf8_identity_preflight_precedes_restore(tmp_path,monkeypatch,loader):
    for index,identifier in enumerate(("é"*300,"bad\0identity")):
        data = _occurrence_facade_v2_fixture(tmp_path/str(index),monkeypatch,loader)
        row = data["new_cache"]["rows"][0];old = row["id"];row["id"] = identifier
        data["new_cache"]["source_contexts"][identifier] = data["new_cache"]["source_contexts"].pop(old)
        data["options"]["row_ids"] = [identifier]
        data["options"]["source_cache_pin"] = write(Path(data["options"]["source_cache_pin"]["path"]),data["new_cache"])
        count = len(loader["loads"])
        with pytest.raises(ValueError,match="UTF8"):
            runtime.open_arbitrary_native_legal_ir_autoencoder_v2(**data["options"])
        assert len(loader["loads"]) == count


def test_occurrence_facade_v2_changed_custody_prevents_call(tmp_path,monkeypatch,loader):
    for index,which in enumerate(("source_document","native_record","captured_source_pin")):
        data = _occurrence_facade_v2_fixture(tmp_path/str(index),monkeypatch,loader)
        handle = runtime.open_arbitrary_native_legal_ir_autoencoder_v2(**data["options"])
        if which == "captured_source_pin":
            options = original._json(handle._options_bytes)
            options["pins"]["source:contextual_legal_ir_numeric"]["sha256"] = "f"*64
            handle._options_bytes = original._raw(options)
        else:
            with data[which].open("ab") as stream:stream.write(b" ")
        with pytest.raises(ValueError):handle.infer_cached()
        assert data["v2"]["calls"] == []


def test_occurrence_facade_v2_post_return_refusal_retains_honest_diagnostics(tmp_path,monkeypatch,loader):
    for index,observed in enumerate((True,False)):
        data = _occurrence_facade_v2_fixture(tmp_path/str(index),monkeypatch,loader)
        data["v2"].update(observed=observed,status="eos" if observed else "deadline")
        data["v2"]["after"] = lambda:data["source_document"].write_bytes(b"changed")
        handle = runtime.open_arbitrary_native_legal_ir_autoencoder_v2(**data["options"])
        with pytest.raises(runtime.ArbitraryNativeLegalRuntimeError) as caught:handle.infer_cached()
        error = caught.value
        assert error.numerical_api_call_started is error.numerical_api_call_returned is True
        assert error.model_inference_started is error.model_inference_executed is observed
        assert error.raw_candidate_report["model_inference_executed"] is observed
        data["v2"]["reports"][0]["model_inference_executed"] = not observed
        assert error.raw_candidate_report["model_inference_executed"] is observed


def test_occurrence_facade_v2_entry_binding_fences_before_and_after(tmp_path,monkeypatch,loader):
    for index,after in enumerate((False,True)):
        data = _occurrence_facade_v2_fixture(tmp_path/str(index),monkeypatch,loader)
        handle = runtime.open_arbitrary_native_legal_ir_autoencoder_v2(**data["options"])
        def replace():monkeypatch.setattr(data["numeric"],"infer_contextual_legal_model_occurrences_v1",lambda *args,**kwargs:None)
        if after:data["v2"]["after"] = replace
        else:replace()
        with pytest.raises(ValueError,match="binding changed") as caught:handle.infer_cached()
        assert len(data["v2"]["calls"]) == int(after)
        if after:assert caught.value.raw_candidate_report["model_inference_executed"] is True
    data = _occurrence_facade_v2_fixture(tmp_path/"missing",monkeypatch,loader)
    monkeypatch.setattr(data["numeric"],"infer_contextual_legal_model_occurrences_v1",None)
    before = len(loader["loads"])
    with pytest.raises(ValueError,match="entry required before restoration"):
        runtime.open_arbitrary_native_legal_ir_autoencoder_v2(**data["options"])
    assert len(loader["loads"]) == before and data["v2"]["calls"] == []
    data = _occurrence_facade_v2_fixture(tmp_path/"restore-code",monkeypatch,loader)
    control = data["v2"];entry = data["numeric"].infer_contextual_legal_model_occurrences_v1
    def replacement(model,source_inputs,**options):
        return dict(control=control,dimension=data["dimension"])
    # Both predeclared test functions capture the same two cells. No dynamic
    # compilation/code creation or audit exception is involved.
    assert replacement.__code__.co_freevars == entry.__code__.co_freevars
    loader["after_load"] = lambda:setattr(entry,"__code__",replacement.__code__)
    with pytest.raises(ValueError,match="changed during restoration") as caught:
        runtime.open_arbitrary_native_legal_ir_autoencoder_v2(**data["options"])
    assert caught.value.model_load_started and caught.value.model_load_performed
    assert data["v2"]["calls"] == []
    loader["after_load"] = None


def test_occurrence_facade_v2_zero_greedy_is_not_model_execution(tmp_path,monkeypatch,loader):
    data = _occurrence_facade_v2_fixture(tmp_path,monkeypatch,loader)
    data["v2"].update(observed=False,status="deadline")
    handle = runtime.open_arbitrary_native_legal_ir_autoencoder_v2(**data["options"])
    report = handle.infer_cached();description = handle.describe()
    assert report["numerical_api_call_started"] is report["numerical_api_call_returned"] is True
    assert report["model_inference_started"] is description["model_inference_started"] is False
    assert report["model_inference_executed"] is description["cached_inference_executed"] is False
    assert description["model_inference_executed"] is False
    assert report["raw_candidate_report"]["execution_completed"] is False
    assert report["raw_candidate_report"]["decoded_IR_valid"] is report["raw_candidate_report"]["task_satisfied"] is None


def test_occurrence_facade_v2_malformed_returns_are_unobserved(tmp_path,monkeypatch,loader):
    changes=(lambda r:r.update(schema="wrong/v1"),lambda r:r.update(model_inference_executed=1),
        lambda r:r.update(greedy_calls_returned=2),lambda r:r["predictions"].reverse(),
        lambda r:r.update(source_inputs_sha256="f"*64))
    for index,change in enumerate(changes):
        data = _occurrence_facade_v2_fixture(tmp_path/str(index),monkeypatch,loader);data["v2"]["change"] = change
        handle = runtime.open_arbitrary_native_legal_ir_autoencoder_v2(**data["options"])
        with pytest.raises(ValueError) as caught:handle.infer_cached()
        assert caught.value.model_inference_started is caught.value.model_inference_executed is None
        assert caught.value.numerical_api_call_started is caught.value.numerical_api_call_returned is True
        assert hasattr(caught.value,"raw_candidate_report")
        assert handle.describe()["model_execution_observation"] == "unobserved"


def test_occurrence_facade_v2_numeric_refusal_is_not_observed_false(tmp_path,monkeypatch,loader):
    data = _occurrence_facade_v2_fixture(tmp_path,monkeypatch,loader);data["v2"]["error"] = RuntimeError("inert owner refusal")
    handle = runtime.open_arbitrary_native_legal_ir_autoencoder_v2(**data["options"])
    with pytest.raises(ValueError) as caught:handle.infer_cached()
    error = caught.value
    assert error.numerical_api_call_started is True and error.numerical_api_call_returned is False
    assert error.model_inference_started is error.model_inference_executed is None
    assert error.raw_candidate_report is None


def test_occurrence_facade_v2_raw_statuses_are_not_repaired(tmp_path,monkeypatch,loader):
    for index,status in enumerate(("eos","output_limit","invalid_special_token","deadline")):
        data = _occurrence_facade_v2_fixture(tmp_path/str(index),monkeypatch,loader)
        data["v2"]["status"] = status
        report = runtime.open_arbitrary_native_legal_ir_autoencoder_v2(**data["options"]).infer_cached()
        assert [row["generation_status"] for row in report["raw_candidate_report"]["predictions"]] == [status,status]
        assert report["raw_candidate_report"]["decoded_IR_valid"] is report["raw_candidate_report"]["task_satisfied"] is None
