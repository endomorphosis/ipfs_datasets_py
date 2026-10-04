"""Synthetic full-vocabulary own-prefix supervision, never qualification."""
from copy import deepcopy
import hashlib
import json
import math
import random
import time

import pytest

torch = pytest.importorskip("torch")
from ipfs_datasets_py.logic.formalization.autoencoder import generated_field_training as subject
from ipfs_datasets_py.logic.formalization.autoencoder import contextual_generated_boundary_training as old
from ipfs_datasets_py.logic.formalization.autoencoder import clause_source_context as contexts_owner
from ipfs_datasets_py.logic.formalization.autoencoder import ordered_clause_recurrent_decoder_experiment as recurrent
from .test_contextual_generated_boundary_training import scripted
from .test_clause_source_context import transform
from .test_projected_source_decoder_experiment import encode, rule
from .test_long_span_cardinality_training import validate_rule


@pytest.fixture(autouse=True)
def one_cpu():
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    yield
    torch.set_num_threads(previous)


def labelled(rows, contexts, codec, *, wrong=True, targets=None):
    train, references = [], []
    for row in rows:
        target = dict(rules=deepcopy(targets[row["id"]]) if targets else
            [dict(rule(), actor="a", action="b", modality="F", object="a") if wrong else rule()
                for _ in contexts[row["id"]]["segments"]])
        train.append(dict(row, target_ids=encode(codec, target)))
        references.append(dict(id=row["id"], source_text=row["source_text"], target=target, clause_count=len(target["rules"])))
    return train, references


def prepared(kind="recurrent", count=2, dimension=8, invalid=False, wrong=True):
    model, codec, rows, contexts = scripted(kind, count=count, dimension=dimension, invalid=invalid)
    train, references = labelled(rows, contexts, codec, wrong=wrong)
    inventory = subject.prepare_training_inventory(train, references, contexts=contexts, codec=codec, validate_rule=validate_rule)
    return model, codec, rows, contexts, inventory


def collect(model, codec, rows, contexts, **options):
    return subject.collect_source_generated_sites(model, rows, codec=codec,
        input_transform=options.pop("input_transform", transform(model.dimension)), source_contexts=contexts,
        max_target_tokens=options.pop("max_target_tokens", 512), batch_size=options.pop("batch_size", 8),
        deadline=options.pop("deadline", time.monotonic()+30), **options)


def losses(model, codec, collection, inventory, contexts, **options):
    return subject.generated_site_losses(torch, model, collection, inventory, codec=codec,
        input_transform=options.pop("input_transform", transform(model.dimension)), source_contexts=contexts,
        deadline=options.pop("deadline", time.monotonic()+30), **options)


def resign(value, name):
    value[name] = subject.core.digest({k: v for k, v in value.items() if k != name})
    return value


@pytest.mark.parametrize("kind", ["clause", "action", "recurrent"])
@pytest.mark.parametrize("dimension", [8, 384, 768])
def test_supported_context_models_widths_preserve_existing_source_only_rollout(kind, dimension):
    model, codec, rows, contexts, inventory = prepared(kind, dimension=dimension)
    previous = old.collect_source_boundary_prefixes(model, rows, codec=codec, input_transform=transform(dimension),
        source_contexts=contexts, deadline=time.monotonic()+30)
    actual = collect(model, codec, rows, contexts)
    assert actual["predictions"] == previous["predictions"]
    assert actual["available_sites"] == previous["available_sites"] == 2
    assert actual["available_field_sites"] == 8
    assert actual["rows"][0]["available_sites"] == previous["rows"][0]["available_sites"]
    assert actual["rows"][0]["consumed_prefix"] == previous["rows"][0]["consumed_prefix"]
    assert actual["inventory_access"] is False and actual["site_policy_access"] is False
    result = losses(model, codec, actual, inventory, contexts)
    assert result["receipt"]["field"]["selected_sites"] == 4
    assert result["receipt"]["boundary"]["selected_sites"] == 2
    assert result["receipt"]["maximum_replay_logit_absolute_difference"] == 0.


def test_inventory_exact_source_offsets_labels_and_no_vectors():
    model, codec, rows, contexts, inventory = prepared()
    record = inventory["rows"]["train"]
    assert record["rule_count"] == 2 and inventory["fields"] == ["actor", "action", "modality", "object"]
    for slot, clause in enumerate(record["clauses"]):
        segment = contexts["train"]["segments"][slot]
        assert clause["slot"] == clause["reference_rule_index"] == slot
        for key in ["source_sha256", "embedding_sha256", "char_start", "char_end", "byte_start", "byte_end"]:
            assert clause[key] == segment[key]
        assert "vector" not in clause and "source_text" not in clause
        assert {field: json.loads(codec["target_vocabulary"][token]) for field, token in clause["target_token_ids"].items()} == {
            "actor": "a", "action": "b", "modality": "F", "object": "a"}
    assert not inventory["validation_rows_used"] and not inventory["source_alignment_inferred"]
    assert subject.FIELD_POLICY == "first_wrong_per_scalar_field"


