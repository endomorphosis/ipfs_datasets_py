"""Synthetic numerical/causality controls, never source-fidelity evidence."""
from copy import deepcopy
import json
import math
import re

import pytest

torch = pytest.importorskip("torch")
from ipfs_datasets_py.logic.formalization.autoencoder import decoder_cardinality_experiment as subject
from ipfs_datasets_py.logic.formalization.autoencoder import decoder_distillation_experiment as core
from ipfs_datasets_py.logic.formalization.autoencoder import decoder_distillation_experiment_v2 as prior
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_latent_formula as numerical


@pytest.fixture(autouse=True)
def single_cpu():
    old = torch.get_num_threads(); torch.set_num_threads(1)
    yield
    torch.set_num_threads(old)


def rule():
    return dict(modality="O", actor="agency", action="save", object="report",
        conditions=[], exceptions=[], temporal=[])


def tokens(text):
    return re.findall(r'"(?:[^"\\]|\\.)*"|[{}\[\],:]|true|false|[0-9]+', text)


def setup(dimension=384, mode="every_step"):
    lexemes = [json.dumps(s) for s in (*subject.FIELDS, "rules", "O", "P", "F", "agency", "save",
        "report", "a", "b", "c", "d", "e", "bad", "unrelated", "}")]
    codec = dict(schema="typed-json-lexical/v1", target_vocabulary=["<pad>", "<bos>", "<eos>"]+
        sorted(set(lexemes+list('{}[],:')+["true", "1"])))
    body = numerical._model({"dimension": dimension}, codec,
        dict(seed=132, hidden_size=8, token_embedding_dim=8, projection_width=2))
    inherited = prior.bind_persistent_model(body, dimension=dimension, conditioning=mode)
    return inherited, codec


def encode(codec, value, *, complete=True):
    text = json.dumps(value, sort_keys=True, separators=(",", ":")) if not isinstance(value, str) else value
    ids = [codec["target_vocabulary"].index(token) for token in tokens(text)]
    return [1]+ids+([2] if complete else [])


def inputs(dimension=384, n=2):
    rng = torch.Generator().manual_seed(444)
    return torch.randn((n, dimension), generator=rng)


@pytest.mark.parametrize("dimension", [8, 384, 768])
@pytest.mark.parametrize("guide", [False, True])
def test_zero_head_preserves_exact_logits_and_inherited_weights(dimension, guide):
    inherited, codec = setup(dimension)
    before, rng = core.tensor_digest(inherited), torch.get_rng_state().clone()
    model = subject.bind_cardinality_model(inherited, codec=codec, guide_boundary=guide)
    assert core.tensor_digest(inherited) == core.tensor_digest(model.body) == before
    assert torch.equal(rng, torch.get_rng_state())
    source = inputs(dimension)
    prefix = torch.tensor([encode(codec, {"rules": [rule(), rule()]})]*2)
    old_projected, old_logits = inherited(source, prefix)
    projected, logits = model(source, prefix)
    assert torch.equal(projected, old_projected) and torch.equal(logits, old_logits)
    assert torch.count_nonzero(model.count_logits(projected)) == 0
    assert model.describe()["count_classes"] == list(range(1, 33))
    assert all(model.describe()[key] is False for key in subject.FALSE)


def test_guided_and_unguided_modes_have_identical_parameters():
    inherited, codec = setup()
    first = subject.bind_cardinality_model(inherited, codec=codec, guide_boundary=False)
    second = subject.bind_cardinality_model(inherited, codec=codec, guide_boundary=True)
    assert core.tensor_digest(first) == core.tensor_digest(second)
    assert [(name, p.numel(), p.requires_grad) for name, p in first.named_parameters()] == [
        (name, p.numel(), p.requires_grad) for name, p in second.named_parameters()]
    assert first.describe()["guide_boundary"] is False and second.describe()["guide_boundary"] is True


@pytest.mark.parametrize("constant", [0., 3., -20.])
def test_uniform_logits_have_exact_zero_odds_at_every_supported_boundary(constant):
    values = torch.full((34, 32), constant)
    correction = subject.boundary_log_odds(values, torch.arange(34))
    assert torch.equal(correction, torch.zeros(34))


