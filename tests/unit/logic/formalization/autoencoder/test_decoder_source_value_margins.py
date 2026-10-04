"""Synthetic causal rollouts and numerical attribution; no fidelity claims."""
from copy import deepcopy
import inspect
import json
import random
import re
import time
import types

import pytest

torch = pytest.importorskip("torch")
from ipfs_datasets_py.logic.formalization.autoencoder import decoder_source_value_margins as subject
from ipfs_datasets_py.logic.formalization.autoencoder import source_value_decoder_experiment as values
from ipfs_datasets_py.logic.formalization.autoencoder import decoder_cardinality_experiment as count
from ipfs_datasets_py.logic.formalization.autoencoder import decoder_distillation_experiment as core
from ipfs_datasets_py.logic.formalization.autoencoder import decoder_distillation_experiment_v2 as adapter
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_latent_formula as numerical


@pytest.fixture(autouse=True)
def one_cpu():
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    yield
    torch.set_num_threads(previous)


def rule(**updates):
    return dict(dict(action="preserve", actor="agency", modality="O", object="report",
        conditions=[], exceptions=[], temporal=[]), **updates)


def encode(codec, target):
    text = json.dumps(target, sort_keys=True, separators=(",", ":"))
    tokens = re.findall(r'"(?:[^"\\]|\\.)*"|[{}\[\],:]|true|false|[0-9]+', text)
    return [1] + [codec["target_vocabulary"].index(t) for t in tokens] + [2]


def prepared(*, target=None, programs=None, feature="projected_source", n=2, cap=512, scripted=True):
    target = {"rules": [rule()]} if target is None else target
    strings = [*count.FIELDS, "rules", "O", "P", "F", "agency", "report", "preserve", "deliver", "archive", "a", "b"]
    codec = dict(schema="typed-json-lexical/v1", target_vocabulary=["<pad>", "<bos>", "<eos>"] +
        sorted(set([json.dumps(s) for s in strings] + list('{}[],:'))))
    raw = numerical._model({"dimension": 384}, codec,
        dict(seed=42, hidden_size=8, token_embedding_dim=8, projection_width=2))
    persistent = adapter.bind_persistent_model(raw, dimension=384, conditioning="every_step")
    if scripted:
        scripted_ids = [encode(codec, target)[1:]] if programs is None else programs(codec)
        def scripted_logits(self, tokens, state):
            hidden, source, position = state
            logits = torch.full((*tokens.shape, len(codec["target_vocabulary"])), -10., dtype=torch.float32)
            for batch in range(len(tokens)):
                program = scripted_ids[batch % len(scripted_ids)]
                for offset in range(tokens.shape[1]):
                    index = int(position[batch]) + offset
                    chosen = program[index] if index < len(program) else 2
                    logits[batch, offset, chosen] = 10.
            return logits, (hidden, source, position + tokens.shape[1])
        persistent.next_logits = types.MethodType(scripted_logits, persistent)
    cardinality = count.bind_cardinality_model(persistent, codec=codec, guide_boundary=False)
    model = values.bind_source_value_model(cardinality, codec=codec, feature_kind=feature)
    rows, references = [], []
    for index in range(n):
        row = dict(id=f"row-{index}", source_text=f"Synthetic source {index}",
            input=[(index + 1) / 100.] * 384, target_ids=encode(codec, target))
        rows.append(row)
        references.append(dict(id=row["id"], source_text=row["source_text"], target=deepcopy(target), clause_count=len(target["rules"])))
    options = dict(codec=codec, input_transform=dict(mode="none", mean=[0.] * 384, scale=1., origin="training_only"),
        lineage=dict(teacher_checkpoint_sha256="a"*64, teacher_codec_sha256=core.digest(codec),
            input_provenance_sha256="b"*64, domain="legal_ir", teacher_lineage="synthetic-private", student_lineage="synthetic-trace",
            teacher_output_limit=cap, student_role="source_conditioned_decoder"),
        validate_rule=lambda target: dict(valid=all(set(r) == set(count.FIELDS) for r in target["rules"])),
        validator_id="synthetic-structure-only", max_target_tokens=cap, max_seconds=30., batch_size=n)
    return model, rows, references, options


