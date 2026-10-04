"""Synthetic source-readout, causal-prefix and full-target binding checks."""
from copy import deepcopy
import json
import re

import pytest

torch = pytest.importorskip("torch")
from ipfs_datasets_py.logic.formalization.autoencoder import source_value_decoder_experiment as subject
from ipfs_datasets_py.logic.formalization.autoencoder import decoder_cardinality_experiment as count
from ipfs_datasets_py.logic.formalization.autoencoder import decoder_distillation_experiment as core
from ipfs_datasets_py.logic.formalization.autoencoder import decoder_distillation_experiment_v2 as adapter
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_latent_formula as numerical


@pytest.fixture(autouse=True)
def one_cpu_thread():
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    yield
    torch.set_num_threads(previous)


def rule(**updates):
    return dict(dict(actor="agency", action="save", modality="O", object="report",
        conditions=[], exceptions=[], temporal=[]), **updates)


def setup(dimension=384):
    lexemes = [json.dumps(s) for s in (*count.FIELDS, "rules", "O", "P", "F", "agency", "save",
        "report", "a", "b", "c", "d", "e", "bad", "unrelated", "}", 'escaped"value', "café")]
    codec = dict(schema="typed-json-lexical/v1", target_vocabulary=["<pad>", "<bos>", "<eos>"] +
        sorted(set(lexemes + list('{}[],:') + ["true", "1"])))
    body = numerical._model({"dimension": dimension}, codec,
        dict(seed=132, hidden_size=8, token_embedding_dim=8, projection_width=2))
    persistent = adapter.bind_persistent_model(body, dimension=dimension, conditioning="every_step")
    # Nonzero source-to-token lane exercises both components of conditioning.
    with torch.no_grad(): persistent.source_to_embedding.weight.fill_(.003)
    return count.bind_cardinality_model(persistent, codec=codec, guide_boundary=False), codec


def encode(codec, value, complete=True):
    text = json.dumps(value, sort_keys=True, separators=(",", ":")) if not isinstance(value, str) else value
    lexemes = re.findall(r'"(?:[^"\\]|\\.)*"|[{}\[\],:]|true|false|[0-9]+', text)
    return [1] + [codec["target_vocabulary"].index(token) for token in lexemes] + ([2] if complete else [])


def inputs(dimension=384, n=2):
    return torch.randn((n, dimension), generator=torch.Generator().manual_seed(444))


@pytest.mark.parametrize("dimension", [8, 384, 768])
@pytest.mark.parametrize("feature_kind", ["projected_source", "inherited_conditioning"])
def test_zero_head_exactly_preserves_logits_and_caller_state(dimension, feature_kind):
    base, codec = setup(dimension)
    base.eval()
    base.body.body.projection_down.weight.requires_grad_(False)
    base.count_head.bias.grad = torch.ones_like(base.count_head.bias)
    before = core.tensor_digest(base)
    flags = [(name, p.requires_grad) for name, p in base.named_parameters()]
    modes = [(name, m.training) for name, m in base.named_modules()]
    rng = torch.get_rng_state().clone()
    model = subject.bind_source_value_model(base, codec=codec, feature_kind=feature_kind)
    assert core.tensor_digest(base) == core.tensor_digest(model.body) == before
    assert torch.equal(rng, torch.get_rng_state())
    assert flags == [(name, p.requires_grad) for name, p in base.named_parameters()]
    assert modes == [(name, m.training) for name, m in base.named_modules()]
    assert torch.equal(base.count_head.bias.grad, torch.ones_like(base.count_head.bias))
    values = inputs(dimension)
    prefix = torch.tensor([encode(codec, {"rules": [rule(), rule()]})] * 2)
    expected_projected, expected_logits = base(values, prefix)
    projected, logits = model(values, prefix)
    assert torch.equal(projected, expected_projected) and torch.equal(logits, expected_logits)
    assert torch.equal(model.count_logits(projected), base.count_logits(projected))
    assert torch.count_nonzero(model.source_value_logits(projected)) == 0
    description = model.describe()
    assert description["feature_dimension"] == (dimension if feature_kind == "projected_source" else 16)
    assert description["source_fields"] == ["actor", "action", "modality", "object"]
    assert all(description[key] is False for key in subject.FALSE)
    assert not description["syntax_forced"] and not description["closure_forced"]


