"""Synthetic dual-donor reuse; no qualified labels, fitting or real embeddings."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[5]
MODULE = ROOT / "ipfs_datasets_py/logic/formalization/autoencoder/gte_decoder_reuse.py"


def read_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


subject = read_module("gte_decoder_reuse_test_subject", MODULE)
primary_fixture = read_module("gte_reuse_primary_fixture", Path(__file__).with_name("test_gte_decoder_warm_start.py"))
legacy_fixture = read_module("gte_reuse_legacy_fixture", Path(__file__).with_name("test_gte_legacy8_decoder_donor.py"))
kd = read_module("gte_reuse_distillation", MODULE.with_name("gte_decoder_distillation.py"))
torch = pytest.importorskip("torch")


@pytest.fixture(scope="module", autouse=True)
def bounded_threads():
    before = torch.get_num_threads()
    torch.set_num_threads(1)
    yield
    torch.set_num_threads(before)


@pytest.fixture(scope="module")
def donors(tmp_path_factory):
    primary = primary_fixture.donor.__wrapped__(tmp_path_factory)
    legacy = legacy_fixture.checkpoint()
    generator = torch.Generator().manual_seed(109)
    # Distinct output rows ensure auxiliary KL actually depends on its input.
    legacy["model_state"] = {name: (torch.randn(shape, generator=generator) * .05).tolist()
        for name, shape in subject._LEGACY._shapes(legacy["config"], len(legacy["codec"]["target_vocabulary"])).items()}
    directory = tmp_path_factory.mktemp("dual_legacy8_donor")
    legacy_path, legacy_sha256 = legacy_fixture.write(directory, legacy)
    return {"primary": primary, "legacy_path": legacy_path,
            "legacy_sha256": legacy_sha256, "legacy": legacy}


def create(donors, **changes):
    arguments = {"expected_teacher384_sha256": donors["primary"]["sha256"],
        "expected_legacy8_sha256": donors["legacy_sha256"], "repository_root": ROOT, "seed": 113}
    arguments.update(changes)
    return subject.create_dual_decoder(donors["primary"]["path"], donors["legacy_path"], **arguments)


@pytest.fixture(scope="module")
def initialized(donors):
    return create(donors)


def inspect(bundle, pins=None):
    return subject.inspect_dual_decoder(bundle, expected_donor_pins=pins or bundle["donor_pins"])


def reload(bundle, pins=None):
    return subject.load_dual_decoder(bundle, expected_donor_pins=pins or bundle["donor_pins"])


def inputs():
    return (torch.linspace(-.8, .9, 2 * 768).reshape(2, 768),
            torch.tensor([[1, 3], [1, 4]], dtype=torch.long),
            torch.tensor([[1, 3, 4], [1, 4, 5]], dtype=torch.long))


def test_import_and_inspection_load_no_model_dependencies():
    program = """import importlib.util,sys
spec=importlib.util.spec_from_file_location('isolated_reuse',sys.argv[1])
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
assert not any(name in sys.modules for name in ('torch','transformers','numpy','ipfs_datasets_py'))
"""
    subprocess.run([sys.executable, "-I", "-c", program, str(MODULE)], check=True)


def test_saved_bundle_inspection_is_dependency_free(initialized, tmp_path):
    bundle_path, pins_path = tmp_path / "bundle.json", tmp_path / "pins.json"
    bundle_path.write_text(json.dumps(initialized[1]))
    pins_path.write_text(json.dumps(initialized[1]["donor_pins"]))
    program = """import importlib.util,json,sys