def expected(model, rows, options):
    working = deepcopy(model).eval()
    data = torch.tensor([row["input"] for row in rows], dtype=torch.float32)
    transform = options["input_transform"]
    data = (data-torch.tensor(transform["mean"], dtype=torch.float32))/transform["scale"]
    with torch.inference_mode():
        _, tokens, statuses = core._greedy(torch, working, data, options["max_target_tokens"],
            len(options["codec"]["target_vocabulary"]), time.monotonic()+20.)
    return [dict(id=row["id"], token_ids=token, generation_status=status, eos_reached=status == "eos")
        for row, token, status in zip(rows, tokens, statuses)]


def trace(model, rows, references, options, **extras):
    predictions = extras.pop("expected_predictions", None)
    return subject.trace_predictions(model, rows, references,
        expected_predictions=expected(model, rows, options) if predictions is None else predictions, **options, **extras)


@pytest.mark.parametrize("feature", ["projected_source", "inherited_conditioning"])
def test_real_model_replay_matches_original_core_and_preserves_every_caller_state(feature):
    model, rows, references, options = prepared(scripted=False, feature=feature, cap=64)
    model.train()
    model.body.eval()
    model.source_value_head.weight.grad = torch.ones_like(model.source_value_head.weight)
    model.body.body.body.projection_down.weight.requires_grad_(False)
    before, grads = core.tensor_digest(model), subject.gradient_digest(model)
    flags = [(name, p.requires_grad) for name, p in model.named_parameters()]
    modes = [(name, m.training) for name, m in model.named_modules()]
    inputs = deepcopy((rows, references, options["codec"], options["input_transform"]))
    torch_rng, python_rng = torch.get_rng_state().clone(), random.getstate()
    result = trace(model, rows, references, options)
    assert result["report"]["decomposition_exact"] and result["report"]["archived_predictions_match"]
    assert core.tensor_digest(model) == before and subject.gradient_digest(model) == grads
    assert torch.equal(torch_rng, torch.get_rng_state()) and python_rng == random.getstate()
    assert flags == [(name, p.requires_grad) for name, p in model.named_parameters()]
    assert modes == [(name, m.training) for name, m in model.named_modules()]
    assert (rows, references, options["codec"], options["input_transform"]) == inputs
    assert all(result["report"][key] is False for key in subject.FALSE)
    assert result["report"]["generation_executed"]


def test_exact_rollout_has_no_fabricated_divergence_or_reference_on_other_captures():
    model, rows, references, options = prepared()
    result = trace(model, rows, references, options)
    for row in result["rows"]:
        assert row["first_divergence"]["status"] == "exact_with_explicit_eos"
        assert row["first_divergence"]["position"] is None
        assert {reason for capture in row["captures"] for reason in capture["reasons"]} == {"first_scalar_site", "first_rule_boundary"}
        assert all(capture["expected_annotation"] is None for capture in row["captures"])
    assert result["report"]["aggregates"]["events"]["inherited_choice_changed"] == 0
    assert result["report"]["aggregates"]["events"]["active_residual_sites"] == 8
    assert result["report"]["aggregates"]["events"]["nonzero_residual_sites"] == 0


def test_correct_source_preference_can_be_overruled_by_inherited_logits():
    wrong = {"rules": [rule(action="deliver")]}
    model, rows, references, options = prepared(programs=lambda codec: [encode(codec, wrong)[1:]])
    codec = options["codec"]
    expected_id = codec["target_vocabulary"].index('"preserve"')
    with torch.no_grad():
        bias = model.source_value_head.bias.reshape(8, 4, -1)
        bias[0, values.SOURCE_FIELDS.index("action"), expected_id] = 3.
    result = trace(model, rows, references, options)
    for row in result["rows"]:
        first = row["first_divergence"]
        assert first["expected_annotation"]["kind"] == "scalar_value" and first["expected_annotation"]["field"] == "action"
        capture = next(c for c in row["captures"] if "first_divergence" in c["reasons"])
        assert capture["reasons"] == ["first_divergence", "first_scalar_site"]
        assert capture["scores"]["inherited"]["expected_minus_emitted"] == -20.
        assert capture["scores"]["source_residual"]["expected_minus_emitted"] == 3.
        assert capture["scores"]["combined"]["expected_minus_emitted"] == -17.
        assert capture["scores"]["source_residual"]["expected_rank"] == 1
        assert capture["event"]["source_winner_token_id"] == expected_id
        assert not capture["event"]["inherited_choice_changed"]
    assert result["report"]["aggregates"]["active_scalar_first_divergence"]["source_prefers_expected_but_emitted_other"] == 2


