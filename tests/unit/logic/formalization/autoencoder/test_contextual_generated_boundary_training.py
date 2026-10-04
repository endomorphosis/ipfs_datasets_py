"""Synthetic contextual self-prefix supervision; no trained checkpoint claims."""
from copy import deepcopy
import math
import random
import time

import pytest

torch = pytest.importorskip("torch")
from ipfs_datasets_py.logic.formalization.autoencoder import contextual_generated_boundary_training as subject
from ipfs_datasets_py.logic.formalization.autoencoder import clause_source_context as contexts_owner
from ipfs_datasets_py.logic.formalization.autoencoder import action_factorized_clause_decoder_experiment as action
from ipfs_datasets_py.logic.formalization.autoencoder import ordered_clause_recurrent_decoder_experiment as recurrent
from .test_boundary_source_diagnostic import scripted as shared_scripted
from .test_clause_source_context import fixtures, transform
from .test_clause_source_decoder_experiment import bound as clause_bound
from .test_ordered_clause_recurrent_decoder_experiment import fixture as recurrent_fixture
from .test_projected_source_decoder_experiment import encode, rule, inputs


@pytest.fixture(autouse=True)
def one_cpu():
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    yield
    torch.set_num_threads(previous)


def scripted(kind="recurrent", count=2, invalid=False, dimension=8):
    if kind == "shared":
        model, codec, rows, _ = shared_scripted("shared")
        contexts = None
    else:
        if kind == "recurrent":
            model, _, codec, _ = recurrent_fixture(dimension)
        else:
            model, _, codec, _, _ = clause_bound(dimension)
            if kind == "action":
                model = action.bind_action_factorized_clause_model(model, codec=codec)
        train, _, _, envelope = fixtures(dimension)
        rows = [dict(train[0], input=inputs(dimension, 1)[0].tolist())]
        contexts = envelope["train"]
    sequence = encode(codec, {"rules": [rule()]*count})[1:]
    if invalid:
        sequence = [codec["target_vocabulary"].index('"agency"'), 2]
    body = model.body.body.body

    class Positions(torch.nn.Module):
        def forward(self, values, hidden):
            pos = hidden[0, :, 0].long()
            output = torch.zeros(len(values), values.shape[1], len(sequence))
            for offset in range(values.shape[1]):
                output[:, offset].scatter_(1, (pos+offset).clamp(max=len(sequence)-1).unsqueeze(1), 1.)
            updated = hidden.clone()
            updated[0, :, 0] += values.shape[1]
            return output, updated

    body.decoder = Positions()
    body.output = torch.nn.Linear(len(sequence), len(codec["target_vocabulary"]))
    with torch.no_grad():
        body.condition.weight.zero_()
        body.condition.bias.zero_()
        body.output.weight.fill_(-20.)
        body.output.bias.zero_()
        for offset, token in enumerate(sequence):
            body.output.weight[token, offset] = 20.
    return model, codec, rows, contexts


def collect(model, codec, rows, contexts=None, **options):
    return subject.collect_source_boundary_prefixes(model, rows, codec=codec,
        input_transform=options.pop("input_transform", transform(model.dimension)), source_contexts=contexts,
        max_target_tokens=options.pop("max_target_tokens", 512), batch_size=2,
        deadline=options.pop("deadline", time.monotonic()+30), **options)


def loss(model, codec, collection, counts, contexts=None, **options):
    return subject.generated_boundary_loss(torch, model, collection, counts, codec=codec,
        input_transform=options.pop("input_transform", transform(model.dimension)), source_contexts=contexts,
        deadline=options.pop("deadline", time.monotonic()+30), **options)


def resign(value):
    value["collection_sha256"] = subject.core.digest({k: v for k, v in value.items() if k != "collection_sha256"})
    return value


