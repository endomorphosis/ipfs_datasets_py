"""Inert occurrence and call-boundary tests; all model/native admissions are doubles.

Real cache/source contracts and retained row validation run here. No encoder,
tensor library, optimizer, training or genuine model inference runs. The fake
equivalence digest is enabled only by monkeypatch, never by the public API.
"""
from contextlib import nullcontext
from copy import deepcopy
import builtins
import hashlib
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import arbitrary_native_span_runtime as runtime
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_continuation as continuation

CONTEXT = {"dimension": 384, "representation_id": "actual_frozen_legal_ir/raw384/v1",
    "producer_sha256": "0e8a4bff65241bd9f7cfa4fd6200cbf1216d836d4687418d25d1c79d9b3ca12d",
    "training_index_sha256": "739964281f8eb516ca7849da422d44428d9ce09a3f2b64df2c34da2d26d6949f"}
MODEL = {"dimension": 384, "model_id": "thenlper/gte-small",
    "revision": "17e1f347d17fe144873b1201da91788898c639cd"}
EXECUTION = {"backend": "sentence-transformers", "cpu_threads": 1, "device": "cpu",
    "dtype": "float32", "eval_mode": True, "gradient_mode": "inference_mode", "kind": "native",
    "max_tokens": 512, "normalization": "l2", "pooling": "mean", "seed": 0, "truncation": False}
VERSIONS = {"python": "3.12.3", "sentence_transformers": "5.4.1", "tokenizers": "0.21.4",
    "torch": "2.13.0+cu130", "transformers": "4.52.1"}
OLD_ENCODER = "27855f5ffd59ebc45444d5e37c18ff1569618084cd27b1503db112940051ffb0"
NEW_ENCODER = "ce80ed6294009e04580051e6eb06a817d74a8a56f04814ad0a698e3d27dd0d41"
ASSETS = [{"diagnostic_double": True}]


