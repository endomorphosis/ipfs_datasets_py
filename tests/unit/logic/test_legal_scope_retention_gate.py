"""Focused custody, objective, online-emission and strict-resume fixtures."""
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
import json
from types import MethodType

import pytest
import torch

from ipfs_datasets_py.logic.formalization.autoencoder import legal_scope_span_decoder as span
from ipfs_datasets_py.logic.formalization.autoencoder import legal_scope_trigger_readout as trigger
from ipfs_datasets_py.logic.formalization.autoencoder import legal_scope_support_action as action
from ipfs_datasets_py.logic.formalization.autoencoder import legal_scope_support_gate as oldgate
from ipfs_datasets_py.logic.formalization.autoencoder import legal_scope_retention_gate as gate

SOURCE = "cedar must move brick when chalk fades."
SHORT = "cedar must move"


def digest(source):
    return sha256(source.encode("utf-8")).hexdigest()


@pytest.fixture(scope="module")
def parent_bytes():
    # Preserve nonempty moments at every historical generation, not just weights.
    donor = span.ScopeSpanDecoder(span.ScopeSpanDecoderConfig(seed=11, byte_dim=4, byte_hidden=16,
        token_dim=8, token_hidden=32, head_hidden=8))
    with torch.no_grad():
        donor.support_head.bias.fill_(-5.)
    optimizer = span.make_scope_span_optimizer(donor)
    span.train_scope_span_step(donor, optimizer, [span.ScopeSpanExample(SOURCE, False)])
    donor.eval()
    raw = json.dumps(span.save_scope_span_checkpoint(donor, optimizer, steps=1), sort_keys=True).encode()
    middle = trigger.FrozenTriggerReadout(raw, expected_donor_sha256=sha256(raw).hexdigest(),
        config=trigger.TriggerReadoutConfig(seed=21, mode="predicted_trigger", hidden=64))
    optimizer = trigger.make_trigger_readout_optimizer(middle)
    trigger.train_trigger_readout_step(middle, optimizer, [trigger.TriggerReadoutExample(SOURCE, True, "O")])
    middle.eval()
    raw = json.dumps(trigger.save_trigger_readout_checkpoint(middle, optimizer, steps=1),
                     ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    parent = action.FrozenSupportAction(raw, expected_parent_sha256=sha256(raw).hexdigest(),
        config=action.SupportActionConfig(seed=22, head_kind="mlp", hidden=32))
    optimizer = action.make_support_action_optimizer(parent)
    action.train_support_action_step(parent, optimizer,
        [action.SupportActionExample(SOURCE, True, [11, 15]), action.SupportActionExample("map and ink", False)])
    action.train_support_action_step(parent, optimizer, [action.SupportActionExample("ink and map", False)])
    parent.eval()
    return json.dumps(action.save_support_action_checkpoint(parent, optimizer, steps=2, action_steps=1),
                      ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def model_from(raw, objective="positive_margin"):
    return gate.FrozenRetentionGate(raw, expected_parent_sha256=sha256(raw).hexdigest(),
                                   config=gate.RetentionGateConfig(seed=31, objective=objective))


def mixed():
    return [gate.RetentionGateExample(SOURCE, True, "rule"),
            gate.RetentionGateExample("oak may cross gate.", True, "statement"),
            gate.RetentionGateExample("cedar muts move brick.", False, "rule")]


def equal_outputs(left, right, support=True):
    assert set(left) == set(right) == {"support", "modality", "presence", "start", "end"}
    for key in ("support", "modality", "presence"):
        if support or key != "support":
            assert torch.equal(left[key], right[key]), key
    for key in ("start", "end"):
        for facet in span.FACETS:
            assert torch.equal(left[key][facet], right[key][facet]), (key, facet)


def reseal(checkpoint):
    checkpoint["checkpoint_sha256"] = sha256(span._canonical({k: v for k, v in checkpoint.items()
                                                            if k != "checkpoint_sha256"})).hexdigest()
    return checkpoint


def source_output(batch=1):
    return {"support": torch.full((batch,), 8.),
            "modality": torch.tensor([[3., 2., 1.]]).repeat(batch, 1),
            "presence": torch.tensor([[[1., 0.], [1., 0.]]]).repeat(batch, 1, 1),
            **{key: {facet: torch.tensor([[5. if i == position else -5. for i in range(3)]]).repeat(batch, 1)
                     for facet, position in {"modality": 1, "actor": 0, "action": 2,
                                              "object": 0, "condition": 0}.items()}
               for key in ("start", "end")}}


def test_closed_objective_fixed_pooling_and_explicit_train_attachment():
    assert gate.RetentionGateConfig().to_dict() == {
        "seed": 24606, "mode": "predicted_trigger", "hidden": 32, "objective": "positive_margin"}
    for objective, weight in (("bce", 0.0), ("positive_margin", 1.0)):
        config = gate.RetentionGateConfig(objective=objective)
        assert config.retention_lambda == weight
        assert gate.RetentionGateConfig.from_dict(config.to_dict()) == config
    for kwargs in ({"mode": "global"}, {"objective": "kl"}, {"hidden": 64}, {"seed": True}):
        with pytest.raises(ValueError):
            gate.RetentionGateConfig(**kwargs)
    with pytest.raises(ValueError):
        gate.RetentionGateConfig.from_dict(gate.RetentionGateConfig().to_dict() | {"retention_lambda": 0.5})
    with pytest.raises(ValueError):
        gate.RetentionGateExample(SOURCE, 1, "rule")
    with pytest.raises(ValueError):
        gate.RetentionGateExample(SOURCE, True, None)
    with pytest.raises(TypeError):
        gate.RetentionGateExample(SOURCE, True)
    with pytest.raises(TypeError):
        gate.RetentionGateExample(SOURCE, True, "rule", action_span=[11, 15])


def test_cold_both_objectives_match_parent_and_original_local_gate(parent_bytes):
    rng = torch.random.get_rng_state().clone()
    parent, parent_optimizer, steps, action_steps = action.restore_support_action_checkpoint(json.loads(parent_bytes))
    control, retained = model_from(parent_bytes, "bce"), model_from(parent_bytes)
    reference = oldgate.FrozenSupportGate(parent_bytes, expected_parent_sha256=sha256(parent_bytes).hexdigest(),
        config=oldgate.SupportGateConfig(seed=31, mode="predicted_trigger"))
    assert (steps, action_steps) == (control.parent_steps, control.parent_action_steps) == (2, 1)
    assert parent_optimizer.state and torch.equal(rng, torch.random.get_rng_state())
    assert all(torch.equal(v, retained.gate.state_dict()[name]) and torch.equal(v, reference.gate.state_dict()[name])
               for name, v in control.gate.state_dict().items())
    batch, _ = span._encoded_sources([SOURCE, "é may go.", "cedar muts move brick."])
    with torch.no_grad():
        expected = parent(*batch)
        for model in (control, retained):
            equal_outputs(expected, model(*batch))
            equal_outputs(reference(*batch), model(*batch))
            assert sum(p.numel() for p in model.parameters() if p.requires_grad) == 3169
            assert sum(p.numel() for p in model.gate.parameters()) == 3169
            cp = gate.save_retention_gate_checkpoint(model, gate.make_retention_gate_optimizer(model), steps=0)
            assert cp["parent"]["json_utf8"].encode() == parent_bytes and cp["optimizer"]["state"] == {}
            assert cp["profile"]["objective"] == model.config.objective
            assert cp["profile"]["retention_lambda"] == model.config.retention_lambda
    original = action.predict_support_action(parent, SOURCE, "rule", expected_source_sha256=digest(SOURCE))
    predicted = gate.predict_retention_gate(retained, SOURCE, "rule", expected_source_sha256=digest(SOURCE))
    for key in ("status", "prediction", "proposal", "blockers", "raw_prediction", "modality_logits",
                "support_probability", "support_threshold"):
        assert predicted.get(key) == original.get(key), key
    assert predicted["schema"] == gate.PREDICTION_SCHEMA and torch.equal(rng, torch.random.get_rng_state())


def test_lambda_zero_exact_old_bce_step_and_full_optimizer_parity(parent_bytes):
    model = model_from(parent_bytes, "bce")
    reference = oldgate.FrozenSupportGate(parent_bytes, expected_parent_sha256=sha256(parent_bytes).hexdigest(),
        config=oldgate.SupportGateConfig(seed=31, mode="predicted_trigger"))
    optimizer, old_optimizer = gate.make_retention_gate_optimizer(model), oldgate.make_support_gate_optimizer(reference)
    examples = mixed()
    old_examples = [oldgate.SupportGateExample(e.source_text, e.supported) for e in examples]
    for step in (1, 2):
        actual = gate.train_retention_gate_step(model, optimizer, examples)
        expected = oldgate.train_support_gate_step(reference, old_optimizer, old_examples)
        for key, value in expected.items():
            assert actual[key] == value, key
        assert actual["retention_lambda"] == actual["weighted_retention_loss"] == 0.0
        assert actual["teacher_source_rows_checked"] == actual["encoded_examples"] == 3
        assert actual["additional_parent_forwards"] == 0 and actual["shared_tensor_forward_calls"] == 1
        new_cp = gate.save_retention_gate_checkpoint(model, optimizer, steps=step)
        old_cp = oldgate.save_support_gate_checkpoint(reference, old_optimizer, steps=step)
        assert new_cp["gate_state"] == old_cp["gate_state"] and new_cp["optimizer"] == old_cp["optimizer"]
        assert new_cp["parent"] == old_cp["parent"]


def test_margin_hinge_clamping_mask_reduction_and_gradient():
    candidate = torch.tensor([-1., .5, 1.5, 99.], requires_grad=True)
    parent = torch.tensor([-1e-8, .75, 8., .4])
    mask = torch.tensor([True, True, True, False])
    penalty = gate._positive_margin_penalty(candidate, parent, mask)
    assert float(penalty) == pytest.approx((1. + .25**2) / 3, rel=1e-7)
    penalty.backward()
    torch.testing.assert_close(candidate.grad, torch.tensor([-2/3, -1/6, 0., 0.]), atol=1e-7, rtol=0)
    assert parent.grad is None
    empty = gate._positive_margin_penalty(candidate, parent, torch.zeros(4, dtype=torch.bool))
    assert float(empty) == 0.0 and empty.shape == torch.Size([]) and not empty.requires_grad


@pytest.mark.parametrize("fault", ["parent_grad", "parent_nan", "candidate_nan", "shape", "mask_type"])
def test_margin_hinge_rejects_untrusted_teacher_shapes_and_values(fault):
    candidate, parent, mask = torch.zeros(2), torch.ones(2), torch.ones(2, dtype=torch.bool)
    if fault == "parent_grad":
        parent.requires_grad_()
    elif fault == "parent_nan":
        parent[0] = float("nan")
    elif fault == "candidate_nan":
        candidate[0] = float("nan")
    elif fault == "shape":
        parent = parent[:1]
    else:
        mask = mask.float()
    with pytest.raises(ValueError):
        gate._positive_margin_penalty(candidate, parent, mask)


def test_actual_parent_emission_mask_uses_supported_and_structural_transport_with_float32_edge():
    examples = [gate.RetentionGateExample(SHORT, True, "rule"),
                gate.RetentionGateExample(SHORT, False, "statement"),
                gate.RetentionGateExample(SHORT, True, "rule")]
    rows = [span.tokenize_source(SHORT) for _ in examples]
    parent_support = torch.tensor([-1e-8, 8., -8.])
    assert float(parent_support.sigmoid()[0]) == .5
    output = source_output(batch=3)
    output["support"].fill_(-8.)  # Candidate refusal must not determine teacher eligibility.
    mask, emitted = gate._parent_emission_mask(output, parent_support, examples, rows, gate.producer_pins())
    assert emitted == [True, True, False] and mask.tolist() == [True, False, False]
    output["start"]["actor"][0] = output["start"]["modality"][0]
    output["end"]["actor"][0] = output["end"]["modality"][0]
    mask, emitted = gate._parent_emission_mask(output, parent_support, examples, rows, gate.producer_pins())
    assert emitted == [False, True, False] and not bool(mask.any())


def test_train_updates_preserve_entire_parent_and_frozen_structural_outputs(parent_bytes, monkeypatch):
    model, examples = model_from(parent_bytes), mixed()
    optimizer = gate.make_retention_gate_optimizer(model, weight_decay=.5)
    batch, _ = span._encoded_sources([e.source_text for e in examples])
    with torch.no_grad():
        before = model(*batch)
    parent_state = deepcopy(model._parent.state_dict())
    parent_artifact, parent_modes, parent_flags = model.parent_checkpoint, dict(model._parent_modes), dict(model._parent_flags)
    def denied(*_args, **_kwargs):
        pytest.fail("old frozen parent typed contract or extra parent forward invoked")
    monkeypatch.setattr(model._parent, "forward", denied)
    monkeypatch.setattr(model._parent, "_assert_parent", denied)
    monkeypatch.setattr(model._parent._parent, "forward", denied)
    monkeypatch.setattr(model._parent._parent, "_assert_frozen", denied)
    monkeypatch.setattr(action, "save_support_action_checkpoint", denied)
    result = gate.train_retention_gate_step(model, optimizer, examples)
    with torch.no_grad():
        after = model(*batch)
    equal_outputs(before, after, support=False)
    assert not torch.equal(before["support"], after["support"])
    assert all(torch.equal(v, parent_state[name]) for name, v in model._parent.state_dict().items())
    assert model.parent_checkpoint == parent_artifact and model._parent_modes == parent_modes and model._parent_flags == parent_flags
    assert all(not p.requires_grad and p.grad is None for p in model._parent.parameters())
    assert set(optimizer.state) == set(model.gate.parameters())
    assert result["objective"] == "positive_margin" and result["retention_lambda"] == 1.0
    assert result["retention_eligible_examples"] == sum(result["anchor_mask"])
    assert result["teacher_source_rows_checked"] == 3 and result["additional_parent_forwards"] == 0
    gate.save_retention_gate_checkpoint(model, optimizer, steps=1)


def test_nonempty_online_retention_train_changes_gradients_and_exactly_resumes(parent_bytes, monkeypatch):
    """Inject only checked numeric features/logits; use both real TRAIN helpers.

    The common fixture residual starts below the margin. This is a loss/Adam
    fixture, not a cold-zero artifact or a claim about a learned parent case.
    """
    examples = [gate.RetentionGateExample(SHORT, True, "rule"),
                gate.RetentionGateExample("cedar muts move", False, "statement")]
    control, retained = model_from(parent_bytes, "bce"), model_from(parent_bytes)
    events = []

    def inject_numeric_boundary(model, name):
        def checked_forward(owner, token_bytes, token_mask):
            owner._assert_parent()
            assert token_bytes.device.type == token_mask.device.type == "cpu"
            assert token_bytes.dtype == torch.long and token_mask.dtype == torch.bool
            assert token_bytes.shape[:2] == token_mask.shape == (2, 3) and bool(token_mask.all())
            features = torch.zeros(2, 97, dtype=torch.float32)
            parent_support = torch.ones(2, dtype=torch.float32)
            output = source_output(batch=2)
            output["support"] = parent_support + owner.gate(features).squeeze(-1)
            assert not parent_support.requires_grad and bool(torch.isfinite(output["support"]).all())
            events.append(name)
            return output, parent_support
        monkeypatch.setattr(model, "_forward_with_parent_support", MethodType(checked_forward, model))

    for name, model in (("control", control), ("retained", retained)):
        with torch.no_grad():
            model.gate[2].bias.fill_(-.5)
        inject_numeric_boundary(model, name)
    assert all(torch.equal(value, retained.gate.state_dict()[name])
               for name, value in control.gate.state_dict().items())
    parent_state = deepcopy(retained._parent.state_dict())
    parent_artifact, parent_modes, parent_flags = retained.parent_checkpoint, dict(retained._parent_modes), dict(retained._parent_flags)
    control_optimizer = gate.make_retention_gate_optimizer(control)
    retained_optimizer = gate.make_retention_gate_optimizer(retained)
    control_report = gate.train_retention_gate_step(control, control_optimizer, examples)
    retained_report = gate.train_retention_gate_step(retained, retained_optimizer, examples)
    assert events == ["control", "retained"]
    for report in (control_report, retained_report):
        assert report["parent_emitted_proposal_mask"] == [True, True]
        assert report["anchor_mask"] == [True, False]
        assert report["retention_eligible_examples"] == 1 and report["parent_emitted_proposal_count"] == 2
        assert report["teacher_source_rows_checked"] == report["encoded_examples"] == 2
        assert report["shared_tensor_forward_calls"] == report["frozen_parent_tensor_paths"] == 1
        assert report["additional_parent_forwards"] == 0
        assert report["supported_examples"] == report["unsupported_examples"] == 1
        assert report["optimizer_step_executed"] and report["support_optimizer_step_executed"]
        assert report["retention_loss"] == .25
    assert control_report["support_loss"] == retained_report["support_loss"]
    assert control_report["weighted_retention_loss"] == 0.0 and retained_report["weighted_retention_loss"] == .25
    assert retained_report["loss"] == pytest.approx(control_report["loss"] + .25, rel=1e-7)
    assert float(retained.gate[2].bias.grad - control.gate[2].bias.grad) == pytest.approx(-1.0, abs=1e-6)
    assert not torch.equal(retained_optimizer.state[retained.gate[2].bias]["exp_avg"],
                           control_optimizer.state[control.gate[2].bias]["exp_avg"])
    assert not torch.equal(retained.gate[2].bias, control.gate[2].bias)
    for model in (control, retained):
        assert all(torch.equal(value, parent_state[name]) for name, value in model._parent.state_dict().items())
        assert model.parent_checkpoint == parent_artifact
        assert model._parent_modes == parent_modes and model._parent_flags == parent_flags
        assert all(not parameter.requires_grad and parameter.grad is None for parameter in model._parent.parameters())

    retained.eval()
    rng = torch.random.get_rng_state().clone()
    checkpoint = json.loads(json.dumps(gate.save_retention_gate_checkpoint(retained, retained_optimizer, steps=1),
                                       allow_nan=False))
    resumed, resumed_optimizer, steps = gate.restore_retention_gate_checkpoint(checkpoint)
    assert steps == 1 and not resumed.training and torch.equal(rng, torch.random.get_rng_state())
    assert checkpoint["parent"]["json_utf8"].encode() == parent_bytes
    assert set(checkpoint["optimizer"]["state"]) == {"0", "1", "2", "3"}
    assert gate.save_retention_gate_checkpoint(resumed, resumed_optimizer, steps=steps) == checkpoint
    inject_numeric_boundary(resumed, "resumed")
    uninterrupted = gate.train_retention_gate_step(retained, retained_optimizer, examples)
    restarted = gate.train_retention_gate_step(resumed, resumed_optimizer, examples)
    assert events == ["control", "retained", "retained", "resumed"]
    assert uninterrupted == restarted and uninterrupted["retention_loss"] > 0.0
    assert uninterrupted["anchor_mask"] == [True, False] and uninterrupted["retention_eligible_examples"] == 1
    assert gate.save_retention_gate_checkpoint(retained, retained_optimizer, steps=2) == gate.save_retention_gate_checkpoint(resumed, resumed_optimizer, steps=2)
    assert all(torch.equal(value, parent_state[name]) for name, value in resumed._parent.state_dict().items())
    assert resumed.parent_checkpoint == parent_artifact and resumed._parent_modes == parent_modes and resumed._parent_flags == parent_flags
    assert all(not parameter.requires_grad and parameter.grad is None for parameter in resumed._parent.parameters())


@pytest.mark.parametrize("objective", ["bce", "positive_margin"])
def test_exact_full_adam_resume_next_step_modes_and_rng(parent_bytes, objective):
    model = model_from(parent_bytes, objective)
    optimizer = gate.make_retention_gate_optimizer(model)
    gate.train_retention_gate_step(model, optimizer, mixed())
    gate.train_retention_gate_step(model, optimizer, [gate.RetentionGateExample("map and ink", False, "rule")])
    model.eval()
    rng = torch.random.get_rng_state().clone()
    cp = json.loads(json.dumps(gate.save_retention_gate_checkpoint(model, optimizer, steps=2), allow_nan=False))
    resumed, new_optimizer, steps = gate.restore_retention_gate_checkpoint(cp)
    assert steps == 2 and not resumed.training and torch.equal(rng, torch.random.get_rng_state())
    assert cp["parent"]["json_utf8"].encode() == parent_bytes
    assert gate.save_retention_gate_checkpoint(resumed, new_optimizer, steps=steps) == cp
    batch, _ = span._encoded_sources([SOURCE])
    equal_outputs(model(*batch), resumed(*batch))
    assert gate.train_retention_gate_step(model, optimizer, mixed()) == gate.train_retention_gate_step(resumed, new_optimizer, mixed())
    assert gate.save_retention_gate_checkpoint(model, optimizer, steps=3) == gate.save_retention_gate_checkpoint(resumed, new_optimizer, steps=3)


def test_source_only_prediction_has_no_teacher_or_train_label_access(parent_bytes, monkeypatch):
    examples, model = mixed(), model_from(parent_bytes)
    def denied(*_args, **_kwargs):
        pytest.fail("target helper or TRAIN teacher accessed at inference")
    monkeypatch.setattr(span, "_labels", denied)
    monkeypatch.setattr(action, "_action_labels", denied)
    monkeypatch.setattr(action, "SupportActionExample", denied)
    monkeypatch.setattr(trigger, "TriggerReadoutExample", denied)
    gate.train_retention_gate_step(model, gate.make_retention_gate_optimizer(model), examples)
    monkeypatch.setattr(gate, "RetentionGateExample", denied)
    monkeypatch.setattr(gate, "_parent_emission_mask", denied)
    monkeypatch.setattr(gate, "_positive_margin_penalty", denied)
    model.forward = lambda *_: source_output()
    result = gate.predict_retention_gate(model, SHORT, "statement", expected_source_sha256=digest(SHORT))
    assert result["status"] == "predicted" and result["formal_output"] is None
    assert result["prediction"]["condition_attachment"] is None and not any(result["masks"].values())
    assert result["schema"] == gate.PREDICTION_SCHEMA and result["retention_lambda"] == 1.0
    assert not any(result[key] for key in ("target_access", "targets_used_at_inference", "accepted", "qualified",
                                          "proof_ready", "proof_authority", "formalized", "source_semantics_verified"))


def test_source_digest_and_caller_attachment_precede_model(parent_bytes):
    model = model_from(parent_bytes)
    model.forward = lambda *_: pytest.fail("model invoked before source/caller validation")
    with pytest.raises(ValueError, match="source digest mismatch"):
        gate.predict_retention_gate(model, SOURCE, "rule", expected_source_sha256="0" * 64)
    result = gate.predict_retention_gate(model, SOURCE, None, expected_source_sha256=digest(SOURCE))
    assert not result["model_executed"] and result["blockers"] == ["explicit_caller_condition_attachment_required"]


@pytest.mark.parametrize("fault", ["extra", "seal", "objective", "lambda", "pure_bce_profile", "parent_sha", "parent_bytes",
                                    "old_adam", "gate_shape", "adam_step", "missing_state", "variance", "steps_bool", "nonfinite"])
def test_strict_checkpoint_rejects_recipe_relabel_full_adam_and_seal_mutation(parent_bytes, fault):
    model = model_from(parent_bytes)
    optimizer = gate.make_retention_gate_optimizer(model)
    gate.train_retention_gate_step(model, optimizer, mixed())
    cp = gate.save_retention_gate_checkpoint(model, optimizer, steps=1)
    if fault == "extra":
        cp["extra"] = None
    elif fault == "seal":
        cp["checkpoint_sha256"] = "0" * 64
    elif fault == "objective":
        cp["config"]["objective"] = "bce"
    elif fault == "lambda":
        cp["profile"]["retention_lambda"] = 0.0
    elif fault == "pure_bce_profile":
        cp["profile"]["loss"] = "BCE_support_all"
    elif fault == "parent_sha":
        cp["parent"]["sha256"] = "0" * 64
    elif fault == "parent_bytes":
        cp["parent"]["bytes"] += 1
    elif fault == "old_adam":
        parent = json.loads(cp["parent"]["json_utf8"])
        parent["optimizer"]["state"]["0"]["step"]["values"][0] = 0.
        parent["checkpoint_sha256"] = sha256(span._canonical({k: v for k, v in parent.items() if k != "checkpoint_sha256"})).hexdigest()
        raw = json.dumps(parent, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        cp["parent"] = {"json_utf8": raw.decode(), "bytes": len(raw), "sha256": sha256(raw).hexdigest()}
    elif fault == "gate_shape":
        cp["gate_state"]["0.weight"]["shape"][1] += 1
    elif fault == "adam_step":
        cp["optimizer"]["state"]["0"]["step"]["values"][0] = 0.
    elif fault == "missing_state":
        del cp["optimizer"]["state"]["2"]
    elif fault == "variance":
        cp["optimizer"]["state"]["0"]["exp_avg_sq"]["values"][0] = -1.
    elif fault == "steps_bool":
        cp["steps"] = True
    else:
        cp["gate_state"]["0.weight"]["values"][0] = float("nan")
    if fault not in ("seal", "nonfinite"):
        reseal(cp)
    with pytest.raises(ValueError):
        gate.restore_retention_gate_checkpoint(cp)


@pytest.mark.parametrize("fault", ["action_weight", "class_weight", "gradflag", "mode", "config", "nestedartifact", "rawprovenance", "objective"])
def test_complete_parent_and_objective_snapshot_refuses_mutation(parent_bytes, fault):
    model = model_from(parent_bytes)
    if fault == "action_weight":
        with torch.no_grad():
            model._parent.heads["action_start"][2].bias.add_(1.)
    elif fault == "class_weight":
        with torch.no_grad():
            model._parent._parent.adapter[2].bias.add_(1.)
    elif fault == "gradflag":
        next(model._parent.heads["support"].parameters()).requires_grad_(True)
    elif fault == "mode":
        model._parent.heads.train()
    elif fault == "config":
        model._parent.config = replace(model._parent.config, seed=99)
    elif fault == "nestedartifact":
        model._parent._parent._donor_json_utf8 += " "
    elif fault == "rawprovenance":
        model._parent_json_utf8 += " "
    else:
        model.config = replace(model.config, objective="bce")
    with pytest.raises(ValueError):
        model(*span._encoded_sources([SOURCE])[0])


def test_cold_zero_cannot_relabel_trained_or_changed_initial_gate(parent_bytes):
    model = model_from(parent_bytes)
    optimizer = gate.make_retention_gate_optimizer(model)
    cp = gate.save_retention_gate_checkpoint(model, optimizer, steps=0)
    cp["gate_state"]["0.bias"]["values"][0] += 1.
    reseal(cp)
    with pytest.raises(ValueError, match="exact seeded cold gate"):
        gate.restore_retention_gate_checkpoint(cp)
    gate.train_retention_gate_step(model, optimizer, mixed())
    with pytest.raises(ValueError, match="exact seeded cold gate"):
        gate.save_retention_gate_checkpoint(model, gate.make_retention_gate_optimizer(model), steps=0)
    with pytest.raises(ValueError, match="inventory"):
        gate.save_retention_gate_checkpoint(model, optimizer, steps=0)
