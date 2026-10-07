"""CPU fixtures for frozen donor custody and the matched residual control."""
from copy import deepcopy
from hashlib import sha256
import json

import pytest
import torch

from ipfs_datasets_py.logic.formalization.autoencoder import legal_scope_span_decoder as span
from ipfs_datasets_py.logic.formalization.autoencoder import legal_scope_trigger_readout as readout

SOURCE = "cedar must move brick when chalk fades."


def digest(source):
    return sha256(source.encode("utf-8")).hexdigest()


@pytest.fixture(scope="module")
def donor_bytes():
    donor = span.ScopeSpanDecoder(span.ScopeSpanDecoderConfig(
        seed=11, byte_dim=4, byte_hidden=4, token_dim=8, token_hidden=8, head_hidden=8))
    with torch.no_grad():
        donor.support_head.bias.fill_(-8.)
    optimizer = span.make_scope_span_optimizer(donor)
    # A real tiny donor Adam fixture, including genuine nonzero shared moments.
    span.train_scope_span_step(donor, optimizer, [span.ScopeSpanExample(SOURCE, False)])
    donor.eval()
    return json.dumps(span.save_scope_span_checkpoint(donor, optimizer, steps=1),
                      sort_keys=True, separators=(",", ":")).encode("utf-8")


def model_from(raw, mode="global"):
    return readout.FrozenTriggerReadout(raw, expected_donor_sha256=sha256(raw).hexdigest(),
                                      config=readout.TriggerReadoutConfig(seed=31, mode=mode, hidden=8))


def training_rows():
    return [readout.TriggerReadoutExample(SOURCE, True, "P"),
            readout.TriggerReadoutExample("acorn may cross gate.", True, "O"),
            readout.TriggerReadoutExample("map and ink", False)]


def equal_outputs(left, right, include_class=True):
    for key in ("support", "modality", "presence"):
        if key != "modality" or include_class:
            assert torch.equal(left[key], right[key]), key
    for key in ("start", "end"):
        for facet in span.FACETS:
            assert torch.equal(left[key][facet], right[key][facet]), (key, facet)


def reseal(checkpoint):
    checkpoint["checkpoint_sha256"] = sha256(span._canonical(
        {k: v for k, v in checkpoint.items() if k != "checkpoint_sha256"})).hexdigest()
    return checkpoint


@pytest.mark.parametrize("mode", ["global", "predicted_trigger"])
def test_initialization_preserves_rng_modes_and_donor_forward(donor_bytes, mode):
    rng = torch.random.get_rng_state().clone()
    forward = span.ScopeSpanDecoder.forward
    model = model_from(donor_bytes, mode)
    assert torch.equal(torch.random.get_rng_state(), rng)
    assert span.ScopeSpanDecoder.forward is forward
    assert model.donor.training is False
    assert model.donor_steps == 1
    assert all(not p.requires_grad and p.grad is None for p in model.donor.parameters())
    batch, _ = span._encoded_sources([SOURCE, "é may go."])
    with torch.no_grad():
        expected = model.donor(*batch)
        actual = model(*batch)
    equal_outputs(expected, actual)
    model.eval()
    assert not model.training and not model.adapter.training and not model.donor.training
    model.train()
    assert model.training and model.adapter.training and not model.donor.training
    assert torch.equal(torch.random.get_rng_state(), rng)


def test_matched_arms_have_identical_initial_parameters(donor_bytes):
    global_model = model_from(donor_bytes)
    trigger_model = model_from(donor_bytes, "predicted_trigger")
    assert sum(p.numel() for p in global_model.adapter.parameters()) == sum(
        p.numel() for p in trigger_model.adapter.parameters())
    assert all(torch.equal(a, b) for a, b in zip(global_model.adapter.parameters(), trigger_model.adapter.parameters()))
    assert bool((global_model.adapter[2].weight == 0).all())
    assert bool((global_model.adapter[2].bias == 0).all())
    assert bool((global_model.adapter[0].weight != 0).any())