@pytest.mark.parametrize("feature_kind", ["projected_source", "inherited_conditioning"])
def test_features_match_actual_inherited_paths(feature_kind):
    base, codec = setup()
    model = subject.bind_source_value_model(base, codec=codec, feature_kind=feature_kind)
    projected = model.project(inputs())
    expected = projected if feature_kind == "projected_source" else torch.cat((
        base.start(projected)[0].squeeze(0), base.body.source_to_embedding(projected)), 1)
    assert torch.equal(model._features(projected), expected)


def test_only_causal_scalar_colons_receive_full_vocabulary_residuals():
    base, codec = setup()
    model = subject.bind_source_value_model(base, codec=codec)
    with torch.no_grad():
        model.source_value_head.bias.copy_(torch.arange(model.source_value_head.out_features) / 100.)
    # Field-name values, punctuation strings, escaped strings and qualifiers
    # cannot be mistaken for structural keys or additional scalar sites.
    document = {"rules": [rule(actor="action", object='escaped"value', conditions=["a", "b"]),
        rule(actor="}", action="actor", object="café", exceptions=["c"], temporal=["d"])]}
    prefix = torch.tensor([encode(codec, document)] * 2)
    values = inputs()
    _, expected = base(values, prefix)
    _, actual = model(values, prefix)
    tables = count._tables(codec, len(codec["target_vocabulary"]), torch)
    final, sites = subject._scan_value_prefix(prefix.tolist(), [[0] * 6] * 2, tables, 8)
    assert final == count._scan_prefix(prefix.tolist(), [[0] * 6] * 2, tables)[0]
    assert len(sites) == 2 * 2 * 4
    allowed = torch.zeros(prefix.shape, dtype=torch.bool)
    source_values = model.source_value_logits(model.project(values))
    for batch, offset, slot, field in sites:
        allowed[batch, offset] = True
        assert torch.allclose(actual[batch, offset] - expected[batch, offset], source_values[batch, slot, field], atol=1e-6)
    assert torch.equal(actual[~allowed], expected[~allowed])
    # A residual can alter punctuation and EOS too: this is deliberately soft,
    # not an allowed-class mask or a semantic validator.
    assert (actual[allowed, 2] - expected[allowed, 2]).abs().sum() > 0


@pytest.mark.parametrize("feature_kind", ["projected_source", "inherited_conditioning"])
def test_incremental_and_full_prefix_match_with_immutable_explicit_state(feature_kind):
    base, codec = setup()
    model = subject.bind_source_value_model(base, codec=codec, feature_kind=feature_kind)
    with torch.no_grad():
        model.source_value_head.weight.fill_(.004)
        model.source_value_head.bias.copy_(torch.arange(model.source_value_head.out_features) / 1000.)
    prefix = torch.tensor([encode(codec, {"rules": [rule(), rule(modality="P")]})] * 2)
    state = model.start(model.project(inputs()))
    snapshot = tuple(part.detach().clone() for part in state)
    expected, expected_state = model.next_logits(prefix, state)
    running, chunks = state, []
    for offset in range(prefix.shape[1]):
        logits, running = model.next_logits(prefix[:, offset:offset + 1], running)
        chunks.append(logits)
    assert torch.allclose(expected, torch.cat(chunks, 1), atol=3e-7, rtol=1e-6)
    assert all(torch.equal(original, saved) for original, saved in zip(state, snapshot))
    assert torch.equal(expected_state[4], running[4]) and expected_state[-1] is state[-1]
    assert running[-1] is state[-1]
    # Changing later prefix tokens cannot change earlier output decisions.
    cut = 20
    earlier, _ = model.next_logits(prefix[:, :cut], state)
    assert torch.allclose(earlier, expected[:, :cut], atol=3e-7, rtol=1e-6)