@pytest.mark.parametrize("kind", ["shared", "clause", "action", "recurrent"])
def test_all_supported_architectures_match_unobserved_actual_greedy(kind):
    model, codec, rows, contexts = scripted(kind)
    with torch.no_grad():
        expected = subject.core._greedy(torch, model, torch.tensor([row["input"] for row in rows]),
            512, len(codec["target_vocabulary"]), time.monotonic()+30,
            **subject.core._source_context_kwargs(torch, rows, contexts, transform(model.dimension)))
    collection = collect(model, codec, rows, contexts)
    assert [row["token_ids"] for row in collection["predictions"]] == expected[1]
    assert [row["generation_status"] for row in collection["predictions"]] == expected[2]
    assert collection["available_sites"] == 2*len(rows)
    assert collection["reference_count_access"] is False and collection["site_policy_access"] is False
    result = loss(model, codec, collection, {row["id"]: 1 for row in rows}, contexts, site_policy="first_wrong")
    assert result["receipt"]["selected_sites"] == len(rows)
    assert all(event["completed_rules"] == 1 and event["action"] == "stop" for event in result["receipt"]["events"])
    assert result["receipt"]["maximum_replay_logit_absolute_difference"] == 0.


@pytest.mark.parametrize("dimension", [8, 384, 768])
def test_contextual_widths_preserve_source_context_hash_and_no_vectors_in_loss_receipt(dimension):
    model, codec, rows, contexts = scripted(dimension=dimension)
    col = collect(model, codec, rows, contexts)
    result = loss(model, codec, col, {"train": 1}, contexts, site_policy="first_wrong")
    assert col["source_contexts_sha256"] == subject.core.digest(contexts)
    assert result["receipt"]["generation"]["source_contexts_sha256"] == col["source_contexts_sha256"]
    assert "source_contexts" not in col
    assert all("input" not in row and "input_sha256" in row for row in result["receipt"]["generation"]["rows"])


def test_first_wrong_is_after_complete_rollout_and_finds_missed_middle_error():
    model, codec, rows, contexts = scripted(count=6)
    col = collect(model, codec, rows, contexts)
    original = deepcopy(col)
    first = loss(model, codec, col, {"train": 3}, contexts, site_policy="first_wrong")
    last = loss(model, codec, col, {"train": 3}, contexts, site_policy="first_last")
    assert col == original and col["available_sites"] == 6
    assert [site["completed_rules"] for site in first["receipt"]["events"]] == [3]
    assert [site["completed_rules"] for site in last["receipt"]["events"]] == [1, 6]
    assert first["receipt"]["site_cap_per_row"] == 1 and last["receipt"]["site_cap_per_row"] == 2
    assert first["receipt"]["generation"]["complete_rollout_before_site_selection"]
    assert first["receipt"]["events"][0]["target_token_id"] != first["receipt"]["events"][0]["actual_next_token_id"]


def test_vary_labels_only_changes_post_collection_selection():
    model, codec, rows, contexts = scripted(count=4)
    col = collect(model, codec, rows, contexts)
    original = deepcopy(col)
    one = loss(model, codec, col, {"train": 1}, contexts, site_policy="first_wrong")
    three = loss(model, codec, col, {"train": 3}, contexts, site_policy="first_wrong")
    five = loss(model, codec, col, {"train": 5}, contexts, site_policy="first_wrong")
    assert [r["completed_rules"] for r in one["receipt"]["events"]] == [1]
    assert [r["completed_rules"] for r in three["receipt"]["events"]] == [3]
    assert [r["completed_rules"] for r in five["receipt"]["events"]] == [4]
    assert five["receipt"]["events"][0]["action"] == "continue"
    assert col == original


def test_correct_rows_are_excluded_from_first_wrong_reduction():
    model, codec, rows, contexts = scripted("shared", count=4)
    col = collect(model, codec, rows, contexts)
    result = loss(model, codec, col, {"0": 4, "1": 2}, contexts, site_policy="first_wrong")
    assert result["receipt"]["active_rows"] == 1
    assert result["receipt"]["rows_without_selected_sites"] == 1
    assert result["receipt"]["selected_sites"] == 1
    assert result["receipt"]["events"][0]["id"] == "1"
    assert result["receipt"]["events"][0]["mean_loss_coefficient"] == 1.


