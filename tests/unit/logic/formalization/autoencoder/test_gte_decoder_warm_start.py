"""Synthetic learned-donor reuse checks; no target encoder or fitting runs."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[5]
MODULE = ROOT / "ipfs_datasets_py/logic/formalization/autoencoder/gte_decoder_warm_start.py"
SPEC = importlib.util.spec_from_file_location("gte_decoder_warm_start_test_subject", MODULE)
subject = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(subject)
torch = pytest.importorskip("torch")


def raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()


@pytest.fixture(scope="module", autouse=True)
def bounded_threads():
    old = torch.get_num_threads()
    torch.set_num_threads(1)
    yield
    torch.set_num_threads(old)


@pytest.fixture(scope="module")
def donor(tmp_path_factory):
    """Synthetic weights, realistic closed donor schema and actual source pins."""
    directory = tmp_path_factory.mktemp("warm_start_donor")
    inspector = subject._TEACHER
    paths = {*inspector._NATIVE_MODULE_PATHS.values(), *inspector._NUMERICAL_PATHS.values(),
             "ipfs_datasets_py/logic/formalization/autoencoder/source_training_v2.py",
             "ipfs_datasets_py/optimizers/logic_theorem_optimizer/domain_384_autoencoder.py"}
    pins = {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in paths}
    config = dict(strategy="reference_ce", epochs=2, max_seconds=10., learning_rate=.003,
        batch_size=1, seed=71, patience=0, max_optimizer_steps=2, reconstruction_weight=.1,
        max_target_tokens=512, validation_interval=1, semantic_weight=4., constant_weight=1.,
        structure_weight=.25, input_normalization="center_rms", hidden_size=8, token_embedding_dim=8,
        projection_width=2, embedding_provenance={"model_id": "thenlper/gte-small",
            "revision": "17e1f347d17fe144873b1201da91788898c639cd", "dimension": 384,
            "dtype": "float32", "normalized": True, "truncated": False})
    codec = {"schema": "typed-json-lexical/v1", "target_vocabulary": ["<pad>", "<bos>", "<eos>", '"a"', '"b"']}
    shapes = inspector._INVENTORY._sequence_shapes({"config": config, "codec": codec}, 384)
    generator = torch.Generator().manual_seed(83)
    state = {name: (torch.randn(shape, generator=generator) * .05).tolist() for name, shape in shapes.items()}
    checkpoint = {"schema": inspector.CHECKPOINT_SCHEMA, "domain_id": "legal_ir", "dimension": 384,
        "architecture": inspector.ARCHITECTURE, "codec": codec, "config": config,
        "implementation": {
            "runtime_sha256": pins["ipfs_datasets_py/logic/formalization/autoencoder/source_training_v2.py"],
            "native": {"runtime": pins["ipfs_datasets_py/optimizers/logic_theorem_optimizer/domain_384_autoencoder.py"],
                "dependencies": {name: pins[path] for name, path in inspector._NATIVE_MODULE_PATHS.items()},
                "scope": "listed_numerical_and_native_validator_modules_only"},
            "numerical": {"files": {name: pins[path] for name, path in inspector._NUMERICAL_PATHS.items()},
                "scope": "listed_latent_decoder_and_grammar_sources_only"},
            "legal_codec_sha256": pins[inspector._NUMERICAL_PATHS["legal_formula_codec.py"]]},
        "parent_sha256": "a" * 64, "parent_binding": {"dimension": 384}, "lineage": {},
        "model_state": state, "weights_sha256": subject.digest(state),
        "input_transform": {"mode": "center_rms", "mean": [.25] * 384, "scale": 2., "origin": "training_only"},
        "semantic_paths": [],
        "training_manifest": [{"id": "synthetic-train", "source_sha256": "1" * 64,
            "normalized_source_sha256": "2" * 64, "embedding_sha256": "3" * 64, "target_sha256": "4" * 64}],
        "validation_manifest": [{"id": "synthetic-tune", "source_sha256": "5" * 64,
            "normalized_source_sha256": "6" * 64, "embedding_sha256": "7" * 64, "target_sha256": "4" * 64}],
        "training": {"optimizer_steps": 2, "selected_epoch": 1, "selected_optimizer_steps": 1,
            "test_used_for_selection": False, "selected_validation": {"objective": .5,
                "token_cross_entropy": .4, "valid_candidates": 1, "exact_targets": 0, "count": 1,
                "semantic_leaf_correct": 1, "semantic_leaf_count": 2, "semantic_leaf_accuracy": .5}},
        **{name: False for name in inspector._FLAGS}}
    path = directory / "synthetic-donor.json"
    path.write_bytes(raw(checkpoint))
    return {"path": path, "checkpoint": checkpoint, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "codec_sha256": subject.digest(codec)}


def create(donor, **overrides):
    arguments = dict(expected_teacher_sha256=donor["sha256"], seed=73, repository_root=ROOT)
    arguments.update(overrides)
    return subject.create_warm_start(donor["path"], **arguments)


def inspect(donor, checkpoint, **overrides):
    arguments = dict(expected_teacher_sha256=donor["sha256"], expected_domain_id="legal_ir",
                     expected_codec_sha256=donor["codec_sha256"])
    arguments.update(overrides)
    return subject.inspect_warm_start(checkpoint, **arguments)


def load(donor, checkpoint):
    return subject.load_warm_start(checkpoint, expected_teacher_sha256=donor["sha256"],
        expected_domain_id="legal_ir", expected_codec_sha256=donor["codec_sha256"])


@pytest.fixture(scope="module")
def initialized(donor):
    return create(donor)


def inputs():
    return torch.linspace(-.8, .9, 2 * 768).reshape(2, 768), torch.tensor([[1, 3], [1, 4]])


def test_import_and_inspection_are_stdlib_only():
    code = """import importlib.util,sys
