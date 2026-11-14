"""Fresh native source receipts bind generation without granting legal credit.

The module fixture invokes the installed offline GTE-small producer exactly once
inside the coordinator's admitted native child. No model double or relabelled
receipt supplies positive coverage. The compact head remains untrained and its
symbolic context and assisted completion are authored, target-derived fixtures.
"""
from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import struct
import sys
from unittest.mock import patch

import pytest
import torch

from ipfs_datasets_py.logic.autoformal import legal_relational_batch_evaluation_v1 as batch
from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_generation_v1 as generation
from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_head_v1 as head
from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_source_binding_v1 as subject
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_embedding_production as codec
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_embedding_runtime as runtime
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_corpus_manifest import SourceSpan


def _fixtures():
    path = Path(__file__).with_name("test_legal_compact_content_generation_v1.py")
    spec = importlib.util.spec_from_file_location("_compact_source_binding_generation_fixtures", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


fixtures = _fixtures()
material = fixtures.material
checkpoint = fixtures.checkpoint
wire, sha, digest = fixtures.wire, fixtures.sha, fixtures.digest


def reference(path):
    path = Path(path)
    raw = path.read_bytes()
    return {"path": str(path.absolute()), "bytes": len(raw), "sha256": sha(raw)}


def receipt_wire(value):
    # The receipt owner's canonical transport deliberately differs from the
    # compact generation owner's UTF-8 transport for non-ASCII source text.
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("utf-8")


def no_authority(report):
    assert report["authority"] and all(value is False for value in report["authority"].values())
    assert type(report["training_mask"]) is int and report["training_mask"] == 0
    assert type(report["evaluation_gold_mask"]) is int and report["evaluation_gold_mask"] == 0
    assert report["runtime_computation_proven"] is False
    assert report["source_encoder_authenticated"] is False


@pytest.fixture(scope="module", autouse=True)
def bounded_threads():
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    try:
        yield
    finally:
        torch.set_num_threads(previous)


@pytest.fixture(scope="module")
def native(tmp_path_factory):
    fixture_path = os.environ.get("LEGAL_COMPACT_SOURCE_BINDING_FIXTURE")
    assert fixture_path, "admitted current native source fixture is required; no skip or synthetic fallback"
    fixture_ref = reference(fixture_path)
    supplied = json.loads(Path(fixture_path).read_bytes())
    assert supplied["schema"] == "legal-compact-source-binding-native-fixture/v1"
    assert set(supplied) == {"schema", "snapshot_path", "source_artifacts", "embedded_requests", "oversized_request"}
    artifacts = supplied["source_artifacts"]
    assert len(artifacts) == 3
    for artifact in artifacts:
        assert set(artifact) == {"path", "sha256", "bytes"}
        assert reference(artifact["path"]) == artifact
    artifact_index = {artifact["sha256"]: artifact for artifact in artifacts}
    assert len(artifact_index) == 3
    requests = supplied["embedded_requests"] + [supplied["oversized_request"]]
    assert len(supplied["embedded_requests"]) == 3
    assert all(set(row) == {"occurrence_id", "input"} for row in requests)
    inputs = [codec.EmbeddingInput.from_dict(row["input"]) for row in requests]
    assert len({item.input_id for item in inputs}) == 4
    assert len({row["occurrence_id"] for row in requests}) == 4
    assert inputs[1].text == inputs[2].text
    assert inputs[1].source != inputs[2].source
    assert inputs[0].source.source_kind == "us_code"
    assert all(item.source.source_kind == "diagnostic" for item in inputs[1:])
    assert all(item.source.language == "en" for item in inputs)

    def resolver(value):
        artifact = artifact_index[value["sha256"]]
        assert value == {key: artifact[key] for key in ("sha256", "bytes")}
        return Path(artifact["path"])

    destination = tmp_path_factory.mktemp("compact-source-binding-native")
    observations = []
    token_observations = []
    original_produce_results = runtime._produce_results
    original_untruncated_tokens = runtime._untruncated_tokens

    def observe_untruncated_tokens(model, text):
        index = len(token_observations)
        assert index < len(inputs) and text == inputs[index].text
        tokens = original_untruncated_tokens(model, text)
        token_observations.append({"input_id": inputs[index].input_id,
            "source_sha256": sha(text.encode("utf-8")), "tokens": deepcopy(tokens),
            "token_count": len(tokens["input_ids"])})
        return tokens

    def observe_results(selected, model, torch_module, *, batch_size, token_input_digest):
        # Observe the actual admitted SentenceTransformer without substituting
        # weights, tokenization, outputs or numerical execution.
        def observed_forward(actual_model, arguments, output):
            assert actual_model is model and torch_module.is_inference_mode_enabled()
            features = arguments[0]
            vectors = output["sentence_embedding"]
            assert vectors.device.type == "cpu" and vectors.dtype == torch_module.float32
            observations.append({"input_ids": features["input_ids"].tolist(),
                "attention_mask": features["attention_mask"].tolist(),
                "token_type_ids": features["token_type_ids"].tolist() if "token_type_ids" in features else None,
                "shape": list(vectors.shape), "dtype": str(vectors.dtype), "device": str(vectors.device),
                "inference_mode": torch_module.is_inference_mode_enabled(),
                "vector_bits": [b"".join(struct.pack(">f", value) for value in row).hex()
                    for row in vectors.tolist()]})
        handle = model.register_forward_hook(observed_forward)
        try:
            return original_produce_results(selected, model, torch_module,
                batch_size=batch_size, token_input_digest=token_input_digest)
        finally:
            handle.remove()

    # Exactly one public native constructor and one real forward for all three
    # eligible inputs. The oversized input retains the producer's refusal.
    with patch.object(runtime, "_produce_results", observe_results), \
            patch.object(runtime, "_untruncated_tokens", observe_untruncated_tokens):
        receipt = runtime.produce_native_embedding_receipt(inputs, resolver=resolver,
            snapshot_path=supplied["snapshot_path"], batch_size=3)
    assert runtime._produce_results is original_produce_results
    assert runtime._untruncated_tokens is original_untruncated_tokens
    assert receipt.status_counts == {"embedded": 3, "token_limit_exceeded": 1, "missing_input": 0}
    assert len(observations) == 1 and observations[0]["shape"] == [3, 384]
    assert len(token_observations) == 4
    observed = observations[0]
    payload = receipt.to_dict()
    for index, row in enumerate(payload["results"][:3]):
        assert token_observations[index]["tokens"] == row["tokens"]
        assert observed["vector_bits"][index] == row["vector"]["bits"]
        mask = observed["attention_mask"][index]
        assert [value for value, visible in zip(observed["input_ids"][index], mask) if visible] == row["tokens"]["input_ids"]
        if observed["token_type_ids"] is not None:
            assert [value for value, visible in zip(observed["token_type_ids"][index], mask) if visible] == row["tokens"]["token_type_ids"]
    assert token_observations[3]["token_count"] > 512
    assert codec.token_input_digest(token_observations[3]["tokens"]) == payload["results"][3]["tokens"]
    receipt_ref = receipt.save(destination / "fresh-native-embedding-receipt.json", resolver=resolver)
    assert reference(receipt_ref["path"]) == receipt_ref
    assert receipt.native_execution_profile is True
    native_evidence = {"schema": "legal-compact-source-binding-native-evidence/v1",
        "input_fixture": fixture_ref, "source_artifacts": artifacts,
        "source_requests": requests, "native_receipt": receipt_ref,
        "receipt_inputs": payload["inputs"], "receipt_results": payload["results"],
        "receipt_status_counts": payload["status_counts"], "forward_observations": observations,
        "token_observations": token_observations, "actual_untruncated_tokenization_call_count": 4,
        "actual_native_producer_call_count": 1, "actual_encoder_forward_count": 1,
        "encoder_inference_executed": True, "model_executed": True,
        "training_executed": False, "optimizer_executed": False,
        "retained_statutory_input_indices": [0], "authored_diagnostic_input_indices": [1, 2, 3],
        "runtime_cryptographically_attested": False, "source_authority_authenticated": False,
        "source_equivalence_proven": False, "convergence_proven": False}
    (destination / "source-binding-native-evidence.json").write_bytes(wire(native_evidence))
    return {"fixture_ref": fixture_ref, "fixture": supplied, "artifacts": artifacts,
        "requests": requests, "inputs": inputs, "receipt": receipt,
        "receipt_ref": receipt_ref, "resolver": resolver, "directory": destination,
        "native_evidence": native_evidence}


def prepare(native, *, index=0, request=None, receipt_ref=None, input_id=None, **changes):
    request = native["requests"][index] if request is None else request
    request_sha = changes["expected_source_request_sha256"] if "expected_source_request_sha256" in changes else digest(request)
    options = {"expected_source_request_sha256": request_sha,
        "input_id": request["input"]["input_id"] if input_id is None else input_id,
        "source_resolver": native["resolver"], **changes}
    return subject.prepare_compact_source_conditioning_v1(request,
        native["receipt_ref"] if receipt_ref is None else receipt_ref, **options)


def case_for_request(material, request, requests):
    ids = tuple(row["occurrence_id"] for row in requests) + ("unobserved-source-binding-control",)
    case = fixtures.fixtures.make_case(material, ids=ids)
    for row, original in zip(case["population"]["rows"], requests):
        row["source_sha256"] = sha(original["input"]["text"].encode("utf-8"))
    case["population_raw"] = fixtures.fixtures.transport(case["population"])
    population_sha = sha(case["population_raw"])
    case["references"]["population_sha256"] = population_sha
    return case


@pytest.fixture(scope="module")
def bound_cases(native, material, checkpoint):
    request = native["requests"][0]
    conditioning = prepare(native)
    case = case_for_request(material, request, native["requests"])
    context_raw = wire(material["context"])
    common = {"expected_population_sha256": sha(case["population_raw"]),
        "expected_source_request_sha256": digest(request), "input_id": request["input"]["input_id"],
        "occurrence_id": request["occurrence_id"], "expected_checkpoint_sha256": digest(checkpoint),
        "expected_context_sha256": sha(context_raw), "context_origin": "target_derived_label",
        "source_resolver": native["resolver"]}
    result = {"source_conditioning": conditioning, "case": case, "checkpoint": checkpoint,
        "context_raw": context_raw, "source_request": request, "common": common}
    for name, prefix, budget, origin in (
        ("bos", [1], 3, "bos_seed"),
        ("exposed_eos", material["ids"][:-1], 1, "target_derived_label")):
        options = {**common, "max_new_tokens": budget, "prefix_origin": origin}
        report = generation.generate_compact_content_v1(checkpoint, conditioning["conditioning"],
            prefix, context_raw, **{key: options[key] for key in (
                "expected_checkpoint_sha256", "expected_context_sha256", "max_new_tokens", "prefix_origin", "context_origin")})
        args = (report, checkpoint, prefix, context_raw, case["population_raw"], request, native["receipt_ref"])
        bind_options = {**options, "expected_generation_sha256": digest(report)}
        outer = subject.bind_compact_content_generation_to_source_v1(*args, **bind_options)
        result[name] = {"args": args, "options": bind_options, "generation": report, "outer": outer}
    return result


def validate_outer(entry, report=None, **changes):
    report = entry["outer"] if report is None else report
    return subject.validate_compact_content_generation_source_binding_v1(report, *entry["args"],
        **{**entry["options"], "expected_report_sha256": digest(report), **changes})


def test_fresh_actual_producer_receipt_and_exact_source_conditioning(native):
    report = prepare(native)
    payload = native["receipt"].to_dict()
    row = payload["results"][0]
    assert report["schema"] == "legal-compact-source-conditioning/v1"
    assert report["profile"] == "exact-native-gte-small384-receipt-reuse/v1"
    assert report["status"] == "embedded"
    assert report["source_request_sha256"] == digest(native["requests"][0])
    assert subject.compact_source_request_sha256(native["requests"][0]) == digest(native["requests"][0])
    assert report["input"] == native["requests"][0]["input"]
    assert report["source_span"] == native["requests"][0]["input"]["source"]
    assert report["source_sha256"] == sha(native["inputs"][0].text.encode("utf-8"))
    assert report["receipt"] == native["receipt_ref"]
    assert report["receipt_input_index"] == 0 and report["receipt_input_count"] == 4
    assert report["receipt_status_counts"] == payload["status_counts"]
    assert report["tokens"] == row["tokens"] and report["tokens_record_sha256"] == digest(row["tokens"])
    assert report["native_vector"] == row["vector"]
    bits = bytes.fromhex(row["vector"]["bits"])
    assert report["native_vector_bits_sha256"] == sha(bits)
    assert len(report["conditioning"]) == 384
    assert b"".join(struct.pack(">f", value) for value in report["conditioning"]) == bits
    assert report["conditioning_sha256"] == digest(report["conditioning"])
    assert report["source_bytes_verified"] is report["source_receipt_binding_verified"] is True
    assert report["native_execution_record_present"] is True
    assert report["encoder_executed_by_adapter"] is False
    assert report["encoder_binding_sha256"] == digest(report["encoder_binding"])
    assert subject.compact_source_binding_sha256(report) == digest(report)
    no_authority(report)


def test_equal_text_at_two_physical_origins_keeps_distinct_exact_inputs(native):
    first, second = prepare(native, index=1), prepare(native, index=2)
    assert first["source_sha256"] == second["source_sha256"]
    assert first["source_span"] != second["source_span"]
    assert first["input_id"] != second["input_id"]
    assert first["receipt_input_index"] == 1 and second["receipt_input_index"] == 2
    assert first["input"] == native["requests"][1]["input"]
    assert second["input"] == native["requests"][2]["input"]
    # Deterministic equal-text embeddings need not differ; origin IDs still do.
    assert first["conditioning"] == second["conditioning"]


def test_actual_oversized_source_retains_disposition_without_zero_vector(native):
    report = prepare(native, index=3)
    assert report["status"] == "token_limit_exceeded"
    assert report["receipt_input_index"] == 3 and report["receipt_input_count"] == 4
    assert report["receipt_status_counts"] == {"embedded": 3, "token_limit_exceeded": 1, "missing_input": 0}
    assert report["tokens"]["token_count"] > 512
    assert report["conditioning"] is report["conditioning_sha256"] is None
    assert report["native_vector"] is report["native_vector_bits_sha256"] is None
    assert report["source_receipt_binding_verified"] is False
    no_authority(report)


def test_independent_source_request_pin_refuses_before_receipt_loading(native, monkeypatch):
    monkeypatch.setattr(codec, "load_embedding_production_receipt",
        lambda *args, **kwargs: pytest.fail("receipt loaded before independent source request pin"))
    with pytest.raises(ValueError):
        prepare(native, expected_source_request_sha256="0" * 64)


@pytest.mark.parametrize("damage", ["argument_input_id", "request_input_id", "physical_origin", "source_text", "extra"])
def test_original_input_and_complete_physical_origin_cannot_be_substituted(native, damage):
    request = deepcopy(native["requests"][1])
    if damage == "argument_input_id":
        with pytest.raises(ValueError):
            prepare(native, index=1, input_id=native["requests"][2]["input"]["input_id"])
        return
    if damage == "request_input_id":
        request["input"]["input_id"] = native["requests"][2]["input"]["input_id"]
    elif damage == "extra":
        request["target"] = "must never enter source-only request"
    else:
        item = deepcopy(request["input"])
        if damage == "physical_origin":
            item["source"]["document_id"] += ":other-physical-origin"
        else:
            item["text"] += " Additional condition."
        request["input"] = codec.EmbeddingInput(SourceSpan.from_dict(item["source"]),
            item["title"], item["section"], item["text"], item["citation"]).to_dict()
    with pytest.raises(ValueError):
        prepare(native, request=request)


@pytest.mark.parametrize("field", ["sha256", "bytes"])
def test_receipt_reference_is_independent_and_exact(native, field):
    bad = deepcopy(native["receipt_ref"])
    bad[field] = "0" * 64 if field == "sha256" else bad[field] + 1
    with pytest.raises(ValueError):
        prepare(native, receipt_ref=bad)


@pytest.mark.parametrize("damage", ["injected_fixture", "producer", "assets", "profile", "tokens"])
def test_corrupted_actual_receipt_cannot_upgrade_or_replace_native_evidence(native, tmp_path, damage):
    # These are explicitly corrupted controls derived from an authentic output,
    # never relabelled fixture positives or runtime-computation attestations.
    payload = native["receipt"].to_dict()
    if damage == "injected_fixture":
        payload["execution"]["kind"] = "injected_fixture"
        payload["results"][0].update(status="missing_input", tokens=None, vector=None)
        payload["status_counts"] = {"embedded": 2, "token_limit_exceeded": 1, "missing_input": 1}
    elif damage == "producer": payload["producer"]["code_sha256"] = "0" * 64
    elif damage == "assets": payload["model_assets"][0]["sha256"] = "0" * 64
    elif damage == "profile": payload["execution"]["device"] = "cuda"
    else: payload["results"][0]["tokens"]["attention_mask"][0] = True
    path = tmp_path / "explicit-corrupted-native-receipt.json"
    path.write_bytes(receipt_wire(payload))
    with pytest.raises(ValueError):
        prepare(native, receipt_ref=reference(path))


def test_exact_source_artifact_bytes_are_rechecked(native, tmp_path):
    path = tmp_path / "wrong-source-bytes"
    path.write_bytes(b"This is not the pinned U.S. Code artifact.")
    with pytest.raises(ValueError):
        prepare(native, source_resolver=lambda value: path)


def test_mutable_runtime_asset_manifest_cannot_replace_fixed_profile(native, monkeypatch):
    changed = deepcopy(runtime._PINNED_ASSETS)
    name = next(iter(changed))
    changed[name] = (changed[name][0], "0" * 64)
    monkeypatch.setattr(runtime, "_PINNED_ASSETS", changed)
    with pytest.raises(ValueError):
        prepare(native)


def test_source_resolver_cannot_change_original_request_during_verification(native):
    request = deepcopy(native["requests"][0])
    calls = []
    def mutating_resolver(value):
        calls.append(deepcopy(value))
        request["occurrence_id"] = "changed-during-real-source-verification"
        return native["resolver"](value)
    with pytest.raises(ValueError):
        prepare(native, request=request, source_resolver=mutating_resolver)
    assert calls


def test_serialized_counterfactual_missing_retains_nulls_without_selected_source_access(native, tmp_path):
    # Deliberately change a serialized claim to exercise the unavailable branch.
    # The actual native producer returned embedded here; this counterfactual is
    # not a native inference result, positive model evidence or trusted receipt.
    payload = native["receipt"].to_dict()
    payload["results"][0].update(status="missing_input", tokens=None, vector=None)
    payload["status_counts"] = {"embedded": 2, "token_limit_exceeded": 1, "missing_input": 1}
    path = tmp_path / "serialized-counterfactual-missing-receipt.json"
    path.write_bytes(receipt_wire(payload))
    selected_artifact = native["requests"][0]["input"]["source"]["artifact"]
    resolved = []
    def resolver(value):
        assert value != selected_artifact, "counterfactual missing origin must not be accessed"
        resolved.append(deepcopy(value))
        return native["resolver"](value)
    report = prepare(native, receipt_ref=reference(path), source_resolver=resolver)
    assert resolved
    assert report["status"] == "missing_input"
    assert report["receipt_status_counts"] == payload["status_counts"]
    assert report["conditioning"] is report["conditioning_sha256"] is None
    assert report["tokens"] is report["native_vector"] is report["native_vector_bits_sha256"] is None
    assert report["source_bytes_verified"] is report["source_receipt_binding_verified"] is False
    no_authority(report)
    control = {"schema": "legal-compact-source-binding-serialized-counterfactual-control/v1",
        "serialized_counterfactual": True, "native_producer_emitted_this_disposition": False,
        "positive_native_inference_evidence": False, "actual_native_disposition": "embedded",
        "claimed_counterfactual_disposition": "missing_input", "report": report}
    (tmp_path / "serialized-counterfactual-not-native-inference-evidence.json").write_bytes(wire(control))


def test_generation_conditioning_cannot_be_resealed_away_from_selected_native_bits(bound_cases):
    entry = bound_cases["bos"]
    changed = deepcopy(entry["generation"])
    changed["conditioning"][0] += .125
    changed["conditioning_sha256"] = digest(changed["conditioning"])
    args = (changed, *entry["args"][1:])
    with pytest.raises(ValueError):
        subject.bind_compact_content_generation_to_source_v1(*args,
            **{**entry["options"], "expected_generation_sha256": digest(changed)})


def test_bos_source_binding_reuses_complete_unchanged_trace_and_stays_unqualified(bound_cases):
    entry = bound_cases["bos"]
    outer, report = entry["outer"], entry["generation"]
    assert outer["schema"] == "legal-compact-content-generation-source-binding/v1"
    assert outer["profile"] == "exact-source-receipt-to-compact-generation/v1"
    assert outer["status"] == "source_receipt_bound_unqualified_generation"
    assert outer["source_conditioning"] == bound_cases["source_conditioning"]
    assert outer["source_conditioning_sha256"] == digest(bound_cases["source_conditioning"])
    assert outer["generation_report"] == report
    assert outer["generation_report_sha256"] == digest(report)
    assert report["status"] == "step_budget_exhausted"
    assert report["initial_prefix_ids"] == [1] and report["emitted_token_count"] == 3
    assert report["numerical_forward_count"] == 3 and report["model_executed"] is True
    assert outer["exposure"] == report["exposure"]
    assert outer["exposure"]["teacher_forcing"] is False
    assert outer["exposure"]["target_access"] is True
    assert outer["exposure"]["encoder_sha256"] is None
    assert outer["population_sha256"] == sha(bound_cases["case"]["population_raw"])
    assert outer["population_row"]["source_sha256"] == outer["source_conditioning"]["source_sha256"]
    assert subject.compact_source_binding_sha256(outer) == digest(outer)
    assert validate_outer(entry) == outer
    no_authority(outer)


def evaluate(bound_cases, entry):
    case = bound_cases["case"]
    predictions_raw = wire(entry["outer"]["batch_adapter"]["predictions"])
    references_raw = fixtures.fixtures.transport(case["references"])
    return batch.prepare_relational_content_token_batch_evaluation_v1(case["population_raw"],
        references_raw, predictions_raw, expected_population_sha256=sha(case["population_raw"]),
        expected_references_sha256=sha(references_raw), expected_predictions_sha256=sha(predictions_raw))


def test_assisted_eos_completion_keeps_full_population_and_encoder_null_no_credit(bound_cases):
    entry = bound_cases["exposed_eos"]
    outer, report = entry["outer"], entry["generation"]
    assert report["status"] == "complete" and report["selected_token_ids"] == [2]
    assert report["emitted_token_count"] == report["numerical_forward_count"] == 1
    assert report["final_decoding"]["status"] == "valid_candidate"
    assert outer["exposure"]["teacher_forcing"] is outer["exposure"]["target_access"] is True
    declared = outer["batch_adapter"]["predictions"]["generation"]
    assert declared["kind"] == "decoder_declared" and declared["latent_dimension"] == 384
    assert declared["encoder_sha256"] is None
    assert declared["checkpoint_sha256"] == digest(bound_cases["checkpoint"])
    result = evaluate(bound_cases, entry)
    ids = [row["id"] for row in bound_cases["case"]["population"]["rows"]]
    assert result["population"]["ordered_ids"] == ids and len(ids) == 5
    assert result["coverage"]["missing_ids"] == ids[1:]
    assert sum(result["terminal_counts"].values()) == 5
    assert result["terminal_counts"]["unverifiable_generation"] == 1
    assert result["terminal_counts"]["missing"] == 4
    assert result["terminal_counts"]["compared"] == 0
    assert result["valid_typed_output"]["count"] == 0
    assert "generation_decoder_encoder_invalid" in result["generation_issues"]
    assert result["observation_ledger"][0]["content_decoding"] == report["final_decoding"]
    assert all(value is False for value in result["authority"].values())
    assert result["training_mask"] == result["evaluation_gold_mask"] == 0
    no_authority(outer)


@pytest.mark.parametrize("damage", ["occurrence", "conditioning", "native_bits", "encoder", "trace", "authority"])
def test_resealed_outer_report_must_replay_against_all_originals(bound_cases, damage):
    entry = bound_cases["bos"]
    changed = deepcopy(entry["outer"])
    if damage == "occurrence": changed["occurrence_id"] += ":other"
    elif damage == "conditioning":
        changed["source_conditioning"]["conditioning"][0] += .125
        changed["source_conditioning"]["conditioning_sha256"] = digest(changed["source_conditioning"]["conditioning"])
        changed["source_conditioning_sha256"] = digest(changed["source_conditioning"])
    elif damage == "native_bits":
        vector = changed["source_conditioning"]["native_vector"]
        corrupted = bytearray.fromhex(vector["bits"])
        corrupted[0] ^= 0x80
        vector["bits"] = corrupted.hex()
        changed["source_conditioning"]["native_vector_bits_sha256"] = sha(bytes.fromhex(vector["bits"]))
        changed["source_conditioning_sha256"] = digest(changed["source_conditioning"])
    elif damage == "encoder":
        changed["batch_adapter"]["predictions"]["generation"]["encoder_sha256"] = "0" * 64
    elif damage == "trace":
        changed["generation_report"]["trace"][0]["logits"][0] += .125
        changed["generation_report_sha256"] = digest(changed["generation_report"])
    else:
        key = next(iter(changed["authority"]))
        changed["authority"][key] = True
    with pytest.raises(ValueError):
        validate_outer(entry, changed)


def test_independent_outer_report_pin_refuses_before_numerical_replay(bound_cases, monkeypatch):
    monkeypatch.setattr(generation, "validate_compact_content_generation_v1",
        lambda *args, **kwargs: pytest.fail("generation replay before independent outer report hash"))
    with pytest.raises(ValueError):
        validate_outer(bound_cases["bos"], expected_report_sha256="0" * 64)


def test_unavailable_native_source_cannot_bind_a_generated_prediction(native, bound_cases):
    entry = bound_cases["bos"]
    request = native["requests"][3]
    args = (*entry["args"][:5], request, native["receipt_ref"])
    with pytest.raises(ValueError):
        subject.bind_compact_content_generation_to_source_v1(*args, **{**entry["options"],
            "expected_source_request_sha256": digest(request), "input_id": request["input"]["input_id"],
            "occurrence_id": request["occurrence_id"]})


def test_returned_source_metadata_and_vectors_are_detached(native):
    report = prepare(native)
    original = deepcopy(report)
    report["input"]["source"]["document_id"] += ":mutated-result"
    report["conditioning"][0] += 1.
    report["receipt_status_counts"]["embedded"] = 99
    assert prepare(native) == original
    assert native["requests"][0]["input"]["source"]["document_id"] == original["input"]["source"]["document_id"]


def test_persist_actual_native_source_and_generation_evidence(native, bound_cases):
    entry = bound_cases["exposed_eos"]
    evaluation = evaluate(bound_cases, entry)
    evidence = {"schema": "legal-compact-source-binding-generation-evidence/v1",
        "input_fixture": native["fixture_ref"], "source_artifacts": native["artifacts"],
        "source_requests": native["requests"], "native_receipt": native["receipt_ref"],
        "native_receipt_status_counts": native["receipt"].status_counts,
        "prepared_sources": [prepare(native, index=index) for index in range(4)],
        "checkpoint": bound_cases["checkpoint"], "context_utf8": bound_cases["context_raw"].decode("utf-8"),
        "population_utf8": bound_cases["case"]["population_raw"].decode("utf-8"),
        "references_utf8": fixtures.fixtures.transport(bound_cases["case"]["references"]).decode("utf-8"),
        "generation_runs": {name: {"prefix_ids": data["args"][2],
            "options": {key: value for key, value in data["options"].items() if key != "source_resolver"},
            "generation": data["generation"], "source_binding": data["outer"]}
            for name, data in bound_cases.items() if name in ("bos", "exposed_eos")},
        "exposed_batch_evaluation": evaluation,
        "actual_native_producer_call_count": 1, "encoder_inference_executed_by_fixture": True,
        "compact_model_executed": True, "model_executed": True,
        "training_executed": False, "compact_optimizer_executed": False,
        "compact_training_steps": 0, "source_encoder_authenticated": False,
        "runtime_cryptographically_attested": False, "source_equivalence_proven": False,
        "context_origin": "target_derived_label", "assisted_completion": True,
        "legal_or_held_out_accuracy_claimed": False, "convergence_proven": False}
    raw = wire(evidence)
    assert 0 < len(raw) <= 16 * 1024 * 1024
    path = native["directory"] / "source-binding-generation-evidence.json"
    path.write_bytes(raw)
    assert path.read_bytes() == raw
