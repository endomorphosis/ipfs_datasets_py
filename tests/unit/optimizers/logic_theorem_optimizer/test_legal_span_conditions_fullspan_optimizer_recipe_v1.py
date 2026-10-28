"""Pure metadata controls for the prospective TRAIN optimizer recipe.

The donor configuration and SHA256 roots below are synthetic caller inputs.
These tests establish contract identity and refusal behavior; they establish no
physical donor authentication, numerical parity, optimizer resume, or fit.
No historical checkpoint, capture, reference body, or numerical library is used.
"""
import copy

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import (
    legal_span_conditions_fullspan_optimizer_recipe_v1 as subject,
    legal_span_conditions_fullspan_training_v1 as base,
)


DONOR_CONFIG = {
    "hidden_size": 32,
    "embedding_dim": 8,
    "projection_width": 8,
    "latent_dimension": 384,
    "latent_enabled": False,
    "residual_scale": 0.25,
    "seed": 1729,
    "batch_size": 12,
    "learning_rate": 0.001,
}
BINDING_NAMES = (
    "donor_checkpoint_sha256", "donor_model_state_sha256",
    "donor_provenance_sha256", "source_parent_checkpoint_sha256",
    "source_parent_model_state_sha256", "context_contract_sha256",
    "training_manifest_sha256", "prepared_training_records_sha256",
    "teacher_checkpoint_sha256", "teacher_model_state_sha256",
    "teacher_capture_sha256", "teacher_training_sha256",
    "row_weight_training_sha256", "training_mask_certificate_sha256",
)
INPUT_BINDINGS = {
    "schema": "conditions-fullspan-f18-four-tensor-input-bindings/v1",
    **{name: format(index, "064x") for index, name in enumerate(BINDING_NAMES, 1)},
}
TOP_FIELDS = (
    "schema", "partition", "donor_config", "donor_config_sha256",
    "base_policy", "base_policy_sha256", "optimizer_recipe", "input_bindings",
    "implementation", "authority",
)
AUTHORITY_FLAGS = (
    "donor_authenticated", "input_origins_verified", "initial_parity_verified",
    "admitted", "native_admission", "model_execution_performed",
    "optimizer_constructed", "training_executed", "qualified",
    "model_gain_claimed", "formalized", "promoted", "semantic_review_performed",
    "Lean_admitted",
)
SELECTED = ["start.weight", "start.bias", "end.weight", "end.bias"]
BASE_PATH = "ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_span_conditions_fullspan_training_v1.py"
BASE_SHA256 = "56bd0a248a07de09519f95e5c4bae02ab9d8eb1134b483c257c1f7e7bcb07147"
RECIPE_PATH = "ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_span_conditions_fullspan_optimizer_recipe_v1.py"


def _arguments(**overrides):
    result = {
        "donor_config": copy.deepcopy(DONOR_CONFIG),
        "expected_bindings": copy.deepcopy(INPUT_BINDINGS),
        "learning_rate": 0.002,
        "margin_weight": 0.0,
    }
    result.update(overrides)
    return result


def _build(**overrides):
    return subject.build_optimizer_recipe(**_arguments(**overrides))


def _validate(recipe, **overrides):
    return subject.validate_optimizer_recipe(recipe, **_arguments(**overrides))


def _set_path(value, path, replacement):
    for key in path[:-1]:
        value = value[key]
    value[path[-1]] = replacement


def _rehash_declared_metadata(recipe):
    # A self-consistent content hash is not an independent expected input.
    recipe["donor_config_sha256"] = subject.recipe_digest(recipe["donor_config"])
    recipe["base_policy_sha256"] = subject.recipe_digest(recipe["base_policy"])


def test_digest_owner_and_closed_metadata_only_authority():
    recipe = _build()
    assert subject.recipe_digest is base.checkpoint_digest
    assert set(recipe) == set(TOP_FIELDS)
    assert recipe["schema"] == "conditions-fullspan-f18-optimizer-recipe/v1"
    assert recipe["partition"] == "TRAIN"
    assert recipe["authority"] == {name: False for name in AUTHORITY_FLAGS}
    assert all(type(value) is bool for value in recipe["authority"].values())
    assert subject.recipe_digest({"b": 2, "a": 1}) == subject.recipe_digest({"a": 1, "b": 2})
    assert len({subject.recipe_digest({"value": value}) for value in (False, 0, 0.0)}) == 3
    for name in ("wire_optimizer", "update", "capture", "checkpoint", "restore", "resume", "grant"):
        assert not hasattr(subject, name)


