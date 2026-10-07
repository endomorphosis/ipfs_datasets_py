"""Normative selection controls with synthetic metadata and inert model calls."""
from copy import deepcopy
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import contextual_legal_ir_runtime as original
from ipfs_datasets_py.logic.formalization.autoencoder import normative_legal_ir_runtime as runtime
from .test_contextual_legal_ir_runtime import loader, make_contextual, pin, repin


def make_normative(tmp_path, dimension=384, recipe_name="normative-wording-ce"):
    data = make_contextual(tmp_path, dimension=dimension)
    data["checkpoint"]["recipe"] = deepcopy(runtime._RECIPES[recipe_name])
    return repin(data)


def options(data, recipe_name="normative-wording-ce"):
    result = deepcopy(data["options"])
    result["request"].update(decoder_contract_id=runtime.DECODER_CONTRACT_ID,
                             training_recipe_name=recipe_name)
    result["source_owner_pins"].update({name: pin(Path(runtime.__file__).with_name(name + ".py"))
        for name in ("normative_legal_ir_runtime", "ir_model_manager_import")})
    return result


@pytest.mark.parametrize("dimension", [384, 768])
@pytest.mark.parametrize("recipe_name", ["normative-wording-zero", "normative-wording-ce"])
def test_separate_selected_recipe_width_bindings_without_numerical_calls(tmp_path, loader, dimension, recipe_name):
    data = make_normative(tmp_path, dimension, recipe_name)
    plan = runtime.prepare_normative_legal_ir_runtime(**options(data, recipe_name))
    assert loader["loads"] == loader["calls"] == []
    assert plan["schema"] == runtime.SCHEMA
    assert plan["saved_training_recipe"] == data["checkpoint"]["recipe"]
    assert len(plan["source_owner_receipts"]) == 15
    selector = plan["model_manager_selector"]
    assert len(selector) == 10
    assert selector["dimension"] == dimension
    assert selector["role"] == recipe_name.replace("-", "_") + "_selected_semantic_decoder_state"
    assert selector["schema_version"] is selector["profile_id"] is selector["format_id"] is None
    assert plan["model_manager_binding_resolved"] is False
    assert all(value is False for value in plan["authority"].values())
    assert plan["input_contract"]["saved_paragraph_vector_producer_authenticated"] is False
    assert plan["row_ids"] == ["source:1", "source:0"]
    with pytest.raises(ValueError, match="selected recipe"):
        original.prepare_contextual_legal_ir_runtime(**data["options"])


def test_open_and_repeat_inference_preserve_recipe_and_only_pass_detached_source_inputs(tmp_path, loader):
    data = make_normative(tmp_path)
    original_bytes = Path(data["options"]["checkpoint_pin"]["path"]).read_bytes()
    handle = runtime.open_normative_legal_ir_autoencoder(**options(data))
    assert len(loader["loads"]) == 1 and not loader["calls"]
    packet = loader["loads"][0]
    assert packet["checkpoint"]["recipe"] == {"name": "normative-wording-ce", "weight": 0.05}
    assert set(packet) == {"checkpoint", "preprocessing", "donor_checkpoint"}
    for _ in range(2):
        report = handle.infer_cached()
        assert report["schema"] == "normative-legal-ir-cached-inference/v1"
        assert report["runtime_selection"]["decoder_contract_id"] == runtime.DECODER_CONTRACT_ID
        assert report["model_inference_executed"] is True
        assert report["original_targets_accessed"] is False
        assert all(value is False for value in report["authority"].values())
    assert [row["id"] for row in loader["calls"][0]["source_inputs"]["rows"]] == ["source:1", "source:0"]
    assert all(set(row) == {"id", "source_text", "input"}
               for row in loader["calls"][0]["source_inputs"]["rows"])
    assert Path(data["options"]["checkpoint_pin"]["path"]).read_bytes() == original_bytes


@pytest.mark.parametrize("recipe", [
    {"name": "normative-wording-ce", "weight": 0.025},
    {"name": "normative-wording-ce", "weight": False},
    {"name": "normative-wording-ce", "weight": 0.05, "extra": None},
    {"name": "normative-wording-zero", "weight": 0},
    {"name": "normative-wording-zero", "weight": False},
    {"name": "continue-lr0001", "learning_rate": 0.0001},
])
def test_wrong_recipe_weight_type_or_extra_fields_never_load(tmp_path, loader, recipe):
    name = "normative-wording-zero" if recipe.get("name") == "normative-wording-zero" else "normative-wording-ce"
    data = make_normative(tmp_path, recipe_name=name)
    data["checkpoint"]["recipe"] = recipe
    repin(data)
    with pytest.raises(ValueError, match="selected recipe"):
        runtime.open_normative_legal_ir_autoencoder(**options(data, name))
    assert loader["loads"] == loader["calls"] == []


@pytest.mark.parametrize("role,selected", [("last_attempt", True), ("last-attempt", True), ("selected", False)])
def test_last_alias_is_not_a_selected_runtime_even_with_selected_header(tmp_path, loader, role, selected):
    data = make_normative(tmp_path)
    data["checkpoint"].update(role=role, selected=selected)
    repin(data)
    with pytest.raises(ValueError, match="selected recipe"):
        runtime.open_normative_legal_ir_autoencoder(**options(data))
    assert not loader["loads"]