@pytest.mark.parametrize("bad_prefix", [
    '{"rules":[{"actor":"agency","actor":"report",',
    '{"rules":[{"modality":"bad",',
    '{"rules":[{"conditions":["b","a"],',
    '{"rules":[{"conditions":["a","b","c","d","e"],',
    '{"rules":[{"actor":true,',
])
def test_invalid_prefix_permanently_disables_future_guidance(bad_prefix):
    base, codec = setup()
    model = subject.bind_source_value_model(base, codec=codec)
    with torch.no_grad(): model.source_value_head.bias.fill_(2.)
    broken = encode(codec, bad_prefix, complete=False)
    continuation = encode(codec, '"object":"report","action":"save"', complete=False)[1:]
    prefix = torch.tensor([broken + continuation])
    _, expected = base(inputs(n=1), prefix)
    _, actual = model(inputs(n=1), prefix)
    assert torch.equal(actual[:, len(broken):], expected[:, len(broken):])
    _, state = model.next_logits(prefix, model.start(model.project(inputs(n=1))))
    assert state[4][0, 0].item() == count._INVALID


def test_ninth_rule_is_unmodified_without_forcing_closure():
    base, codec = setup()
    model = subject.bind_source_value_model(base, codec=codec)
    with torch.no_grad(): model.source_value_head.bias.fill_(2.)
    prefix = torch.tensor([encode(codec, {"rules": [rule()] * 9})])
    _, expected = base(inputs(n=1), prefix)
    _, actual = model(inputs(n=1), prefix)
    tables = count._tables(codec, len(codec["target_vocabulary"]), torch)
    _, boundaries = count._scan_prefix(prefix.tolist(), [[0] * 6], tables)
    eighth_close = next(offset for _, offset, completed in boundaries if completed == 8)
    assert torch.equal(actual[:, eighth_close:], expected[:, eighth_close:])
    assert model.describe()["source_value_guidance_above_max_rules"] == "inactive_without_truncation_or_forced_closure"


@pytest.mark.parametrize("feature_kind", ["projected_source", "inherited_conditioning"])
def test_auxiliary_and_actual_prefix_ce_both_train_source_head(feature_kind):
    base, codec = setup()
    before = core.tensor_digest(base)
    model = subject.bind_source_value_model(base, codec=codec, feature_kind=feature_kind)
    projected = model.project(inputs())
    head_logits = model.source_value_logits(projected)
    targets = torch.full((2, 8, 4), -1, dtype=torch.long)
    targets[:, 0, :] = torch.tensor([codec["target_vocabulary"].index(json.dumps(rule()[field])) for field in subject.SOURCE_FIELDS])
    torch.nn.functional.cross_entropy(head_logits.flatten(0, 2), targets.flatten(), ignore_index=-1).backward()
    assert model.source_value_head.weight.grad.abs().sum() > 0
    assert model.source_value_head.bias.grad.abs().sum() > 0
    model.zero_grad(set_to_none=True)
    prefix = torch.tensor([encode(codec, {"rules": [rule()]})] * 2)
    _, logits = model(inputs(), prefix[:, :-1])
    torch.nn.functional.cross_entropy(logits.flatten(0, 1), prefix[:, 1:].flatten()).backward()
    assert model.source_value_head.weight.grad.abs().sum() > 0
    assert model.source_value_head.bias.grad.abs().sum() > 0
    assert core.tensor_digest(base) == before and all(p.grad is None for p in base.parameters())


@pytest.mark.parametrize("feature_kind", ["projected_source", "inherited_conditioning"])
def test_zero_source_control_clears_all_source_lanes_and_keeps_priors(feature_kind):
    base, codec = setup()
    model = subject.bind_source_value_model(base, codec=codec, feature_kind=feature_kind)
    with torch.no_grad():
        model.source_value_head.weight.fill_(.01)
        model.source_value_head.bias.fill_(.3)
        model.body.count_head.weight.fill_(.02)
        model.body.count_head.bias.copy_(torch.arange(32) / 10.)
    before, rng = core.tensor_digest(model), torch.get_rng_state().clone()
    control = subject.bind_zero_condition_model(model)
    prefix = torch.tensor([encode(codec, {"rules": [rule()]})] * 2)
    first, second = inputs(), inputs() * 3 + 4
    p1, l1 = control(first, prefix)
    p2, l2 = control(second, prefix)
    assert torch.equal(p1, model.project(first)) and torch.equal(p2, model.project(second))
    assert not torch.equal(p1, p2) and torch.equal(l1, l2)
    state = control.start(p1)
    assert torch.count_nonzero(state[0]) == torch.count_nonzero(state[1]) == 0
    assert torch.equal(state[3], model.body.count_head.bias.expand(2, -1))
    assert torch.equal(state[-1], model.source_value_head.bias.reshape(1, 8, 4, -1).expand(2, -1, -1, -1))
    assert torch.equal(control.count_logits(p1), state[3])
    assert torch.equal(control.source_value_logits(p1), state[-1])
    assert core.tensor_digest(model) == before and torch.equal(rng, torch.get_rng_state())