def test_wrong_source_can_override_correct_inherited_choice_without_hidden_mask():
    model, rows, references, options = prepared()
    emitted = options["codec"]["target_vocabulary"].index('"deliver"')
    with torch.no_grad(): model.source_value_head.bias.reshape(8, 4, -1)[0, 1, emitted] = 30.
    result = trace(model, rows, references, options)
    first = result["report"]["aggregates"]["active_scalar_first_divergence"]
    assert first["inherited_prefers_expected"] == first["source_winner_emitted"] == 2
    assert first["source_prefers_expected"] == 0
    assert result["report"]["aggregates"]["events"]["inherited_choice_changed"] == 2


def test_syntax_error_makes_subsequent_prefix_guidance_inactive():
    def broken(codec):
        program = encode(codec, {"rules": [rule()]})[1:]
        program[0] = codec["target_vocabulary"].index("]")
        return [program]
    model, rows, references, options = prepared(programs=broken)
    result = trace(model, rows, references, options)
    for row in result["rows"]:
        assert row["first_divergence"]["position"] == 1
        assert row["first_divergence"]["expected_annotation"]["kind"] == "syntax"
        assert all(event["guidance_status"] == "invalid_prefix" for event in row["events"][1:])
        assert not any(event["source_residual_nonzero"] for event in row["events"])
        assert len(row["captures"]) == 1


def test_ninth_generated_rule_is_beyond_head_slots_and_remains_unforced():
    target = {"rules": [rule()] * 9}
    model, rows, references, options = prepared(target=target)
    result = trace(model, rows, references, options)
    for row in result["rows"]:
        beyond = [event for event in row["events"] if event["guidance_status"] == "beyond_slot_limit"]
        assert len(beyond) == 4 and all(event["rule_slot"] == 8 for event in beyond)
        assert all(event["source_winner_token_id"] is None for event in beyond)
        assert row["prediction"]["eos_reached"]


@pytest.mark.parametrize("special", [0, 1, 2])
def test_actual_special_token_is_identified_and_inactive_rows_still_replay(special):
    model, rows, references, options = prepared(programs=lambda codec: [[special], encode(codec, {"rules": [rule()]})[1:]])
    result = trace(model, rows, references, options)
    first, second = result["rows"]
    assert len(first["events"]) == 1 and len(second["events"]) > 1
    assert first["first_divergence"]["emitted_token_id"] == special
    assert first["prediction"]["generation_status"] == ("eos" if special == 2 else "invalid_special_token")
    assert second["first_divergence"]["status"] == "exact_with_explicit_eos"


def test_output_limit_does_not_fabricate_eos_or_run_one_extra_step():
    model, rows, references, options = prepared(programs=lambda codec: [[codec["target_vocabulary"].index("{")] * 100], cap=64)
    result = trace(model, rows, references, options)
    assert all(len(row["events"]) == len(row["prediction"]["token_ids"]) == 63 for row in result["rows"])
    assert all(row["prediction"]["generation_status"] == "output_limit" and not row["prediction"]["eos_reached"] for row in result["rows"])


def test_source_shuffle_binding_is_verified_without_changing_target_or_source_identity():
    model, originals, references, options = prepared()
    actual = deepcopy(originals)
    actual[0]["input"], actual[1]["input"] = actual[1]["input"], actual[0]["input"]
    control = dict(kind="source_shuffle", source_assignment={"row-0": "row-1", "row-1": "row-0"})
    result = trace(model, actual, references, options, source_rows=originals, control=control)
    assert result["report"]["source_assignment_verified"]
    assert [r["assigned_source_id"] for r in result["rows"]] == ["row-1", "row-0"]
    actual[0]["input"][0] += 1
    with pytest.raises(ValueError, match="assigned original"):
        trace(model, actual, references, options, source_rows=originals, control=control)