def test_odds_matches_declared_count_vs_remaining_counts_and_is_differentiable():
    logits = torch.linspace(-1., 1., 32).repeat(3, 1).requires_grad_()
    counts = torch.tensor([1, 7, 31])
    actual = subject.boundary_log_odds(logits, counts)
    expected = torch.stack([row[k-1]-torch.logsumexp(row[k:], 0)+math.log(32-k)
        for row, k in zip(logits, counts.tolist())])
    assert torch.allclose(actual, expected, atol=2e-7, rtol=1e-6)
    actual.sum().backward()
    assert logits.grad is not None and bool(torch.isfinite(logits.grad).all()) and logits.grad.abs().sum() > 0


def test_count_loss_trains_new_head_from_source_without_touching_caller():
    inherited, codec = setup()
    before = core.tensor_digest(inherited)
    model = subject.bind_cardinality_model(inherited, codec=codec)
    logits = model.count_logits(model.project(inputs()))
    torch.nn.functional.cross_entropy(logits, torch.tensor([0, 7])).backward()
    assert model.count_head.weight.grad is not None and model.count_head.weight.grad.abs().sum() > 0
    assert model.count_head.bias.grad is not None and model.count_head.bias.grad.abs().sum() > 0
    assert all(p.grad is None for p in inherited.parameters()) and core.tensor_digest(inherited) == before


def test_generation_loss_can_train_count_head_only_at_recognized_boundaries():
    inherited, codec = setup()
    model = subject.bind_cardinality_model(inherited, codec=codec, guide_boundary=True)
    prefix = torch.tensor([encode(codec, {"rules": [rule()]})]*2)
    _, logits = model(inputs(), prefix)
    closing = codec["target_vocabulary"].index("]")
    logits[:, :, closing].sum().backward()
    assert model.count_head.weight.grad is not None and model.count_head.weight.grad.abs().sum() > 0


def test_guidance_alters_only_next_closing_array_logit_at_complete_rule_close():
    inherited, codec = setup()
    guided = subject.bind_cardinality_model(inherited, codec=codec, guide_boundary=True)
    plain = subject.bind_cardinality_model(inherited, codec=codec, guide_boundary=False)
    with torch.no_grad(): guided.count_head.bias[0] = 2.
    plain.load_state_dict(guided.state_dict())
    prefix = torch.tensor([encode(codec, {"rules": [rule(), rule()]})]*2)
    source = inputs()
    _, expected = plain(source, prefix)
    _, actual = guided(source, prefix)
    difference = actual-expected
    tables = subject._tables(codec, len(codec["target_vocabulary"]), torch)
    _, boundaries = subject._scan_prefix(prefix.tolist(), [[0]*6]*2, tables)
    closing = codec["target_vocabulary"].index("]")
    allowed = torch.zeros_like(difference, dtype=torch.bool)
    for batch, offset, _ in boundaries: allowed[batch, offset, closing] = True
    assert torch.count_nonzero(difference[~allowed]) == 0
    assert torch.count_nonzero(difference[allowed]) > 0
    assert guided.describe()["guidance_forces_closure"] is False


@pytest.mark.parametrize("guided", [False, True])
def test_full_prefix_and_incremental_are_equivalent_and_state_is_immutable(guided):
    inherited, codec = setup()
    model = subject.bind_cardinality_model(inherited, codec=codec, guide_boundary=guided)
    with torch.no_grad(): model.count_head.bias.copy_(torch.arange(32)/10.)
    prefix = torch.tensor([encode(codec, {"rules": [rule(), rule()]})]*2)
    state = model.start(model.project(inputs()))
    original = tuple(part.clone() for part in state)
    full, full_state = model.next_logits(prefix, state)
    partial, outputs = state, []
    for offset in range(prefix.shape[1]):
        logits, partial = model.next_logits(prefix[:, offset:offset+1], partial)
        outputs.append(logits)
    assert torch.allclose(full, torch.cat(outputs, 1), atol=2e-7, rtol=1e-6)
    assert all(torch.equal(left, right) for left, right in zip(state, original))
    assert torch.equal(full_state[-1], partial[-1]) and torch.equal(full_state[2], partial[2])
    assert full_state[-1][:, 3].tolist() == [2, 2]
    assert full_state[-1][:, 0].tolist() == [17, 17]
    assert partial[3] is state[3]