@pytest.mark.parametrize("mode", ["global", "predicted_trigger"])
def test_prediction_matches_v1_donor_and_reports_finite_class_logits(donor_bytes, mode):
    model = model_from(donor_bytes, mode)
    before_mode = model.training
    before_rng = torch.random.get_rng_state().clone()
    original = span.predict_scope_span_decoder(model.donor, SOURCE, "rule", expected_source_sha256=digest(SOURCE))
    actual = readout.predict_trigger_readout(model, SOURCE, "rule", expected_source_sha256=digest(SOURCE))
    for key, value in original.items():
        if key != "schema":
            assert actual[key] == value, key
    assert actual["status"] == "abstained"
    assert len(actual["modality_logits"]) == 3 and all(torch.isfinite(torch.tensor(actual["modality_logits"])))
    assert model.training is before_mode and model.donor.training is False
    assert torch.equal(before_rng, torch.random.get_rng_state())
    assert actual["target_access"] is False and actual["formal_output"] is None


@pytest.mark.parametrize("mode", ["global", "predicted_trigger"])
def test_adapter_updates_only_class_and_exactly_resumes(donor_bytes, mode):
    model = model_from(donor_bytes, mode)
    optimizer = readout.make_trigger_readout_optimizer(model)
    batch, _ = span._encoded_sources([SOURCE, "oak can move."])
    baseline = model(*batch)
    donor_snapshot = deepcopy(model.donor.state_dict())
    result = readout.train_trigger_readout_step(model, optimizer, training_rows())
    assert result["optimizer_step_executed"] and result["supported_examples"] == 2
    after = model(*batch)
    equal_outputs(baseline, after, include_class=False)
    assert not torch.equal(baseline["modality"], after["modality"])
    assert all(torch.equal(v, donor_snapshot[k]) for k, v in model.donor.state_dict().items())
    assert all(p.grad is None for p in model.donor.parameters())
    assert {id(p) for p in optimizer.state} == {id(p) for p in model.adapter.parameters()}
    assert all(float(state["step"]) == 1 for state in optimizer.state.values())
    model.eval()
    checkpoint = readout.save_trigger_readout_checkpoint(model, optimizer, steps=1)
    # Plain finite JSON roundtrip and exact embedded donor byte authentication.
    checkpoint = json.loads(json.dumps(checkpoint, allow_nan=False))
    assert checkpoint["donor"]["json_utf8"].encode() == donor_bytes
    rng = torch.random.get_rng_state().clone()
    restored, resumed, steps = readout.restore_trigger_readout_checkpoint(checkpoint)
    assert steps == 1 and not restored.training and not restored.donor.training
    assert torch.equal(rng, torch.random.get_rng_state())
    assert readout.save_trigger_readout_checkpoint(restored, resumed, steps=steps) == checkpoint
    equal_outputs(model(*batch), restored(*batch))
    left = readout.train_trigger_readout_step(model, optimizer, training_rows())
    right = readout.train_trigger_readout_step(restored, resumed, training_rows())
    assert left == right
    assert readout.save_trigger_readout_checkpoint(model, optimizer, steps=2) == readout.save_trigger_readout_checkpoint(
        restored, resumed, steps=2)


def test_all_negative_batches_leave_optimizer_and_weights_idle(donor_bytes):
    model = model_from(donor_bytes)
    optimizer = readout.make_trigger_readout_optimizer(model, weight_decay=.5)
    negatives = [readout.TriggerReadoutExample("map and ink", False)]
    zero = readout.save_trigger_readout_checkpoint(model, optimizer, steps=0)
    assert not readout.train_trigger_readout_step(model, optimizer, negatives)["optimizer_step_executed"]
    assert zero == readout.save_trigger_readout_checkpoint(model, optimizer, steps=0)
    readout.train_trigger_readout_step(model, optimizer, training_rows())
    prior = readout.save_trigger_readout_checkpoint(model, optimizer, steps=1)
    model.forward = lambda *_: pytest.fail("all-negative batch invoked model")
    assert not readout.train_trigger_readout_step(model, optimizer, negatives)["optimizer_step_executed"]
    assert prior == readout.save_trigger_readout_checkpoint(model, optimizer, steps=1)
    assert all(p.grad is None for p in model.adapter.parameters())


def test_soft_interval_feature_uses_predicted_coverage_and_real_tokens():
    encoded = torch.tensor([[[2., 1.], [4., 3.], [8., 7.], [900., 900.]]])
    mask = torch.tensor([[True, True, True, False]])
    starts = torch.log(torch.tensor([[.2, .5, .3, .9]]))
    ends = torch.log(torch.tensor([[.4, .4, .2, .9]]))
    weights = torch.tensor([[.2 * 1., .7 * .6, 1. * .2]])
    expected = (encoded[:, :3] * (weights / weights.sum())[:, :, None]).sum(1)
    actual = readout._predicted_trigger_feature(encoded, mask, starts, ends)
    assert torch.allclose(actual, expected, atol=1e-6, rtol=0)
    changed = encoded.clone(); changed[:, 3] = -500.
    assert torch.equal(actual, readout._predicted_trigger_feature(changed, mask, starts, ends))


