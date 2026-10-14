"""V2 source eligibility and byte order remain learned, isolated and restorable."""
from copy import deepcopy
import json

import pytest
import torch

from ipfs_datasets_py.logic.autoformal import legal_coordination as bridge
from ipfs_datasets_py.logic.deontic import coordination, coordination_decoder as semantic
from ipfs_datasets_py.logic.deontic.utils import deontic_parser
from ipfs_datasets_py.logic.formalization.autoencoder import legal_grouped_span_decoder as v1
from ipfs_datasets_py.logic.formalization.autoencoder import legal_grouped_span_decoder_v2 as v2


SOURCE = "The Secretary shall publish the notice or shall retain the record."
SCOPES = ("modal_over_actions", "disjunction_of_norms")
STRUCTURAL_PREFIXES = ("count_head.", "scope_head.", "modality_head.", "pointer_keys.",
                       "pointer_queries.", "slot_queries.", "attention_keys.", "slot_fusion.")


@pytest.fixture(scope="module", autouse=True)
def small_cpu_thread_pool():
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    yield
    torch.set_num_threads(previous)


def model():
    return v2.GroupedSpanDecoder(v2.SpanDecoderConfig(
        seed=1729, token_dim=16, token_hidden=16, slot_hidden=24, max_tokens=64))


def span(label):
    start = SOURCE.index(label)
    return start, start + len(label)


def positive(scope=SCOPES[0]):
    return v2.GroupedSpanExample(SOURCE, scope, tuple(
        v2.GroupedSpanTarget(span("The Secretary"), span(action), "O")
        for action in ("publish the notice", "retain the record")), supported=True)


def negative():
    return v2.GroupedSpanExample("The Secretary published the notice yesterday.", SCOPES[0], (), supported=False)


