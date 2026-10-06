"""Portable metadata fixtures and fixed inert numerical boundary observations."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import contextual_legal_ir_runtime as runtime


def pin(path):
    raw = Path(path).read_bytes()
    return {"path": str(path), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def write(path, value):
    Path(path).write_bytes(runtime._raw(value))
    return pin(path)


def zeros(shape):
    return 0. if not shape else [zeros(shape[1:]) for _ in range(shape[0])]


def receipt(value):
    value["receipt_sha256"] = runtime._digest(value)
    return value


def make_contextual(tmp_path, monkeypatch=None, dimension=384):
    """Explicit synthetic byte pins; this fixture is never a trained model."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    codec = {"schema": "typed-json-lexical/v1", "target_vocabulary": ["<pad>", "<bos>", "<eos>",
        '"F"', '"O"', '"P"', '"action"', '"actor"', '"approve"', '"archive"', '"conditions"',
        '"deliver"', '"examine"', '"exceptions"', '"modality"', '"notary"', '"notice"', '"object"',
        '"preserve"', '"publish"', '"registrar"', '"rules"', '"secretary"', '"temporal"', '"treasurer"',
        '"trustee"', ",", ":", "[", "]", "{", "}"]}
    _, donor_shapes = runtime._shapes(384)
    donor_state = {name: zeros(shape) for name, shape in donor_shapes.items()}
    donor = {"domain_id": "legal_ir", "dimension": 384, "codec": codec, "model_state": donor_state,
        "weights_sha256": runtime._digest(donor_state), "config": {"hidden_size": 32, "projection_width": 8,
        "token_embedding_dim": 16, "max_target_tokens": 512, "seed": 1729}, "qualified": False, "proof_authority": False}
    donor_pin = write(tmp_path / "donor.json", donor)
    transform = {"mode": "center_rms", "origin": "training_only", "mean": [0.]*dimension, "scale": 1.}
    norm = receipt({"schema": "training-source-normalization/v1", "dimension": dimension,
        "kind": "center_rms", "scope": "training_only_frozen_transform", "validation_rows_used_for_fitting": 0,
        "mean": [0.]*dimension, "scale": 1., "fitted_training_mean": [0.]*dimension, "fitted_training_scale": 1.,
        "training_rows_sha256": "b"*64, "qualified": False, "admitted": False, "proof_authority": False})
    prior = receipt({"schema": "training-source-count-prior/v1", "scope": "training_only_frozen_count_prior",
        "target_access": "authenticated_training_count_labels_only", "validation_rows_used_for_fitting": 0,
        "count_classes": list(range(1, 33)), "log_prior": [0.]*32,
        "training_rows_sha256": "b"*64, "qualified": False, "admitted": False, "proof_authority": False})
    shapes, raw_shapes = runtime._shapes(dimension)
    state = {name: zeros(shape) for name, shape in shapes.items()}
    state.update(head_initialization_seed=1729, ordered_clause_recurrent_version=1,
                 **{"body.source_scale": 1., "clause_source_scale": 1.})
    initializer_state = {name: zeros(shape) for name, shape in raw_shapes.items()}
    initializer = receipt({"schema": "dimension-native-raw-decoder-development/v1", "dimension": dimension,
        "projection_width": 8, "hidden_width": 32, "token_embedding_width": 16, "source_seed": 1729,
        "donor_tensor_sha256": runtime._tensor_digest(donor_state, donor_shapes),
        "initial_tensor_sha256": runtime._tensor_digest(initializer_state, raw_shapes),
        "qualified": False, "admitted": False, "proof_authority": False})
    architecture = {"schema": "ordered-clause-recurrent-source-decoder-development/v1", "dimension": dimension,
        "max_rules": 8, "vocabulary_size": 32, "codec_sha256": runtime._digest(codec),
        "normalization": norm, "clause_normalization": deepcopy(norm), "base_architecture": {"count_prior": prior},
        "qualified": False, "admitted": False, "proof_authority": False}
    source_digest = "a"*64
    checkpoint = {"schema": "private-native-dimension-source-state/v1", "dimension": dimension,
        "architecture": architecture, "codec": codec, "initializer_receipt": initializer, "input_transform": transform,
        "lineage": {"domain": "legal_ir", "teacher_codec_sha256": runtime._digest(codec),
            "teacher_checkpoint_sha256": donor_pin["sha256"], "input_provenance_sha256": source_digest, "teacher_output_limit": 512},
        "model_state": state, "weights_sha256": runtime._digest(state),
        "tensor_sha256": runtime._tensor_digest(state, shapes, integer_buffers=True),
        "recipe": {"name": "continue-lr0001", "learning_rate": .0001}, "role": "selected", "selected": True,
        **{key: False for key in runtime._STATE_FALSE}}
    preprocessing = {"dimension": dimension, "initializer": initializer, "input_transform": transform,
        "paragraph_normalization": norm, "clause_normalization": deepcopy(norm), "count_prior": prior,
        "source_inputs_sha256": source_digest, "qualified": False, "admitted": False, "proof_authority": False}
    rows, contexts = [], {}
    for index in (0, 1):
        text = f"Private legal source {index}."
        vector = [float(offset == index) for offset in range(dimension)]
        identifier = f"source:{index}"
        source_sha = hashlib.sha256(text.encode()).hexdigest()
        rows.append({"id": identifier, "source_text": text, "input": vector})
        contexts[identifier] = {"source_sha256": source_sha, "segments": [{"source_text": text,
            "source_sha256": source_sha, "embedding_sha256": runtime._digest(vector), "vector": vector,
            "char_start": 0, "char_end": len(text), "byte_start": 0, "byte_end": len(text.encode())}]}
    preprocessing["source_binding"] = {"schema": "training-source-clause-context/v1", "reference_labels_accessed": False,
        "validation": {"schema": "source-clause-context/v1", "dimension": dimension, "reference_labels_accessed": False,
            "contexts_sha256": runtime._digest(contexts), "source_inventory": [{"id": row["id"],
                "source_sha256": contexts[row["id"]]["source_sha256"]} for row in rows]}}
    data = {"dimension": dimension, "checkpoint": checkpoint, "preprocessing": preprocessing,
        "donor": donor, "rows": rows, "contexts": contexts, "root": tmp_path}
    repin(data)
    return data