@pytest.mark.parametrize("field,value", [
    ("decoder_contract_id", "contextual-selected/v1"),
    ("training_recipe_name", "normative-aux025"),
    ("ir_family_id", "intent_ir"),
    ("dimension", 8), ("dimension", 786),
    ("dimension_role", "latent"), ("task_id", "legal_text_reconstruction"),
])
def test_family_dimension_contract_and_task_are_separate_before_reads(tmp_path, monkeypatch, loader, field, value):
    data = make_normative(tmp_path)
    kwargs = options(data)
    kwargs["request"][field] = value
    def forbidden(*args, **kwargs):
        raise AssertionError("invalid request attempted artifact read")
    monkeypatch.setattr(original, "_read", forbidden)
    with pytest.raises(ValueError):
        runtime.open_normative_legal_ir_autoencoder(**kwargs)
    assert not loader["loads"]


def test_zero_state_cannot_be_requested_as_auxiliary(tmp_path, loader):
    data = make_normative(tmp_path, recipe_name="normative-wording-zero")
    with pytest.raises(ValueError, match="selected recipe"):
        runtime.open_normative_legal_ir_autoencoder(**options(data))
    assert not loader["loads"]


def test_frozen_vocabulary_rejects_a_consistently_rehashed_alternate_codec(tmp_path, loader):
    data = make_normative(tmp_path)
    codec = data["checkpoint"]["codec"]
    codec["target_vocabulary"][8] = '"different_action"'
    data["donor"]["codec"] = deepcopy(codec)
    data["checkpoint"]["architecture"]["codec_sha256"] = original._digest(codec)
    data["checkpoint"]["lineage"]["teacher_codec_sha256"] = original._digest(codec)
    data["checkpoint"]["lineage"]["teacher_checkpoint_sha256"] = original._digest(data["donor"])
    repin(data)
    with pytest.raises(ValueError, match="normative32 vocabulary"):
        runtime.open_normative_legal_ir_autoencoder(**options(data))
    assert not loader["loads"]


@pytest.mark.parametrize("owner", ["normative_legal_ir_runtime", "ir_model_manager_import"])
def test_missing_additional_source_owner_refuses(tmp_path, loader, owner):
    data = make_normative(tmp_path)
    kwargs = options(data)
    del kwargs["source_owner_pins"][owner]
    with pytest.raises(ValueError, match="fifteen-owner"):
        runtime.open_normative_legal_ir_autoencoder(**kwargs)
    assert not loader["loads"]


def test_recipe_mutation_after_load_refuses_with_truthful_load_flags(tmp_path, loader):
    data = make_normative(tmp_path)
    def mutate():
        data["checkpoint"]["recipe"]["weight"] = 1.0
        repin(data)
    loader["after_load"] = mutate
    with pytest.raises(runtime.NormativeLegalRuntimeError) as observed:
        runtime.open_normative_legal_ir_autoencoder(**options(data))
    assert observed.value.model_load_started is observed.value.model_load_performed is True
    assert observed.value.model_inference_executed is False
    assert not loader["calls"]


def test_closing_fence_retains_actual_candidate_after_input_file_changes(tmp_path, loader):
    data = make_normative(tmp_path)
    handle = runtime.open_normative_legal_ir_autoencoder(**options(data))
    def mutate():
        Path(data["options"]["source_inputs_pin"]["path"]).write_bytes(b"[]")
    loader["after_infer"] = mutate
    with pytest.raises(runtime.NormativeLegalRuntimeError) as observed:
        handle.infer_cached()
    assert observed.value.model_inference_started is observed.value.model_inference_executed is True
    assert observed.value.raw_candidate_report["scope"] == "inert boundary observation"


def test_target_injection_by_numerical_owner_refuses(tmp_path, loader):
    data = make_normative(tmp_path)
    handle = runtime.open_normative_legal_ir_autoencoder(**options(data))
    loader["mutate_inputs"] = True
    with pytest.raises(ValueError, match="mutated source-only"):
        handle.infer_cached()


def test_foreign_loaded_registry_origin_refuses_before_identity_helper(tmp_path, monkeypatch, loader):
    data = make_normative(tmp_path)
    calls = []
    monkeypatch.setattr(runtime.registration, "__file__", "/foreign-worktree/ir_model_manager_import.py")
    monkeypatch.setattr(runtime.registration, "ir_model_asset_record_id", lambda *args: calls.append(args))
    with pytest.raises(ValueError, match="owner origin differs"):
        runtime.prepare_normative_legal_ir_runtime(**options(data))
    assert calls == loader["loads"] == loader["calls"] == []


def test_identity_helper_origin_change_is_caught_at_metadata_closing_fence(tmp_path, monkeypatch, loader):
    data = make_normative(tmp_path)
    calls = []
    derive = runtime.registration.ir_model_asset_record_id
    def changed(*args):
        result = derive(*args)
        calls.append(args)
        monkeypatch.setattr(runtime.registration, "__file__", "/foreign-worktree/ir_model_manager_import.py")
        return result
    monkeypatch.setattr(runtime.registration, "ir_model_asset_record_id", changed)
    with pytest.raises(ValueError, match="owner origin differs"):
        runtime.prepare_normative_legal_ir_runtime(**options(data))
    assert len(calls) == 1
    assert loader["loads"] == loader["calls"] == []


def test_hub_gateways_use_the_same_opt_in_contract(tmp_path, loader):
    from ipfs_datasets_py.logic.formalization.autoencoder import checkpoint_hub as hub
    data = make_normative(tmp_path)
    plan = hub.prepare_normative_legal_ir_runtime(**options(data))
    assert plan["schema"] == runtime.SCHEMA and not loader["loads"]
    handle = hub.open_normative_legal_ir_autoencoder(**options(data))
    assert handle.describe()["saved_training_recipe"] == data["checkpoint"]["recipe"]
    assert len(loader["loads"]) == 1 and not loader["calls"]