@pytest.mark.parametrize("field", ["actor", "action", "modality", "object"])
def test_repeated_literal_source_with_conflicting_field_label_is_rejected(field):
    model, codec, rows, contexts = scripted()
    segment = contexts["train"]["segments"][0]
    rows[0]["source_text"] = segment["source_text"]+"\n\n"+segment["source_text"]
    contexts["train"] = contexts_owner._descriptor(rows[0]["source_text"], [segment["vector"], segment["vector"]])
    target = [rule(), dict(rule(), **{field: "F" if field == "modality" else "a"})]
    train, refs = labelled(rows, contexts, codec, targets={"train": target})
    with pytest.raises(ValueError, match="ambiguous.*conflicting"):
        subject.prepare_training_inventory(train, refs, contexts=contexts, codec=codec, validate_rule=validate_rule)


def test_identical_repeated_sources_retain_positioned_occurrences():
    model, codec, rows, contexts = scripted()
    segment = contexts["train"]["segments"][0]
    rows[0]["source_text"] = segment["source_text"]+"\n\n"+segment["source_text"]
    contexts["train"] = contexts_owner._descriptor(rows[0]["source_text"], [segment["vector"], segment["vector"]])
    train, refs = labelled(rows, contexts, codec)
    inventory = subject.prepare_training_inventory(train, refs, contexts=contexts, codec=codec, validate_rule=validate_rule)
    clauses = inventory["rows"]["train"]["clauses"]
    assert inventory["unique_training_clauses"] == 1 and len(clauses) == 2
    assert clauses[0]["source_sha256"] == clauses[1]["source_sha256"]
    assert clauses[0]["char_start"] != clauses[1]["char_start"]
    col = collect(model, codec, rows, contexts)
    result = losses(model, codec, col, inventory, contexts)
    assert result["receipt"]["field"]["selected_sites"] == 4
    assert all(event["slot"] == 0 for event in result["receipt"]["field"]["events"])


def test_source_reference_count_mismatch_is_not_guessed():
    model, codec, rows, contexts = scripted()
    train, refs = labelled(rows, contexts, codec, targets={"train": [rule()]})
    with pytest.raises(ValueError, match="one-source-clause"):
        subject.prepare_training_inventory(train, refs, contexts=contexts, codec=codec, validate_rule=validate_rule)


def test_reference_labels_must_match_actual_training_document_and_token_ids():
    model, codec, rows, contexts = scripted()
    train, refs = labelled(rows, contexts, codec)
    refs[0]["target"]["rules"][0]["actor"] = "agency"
    with pytest.raises(ValueError):
        subject.prepare_training_inventory(train, refs, contexts=contexts, codec=codec, validate_rule=validate_rule)


def test_one_rollout_and_one_union_replay_not_a_second_boundary_forward(monkeypatch):
    model, codec, rows, contexts, inventory = prepared()
    observed = {"greedy": 0, "logits": 0}
    greedy, logits = subject.core._greedy, subject.core._logits
    def count_greedy(*a, **kw):
        observed["greedy"] += 1
        return greedy(*a, **kw)
    def count_logits(*a, **kw):
        observed["logits"] += 1
        return logits(*a, **kw)
    monkeypatch.setattr(subject.core, "_greedy", count_greedy)
    monkeypatch.setattr(subject.core, "_logits", count_logits)
    col = collect(model, codec, rows, contexts)
    result = losses(model, codec, col, inventory, contexts)
    assert observed == {"greedy": 1, "logits": 1}
    assert result["receipt"]["replay_batch_count"] == result["receipt"]["union_active_rows"] == 1
    row = result["receipt"]["generation"]["rows"][0]
    union = sorted({site["position"] for site in row["selected_boundary_sites"]+row["selected_field_sites"]})
    assert row["union_replay_positions"] == union
    assert row["replay_prefix_tokens"] == union[-1]+1
    assert "input" not in row and "input_sha256" in row
    assert "source_contexts" not in result["receipt"]["generation"]


def test_boundary_loss_matches_legacy_full_vocabulary_and_gradient_exactly():
    model, codec, rows, contexts, inventory = prepared(wrong=False)
    col = collect(model, codec, rows, contexts)
    joint = losses(model, codec, col, inventory, contexts)
    previous = old.collect_source_boundary_prefixes(model, rows, codec=codec, input_transform=transform(),
        source_contexts=contexts, deadline=time.monotonic()+30)
    alone = old.generated_boundary_loss(torch, model, previous, {"train": 2}, codec=codec, input_transform=transform(),
        source_contexts=contexts, deadline=time.monotonic()+30)
    assert joint["field_loss"] is None
    assert torch.equal(joint["boundary_loss"], alone["loss"])
    parameters = [p for p in model.parameters() if p.requires_grad]
    a = torch.autograd.grad(joint["boundary_loss"], parameters, allow_unused=True)
    b = torch.autograd.grad(alone["loss"], parameters, allow_unused=True)
    assert all(x is None and y is None or x is not None and y is not None and torch.equal(x, y) for x, y in zip(a, b))


