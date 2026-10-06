"""Adversarial v2 inference/training boundaries, not trained-model accuracy.

Forced logits isolate validation and learned-refusal routing. Real forwards
test byte-order observability; they do not claim correct source interpretation.
"""
from copy import deepcopy
import hashlib
import inspect
import json

import pytest
import torch

from ipfs_datasets_py.logic.formalization.autoencoder import legal_grouped_span_decoder_v2 as head

ACTIONS = ("publish notice", "retain records", "file reports", "copy documents",
           "display lists", "seal envelopes", "store ledgers", "record receipts")


@pytest.fixture(scope="module", autouse=True)
def limited_threads():
    previous = torch.get_num_threads()
    torch.set_num_threads(2)
    yield
    torch.set_num_threads(previous)


@pytest.fixture
def model():
    return head.GroupedSpanDecoder(head.SpanDecoderConfig(
        seed=121, byte_dim=4, byte_hidden=4, token_dim=8, token_hidden=8, slot_hidden=8))


def example(count=2, scope="disjunction_of_norms", modality="O", duplicate=False):
    source = "The Registrar "
    members = []
    modal = {"O": "shall", "P": "may", "F": "shall not"}[modality]
    for index in range(count):
        if index:
            source += " or "
        source += modal + " "
        start = len(source)
        source += ACTIONS[0] if duplicate else ACTIONS[index]
        members.append(head.GroupedSpanTarget((4, 13), (start, len(source)), modality))
    return head.GroupedSpanExample(source + ".", scope, tuple(members), supported=True)


def logits(model, target, support=20.0):
    tokens = head.tokenize_source(target.source_text, model.config)
    starts, ends = {t.start: i for i, t in enumerate(tokens)}, {t.end: i for i, t in enumerate(tokens)}
    values = {"support": torch.tensor([support], dtype=torch.float32),
              "count": torch.full((1, 7), -100.0), "scope": torch.full((1, 2), -100.0),
              "modality": torch.full((1, 8, 3), -100.0)}
    values.update({name: torch.full((1, 8, len(tokens)), -100.0) for name in head.POINTERS})
    values["count"][0, len(target.members) - 2] = 100
    values["scope"][0, head.SCOPES.index(target.modal_scope)] = 100
    for index, member in enumerate(target.members):
        values["modality"][0, index, head.MODALITIES.index(member.modality)] = 100
        for field in ("actor", "action"):
            span = getattr(member, field + "_span")
            values[field + "_start"][0, index, starts[span[0]]] = 100
            values[field + "_end"][0, index, ends[span[1]]] = 100
    return values


def install(monkeypatch, model, values):
    calls = []
    def forward(*args):
        calls.append(tuple(value.detach().clone() for value in args))
        return values
    monkeypatch.setattr(model, "forward", forward)
    return calls


@pytest.mark.parametrize("count", range(2, 9))
def test_supported_outputs_keep_ordered_inherited_actor_and_duplicate_occurrences(monkeypatch, model, count):
    target = example(count, duplicate=True)
    install(monkeypatch, model, logits(model, target))
    result = head.predict_grouped_span_decoder(model, target.source_text, target.modal_scope)
    assert result["status"] == "predicted"
    assert len(result["request"]["members"]) == count
    assert [member["action"] for member in result["request"]["members"]] == ["publish notice"] * count
    assert result["predicted_character_spans"] == [
        {"actor": list(member.actor_span), "action": list(member.action_span)} for member in target.members]
    assert len({tuple(member["action"]) for member in result["predicted_character_spans"]}) == count
    assert result["source_semantics_verified"] is result["proof_ready"] is result["targets_used_at_inference"] is False


@pytest.mark.parametrize("scope", head.SCOPES)
@pytest.mark.parametrize("modality", head.MODALITIES)
def test_supported_scope_and_operators_are_independently_preserved(monkeypatch, model, scope, modality):
    target = example(3, scope, modality)
    install(monkeypatch, model, logits(model, target))
    result = head.predict_grouped_span_decoder(model, target.source_text, scope)
    assert result["request"]["modal_scope"] == scope
    assert [member["modality"] for member in result["request"]["members"]] == [modality] * 3