def forbid_teacher(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("v2 inference consulted parser, teacher, labels or the v1 predictor")
    for module, names in (
        (coordination, ("build_coordination_groups", "reconstruct_source", "validate_coordination_group")),
        (deontic_parser, ("extract_normative_elements", "analyze_normative_sentence", "_unresolved_duty_disjunction_groups")),
        (bridge, ("compile_coordination_group", "reconstruct_compiled_group", "coordination_decode_request_from_compiled")),
        (v2, ("_labels", "GroupedSpanTarget", "GroupedSpanExample")),
        (v1, ("predict_grouped_span_decoder", "_encoded_sources")),
    ):
        for name in names:
            monkeypatch.setattr(module, name, forbidden)


def parameter_snapshot(net):
    return {key: value.detach().clone() for key, value in net.named_parameters()}


def assert_checkpoint_numerical_state_equal(left, right):
    assert set(left.state_dict()) == set(right.state_dict())
    for key, value in left.state_dict().items():
        assert torch.equal(value, right.state_dict()[key]), key


@pytest.mark.parametrize("scope", SCOPES)
def test_actual_v2_forward_sees_only_entire_source_and_explicit_scope(monkeypatch, scope):
    net = model()
    tokens = v2.tokenize_source(SOURCE, net.config)
    calls = []
    def trace(module, args):
        assert module is net and len(args) == 3
        token_bytes, mask, caller_scope = args
        actual = [bytes(value - 1 for value in token.tolist() if value).decode() for token in token_bytes[0]]
        assert actual == [token.text for token in tokens]
        assert mask.all() and caller_scope.tolist() == [SCOPES.index(scope)]
        calls.append(actual)
    hook = net.register_forward_pre_hook(trace)
    forbid_teacher(monkeypatch)
    result = v2.predict_grouped_span_decoder(net, SOURCE, scope)
    hook.remove()
    assert len(calls) == 1
    assert result["status"] in {"predicted", "blocked", "abstained"}
    assert result["proof_ready"] is result["source_semantics_verified"] is False
    assert result["targets_used_at_inference"] is False


@pytest.mark.parametrize("scope", [None, "", "unknown"])
def test_undeclared_scope_abstains_before_encoding_or_numerical_forward(monkeypatch, scope):
    net = model()
    def forbidden(*args, **kwargs):
        raise AssertionError("missing declaration reached inference")
    monkeypatch.setattr(v2, "_encoded_sources", forbidden)
    monkeypatch.setattr(net, "forward", forbidden)
    result = v2.predict_grouped_span_decoder(net, SOURCE, scope)
    assert result["status"] == "abstained" and result["request"] is None
    assert result["blockers"] == ["explicit_caller_scope_required"]


def test_negative_support_training_cannot_create_structural_gradients_or_adam_state(monkeypatch):
    net = model()
    optimizer = v2.make_grouped_span_optimizer(net, weight_decay=0.1)
    before = parameter_snapshot(net)
    def no_structural_targets(*args, **kwargs):
        raise AssertionError("unsupported examples requested structural labels")
    for name in ("CoordinationDecodeMember", "CoordinationDecodeRequest", "semantic_label_identity"):
        monkeypatch.setattr(semantic, name, no_structural_targets)
    losses = v2.train_grouped_span_step(net, optimizer, [negative()])
    assert losses["support_loss"] > 0
    assert losses["supported_examples"] == 0 and losses["unsupported_examples"] == 1
    assert all(losses[key + "_loss"] == 0 for key in ("count", "scope", "modality", *v2.POINTERS))
    structural_count = 0
    for name, parameter in net.named_parameters():
        if name.startswith(STRUCTURAL_PREFIXES):
            structural_count += 1
            assert parameter.grad is None, name
            assert parameter not in optimizer.state, name
            assert torch.equal(parameter, before[name]), name
    assert structural_count > 0
    assert any(parameter.grad is not None and torch.count_nonzero(parameter.grad)
               for name, parameter in net.named_parameters() if name.startswith("support_head."))
    convolutions = [module for module in net.modules() if isinstance(module, torch.nn.Conv1d)]
    assert len(convolutions) == 2
    assert all(module.weight.grad is not None and torch.count_nonzero(module.weight.grad) for module in convolutions)


def test_negative_step_after_positive_does_not_move_heads_through_adam_momentum_or_decay():
    net = model()
    optimizer = v2.make_grouped_span_optimizer(net, weight_decay=0.1)
    v2.train_grouped_span_step(net, optimizer, [positive()])
    before = parameter_snapshot(net)
    state_before = {name: deepcopy(optimizer.state[parameter]) for name, parameter in net.named_parameters()
                    if name.startswith(STRUCTURAL_PREFIXES)}
    v2.train_grouped_span_step(net, optimizer, [negative()])
    for name, parameter in net.named_parameters():
        if name.startswith(STRUCTURAL_PREFIXES):
            assert parameter.grad is None and torch.equal(parameter, before[name]), name
            for key, value in state_before[name].items():
                assert torch.equal(optimizer.state[parameter][key], value), (name, key)
    assert any(not torch.equal(parameter, before[name]) for name, parameter in net.named_parameters()
               if name.startswith("support_head."))


def test_mixed_batch_gradients_mask_only_unsupported_structural_rows():
    net = model()
    optimizer = v2.make_grouped_span_optimizer(net)
    observed = {}
    def trace(module, args, outputs):
        for key, tensor in outputs.items():
            tensor.retain_grad()
            observed[key] = tensor
    hook = net.register_forward_hook(trace)
    losses = v2.train_grouped_span_step(net, optimizer, [positive(), negative()])
    hook.remove()
    assert losses["supported_examples"] == losses["unsupported_examples"] == 1
    assert observed["support"].grad[0] < 0 < observed["support"].grad[1]
    for key in ("count", "scope", "modality", *v2.POINTERS):
        gradient = observed[key].grad
        assert gradient is not None
        assert torch.count_nonzero(gradient[0]) > 0, key
        assert torch.count_nonzero(gradient[1]) == 0, key


def test_partial_optimizer_checkpoint_restores_exact_next_positive_then_mixed_update(tmp_path):
    net = model()
    optimizer = v2.make_grouped_span_optimizer(net, weight_decay=0.1)
    v2.train_grouped_span_step(net, optimizer, [negative()])
    checkpoint = v2.save_grouped_span_checkpoint(net, optimizer, steps=1)
    path = tmp_path / "negative-only.json"
    path.write_text(json.dumps(checkpoint, allow_nan=False))
    restored, resumed_optimizer, steps = v2.restore_grouped_span_checkpoint(json.loads(path.read_text()))
    assert steps == 1
    assert_checkpoint_numerical_state_equal(net, restored)
    assert len(optimizer.state) < len(list(net.parameters()))
    assert v2.save_grouped_span_checkpoint(restored, resumed_optimizer, steps=steps) == checkpoint
    for index, batch in enumerate(([positive()], [positive(SCOPES[1]), negative()]), start=2):
        left = v2.train_grouped_span_step(net, optimizer, batch)
        right = v2.train_grouped_span_step(restored, resumed_optimizer, batch)
        assert left == right
        assert_checkpoint_numerical_state_equal(net, restored)
        assert v2.save_grouped_span_checkpoint(net, optimizer, steps=index) == v2.save_grouped_span_checkpoint(restored, resumed_optimizer, steps=index)
    assert len(optimizer.state) == len(list(net.parameters()))
    assert SOURCE not in path.read_text()


def test_interior_byte_order_changes_actual_numerical_output():
    net = model().eval()
    first, second = "Registrar", "Regitsrar"
    assert sorted(first) == sorted(second) and first[0] == second[0] and first[-1] == second[-1]
    texts = [SOURCE.replace("Secretary", actor) for actor in (first, second)]
    batch, _ = v2._encoded_sources(net.config, texts, [SCOPES[0], SCOPES[0]])
    with torch.no_grad():
        values = net(*batch)
    assert any(not torch.allclose(tensor[0], tensor[1], rtol=1e-6, atol=1e-8) for tensor in values.values())


def test_added_byte_padding_cannot_change_source_representation():
    net = model().eval()
    batch, _ = v2._encoded_sources(net.config, [SOURCE], [SCOPES[0]])
    token_bytes, mask, scope = batch
    padded = torch.nn.functional.pad(token_bytes, (0, 9))
    with torch.no_grad():
        first = net(token_bytes, mask, scope)
        second = net(padded, mask, scope)
    assert set(first) == set(second)
    for key in first:
        torch.testing.assert_close(first[key], second[key], rtol=1e-5, atol=1e-6, msg=key)


def test_learned_negative_support_abstains_without_teacher_or_pointer_repair(monkeypatch):
    net = model()
    batch, _ = v2._encoded_sources(net.config, [SOURCE], [SCOPES[0]])
    with torch.no_grad():
        values = net(*batch)
    values["support"] = torch.tensor([-20.0])
    monkeypatch.setattr(net, "forward", lambda *args: values)
    forbid_teacher(monkeypatch)
    result = v2.predict_grouped_span_decoder(net, SOURCE, SCOPES[0])
    assert result["status"] == "abstained" and result["request"] is None
    assert result["blockers"] == ["learned_source_unsupported"]
    assert result["proof_ready"] is result["source_semantics_verified"] is False


def test_v1_checkpoint_remains_readable_only_by_its_unchanged_version():
    old = v1.GroupedSpanDecoder(v1.SpanDecoderConfig(seed=1729, token_dim=16, token_hidden=16, slot_hidden=24, max_tokens=64))
    old_checkpoint = v1.save_grouped_span_checkpoint(old, v1.make_grouped_span_optimizer(old), steps=0)
    restored, optimizer, steps = v1.restore_grouped_span_checkpoint(old_checkpoint)
    assert_checkpoint_numerical_state_equal(old, restored)
    assert v1.save_grouped_span_checkpoint(restored, optimizer, steps=steps) == old_checkpoint
    with pytest.raises(ValueError):
        v2.restore_grouped_span_checkpoint(old_checkpoint)
    new = model()
    checkpoint = v2.save_grouped_span_checkpoint(new, v2.make_grouped_span_optimizer(new), steps=0)
    with pytest.raises(ValueError):
        v1.restore_grouped_span_checkpoint(checkpoint)