def corpus(codec):
    documents = [{"rules": [rule(actor="action", object='escaped"value', conditions=["a", "b"])]},
        {"rules": [rule(), rule(actor="café", modality="P", exceptions=["c"])]}]
    rows, references = [], []
    for index, target in enumerate(documents):
        row = dict(id=f"row{index}", source_text=f"Source {index}", input=[0.] * 384,
            target_ids=encode(codec, target))
        rows.append(row)
        references.append(dict(id=row["id"], source_text=row["source_text"], target=target,
            clause_count=len(target["rules"])))
    return rows, references


def validator(value):
    return dict(valid=set(value) == {"rules"} and all(set(item) == set(count.FIELDS) for item in value["rules"]))


def test_auxiliary_labels_are_actual_token_ids_present_only_and_do_not_mutate():
    _, codec = setup()
    rows, references = corpus(codec)
    original = deepcopy((rows, references, codec))
    result = subject.reference_source_values(rows, references, codec, validate_rule=validator)
    for row, reference in zip(rows, references):
        for index, target_rule in enumerate(reference["target"]["rules"]):
            assert result[row["id"]][index] == [codec["target_vocabulary"].index(json.dumps(target_rule[field]))
                for field in subject.SOURCE_FIELDS]
        assert all(labels == [-1] * 4 for labels in result[row["id"]][len(reference["target"]["rules"]):])
    assert (rows, references, codec) == original


@pytest.mark.parametrize("tamper", ["scalar", "qualifier", "count", "source", "ids", "overflow", "validator"])
def test_auxiliary_reference_binding_rejects_drift_and_missing_validation(tamper):
    _, codec = setup()
    rows, references = corpus(codec)
    valid = validator
    if tamper == "scalar": references[0]["target"]["rules"][0]["actor"] = "report"
    elif tamper == "qualifier": references[0]["target"]["rules"][0]["conditions"] = []
    elif tamper == "count": references[0]["clause_count"] = 2
    elif tamper == "source": references[0]["source_text"] += " changed"
    elif tamper == "ids": references[0]["id"] = "wrong"
    elif tamper == "overflow":
        references[0]["target"]["rules"] *= 9
        references[0]["clause_count"] = 9
        rows[0]["target_ids"] = encode(codec, references[0]["target"])
    elif tamper == "validator": valid = lambda value: dict(valid=False)
    with pytest.raises((ValueError, RuntimeError)):
        subject.reference_source_values(rows, references, codec, validate_rule=valid)


@pytest.mark.parametrize("override", [dict(feature_kind="unknown"), dict(guidance=1), dict(max_rules=0),
    dict(max_rules=9), dict(max_rules=True)])
def test_rejects_unbounded_or_undeclared_model_modes(override):
    base, codec = setup()
    with pytest.raises((ValueError, RuntimeError)):
        subject.bind_source_value_model(base, codec=codec, **override)


def test_false_guidance_keeps_original_logits_even_after_head_changes():
    base, codec = setup()
    model = subject.bind_source_value_model(base, codec=codec, guidance=False)
    with torch.no_grad(): model.source_value_head.weight.fill_(2.)
    prefix = torch.tensor([encode(codec, {"rules": [rule()]})] * 2)
    assert torch.equal(model(inputs(), prefix)[1], base(inputs(), prefix)[1])


def test_malformed_value_state_is_rejected_before_generation():
    base, codec = setup()
    model = subject.bind_source_value_model(base, codec=codec)
    state = model.start(model.project(inputs()))
    for invalid in (state[:-1], (*state[:-1], state[-1][:, :2]), (*state[:-1], state[-1] * float("nan"))):
        with pytest.raises((ValueError, RuntimeError)):
            model.next_logits(torch.ones((2, 1), dtype=torch.long), invalid)