@pytest.mark.parametrize("score,status", [(-20.0, "abstained"), (-0.001, "abstained"), (0.0, "predicted"), (20.0, "predicted")])
def test_support_threshold_uses_actual_probability_without_target_override(monkeypatch, model, score, status):
    target = example()
    install(monkeypatch, model, logits(model, target, score))
    result = head.predict_grouped_span_decoder(model, target.source_text, target.modal_scope)
    assert result["status"] == status
    assert result["support_probability"] == float(torch.tensor(score).sigmoid())
    assert result["support_threshold"] == 0.5
    assert result["confidence"]["support"] == result["raw_prediction"]["support_probability"] == result["support_probability"]
    if status == "abstained":
        assert result["request"] is None and result["blockers"] == ["learned_source_unsupported"]


def test_low_support_never_constructs_or_repairs_a_semantic_request(monkeypatch, model):
    target = example()
    values = logits(model, target, -20)
    values["actor_start"][0, 0].fill_(-100)
    values["actor_start"][0, 0, -1] = 100
    install(monkeypatch, model, values)
    def forbidden(*args, **kwargs):
        raise AssertionError("Refusal attempted to build a semantic target")
    monkeypatch.setattr(head.semantic, "CoordinationDecodeMember", forbidden)
    result = head.predict_grouped_span_decoder(model, target.source_text, target.modal_scope)
    assert result["status"] == "abstained" and result["request"] is None
    assert result["raw_prediction"]["members"][0]["actor_start"] > result["raw_prediction"]["members"][0]["actor_end"]


@pytest.mark.parametrize("mutation", ["missing_support", "scalar", "two_dimensional", "wrong_batch", "float64", "bool", "non_tensor", "extra_teacher"])
def test_malformed_support_heads_fail_closed_even_with_negative_support(monkeypatch, model, mutation):
    target = example()
    values = logits(model, target, -20)
    if mutation == "missing_support":
        del values["support"]
    elif mutation == "scalar":
        values["support"] = torch.tensor(-20.0)
    elif mutation == "two_dimensional":
        values["support"] = torch.zeros((1, 1))
    elif mutation == "wrong_batch":
        values["support"] = torch.zeros((2,))
    elif mutation == "float64":
        values["support"] = values["support"].double()
    elif mutation == "bool":
        values["support"] = torch.tensor([False])
    elif mutation == "non_tensor":
        values["support"] = [-20.0]
    else:
        values["target_supported"] = torch.tensor([False])
    install(monkeypatch, model, values)
    result = head.predict_grouped_span_decoder(model, target.source_text, target.modal_scope)
    assert result["status"] == "blocked" and result["blockers"] == ["malformed_model_prediction"]
    assert result["request"] is result["raw_prediction"] is None


@pytest.mark.parametrize("field", ["support", "count", "scope", "modality", *head.POINTERS])
def test_negative_support_does_not_hide_nonfinite_other_heads(monkeypatch, model, field):
    target = example()
    values = logits(model, target, -20)
    values[field].reshape(-1)[0] = float("nan")
    install(monkeypatch, model, values)
    result = head.predict_grouped_span_decoder(model, target.source_text, target.modal_scope)
    assert result["status"] == "blocked" and result["blockers"] == ["nonfinite_model_prediction"]
    assert result["request"] is result["raw_prediction"] is None


@pytest.mark.parametrize("choice", [None, "", "automatic", "exclusive_or", True, 1])
def test_missing_caller_scope_does_not_run_support_classifier(monkeypatch, model, choice):
    def forbidden(*args, **kwargs):
        raise AssertionError("Ran model without explicit caller scope")
    monkeypatch.setattr(model, "forward", forbidden)
    result = head.predict_grouped_span_decoder(model, example().source_text, choice)
    assert result["status"] == "abstained" and result["raw_prediction"] is None
    assert result["blockers"] == ["explicit_caller_scope_required"]


