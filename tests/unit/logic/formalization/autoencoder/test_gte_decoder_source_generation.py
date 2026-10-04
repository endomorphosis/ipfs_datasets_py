"""Real decoder greedy generation on explicitly synthetic archived donors."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[5]
PATH = ROOT / "ipfs_datasets_py/logic/formalization/autoencoder/gte_decoder_source_generation.py"


def read_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


subject = read_module("gte_source_generation_subject", PATH)
replay_fixture = read_module("gte_source_generation_fixture", Path(__file__).with_name("test_gte_decoder_transfer_replay.py"))
torch = pytest.importorskip("torch")
CASES = [("donor384", "primary384"), ("legacy8", "legacy8"),
         ("student768", "primary384"), ("student768", "legacy8")]


@pytest.fixture(scope="module", autouse=True)
def single_thread():
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    yield
    torch.set_num_threads(previous)


@pytest.fixture(scope="module")
def fixture(tmp_path_factory):
    return replay_fixture.inputs.__wrapped__(tmp_path_factory)


def model_for(fixture, variant):
    replay = replay_fixture.subject
    if variant == "donor384":
        return replay._original_primary_model(torch, fixture["primary"])
    if variant == "legacy8":
        return replay._helper("gte_legacy8_decoder_donor").load_private_legacy8_decoder_snapshot(
            fixture["initialization"]["legacy8"],
            expected_source_checkpoint_sha256=fixture["pins"]["legacy8_checkpoint_sha256"],
            expected_source_model_state_sha256=fixture["pins"]["legacy8_weights_sha256"])["model"]
    return replay._helper("gte_decoder_reuse").load_dual_decoder(fixture["initialization"],
        expected_donor_pins=fixture["pins"])


def arguments(fixture, variant, head, **changes):
    width = subject.VARIANTS[variant][head]
    vector = [1.] + [0.] * (width - 1)
    arguments = {"variant": variant, "head": head, "input_vector": vector,
        "max_new_tokens": 12, "inherited_max_target_tokens":
            fixture["initialization"]["primary" if head == "primary384" else "legacy8"]["config"]["max_target_tokens"]}
    arguments.update(changes)
    return arguments


def output_head(model, variant, head):
    return (model.primary if head == "primary384" else model.legacy8) if variant == "student768" else model


def constant_output(model, variant, head, token):
    part = output_head(model, variant, head)
    with torch.no_grad():
        part.output.weight.zero_()
        part.output.bias.fill_(-5.)
        part.output.bias[token] = 5.


def manual(model, variant, head, arguments):
    """Independent complete-prefix autoregression through whole model.forward."""
    vector = torch.tensor([arguments["input_vector"]], dtype=torch.float32)
    ids, audits = [1], []
    inactive = torch.tensor([[1]], dtype=torch.int64)
    with torch.no_grad():
        for _ in range(min(arguments["max_new_tokens"], arguments["inherited_max_target_tokens"] - 1)):
            prefix = torch.tensor([ids], dtype=torch.int64)
            if variant == "student768":
                result = model(vector, prefix if head == "primary384" else inactive,
                               prefix if head == "legacy8" else inactive)
                raw = result["primary_logits" if head == "primary384" else "auxiliary_logits"][0, -1]
            else:
                raw = model(vector, prefix)[2 if variant == "donor384" else 1][0, -1]
            token = int(raw.argmax().item())
            audits.append((deepcopy(ids), subject.digest(raw.tolist()), token))
            ids.append(token)
            if token == 2:
                break
    return ids, audits


def test_import_is_dependency_free():
    code = """import importlib.util,sys