@pytest.mark.parametrize("margin_weight", [0.0, 0.25])
@pytest.mark.parametrize("learning_rate", [0.001, 0.002, 1, 1.0])
def test_explicit_rate_changes_only_detached_optimizer_metadata(learning_rate, margin_weight):
    recipe = _build(learning_rate=learning_rate, margin_weight=margin_weight)
    original_policy = base.checkpoint_policy(margin_weight=margin_weight)
    assert recipe["base_policy"] == original_policy
    assert recipe["base_policy_sha256"] == base.checkpoint_digest(original_policy)
    assert recipe["donor_config"] == DONOR_CONFIG
    assert recipe["donor_config_sha256"] == base.checkpoint_digest(DONOR_CONFIG)
    assert recipe["donor_config"]["learning_rate"] == 0.001
    assert type(recipe["donor_config"]["learning_rate"]) is float
    assert recipe["base_policy"]["optimizer"]["learning_rate"] == 0.001
    prospective = copy.deepcopy(original_policy["optimizer"])
    prospective["learning_rate"] = learning_rate
    assert recipe["optimizer_recipe"] == prospective
    assert type(recipe["optimizer_recipe"]["learning_rate"]) is type(learning_rate)
    assert recipe["input_bindings"] == INPUT_BINDINGS
    assert _validate(recipe, learning_rate=learning_rate, margin_weight=margin_weight) == recipe
    assert recipe["implementation"]["base"] == base._checkpoint_implementation()
    assert set(recipe["implementation"]) == {"base", "recipe"}
    assert set(recipe["implementation"]["recipe"]) == {"path", "sha256"}
    assert recipe["implementation"]["recipe"]["path"] == RECIPE_PATH
    assert len(recipe["implementation"]["recipe"]["sha256"]) == 64
    assert [row for row in recipe["implementation"]["base"]["owners"] if row["path"] == BASE_PATH] == [
        {"path": BASE_PATH, "sha256": BASE_SHA256}]


@pytest.mark.parametrize("margin_weight", [0.0, 0.25])
def test_fixed_train_objective_mask_and_frozen_metadata(margin_weight):
    policy = _build(margin_weight=margin_weight)["base_policy"]
    assert policy["margin_weight"] == margin_weight
    assert (policy["training_rows"], policy["gold_present_rows"], policy["gold_absent_rows"]) == (168, 72, 96)
    assert (policy["seed"], policy["batch_size"]) == (1729, 12)
    assert (policy["max_cumulative_updates"], policy["max_call_seconds"]) == (32, 32)
    assert (policy["ce_outer_denominator"], policy["kl_full_batch_denominator"]) == (8, 72)
    assert policy["latent_enabled"] is False
    assert policy["teacher_model_forwards"] == 0
    assert type(policy["teacher_model_forwards"]) is int
    assert policy["tuning_or_evaluation_references_used"] is False
    assert policy["schedule_owner"] == "legal_span_targeted_loss._batch_indices/_advance_progress"
    assert policy["objective_owner"] == "legal_span_modality_conditions_retention._loss + conditions_fullspan_margin_from_logits"
    selection = policy["selection"]
    assert selection["optimizer_parameter_order"] == SELECTED
    assert selection["active_rows"] == {name: [3] for name in SELECTED}
    assert selection["inactive_rows"] == {name: [0, 1, 2, 4, 5] for name in SELECTED}
    assert (selection["active_scalar_count"], selection["stored_scalar_count"], selection["inactive_scalar_count"]) == (130, 780, 650)
    assert (selection["donor_tensor_count"], selection["frozen_tensor_count"], selection["conditions_row"]) == (42, 38, 3)
    assert selection["modality_frozen"] is True
    assert len(selection["frozen_parameter_names"]) == 38
    assert "modality.weight" in selection["frozen_parameter_names"]
    assert "modality.bias" in selection["frozen_parameter_names"]
    assert set(selection["frozen_parameter_names"]).isdisjoint(SELECTED)


