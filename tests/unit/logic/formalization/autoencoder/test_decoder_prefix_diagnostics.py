"""Synthetic fixed-state prefix diagnostics; no corpus or qualification runs."""
from copy import deepcopy
import json
import math
import random
import re
import time

import pytest

torch = pytest.importorskip("torch")
from ipfs_datasets_py.logic.formalization.autoencoder import decoder_prefix_diagnostics as subject
from ipfs_datasets_py.logic.formalization.autoencoder import decoder_cardinality_experiment as adapter
from ipfs_datasets_py.logic.formalization.autoencoder import decoder_distillation_experiment as core
from .test_long_span_cardinality_training import setup, validate_rule


@pytest.fixture(autouse=True)
def one_cpu():
    old = torch.get_num_threads(); torch.set_num_threads(1)
    yield
    torch.set_num_threads(old)


def example(kind="conditioned", unavailable=False):
    model, _, _, originals, options = setup()
    rows = deepcopy(originals)
    ids = [r["id"] for r in rows]
    assignment = dict(zip(ids, list(reversed(ids)) if kind == "source_shuffle" else ids))
    source_by_id = {r["id"]: r for r in originals}
    for row in rows:
        row["input"] = deepcopy(source_by_id[assignment[row["id"]]]["input"])
    control = dict(kind=kind, source_assignment=assignment)
    predictions = [dict(id=r["id"], token_ids=r["target_ids"][1:-1], eos_reached=True, generation_status="eos") for r in rows]
    executed = adapter.bind_zero_condition_model(model) if kind == "zero_condition" else model
    provenance = dict(schema=subject.ARCHIVE_SCHEMA, status="unavailable" if unavailable else "available",
        split="synthetic-validation", rows_sha256=core.digest(rows), control_sha256=core.digest(control), output_limit=128)
    if unavailable:
        predictions = None
        provenance["reason"] = "not present in prior archive"
    else:
        provenance.update(predictions_sha256=core.digest(predictions), prior_report_sha256="a"*64,
            executed_model_weights_sha256=core.tensor_digest(executed), codec_sha256=core.digest(options["codec"]))
    kwargs = dict(codec=options["codec"], input_transform=options["input_transform"], lineage=options["lineage"],
        archived_predictions=predictions, archive_provenance=provenance, source_rows=originals, control=control,
        validate_rule=validate_rule, validator_id=options["validator_id"], max_target_tokens=128, batch_size=2)
    return model, rows, options["validation_references"], kwargs


def call(values, **extra):
    model, rows, refs, kwargs = values
    return subject.diagnose_prefixes(model, rows, refs, **{**kwargs, **extra})