spec=importlib.util.spec_from_file_location('isolated_inspection',sys.argv[1])
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
with open(sys.argv[2]) as stream: bundle=json.load(stream)
with open(sys.argv[3]) as stream: pins=json.load(stream)
report=module.inspect_dual_decoder(bundle,expected_donor_pins=pins)
assert report['primary_copied_tensor_count']==report['legacy8_copied_tensor_count']==13
assert not any(name in sys.modules for name in ('torch','transformers','numpy','ipfs_datasets_py'))
"""
    subprocess.run([sys.executable, "-I", "-c", program, str(MODULE), str(bundle_path), str(pins_path)], check=True)


def test_all_26_learned_tensors_and_both_exact_codecs_are_copied(donors, initialized):
    model, bundle = initialized
    primary = donors["primary"]["checkpoint"]
    legacy = donors["legacy"]
    assert bundle["primary"]["codec"] == primary["codec"]
    assert bundle["legacy8"]["codec"] == legacy["codec"]
    assert len(primary["model_state"]) == len(legacy["model_state"]) == 13
    for branch, checkpoint in ((model.primary, primary), (model.legacy8, legacy)):
        for name, expected in checkpoint["model_state"].items():
            actual = branch.state_dict()[name]
            assert torch.equal(actual, torch.tensor(expected, dtype=torch.float32))
            assert actual.device.type == "cpu" and actual.dtype == torch.float32
    assert bundle["primary"]["input_transform"] == primary["input_transform"]
    report = inspect(bundle)
    assert report["primary_copied_tensor_count"] == report["legacy8_copied_tensor_count"] == 13
    assert report["copied_parameter_count"] == sum(
        torch.tensor(value).numel() for checkpoint in (primary, legacy) for value in checkpoint["model_state"].values())
    assert report["new_boundary_parameter_count"] == 768 * 384 + 384
    assert report["new_auxiliary_connector_parameter_count"] == 8 * primary["config"]["hidden_size"] + 8
    assert report["primary_vocabulary_size"] == 5 and report["auxiliary_vocabulary_size"] == 17
    assert report["primary_max_target_tokens"] == 512 and report["auxiliary_max_target_tokens"] == 64
    assert report["decoder_parameters_random"] is False
    assert report["boundary_alignment_required"] is True
    assert not report["training_executed"] and not report["distillation_executed"]


def test_created_students_have_private_storages_and_leave_donors_unchanged(donors, initialized):
    first, bundle = initialized
    before_files = {"primary": donors["primary"]["path"].read_bytes(), "legacy": donors["legacy_path"].read_bytes()}
    second = reload(bundle)
    pointers = [value.untyped_storage().data_ptr() for value in second.state_dict().values()]
    assert len(pointers) == len(set(pointers))
    for name, value in first.state_dict().items():
        assert value.data_ptr() != second.state_dict()[name].data_ptr()
        assert torch.equal(value, second.state_dict()[name])
    with torch.no_grad():
        second.primary.output.bias.add_(1.)
        second.legacy8.output.bias.add_(2.)
    assert not torch.equal(first.primary.output.bias, second.primary.output.bias)
    assert not torch.equal(first.legacy8.output.bias, second.legacy8.output.bias)
    assert donors["primary"]["path"].read_bytes() == before_files["primary"]
    assert donors["legacy_path"].read_bytes() == before_files["legacy"]


def test_construction_reload_preserve_rng_threads_and_only_new_interface_seeds_change(donors, initialized):
    before = torch.get_rng_state().clone()
    threads = torch.get_num_threads()
    same, same_bundle = create(donors)
    different, different_bundle = create(donors, seed=127)
    restored = reload(initialized[1])
    assert torch.equal(before, torch.get_rng_state()) and torch.get_num_threads() == threads
    assert same_bundle == initialized[1]
    assert different_bundle["representation_id"] != same_bundle["representation_id"]
    for name, value in same.state_dict().items():
        assert torch.equal(value, restored.state_dict()[name])
        if name.startswith(("primary.input_adapter.", "auxiliary_connector.")):
            if name.endswith("weight"):
                assert not torch.equal(value, different.state_dict()[name])
        else:
            assert torch.equal(value, different.state_dict()[name])
    assert not any(module.training for module in restored.modules())


def test_forward_uses_shared_condition_without_merging_head_vocabularies(initialized):
    model, _ = initialized
    vectors, primary_prefix, auxiliary_prefix = inputs()
    shared = model.primary.condition_from_input(vectors)
    expected_primary = model.primary.decode_from_condition(shared, primary_prefix)
    auxiliary_latent = model.auxiliary_connector(shared)
    expected_auxiliary = model.legacy8(auxiliary_latent, auxiliary_prefix)[1]
    result = model(vectors, primary_prefix, auxiliary_prefix)
    assert torch.equal(result["shared_condition"], shared)
    assert torch.equal(result["auxiliary_latent"], auxiliary_latent)
    assert torch.equal(result["primary_logits"], expected_primary)
    assert torch.equal(result["auxiliary_logits"], expected_auxiliary)
    assert result["primary_logits"].shape == (2, 2, 5)
    assert result["auxiliary_logits"].shape == (2, 3, 17)


def test_reference_prefixes_do_not_enter_the_shared_source_condition_or_other_head(initialized):
    model, _ = initialized
    vectors, primary_prefix, auxiliary_prefix = inputs()
    original = model(vectors, primary_prefix, auxiliary_prefix)
    changed_primary = model(vectors, primary_prefix.flip(1), auxiliary_prefix)
    assert torch.equal(original["shared_condition"], changed_primary["shared_condition"])
    assert torch.equal(original["auxiliary_logits"], changed_primary["auxiliary_logits"])
    assert not torch.equal(original["primary_logits"], changed_primary["primary_logits"])
    changed_auxiliary = model(vectors, primary_prefix, auxiliary_prefix.flip(1))
    assert torch.equal(original["shared_condition"], changed_auxiliary["shared_condition"])
    assert torch.equal(original["primary_logits"], changed_auxiliary["primary_logits"])
    assert not torch.equal(original["auxiliary_logits"], changed_auxiliary["auxiliary_logits"])


def test_auxiliary_loss_reaches_primary_boundary_and_connector_with_both_heads_frozen(initialized):
    model = reload(initialized[1])
    saved = {name: value.clone() for name, value in model.state_dict().items()}
    auxiliary = model(*inputs())["auxiliary_logits"]
    weights = torch.linspace(.5, 1.5, auxiliary.numel()).reshape(auxiliary.shape)
    (auxiliary * weights).mean().backward()
    trainable = {"primary.input_adapter.weight", "primary.input_adapter.bias",
                 "auxiliary_connector.weight", "auxiliary_connector.bias"}
    for name, parameter in model.named_parameters():
        if name in trainable:
            assert parameter.requires_grad and parameter.grad is not None
            assert bool(torch.isfinite(parameter.grad).all()) and bool((parameter.grad != 0).any())
        else:
            assert not parameter.requires_grad and parameter.grad is None
    assert all(torch.equal(value, saved[name]) for name, value in model.state_dict().items())


def kd_contract(codec, prefix):
    return {"student_codec_sha256": codec, "teacher_codec_sha256": codec,
        "student_prefix_sha256": prefix, "teacher_prefix_sha256": prefix,
        "prefix_policy": "reference_prefix", "distribution": "raw",
        "teacher_checkpoint_sha256": "a" * 64, "teacher_qualification_sha256": "b" * 64,
        "teacher_scope_id": "synthetic-objective-check-only"}


def test_auxiliary_masked_kd_reaches_shared_primary_boundary_without_optimizer(initialized):
    model = reload(initialized[1])
    result = model(*inputs())
    student = result["auxiliary_logits"]
    teacher = torch.linspace(-.9, .8, student.numel()).reshape(student.shape).requires_grad_()
    mask = torch.tensor([[True, False, True], [False, True, False]])
    auxiliary = kd.masked_teacher_kl(student, teacher, token_mask=mask,
        alignment_contract=kd_contract(initialized[1]["donor_pins"]["legacy8_codec_sha256"], "c" * 64))
    auxiliary["loss"].backward()
    assert teacher.grad is None
    for parameter in (*model.primary.input_adapter.parameters(), *model.auxiliary_connector.parameters()):
        assert parameter.grad is not None and torch.isfinite(parameter.grad).all()
        assert bool((parameter.grad != 0).any())
    assert all(parameter.grad is None for parameter in model.legacy8.parameters())
    assert all(parameter.grad is None for name, parameter in model.primary.named_parameters()
               if not name.startswith("input_adapter."))


def test_separate_head_kd_combines_objectives_with_independent_prefix_digests(initialized):
    model = reload(initialized[1])
    result = model(*inputs())
    heads = {}
    for name, key, codec_key, prefix_digest in (("primary", "primary_logits", "teacher384_codec_sha256", "c" * 64),
        ("auxiliary", "auxiliary_logits", "legacy8_codec_sha256", "d" * 64)):
        logits = result[key]
        teacher = torch.linspace(-.7, .5, logits.numel()).reshape(logits.shape).requires_grad_()
        heads[name] = kd.masked_teacher_kl(logits, teacher,
            token_mask=torch.ones(logits.shape[:2], dtype=torch.bool),
            alignment_contract=kd_contract(initialized[1]["donor_pins"][codec_key], prefix_digest))
    objective = kd.combine_multiteacher_losses(heads, weights={"primary": 1., "auxiliary": .25})
    assert objective["heads"]["primary"]["vocabulary_size"] == 5
    assert objective["heads"]["auxiliary"]["vocabulary_size"] == 17
    assert objective["heads"]["primary"]["valid_token_count"] == 4
    assert objective["heads"]["auxiliary"]["valid_token_count"] == 6
    assert objective["logits_combined"] is False
    objective["loss"].backward()
    assert model.primary.input_adapter.weight.grad is not None
    assert bool((model.primary.input_adapter.weight.grad != 0).any())
    assert model.auxiliary_connector.weight.grad is not None
    assert bool((model.auxiliary_connector.weight.grad != 0).any())


def test_private_dual_bundle_reloads_exactly_from_authenticated_bytes(initialized, tmp_path):
    model, bundle = initialized
    path = tmp_path / "dual.json"
    path.write_bytes(json.dumps(bundle, sort_keys=True, separators=(",", ":")).encode())
    expected = hashlib.sha256(path.read_bytes()).hexdigest()
    authenticated, _ = subject._PRIMARY._IO.read_pinned_json(path, expected_sha256=expected)
    restored = reload(authenticated, bundle["donor_pins"])
    for name, value in model.state_dict().items():
        assert torch.equal(value, restored.state_dict()[name])
    original_result = model(*inputs())
    actual_result = restored(*inputs())
    assert all(torch.equal(value, actual_result[name]) for name, value in original_result.items())
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError):
        subject._PRIMARY._IO.read_pinned_json(path, expected_sha256=expected)


def test_fresh_optimizer_has_only_four_new_interface_tensors_and_no_donor_moments(initialized):
    model = reload(initialized[1])
    optimizer = subject._PRIMARY.create_fresh_optimizer(model)
    assert not optimizer.state
    parameters = optimizer.param_groups[0]["params"]
    assert len(parameters) == 4
    assert {id(value) for value in parameters} == {id(value) for value in model.parameters() if value.requires_grad}
    assert initialized[1]["optimizer"] == {"mode": "fresh", "state": None, "resume": False}
    assert initialized[1]["primary"]["optimizer"] == initialized[1]["optimizer"]
    assert "optimizer_state" not in initialized[1]["legacy8"]


def test_head_prefix_lengths_and_vocabulary_are_independent(initialized):
    model, _ = initialized
    vectors = inputs()[0]
    result = model(vectors, torch.ones((2, 65), dtype=torch.long), torch.full((2, 64), 16, dtype=torch.long))
    assert result["primary_logits"].shape == (2, 65, 5)
    assert result["auxiliary_logits"].shape == (2, 64, 17)
    with pytest.raises(ValueError):
        model(vectors, torch.full((2, 1), 16, dtype=torch.long), torch.ones((2, 1), dtype=torch.long))
    with pytest.raises(ValueError):
        model(vectors, torch.ones((2, 1), dtype=torch.long), torch.ones((2, 65), dtype=torch.long))
    with pytest.raises(ValueError):
        model(vectors, torch.ones((2, 513), dtype=torch.long), torch.ones((2, 1), dtype=torch.long))


@pytest.mark.parametrize("kind", ["float", "negative", "outside", "zero_length", "batch", "rank", "meta"])
def test_auxiliary_prefix_rejections(initialized, kind):
    vectors, primary, auxiliary = inputs()
    bad = {"float": auxiliary.float(), "negative": torch.full((2, 1), -1, dtype=torch.long),
           "outside": torch.full((2, 1), 17, dtype=torch.long), "zero_length": auxiliary[:, :0],
           "batch": auxiliary[:1], "rank": auxiliary.unsqueeze(0),
           "meta": torch.empty((2, 1), dtype=torch.long, device="meta")}[kind]
    with pytest.raises(ValueError):
        initialized[0](vectors, primary, bad)


@pytest.mark.parametrize("seed", [-1, 2**31, True, 1.2, "113"])
def test_constructor_seed_is_strict(donors, seed):
    with pytest.raises(ValueError):
        create(donors, seed=seed)


@pytest.mark.parametrize("which", ["expected_teacher384_sha256", "expected_legacy8_sha256"])
def test_constructor_authenticates_both_donor_files(donors, which):
    with pytest.raises(ValueError):
        create(donors, **{which: "f" * 64})


@pytest.mark.parametrize("field,value", [
    ("schema", "other"), ("architecture", "single-head"), ("dimension", True),
    ("dimension", 384), ("domain_id", "security_ir"), ("source_profile_id", "gte-small"),
    ("seed", -1), ("seed", True), ("primary_sha256", "a" * 64),
    ("legacy8_sha256", "a" * 64), ("connector_sha256", "a" * 64),
    ("representation_id", "legacy_alias"), ("implementation", {}),
    ("optimizer", {"mode": "resume", "state": {}, "resume": True}),
    ("optimizer", {"mode": "fresh", "state": None, "resume": 0}),
    ("training_executed", True), ("decoder_parameters_random", 0),
    ("distillation_executed", 1), ("source_fidelity_qualified", True),
])
def test_dual_bundle_tampering_fails(initialized, field, value):
    bundle = deepcopy(initialized[1])
    pins = deepcopy(bundle["donor_pins"])
    bundle[field] = value
    with pytest.raises(ValueError):
        inspect(bundle, pins)


def test_unknown_missing_fields_and_valid_but_inconsistent_seed_rejected(initialized):
    for mutate in (lambda b: b.update(unknown=False), lambda b: b.pop("legacy8"),
                   lambda b: b.update(seed=b["seed"] + 1)):
        bundle = deepcopy(initialized[1])
        pins = deepcopy(bundle["donor_pins"])
        mutate(bundle)
        with pytest.raises(ValueError):
            inspect(bundle, pins)


@pytest.mark.parametrize("field,value", [
    ("merge_logits", True), ("merge_logits", 0), ("separate_vocabularies", 1),
    ("reference_prefix_required_for_kd", 1), ("qualified_teacher_scope_required_for_kd", False),
    ("auxiliary_input_width", 384), ("primary_head", "legacy_formula"),
])
def test_loss_contract_tampering_and_integer_boolean_aliases_rejected(initialized, field, value):
    bundle = deepcopy(initialized[1])
    bundle["loss_contract"][field] = value
    with pytest.raises(ValueError):
        inspect(bundle)


@pytest.mark.parametrize("field", sorted(subject.PIN_FIELDS))
def test_every_external_donor_pin_is_enforced(initialized, field):
    pins = deepcopy(initialized[1]["donor_pins"])
    pins[field] = "f" * 64
    with pytest.raises(ValueError):
        inspect(initialized[1], pins)
    with pytest.raises(ValueError):
        reload(initialized[1], pins)


def test_missing_unknown_or_malformed_external_pins_rejected(initialized):
    variants = [None, {}, {**initialized[1]["donor_pins"], "unexpected": "a" * 64}]
    for wrong in (True, "A" * 64, "short"):
        pins = deepcopy(initialized[1]["donor_pins"])
        pins["legacy8_weights_sha256"] = wrong
        variants.append(pins)
    for pins in variants:
        with pytest.raises(ValueError):
            subject.inspect_dual_decoder(initialized[1], expected_donor_pins=pins)


@pytest.mark.parametrize("kind", ["shape", "nonfinite", "boolean", "float32_rounding"])
def test_connector_payload_tampering_rejected(initialized, kind):
    bundle = deepcopy(initialized[1])
    if kind == "shape":
        bundle["connector"]["weight"].pop()
    elif kind == "nonfinite":
        bundle["connector"]["bias"][0] = float("inf")
    elif kind == "boolean":
        bundle["connector"]["bias"][0] = True
    else:
        # A valid finite Python float need not be an exact float32 value.
        bundle["connector"]["bias"][0] = .1
    if kind != "nonfinite":
        bundle["connector_sha256"] = subject.digest(bundle["connector"])
        bundle["representation_id"] = subject._identity(bundle)
    with pytest.raises(ValueError):
        reload(bundle, initialized[1]["donor_pins"])


def test_rehashed_primary_donor_weights_cannot_replace_external_donor(initialized):
    bundle = deepcopy(initialized[1])
    original_pins = deepcopy(bundle["donor_pins"])
    primary = bundle["primary"]
    primary["model_state"]["condition.bias"][0] += .01
    state = primary["model_state"]
    primary["weights_sha256"] = subject._PRIMARY.digest(state)
    inherited = {key: value for key, value in state.items() if key not in subject._PRIMARY._NEW}
    primary["donor"]["weights_sha256"] = subject._PRIMARY.digest(inherited)
    primary["tensor_inventory"] = subject._PRIMARY._inventory(state, subject._PRIMARY._shapes(primary["config"], primary["codec"]))
    primary["representation_id"] = subject._PRIMARY._identity(primary)
    bundle["primary_sha256"] = subject.digest(primary)
    bundle["representation_id"] = subject._identity(bundle)
    with pytest.raises(ValueError, match="primary donor"):
        inspect(bundle, original_pins)


def test_rehashed_legacy_donor_weights_cannot_replace_external_donor(initialized):
    bundle = deepcopy(initialized[1])
    original_pins = deepcopy(bundle["donor_pins"])
    legacy = bundle["legacy8"]
    legacy["model_state"]["output.bias"][0] += .01
    legacy["source_model_state_sha256"] = subject._LEGACY._digest(legacy["model_state"])
    identity = {"checkpoint_sha256": legacy["source_checkpoint_sha256"], "binding": legacy["binding"],
        "config": legacy["config"], "codec_sha256": legacy["source_codec_sha256"],
        "model_state_sha256": legacy["source_model_state_sha256"], "implementation": legacy["source_implementation"]}
    legacy["donor_identity_sha256"] = subject._LEGACY._digest(identity)
    bundle["legacy8_sha256"] = subject.digest(legacy)
    bundle["representation_id"] = subject._identity(bundle)
    with pytest.raises(ValueError, match="external model state"):
        inspect(bundle, original_pins)


def test_dual_bundle_keeps_primary_inherited_tensors_frozen(initialized):
    bundle = deepcopy(initialized[1])
    bundle["primary"]["freeze_inherited"] = False
    bundle["primary_sha256"] = subject.digest(bundle["primary"])
    bundle["representation_id"] = subject._identity(bundle)
    with pytest.raises(ValueError, match="frozen primary"):
        inspect(bundle, initialized[1]["donor_pins"])
