"""Learned grouped pointers cross the renderer boundary without teacher access.

Controlled logits below test interface failures only; they are not model-quality
evidence. The real numerical forward and one-step round trip run independently.
"""
from copy import deepcopy
import json

import pytest
import torch

from ipfs_datasets_py.logic.autoformal import legal_coordination as bridge
from ipfs_datasets_py.logic.autoformal import legal_coordination_evaluation as evaluation
from ipfs_datasets_py.logic.deontic import coordination, coordination_decoder as semantic
from ipfs_datasets_py.logic.deontic.exports import build_document_export_tables_from_ir
from ipfs_datasets_py.logic.deontic.ir import LegalNormIR
from ipfs_datasets_py.logic.deontic.utils import deontic_parser
from ipfs_datasets_py.logic.formalization.autoencoder import legal_grouped_span_decoder as learned


SOURCE = "The Secretary shall publish the notice or shall retain the record."
SCOPES = ("modal_over_actions", "disjunction_of_norms")


def tiny_model():
    return learned.GroupedSpanDecoder(learned.SpanDecoderConfig(
        seed=1729, token_dim=16, token_hidden=16, slot_hidden=24, max_tokens=64))


def no_teacher_dependencies(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("prediction consulted a source parser, group compiler, or target helper")
    for module, names in (
        (coordination, ("build_coordination_groups", "reconstruct_source", "validate_coordination_group")),
        (deontic_parser, ("extract_normative_elements", "analyze_normative_sentence", "_unresolved_duty_disjunction_groups")),
        (bridge, ("compile_coordination_group", "reconstruct_compiled_group", "coordination_decode_request_from_compiled")),
        (learned, ("_labels", "GroupedSpanTarget", "GroupedSpanExample")),
    ):
        for name in names:
            monkeypatch.setattr(module, name, forbidden)


def span(text, label):
    start = text.index(label)
    return start, start + len(label)


def authored_example(scope="modal_over_actions"):
    actor = span(SOURCE, "The Secretary")
    return learned.GroupedSpanExample(SOURCE, scope, tuple(
        learned.GroupedSpanTarget(actor, span(SOURCE, action), "O")
        for action in ("publish the notice", "retain the record")))


def controlled_logits(model, source=SOURCE, *, scope="modal_over_actions", bad_action=False):
    """Explicit interface fixture; never used as a trained-model witness."""
    tokens = learned.tokenize_source(source, model.config)
    starts = {token.start: index for index, token in enumerate(tokens)}
    ends = {token.end: index for index, token in enumerate(tokens)}
    outputs = {"count": torch.full((1, 7), -10.0), "scope": torch.full((1, 2), -10.0),
               "modality": torch.full((1, 8, 3), -10.0)}
    outputs["count"][0, 0] = 10
    outputs["scope"][0, SCOPES.index(scope)] = 10
    outputs["modality"][:, :, 0] = 10
    for key in learned.POINTERS:
        outputs[key] = torch.full((1, 8, len(tokens)), -10.0)
    actor = span(source, "The Secretary")
    actions = ("shall publish the notice" if bad_action else "publish the notice", "retain the record")
    for index, action in enumerate(actions):
        for field, value in (("actor", actor), ("action", span(source, action))):
            outputs[field + "_start"][0, index, starts[value[0]]] = 10
            outputs[field + "_end"][0, index, ends[value[1]]] = 10
    return outputs


@pytest.mark.parametrize("scope", SCOPES)
def test_real_forward_receives_only_complete_source_bytes_and_explicit_caller_scope(monkeypatch, scope):
    model = tiny_model()
    tokens = learned.tokenize_source(SOURCE, model.config)
    observed = []
    def trace(module, args):
        assert module is model and len(args) == 3
        token_bytes, mask, caller = args
        assert token_bytes.dtype == caller.dtype == torch.long
        assert mask.dtype == torch.bool and mask.all()
        copied = [bytes(value - 1 for value in token.tolist() if value).decode("utf-8")
                  for token in token_bytes[0]]
        assert copied == [token.text for token in tokens]
        assert caller.tolist() == [SCOPES.index(scope)]
        observed.append(copied)
    hook = model.register_forward_pre_hook(trace)
    no_teacher_dependencies(monkeypatch)
    result = learned.predict_grouped_span_decoder(model, SOURCE, scope)
    hook.remove()
    assert len(observed) == 1
    assert result["raw_prediction"] is not None
    assert result["status"] in {"predicted", "blocked"}
    assert result["targets_used_at_inference"] is result["source_semantics_verified"] is result["proof_ready"] is False
    assert model.training is True


@pytest.mark.parametrize("scope", [None, "", "unknown", {"modal_scope": "modal_over_actions"}])
def test_missing_or_unknown_scope_abstains_before_source_encoding_or_forward(monkeypatch, scope):
    model = tiny_model()
    def forbidden(*args, **kwargs):
        raise AssertionError("an undeclared scope reached source encoding or inference")
    monkeypatch.setattr(learned, "_encoded_sources", forbidden)
    monkeypatch.setattr(model, "forward", forbidden)
    no_teacher_dependencies(monkeypatch)
    result = learned.predict_grouped_span_decoder(model, SOURCE, scope)
    assert result["status"] == "abstained"
    assert result["request"] is result["raw_prediction"] is None
    assert result["blockers"] == ["explicit_caller_scope_required"]


def test_controlled_scope_disagreement_is_not_overwritten_or_repaired(monkeypatch):
    model = tiny_model()
    outputs = controlled_logits(model, scope="disjunction_of_norms")
    monkeypatch.setattr(model, "forward", lambda *args: outputs)
    no_teacher_dependencies(monkeypatch)
    result = learned.predict_grouped_span_decoder(model, SOURCE, "modal_over_actions")
    assert result["status"] == "blocked" and result["request"] is None
    assert result["raw_prediction"]["modal_scope"] == "disjunction_of_norms"
    assert result["blockers"] == ["predicted_scope_disagrees_with_caller"]


def test_controlled_modal_embedded_in_action_is_blocked_without_reference_fallback(monkeypatch):
    model = tiny_model()
    outputs = controlled_logits(model, bad_action=True)
    reference = {"schema": semantic.COORDINATION_DECODE_REQUEST_SCHEMA, "modal_scope": "modal_over_actions",
                 "connective": "inclusive_or", "binding_profile": "universal_actor_predicate",
                 "members": [{"actor": "secretary", "modality": "O", "action": action}
                             for action in ("publish the notice", "retain the record")]}
    monkeypatch.setattr(model, "forward", lambda *args: outputs)
    no_teacher_dependencies(monkeypatch)
    result = learned.predict_grouped_span_decoder(model, SOURCE, "modal_over_actions")
    assert result["status"] == "blocked" and result["request"] is None
    assert result["blockers"] == ["predicted_span_or_request_invalid"]
    measured = evaluation.evaluate_coordination_outputs(
        [semantic.CoordinationDecodeRequest.from_dict(reference)], [result["request"]])
    assert measured["invalid_output_count"] == measured["failed_count"] == 1
    assert measured["passed_count"] == 0
    assert "candidate_formula" not in measured["cases"][0]


@pytest.mark.parametrize("scope", SCOPES)
def test_controlled_valid_span_request_renders_but_cannot_admit_original_branches(monkeypatch, scope):
    norms = [LegalNormIR.from_parser_element(row) for row in deontic_parser.extract_normative_elements(SOURCE)]
    model = tiny_model()
    outputs = controlled_logits(model, scope=scope)
    with monkeypatch.context() as isolated:
        isolated.setattr(model, "forward", lambda *args: outputs)
        no_teacher_dependencies(isolated)
        prediction = learned.predict_grouped_span_decoder(model, SOURCE, scope)
        assert prediction["status"] == "predicted"
        request = semantic.CoordinationDecodeRequest.from_dict(prediction["request"])
        record = semantic.decode_coordination_request(request)
    assert record["family_validation"]["passed"] is True
    assert record["structure_compiled"] is True
    assert record["proof_ready"] is record["source_semantics_verified"] is record["admitted"] is False
    assert record["requires_validation"] is True
    assert prediction["proof_ready"] is prediction["source_semantics_verified"] is False
    tables = build_document_export_tables_from_ir(norms)
    for table in ("canonical", "formal_logic", "proof_obligations"):
        assert tables[table]
        for row in tables[table]:
            assert row["proof_ready"] is False
            assert "formula_coordination_scope_unresolved" in row["blockers"]


def test_actual_optimizer_checkpoint_roundtrip_preserves_all_tensors_and_source_only_prediction(tmp_path, monkeypatch):
    old_threads = torch.get_num_threads()
    torch.set_num_threads(1)
    try:
        model = tiny_model()
        optimizer = learned.make_grouped_span_optimizer(model)
        before = {key: value.clone() for key, value in model.state_dict().items()}
        losses = learned.train_grouped_span_step(model, optimizer, [authored_example(scope) for scope in SCOPES])
        assert losses["loss"] > 0 and losses["gradient_norm"] > 0
        assert any(not torch.equal(value, before[key]) for key, value in model.state_dict().items())
        checkpoint = learned.save_grouped_span_checkpoint(model, optimizer, steps=1)
        path = tmp_path / "checkpoint.json"
        path.write_text(json.dumps(checkpoint, allow_nan=False))
        saved = json.loads(path.read_text())
        restored, restored_optimizer, steps = learned.restore_grouped_span_checkpoint(saved)
        assert steps == 1
        assert set(model.state_dict()) == set(restored.state_dict())
        for key, tensor in model.state_dict().items():
            assert torch.equal(tensor, restored.state_dict()[key]), key
            assert tensor.data_ptr() != restored.state_dict()[key].data_ptr(), key
        for index, state in optimizer.state_dict()["state"].items():
            for key, tensor in state.items():
                assert torch.equal(tensor, restored_optimizer.state_dict()["state"][index][key])
        assert learned.save_grouped_span_checkpoint(restored, restored_optimizer, steps=steps) == saved
        assert saved["profile"]["input_fields"] == ["source_text", "modal_scope"]
        assert saved["profile"]["numeric_vector_conditioning"] is False
        assert SOURCE not in path.read_text()
        no_teacher_dependencies(monkeypatch)
        for scope in SCOPES:
            assert learned.predict_grouped_span_decoder(model, SOURCE, scope) == learned.predict_grouped_span_decoder(restored, SOURCE, scope)
        assert saved == checkpoint
    finally:
        torch.set_num_threads(old_threads)


def test_changed_checkpoint_tensor_cannot_restore_under_original_seal():
    model = tiny_model()
    checkpoint = learned.save_grouped_span_checkpoint(model, learned.make_grouped_span_optimizer(model), steps=0)
    changed = deepcopy(checkpoint)
    changed["model_state"]["byte_embedding.weight"]["values"][0] = 1.0
    with pytest.raises(ValueError, match="seal mismatch"):
        learned.restore_grouped_span_checkpoint(changed)