@pytest.mark.parametrize("policy", ["first_last", "first_wrong"])
def test_full_vocabulary_ce_row_balanced_reduction_and_prefix_hashes(policy):
    model, codec, rows, contexts = scripted("shared", count=4)
    col = collect(model, codec, rows, contexts)
    result = loss(model, codec, col, {"0": 2, "1": 6}, contexts, site_policy=policy)
    total = 0.
    for event in result["receipt"]["events"]:
        values = event["replay_logits"]
        maximum = max(values)
        ce = maximum+math.log(sum(math.exp(v-maximum) for v in values))-values[event["target_token_id"]]
        assert len(values) == len(codec["target_vocabulary"])
        assert event["cross_entropy"] == pytest.approx(ce, abs=3e-6)
        row = next(row for row in result["receipt"]["generation"]["rows"] if row["id"] == event["id"])
        assert event["consumed_prefix_sha256"] == subject.core.digest(row["consumed_prefix"][:event["position"]+1])
        total += ce*event["mean_loss_coefficient"]
    assert float(result["loss"].detach()) == pytest.approx(total, abs=3e-6)


@pytest.mark.parametrize("invalid,policy", [(True, "first_last"), (True, "first_wrong"), (False, "first_wrong")])
def test_no_sites_or_no_errors_returns_no_graph_and_no_replay(invalid, policy, monkeypatch):
    model, codec, rows, contexts = scripted(invalid=invalid)
    col = collect(model, codec, rows, contexts)
    monkeypatch.setattr(subject.core, "_logits", lambda *a, **kw: pytest.fail("no selected sites must not replay"))
    result = loss(model, codec, col, {"train": 2}, contexts, site_policy=policy)
    assert result["loss"] is None
    assert result["receipt"]["active_rows"] == result["receipt"]["selected_sites"] == 0
    assert result["receipt"]["events"] == []
    assert all(p.grad is None for p in model.parameters())
    if invalid:
        assert all(row["first_invalid_prefix_position"] is not None for row in col["rows"])


@pytest.mark.parametrize("policy", ["first_last", "first_wrong"])
def test_only_boundary_objective_backpropagates_without_optimizer_update(policy):
    model, codec, rows, contexts = scripted()
    col = collect(model, codec, rows, contexts)
    before = subject.core.tensor_digest(model)
    result = loss(model, codec, col, {"train": 1}, contexts, site_policy=policy)
    result["loss"].backward()
    assert torch.count_nonzero(model.body.body.body.output.weight.grad)
    assert torch.count_nonzero(model.body.count_head.bias.grad)
    assert subject.core.tensor_digest(model) == before
    assert all(p.grad is None for name, p in model.named_parameters() if "projection_down." in name or "projection_up." in name)


def test_existing_main_graph_and_modes_rng_gradients_inputs_are_preserved():
    model, codec, rows, contexts = scripted()
    model.train()
    model.action_head.eval()
    for p in model.parameters():
        p.grad = torch.ones_like(p)
    before = subject._state_versions(model)
    modes = {n: m.training for n, m in model.named_modules()}
    rng, prng = torch.get_rng_state().clone(), random.getstate()
    original = deepcopy((rows, contexts))
    main = model.body.count_head.bias.square().sum()
    col = collect(model, codec, rows, contexts)
    result = loss(model, codec, col, {"train": 1}, contexts, site_policy="first_wrong")
    assert subject._state_versions(model) == before
    assert (rows, contexts) == original
    assert modes == {n: m.training for n, m in model.named_modules()}
    assert torch.equal(rng, torch.get_rng_state()) and random.getstate() == prng
    (main+result["loss"]).backward()
    assert model.body.count_head.bias.grad is not None


@pytest.mark.parametrize("field", ["target_ids", "target", "reference_count", "prefix", "site_policy"])
def test_collector_rejects_poisoned_label_or_policy_fields(field):
    model, codec, rows, contexts = scripted()
    rows[0][field] = object()
    with pytest.raises(ValueError, match="source-only"):
        collect(model, codec, rows, contexts)


@pytest.mark.parametrize("argument", ["training_counts_by_id", "site_policy", "reference_documents"])
def test_collector_has_no_label_or_site_policy_argument(argument):
    model, codec, rows, contexts = scripted()
    with pytest.raises(TypeError):
        collect(model, codec, rows, contexts, **{argument: object()})