@pytest.mark.parametrize("mutation", ["scope", "reversed_actor", "reversed_action"])
def test_high_support_cannot_override_scope_or_span_validation(monkeypatch, model, mutation):
    target = example()
    values = logits(model, target)
    if mutation == "scope":
        values["scope"][0] = torch.tensor([100.0, -100.0])
    else:
        field = mutation.split("_")[1]
        values[field + "_start"][0, 0].fill_(-100)
        values[field + "_start"][0, 0, -1] = 100
    install(monkeypatch, model, values)
    result = head.predict_grouped_span_decoder(model, target.source_text, target.modal_scope)
    assert result["status"] == "blocked" and result["request"] is None
    assert result["raw_prediction"] is not None and result["support_probability"] > .99


@pytest.mark.parametrize("source_mutation", [False, True])
@pytest.mark.parametrize("support", [-20.0, 20.0])
def test_refusal_comes_from_learned_head_without_modal_dictionary_or_parser(monkeypatch, model, source_mutation, support):
    from ipfs_datasets_py.logic.deontic.utils import deontic_parser
    target = example()
    source = target.source_text.replace("shall", "shlal") if source_mutation else target.source_text
    calls = install(monkeypatch, model, logits(model, target, support))
    def forbidden(*args, **kwargs):
        raise AssertionError("Source parser or target labels consulted at inference")
    # The source-only integration need not install the optional legacy bridge.
    # If it is absent, prove that any attempted fallback import fails. If it
    # exists in a later integration, poison its real source-recovery helpers.
    import importlib
    import importlib.util
    import sys
    for module_name in (
        "ipfs_datasets_py.logic.deontic.coordination",
        "ipfs_datasets_py.logic.autoformal.legal_coordination",
    ):
        if importlib.util.find_spec(module_name) is None:
            monkeypatch.setitem(sys.modules, module_name, None)
            with pytest.raises(ModuleNotFoundError):
                importlib.import_module(module_name)
        else:
            optional_module = importlib.import_module(module_name)
            for helper in ("build_coordination_groups", "reconstruct_source", "compile_coordination_group",
                           "reconstruct_compiled_group", "coordination_decode_request_from_compiled"):
                if hasattr(optional_module, helper):
                    monkeypatch.setattr(optional_module, helper, forbidden)
                    with pytest.raises(AssertionError):
                        getattr(optional_module, helper)()
    monkeypatch.setattr(deontic_parser, "extract_normative_elements", forbidden)
    monkeypatch.setattr(head, "_labels", forbidden)
    assert list(inspect.signature(head.predict_grouped_span_decoder).parameters) == ["model", "source_text", "modal_scope"]
    result = head.predict_grouped_span_decoder(model, source, target.modal_scope)
    assert result["status"] == ("abstained" if support < 0 else "predicted")
    tokens = head.tokenize_source(source, model.config)
    values, mask, scope = calls[0]
    reconstructed = [bytes((values[0, i, values[0, i] != 0] - 1).tolist()).decode() for i in range(len(tokens))]
    assert reconstructed == [token.text for token in tokens]
    assert len(calls) == 1 and int(mask.sum()) == len(tokens)
    assert int(scope[0]) == head.SCOPES.index(target.modal_scope)



@pytest.mark.parametrize("supported,members", [(1, ()), (0, ()), (None, ()), (True, ()), (False, "positive")])
def test_support_targets_cannot_be_coerced_or_carry_conflicting_structure(supported, members):
    actual_members = example().members if members == "positive" else members
    with pytest.raises(ValueError):
        head.GroupedSpanExample("The Registrar shall publish notice or shall retain records.", "disjunction_of_norms", actual_members, supported)


