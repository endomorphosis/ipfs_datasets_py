"""Bounded genuine CPU generation engineering with exposed authored context.

Conditioning is arbitrary and the compact head has zero optimizer updates.
These controls establish neither an encoder nor held-out/statutory accuracy.
All execution belongs to the coordinator's exact owned native qualification.
"""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import pytest
import torch

from ipfs_datasets_py.logic.autoformal import legal_relational_batch_evaluation_v1 as batch
from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_generation_v1 as subject
from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_head_v1 as head
from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_tokens_v1 as tokens


def _fixtures():
    path = Path(__file__).with_name("test_legal_relational_content_token_batch_evaluation_v1.py")
    spec = importlib.util.spec_from_file_location("_compact_generation_authored_content_fixtures", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


fixtures = _fixtures()
material = fixtures.material
wire, sha = fixtures.wire, fixtures.sha


def digest(value):
    return sha(wire(value))


@pytest.fixture(scope="module", autouse=True)
def bounded_threads():
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    try:
        yield
    finally:
        torch.set_num_threads(previous)


@pytest.fixture(scope="module")
def checkpoint():
    return head.create_compact_content_head_v1(config={"hidden_size": 8,
        "token_embedding_dim": 8, "projection_width": 4, "seed": 1729})


def arguments(material, checkpoint, *, prefix=None, max_new_tokens=3,
              prefix_origin="bos_seed", context_origin="target_derived_label"):
    raw = wire(material["context"])
    values = (checkpoint, [.25, -.125] + [0.] * 382,
              [1] if prefix is None else deepcopy(prefix), raw)
    options = {"expected_checkpoint_sha256": digest(checkpoint),
        "expected_context_sha256": sha(raw), "max_new_tokens": max_new_tokens,
        "prefix_origin": prefix_origin, "context_origin": context_origin}
    return values, options


def generate(material, checkpoint, **changes):
    values, options = arguments(material, checkpoint, **changes)
    return subject.generate_compact_content_v1(*values, **options)


def validate(report, values, options, **changes):
    return subject.validate_compact_content_generation_v1(report, *values,
        **{**options, "expected_report_sha256": digest(report), **changes})


def adapter(report, values, options, case, *, occurrence_id="one", **changes):
    population_raw = case["population_raw"]
    return subject.prepare_compact_content_generation_batch_prediction_v1(
        report, *values, population_raw,
        **{**options, "expected_generation_sha256": digest(report),
           "expected_population_sha256": sha(population_raw),
           "occurrence_id": occurrence_id, **changes})


def evaluate_adapter(adapted, case):
    population_raw, references_raw, _ = fixtures.legacy.originals(case)[0]
    predictions_raw = wire(adapted["predictions"])
    return batch.prepare_relational_content_token_batch_evaluation_v1(
        population_raw, references_raw, predictions_raw,
        expected_population_sha256=sha(population_raw),
        expected_references_sha256=sha(references_raw),
        expected_predictions_sha256=sha(predictions_raw))


def no_authority(report):
    assert report["authority"] and all(flag is False for flag in report["authority"].values())
    assert type(report["training_mask"]) is int and report["training_mask"] == 0
    assert type(report["evaluation_gold_mask"]) is int and report["evaluation_gold_mask"] == 0


@pytest.mark.parametrize("budget", [True, 0, -1, 513, 1.0, None])
def test_generation_step_budget_requires_bounded_plain_positive_integer(material, checkpoint, monkeypatch, budget):
    values, options = arguments(material, checkpoint)
    options["max_new_tokens"] = budget
    monkeypatch.setattr(head, "score_compact_content_head_v1",
                        lambda *args, **kwargs: pytest.fail("invalid generation budget reached numerical head"))
    with pytest.raises(ValueError):
        subject.generate_compact_content_v1(*values, **options)


@pytest.mark.parametrize("field", ["expected_checkpoint_sha256", "expected_context_sha256"])
def test_independent_original_input_pins_refuse_before_any_head_step(material, checkpoint, monkeypatch, field):
    values, options = arguments(material, checkpoint)
    options[field] = "0" * 64
    monkeypatch.setattr(head, "score_compact_content_head_v1",
                        lambda *args, **kwargs: pytest.fail("wrong original pin reached numerical head"))
    with pytest.raises(ValueError):
        subject.generate_compact_content_v1(*values, **options)


@pytest.mark.parametrize("failure_type", [RuntimeError, ValueError, KeyboardInterrupt])
def test_public_head_operational_failures_propagate_without_partial_trace(material, checkpoint, monkeypatch, failure_type):
    values, options = arguments(material, checkpoint)
    failure = failure_type("authored numerical boundary failure; no partial model score")
    def failed(*args, **kwargs):
        raise failure
    monkeypatch.setattr(head, "score_compact_content_head_v1", failed)
    with pytest.raises(failure_type) as caught:
        subject.generate_compact_content_v1(*values, **options)
    assert caught.value is failure


@pytest.mark.parametrize("prefix", [[], [True], [1.0], ["1"], [1 << 63], [1] * 513])
def test_prefix_plain_types_and_total_limit_refuse_without_model_execution(material, checkpoint, monkeypatch, prefix):
    values, options = arguments(material, checkpoint, prefix=prefix,
        prefix_origin="caller_supplied_unverified")
    monkeypatch.setattr(head, "_forward",
                        lambda *args, **kwargs: pytest.fail("malformed prefix reached real forward"))
    with pytest.raises(ValueError):
        subject.generate_compact_content_v1(*values, **options)


@pytest.mark.parametrize("field", ["prefix_origin", "context_origin"])
def test_unknown_exposure_labels_do_not_become_permitted_context(material, checkpoint, monkeypatch, field):
    values, options = arguments(material, checkpoint)
    options[field] = "verified_held_out_source_context"
    monkeypatch.setattr(head, "score_compact_content_head_v1",
                        lambda *args, **kwargs: pytest.fail("invalid origin reached head"))
    with pytest.raises(ValueError):
        subject.generate_compact_content_v1(*values, **options)


@pytest.mark.parametrize("steps", [2, 4])
def test_bos_seeded_genuine_steps_retain_complete_scores_and_exact_public_replay(material, checkpoint, steps):
    values, options = arguments(material, checkpoint, max_new_tokens=steps)
    before = deepcopy((values, options))
    rng, threads = torch.get_rng_state().clone(), torch.get_num_threads()
    report = subject.generate_compact_content_v1(*values, **options)
    assert (values, options) == before
    assert report["schema"] == "legal-compact-content-generation/v1"
    assert report["profile"] == "bounded-conditioning-compact-content-generation/v1"
    assert report["status"] == "step_budget_exhausted"
    assert report["reason"] == "max_new_tokens_reached"
    assert report["initial_prefix_ids"] == [1]
    assert report["selected_token_ids"] == report["generated_ids"][1:]
    assert report["emitted_token_count"] == steps
    assert report["total_token_count"] == steps + 1
    assert report["score_call_count"] == report["numerical_forward_count"] == steps
    assert len(report["trace"]) == steps
    assert report["final_decoding"]["generated_ids"] == report["generated_ids"]
    assert report["final_decoding"]["status"] == "incomplete"
    assert report["checkpoint_sha256"] == digest(checkpoint)
    assert report["weights_sha256"] == digest(checkpoint["model_state"])
    assert report["codec_sha256"] == checkpoint["codec_sha256"]
    assert report["conditioning"] == values[1]
    assert report["conditioning_sha256"] == digest(values[1])
    assert report["context_raw_sha256"] == sha(values[3])
    assert report["context_sha256"] == digest(material["context"])
    assert report["settings_sha256"] == digest(report["settings"])
    prefix, selected, raw_argmax = [1], [], []
    for score in report["trace"]:
        # Independent public head replay corroborates actual numerical output;
        # no numerical helper, target string or score stub creates this oracle.
        expected = head.score_compact_content_head_v1(checkpoint, values[1], prefix, values[3],
            expected_checkpoint_sha256=options["expected_checkpoint_sha256"],
            expected_context_sha256=options["expected_context_sha256"])
        assert score == expected
        assert score["status"] == "scored" and score["numerical_forward_executed"] is True
        assert score["model_restore_performed"] is True
        assert score["prefix_ids"] == prefix
        assert len(score["logits"]) == 537
        assert score["logits_sha256"] == digest(score["logits"])
        assert score["selection"]["logits"] == score["logits"]
        assert score["next_prefix_ids"] == prefix + [score["selection"]["selected_token_id"]]
        selected.append(score["selection"]["selected_token_id"])
        raw_argmax.append(score["selection"]["raw_argmax_token_id"])
        prefix = list(score["next_prefix_ids"])
        assert score["optimizer_executed"] is False and score["compact_training_steps"] == 0
        no_authority(score)
    assert report["generated_ids"] == prefix
    assert report["selected_token_ids"] == selected
    assert report["raw_argmax_ids_by_step"] == raw_argmax
    assert report["exposure"]["teacher_forcing"] is False
    assert report["exposure"]["target_access"] is True
    assert report["exposure"]["encoder_sha256"] is None
    assert report["exposure"]["source_encoder_authenticated"] is False
    assert report["exposure"]["context_permission_verified"] is False
    assert report["model_executed"] is True
    assert report["training_executed"] is report["compact_optimizer_executed"] is False
    no_authority(report)
    assert subject.compact_content_generation_sha256(report) == digest(report)
    assert validate(report, values, options) == report
    assert torch.equal(rng, torch.get_rng_state()) and torch.get_num_threads() == threads


@pytest.mark.parametrize("prefix_kind", ["complete", "unknown", "interior_PAD"])
def test_genuine_terminal_prefixes_retain_all_seed_ids_without_numerical_forward(material, checkpoint, monkeypatch, prefix_kind):
    prefix = fixtures.ids_for(material["content"], material["codec"]) if prefix_kind == "complete" else (
        [1, -1] if prefix_kind == "unknown" else [1, 0])
    values, options = arguments(material, checkpoint, prefix=prefix,
        prefix_origin="target_derived_label")
    monkeypatch.setattr(head, "_forward",
                        lambda *args, **kwargs: pytest.fail("terminal prefix reached numerical forward"))
    report = subject.generate_compact_content_v1(*values, **options)
    assert report["status"] == ("supplied_complete" if prefix_kind == "complete" else "blocked")
    assert report["initial_prefix_ids"] == report["generated_ids"] == prefix
    assert report["selected_token_ids"] == [] and report["emitted_token_count"] == 0
    assert report["numerical_forward_count"] == 0 and report["model_executed"] is False
    assert report["total_token_count"] == len(prefix)
    assert report["final_prefix_report"]["allowed_token_ids"] == []
    assert all(score["status"] == "no_forward" and score["logits"] is score["selection"] is None
               and score["prefix_ids"] == score["next_prefix_ids"] == prefix
               and score["numerical_forward_executed"] is False for score in report["trace"])
    assert report["exposure"]["teacher_forcing"] is True
    assert report["exposure"]["target_access"] is True
    no_authority(report)


@pytest.mark.parametrize("damage", ["score", "selected", "origin", "seed", "codec", "no_forward"])
def test_resealed_trace_claims_cannot_replace_original_input_bound_numerical_replay(material, checkpoint, damage):
    values, options = arguments(material, checkpoint, max_new_tokens=2)
    report = subject.generate_compact_content_v1(*values, **options)
    changed = deepcopy(report)
    if damage == "score":
        score = changed["trace"][0]
        score["logits"][0] += .125
        score["logits_sha256"] = digest(score["logits"])
        score["selection"]["logits"] = deepcopy(score["logits"])
        score["selection"]["logits_sha256"] = score["logits_sha256"]
    elif damage == "selected": changed["selected_token_ids"][0] = 0
    elif damage == "origin":
        changed["context_origin"] = "caller_supplied_unverified"
        changed["exposure"]["target_access"] = False
    elif damage == "seed": changed["initial_prefix_ids"][0] = 2
    elif damage == "codec": changed["codec_sha256"] = "0" * 64
    else:
        changed["trace"][0]["numerical_forward_executed"] = False
        changed["trace"][0]["model_restore_performed"] = False
    assert subject.compact_content_generation_sha256(changed) == digest(changed)
    with pytest.raises(ValueError):
        validate(changed, values, options)



def original_payload(values, options):
    return {"checkpoint": values[0], "conditioning": values[1],
        "prefix_ids": values[2], "context_utf8": values[3].decode("utf-8"),
        "options": options}


def test_genuine_bos_and_exposed_eos_evidence_keeps_missing_denominator_and_no_encoder_credit(material, checkpoint, tmp_path):
    # These two executions are the behavior under test, not additional model
    # passes made solely to collect diagnostics. Their full outputs are saved.
    bos_values, bos_options = arguments(material, checkpoint, max_new_tokens=3)
    bos = subject.generate_compact_content_v1(*bos_values, **bos_options)
    assert bos["status"] == "step_budget_exhausted"
    assert bos["initial_prefix_ids"] == [1] and bos["emitted_token_count"] == 3
    assert bos["generated_ids"] == [1, *bos["selected_token_ids"]]
    assert bos["score_call_count"] == bos["numerical_forward_count"] == 3
    assert bos["model_executed"] is True and bos["compact_optimizer_executed"] is False
    target = fixtures.ids_for(material["content"], material["codec"])
    assert target[0] == 1 and target[-1] == 2 and len(target) <= 512
    exposed_values, exposed_options = arguments(material, checkpoint,
        prefix=target[:-1], max_new_tokens=1, prefix_origin="target_derived_label")
    exposed = subject.generate_compact_content_v1(*exposed_values, **exposed_options)
    assert exposed["status"] == "complete" and exposed["reason"] is None
    assert exposed["initial_prefix_ids"] == target[:-1]
    assert exposed["selected_token_ids"] == [2]
    assert exposed["generated_ids"] == target
    assert exposed["emitted_token_count"] == 1 and exposed["total_token_count"] == len(target)
    assert exposed["score_call_count"] == exposed["numerical_forward_count"] == 1
    assert len(exposed["trace"]) == 1
    assert exposed["trace"][0]["selection"]["selected_token_id"] == 2
    assert exposed["final_decoding"]["status"] == "valid_candidate"
    assert exposed["exposure"]["teacher_forcing"] is True
    assert exposed["exposure"]["target_access"] is True
    assert exposed["exposure"]["encoder_sha256"] is None
    assert exposed["exposure"]["source_encoder_authenticated"] is False
    assert checkpoint["compact_training_steps"] == 0
    case = fixtures.make_case(material, ids=("one", "unobserved"))
    adapted = adapter(exposed, exposed_values, exposed_options, case)
    assert adapted["generation_sha256"] == adapted["generation_report_sha256"] == digest(exposed)
    assert adapted["population_sha256"] == sha(case["population_raw"])
    assert adapted["occurrence_id"] == "one"
    assert adapted["predictions"]["schema"] == batch.CONTENT_PREDICTIONS_SCHEMA
    assert adapted["predictions"]["rows"] == [adapted["prediction_row"]]
    observed = adapted["prediction_row"]
    assert observed["generated_ids"] == target
    assert observed["generated_ids_sha256"] == digest(target)
    assert observed["id"] == "one"
    assert observed["source_sha256"] == case["population"]["rows"][0]["source_sha256"]
    assert observed["context_sha256"] == case["population"]["rows"][0]["context_sha256"]
    assert observed["content_context_sha256"] == exposed_options["expected_context_sha256"]
    assert observed["content_context_origin"] == "target_derived_label"
    assert observed["teacher_forcing"] is observed["target_access"] is True
    declared = adapted["predictions"]["generation"]
    assert declared["kind"] == "decoder_declared" and declared["latent_dimension"] == 384
    assert declared["checkpoint_sha256"] == digest(checkpoint)
    assert declared["encoder_sha256"] is None
    result = evaluate_adapter(adapted, case)
    assert result["population"]["ordered_ids"] == ["one", "unobserved"]
    assert result["coverage"]["missing_ids"] == ["unobserved"]
    assert sum(result["terminal_counts"].values()) == 2
    assert result["terminal_counts"]["unverifiable_generation"] == 1
    assert result["terminal_counts"]["missing"] == 1
    assert result["terminal_counts"]["compared"] == 0
    assert result["valid_typed_output"]["count"] == 0
    assert "generation_decoder_encoder_invalid" in result["generation_issues"]
    assert result["observation_ledger"][0]["content_decoding"]["status"] == "valid_candidate"
    assert result["observation_ledger"][0]["raw_observation"]["generated_ids"] == target
    assert all(row["pair_diagnostic"] is None for row in result["occurrences"])
    for report in (bos, exposed, adapted, result):
        no_authority(report)
    population_raw, references_raw, _ = fixtures.legacy.originals(case)[0]
    evidence = {"schema": "legal-compact-content-generation-engineering-evidence/v1",
        "bos_seeded": {"originals": original_payload(bos_values, bos_options), "generation": bos},
        "exposed_eos_completion": {"originals": original_payload(exposed_values, exposed_options),
            "generation": exposed, "adapter": adapted, "batch_evaluation": result,
            "population_utf8": population_raw.decode("utf-8"),
            "references_utf8": references_raw.decode("utf-8")},
        "model_executed": True, "training_executed": False, "compact_optimizer_executed": False,
        "source_encoder_authenticated": False, "held_out_convergence_proven": False,
        "conditioning_origin": "arbitrary_authored_fixture_vector",
        "head_is_compact_trained": False, "prefix_assisted_completion": True,
        "statutory_or_held_out_accuracy_claimed": False}
    raw = wire(evidence)
    assert 0 < len(raw) <= 16 * 1024 * 1024
    destination = tmp_path / "compact-generation-engineering-evidence.json"
    destination.write_bytes(raw)
    assert destination.read_bytes() == raw


@pytest.mark.parametrize("pin", ["expected_generation_sha256", "expected_population_sha256"])
def test_batch_adapter_requires_independent_generation_and_population_originals(material, checkpoint, monkeypatch, pin):
    values, options = arguments(material, checkpoint, max_new_tokens=2)
    report = subject.generate_compact_content_v1(*values, **options)
    case = fixtures.make_case(material)
    with pytest.raises(ValueError):
        adapter(report, values, options, case, **{pin: "0" * 64})


def test_independent_report_pin_refuses_before_numerical_regeneration(material, checkpoint, monkeypatch):
    values, options = arguments(material, checkpoint, max_new_tokens=2)
    report = subject.generate_compact_content_v1(*values, **options)
    monkeypatch.setattr(head, "score_compact_content_head_v1",
                        lambda *args, **kwargs: pytest.fail("regenerated before independent report hash check"))
    with pytest.raises(ValueError):
        validate(report, values, options, expected_report_sha256="0" * 64)


def test_complete_trace_bound_refuses_without_returning_a_truncated_receipt(material, checkpoint, monkeypatch):
    values, options = arguments(material, checkpoint, max_new_tokens=2)
    report = subject.generate_compact_content_v1(*values, **options)
    # Labelled bound seam: lower the whole generation-report serialization
    # limit without changing public head/selector outputs or dropping a step.
    original_wire = subject._wire
    report_limit = len(wire(report)) - 1
    def bounded(value, *args, **kwargs):
        if type(value) is dict and value.get("schema") == "legal-compact-content-generation/v1":
            return original_wire(value, report_limit)
        return original_wire(value, *args, **kwargs)
    monkeypatch.setattr(subject, "_wire", bounded)
    with pytest.raises(ValueError):
        subject.generate_compact_content_v1(*values, **options)


def test_complete_original_input_bound_refuses_before_any_head_call(material, checkpoint, monkeypatch):
    values, options = arguments(material, checkpoint)
    monkeypatch.setattr(subject, "MAX_INPUT_BYTES", 1)
    monkeypatch.setattr(head, "score_compact_content_head_v1",
                        lambda *args, **kwargs: pytest.fail("input overflow reached numerical head"))
    with pytest.raises(ValueError):
        subject.generate_compact_content_v1(*values, **options)


def test_genuine_head_callback_cannot_change_original_conditioning_mid_operation(material, checkpoint, monkeypatch):
    values, options = arguments(material, checkpoint, max_new_tokens=2)
    original = head.score_compact_content_head_v1
    observed = []
    def changed(*args, **kwargs):
        report = original(*args, **kwargs)
        assert report["numerical_forward_executed"] is True
        observed.append(report)
        values[1][0] += 1
        return report
    monkeypatch.setattr(head, "score_compact_content_head_v1", changed)
    with pytest.raises(ValueError):
        subject.generate_compact_content_v1(*values, **options)
    assert observed


def test_trace_outputs_and_inputs_do_not_share_mutable_score_or_prefix_values(material, checkpoint):
    values, options = arguments(material, checkpoint, max_new_tokens=2)
    report = subject.generate_compact_content_v1(*values, **options)
    snapshot = deepcopy(report)
    values[1][0] = 123.
    values[2].append(0)
    assert report == snapshot
    report["trace"][0]["logits"][0] += 1
    report["generated_ids"].append(999)
    assert 999 not in values[2]
    assert report["trace"][0]["prefix_ids"] == snapshot["trace"][0]["prefix_ids"]
