"""Source-conditioned grouped span head boundary tests, not accuracy evidence.

Forced logits isolate inference validation. They are never presented as trained
model predictions or reviewed legal interpretations.
"""
from copy import deepcopy
from dataclasses import replace
import inspect

import pytest
import torch

from ipfs_datasets_py.logic.formalization.autoencoder import legal_grouped_span_decoder as head

ACTIONS = ("publish notice", "retain records", "file reports", "copy documents",
           "display lists", "seal envelopes", "store ledgers", "record receipts")


def source_example(count=2, scope="disjunction_of_norms", operator="O", duplicate=False):
    source = "The Registrar "
    actor_span = (4, 13)
    targets = []
    modal = {"O": "shall", "P": "may", "F": "shall not"}[operator]
    for index in range(count):
        if index:
            source += " or "
        source += modal + " "
        action = ACTIONS[0] if duplicate else ACTIONS[index]
        start = len(source)
        source += action
        targets.append(head.GroupedSpanTarget(actor_span, (start, len(source)), operator))
    return head.GroupedSpanExample(source + ".", scope, tuple(targets))


@pytest.fixture
def model():
    return head.GroupedSpanDecoder(head.SpanDecoderConfig(
        seed=121, byte_dim=4, token_dim=8, token_hidden=8, slot_hidden=8,
    ))


def forced_outputs(model, example):
    tokens = head.tokenize_source(example.source_text, model.config)
    starts = {token.start: i for i, token in enumerate(tokens)}
    ends = {token.end: i for i, token in enumerate(tokens)}
    logits = {"count": torch.full((1, 7), -100.0), "scope": torch.full((1, 2), -100.0),
              "modality": torch.full((1, 8, 3), -100.0)}
    logits.update({name: torch.full((1, 8, len(tokens)), -100.0) for name in head.POINTERS})
    logits["count"][0, len(example.members) - 2] = 100
    logits["scope"][0, head.SCOPES.index(example.modal_scope)] = 100
    for i, member in enumerate(example.members):
        logits["modality"][0, i, head.MODALITIES.index(member.modality)] = 100
        for slot in ("actor", "action"):
            span = getattr(member, slot + "_span")
            logits[slot + "_start"][0, i, starts[span[0]]] = 100
            logits[slot + "_end"][0, i, ends[span[1]]] = 100
    return logits


def install_outputs(monkeypatch, model, outputs):
    calls = []
    def forward(token_bytes, token_mask, scope_indices):
        calls.append((token_bytes.detach().clone(), token_mask.detach().clone(), scope_indices.detach().clone()))
        return outputs
    monkeypatch.setattr(model, "forward", forward)
    return calls


@pytest.mark.parametrize("count", range(2, 9))
def test_predicted_count_and_all_ordered_source_spans_are_preserved(monkeypatch, model, count):
    example = source_example(count)
    calls = install_outputs(monkeypatch, model, forced_outputs(model, example))
    result = head.predict_grouped_span_decoder(model, example.source_text, example.modal_scope)
    assert len(calls) == 1
    assert result["status"] == "predicted"
    assert result["raw_prediction"]["count"] == len(result["request"]["members"]) == count
    assert result["request"]["members"] == [
        {"actor": "registrar", "modality": "O", "action": ACTIONS[i]} for i in range(count)
    ]
    assert result["predicted_character_spans"] == [
        {"actor": list(member.actor_span), "action": list(member.action_span)} for member in example.members
    ]
    assert result["source_semantics_verified"] is result["proof_ready"] is result["targets_used_at_inference"] is False


@pytest.mark.parametrize("scope", head.SCOPES)
@pytest.mark.parametrize("operator", head.MODALITIES)
def test_caller_scope_and_predicted_operator_survive_source_span_copy(monkeypatch, model, scope, operator):
    example = source_example(3, scope, operator)
    install_outputs(monkeypatch, model, forced_outputs(model, example))
    result = head.predict_grouped_span_decoder(model, example.source_text, scope)
    assert result["status"] == "predicted"
    assert result["request"]["modal_scope"] == scope
    assert [member["modality"] for member in result["request"]["members"]] == [operator] * 3


def test_duplicate_action_occurrences_keep_distinct_ordered_pointer_evidence(monkeypatch, model):
    example = source_example(3, duplicate=True)
    install_outputs(monkeypatch, model, forced_outputs(model, example))
    result = head.predict_grouped_span_decoder(model, example.source_text, example.modal_scope)
    assert result["status"] == "predicted"
    assert [member["action"] for member in result["request"]["members"]] == ["publish notice"] * 3
    spans = [row["action"] for row in result["predicted_character_spans"]]
    assert len({tuple(span) for span in spans}) == 3
    assert all(left[1] < right[0] for left, right in zip(spans, spans[1:]))
    assert {tuple(row["actor"]) for row in result["predicted_character_spans"]} == {(4, 13)}


@pytest.mark.parametrize("choice", [None, "", "automatic", "exclusive_or", True, 1])
def test_missing_or_unknown_caller_choice_abstains_without_running_model(monkeypatch, model, choice):
    def forbidden(*args, **kwargs):
        raise AssertionError("Model executed without a caller scope")
    monkeypatch.setattr(model, "forward", forbidden)
    result = head.predict_grouped_span_decoder(model, source_example().source_text, choice)
    assert result["status"] == "abstained"
    assert result["request"] is None
    assert result["raw_prediction"] is None
    assert "explicit_caller_scope_required" in result["blockers"]