spec=importlib.util.spec_from_file_location('source_generation',sys.argv[1])
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
assert not any(name in sys.modules for name in ('torch','numpy','transformers','ipfs_datasets_py'))
"""
    subprocess.run([sys.executable, "-I", "-c", code, str(PATH)], check=True)


@pytest.mark.parametrize("variant,head", CASES)
def test_raw_autoregression_matches_independent_manual_model_calls(fixture, variant, head):
    model = model_for(fixture, variant)
    args = arguments(fixture, variant, head)
    ids, audits = manual(model, variant, head, args)
    receipt = subject.generate_source_only(model, **args)
    assert receipt["generated_ids"] == ids
    assert set(receipt) == subject.GENERATION_FIELDS
    assert receipt["input_vector_sha256"] == subject.digest(args["input_vector"])
    for index, (prefix, logits_sha, token) in enumerate(audits):
        step = receipt["steps"][index]
        assert step["prefix_length"] == len(prefix)
        assert step["prefix_sha256"] == subject.digest(prefix)
        assert step["raw_logits_sha256"] == logits_sha
        assert step["next_token_id"] == token
        assert "prefix_ids" not in step
    assert subject.inspect_source_only_generation(receipt)["execution_authenticated"] is False


@pytest.mark.parametrize("variant,head", CASES)
def test_eos_is_emitted_and_stops_after_one_real_step(fixture, variant, head):
    model = model_for(fixture, variant)
    constant_output(model, variant, head, 2)
    receipt = subject.generate_source_only(model, **arguments(fixture, variant, head))
    assert receipt["generated_ids"] == [1, 2]
    assert receipt["step_count"] == 1
    assert receipt["terminated"] is True and receipt["truncated"] is False
    assert receipt["stop_reason"] == "eos"


@pytest.mark.parametrize("variant,head", CASES)
@pytest.mark.parametrize("token", [0, 1])
def test_invalid_pad_and_extra_bos_are_not_masked_or_omitted(fixture, variant, head, token):
    model = model_for(fixture, variant)
    constant_output(model, variant, head, token)
    receipt = subject.generate_source_only(model, **arguments(fixture, variant, head, max_new_tokens=3))
    assert receipt["generated_ids"] == [1, token, token, token]
    assert receipt["terminated"] is False and receipt["truncated"] is True
    assert receipt["stop_reason"] == "token_limit"
    assert receipt["step_count"] == 3


@pytest.mark.parametrize("variant,head", CASES[:2])
def test_inherited_budget_includes_bos_without_off_by_one(fixture, variant, head):
    model = model_for(fixture, variant)
    constant_output(model, variant, head, 3)
    receipt = subject.generate_source_only(model, **arguments(fixture, variant, head,
        max_new_tokens=20, inherited_max_target_tokens=4))
    assert receipt["effective_max_new_tokens"] == 3
    assert receipt["generated_ids"] == [1, 3, 3, 3]


@pytest.mark.parametrize("variant,head", CASES)
def test_requested_one_token_cap_emits_exactly_one_token(fixture, variant, head):
    model = model_for(fixture, variant)
    constant_output(model, variant, head, 3)
    receipt = subject.generate_source_only(model, **arguments(fixture, variant, head, max_new_tokens=1))
    assert receipt["generated_ids"] == [1, 3]
    assert receipt["step_count"] == receipt["effective_max_new_tokens"] == 1


@pytest.mark.parametrize("variant,head", CASES)
def test_actual_received_prefixes_are_generated_ids_only(fixture, monkeypatch, variant, head):
    model = model_for(fixture, variant)
    constant_output(model, variant, head, 3)
    captured = []
    if variant == "student768" and head == "primary384":
        owner, name = model.primary, "decode_from_condition"
    else:
        owner, name = (model.legacy8 if variant == "student768" else model), "forward"
    original = getattr(owner, name)

    def observed(source, prefix):
        captured.append(prefix.tolist()[0])
        assert prefix.tolist()[0] == [1] + [3] * (len(captured) - 1)
        return original(source, prefix)

    monkeypatch.setattr(owner, name, observed)
    receipt = subject.generate_source_only(model, **arguments(fixture, variant, head, max_new_tokens=4))
    assert captured == [[1], [1, 3], [1, 3, 3], [1, 3, 3, 3]]
    for prefix, step in zip(captured, receipt["steps"]):
        assert step["prefix_sha256"] == subject.digest(prefix)


@pytest.mark.parametrize("variant,head", CASES)
def test_all_parameters_nonpersistent_buffers_existing_gradients_and_context_are_preserved(fixture, variant, head):
    model = model_for(fixture, variant)
    model.train()
    model.decoder.eval() if variant != "student768" else model.primary.decoder.eval()
    first = next(model.parameters())
    first.grad = torch.full_like(first, .25)
    state = {name: value.detach().clone() for name, value in model.state_dict().items()}
    buffers = {name: value.detach().clone() for name, value in model.named_buffers()}
    pointers = {name: value.untyped_storage().data_ptr() for name, value in model.named_parameters()}
    gradients = {name: value.grad for name, value in model.named_parameters()}
    modes = [part.training for part in model.modules()]
    rng = torch.get_rng_state().clone()
    previous = torch.get_num_threads()
    torch.set_num_threads(2)
    args = arguments(fixture, variant, head, max_new_tokens=2)
    original_args = deepcopy(args)
    try:
        receipt = subject.generate_source_only(model, **args)
        assert torch.get_num_threads() == 2
    finally:
        torch.set_num_threads(previous)
    assert torch.equal(rng, torch.get_rng_state())
    assert modes == [part.training for part in model.modules()]
    assert args == original_args
    assert len(state) == (30 if variant == "student768" else 13)
    assert all(torch.equal(value, model.state_dict()[name]) for name, value in state.items())
    assert all(torch.equal(value, dict(model.named_buffers())[name]) for name, value in buffers.items())
    assert pointers == {name: value.untyped_storage().data_ptr() for name, value in model.named_parameters()}
    assert all(value.grad is gradients[name] for name, value in model.named_parameters())
    assert torch.equal(first.grad, torch.full_like(first, .25))
    assert receipt["optimizer_created"] is False and receipt["optimizer_steps"] == 0
    assert all(receipt[key] is True for key in subject.TRUE_FLAGS)


@pytest.mark.parametrize("change", [
    {"variant": "unknown"}, {"head": "unknown"}, {"variant": "legacy8", "head": "primary384"},
    {"max_new_tokens": True}, {"max_new_tokens": 0}, {"max_new_tokens": 1025},
    {"inherited_max_target_tokens": True}, {"inherited_max_target_tokens": 3},
    {"inherited_max_target_tokens": 1025}, {"input_vector": [0.] * 8},
    {"input_vector": [True] * 384}, {"input_vector": [float("nan")] * 384},
    {"input_vector": [10**1000] + [0.] * 383},
])
def test_bad_controls_and_input_fail_before_importing_torch(tmp_path, change):
    args = {"variant": "donor384", "head": "primary384", "input_vector": [0.] * 384,
            "max_new_tokens": 4, "inherited_max_target_tokens": 512, **change}
    payload = tmp_path / "arguments.json"
    payload.write_text(json.dumps(args))
    code = """import builtins,importlib.util,json,sys