@pytest.mark.parametrize("field", ["actor", "action", "modality", "object"])
def test_selects_first_wrong_per_field_after_rollout_not_last_or_first_correct(field):
    model, codec, rows, contexts = scripted()
    target = [rule(), dict(rule(), **{field: "F" if field == "modality" else "a"})]
    train, refs = labelled(rows, contexts, codec, targets={"train": target})
    inventory = subject.prepare_training_inventory(train, refs, contexts=contexts, codec=codec, validate_rule=validate_rule)
    col = collect(model, codec, rows, contexts)
    before = deepcopy(col)
    result = losses(model, codec, col, inventory, contexts)
    events = result["receipt"]["field"]["events"]
    assert len(events) == 1 and events[0]["field"] == field and events[0]["slot"] == 1
    assert events[0]["target_token_id"] != events[0]["actual_next_token_id"]
    assert col == before


def test_each_scalar_is_selected_independently_and_full_vocabulary_ce_is_recomputable():
    model, codec, rows, contexts, inventory = prepared()
    result = losses(model, codec, collect(model, codec, rows, contexts), inventory, contexts)
    assert set(result["receipt"]["field"]["labels_by_field"]) == set(subject.FIELDS)
    for component, key in [("field", "field_loss"), ("boundary", "boundary_loss")]:
        total = 0.
        for event in result["receipt"][component]["events"]:
            raw = event["replay_logits"]
            assert len(raw) == len(codec["target_vocabulary"])
            high = max(raw)
            ce = high+math.log(sum(math.exp(value-high) for value in raw))-raw[event["target_token_id"]]
            assert ce == pytest.approx(event["cross_entropy"], abs=3e-6)
            total += ce*event["mean_loss_coefficient"]
            row = result["receipt"]["generation"]["rows"][0]
            assert event["consumed_prefix_sha256"] == subject.core.digest(row["consumed_prefix"][:event["position"]+1])
        assert float(result[key].detach()) == pytest.approx(total, abs=3e-6)


def test_components_have_separate_active_row_reduction():
    model, codec, rows, contexts = scripted()
    other = dict(id="other", source_text="Different agency source.\n\nDifferent officer source.", input=rows[0]["input"][:])
    rows.append(other)
    contexts["other"] = contexts_owner._descriptor(other["source_text"], [segment["vector"] for segment in contexts["train"]["segments"]])
    targets = {"train": [rule(), rule()], "other": [dict(rule(), actor="a"), rule()]}
    train, refs = labelled(rows, contexts, codec, targets=targets)
    inventory = subject.prepare_training_inventory(train, refs, contexts=contexts, codec=codec, validate_rule=validate_rule)
    result = losses(model, codec, collect(model, codec, rows, contexts), inventory, contexts)
    assert result["receipt"]["boundary"]["active_rows"] == 2
    assert result["receipt"]["field"]["active_rows"] == 1
    assert result["receipt"]["field"]["events"][0]["mean_loss_coefficient"] == 1.
    assert all(event["mean_loss_coefficient"] == .25 for event in result["receipt"]["boundary"]["events"])
    assert result["receipt"]["union_active_rows"] == 2 and result["receipt"]["replay_batch_count"] == 1


def test_exhausted_source_slots_are_unscored_without_clamping_or_fabricated_labels():
    model, codec, rows, contexts, inventory = prepared(count=4)
    col = collect(model, codec, rows, contexts)
    assert col["available_field_sites"] == 16
    result = losses(model, codec, col, inventory, contexts)
    assert result["receipt"]["field"]["scored_sites"] == result["receipt"]["field"]["unscored_sites"] == 8
    ignored = result["receipt"]["generation"]["rows"][0]["unscored_field_sites"]
    assert len(ignored) == 8 and {site["slot"] for site in ignored} == {2, 3}
    assert all(site["reason"] == "source_clause_and_reference_slot_unavailable" for site in ignored)
    assert all(event["slot"] < 2 for event in result["receipt"]["field"]["events"])


def test_eight_slot_exhaustion_still_observed_without_reference_clamping():
    model, codec, rows, contexts, inventory = prepared(count=9)
    col = collect(model, codec, rows, contexts)
    assert len(col["rows"][0]["available_field_sites"]) == 36
    assert max(site["slot"] for site in col["rows"][0]["available_field_sites"]) == 8
    result = losses(model, codec, col, inventory, contexts)
    assert result["receipt"]["field"]["unscored_sites"] == 28