def test_no_future_prefix_token_influences_earlier_corrections():
    inherited, codec = setup()
    model = subject.bind_cardinality_model(inherited, codec=codec, guide_boundary=True)
    with torch.no_grad(): model.count_head.bias[0] = 2.
    good = encode(codec, {"rules": [rule(), rule()]})
    bad = good[:]
    bad[-4] = codec["target_vocabulary"].index('"bad"')
    state = model.start(model.project(inputs(n=1)))
    first, _ = model.next_logits(torch.tensor([good]), state)
    second, _ = model.next_logits(torch.tensor([bad]), state)
    assert torch.equal(first[:, :-4], second[:, :-4])


@pytest.mark.parametrize("text", [
    '{"unrelated":[{"action":"save"}]}',
    '{"rules":[{}]}',
    '{"rules":[{"action":"save","action":"save","actor":"agency","conditions":[],"exceptions":[],"modality":"O","object":"report","temporal":[]}]}',
    '{"rules":[{"action":{"object":"report"},"actor":"agency","conditions":[],"exceptions":[],"modality":"O","object":"report","temporal":[]}]}',
    '{"rules":[{"action":"save","actor":"agency","conditions":["b","a"],"exceptions":[],"modality":"O","object":"report","temporal":[]}]}',
    '{"rules":[{"action":"save","actor":"agency","conditions":["a","a"],"exceptions":[],"modality":"O","object":"report","temporal":[]}]}',
    '{"rules":[{"action":"save","actor":"agency","conditions":["a","b","c","d","e"],"exceptions":[],"modality":"O","object":"report","temporal":[]}]}',
    '{"rules":[{"action":"save","actor":"agency","conditions":[],"exceptions":[],"modality":"bad","object":"report","temporal":[]}]}',
    '{"rules":[{"action":"save","actor":"agency","conditions":[true],"exceptions":[],"modality":"O","object":"report","temporal":[]}]}',
])
def test_invalid_or_unrelated_prefix_never_creates_a_boundary(text):
    inherited, codec = setup()
    model = subject.bind_cardinality_model(inherited, codec=codec, guide_boundary=True)
    plain = subject.bind_cardinality_model(inherited, codec=codec, guide_boundary=False)
    with torch.no_grad(): model.count_head.bias[0] = 3.
    plain.load_state_dict(model.state_dict())
    # A later syntactically valid fragment cannot reset the invalid recognizer.
    prefix = torch.tensor([encode(codec, text)+encode(codec, {"rules": [rule()]})])
    source = inputs(n=1)
    _, guided_logits = model(source, prefix)
    _, original_logits = plain(source, prefix)
    assert torch.equal(guided_logits, original_logits)
    _, state = model.next_logits(prefix, model.start(model.project(source)))
    assert state[-1][0, 0] == subject._INVALID and state[-1][0, 3] == 0


def test_string_containing_brace_is_not_a_structural_close():
    inherited, codec = setup()
    modified = rule(); modified["object"] = "}"
    prefix = [encode(codec, {"rules": [modified]})]
    tables = subject._tables(codec, len(codec["target_vocabulary"]), torch)
    state, boundaries = subject._scan_prefix(prefix, [[0]*6], tables)
    assert len(boundaries) == 1 and prefix[0][boundaries[0][1]] == codec["target_vocabulary"].index("}")
    assert state[0][3] == 1


def test_count32_and_later_do_not_receive_guidance():
    _, codec = setup()
    tables = subject._tables(codec, len(codec["target_vocabulary"]), torch)
    # A direct lexical parser test avoids exceeding the unchanged1024 budget.
    state, boundaries = subject._scan_prefix([encode(codec, {"rules": [rule()]*33})], [[0]*6], tables)
    assert state[0][3] == 33
    assert [item[2] for item in boundaries] == list(range(1, 32))
    assert torch.equal(subject.boundary_log_odds(torch.arange(32).float().repeat(2, 1), torch.tensor([32, 33])), torch.zeros(2))