def repin(data, monkeypatch=None):
    """Repin explicit private bytes after a boundary control; no allowlists bypassed."""
    data["options"] = {
        "request": {"ir_family_id": "legal_ir", "dimension": data["dimension"],
                    "dimension_role": "input_embedding", "task_id": "semantic_IR_reconstruction", "checkpoint_sha256": ""},
        "checkpoint_pin": write(data["root"] / "checkpoint.json", data["checkpoint"]),
        "preprocessing_pin": write(data["root"] / "preprocessing.json", data["preprocessing"]),
        "donor_checkpoint_pin": write(data["root"] / "donor.json", data["donor"]),
        "source_inputs_pin": write(data["root"] / "rows.json", data["rows"]),
        "source_contexts_pin": write(data["root"] / "contexts.json", data["contexts"]),
        "source_owner_pins": {name: pin(Path(runtime.__file__).with_name(name + ".py")) for name in runtime.SOURCE_OWNER_NAMES},
        "row_ids": [row["id"] for row in reversed(data["rows"])],
    }
    data["options"]["request"]["checkpoint_sha256"] = data["options"]["checkpoint_pin"]["sha256"]
    return data


def prepare(data, **changes):
    options = deepcopy(data["options"])
    options.update(changes)
    return runtime.prepare_contextual_legal_ir_runtime(**options)


def open_contextual(data, **changes):
    options = deepcopy(data["options"])
    options.update(changes)
    return runtime.open_contextual_legal_ir_autoencoder(**options)


@pytest.fixture
def data(tmp_path, monkeypatch):
    return make_contextual(tmp_path, monkeypatch)