@pytest.mark.parametrize("mutation", ["extra", "missing", "hash", "source", "dimension", "label"])
def test_context_inventory_must_be_exact_authenticated_subset(mutation):
    model, codec, rows, contexts = scripted()
    if mutation == "extra":
        contexts["extra"] = deepcopy(contexts["train"])
    elif mutation == "missing":
        contexts.clear()
    elif mutation == "hash":
        contexts["train"]["source_sha256"] = "a"*64
    elif mutation == "source":
        rows[0]["source_text"] += "x"
    elif mutation == "dimension":
        _, _, _, ctx = fixtures(384)
        contexts = ctx["train"]
    else:
        contexts["train"]["reference_count"] = 2
    with pytest.raises(ValueError):
        collect(model, codec, rows, contexts)


@pytest.mark.parametrize("kind", ["shared", "recurrent"])
def test_context_presence_is_required_by_architecture(kind):
    model, codec, rows, contexts = scripted(kind)
    with pytest.raises(ValueError, match="paired"):
        collect(model, codec, rows, {} if contexts is None else None)


@pytest.mark.parametrize("mutation", ["model", "context", "transform", "source"])
def test_stale_collection_is_refused(mutation):
    model, codec, rows, contexts = scripted()
    col = collect(model, codec, rows, contexts)
    options = {}
    if mutation == "model":
        with torch.no_grad():
            model.body.count_head.bias[0].add_(.01)
    elif mutation == "context":
        contexts["train"]["segments"][0]["vector"][0] = .5
    elif mutation == "transform":
        options["input_transform"] = dict(transform(), scale=2.)
    else:
        col["source_rows"][0]["input"][0] += .5
    with pytest.raises(ValueError, match="stale|digest"):
        loss(model, codec, col, {"train": 1}, contexts, **options)


@pytest.mark.parametrize("mutation", ["position", "count", "argmax", "output", "special", "missing_site", "invalid", "status", "full_logits"])
def test_rehashed_forged_available_sites_are_independently_rejected(mutation):
    model, codec, rows, contexts = scripted()
    col = collect(model, codec, rows, contexts)
    site = col["rows"][0]["available_sites"][0]
    if mutation == "position":
        site["position"] += 1
    elif mutation == "count":
        site["completed_rules"] += 1
    elif mutation == "argmax":
        site["actual_next_token_id"] = 2
    elif mutation == "output":
        token = codec["target_vocabulary"].index("]")
        site["collection_logits"][token] = 30.
        site["actual_next_token_id"] = token
    elif mutation == "special":
        col["predictions"][0]["token_ids"][0] = 2
    elif mutation == "missing_site":
        col["rows"][0]["available_sites"].pop()
    elif mutation == "invalid":
        col["rows"][0]["first_invalid_prefix_position"] = 0
    elif mutation == "status":
        col["predictions"][0]["generation_status"] = "output_limit"
    else:
        site["collection_logits"] = site["collection_logits"][:-1]
    resign(col)
    with pytest.raises(ValueError):
        loss(model, codec, col, {"train": 1}, contexts, site_policy="first_wrong")


def test_replay_refuses_forged_logits_even_with_same_argmax_and_updated_digest():
    model, codec, rows, contexts = scripted()
    col = collect(model, codec, rows, contexts)
    col["rows"][0]["available_sites"][0]["collection_logits"][0] += .1
    resign(col)
    with pytest.raises(ValueError, match="replayed boundary logits"):
        loss(model, codec, col, {"train": 1}, contexts, site_policy="first_wrong")


@pytest.mark.parametrize("token", [0, 1, 2])
def test_special_token_at_actual_boundary_is_retained_as_first_wrong(token):
    model, codec, rows, contexts = scripted()
    original = collect(model, codec, rows, contexts)
    position = original["rows"][0]["available_sites"][0]["position"]
    with torch.no_grad():
        model.body.body.body.output.weight[:, position].fill_(-20.)
        model.body.body.body.output.weight[token, position] = 20.
    col = collect(model, codec, rows, contexts)
    assert col["available_sites"] == 1
    assert col["rows"][0]["available_sites"][0]["actual_next_token_id"] == token
    result = loss(model, codec, col, {"train": 1}, contexts, site_policy="first_wrong")
    assert result["receipt"]["selected_sites"] == 1
    assert result["receipt"]["events"][0]["action"] == "stop"
    assert result["receipt"]["events"][0]["actual_next_token_id"] == token


