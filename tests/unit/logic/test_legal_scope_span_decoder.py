"""CPU occurrence learning, exact numerical resume and proposal boundaries."""
from copy import deepcopy
from hashlib import sha256

import pytest
import torch

from ipfs_datasets_py.logic.formalization.autoencoder import legal_scope_span_decoder as decoder
from ipfs_datasets_py.logic.formalization.autoencoder import legal_scope_span_proposal as proposal

SOURCE = "The Régisseur shall submit notice if notice arrives."


def target(*, optional=True, attachment="rule"):
    def span(text, start=0):
        at = SOURCE.index(text, start)
        return [at, at + len(text)]
    return {"schema": proposal.PREDICTION_SCHEMA, "interpretation_profile": proposal.INTERPRETATION_PROFILE,
            "modality": "O", "spans": {"modality": span("shall"), "actor": span("Régisseur"),
            "action": span("submit"), "object": span("notice") if optional else None,
            "condition": span("notice arrives", span("notice")[1]) if optional else None},
            "condition_attachment": attachment if optional else None}


def example(optional=True):
    return decoder.ScopeSpanExample(SOURCE, True, target(optional=optional))


def model(kernel=3):
    return decoder.ScopeSpanDecoder(decoder.ScopeSpanDecoderConfig(seed=19, byte_kernel=kernel,
        byte_dim=4, byte_hidden=4, token_dim=8, token_hidden=8, head_hidden=8))


def predict(network, attachment="rule", text=SOURCE):
    return decoder.predict_scope_span_decoder(network, text, attachment,
        expected_source_sha256=sha256(text.encode()).hexdigest())


def fake_output(network, *, optional=True, support=10.):
    tokens = decoder.tokenize_source(SOURCE)
    starts = {t.start: i for i, t in enumerate(tokens)}
    ends = {t.end: i for i, t in enumerate(tokens)}
    expected = target(optional=optional)
    result = {"support": torch.tensor([support], dtype=torch.float32),
              "modality": torch.tensor([[8., -8., -8.]], dtype=torch.float32),
              "presence": torch.tensor([[[-8., 8.] if optional else [8., -8.]] * 2], dtype=torch.float32),
              "start": {}, "end": {}}
    for facet in decoder.FACETS:
        value = expected["spans"][facet]
        for key, position in (("start", starts[value[0]] if value else 0),
                              ("end", ends[value[1]] if value else 0)):
            logits = torch.full((1, len(tokens)), -8., dtype=torch.float32)
            logits[0, position] = 8.
            result[key][facet] = logits
    return result


def seal(checkpoint):
    checkpoint["checkpoint_sha256"] = sha256(decoder._canonical(
        {k: v for k, v in checkpoint.items() if k != "checkpoint_sha256"})).hexdigest()
    return checkpoint


@pytest.mark.parametrize("kernel", [1, 3])
def test_generic_unicode_bounds_cpu_and_rng(kernel):
    rng = torch.get_rng_state().clone()
    network = model(kernel)
    assert torch.equal(rng, torch.get_rng_state())
    assert all(p.device.type == "cpu" and p.dtype == torch.float32 for p in network.parameters())
    assert all(SOURCE[t.start:t.end] == t.text for t in decoder.tokenize_source(SOURCE))
    assert decoder.tokenize_source("é")[0].end == 1
    with pytest.raises(ValueError, match="token bounds"):
        decoder.tokenize_source("a " * 97)
    with pytest.raises(ValueError, match="byte bounds"):
        decoder.tokenize_source("é" * 33)
    with pytest.raises(ValueError, match="UTF8"):
        decoder.tokenize_source("\ud800")


@pytest.mark.parametrize("kernel", [1, 3])
def test_padding_invariance_for_short_source_in_mixed_batch(kernel):
    network = model(kernel).eval()
    short, _ = decoder._encoded_sources(["A may run."])
    mixed, _ = decoder._encoded_sources(["A may run.", "The Verylongregistrar shall record extensive observations."])
    with torch.no_grad():
        left, right = network(*short), network(*mixed)
    for key in ("support", "modality", "presence"):
        torch.testing.assert_close(left[key][0], right[key][0], atol=2e-7, rtol=2e-6)
    for key in ("start", "end"):
        for facet in decoder.FACETS:
            torch.testing.assert_close(left[key][facet][0], right[key][facet][0, :short[0].shape[1]], atol=2e-7, rtol=2e-6)