@pytest.fixture
def loader(monkeypatch):
    from ipfs_datasets_py.logic.formalization.autoencoder import contextual_legal_ir_numeric as numeric
    controls = {"loads": [], "calls": [], "after_load": None, "after_infer": None,
                "mutate_inputs": False, "load_error": None, "infer_error": None}

    def restore(prepared):
        controls["loads"].append(deepcopy(prepared))
        if controls["after_load"] is not None:
            controls["after_load"]()
        if controls["load_error"] is not None:
            raise controls["load_error"]
        return object()

    def infer(model, source_inputs, **options):
        controls["calls"].append({"source_inputs": deepcopy(source_inputs), "options": dict(options)})
        if controls["mutate_inputs"]:
            source_inputs["rows"][0]["target_ids"] = [1, 2]
        if controls["after_infer"] is not None:
            controls["after_infer"]()
        if controls["infer_error"] is not None:
            raise controls["infer_error"]
        return {"scope": "inert boundary observation", "predictions": [{"id": row["id"], "token_ids": [2],
            "eos_reached": True, "generation_status": "eos"} for row in source_inputs["rows"]]}

    monkeypatch.setattr(numeric, "restore_contextual_legal_model", restore)
    monkeypatch.setattr(numeric, "infer_contextual_legal_model", infer)
    return controls


@pytest.mark.parametrize("dimension", [384, 768])
def test_prepare_keeps_width_and_order_and_excludes_gold(tmp_path, monkeypatch, loader, dimension):
    data = make_contextual(tmp_path, monkeypatch, dimension)
    plan = prepare(data)
    assert loader["loads"] == loader["calls"] == []
    assert plan["request"]["dimension"] == dimension
    assert plan["row_ids"] == ["source:1", "source:0"]
    assert [row["id"] for row in plan["source_inputs"]["rows"]] == plan["row_ids"]
    assert all(set(row) == {"id", "source_text", "input"} for row in plan["source_inputs"]["rows"])
    assert plan["native_ir_schema_version"] is plan["decoder_profile_id"] is plan["decoder_format_id"] is None
    assert all(value is False for value in plan["authority"].values())
    assert plan["original_targets_accessed"] is False
    plan["source_inputs"]["rows"][0]["input"][0] = 999.
    assert prepare(data)["source_inputs"]["rows"][0]["input"][0] == 0.


def test_lazy_open_restores_only_three_detached_documents_and_selected_sources(data, loader):
    runtime_instance = open_contextual(data)
    assert len(loader["loads"]) == 1 and loader["calls"] == []
    packet = loader["loads"][0]
    assert set(packet) == {"checkpoint", "preprocessing", "donor_checkpoint"}
    assert set(packet["donor_checkpoint"]) == {"codec", "config", "model_state"}
    report = runtime_instance.infer_cached()
    assert report["model_inference_executed"] is True
    assert all(value is False for value in report["authority"].values())
    call = loader["calls"][0]
    assert list(call["source_inputs"]["contexts"]) == ["source:0", "source:1"]  # JSON order is canonical.
    assert [row["id"] for row in call["source_inputs"]["rows"]] == ["source:1", "source:0"]
    assert call["options"] == {"output_cap": 512, "deadline_seconds": 120, "batch_size": 8}


@pytest.mark.parametrize("failure", ["load", "infer"])
def test_failure_records_actual_model_call_boundaries(data, loader, failure):
    loader[failure + "_error"] = RuntimeError("deliberate numerical refusal")
    with pytest.raises(runtime.ContextualLegalRuntimeError) as caught:
        instance = open_contextual(data)
        instance.infer_cached()
    error = caught.value
    assert error.model_load_started is True
    assert error.model_load_performed is (failure == "infer")
    assert error.model_inference_started is (failure == "infer")
    assert error.model_inference_executed is False


def test_owner_input_mutation_refuses_with_completed_inference_observation(data, loader):
    loader["mutate_inputs"] = True
    with pytest.raises(runtime.ContextualLegalRuntimeError) as caught:
        open_contextual(data).infer_cached()
    assert caught.value.model_inference_executed is True
    assert caught.value.raw_candidate_report is not None


@pytest.mark.parametrize("key", ["runtime_admitted", "runtime_release_qualified", "teacher_qualified", "decoder_profile_id"])
def test_nested_private_state_cannot_invent_runtime_authority_or_native_identity(data, loader, key):
    data["checkpoint"]["architecture"][key] = "invented-profile" if key == "decoder_profile_id" else True
    repin(data)
    with pytest.raises(runtime.ContextualLegalRuntimeError):
        open_contextual(data)
    assert loader["loads"] == []