def test_build_and_validate_detach_inputs_outputs_and_base_optimizer():
    arguments = _arguments()
    expected_inputs = copy.deepcopy(arguments)
    first = subject.build_optimizer_recipe(**arguments)
    second = subject.build_optimizer_recipe(**arguments)
    validated = subject.validate_optimizer_recipe(first, **arguments)
    assert arguments == expected_inputs
    assert validated == first == second
    assert first is not second and validated is not first
    assert first["optimizer_recipe"] is not first["base_policy"]["optimizer"]
    first["optimizer_recipe"]["betas"][0] = 0.1
    first["input_bindings"][BINDING_NAMES[0]] = "f" * 64
    first["donor_config"]["residual_scale"] = 0.5
    first["implementation"]["recipe"]["path"] = "detached"
    assert validated == second
    assert arguments == expected_inputs
    validated["base_policy"]["selection"]["active_rows"]["start.weight"].append(4)
    assert second == subject.build_optimizer_recipe(**arguments)
    arguments["donor_config"]["residual_scale"] = 0.75
    arguments["expected_bindings"][BINDING_NAMES[1]] = "e" * 64
    assert second["donor_config"] == DONOR_CONFIG
    assert second["input_bindings"] == INPUT_BINDINGS


@pytest.mark.parametrize("binding_name", BINDING_NAMES)
def test_independent_expected_root_cannot_be_replaced_by_recipe_root(binding_name):
    recipe = _build()
    other_bindings = copy.deepcopy(INPUT_BINDINGS)
    other_bindings[binding_name] = "f" * 64
    with pytest.raises(ValueError):
        _validate(recipe, expected_bindings=other_bindings)
    recipe["input_bindings"][binding_name] = "f" * 64
    with pytest.raises(ValueError):
        _validate(recipe)


@pytest.mark.parametrize("expected_change", ["learning_rate", "margin_weight", "donor_geometry", "donor_residual"])
def test_independent_expected_inputs_are_required_even_for_self_consistent_recipe(expected_change):
    recipe = _build()
    overrides = {}
    if expected_change == "learning_rate":
        overrides["learning_rate"] = 0.003
    elif expected_change == "margin_weight":
        overrides["margin_weight"] = 0.25
    else:
        donor = copy.deepcopy(DONOR_CONFIG)
        donor["embedding_dim" if expected_change == "donor_geometry" else "residual_scale"] = (
            16 if expected_change == "donor_geometry" else 0.5)
        overrides["donor_config"] = donor
    replacement = _build(**overrides)
    assert subject.recipe_digest(recipe) != subject.recipe_digest(replacement)
    with pytest.raises(ValueError):
        _validate(recipe, **overrides)
    with pytest.raises(ValueError):
        _validate(replacement)


@pytest.mark.parametrize("field", TOP_FIELDS)
def test_missing_top_level_contract_field_refused(field):
    recipe = _build()
    del recipe[field]
    with pytest.raises(ValueError):
        _validate(recipe)


@pytest.mark.parametrize("field", ["optimizer_state", "resume", "evaluation_references", "callback", "admission"])
def test_extra_execution_reference_or_state_field_refused(field):
    recipe = _build()
    recipe[field] = None
    with pytest.raises(ValueError):
        _validate(recipe)


@pytest.mark.parametrize("path,replacement", [
    (("schema",), "conditions-fullspan-f18-four-tensor-checkpoint/v1"),
    (("partition",), "DEV"),
    (("partition",), "TEST"),
    (("partition",), "TUNE"),
    (("donor_config", "residual_scale"), 0.5),
    (("donor_config", "learning_rate"), 0.002),
    (("base_policy", "margin_weight"), 0.25),
    (("base_policy", "training_rows"), 167),
    (("base_policy", "batch_size"), 6),
    (("base_policy", "seed"), 1730),
    (("base_policy", "max_cumulative_updates"), 64),
    (("base_policy", "schedule_sha256"), "f" * 64),
    (("base_policy", "ce_outer_denominator"), 7),
    (("base_policy", "kl_full_batch_denominator"), 6),
    (("base_policy", "selection", "active_rows", "start.weight"), [3, 4]),
    (("base_policy", "selection", "frozen_tensor_count"), 36),
    (("optimizer_recipe", "parameter_order"), list(reversed(SELECTED))),
    (("optimizer_recipe", "weight_decay"), 0.01),
    (("implementation", "recipe", "sha256"), "f" * 64),
    (("implementation", "recipe", "path"), "different_owner.py"),
])
def test_rehashed_policy_donor_source_or_partition_mutation_refused(path, replacement):
    recipe = _build()
    _set_path(recipe, path, copy.deepcopy(replacement))
    _rehash_declared_metadata(recipe)
    with pytest.raises(ValueError):
        _validate(recipe)