@pytest.mark.parametrize("kernel", [1, 3])
def test_real_gradient_step_exact_resume_and_preserved_reload_mode_rng(kernel):
    network = model(kernel)
    optimizer = decoder.make_scope_span_optimizer(network)
    original = deepcopy(network.state_dict())
    rows = [example(), decoder.ScopeSpanExample("The clerk shall dance or sing.", False)]
    report = decoder.train_scope_span_step(network, optimizer, rows)
    assert report["supported_examples"] == report["unsupported_examples"] == 1
    assert report["loss"] > 0 and report["gradient_norm"] > 0
    assert any(not torch.equal(value, original[name]) for name, value in network.state_dict().items())
    network.eval()
    saved = decoder.save_scope_span_checkpoint(network, optimizer, steps=1)
    rng = torch.get_rng_state().clone()
    restored, resumed, steps = decoder.restore_scope_span_checkpoint(saved)
    assert steps == 1 and not restored.training and torch.equal(rng, torch.get_rng_state())
    assert decoder.save_scope_span_checkpoint(restored, resumed, steps=1) == saved
    a = decoder.train_scope_span_step(network, optimizer, rows)
    b = decoder.train_scope_span_step(restored, resumed, rows)
    assert a == b
    assert decoder.save_scope_span_checkpoint(network, optimizer, steps=2) == decoder.save_scope_span_checkpoint(restored, resumed, steps=2)


def test_negative_and_absent_optional_pointer_heads_have_no_gradient_or_moment_updates():
    network = model()
    optimizer = decoder.make_scope_span_optimizer(network, weight_decay=.1)
    decoder.train_scope_span_step(network, optimizer, [example()])
    before = decoder.save_scope_span_checkpoint(network, optimizer, steps=1)
    decoder.train_scope_span_step(network, optimizer, [example(optional=False)])
    after = decoder.save_scope_span_checkpoint(network, optimizer, steps=2)
    optional = [name for name, _ in network.named_parameters()
                if name.startswith(tuple(k + "." + f + "." for k in ("start_heads", "end_heads") for f in decoder.OPTIONAL))]
    names = [name for name, _ in network.named_parameters()]
    for name in optional:
        assert dict(network.named_parameters())[name].grad is None
        assert before["model_state"][name] == after["model_state"][name]
        assert before["optimizer"]["state"][str(names.index(name))] == after["optimizer"]["state"][str(names.index(name))]
    decoder.train_scope_span_step(network, optimizer, [decoder.ScopeSpanExample(SOURCE, False)])
    negative = decoder.save_scope_span_checkpoint(network, optimizer, steps=3)
    for name, parameter in network.named_parameters():
        if name.startswith(decoder._STRUCTURAL):
            assert parameter.grad is None
            assert negative["model_state"][name] == after["model_state"][name]
            assert negative["optimizer"]["state"][str(names.index(name))] == after["optimizer"]["state"][str(names.index(name))]
    assert decoder.restore_scope_span_checkpoint(negative)[2] == 3


def test_never_seen_optional_or_all_structural_adam_states_stay_absent():
    for rows in ([example(optional=False)], [decoder.ScopeSpanExample(SOURCE, False)]):
        network = model()
        optimizer = decoder.make_scope_span_optimizer(network)
        decoder.train_scope_span_step(network, optimizer, rows)
        saved = decoder.save_scope_span_checkpoint(network, optimizer, steps=1)
        restored, resumed, steps = decoder.restore_scope_span_checkpoint(saved)
        assert decoder.save_scope_span_checkpoint(restored, resumed, steps=steps) == saved


@pytest.mark.parametrize("attachment", ["rule", "statement"])
@pytest.mark.parametrize("optional", [True, False])
def test_only_predicted_occurrences_and_caller_premise_reach_existing_zero_mask_owner(monkeypatch, attachment, optional):
    network = model().eval()
    output = fake_output(network, optional=optional)
    monkeypatch.setattr(network, "forward", lambda *_: output)
    monkeypatch.setattr(decoder, "_labels", lambda *_: pytest.fail("Inference accessed targets"))
    result = predict(network, attachment)
    assert result["status"] == "predicted" and result["prediction"] == target(optional=optional, attachment=attachment)
    assert all(v == 0 for v in result["masks"].values())
    assert result["proposal"]["declaration"]["input"]["context"]["role"] == "required_unavailable"
    assert result["proposal"]["formal_output"] is result["formal_output"] is None
    assert result["condition_attachment_origin"] == "explicit_caller_premise"
    assert result["model_executed"] is True and result["target_access"] is False and not network.training
    for flag in ("qualified", "accepted", "formalized", "proof_authority", "proof_ready", "source_semantics_verified"):
        assert result[flag] is False