spec=importlib.util.spec_from_file_location('isolated_warm_start',sys.argv[1])
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
assert not any(name in sys.modules for name in ('torch','transformers','numpy'))
"""
    subprocess.run([sys.executable, "-I", "-c", code, str(MODULE)], check=True)


def test_all_learned_decoder_tensors_and_exact_codec_are_inherited(donor, initialized):
    model, checkpoint = initialized
    old = donor["checkpoint"]
    assert checkpoint["codec"] == old["codec"]
    assert checkpoint["input_transform"] == old["input_transform"]
    assert checkpoint["donor"]["weights_sha256"] == old["weights_sha256"]
    assert set(model.state_dict()) == set(old["model_state"]) | subject._NEW
    for name, tensor in model.state_dict().items():
        if name not in subject._NEW:
            assert torch.equal(tensor, torch.tensor(old["model_state"][name]))
            assert checkpoint["model_state"][name] == old["model_state"][name]
    report = inspect(donor, checkpoint)
    assert report["copied_tensor_count"] == 13 and report["new_tensor_count"] == 2
    assert report["new_boundary_parameter_count"] == 768 * 384 + 384
    assert report["copied_parameter_count"] == sum(torch.tensor(value).numel() for value in old["model_state"].values())
    assert report["decoder_parameters_random"] is False and report["boundary_alignment_required"] is True


def test_only_boundary_seed_changes_and_rng_threads_are_preserved(donor, initialized):
    before = torch.get_rng_state().clone()
    threads = torch.get_num_threads()
    second, same = create(donor)
    third, different = create(donor, seed=74)
    assert torch.equal(before, torch.get_rng_state()) and torch.get_num_threads() == threads
    first, original = initialized
    assert same["weights_sha256"] == original["weights_sha256"]
    assert different["weights_sha256"] != original["weights_sha256"]
    for name, tensor in first.state_dict().items():
        assert tensor.device.type == "cpu" and tensor.dtype == torch.float32
        assert tensor.data_ptr() != second.state_dict()[name].data_ptr()
        assert torch.equal(tensor, second.state_dict()[name])
        if name not in subject._NEW:
            assert torch.equal(tensor, third.state_dict()[name])
    assert torch.equal(first.input_adapter.bias, torch.zeros(384))
    assert bool((first.input_adapter.weight[:, :384] != 0).all())
    assert bool((first.input_adapter.weight[:, 384:] != 0).all())
    assert donor["sha256"] == hashlib.sha256(donor["path"].read_bytes()).hexdigest()


def test_forward_exactly_matches_adapter_then_inherited_teacher_math(initialized):
    model, _ = initialized
    vectors, tokens = inputs()
    adapted = (model.input_adapter(vectors) - .25) / 2.
    projected = adapted + model.projection_up(torch.tanh(model.projection_down(adapted)))
    hidden = torch.tanh(model.condition(projected)).unsqueeze(0)
    expected = model.output(model.decoder(model.target_embedding(tokens), hidden)[0])
    actual_projected, logits = model(vectors, tokens)
    assert torch.equal(projected, actual_projected)
    assert torch.equal(logits, expected)
    condition = model.condition_from_input(vectors)
    assert condition.shape == (2, 8)
    assert torch.equal(condition, hidden.squeeze(0))
    assert torch.equal(model.decode_from_condition(condition, tokens), logits)


def test_private_student_weights_do_not_alias_donor_or_another_student(donor, initialized):
    first, checkpoint = initialized
    second = load(donor, checkpoint)
    with torch.no_grad():
        second.decoder.weight_ih_l0.add_(1)
    assert not torch.equal(first.decoder.weight_ih_l0, second.decoder.weight_ih_l0)
    assert checkpoint["model_state"]["decoder.weight_ih_l0"] == donor["checkpoint"]["model_state"]["decoder.weight_ih_l0"]


def test_exact_checkpoint_reload_preserves_outputs_and_inventory(donor, initialized):
    before = torch.get_rng_state().clone()
    model, checkpoint = initialized
    restored = load(donor, json.loads(raw(checkpoint)))
    assert torch.equal(before, torch.get_rng_state())
    vectors, tokens = inputs()
    assert torch.equal(restored(vectors, tokens)[1], model(vectors, tokens)[1])
    assert all(torch.equal(value, restored.state_dict()[name]) for name, value in model.state_dict().items())
    assert all(parameter.requires_grad for parameter in restored.parameters())
    assert checkpoint["optimizer"] == {"mode": "fresh", "state": None, "resume": False}


def test_frozen_inherited_decoder_still_backpropagates_to_new_boundary(donor):
    model, checkpoint = create(donor, freeze_inherited=True)
    vectors, tokens = inputs()
    weights_before = {name: value.clone() for name, value in model.state_dict().items()}
    logits = model(vectors, tokens)[1]
    logits.square().mean().backward()
    for name, parameter in model.named_parameters():
        if name in subject._NEW:
            assert parameter.requires_grad and parameter.grad is not None
            assert bool(torch.isfinite(parameter.grad).all()) and bool((parameter.grad != 0).any())
        else:
            assert not parameter.requires_grad and parameter.grad is None
    assert all(torch.equal(value, weights_before[name]) for name, value in model.state_dict().items())
    restored = load(donor, checkpoint)
    assert {name for name, parameter in restored.named_parameters() if parameter.requires_grad} == subject._NEW
    optimizer = subject.create_fresh_optimizer(restored)
    assert not optimizer.state
    assert len(optimizer.param_groups[0]["params"]) == 2


def test_pinned_bridge_is_copied_exactly_without_alignment_claims(donor, tmp_path):
    adapter = subject._BRIDGE.create_affine_bridge(97)
    bridge = subject._BRIDGE.pack_bridge_checkpoint(adapter, seed=97, domain_id="legal_ir",
        teacher_runtime_id="legal_ir:source_training_v2", source_representation_id=subject._TEACHER.SOURCE_REPRESENTATION_ID,
        student_representation_id=subject.PROFILE_ID, teacher_checkpoint_sha256=donor["sha256"],
        input_transform=donor["checkpoint"]["input_transform"])
    path = tmp_path / "bridge.json"
    path.write_bytes(raw(bridge))
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    model, checkpoint = create(donor, bridge_checkpoint_path=path, expected_bridge_sha256=digest)
    assert torch.equal(model.input_adapter.weight, adapter.weight)
    assert torch.equal(model.input_adapter.bias, adapter.bias)
    boundary = inspect(donor, checkpoint)["boundary_initialization"]
    assert boundary["mode"] == "pinned_affine_bridge" and boundary["seed"] == 97
    assert boundary["bridge_checkpoint_sha256"] == digest and boundary["alignment_qualified"] is False
    assert torch.equal(load(donor, checkpoint).input_adapter.weight, adapter.weight)


@pytest.mark.parametrize("seed", [-1, 2**31, True, "73", 1.2])
def test_invalid_seed_rejected_before_numerics(donor, seed):
    with pytest.raises(ValueError):
        create(donor, seed=seed)


@pytest.mark.parametrize("overrides", [{"expected_teacher_sha256": "b" * 64}, {"domain_id": "intent_ir"},
    {"freeze_inherited": 1}, {"bridge_checkpoint_path": "/missing"}, {"expected_bridge_sha256": "a" * 64}])
def test_constructor_external_bindings_are_required(donor, overrides):
    with pytest.raises(ValueError):
        create(donor, **overrides)


@pytest.mark.parametrize("field,value", [("schema", "unknown"), ("architecture", "native_random_decoder"),
    ("dimension", True), ("dimension", 384), ("intermediate_dimension", 768), ("runtime_id", "legacy"),
    ("source_profile_id", "gte-small"), ("freeze_inherited", 1), ("optimizer", {"mode": "resume", "state": {}}),
    ("representation_id", "invented"), ("weights_sha256", "b" * 64), ("implementation", {})])
def test_wrong_initialization_contract_fails(donor, initialized, field, value):
    checkpoint = deepcopy(initialized[1])
    checkpoint[field] = value
    with pytest.raises(ValueError):
        inspect(donor, checkpoint)


@pytest.mark.parametrize("field", list(subject.FLAGS))
def test_unsupported_claims_fail(donor, initialized, field):
    checkpoint = deepcopy(initialized[1])
    checkpoint[field] = not subject.FLAGS[field]
    with pytest.raises(ValueError):
        inspect(donor, checkpoint)


def test_changed_decoder_tensor_cannot_retain_donor_copy_claim(donor, initialized):
    checkpoint = deepcopy(initialized[1])
    checkpoint["model_state"]["output.bias"][0] += .25
    checkpoint["weights_sha256"] = subject.digest(checkpoint["model_state"])
    checkpoint["tensor_inventory"] = subject._inventory(checkpoint["model_state"],
        subject._shapes(checkpoint["config"], checkpoint["codec"]))
    checkpoint["representation_id"] = subject._identity(checkpoint)
    with pytest.raises(ValueError, match="inherited decoder"):
        inspect(donor, checkpoint)


def test_vocabulary_permutation_is_rejected_even_when_rehashed(donor, initialized):
    checkpoint = deepcopy(initialized[1])
    checkpoint["codec"]["target_vocabulary"][1:3] = ["<eos>", "<bos>"]
    checkpoint["codec_sha256"] = subject.digest(checkpoint["codec"])
    with pytest.raises(ValueError):
        inspect(donor, checkpoint)
    with pytest.raises(ValueError, match="vocabulary identity"):
        inspect(donor, initialized[1], expected_codec_sha256="e" * 64)


@pytest.mark.parametrize("change", ["unknown_source", "second_source_root", "numeric_resume", "bool_inventory_shape"])
def test_donor_closure_and_boolean_metadata_remain_exact(donor, initialized, change):
    checkpoint = deepcopy(initialized[1])
    if change == "unknown_source":
        checkpoint["donor_source_pins"][0]["path"] = "/unrelated/unknown.py"
    elif change == "second_source_root":
        checkpoint["donor_source_pins"][0]["path"] = "/different" + checkpoint["donor_source_pins"][0]["path"]
        checkpoint["donor_source_pins"].sort(key=lambda value: value["path"])
    elif change == "numeric_resume":
        checkpoint["optimizer"]["resume"] = 0
    else:
        checkpoint["tensor_inventory"][0]["shape"][0] = True
    with pytest.raises(ValueError):
        inspect(donor, checkpoint)


@pytest.mark.parametrize("change", ["unknown_tensor", "ragged", "bool", "nan", "float32_overflow"])
def test_malformed_tensor_states_fail(donor, initialized, change):
    checkpoint = deepcopy(initialized[1])
    state = checkpoint["model_state"]
    if change == "unknown_tensor":
        state["rogue"] = [0.]
    elif change == "ragged":
        state["input_adapter.weight"][0].pop()
    elif change == "bool":
        state["input_adapter.bias"][0] = True
    elif change == "nan":
        state["input_adapter.bias"][0] = float("nan")
    else:
        state["input_adapter.bias"][0] = 1e100
    with pytest.raises(ValueError):
        inspect(donor, checkpoint)


def test_non_float32_state_is_rejected_even_with_consistent_json_digests(donor, initialized):
    checkpoint = deepcopy(initialized[1])
    checkpoint["model_state"]["input_adapter.bias"][0] = 1e-20 + 1e-30
    checkpoint["weights_sha256"] = subject.digest(checkpoint["model_state"])
    checkpoint["tensor_inventory"] = subject._inventory(checkpoint["model_state"],
        subject._shapes(checkpoint["config"], checkpoint["codec"]))
    checkpoint["representation_id"] = subject._identity(checkpoint)
    with pytest.raises(ValueError, match="exact float32"):
        load(donor, checkpoint)


@pytest.mark.parametrize("change", ["wrong_width", "float64", "nan", "empty", "token_outside_codec",
                                   "negative_token", "long_prefix", "batch_mismatch", "non_integer_prefix"])
def test_forward_rejects_invalid_768_inputs_and_prefixes(initialized, change):
    model, _ = initialized
    vectors, tokens = inputs()
    if change == "wrong_width":
        vectors = vectors[:, :384]
    elif change == "float64":
        vectors = vectors.double()
    elif change == "nan":
        vectors[0, 0] = float("nan")
    elif change == "empty":
        vectors = vectors[:0]
    elif change == "token_outside_codec":
        tokens[0, 0] = 5
    elif change == "negative_token":
        tokens[0, 0] = -1
    elif change == "long_prefix":
        tokens = torch.ones(2, 513, dtype=torch.long)
    elif change == "batch_mismatch":
        tokens = tokens[:1]
    else:
        tokens = tokens.float()
    with pytest.raises(ValueError):
        model(vectors, tokens)


@pytest.mark.parametrize("learning_rate", [0, -.1, .2, float("nan"), True, ".003"])
def test_fresh_optimizer_rejects_bad_learning_rate(initialized, learning_rate):
    with pytest.raises(ValueError):
        subject.create_fresh_optimizer(initialized[0], learning_rate=learning_rate)