@pytest.mark.parametrize("invalid", [False, True])
def test_no_field_errors_and_no_wrong_boundaries_yield_no_graph(invalid, monkeypatch):
    model, codec, rows, contexts, inventory = prepared(invalid=invalid, wrong=False)
    col = collect(model, codec, rows, contexts)
    monkeypatch.setattr(subject.core, "_logits", lambda *a, **kw: pytest.fail("no selected sites must not replay"))
    result = losses(model, codec, col, inventory, contexts, boundary_site_policy="first_wrong")
    assert result["boundary_loss"] is result["field_loss"] is None
    assert result["receipt"]["union_active_rows"] == result["receipt"]["replay_batch_count"] == 0
    if invalid:
        assert col["available_field_sites"] == col["available_sites"] == 0
    assert all(p.grad is None for p in model.parameters())


def test_field_only_active_loss_does_not_attach_boundary_graph():
    model, codec, rows, contexts, inventory = prepared()
    result = losses(model, codec, collect(model, codec, rows, contexts), inventory, contexts, boundary_site_policy="first_wrong")
    assert result["boundary_loss"] is None and result["field_loss"].requires_grad
    assert result["receipt"]["boundary"]["active_rows"] == 0
    result["field_loss"].backward()
    assert torch.count_nonzero(model.body.body.body.output.weight.grad)


@pytest.mark.parametrize("token", [0, 1, 2])
def test_special_token_at_field_site_is_observed_error_with_no_later_invented_sites(token):
    model, codec, rows, contexts, inventory = prepared()
    original = collect(model, codec, rows, contexts)
    first = original["rows"][0]["available_field_sites"][0]
    with torch.no_grad():
        model.body.body.body.output.weight[:, first["position"]].fill_(-20.)
        model.body.body.body.output.weight[token, first["position"]] = 20.
    col = collect(model, codec, rows, contexts)
    assert col["available_field_sites"] == 1 and col["available_sites"] == 0
    result = losses(model, codec, col, inventory, contexts)
    event = result["receipt"]["field"]["events"][0]
    assert event["actual_next_token_id"] == token
    assert event["field"] == first["field"] and event["slot"] == 0


def test_output_limit_keeps_only_actual_visited_sites_and_final_choice():
    model, codec, rows, contexts, inventory = prepared()
    full = collect(model, codec, rows, contexts)
    position = full["rows"][0]["available_field_sites"][0]["position"]
    col = collect(model, codec, rows, contexts, max_target_tokens=position+2)
    assert col["predictions"][0]["generation_status"] == "output_limit" and col["available_field_sites"] == 1
    result = losses(model, codec, col, inventory, contexts)
    assert result["boundary_loss"] is None and result["field_loss"] is not None


@pytest.mark.parametrize("field_value", ["actor", "action", "object", "}"])
def test_quoted_field_names_used_as_values_cannot_create_extra_sites(field_value):
    model, codec, rows, contexts, inventory = prepared()
    original = collect(model, codec, rows, contexts)
    site = next(site for site in original["rows"][0]["available_field_sites"] if site["field"] == "action")
    with torch.no_grad():
        model.body.body.body.output.weight[:, site["position"]].fill_(-20.)
        model.body.body.body.output.weight[codec["target_vocabulary"].index(json.dumps(field_value)), site["position"]] = 20.
    col = collect(model, codec, rows, contexts)
    assert col["available_field_sites"] == 8 and col["available_sites"] == 2
    assert [(s["position"], s["slot"], s["field"]) for s in col["rows"][0]["available_field_sites"]] == [
        (s["position"], s["slot"], s["field"]) for s in original["rows"][0]["available_field_sites"]]
    assert losses(model, codec, col, inventory, contexts)["field_loss"] is not None


def test_invalid_modality_does_not_invent_later_fields_or_boundaries():
    model, codec, rows, contexts, inventory = prepared()
    original = collect(model, codec, rows, contexts)
    site = next(site for site in original["rows"][0]["available_field_sites"] if site["field"] == "modality")
    with torch.no_grad():
        model.body.body.body.output.weight[:, site["position"]].fill_(-20.)
        model.body.body.body.output.weight[codec["target_vocabulary"].index('"agency"'), site["position"]] = 20.
    col = collect(model, codec, rows, contexts)
    assert col["available_sites"] == 0
    assert col["rows"][0]["first_invalid_prefix_position"] == site["position"]+1
    assert all(s["position"] <= site["position"] for s in col["rows"][0]["available_field_sites"])
    result = losses(model, codec, col, inventory, contexts)
    assert result["boundary_loss"] is None
    assert any(event["field"] == "modality" for event in result["receipt"]["field"]["events"])