def test_caller_premise_and_external_digest_are_required_before_forward(monkeypatch):
    network = model()
    monkeypatch.setattr(network, "forward", lambda *_: pytest.fail("Invalid input executed model"))
    assert predict(network, None)["blockers"] == ["explicit_caller_condition_attachment_required"]
    with pytest.raises(ValueError, match="digest mismatch"):
        decoder.predict_scope_span_decoder(network, SOURCE, "rule", expected_source_sha256="0" * 64)
    with pytest.raises(TypeError):
        decoder.predict_scope_span_decoder(network, SOURCE, "rule", expected_source_sha256=sha256(SOURCE.encode()).hexdigest(), target=target())


@pytest.mark.parametrize("bad", ["unsupported", "nonfinite", "shape", "overlap", "reverse"])
def test_refusal_shapes_finite_and_grammar_do_not_repair_predictions(monkeypatch, bad):
    network = model()
    output = fake_output(network)
    if bad == "unsupported":
        output["support"].fill_(-10.)
    elif bad == "nonfinite":
        output["modality"][0, 0] = float("nan")
    elif bad == "shape":
        output["start"]["object"] = torch.zeros((1, 1))
    elif bad == "overlap":
        output["start"]["action"] = output["start"]["actor"].clone()
        output["end"]["action"] = output["end"]["actor"].clone()
    else:
        output["start"]["actor"].fill_(-8.)
        output["start"]["actor"][0, -1] = 8.
    monkeypatch.setattr(network, "forward", lambda *_: output)
    result = predict(network)
    assert result["status"] == ("abstained" if bad == "unsupported" else "blocked")
    assert result["prediction"] is result["proposal"] is None and result["blockers"]
    assert network.training


def test_train_validates_explicit_occurrences_and_rejects_structural_negatives():
    with pytest.raises(ValueError, match="unsupported examples"):
        decoder.ScopeSpanExample(SOURCE, False, target())
    network = model()
    optimizer = decoder.make_scope_span_optimizer(network)
    bad = target()
    bad["spans"]["actor"][0] += 1
    before = decoder.save_scope_span_checkpoint(network, optimizer, steps=0)
    with pytest.raises(ValueError, match="cuts a token"):
        decoder.train_scope_span_step(network, optimizer, [decoder.ScopeSpanExample(SOURCE, True, bad)])
    assert decoder.save_scope_span_checkpoint(network, optimizer, steps=0) == before


@pytest.mark.parametrize("bad", ["seal", "schema", "producer", "shape", "overflow", "step", "variance", "extra"])
def test_checkpoint_rejects_corruption_and_invented_progress(bad):
    network = model()
    optimizer = decoder.make_scope_span_optimizer(network)
    decoder.train_scope_span_step(network, optimizer, [example()])
    saved = deepcopy(decoder.save_scope_span_checkpoint(network, optimizer, steps=1))
    first = next(iter(saved["model_state"]))
    adam = next(iter(saved["optimizer"]["state"].values()))
    if bad == "seal":
        saved["checkpoint_sha256"] = "0" * 64
    elif bad == "schema":
        saved["schema"] = "legal-grouped-span-decoder-checkpoint/v2"
    elif bad == "producer":
        saved["producer"]["implementation_sha256"] = "0" * 64
    elif bad == "shape":
        saved["model_state"][first]["shape"] = [1]
    elif bad == "overflow":
        saved["model_state"][first]["values"][0] = 1e100
    elif bad == "step":
        adam["step"]["values"][0] = 2.
    elif bad == "variance":
        adam["exp_avg_sq"]["values"][0] = -1.
    else:
        saved["unexpected"] = True
    if bad != "seal":
        seal(saved)
    with pytest.raises(ValueError):
        decoder.restore_scope_span_checkpoint(saved)


def test_declared_zero_steps_reject_nonempty_adam_and_boolean_progress():
    network = model()
    optimizer = decoder.make_scope_span_optimizer(network)
    decoder.train_scope_span_step(network, optimizer, [example()])
    with pytest.raises(ValueError, match="zero progress"):
        decoder.save_scope_span_checkpoint(network, optimizer, steps=0)
    with pytest.raises(ValueError, match="integer progress"):
        decoder.save_scope_span_checkpoint(network, optimizer, steps=True)