@pytest.mark.parametrize("path,replacement", [
    (("donor_config", "latent_enabled"), 0),
    (("donor_config", "hidden_size"), 32.0),
    (("base_policy", "latent_enabled"), 0),
    (("base_policy", "teacher_model_forwards"), False),
    (("base_policy", "training_rows"), 168.0),
    (("base_policy", "selection", "modality_frozen"), 1),
    (("base_policy", "selection", "conditions_row"), 3.0),
    (("base_policy", "optimizer", "foreach"), 0),
    (("optimizer_recipe", "inherited_moments"), 0),
    (("optimizer_recipe", "foreach"), 0),
    (("optimizer_recipe", "learning_rate"), 1),
    (("authority", "admitted"), 0),
])
def test_python_equal_scalar_is_not_canonical_contract_identity(path, replacement):
    rate = 1.0 if path == ("optimizer_recipe", "learning_rate") else 0.002
    recipe = _build(learning_rate=rate)
    original = copy.deepcopy(recipe)
    _set_path(recipe, path, replacement)
    assert recipe == original
    _rehash_declared_metadata(recipe)
    with pytest.raises(ValueError):
        _validate(recipe, learning_rate=rate)


@pytest.mark.parametrize("flag", AUTHORITY_FLAGS)
def test_no_authority_flag_can_be_promoted(flag):
    recipe = _build()
    recipe["authority"][flag] = True
    with pytest.raises(ValueError):
        _validate(recipe)


@pytest.mark.parametrize("learning_rate", [False, True, None, "0.002", 0, -0.0, -1, float("nan"), float("inf"), -float("inf"), 10 ** 500])
def test_train_rate_requires_explicit_finite_positive_number(learning_rate):
    with pytest.raises(ValueError):
        _build(learning_rate=learning_rate)


@pytest.mark.parametrize("margin_weight", [False, True, None, "0.25", -0.25, 0.1, 0.5, float("nan"), 10 ** 500])
def test_margin_requires_explicit_existing_matched_arm(margin_weight):
    with pytest.raises(ValueError):
        _build(margin_weight=margin_weight)


@pytest.mark.parametrize("field,replacement", [
    ("hidden_size", 32.0), ("hidden_size", True),
    ("embedding_dim", 8.0), ("embedding_dim", 3),
    ("projection_width", 8.0), ("projection_width", 129),
    ("latent_dimension", 384.0), ("latent_dimension", 768),
    ("seed", 1729.0), ("seed", 1730),
    ("batch_size", 12.0), ("batch_size", 6),
    ("latent_enabled", 0), ("latent_enabled", True),
    ("learning_rate", 0.002), ("learning_rate", True),
    ("residual_scale", False), ("residual_scale", 1.25),
])
def test_donor_config_remains_typed_original_v1_geometry(field, replacement):
    donor = copy.deepcopy(DONOR_CONFIG)
    donor[field] = replacement
    with pytest.raises(ValueError):
        _build(donor_config=donor)


@pytest.mark.parametrize("malformation", ["missing_config", "extra_config", "missing_root", "extra_root", "wrong_schema", "uppercase_root", "short_root", "nonstring_root"])
def test_closed_donor_and_original_input_binding_schemas(malformation):
    donor = copy.deepcopy(DONOR_CONFIG)
    bindings = copy.deepcopy(INPUT_BINDINGS)
    if malformation == "missing_config":
        del donor["learning_rate"]
    elif malformation == "extra_config":
        donor["partition"] = "TRAIN"
    elif malformation == "missing_root":
        del bindings["training_mask_certificate_sha256"]
    elif malformation == "extra_root":
        bindings["evaluation_capture_sha256"] = "e" * 64
    elif malformation == "wrong_schema":
        bindings["schema"] = "caller-self-authenticated/v1"
    elif malformation == "uppercase_root":
        bindings["training_mask_certificate_sha256"] = "A" * 64
    elif malformation == "short_root":
        bindings["training_mask_certificate_sha256"] = "a" * 63
    else:
        bindings["training_mask_certificate_sha256"] = 1
    with pytest.raises(ValueError):
        _build(donor_config=donor, expected_bindings=bindings)