def test_existing_main_graph_rng_gradients_modes_and_inputs_preserved():
    model, codec, rows, contexts, inventory = prepared()
    model.train()
    model.action_head.eval()
    for parameter in model.parameters():
        parameter.grad = torch.ones_like(parameter)
    versions = old._state_versions(model)
    modes = {name: module.training for name, module in model.named_modules()}
    rng, prng = torch.get_rng_state().clone(), random.getstate()
    original = deepcopy((rows, contexts, inventory))
    main = model.body.count_head.bias.square().sum()
    col = collect(model, codec, rows, contexts)
    result = losses(model, codec, col, inventory, contexts)
    assert old._state_versions(model) == versions
    assert modes == {name: module.training for name, module in model.named_modules()}
    assert torch.equal(rng, torch.get_rng_state()) and random.getstate() == prng
    assert original == (rows, contexts, inventory)
    (main+.05*result["boundary_loss"]+.05*result["field_loss"]).backward()
    assert torch.count_nonzero(model.body.body.body.output.weight.grad)


@pytest.mark.parametrize("field", ["target_ids", "reference_count", "inventory", "target", "site_policy"])
def test_collection_rejects_label_policy_metadata(field):
    model, codec, rows, contexts, _ = prepared()
    rows[0][field] = object()
    with pytest.raises(ValueError, match="source-only"):
        collect(model, codec, rows, contexts)


@pytest.mark.parametrize("argument", ["inventory", "training_references", "site_policy", "fields"])
def test_collection_has_no_reference_inventory_or_policy_argument(argument):
    model, codec, rows, contexts, _ = prepared()
    with pytest.raises(TypeError):
        collect(model, codec, rows, contexts, **{argument: object()})


@pytest.mark.parametrize("mutation", ["extra", "missing", "source", "label"])
def test_exact_closed_context_subset_required(mutation):
    model, codec, rows, contexts, _ = prepared()
    if mutation == "extra":
        contexts["other"] = deepcopy(contexts["train"])
    elif mutation == "missing":
        contexts.clear()
    elif mutation == "source":
        rows[0]["source_text"] += "x"
    else:
        contexts["train"]["target"] = {}
    with pytest.raises(ValueError):
        collect(model, codec, rows, contexts)


@pytest.mark.parametrize("mutation", ["model", "context", "transform", "source"])
def test_stale_model_context_transform_or_input_refused(mutation):
    model, codec, rows, contexts, inventory = prepared()
    col = collect(model, codec, rows, contexts)
    kwargs = {}
    if mutation == "model":
        with torch.no_grad():
            model.body.count_head.bias[0] += .1
    elif mutation == "context":
        contexts["train"]["segments"][0]["vector"][0] = .5
    elif mutation == "transform":
        kwargs["input_transform"] = dict(transform(), scale=2.)
    else:
        col["source_rows"][0]["input"][0] += 1.
    with pytest.raises(ValueError, match="stale|digest"):
        losses(model, codec, col, inventory, contexts, **kwargs)


@pytest.mark.parametrize("mutation", ["position", "slot", "field", "argmax", "missing", "logits"])
def test_rehashed_forged_field_sites_are_refused(mutation):
    model, codec, rows, contexts, inventory = prepared()
    col = collect(model, codec, rows, contexts)
    site = col["rows"][0]["available_field_sites"][0]
    if mutation == "position":
        site["position"] += 1
    elif mutation == "slot":
        site["slot"] += 1
    elif mutation == "field":
        site["field"] = "actor" if site["field"] != "actor" else "action"
    elif mutation == "argmax":
        site["actual_next_token_id"] = 2
    elif mutation == "missing":
        col["rows"][0]["available_field_sites"].pop()
    else:
        site["collection_logits"][0] += .1
    resign(col, "collection_sha256")
    with pytest.raises(ValueError):
        losses(model, codec, col, inventory, contexts)


@pytest.mark.parametrize("mutation", ["input", "context", "source", "offset", "slot", "label", "validation"])
def test_rehashed_inventory_cannot_change_source_alignment_or_bounds(mutation):
    model, codec, rows, contexts, inventory = prepared()
    col = collect(model, codec, rows, contexts)
    record = inventory["rows"]["train"]
    if mutation == "input":
        record["input_sha256"] = "a"*64
    elif mutation == "context":
        record["source_context_sha256"] = "a"*64
    elif mutation == "source":
        record["clauses"][0]["source_sha256"] = "a"*64
    elif mutation == "offset":
        record["clauses"][0]["char_start"] += 1
    elif mutation == "slot":
        record["clauses"][0]["reference_rule_index"] += 1
    elif mutation == "label":
        record["clauses"][0]["target_token_ids"]["actor"] = -1
    else:
        inventory["validation_rows_used"] = True
    resign(inventory, "inventory_sha256")
    with pytest.raises(ValueError):
        losses(model, codec, col, inventory, contexts)