def test_interleaved_requests_do_not_share_counts_or_parser_state():
    inherited, codec = setup()
    model = subject.bind_cardinality_model(inherited, codec=codec, guide_boundary=True)
    with torch.no_grad(): model.count_head.weight.fill_(.2)
    source = inputs()
    first = model.start(model.project(source[:1])); second = model.start(model.project(source[1:]))
    prefix = torch.tensor([encode(codec, {"rules": [rule()]})])
    expected, expected_state = model.next_logits(prefix, first)
    split = 9
    left, ongoing = model.next_logits(prefix[:, :split], first)
    model.next_logits(prefix, second)
    right, final = model.next_logits(prefix[:, split:], ongoing)
    assert torch.allclose(expected, torch.cat([left, right], 1), atol=2e-7, rtol=1e-6)
    assert torch.equal(expected_state[-1], final[-1])
    assert torch.count_nonzero(first[-1]) == torch.count_nonzero(second[-1]) == 0


def test_zero_condition_control_removes_all_source_paths_and_retains_count_bias():
    inherited, codec = setup()
    model = subject.bind_cardinality_model(inherited, codec=codec, guide_boundary=True)
    with torch.no_grad():
        model.body.source_to_embedding.weight.fill_(.1)
        model.count_head.weight.fill_(.2)
        model.count_head.bias.copy_(torch.arange(32)/10.)
    before = core.tensor_digest(model)
    control = subject.bind_zero_condition_model(model)
    source = inputs()
    projected = control.project(source)
    count_logits = control.count_logits(projected)
    assert torch.equal(count_logits, model.count_head.bias.unsqueeze(0).expand(2, -1))
    state = control.start(projected)
    assert torch.count_nonzero(state[0]) == torch.count_nonzero(state[1]) == 0
    assert torch.equal(state[3], count_logits)
    prefix = torch.tensor([encode(codec, {"rules": [rule()]})]*2)
    logits, final = control.next_logits(prefix, state)
    assert torch.equal(logits[0], logits[1])
    assert not torch.equal(projected[0], projected[1])
    assert final[2].tolist() == [prefix.shape[1]]*2 and final[-1][:, 3].tolist() == [1]*2
    assert core.tensor_digest(model) == before
    assert all(value is False for key, value in control.describe().items() if key in subject.FALSE)


def test_geometry_mode_and_codec_fail_closed():
    inherited, codec = setup()
    with pytest.raises(ValueError): subject.bind_cardinality_model(inherited, codec=codec, guide_boundary=1)
    wrong = deepcopy(codec); wrong["target_vocabulary"] = wrong["target_vocabulary"][:-1]
    with pytest.raises(ValueError): subject.bind_cardinality_model(inherited, codec=wrong)
    with pytest.raises(ValueError): subject.bind_cardinality_model(inherited.body, codec=codec)


def test_auxiliary_state_roundtrip_and_shared_core_finiteness():
    inherited, codec = setup()
    first = subject.bind_cardinality_model(inherited, codec=codec, guide_boundary=True)
    second = subject.bind_cardinality_model(inherited, codec=codec, guide_boundary=True)
    with torch.no_grad(): first.count_head.bias[5] = 3.
    second.load_state_dict(first.state_dict(), strict=True)
    assert core.tensor_digest(first) == core.tensor_digest(second)
    state = first.start(first.project(inputs()))
    assert core._finite(torch, state)
    with pytest.raises(RuntimeError): inherited.load_state_dict(first.state_dict(), strict=True)


def test_codec_binding_is_captured_not_mutable_caller_metadata():
    inherited, codec = setup()
    expected = core.digest(codec)
    model = subject.bind_cardinality_model(inherited, codec=codec)
    codec["schema"] = "caller-modified-after-bind"
    assert model.describe()["codec_sha256"] == expected


def test_partial_qualifier_lists_and_rules_never_look_ahead_to_create_boundaries():
    _, codec = setup()
    tables = subject._tables(codec, len(codec["target_vocabulary"]), torch)
    target = rule(); target["conditions"] = ["a", "b"]
    ids = encode(codec, {"rules": [target]})
    _, full = subject._scan_prefix([ids], [[0]*6], tables)
    assert len(full) == 1
    boundary_offset = full[0][1]
    for end in range(1, boundary_offset+1):
        _, boundaries = subject._scan_prefix([ids[:end]], [[0]*6], tables)
        assert boundaries == []
    _, boundaries = subject._scan_prefix([ids[:boundary_offset+1]], [[0]*6], tables)
    assert boundaries == full