def annotation_example():
    rule = dict(actor="actor", action='quote "x"\\path\n雪', object="rules", modality="O",
        conditions=["actor", "object"], exceptions=[], temporal=["}"])
    target = {"rules": [rule, dict(rule, actor="action", conditions=[], temporal=[])]}
    raw = json.dumps(target, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    tokens = re.findall(r'"(?:[^"\\]|\\.)*"|[{}\[\],:]', raw)
    vocabulary = ["<pad>", "<bos>", "<eos>"]+sorted(set(tokens))
    return target, dict(target_vocabulary=vocabulary), tokens


def test_annotation_is_lossless_and_position_aware_for_repeated_keys_values_escaping():
    target, codec, tokens = annotation_example()
    rows = subject.annotate_target(target, codec)
    assert [r["token"] for r in rows] == ["<bos>"]+tokens+["<eos>"]
    assert [r["position"] for r in rows] == list(range(len(rows)))
    actor = [r for r in rows if r["token"] == '"actor"']
    assert {r["kind"] for r in actor} == {"field_key", "scalar_value", "qualifier_atom"}
    assert all(not r["meaningful_value"] for r in actor if r["kind"] == "field_key")
    scalar = next(r for r in actor if r["kind"] == "scalar_value")
    qualifier = next(r for r in actor if r["kind"] == "qualifier_atom")
    assert scalar["path"] == ["rules", 0, "actor"]
    assert qualifier["path"] == ["rules", 0, "conditions", 0]
    assert scalar["value_id"] != qualifier["value_id"]
    assert sum(r["kind"] == "fixed_empty_qualifier" for r in rows) == 8
    assert all(not r["meaningful_value"] for r in rows if r["kind"] == "fixed_empty_qualifier")
    boundaries = [r for r in rows if r["boundary_after_rule"] is not None]
    assert [(r["token"], r["boundary_after_rule"]) for r in boundaries] == [(",", 0), ("]", 1)]
    for row in boundaries:
        assert rows[row["position"]-1]["token"] == "}"
        assert row["path"] == ["rules"] and row["field"] is None
    assert rows[-1]["kind"] == "eos" and not rows[-1]["meaningful_value"]


def test_handcrafted_logits_rank_ties_full_vocabulary_and_binary_boundary_are_distinct():
    target, codec, _ = annotation_example()
    annotations = subject.annotate_target(target, codec)
    vocabulary = codec["target_vocabulary"]
    labels = torch.tensor([r["token_id"] for r in annotations[1:]])
    logits = torch.zeros((len(labels), len(vocabulary)), dtype=torch.float32)
    logits[torch.arange(len(labels)), labels] = 1.
    boundary = next(r for r in annotations if r["boundary_after_rule"] == 0)
    i = boundary["position"]-1
    logits[i].zero_()
    logits[i, vocabulary.index("]")] = 2.
    logits[i, vocabulary.index(",")] = 1.
    logits[i, vocabulary.index('"rules"')] = 3.
    # Equal-score target/earlier-ID tie: rank1, but argmax picks first ID.
    j = next(r["position"]-1 for r in annotations if r["kind"] == "scalar_value")
    logits[j].zero_(); logits[j, 0] = 1.; logits[j, labels[j]] = 1.
    positions, boundaries = subject._position_metrics(torch, logits, labels, annotations, vocabulary)
    b = boundaries[0]
    denominator = sum(math.exp(float(x)) for x in logits[i])
    assert b["stop_probability"] == pytest.approx(math.exp(2.)/denominator, rel=1e-6)
    assert b["continue_probability"] == pytest.approx(math.exp(1.)/denominator, rel=1e-6)
    assert b["other_probability"] == pytest.approx(1.-(math.exp(2.)+math.exp(1.))/denominator, rel=1e-6)
    assert b["expected"] == "continue" and b["two_way_choice"] == "stop"
    assert not b["full_vocabulary_correct"] and b["argmax_token"] == '"rules"'
    assert b["stop_minus_continue_logit"] == 1.
    assert positions[j]["rank"] == 1 and positions[j]["argmax_token_id"] == 0
    assert positions[j]["correct"] is False
    assert positions[j]["raw_logits"] == logits[j].tolist()
    assert positions[-1]["kind"] == "eos" and positions[-1]["correct"]


@pytest.mark.parametrize("ending", ["eos", "output_limit", "invalid_special_token"])
def test_first_divergence_never_invents_missing_eos(ending):
    target, codec, _ = annotation_example()
    annotation = subject.annotate_target(target, codec)
    prediction = dict(id="x", token_ids=[r["token_id"] for r in annotation[1:-1]],
        eos_reached=ending == "eos", generation_status=ending)
    result = subject.first_divergence(annotation, prediction, vocabulary=codec["target_vocabulary"], output_limit=512)
    assert result["explicit_eos_appended"] == (ending == "eos")
    if ending == "eos":
        assert result["status"] == "exact_with_explicit_eos" and result["expected_position"] is None
    else:
        assert result["expected_position"]["kind"] == "eos"
        assert result["emitted_token_id"] is None
        assert result["matched_prefix_tokens"] == len(annotation)-2
        assert result["missing_eos"]


def test_first_divergence_matches_expected_facet_at_wrong_emitted_token():
    target, codec, _ = annotation_example()
    annotation = subject.annotate_target(target, codec)
    value = next(r for r in annotation if r["kind"] == "scalar_value")
    tokens = [r["token_id"] for r in annotation[1:-1]]
    tokens[value["position"]-1] = codec["target_vocabulary"].index("{")
    result = subject.first_divergence(annotation, dict(token_ids=tokens, generation_status="eos", eos_reached=True),
        vocabulary=codec["target_vocabulary"], output_limit=512)
    assert result["status"] == "token_mismatch"
    assert result["expected_position"]["field"] == value["field"]
    assert result["matched_prefix_tokens"] == value["position"]-1
    assert result["emitted_token"] == "{"


def test_missing_prediction_is_unavailable_not_fake_eos_or_fake_divergence():
    target, codec, _ = annotation_example()
    result = subject.first_divergence(subject.annotate_target(target, codec), None,
        vocabulary=codec["target_vocabulary"], output_limit=512)
    assert result["status"] == "prediction_missing" and not result["available"]
    assert result["emitted_token_id"] is None


@pytest.mark.parametrize("kind", ["conditioned", "source_shuffle", "zero_condition"])
def test_real_tiny_model_full_prefix_only_preserves_caller_and_reconciles_numeric_ce(kind, monkeypatch):
    values = example(kind); model, rows, refs, kwargs = values
    model.train(); model.count_head.eval()
    next(iter(model.parameters())).grad = torch.ones_like(next(iter(model.parameters())))
    before = core.tensor_digest(model), subject.gradient_digest(model)
    modes = {n: m.training for n, m in model.named_modules()}
    data_before = deepcopy((rows, refs, kwargs))
    torch_before, random_before = torch.get_rng_state().clone(), random.getstate()
    def forbidden(*args, **kwargs):
        raise AssertionError("generation/training forbidden")
    monkeypatch.setattr(core, "_greedy", forbidden)
    monkeypatch.setattr(torch.optim, "AdamW", forbidden)
    result = call(values)
    report = result["report"]
    assert report["complete"] and report["forward_executed"] and report["reference_prefix_access"]
    assert all(report[key] is False for key in subject.FALSE)
    assert report["diagnostic_rows_sha256"] == core.digest(result["rows"])
    assert report["report_sha256"] == core.digest({k:v for k,v in report.items() if k != "report_sha256"})
    assert report["aggregates"]["archived_first_divergence"]["by_status"] == {"exact_with_explicit_eos": 2}
    assert report["aggregates"]["whole_value"]["token_counts"] == [1]
    assert report["numerical"]["target_token_count"] == sum(len(r["target_ids"])-1 for r in rows)
    assert report["aggregates"]["by_facet"]["exceptions"]["tokens"] == 0
    assert before == (core.tensor_digest(model), subject.gradient_digest(model))
    assert modes == {n: m.training for n, m in model.named_modules()}
    assert (rows, refs, kwargs) == data_before
    assert torch.equal(torch_before, torch.get_rng_state()) and random_before == random.getstate()
    work = adapter.bind_zero_condition_model(model) if kind == "zero_condition" else deepcopy(model)
    work.eval()
    with torch.inference_mode():
        data, labels = core._batch(torch, rows, kwargs["input_transform"])
        _, logits = core._logits(torch, work, data, labels[:, :-1], len(kwargs["codec"]["target_vocabulary"]))
        ce = torch.nn.functional.cross_entropy(logits.flatten(0,1), labels[:,1:].flatten(),ignore_index=0,reduction="sum")
        expected = float(ce)/int((labels[:,1:] != 0).sum())
    assert report["numerical"]["token_cross_entropy"] == expected
    json.dumps(result, allow_nan=False)


def test_unavailable_archive_has_zero_observed_divergence_denominator():
    values = example("zero_condition", unavailable=True)
    result = call(values)
    assert result["report"]["archived_fidelity_metrics"] is None
    assert result["report"]["aggregates"]["archived_first_divergence"]["available_rows"] == 0
    assert all(r["first_divergence"]["status"] == "archive_panel_unavailable" for r in result["rows"])
    assert result["report"]["executed_model_weights_sha256"] != result["report"]["model_weights_sha256"]


@pytest.mark.parametrize("mutation,reason", [
    ("target", "complete reference token"), ("source", "reference source"), ("source_hash", "source provenance"),
    ("duplicate_reference", "reference IDs"), ("assignment", "assigned original source"),
    ("prediction_digest", "archive predictions"), ("model_digest", "archive predictions"),
    ("control_digest", "archive inputs"), ("truncated", "complete BOS/content/EOS"),
    ("unavailable_with_predictions", "unavailable archive"), ("mutating_validator", "validator mutated")])
def test_tamper_and_incomplete_inputs_fail_closed(mutation, reason):
    values = example(); model, rows, refs, kwargs = values
    if mutation == "target":
        refs[0]["target"]["rules"][0]["actor"] = "agency"
    elif mutation == "source": refs[0]["source_text"] += "changed"
    elif mutation == "source_hash": refs[0]["source_sha256"] = "f"*64
    elif mutation == "duplicate_reference": refs[1] = deepcopy(refs[0])
    elif mutation == "assignment": rows[0]["input"][0] += .1
    elif mutation == "prediction_digest": kwargs["archive_provenance"]["predictions_sha256"] = "f"*64
    elif mutation == "model_digest": kwargs["archive_provenance"]["executed_model_weights_sha256"] = "f"*64
    elif mutation == "control_digest": kwargs["archive_provenance"]["control_sha256"] = "f"*64
    elif mutation == "truncated": rows[0]["target_ids"] = rows[0]["target_ids"][:-1]
    elif mutation == "unavailable_with_predictions": kwargs["archive_provenance"]["status"] = "unavailable"
    elif mutation == "mutating_validator":
        def bad(value):
            value["rules"][0]["actor"] = "changed"
            return {"valid": True}
        kwargs["validate_rule"] = bad
    with pytest.raises(ValueError, match=reason): call(values)


def test_memory_preflight_before_private_model_allocation(monkeypatch):
    values = example()
    original = subject.deepcopy
    def checked(value):
        assert not isinstance(value, torch.nn.Module), "model copy before memory preflight"
        return original(value)
    monkeypatch.setattr(subject, "deepcopy", checked)
    with pytest.raises(ValueError, match="memory estimate"):
        call(values, max_memory_bytes=1048576, batch_size=128)


def test_final_integrity_time_is_inside_deadline(monkeypatch):
    values = example()
    clock, calls = [0.], [0]
    original = subject.gradient_digest
    def digest(model):
        calls[0] += 1
        answer = original(model)
        if calls[0] == 2: clock[0] = 31.
        return answer
    monkeypatch.setattr(subject, "gradient_digest", digest)
    monkeypatch.setattr(subject.time, "monotonic", lambda: clock[0])
    rng = torch.get_rng_state().clone(); prior = random.getstate()
    with pytest.raises(TimeoutError, match="deadline"):
        call(values, max_seconds=30.)
    assert calls[0] == 2 and torch.equal(rng, torch.get_rng_state()) and prior == random.getstate()


def test_nonfinite_forward_and_failure_restore_rng_and_caller(monkeypatch):
    values = example(); model = values[0]
    before = core.tensor_digest(model), subject.gradient_digest(model)
    rng = torch.get_rng_state().clone(); prior = random.getstate()
    original = model.__class__.next_logits
    def poisoned(self, *args):
        random.random(); torch.rand(1)
        logits, hidden = original(self, *args)
        return logits*float("nan"), hidden
    monkeypatch.setattr(model.__class__, "next_logits", poisoned)
    with pytest.raises(ValueError, match="finite-state"):
        call(values)
    assert before == (core.tensor_digest(model), subject.gradient_digest(model))
    assert torch.equal(rng, torch.get_rng_state()) and prior == random.getstate()


def test_batch_splitting_preserves_denominator_and_bounds_float32_reduction_difference():
    values = example()
    first = call(values, batch_size=1)
    second = call(values, batch_size=2)
    assert first["report"]["numerical"]["target_token_count"] == second["report"]["numerical"]["target_token_count"]
    assert first["report"]["numerical"]["token_cross_entropy"] == pytest.approx(second["report"]["numerical"]["token_cross_entropy"], rel=1e-6)
    for x, y in zip(first["rows"], second["rows"]):
        assert x["id"] == y["id"] and len(x["positions"]) == len(y["positions"])
        for a, b in zip(x["positions"], y["positions"]):
            assert a["log_probability"] == pytest.approx(b["log_probability"], rel=1e-6)