def pin(path):
    raw = path.read_bytes()
    return {"path": str(path.resolve()), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def write(path, value):
    path.write_bytes(runtime._ascii(value))
    return pin(path)


def test_concrete_constants_match_independent_literals_and_reviewed_receipt():
    assert runtime.HISTORICAL_CONTEXT == CONTEXT
    assert len(CONTEXT["training_index_sha256"]) == 64
    assert runtime.MODEL == MODEL and runtime.EXECUTION == EXECUTION
    assert runtime.OLD_ENCODER_SHA256 == OLD_ENCODER and runtime.NEW_ENCODER_SHA256 == NEW_ENCODER
    assert runtime.ASSETS_SHA256 == "def8d7e04c05560b1d0dd1fa9317be7a59a1ba8399ca725be0ac807a9a264edc"
    # Optional retained review is a local artifact, not a network dependency.
    review = Path(__file__).resolve().parents[6] / "raw384-equivalence.json"
    if review.is_file():
        reference = pin(review)
        assert reference["sha256"] == runtime.EQUIVALENCE_SHA256 and reference["bytes"] == runtime.EQUIVALENCE_BYTES
        value = json.loads(review.read_bytes())
        assert value["historical_context_contract"] == runtime.HISTORICAL_CONTEXT
        assert value["model"] == runtime.MODEL and value["execution_common"] == runtime.EXECUTION
        assert value["model_assets_sha256"] == runtime.ASSETS_SHA256
        assert value["historical_encoder_code_sha256"] == runtime.OLD_ENCODER_SHA256
        assert value["current_encoder_code_sha256"] == runtime.NEW_ENCODER_SHA256


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    texts = ["État must archive records.", "Every officer must preserve records.", "État must archive records."]
    prefix = "Préface\n"
    full = prefix + "\n\n".join(texts)
    document = tmp_path / "document.txt"
    document.write_bytes(full.encode())
    document_pin = pin(document)
    offset = len(prefix.encode())
    requests = []
    for index, text in enumerate(texts):
        requests.append({"id": str(index), "source_text": text, "source": {
            "artifact": {"sha256": document_pin["sha256"], "bytes": document_pin["bytes"]},
            "source_kind": "diagnostic", "release_id": "diagnostic-v1", "document_id": "document",
            "language": "en", "citation": "diagnostic statute", "byte_start": offset,
            "byte_end": offset+len(text.encode()), "normalization": "identity"}})
        offset += len(text.encode())+2
    requests_pin = write(tmp_path / "requests.json", requests)
    receipt_pin = write(tmp_path / "native.json", {"diagnostic_double": True, "model": MODEL,
        "execution": {**EXECUTION, "batch_size": 4}, "model_assets": ASSETS,
        "producer": {"code_sha256": NEW_ENCODER, "runtime_versions": VERSIONS}})
    index = {}
    for position, request in enumerate(requests):
        vector = [0.] * 384
        vector[position] = 1.
        record = {"vector": vector, "tokens": {"input_ids": [0, 20, 2], "attention_mask": [1, 1, 1],
            "token_type_ids": None}, "receipt": receipt_pin, "input_id": "diagnostic-native-double",
            "producer_source_span_present": True, "producer_evidence": {"diagnostic_double": True}}
        index[(request["source_text"], runtime.cache_owner.digest(request["source"]))] = [record]
    monkeypatch.setattr(runtime.cache_owner, "_native384_records", lambda refs, resolver: deepcopy(index))
    cache = runtime.cache_owner.plan_arbitrary_native_source_cache(requests, dimension=384,
        native384_receipt_refs=[receipt_pin], source_resolver=lambda artifact: document)
    cache_pin = write(tmp_path / "cache.json", cache)
    owners = {name: pin(Path(path)) for name, path in runtime.source_owner_paths().items()}
    prefix_name = "ipfs_datasets_py.optimizers.logic_theorem_optimizer."
    implementation = {key: owners[name]["sha256"] for key, name in (
        ("span", prefix_name+"legal_span_formula"), ("codec", prefix_name+"legal_formula_codec"),
        ("canonical", "ipfs_datasets_py.logic.legal_ir.canonical_contracts"),
        ("grammar", prefix_name+"legal_ir_grammar_decoder"))}
    flags = dict(runtime.span_boundary._NATIVE_FALSE)
    config = {"diagnostic_double": True, "latent_dimension": 384, "latent_enabled": True}
    parent = {"schema": "span-legal-formula-checkpoint/v1", "lineage_id": "source_span_formula_v1",
        "config": config, "implementation": implementation, "training_manifest_sha256": "1"*64,
        "training_count": 1, "tuning_manifest_sha256": "2"*64, "tuning_count": 1,
        "model_state": {"diagnostic_weight": [1.]}, "optimizer_state": {"diagnostic_double": True},
        "progress": {"optimizer_steps": 800}, "parent_checkpoint_sha256": None, **flags}
    raw_checkpoint = {"schema": "warm-start-span-legal-formula-checkpoint/v1",
        "lineage_id": "warm_start_source_span_formula_v1", "initialization": deepcopy(continuation._INITIALIZATION),
        "implementation": {"continuation_sha256": owners[prefix_name+"legal_span_continuation"]["sha256"],
            "base_span": implementation}, "source_parent_checkpoint": parent,
        "source_parent_checkpoint_sha256": runtime._digest(parent), "source_parent_optimizer_steps": 800,
        "initial_model_state_sha256": runtime._digest(parent["model_state"]), "initial_base_checkpoint_sha256": "3"*64,
        "context_contract": CONTEXT, "context_contract_sha256": runtime._digest(CONTEXT),
        "base_checkpoint": deepcopy(parent), "parent_checkpoint_sha256": None, **flags}
    raw_pin = write(tmp_path / "raw-checkpoint.json", raw_checkpoint)
    disabled_checkpoint = deepcopy(raw_checkpoint)
    disabled_checkpoint["base_checkpoint"]["config"]["latent_enabled"] = False
    disabled_pin = write(tmp_path / "disabled-checkpoint.json", disabled_checkpoint)
    recipes = {reference["path"]: reference for reference in (raw_pin, disabled_pin)}
    for number in range(11):
        reference = write(tmp_path / ("recipe-"+str(number)+".json"), {"diagnostic_double": number})
        recipes[reference["path"]] = reference
    review = {"schema": "raw-gte384-retained-span-equivalence/v1", "historical_context_contract": CONTEXT,
        "model": MODEL, "model_assets_sha256": runtime._digest(ASSETS), "execution_common": EXECUTION,
        "historical_encoder_code_sha256": OLD_ENCODER, "current_encoder_code_sha256": NEW_ENCODER,
        "historical_batch_size": 16, "current_receipt_batch_size": 4,
        "cryptographic_execution_attestation": False, "numerical_execution_performed": False,
        "source_semantics_verified": False, "historical_recipe_evidence": recipes,
        "raw384_checkpoint_pin": raw_pin, "source_only_checkpoint_pin": disabled_pin,
        "historical_parent_base_checkpoint_sha256": runtime._digest(parent), "raw384_model_config": config,
        "runtime_versions": VERSIONS}
    review_pin = write(tmp_path / "equivalence.json", review)
    monkeypatch.setattr(runtime, "EQUIVALENCE_SHA256", review_pin["sha256"])
    monkeypatch.setattr(runtime, "EQUIVALENCE_BYTES", review_pin["bytes"])
    monkeypatch.setattr(runtime, "ASSETS_SHA256", runtime._digest(ASSETS))
    options = {"checkpoint_pin": raw_pin, "source_cache_pin": cache_pin, "source_requests_pin": requests_pin,
        "native384_receipt_refs": [receipt_pin], "source_artifact_pins": {document_pin["sha256"]: document_pin},
        "raw384_equivalence_pin": review_pin, "source_owner_pins": owners, "row_ids": ["0", "1", "2"]}
    return SimpleNamespace(options=options, requests=requests, index=index, cache=cache, review=review,
        raw_checkpoint=raw_checkpoint, disabled_pin=disabled_pin, monkeypatch=monkeypatch, tmp_path=tmp_path)


def prepare(fixture, **changes):
    return runtime.prepare_arbitrary_native_span_runtime(**{**fixture.options, **changes})


def reseal_review(fixture):
    reference = write(Path(fixture.options["raw384_equivalence_pin"]["path"]), fixture.review)
    fixture.options["raw384_equivalence_pin"] = reference
    fixture.monkeypatch.setattr(runtime, "EQUIVALENCE_SHA256", reference["sha256"])
    fixture.monkeypatch.setattr(runtime, "EQUIVALENCE_BYTES", reference["bytes"])


def test_preparation_is_inert_and_keeps_unicode_physical_occurrences(fixture, monkeypatch):
    original = builtins.__import__
    def fenced(name, *args, **kwargs):
        if name.split(".")[0] in {"torch", "transformers", "tensorflow", "sentence_transformers"}:
            raise AssertionError("unexpected numerical import")
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", fenced)
    monkeypatch.setattr(continuation, "SpanContinuationDecoder", lambda *args: pytest.fail("unexpected constructor"))
    plan = prepare(fixture)
    assert plan["input_count"] == 3 and plan["eligible_count"] == 2
    assert plan["submitted_positions"] == [0, 2]
    first, _, last = plan["rows"]
    assert first["source_sha256"] == last["source_sha256"]
    assert first["source"] != last["source"] and first["id"] != last["id"]
    assert first["source"]["byte_start"] == len("Préface\n".encode())
    assert first["original_latent_sha256"] != last["original_latent_sha256"]
    assert first["original_latent_sha256"] == first["effective_latent_sha256"]
    assert plan["paragraph_vectors_only"] and not plan["cached_clause_vectors_used"]
    assert all(value is False for value in plan["authority"].values())
    assert plan["historical_batch_size"] == 16 and plan["current_recorded_batch_size"] == 4
    assert not plan["model_load_performed"] and not plan["checkpoint_numeric_geometry_validated"]


def test_rotation_is_joined_before_filtering_and_retains_exact_donor_occurrence(fixture):
    plan = prepare(fixture, row_ids=["2", "1", "0"], control="rotate")
    assert plan["submitted_positions"] == [0, 2]
    assert [row["latent_donor_id"] for row in plan["rows"]] == ["1", "0", "2"]
    assert [row["latent_donor_position"] for row in plan["rows"]] == [1, 2, 0]
    assert plan["rows"][0]["latent_donor_source"] == fixture.requests[1]["source"]
    assert plan["rows"][0]["effective_latent_sha256"] == runtime._digest(fixture.index[
        (fixture.requests[1]["source_text"], runtime.cache_owner.digest(fixture.requests[1]["source"]))][0]["vector"])


@pytest.mark.parametrize("control", ["none", "zero", "disabled", "rotate"])
def test_explicit_controls_and_disabled_source_only_lane(fixture, control):
    plan = prepare(fixture, control=control)
    assert all(row["latent_input_enabled"] is (control != "disabled") for row in plan["rows"])
    assert plan["owner_control"] == ("disabled" if control == "disabled" else "none")
    if control == "zero":
        assert all(row["effective_latent_sha256"] == runtime._digest([0.]*384) for row in plan["rows"])
    source_only = prepare(fixture, checkpoint_pin=fixture.disabled_pin, control=control)
    assert not source_only["checkpoint_metadata"]["latent_enabled"]
    assert all(row["latent_input_enabled"] is False for row in source_only["rows"])


@pytest.mark.parametrize("change", ["unknown_target", "missing_owner", "wrong_owner", "duplicate_id", "missing_id",
    "bad_control", "single_rotate", "aliased_source", "extra_pin_field", "unapproved_review"])
def test_closed_public_inputs_refuse(fixture, change):
    options = deepcopy(fixture.options)
    if change == "unknown_target": options["targets"] = ["gold"]
    elif change == "missing_owner": options["source_owner_pins"].pop(next(iter(options["source_owner_pins"])))
    elif change == "wrong_owner": options["source_owner_pins"][runtime.__name__] = options["source_cache_pin"]
    elif change == "duplicate_id": options["row_ids"] = ["0", "0"]
    elif change == "missing_id": options["row_ids"] = ["missing"]
    elif change == "bad_control": options["control"] = "trained384"
    elif change == "single_rotate": options.update(row_ids=["0"], control="rotate")
    elif change == "extra_pin_field": options["checkpoint_pin"]["target"] = "gold"
    elif change == "unapproved_review":
        options["raw384_equivalence_pin"] = write(fixture.tmp_path/"unapproved.json", {"passed": True})
    else:
        original = next(iter(options["source_artifact_pins"].values()))
        link = fixture.tmp_path/"alias"; link.symlink_to(original["path"])
        options["source_artifact_pins"][original["sha256"]]["path"] = str(link)
    with pytest.raises((ValueError, TypeError)):
        runtime.prepare_arbitrary_native_span_runtime(**options)


@pytest.mark.parametrize("field,value", [("representation_id", "actual_frozen_legal_ir/trained384/v1"),
    ("dimension", 768), ("training_index_sha256", "0"*64), ("producer_sha256", "0"*64)])
def test_resealed_review_cannot_relabel_raw384(fixture, field, value):
    fixture.review["historical_context_contract"] = {**CONTEXT, field: value}
    reseal_review(fixture)
    with pytest.raises(ValueError, match="concrete encoder recipe"):
        prepare(fixture)


@pytest.mark.parametrize("field,value", [("pooling", "cls"), ("normalization", "none"), ("dtype", "float16"),
    ("max_tokens", 8192), ("device", "cuda"), ("truncation", True)])
def test_resealed_unsupported_recipe_is_refused(fixture, field, value):
    fixture.review["execution_common"] = {**EXECUTION, field: value}
    reseal_review(fixture)
    with pytest.raises(ValueError, match="concrete encoder recipe"):
        prepare(fixture)


@pytest.mark.parametrize("section,field,value", [("model", "revision", "0"*40),
    ("model", "dimension", 768), ("execution", "batch_size", 16),
    ("execution", "pooling", "cls"), ("execution", "cpu_threads", True),
    ("execution", "seed", False), ("producer", "code_sha256", OLD_ENCODER),
    ("producer", "runtime_versions", {**VERSIONS, "torch": "different"})])
def test_actual_receipt_header_must_match_reviewed_profile(fixture, section, field, value):
    path = Path(fixture.options["native384_receipt_refs"][0]["path"])
    receipt = json.loads(path.read_bytes()); receipt[section][field] = value
    fixture.options["native384_receipt_refs"] = [write(path, receipt)]
    with pytest.raises(ValueError, match="new native receipt profile"):
        prepare(fixture)


@pytest.mark.parametrize("change", ["target", "offset", "artifact_bytes", "source_bytes"])
def test_exact_source_request_and_physical_bytes_are_checked(fixture, change):
    requests = deepcopy(fixture.requests)
    if change == "target": requests[0]["target"] = "gold"
    elif change == "offset": requests[0]["source"]["byte_start"] += 1
    elif change == "artifact_bytes": requests[0]["source"]["artifact"]["bytes"] += 1
    else: Path(next(iter(fixture.options["source_artifact_pins"].values()))["path"]).write_bytes(b"changed")
    fixture.options["source_requests_pin"] = write(Path(fixture.options["source_requests_pin"]["path"]), requests)
    with pytest.raises(ValueError): prepare(fixture)


def test_resealed_cache_vector_and_occurrence_origin_are_checked(fixture):
    fixture.cache["rows"][0]["input"] = [0.]*384
    fixture.cache["cache_sha256"] = runtime.cache_owner.digest({k:v for k,v in fixture.cache.items() if k != "cache_sha256"})
    fixture.options["source_cache_pin"] = write(Path(fixture.options["source_cache_pin"]["path"]), fixture.cache)
    with pytest.raises(ValueError): prepare(fixture)


@pytest.mark.parametrize("change", ["trained384", "width8", "target", "authority", "initialization", "step_type", "enabled_type"])
def test_resealed_checkpoint_contract_refuses_before_any_model_import(fixture, change, monkeypatch):
    checkpoint = deepcopy(fixture.raw_checkpoint)
    if change == "trained384":
        checkpoint["context_contract"]["representation_id"] = "actual_frozen_legal_ir/trained384/v1"
        checkpoint["context_contract_sha256"] = runtime._digest(checkpoint["context_contract"])
    elif change == "width8": checkpoint["base_checkpoint"]["config"]["latent_dimension"] = 8
    elif change == "target": checkpoint["target"] = "gold"
    elif change == "authority": checkpoint["qualified"] = True
    elif change == "initialization": checkpoint["initialization"]["mode"] = "from_scratch"
    elif change == "step_type": checkpoint["source_parent_optimizer_steps"] = 800.0
    else: checkpoint["base_checkpoint"]["config"]["latent_enabled"] = 1
    reference = write(Path(fixture.options["checkpoint_pin"]["path"]), checkpoint)
    fixture.options["checkpoint_pin"] = reference
    fixture.review["raw384_checkpoint_pin"] = reference
    fixture.review["historical_recipe_evidence"][reference["path"]] = reference
    reseal_review(fixture)
    monkeypatch.setattr(continuation, "SpanContinuationDecoder", lambda *args: pytest.fail("constructor reached"))
    with pytest.raises(ValueError): prepare(fixture)


def test_native768_cache_cannot_be_silently_padded_or_projected(fixture, monkeypatch):
    validator = runtime.cache_owner.validate_arbitrary_native_source_cache
    def wrong_width(*args, **kwargs):
        result = validator(*args, **kwargs)
        return {**result, "dimension": 768}
    monkeypatch.setattr(runtime.cache_owner, "validate_arbitrary_native_source_cache", wrong_width)
    with pytest.raises(ValueError, match="raw native384 cache"): prepare(fixture)


def test_foreign_namespace_swap_is_refused_before_cache_validator(fixture, monkeypatch):
    captured = runtime._capture(**fixture.options)
    replacement = ModuleType(runtime.cache_owner.__name__)
    replacement.__file__ = runtime.cache_owner.__file__
    monkeypatch.setitem(sys.modules, replacement.__name__, replacement)
    monkeypatch.setattr(runtime.cache_owner, "validate_arbitrary_native_source_cache", lambda *a, **k: pytest.fail("validator reached"))
    with pytest.raises(ValueError, match="module replaced"): runtime._prepare(captured)


def test_postvalidation_file_fence_detects_replacement(fixture, monkeypatch):
    validator = runtime.cache_owner.validate_arbitrary_native_source_cache
    def late_replace(*args, **kwargs):
        result = validator(*args, **kwargs)
        Path(fixture.options["source_cache_pin"]["path"]).write_bytes(b"{}")
        return result
    monkeypatch.setattr(runtime.cache_owner, "validate_arbitrary_native_source_cache", late_replace)
    with pytest.raises(ValueError): prepare(fixture)


def test_all_blocked_sources_open_no_model_or_tensor_library(fixture, monkeypatch):
    original = builtins.__import__
    def fenced(name, *args, **kwargs):
        if name.split(".")[0] in {"torch", "tensorflow", "transformers"}:
            raise AssertionError("unexpected tensor import")
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", fenced)
    monkeypatch.setattr(continuation, "SpanContinuationDecoder", lambda *args: pytest.fail("constructor reached"))
    handle = runtime.open_arbitrary_native_span_decoder(**{**fixture.options, "row_ids": ["1"]})
    assert handle.model is None and not handle.describe()["model_load_performed"]
    report = handle.infer_cached()
    assert report["decoder_calls"] == 0 and report["raw_owner_report"] is None
    assert not report["numerical_custody_checked"]
    assert report["weights_unchanged"] is None and report["ambient_CPU_RNG_preserved"] is None


class TensorDouble:
    def __init__(self, value): self.value = deepcopy(value)
    def detach(self): return self
    def cpu(self): return self
    def clone(self): return TensorDouble(self.value)
    def tolist(self): return deepcopy(self.value)


class ModelDouble:
    def __init__(self):
        self.training = False
        self.parameter = SimpleNamespace(grad=None, requires_grad=True)
        self.weight = [1.]
    def modules(self): return [self]
    def parameters(self): return [self.parameter]
    def state_dict(self): return {"diagnostic_weight": TensorDouble(self.weight)}


@pytest.fixture
def opened(fixture, monkeypatch):
    fake_torch = ModuleType("torch")
    fake_torch.diagnostic_double = True
    fake_torch.rng = [11]
    fake_torch.get_num_threads = lambda: 1
    fake_torch.get_rng_state = lambda: TensorDouble(fake_torch.rng)
    fake_torch.equal = lambda left, right: left.value == right.value
    fake_torch.random = SimpleNamespace(fork_rng=lambda **kwargs: nullcontext())
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    calls, instances = [], []
    class DecoderDouble:
        def __init__(self, checkpoint):
            self.checkpoint = deepcopy(checkpoint)
            self.model = ModelDouble()
            self.on_return = None
            instances.append(self)
        def decode_formal_logic(self, texts, vectors, *, latent_ablation):
            calls.append((deepcopy(texts), deepcopy(vectors), latent_ablation))
            rows = [{"source_sha256": hashlib.sha256(text.encode()).hexdigest(), "latent_sha256": runtime._digest(vector),
                "status": "abstained", "reason": "nonfinite_decoder_scores", "canonical_ir": None,
                "formal_outputs": [], "formula_text": None, "teacher_forcing": False, "target_access": False,
                "training_executed": False, "source_input_conditioned": True, "learned_formula_generation": True,
                "sample_memory_used": False, "family_syntax_checked": False,
                "latent_input_enabled": latent_ablation != "disabled" and self.checkpoint["base_checkpoint"]["config"]["latent_enabled"],
                **runtime.span_boundary._NATIVE_FALSE} for text, vector in zip(texts, vectors, strict=True)]
            report = {"schema": "warm-start-span-legal-formula-inference/v1", "lineage_id": "warm_start_source_span_formula_v1",
                "checkpoint_sha256": runtime._digest(self.checkpoint),
                "base_checkpoint_sha256": runtime._digest(self.checkpoint["base_checkpoint"]),
                "source_parent_checkpoint_sha256": self.checkpoint["source_parent_checkpoint_sha256"],
                "source_parent_optimizer_steps": self.checkpoint["source_parent_optimizer_steps"],
                "context_contract_sha256": self.checkpoint["context_contract_sha256"],
                "initialization": deepcopy(self.checkpoint["initialization"]), "rows": rows, "decoded_count": 0,
                "status": "abstained", "latent_ablation": latent_ablation, "target_access": False,
                "teacher_forcing": False, "training_executed": False, **runtime.span_boundary._NATIVE_FALSE}
            if self.on_return is not None: self.on_return(report)
            return report
    monkeypatch.setattr(continuation, "SpanContinuationDecoder", DecoderDouble)
    handle = runtime.open_arbitrary_native_span_decoder(**fixture.options)
    assert len(instances) == 1 and handle.model is instances[0].model
    return SimpleNamespace(handle=handle, decoder=instances[0], calls=calls, torch=fake_torch, fixture=fixture)


@pytest.mark.parametrize("control", ["none", "zero", "disabled", "rotate"])
def test_inference_double_preserves_abstentions_and_exact_prefilter_controls(opened, control):
    report = opened.handle.infer_cached(control=control)
    assert len(opened.calls) == 1 and len(opened.calls[0][0]) == 2
    assert [row["outcome"] for row in report["rows"]] == ["decoder_abstained", "source_blocked", "decoder_abstained"]
    assert report["raw_owner_report"]["decoded_count"] == 0
    assert report["numerical_custody_checked"] and report["weights_unchanged"] and report["ambient_CPU_RNG_preserved"]
    assert report["optimizer_steps_executed"] == 0 and all(value is False for value in report["authority"].values())
    vectors = opened.calls[0][1]
    assert opened.calls[0][2] == ("disabled" if control == "disabled" else "none")
    if control == "zero": assert all(vector == [0.]*384 for vector in vectors)
    elif control == "rotate": assert vectors[0][1] == 1. and vectors[1][0] == 1.
    else: assert vectors[0][0] == 1. and vectors[1][2] == 1.


def test_source_only_inference_cannot_enable_latent_inputs(opened):
    handle = runtime.open_arbitrary_native_span_decoder(**{**opened.fixture.options,
        "checkpoint_pin": opened.fixture.disabled_pin})
    for control in runtime.CONTROLS:
        report = handle.infer_cached(control=control)
        assert not report["checkpoint_metadata"]["latent_enabled"]
        assert all(row["latent_input_enabled"] is False for row in report["rows"])
        assert all(row["decoder_row"]["latent_input_enabled"] is False
            for row in report["rows"] if row["decoder_row"] is not None)


def test_constructor_failure_has_truthful_call_boundaries(fixture, opened, monkeypatch):
    def failing_constructor(checkpoint): raise RuntimeError("diagnostic constructor double failed")
    monkeypatch.setattr(continuation, "SpanContinuationDecoder", failing_constructor)
    with pytest.raises(runtime.SpanRuntimeError) as error:
        runtime.open_arbitrary_native_span_decoder(**fixture.options)
    assert error.value.model_load_started and not error.value.model_load_performed
    assert not error.value.model_inference_started and not error.value.model_inference_executed
    assert error.value.raw_candidate_report is None


@pytest.mark.parametrize("change", ["extra_target", "authority", "count", "status", "initialization", "parent_steps",
    "row_source", "row_vector", "row_authority", "row_target", "row_gate", "row_candidate"])
def test_returned_owner_contract_failures_retain_raw_diagnostic(opened, change):
    def mutate(report):
        if change == "extra_target": report["target"] = "gold"
        elif change == "authority": report["qualified"] = True
        elif change == "count": report["decoded_count"] = True
        elif change == "status": report["status"] = "decoded"
        elif change == "initialization": report["initialization"]["mode"] = "trained384"
        elif change == "parent_steps": report["source_parent_optimizer_steps"] = True
        elif change == "row_source": report["rows"][0]["source_sha256"] = "0"*64
        elif change == "row_vector": report["rows"][0]["latent_sha256"] = "0"*64
        elif change == "row_authority": report["rows"][0]["admitted"] = True
        elif change == "row_target": report["rows"][0]["target"] = "gold"
        elif change == "row_gate": report["rows"][0]["latent_input_enabled"] = False
        else: report["rows"][0]["canonical_ir"] = {"unvalidated": True}
    opened.decoder.on_return = mutate
    with pytest.raises(runtime.SpanRuntimeError) as error:
        opened.handle.infer_cached()
    assert error.value.model_load_performed and error.value.model_inference_started and error.value.model_inference_executed
    assert error.value.raw_candidate_report is not None
    assert len(opened.calls) == 1


@pytest.mark.parametrize("change", ["weights", "rng", "mode", "grad", "flags", "file"])
def test_late_custody_failures_preserve_returned_report(opened, change):
    def mutate(report):
        if change == "weights": opened.decoder.model.weight = [2.]
        elif change == "rng": opened.torch.rng = [12]
        elif change == "mode": opened.decoder.model.training = True
        elif change == "grad": opened.decoder.model.parameter.grad = "diagnostic-double"
        elif change == "flags": opened.decoder.model.parameter.requires_grad = False
        else: Path(opened.fixture.options["source_cache_pin"]["path"]).write_bytes(b"{}")
    opened.decoder.on_return = mutate
    with pytest.raises(runtime.SpanRuntimeError) as error: opened.handle.infer_cached()
    assert error.value.model_inference_executed and error.value.raw_candidate_report is not None


@pytest.mark.parametrize("change", ["mode", "grad", "weights"])
def test_bad_model_state_is_refused_before_decoder_call(opened, change):
    if change == "mode": opened.decoder.model.training = True
    elif change == "grad": opened.decoder.model.parameter.grad = "diagnostic-double"
    else: opened.decoder.model.weight = [2.]
    with pytest.raises(runtime.SpanRuntimeError) as error: opened.handle.infer_cached()
    assert not error.value.model_inference_started and not error.value.model_inference_executed
    assert error.value.raw_candidate_report is None and opened.calls == []