@pytest.mark.parametrize("wrapper", [recurrent.bind_zero_condition_model, recurrent.bind_residual_off_model])
def test_inference_controls_are_not_admitted_as_training_models(wrapper):
    model, codec, rows, contexts, _ = prepared()
    with pytest.raises(ValueError, match="supported trainable"):
        collect(wrapper(model), codec, rows, contexts)


def test_non_contextual_model_is_explicitly_unsupported():
    model, codec, rows, contexts = scripted("shared")
    with pytest.raises(ValueError, match="contextual"):
        collect(model, codec, rows, contexts)


@pytest.mark.parametrize("value", [0, True, 513])
def test_output_ceiling_cannot_change(value):
    model, codec, rows, contexts, _ = prepared()
    with pytest.raises(ValueError, match="fixed512"):
        collect(model, codec, rows, contexts, max_target_tokens=value)


def test_unknown_policy_and_field_scope_refused():
    model, codec, rows, contexts, inventory = prepared()
    col = collect(model, codec, rows, contexts)
    with pytest.raises(ValueError, match="policy"):
        losses(model, codec, col, inventory, contexts, boundary_site_policy="all")
    with pytest.raises(TypeError):
        losses(model, codec, col, inventory, contexts, fields=("actor",))


def test_deadline_during_collection_and_replay_preserves_caller(monkeypatch):
    model, codec, rows, contexts, inventory = prepared()
    col = collect(model, codec, rows, contexts)
    before = old._snapshot(model, torch)
    with pytest.raises(TimeoutError):
        collect(model, codec, rows, contexts, deadline=time.monotonic()-1)
    with pytest.raises(TimeoutError):
        losses(model, codec, col, inventory, contexts, deadline=time.monotonic()-1)
    tick = [0.]
    def clock():
        tick[0] += 1.
        return tick[0]
    monkeypatch.setattr(subject.time, "monotonic", clock)
    with pytest.raises(TimeoutError):
        collect(model, codec, rows, contexts, deadline=12.)
    old._preserved(model, torch, before)
    tick[0] = 0.
    with pytest.raises(TimeoutError):
        losses(model, codec, col, inventory, contexts, deadline=12.)
    old._preserved(model, torch, before)


def test_replay_exception_restores_mixed_modes_gradients_and_rng(monkeypatch):
    model, codec, rows, contexts, inventory = prepared()
    model.train()
    model.action_head.eval()
    for parameter in model.parameters():
        parameter.grad = torch.ones_like(parameter)
    col = collect(model, codec, rows, contexts)
    before = old._snapshot(model, torch)
    def fail(*args, **kwargs):
        raise RuntimeError("synthetic replay failure")
    monkeypatch.setattr(subject.core, "_logits", fail)
    with pytest.raises(RuntimeError, match="synthetic replay"):
        losses(model, codec, col, inventory, contexts)
    old._preserved(model, torch, before)


def _force_bulk_mismatch(monkeypatch):
    original = subject._bulk_replay
    def changed(*args, **kwargs):
        return original(*args, **kwargs) + .1
    monkeypatch.setattr(subject, "_bulk_replay", changed)


@pytest.mark.parametrize("kind", ["clause", "action", "recurrent"])
@pytest.mark.parametrize("dimension", [8, 384, 768])
def test_strict_incremental_retry_matches_collection_with_all_trainable_gradients(kind, dimension, monkeypatch):
    model, codec, rows, contexts, inventory = prepared(kind, dimension=dimension)
    collection = collect(model, codec, rows, contexts)
    _force_bulk_mismatch(monkeypatch)
    before = old._snapshot(model, torch)
    result = losses(model, codec, collection, inventory, contexts)
    old._preserved(model, torch, before)
    receipt = result["receipt"]
    assert receipt["schema"] == "generated-source-field-loss/v2"
    assert not receipt["one_union_replay_per_active_row"]
    assert receipt["one_union_gradient_replay_per_active_row"]
    assert receipt["bulk_replay_batch_count"] == receipt["discarded_bulk_batch_count"] == 1
    assert receipt["incremental_retry_batch_count"] == receipt["replay_batch_count"] == 1
    bulk, retry = receipt["replay_attempts"]
    assert not bulk["parity_passed"] and not bulk["used_for_loss"] and bulk["mismatches"]
    assert retry["parity_passed"] and retry["used_for_loss"] and not retry["mismatches"]
    assert retry["maximum_absolute_difference"] == receipt["maximum_replay_logit_absolute_difference"] == 0.
    assert bulk["before_component_cross_entropy"] and retry["before_component_cross_entropy"]
    assert retry["original_batch_membership_preserved"] and retry["collected_prefix_checked"]
    assert receipt["incremental_retry_forward_steps"] == retry["prefix_steps"] == retry["forward_calls"]
    assert receipt["physical_replay_forward_calls"] == 1+retry["prefix_steps"]
    assert receipt["physical_replay_row_tokens"] == receipt["bulk_attempted_row_tokens"]+receipt["retry_attempted_row_tokens"]
    available = {site["position"]: site for site in collection["rows"][0]["available_sites"]+collection["rows"][0]["available_field_sites"]}
    for record in retry["selected_logits"]:
        assert record["logits"] == available[record["position"]]["collection_logits"]
    for component in ("boundary", "field"):
        for event in receipt[component]["events"]:
            accepted = next(record for record in retry["selected_logits"] if record["id"] == event["id"] and record["position"] == event["position"])
            assert event["replay_logits"] is accepted["logits"]
            expected = torch.nn.functional.cross_entropy(torch.tensor([event["replay_logits"]]), torch.tensor([event["target_token_id"]]))
            assert event["cross_entropy"] == float(expected)
    (result["boundary_loss"]+result["field_loss"]).backward()
    assert model.body.body.body.output.weight.grad is not None
    assert receipt["additional_optimizer_steps"] == 0