class _Dict(dict):
    pass


class _List(list):
    pass


class _String(str):
    pass


class _Float(float):
    pass


class _Int(int):
    pass


@pytest.mark.parametrize("malformation", ["binding_schema_subclass", "binding_key_subclass", "binding_value_subclass", "bindings_dict_subclass", "donor_dict_subclass", "rate_number_subclass", "donor_integer_subclass"])
def test_caller_inputs_are_literal_types_before_detaching(malformation):
    arguments = _arguments()
    bindings = arguments["expected_bindings"]
    if malformation == "binding_schema_subclass":
        bindings["schema"] = _String(bindings["schema"])
    elif malformation == "binding_key_subclass":
        value = bindings.pop(BINDING_NAMES[0])
        bindings[_String(BINDING_NAMES[0])] = value
    elif malformation == "binding_value_subclass":
        bindings[BINDING_NAMES[0]] = _String(bindings[BINDING_NAMES[0]])
    elif malformation == "bindings_dict_subclass":
        arguments["expected_bindings"] = _Dict(bindings)
    elif malformation == "donor_dict_subclass":
        arguments["donor_config"] = _Dict(arguments["donor_config"])
    elif malformation == "rate_number_subclass":
        arguments["learning_rate"] = _Float(0.002)
    else:
        arguments["donor_config"]["seed"] = _Int(1729)
    with pytest.raises(ValueError):
        subject.build_optimizer_recipe(**arguments)


@pytest.mark.parametrize("malformation", ["top_dict_subclass", "nested_dict_subclass", "list_subclass", "tuple", "set", "bytes", "nonstring_key", "nonfinite_float"])
def test_recipe_requires_literal_finite_json_containers(malformation):
    recipe = _build()
    if malformation == "top_dict_subclass":
        recipe = _Dict(recipe)
    elif malformation == "nested_dict_subclass":
        recipe["authority"] = _Dict(recipe["authority"])
    elif malformation == "list_subclass":
        recipe["optimizer_recipe"]["betas"] = _List([0.9, 0.999])
    elif malformation == "tuple":
        recipe["optimizer_recipe"]["betas"] = (0.9, 0.999)
    elif malformation == "set":
        recipe["optimizer_recipe"]["betas"] = {0.9, 0.999}
    elif malformation == "bytes":
        recipe["schema"] = b"conditions-fullspan-f18-optimizer-recipe/v1"
    elif malformation == "nonstring_key":
        recipe["authority"][1] = False
    else:
        recipe["optimizer_recipe"]["eps"] = float("nan")
    with pytest.raises(ValueError):
        _validate(recipe)


@pytest.mark.parametrize("bound", ["depth", "nodes", "bytes"])
def test_recipe_json_bounds_refuse_before_contract_comparison(bound):
    recipe = _build()
    if bound == "depth":
        payload = None
        for _ in range(17):
            payload = [payload]
    elif bound == "nodes":
        payload = [False] * 16385
    else:
        payload = "x" * (128 * 1024 + 1)
    recipe["authority"]["admitted"] = payload
    with pytest.raises(ValueError, match="bounded recipe JSON"):
        _validate(recipe)


@pytest.mark.parametrize("owner", ["base", "recipe"])
def test_observed_source_drift_refused_without_writing_source(monkeypatch, owner):
    original_read = subject._source_bytes
    drift_path = str(base.__file__ if owner == "base" else subject.__file__)

    def observed_bytes(path, maximum):
        if str(path) == drift_path:
            return b"synthetic observed source drift"
        return original_read(path, maximum)

    monkeypatch.setattr(subject, "_source_bytes", observed_bytes)
    with pytest.raises(ValueError, match="source"):
        _build()


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "wrong_hash"])
def test_original_implementation_requires_exactly_one_profile56_owner(monkeypatch, mutation):
    implementation = copy.deepcopy(base._checkpoint_implementation())
    owners = implementation["owners"]
    original = next(row for row in owners if row["path"] == BASE_PATH)
    if mutation == "missing":
        owners.remove(original)
    elif mutation == "duplicate":
        owners.append(copy.deepcopy(original))
    else:
        original["sha256"] = "f" * 64
    monkeypatch.setattr(base, "_checkpoint_implementation", lambda: implementation)
    with pytest.raises(ValueError, match="profile56 implementation binding"):
        _build()