def test_invalid_coverage_blocks_and_restores_mode_without_repair(donor_bytes):
    encoded = torch.zeros(1, 3, 2)
    mask = torch.ones(1, 3, dtype=torch.bool)
    # Finite extreme logits can underflow to disjoint deterministic endpoints.
    with pytest.raises(ValueError, match="positive finite coverage"):
        readout._predicted_trigger_feature(encoded, mask, torch.tensor([[-1000., -1000., 1000.]]),
                                           torch.tensor([[1000., -1000., -1000.]]))
    model = model_from(donor_bytes, "predicted_trigger")
    def invalid(*_):
        raise readout._InvalidTriggerFeature("positive finite coverage required")
    model.forward = invalid
    result = readout.predict_trigger_readout(model, SOURCE, "rule", expected_source_sha256=digest(SOURCE))
    assert result["status"] == "blocked" and result["model_executed"]
    assert result["blockers"] == ["invalid_predicted_trigger_coverage"]
    assert result["modality_logits"] is None
    assert model.training and not model.donor.training


@pytest.mark.parametrize("mode", ["global", "predicted_trigger"])
def test_token_and_byte_padding_invariance(donor_bytes, mode):
    model = model_from(donor_bytes, mode)
    (values, mask), _ = span._encoded_sources([SOURCE])
    padded = torch.zeros((1, values.shape[1] + 2, values.shape[2] + 3), dtype=torch.long)
    padded[:, :values.shape[1], :values.shape[2]] = values
    padded_mask = torch.zeros((1, mask.shape[1] + 2), dtype=torch.bool)
    padded_mask[:, :mask.shape[1]] = mask
    original, larger = model(values, mask), model(padded, padded_mask)
    for key in ("support", "modality", "presence"):
        assert torch.allclose(original[key], larger[key], atol=1e-7, rtol=0)
    for key in ("start", "end"):
        for facet in span.FACETS:
            assert torch.allclose(original[key][facet], larger[key][facet][:, :mask.shape[1]], atol=1e-7, rtol=0)


def test_targets_and_parser_are_not_used_at_inference_or_adapter_training(donor_bytes, monkeypatch):
    model = model_from(donor_bytes, "predicted_trigger")
    monkeypatch.setattr(span, "_labels", lambda *_: pytest.fail("target span adapter was called"))
    monkeypatch.setattr(span.proposal, "propose_scope_from_spans", lambda *_args, **_kwargs: pytest.fail("TRAIN used proposal/parser"))
    readout.train_trigger_readout_step(model, readout.make_trigger_readout_optimizer(model), training_rows())
    # Donor support refuses: inference does not reach proposal validation.
    assert readout.predict_trigger_readout(model, SOURCE, "rule", expected_source_sha256=digest(SOURCE))["status"] == "abstained"
    with pytest.raises(ValueError):
        readout.TriggerReadoutExample(SOURCE, False, "O")
    with pytest.raises(ValueError):
        readout.TriggerReadoutExample(SOURCE, True)
    with pytest.raises(TypeError):
        readout.TriggerReadoutExample(SOURCE, True, "O", target={})


def test_wrong_digest_and_missing_caller_fail_before_model(donor_bytes):
    model = model_from(donor_bytes)
    model.forward = lambda *_: pytest.fail("model ran before source/caller validation")
    with pytest.raises(ValueError, match="source digest mismatch"):
        readout.predict_trigger_readout(model, SOURCE, "rule", expected_source_sha256="0" * 64)
    result = readout.predict_trigger_readout(model, SOURCE, None, expected_source_sha256=digest(SOURCE))
    assert result["blockers"] == ["explicit_caller_condition_attachment_required"]
    assert result["modality_logits"] is None and not result["model_executed"]


def source_output():
    return {"support": torch.tensor([8.]), "modality": torch.tensor([[.1, .2, .3]]),
            "presence": torch.tensor([[[1., 0.], [1., 0.]]]),
            **{key: {facet: torch.tensor([[5. if i == pos else -5. for i in range(3)]])
                     for facet, pos in {"modality": 1, "actor": 0, "action": 2, "object": 0, "condition": 0}.items()}
               for key in ("start", "end")}}