def test_successful_bulk_replay_does_not_invoke_retry(monkeypatch):
    model, codec, rows, contexts, inventory = prepared()
    collection = collect(model, codec, rows, contexts)
    monkeypatch.setattr(subject, "_incremental_replay", lambda *a, **k: pytest.fail("successful bulk must not retry"))
    receipt = losses(model, codec, collection, inventory, contexts)["receipt"]
    assert receipt["one_union_replay_per_active_row"]
    assert receipt["bulk_replay_batch_count"] == receipt["physical_replay_forward_calls"] == 1
    assert receipt["incremental_retry_batch_count"] == receipt["discarded_bulk_batch_count"] == receipt["retry_attempted_row_tokens"] == 0
    assert len(receipt["replay_attempts"]) == 1 and receipt["replay_attempts"][0]["used_for_loss"]


def test_rejected_bulk_graph_is_dropped_before_retry_and_no_ce_precedes_retry(monkeypatch):
    import weakref
    model, codec, rows, contexts, inventory = prepared()
    collection = collect(model, codec, rows, contexts)
    original_bulk, original_retry = subject._bulk_replay, subject._incremental_replay
    references, phases = [], []
    def bulk(*args, **kwargs):
        value = original_bulk(*args, **kwargs)+.1
        references.append(weakref.ref(value))
        value.register_hook(lambda gradient: pytest.fail("discarded bulk graph received gradients"))
        return value
    def retry(*args, **kwargs):
        assert references[0]() is None
        assert not phases
        result = original_retry(*args, **kwargs)
        phases.append("retried")
        return result
    original_ce = torch.nn.functional.cross_entropy
    def checked_ce(*args, **kwargs):
        assert phases == ["retried"]
        return original_ce(*args, **kwargs)
    monkeypatch.setattr(subject, "_bulk_replay", bulk)
    monkeypatch.setattr(subject, "_incremental_replay", retry)
    monkeypatch.setattr(torch.nn.functional, "cross_entropy", checked_ce)
    result = losses(model, codec, collection, inventory, contexts)
    (result["boundary_loss"]+result["field_loss"]).backward()


def _several_rows(count=2):
    model, codec, rows, contexts = scripted("recurrent", count=2)
    template = deepcopy(rows[0])
    vectors = [segment["vector"] for segment in contexts["train"]["segments"]]
    rows, contexts = [], {}
    targets = {}
    for index in range(count):
        identity = "row"+str(index)
        text = f"Agency source {index}.\n\nOfficer source {index}."
        rows.append(dict(id=identity, source_text=text, input=template["input"][:]))
        contexts[identity] = contexts_owner._descriptor(text, vectors)
        targets[identity] = [dict(rule(), actor="a"), rule()] if index % 2 else [rule(), rule()]
    train, references = labelled(rows, contexts, codec, targets=targets)
    inventory = subject.prepare_training_inventory(train, references, contexts=contexts, codec=codec, validate_rule=validate_rule)
    return model, codec, rows, contexts, inventory