@pytest.mark.parametrize("original,mutated", [("shall", "shlal"), ("must", "msut"), ("permitted", "perimtted")])
def test_ordered_byte_features_distinguish_the_previous_pooling_collision(model, original, mutated):
    captured = []
    hook = model.token_projection.register_forward_pre_hook(lambda module, inputs: captured.append(inputs[0].detach().clone()))
    try:
        batch, _ = head._encoded_sources(model.config, [original, mutated], ["disjunction_of_norms"] * 2)
        with torch.no_grad():
            model(*batch)
    finally:
        hook.remove()
    assert original[0] == mutated[0] and original[-1] == mutated[-1]
    assert sorted(original) == sorted(mutated)
    assert float((captured[0][0, 0] - captured[0][1, 0]).abs().max()) > 1e-6


def test_padding_width_and_neighbor_batch_do_not_change_real_token_features(model):
    source = example().source_text
    longer = "The International Administrator shall publish comprehensive documentation or shall retain records."
    captured = []
    hook = model.token_projection.register_forward_pre_hook(lambda module, inputs: captured.append(inputs[0].detach().clone()))
    try:
        one, token_rows = head._encoded_sources(model.config, [source], ["disjunction_of_norms"])
        two, _ = head._encoded_sources(model.config, [longer, source], ["modal_over_actions", "disjunction_of_norms"])
        with torch.no_grad():
            alone, mixed = model(*one), model(*two)
    finally:
        hook.remove()
    count = len(token_rows[0])
    torch.testing.assert_close(captured[0][0, :count], captured[1][1, :count], rtol=1e-6, atol=1e-6)
    for field in ("support", "count", "scope", "modality"):
        torch.testing.assert_close(alone[field][0], mixed[field][1], rtol=1e-5, atol=1e-6)
    for field in head.POINTERS:
        torch.testing.assert_close(alone[field][0], mixed[field][1, :, :count], rtol=1e-5, atol=1e-6)


def test_negative_only_steps_preserve_already_active_structure_moments_and_weights(model):
    optimizer = head.make_grouped_span_optimizer(model, weight_decay=.2)
    head.train_grouped_span_step(model, optimizer, [example()])
    structural = ("slot_queries.", "attention_keys.", "slot_fusion.", "count_head.", "scope_head.",
                  "modality_head.", "pointer_keys.", "pointer_queries.")
    parameters = dict(model.named_parameters())
    before = {name: parameter.detach().clone() for name, parameter in parameters.items()}
    states = {name: {key: value.clone() for key, value in optimizer.state[parameter].items()}
              for name, parameter in parameters.items() if name.startswith(structural)}
    negative = head.GroupedSpanExample("The Registrar shlal publish notice or shlal retain records.", "disjunction_of_norms", (), False)
    for _ in range(2):
        metrics = head.train_grouped_span_step(model, optimizer, [negative])
        assert metrics["supported_examples"] == 0 and metrics["unsupported_examples"] == 1
        assert metrics["support_loss"] > 0
        assert all(metrics[field + "_loss"] == 0 for field in ("count", "scope", "modality", *head.POINTERS))
    for name, parameter in parameters.items():
        if name.startswith(structural):
            assert parameter.grad is None and torch.equal(parameter.detach(), before[name])
            assert all(torch.equal(value, states[name][key]) for key, value in optimizer.state[parameter].items())
    assert not torch.equal(parameters["support_head.weight"].detach(), before["support_head.weight"])
    checkpoint = head.save_grouped_span_checkpoint(model, optimizer, steps=3)
    restored, restored_optimizer, steps = head.restore_grouped_span_checkpoint(checkpoint)
    assert steps == 3
    assert head.save_grouped_span_checkpoint(restored, restored_optimizer, steps=3) == checkpoint


def test_self_resealed_checkpoint_cannot_change_support_policy(model):
    optimizer = head.make_grouped_span_optimizer(model)
    checkpoint = head.save_grouped_span_checkpoint(model, optimizer, steps=0)
    forged = deepcopy(checkpoint)
    forged["profile"]["support_threshold"] = .1
    forged.pop("checkpoint_sha256")
    forged["checkpoint_sha256"] = hashlib.sha256(json.dumps(forged, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()).hexdigest()
    with pytest.raises(ValueError):
        head.restore_grouped_span_checkpoint(forged)