def test_prediction_owner_keeps_nullable_attachment_and_zero_authority(donor_bytes):
    model = model_from(donor_bytes)
    model.forward = lambda *_: source_output()
    source = "cedar must move"
    result = readout.predict_trigger_readout(model, source, "statement", expected_source_sha256=digest(source))
    assert result["status"] == "predicted"
    assert result["prediction"]["condition_attachment"] is None
    assert result["prediction"]["spans"]["condition"] is None
    assert result["modality_logits"] == source_output()["modality"][0].tolist()
    assert all(v == 0 for v in result["masks"].values())
    assert result["formal_output"] is None and not result["proof_authority"]


@pytest.mark.parametrize("fault", ["reversed", "shape", "nonfinite"])
def test_bad_predictions_block_without_repairs(donor_bytes, fault):
    model = model_from(donor_bytes)
    output = source_output()
    if fault == "reversed":
        output["end"]["action"] = torch.tensor([[5., -5., -5.]])
    elif fault == "shape":
        output["modality"] = torch.zeros(1, 4)
    else:
        output["modality"][0, 0] = float("nan")
    model.forward = lambda *_: output
    source = "cedar must move"
    result = readout.predict_trigger_readout(model, source, "rule", expected_source_sha256=digest(source))
    assert result["status"] == "blocked" and result["prediction"] is None
    assert result["modality_logits"] is not None if fault == "reversed" else result["modality_logits"] is None


@pytest.mark.parametrize("fault", ["extra", "seal", "donor_sha", "donor_bytes", "adapter_shape", "adam_step", "adam_variance", "steps", "recipe"])
def test_checkpoint_rejects_tampered_custody_shapes_and_progress(donor_bytes, fault):
    model = model_from(donor_bytes)
    optimizer = readout.make_trigger_readout_optimizer(model)
    readout.train_trigger_readout_step(model, optimizer, training_rows())
    checkpoint = readout.save_trigger_readout_checkpoint(model, optimizer, steps=1)
    if fault == "extra":
        checkpoint["extra"] = None
    elif fault == "seal":
        checkpoint["checkpoint_sha256"] = "0" * 64
    elif fault == "donor_sha":
        checkpoint["donor"]["sha256"] = "0" * 64
    elif fault == "donor_bytes":
        checkpoint["donor"]["bytes"] += 1
    elif fault == "adapter_shape":
        checkpoint["adapter_state"]["0.weight"]["shape"][0] += 1
    elif fault == "adam_step":
        checkpoint["optimizer"]["state"]["0"]["step"]["values"][0] = 0.
    elif fault == "adam_variance":
        checkpoint["optimizer"]["state"]["0"]["exp_avg_sq"]["values"][0] = -1.
    elif fault == "steps":
        checkpoint["steps"] = True
    else:
        checkpoint["profile"]["target_spans_at_inference"] = True
    if fault != "seal":
        reseal(checkpoint)
    with pytest.raises(ValueError):
        readout.restore_trigger_readout_checkpoint(checkpoint)


def test_donor_pin_and_runtime_freeze_cannot_silently_change(donor_bytes):
    with pytest.raises(ValueError, match="donor digest mismatch"):
        readout.FrozenTriggerReadout(donor_bytes, expected_donor_sha256="0" * 64)
    model = model_from(donor_bytes)
    parsed = model.donor_checkpoint
    parsed["steps"] = 99
    assert model.donor_checkpoint["steps"] == 1
    with torch.no_grad():
        model.donor.support_head.bias.add_(1.)
    with pytest.raises(ValueError, match="frozen donor state changed"):
        model(*span._encoded_sources([SOURCE])[0])


def test_v1_predictor_rejects_wrapper_and_tensor_bounds_remain_closed(donor_bytes):
    model = model_from(donor_bytes)
    with pytest.raises(ValueError, match="typed scope model"):
        span.predict_scope_span_decoder(model, SOURCE, "rule", expected_source_sha256=digest(SOURCE))
    (values, mask), _ = span._encoded_sources([SOURCE])
    with pytest.raises(ValueError, match="CPU typed"):
        model(values.float(), mask)
    invalid = values.clone(); invalid[0, 0, 0] = 257
    with pytest.raises(ValueError, match="alphabet"):
        model(invalid, mask)
    with pytest.raises(ValueError):
        readout.TriggerReadoutExample("x" * 65, False)