def test_scope_head_disagreement_blocks_without_replacing_the_prediction(monkeypatch, model):
    example = source_example(scope="modal_over_actions")
    outputs = forced_outputs(model, example)
    outputs["scope"] = torch.tensor([[-100.0, 100.0]])
    install_outputs(monkeypatch, model, outputs)
    result = head.predict_grouped_span_decoder(model, example.source_text, example.modal_scope)
    assert result["status"] == "blocked" and result["request"] is None
    assert result["raw_prediction"]["modal_scope"] == "disjunction_of_norms"
    assert "predicted_scope_disagrees_with_caller" in result["blockers"]


@pytest.mark.parametrize("mutation", ["reversed_actor", "reversed_action", "modal_in_actor", "modal_in_action"])
def test_invalid_learned_spans_block_without_parser_or_reference_repair(monkeypatch, model, mutation):
    example = source_example()
    tokens = head.tokenize_source(example.source_text, model.config)
    outputs = forced_outputs(model, example)
    if mutation.startswith("reversed"):
        slot = mutation.split("_")[1]
        outputs[slot + "_start"][0, 0].fill_(-100)
        outputs[slot + "_start"][0, 0, -1] = 100
    else:
        slot = mutation.split("_")[-1]
        start = next(i for i, token in enumerate(tokens) if token.text == "shall")
        for key in (slot + "_start", slot + "_end"):
            outputs[key][0, 0].fill_(-100)
            outputs[key][0, 0, start] = 100
    install_outputs(monkeypatch, model, outputs)
    result = head.predict_grouped_span_decoder(model, example.source_text, example.modal_scope)
    assert result["status"] == "blocked" and result["request"] is None
    assert result["raw_prediction"] is not None
    assert "predicted_span_or_request_invalid" in result["blockers"]


@pytest.mark.parametrize("mutation", [
    "missing_head", "extra_head", "count_width", "scope_width", "modality_width",
    "pointer_width", "non_tensor", "integer_dtype", "wrong_batch",
])
def test_malformed_model_head_inventory_and_shapes_fail_closed(monkeypatch, model, mutation):
    example = source_example()
    outputs = forced_outputs(model, example)
    if mutation == "missing_head":
        outputs.pop("actor_end")
    elif mutation == "extra_head":
        outputs["target_request"] = torch.zeros(1)
    elif mutation == "count_width":
        outputs["count"] = torch.zeros((1, 8))
    elif mutation == "scope_width":
        outputs["scope"] = torch.zeros((1, 3))
    elif mutation == "modality_width":
        outputs["modality"] = torch.zeros((1, 8, 4))
    elif mutation == "pointer_width":
        outputs["action_end"] = torch.zeros((1, 8, outputs["action_end"].shape[-1] + 1))
    elif mutation == "non_tensor":
        outputs["count"] = [0] * 7
    elif mutation == "integer_dtype":
        outputs["count"] = outputs["count"].long()
    else:
        outputs["count"] = torch.zeros((2, 7))
    install_outputs(monkeypatch, model, outputs)
    result = head.predict_grouped_span_decoder(model, example.source_text, example.modal_scope)
    assert result["status"] == "blocked"
    assert result["request"] is result["raw_prediction"] is None
    assert "malformed_model_prediction" in result["blockers"]


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_learned_scores_fail_closed(monkeypatch, model, value):
    example = source_example()
    outputs = forced_outputs(model, example)
    outputs["count"][0, 0] = value
    install_outputs(monkeypatch, model, outputs)
    result = head.predict_grouped_span_decoder(model, example.source_text, example.modal_scope)
    assert result["status"] == "blocked"
    assert result["request"] is result["raw_prediction"] is None
    assert "nonfinite_model_prediction" in result["blockers"]


@pytest.mark.parametrize("bad_source", ["", " ", None, "a" * 65, "x " * 193, "\ud800"])
def test_unrepresentable_source_is_blocked_without_truncation(monkeypatch, model, bad_source):
    def forbidden(*args, **kwargs):
        raise AssertionError("Model executed on unsupported source")
    monkeypatch.setattr(model, "forward", forbidden)
    result = head.predict_grouped_span_decoder(model, bad_source, "disjunction_of_norms")
    assert result["status"] == "blocked" and result["request"] is None
    assert "source_profile_unsupported" in result["blockers"]


def test_predictor_signature_has_no_target_or_source_parser_dependency(monkeypatch, model):
    from ipfs_datasets_py.logic.deontic.utils import deontic_parser
    assert list(inspect.signature(head.predict_grouped_span_decoder).parameters) == ["model", "source_text", "modal_scope"]
    example = source_example()
    install_outputs(monkeypatch, model, forced_outputs(model, example))
    def forbidden(*args, **kwargs):
        raise AssertionError("Reference parser was consulted at inference")
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
    result = head.predict_grouped_span_decoder(model, example.source_text, example.modal_scope)
    assert result["status"] == "predicted" and result["targets_used_at_inference"] is False



@pytest.mark.parametrize("span", [(True, 4), (0, 0), (-1, 2), (1.0, 4), [0, 4], (0, 20000)])
def test_training_target_span_types_and_bounds_cannot_be_coerced(span):
    with pytest.raises(ValueError):
        head.GroupedSpanTarget(span, (5, 8), "O")


def test_token_offsets_preserve_unicode_characters_separately_from_utf8_byte_width():
    source = "The café keeper shall display agency’s notice."
    tokens = head.tokenize_source(source, head.SpanDecoderConfig())
    assert all(source[token.start:token.end] == token.text for token in tokens)
    cafe = next(token for token in tokens if token.text == "café")
    assert cafe.end - cafe.start == 4
    assert len(cafe.text.encode("utf-8")) == 5