def test_collector_invalid_grammar_never_recovers_invented_later_boundaries():
    model, codec, rows, contexts = scripted()
    with torch.no_grad():
        model.body.body.body.output.weight[:, 0].fill_(-20.)
        model.body.body.body.output.weight[codec["target_vocabulary"].index('"agency"'), 0] = 20.
    col = collect(model, codec, rows, contexts)
    assert col["available_sites"] == 0
    assert col["rows"][0]["first_invalid_prefix_position"] == 1
    assert loss(model, codec, col, {"train": 2}, contexts, site_policy="first_wrong")["loss"] is None


@pytest.mark.parametrize("value", [True, 0, 33, 1.5])
def test_loss_requires_bounded_integer_training_counts(value):
    model, codec, rows, contexts = scripted()
    col = collect(model, codec, rows, contexts)
    with pytest.raises(ValueError, match="counts1..32"):
        loss(model, codec, col, {"train": value}, contexts)


@pytest.mark.parametrize("options", [{"max_target_tokens": 513}, {"max_sites_per_row": 1}, {"max_sites_per_row": True}])
def test_unreviewed_caps_rejected(options):
    model, codec, rows, contexts = scripted()
    with pytest.raises(ValueError):
        collect(model, codec, rows, contexts, **options)


@pytest.mark.parametrize("options", [{"site_policy": "all"}, {"gradient_scope": "count_head_only"}])
def test_unreviewed_objective_settings_rejected(options):
    model, codec, rows, contexts = scripted()
    col = collect(model, codec, rows, contexts)
    with pytest.raises(ValueError):
        loss(model, codec, col, {"train": 1}, contexts, **options)


@pytest.mark.parametrize("wrapper", [recurrent.bind_zero_condition_model, recurrent.bind_residual_off_model])
def test_inference_only_controls_are_not_training_models(wrapper):
    model, codec, rows, contexts = scripted()
    with pytest.raises(ValueError, match="supported trainable"):
        collect(wrapper(model), codec, rows, contexts)


def test_deadline_timeout_preserves_caller_during_collection_and_replay(monkeypatch):
    model, codec, rows, contexts = scripted()
    col = collect(model, codec, rows, contexts)
    snapshot = subject._snapshot(model, torch)
    with pytest.raises(TimeoutError):
        collect(model, codec, rows, contexts, deadline=time.monotonic()-1)
    with pytest.raises(TimeoutError):
        loss(model, codec, col, {"train": 1}, contexts, deadline=time.monotonic()-1)
    tick = [0.]
    def clock():
        tick[0] += 1.
        return tick[0]
    monkeypatch.setattr(subject.time, "monotonic", clock)
    with pytest.raises(TimeoutError):
        collect(model, codec, rows, contexts, deadline=10.)
    subject._preserved(model, torch, snapshot)
    tick[0] = 0.
    with pytest.raises(TimeoutError):
        loss(model, codec, col, {"train": 1}, contexts, deadline=10.)
    subject._preserved(model, torch, snapshot)


def test_output_limit_no_sites_and_final_boundary_choice_are_real():
    model, codec, rows, contexts = scripted()
    col = collect(model, codec, rows, contexts, max_target_tokens=4)
    assert col["predictions"][0]["generation_status"] == "output_limit"
    assert col["available_sites"] == 0
    assert loss(model, codec, col, {"train": 1}, contexts, site_policy="first_wrong")["loss"] is None
    full = collect(model, codec, rows, contexts)
    boundary = full["rows"][0]["available_sites"][0]["position"]
    truncated = collect(model, codec, rows, contexts, max_target_tokens=boundary+2)
    assert truncated["available_sites"] == 1 and truncated["predictions"][0]["generation_status"] == "output_limit"
    assert loss(model, codec, truncated, {"train": 1}, contexts, site_policy="first_wrong")["loss"] is not None