spec=importlib.util.spec_from_file_location('source_generation',sys.argv[1])
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
original=builtins.__import__
def admitted(name,*args,**kwargs):
    assert name.split('.')[0] not in ('torch','numpy','transformers'), name
    return original(name,*args,**kwargs)
builtins.__import__=admitted
try: module.generate_source_only(None,**json.load(open(sys.argv[2])))
except ValueError: pass
else: raise AssertionError('invalid numerical generation admitted')
assert 'torch' not in sys.modules
"""
    subprocess.run([sys.executable, "-I", "-c", code, str(PATH), str(payload)], check=True)


def test_input_float32_overflow_is_rejected(fixture):
    model = model_for(fixture, "donor384")
    with pytest.raises(ValueError, match="overflows"):
        subject.generate_source_only(model, **arguments(fixture, "donor384", "primary384",
            input_vector=[1e100] + [0.] * 383))


def test_reference_fields_are_not_accepted_by_numerical_api(fixture):
    with pytest.raises(TypeError, match="reference"):
        subject.generate_source_only(model_for(fixture, "donor384"),
            **arguments(fixture, "donor384", "primary384"), reference_prefix=[1, 3, 2])


def test_nonfinite_outputs_fail_and_restore_rng_threads_and_modes(fixture, monkeypatch):
    model = model_for(fixture, "donor384")
    model.train()
    rng = torch.get_rng_state().clone()
    previous_threads = torch.get_num_threads()
    modes = [part.training for part in model.modules()]
    original = model.forward

    def nonfinite(vector, prefix):
        torch.rand(3)
        projected, condition, logits = original(vector, prefix)
        logits[0, -1, 0] = float("nan")
        return projected, condition, logits

    monkeypatch.setattr(model, "forward", nonfinite)
    with pytest.raises(ValueError, match="finite detached"):
        subject.generate_source_only(model, **arguments(fixture, "donor384", "primary384"))
    assert torch.equal(rng, torch.get_rng_state())
    assert torch.get_num_threads() == previous_threads
    assert modes == [part.training for part in model.modules()]


def test_source_vector_signed_zero_mutation_is_detected(fixture, monkeypatch):
    model = model_for(fixture, "donor384")
    original = model.forward

    def mutated(vector, prefix):
        vector[0, 1] = -0.
        return original(vector, prefix)

    monkeypatch.setattr(model, "forward", mutated)
    with pytest.raises(ValueError, match="changed source input"):
        subject.generate_source_only(model, **arguments(fixture, "donor384", "primary384", max_new_tokens=1))


@pytest.fixture(scope="module")
def receipt(fixture):
    model = model_for(fixture, "donor384")
    constant_output(model, "donor384", "primary384", 3)
    return subject.generate_source_only(model, **arguments(fixture, "donor384", "primary384", max_new_tokens=3))


@pytest.mark.parametrize("field,value", [
    ("optimizer_created", True), ("optimizer_steps", True), ("training_executed", True),
    ("proof_authority", True), ("qualification_executed", True), ("model_parameters_unchanged", False),
    ("model_state_sha256_after", "a" * 64), ("implementation_sha256", "a" * 64),
    ("step_count", True), ("truncated", False), ("terminated", True), ("generated_ids_sha256", "a" * 64),
])
def test_receipt_cannot_claim_updates_quality_or_mutated_bindings(receipt, field, value):
    changed = deepcopy(receipt)
    changed[field] = value
    with pytest.raises(ValueError):
        subject.inspect_source_only_generation(changed)


@pytest.mark.parametrize("field,value", [
    ("prefix_length", 10), ("prefix_sha256", "a" * 64), ("next_token_id", 4),
    ("input_vector_sha256", "a" * 64), ("step", True), ("raw_logits_sha256", "invalid"),
])
def test_compact_prefix_audit_rejects_target_or_foreign_prefixes(receipt, field, value):
    changed = deepcopy(receipt)
    changed["steps"][1][field] = value
    with pytest.raises(ValueError):
        subject.inspect_source_only_generation(changed)


def test_receipt_inspection_remains_dependency_free(receipt, tmp_path):
    path = tmp_path / "receipt.json"
    path.write_text(json.dumps(receipt))
    code = """import importlib.util,json,sys
spec=importlib.util.spec_from_file_location('source_generation',sys.argv[1])
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
result=module.inspect_source_only_generation(json.load(open(sys.argv[2])))
assert result['execution_authenticated'] is False
assert result['teacher_qualified'] is False
assert not any(name in sys.modules for name in ('torch','numpy','transformers','ipfs_datasets_py'))
"""
    subprocess.run([sys.executable, "-I", "-c", code, str(PATH), str(path)], check=True)