def test_retry_keeps_unselected_original_rows_and_original_batch_boundaries(monkeypatch):
    model, codec, rows, contexts, inventory = _several_rows(6)
    collection = collect(model, codec, rows, contexts, batch_size=2)
    _force_bulk_mismatch(monkeypatch)
    receipt = losses(model, codec, collection, inventory, contexts, boundary_site_policy="first_wrong")["receipt"]
    assert receipt["union_active_rows"] == receipt["replay_batch_count"] == 3
    assert receipt["bulk_replay_batch_count"] == receipt["incremental_retry_batch_count"] == 3
    for offset in (0, 2, 4):
        attempts = [item for item in receipt["replay_attempts"] if item["original_batch_offset"] == offset]
        assert len(attempts) == 2
        bulk, retry = attempts
        assert bulk["row_ids"] == retry["active_row_ids"] == ["row"+str(offset+1)]
        assert retry["row_ids"] == ["row"+str(offset), "row"+str(offset+1)]
        assert retry["physical_row_tokens"] == 2*bulk["physical_row_tokens"]
    assert receipt["retry_limit_per_original_batch"] == 1


@pytest.mark.parametrize("failure", ["mismatch", "timeout", "prefix"])
def test_retry_failure_retains_guard_and_preserves_caller(failure, monkeypatch):
    model, codec, rows, contexts, inventory = prepared()
    collection = collect(model, codec, rows, contexts)
    _force_bulk_mismatch(monkeypatch)
    original = subject._incremental_replay
    before = old._snapshot(model, torch)
    def failed(*args, **kwargs):
        if failure == "timeout":
            raise TimeoutError("synthetic retry deadline")
        if failure == "prefix":
            real = model.next_logits
            def differing(tokens, state):
                logits, updated = real(tokens, state)
                adjusted = logits.clone()
                adjusted[:, :, 0] = 1000.
                return adjusted, updated
            with monkeypatch.context() as patch:
                patch.setattr(model, "next_logits", differing)
                return original(*args, **kwargs)
        result = original(*args, **kwargs)
        return {identity: {position: value+.1 for position, value in sites.items()} for identity, sites in result.items()}
    monkeypatch.setattr(subject, "_incremental_replay", failed)
    monkeypatch.setattr(torch.nn.functional, "cross_entropy", lambda *a, **k: pytest.fail("failed retry must not create CE"))
    with pytest.raises(TimeoutError if failure == "timeout" else ValueError, match="deadline|differ"):
        losses(model, codec, collection, inventory, contexts)
    old._preserved(model, torch, before)
    assert subject.boundary.REPLAY_ATOL == subject.boundary.REPLAY_RTOL == 2e-5


@pytest.mark.parametrize("offset", [1, -1, True, 0.0, "0"])
def test_rehashed_original_batch_offset_forgery_is_refused(offset, monkeypatch):
    model, codec, rows, contexts, inventory = prepared()
    collection = collect(model, codec, rows, contexts)
    collection["rows"][0]["batch_offset"] = offset
    resign(collection, "collection_sha256")
    monkeypatch.setattr(subject, "_bulk_replay", lambda *a, **k: pytest.fail("forged batch must fail before replay"))
    with pytest.raises(ValueError, match="batch offset"):
        losses(model, codec, collection, inventory, contexts)


def test_retry_continues_terminated_original_rows_with_actual_argmax_not_padding(monkeypatch):
    model, codec, rows, contexts, inventory = _several_rows(2)
    rows[0]["input"][0] += 1.
    train, references = labelled(rows, contexts, codec, wrong=True)
    inventory = subject.prepare_training_inventory(train, references, contexts=contexts, codec=codec, validate_rule=validate_rule)
    real = model.next_logits
    trace = []
    with torch.no_grad():
        projected = model.project(subject.boundary.legacy._data(torch, rows, transform(model.dimension)))
        marker = float(projected[0, 0])
        assert marker != float(projected[1, 0])
    def terminated_row(tokens, state):
        logits, updated = real(tokens, state)
        changed = logits.clone()
        for index in range(len(tokens)):
            if float(state[1][index, 0]) == marker:
                for offset in range(tokens.shape[1]):
                    position = int(state[2][index])+offset
                    changed[index, offset].fill_(-100.)
                    changed[index, offset, 2 if position == 0 else 3+position % 5] = 100.
        if tokens.shape[1] == 1 and len(tokens) == 2:
            trace.append(tokens[:, 0].tolist())
        return changed, updated
    monkeypatch.setattr(model, "next_logits", terminated_row)
    collection = collect(model, codec, rows, contexts)
    assert collection["predictions"][0]["generation_status"] == "eos"
    assert collection["rows"][0]["consumed_prefix"] == [1]
    collected_trace = deepcopy(trace)
    trace.clear()
    _force_bulk_mismatch(monkeypatch)
    receipt = losses(model, codec, collection, inventory, contexts)["receipt"]
    retry = receipt["replay_attempts"][-1]
    assert retry["row_ids"] == ["row0", "row1"] and retry["active_row_ids"] == ["row1"]
    assert trace == collected_trace[:retry["prefix_steps"]]
    assert trace[1][0] == 2 and all(pair[0] != 0 for pair in trace)
    assert retry["parity_passed"] and retry["collected_prefix_checked"]