def test_references_change_posthoc_alignment_without_entering_rollout(monkeypatch):
    model, rows, references, options = prepared()
    archived = expected(model, rows, options)
    original_rollout = subject._rollout
    calls = []
    def spy(torch, model, data, **kwargs):
        assert isinstance(data, torch.Tensor) and set(kwargs) == {"cap", "size", "check"}
        calls.append(tuple(data.flatten().tolist()))
        return original_rollout(torch, model, data, **kwargs)
    monkeypatch.setattr(subject, "_rollout", spy)
    first = trace(model, rows, references, options, expected_predictions=archived)
    for row, reference in zip(rows, references):
        reference["target"]["rules"][0]["object"] = "archive"
        row["target_ids"] = encode(options["codec"], reference["target"])
    second = trace(model, rows, references, options, expected_predictions=archived)
    assert calls[0] == calls[1]
    assert [row["prediction"] for row in first["rows"]] == [row["prediction"] for row in second["rows"]]
    assert second["rows"][0]["first_divergence"]["expected_annotation"]["field"] == "object"
    assert "references" not in inspect.signature(original_rollout).parameters


@pytest.mark.parametrize("tamper", ["tokens", "status", "id", "missing", "duplicate"])
def test_archived_drift_never_receives_complete_report(tamper):
    model, rows, references, options = prepared()
    archive = expected(model, rows, options)
    if tamper == "tokens": archive[0]["token_ids"][0] = options["codec"]["target_vocabulary"].index("]")
    elif tamper == "status": archive[0].update(generation_status="output_limit", eos_reached=False)
    elif tamper == "id": archive[0]["id"] = "unknown"
    elif tamper == "missing": archive.pop()
    else: archive[1]["id"] = archive[0]["id"]
    with pytest.raises(ValueError):
        trace(model, rows, references, options, expected_predictions=archive)


def test_full_target_token_identity_is_required():
    model, rows, references, options = prepared()
    references[0]["target"]["rules"][0]["object"] = "archive"
    with pytest.raises(ValueError, match="target tokens"):
        trace(model, rows, references, options)


def test_nonidentity_training_transform_replays_exactly():
    model, rows, references, options = prepared(scripted=False, cap=64)
    options["input_transform"] = dict(mode="center_rms", mean=[.1]*384, scale=.5, origin="training_only")
    assert trace(model, rows, references, options)["report"]["archived_predictions_match"]


def test_memory_budget_refuses_before_rollout(monkeypatch):
    model, rows, references, options = prepared()
    archive = expected(model, rows, options)
    monkeypatch.setattr(subject, "_rollout", lambda *a, **k: pytest.fail("should refuse before rollout"))
    with pytest.raises(ValueError, match="memory estimate"):
        trace(model, rows, references, options, expected_predictions=archive, max_memory_bytes=1048576)


@pytest.mark.parametrize("when", ["rollout", "finally"])
def test_deadline_includes_final_integrity_checks_and_restores_caller(monkeypatch, when):
    model, rows, references, options = prepared()
    archive = expected(model, rows, options)
    before, rng = core.tensor_digest(model), torch.get_rng_state().clone()
    clock = [0.]
    monkeypatch.setattr(subject.time, "monotonic", lambda: clock[0])
    if when == "rollout":
        original = subject._rollout
        def expire(*args, **kwargs):
            value = original(*args, **kwargs)
            clock[0] = 31.
            return value
        monkeypatch.setattr(subject, "_rollout", expire)
    else:
        original, calls = core.tensor_digest, []
        def expire(value):
            calls.append(1)
            result = original(value)
            if len(calls) == 3: clock[0] = 31.
            return result
        monkeypatch.setattr(core, "tensor_digest", expire)
    with pytest.raises(TimeoutError):
        trace(model, rows, references, options, expected_predictions=archive)
    assert core.tensor_digest(model) == before and torch.equal(rng, torch.get_rng_state())


def test_raw_vectors_reproduce_score_ranks_and_full_sum():
    model, rows, references, options = prepared(programs=lambda codec: [encode(codec, {"rules": [rule(action="deliver")]})[1:]])
    result = trace(model, rows, references, options)
    for row in result["rows"]:
        for capture in row["captures"]:
            raw = capture["raw_logits"]
            assert torch.equal(torch.tensor(raw["inherited"]) + torch.tensor(raw["source_residual"]), torch.tensor(raw["combined"]))
            for key, vector in raw.items():
                winner = max(range(len(vector)), key=vector.__getitem__)
                assert capture["scores"][key]["winner_token_id"] == winner
    assert result["report"]["diagnostic_rows_sha256"] == core.digest(result["rows"])
