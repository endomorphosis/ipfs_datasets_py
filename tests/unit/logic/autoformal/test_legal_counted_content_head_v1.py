"""Actual counted28 CPU engineering, with one exposed authored label only."""
from copy import deepcopy
import hashlib
import inspect
import json
import math

import pytest
import torch

from ipfs_datasets_py.logic.formalization.autoencoder import legal_counted_content_head_v1 as subject
from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_head_v1 as base

CONFIG = dict(hidden_size=8, token_embedding_dim=8, projection_width=4, seed=1729)
VECTOR = [1.] + [0.] * 383
CONTEXT = b'{"distinctness":"builtin_object_identity","frame":{"event":{"sort":"EventFrame","variable":"event"},"policy":"per_event_and_time","time":{"semantics":"arbitrary_index_without_order","sort":"TimeFrame","variable":"time"}},"maximum":3,"membership":{"argument_roles":["object","event","time"],"symbol":"Member"},"object_variables":["x0","x1","x2","x3"],"predicate":{"domain":["Object","EventFrame","TimeFrame"],"name":"Member","range":"Bool"},"schema":"legal-counted-compact-context/v1","sorts":["Object","EventFrame","TimeFrame"]}'
IDS = [1,26,13,23,10,16,14,23,24,8,16,17,16,3,16,24,8,16,18,16,5,16,24,8,16,19,16,4,16,24,8,16,20,16,4,16,24,8,16,21,16,4,16,24,8,16,22,16,4,16,24,9,16,24,6,16,24,6,16,24,6,16,24,12,16,17,16,24,24,15,16,19,25,16,24,15,16,17,25,16,24,15,16,18,25,25,25,16,24,12,16,17,16,24,24,15,16,20,25,16,24,15,16,17,25,16,24,15,16,18,25,25,25,25,16,24,12,16,17,16,24,24,15,16,21,25,16,24,15,16,17,25,16,24,15,16,18,25,25,25,25,16,24,12,16,17,16,24,24,15,16,22,25,16,24,15,16,17,25,16,24,15,16,18,25,25,25,25,16,24,11,16,24,11,16,24,11,16,24,11,16,24,11,16,24,7,16,24,15,16,19,25,16,24,15,16,20,25,25,16,24,7,16,24,15,16,19,25,16,24,15,16,21,25,25,25,16,24,7,16,24,15,16,19,25,16,24,15,16,22,25,25,25,16,24,7,16,24,15,16,20,25,16,24,15,16,21,25,25,25,16,24,7,16,24,15,16,20,25,16,24,15,16,22,25,25,25,16,24,7,16,24,15,16,21,25,16,24,15,16,22,25,25,25,25,25,25,25,25,25,25,27,2]


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def digest(value):
    return sha(wire(value))


@pytest.fixture(scope="module", autouse=True)
def cpu_scope():
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    try:
        yield
    finally:
        torch.set_num_threads(previous)


@pytest.fixture(scope="module")
def checkpoint():
    return subject.create_counted_content_head_v1(config=CONFIG)


def score(value, vector=None, prefix=None, **changes):
    options = dict(expected_checkpoint_sha256=digest(value))
    options.update(changes)
    return subject.score_counted_content_head_v1(value, VECTOR if vector is None else vector,
        [1] if prefix is None else prefix, **options)


def evaluate(value, ids=None, context=CONTEXT, **changes):
    options = dict(expected_checkpoint_sha256=digest(value), expected_context_sha256=sha(context))
    options.update(changes)
    return subject.evaluate_counted_content_head_v1(value, VECTOR, IDS if ids is None else ids, context, **options)


def forbidden(*args, **kwargs):
    pytest.fail("invalid counted input reached actual numerical forward")


def no_authority(value):
    assert value["authority"] and all(flag is False for flag in value["authority"].values())
    assert type(value["training_mask"]) is int and value["training_mask"] == 0
    assert type(value["evaluation_gold_mask"]) is int and value["evaluation_gold_mask"] == 0
    assert value["counted_training_steps"] == 0


def test_counted_seeded_head_uses_exact_declared_shapes_and_preserves_rng(checkpoint):
    before = torch.get_rng_state().clone()
    repeated = subject.create_counted_content_head_v1(config=CONFIG)
    assert repeated == checkpoint and torch.equal(before, torch.get_rng_state())
    assert checkpoint["codec"]["vocabulary_size"] == 28
    assert checkpoint["input_role"] == "unverified_caller_supplied_conditioning_vector"
    assert checkpoint["spec"]["identity"]["input"]["space"] == "raw_native_gte_small384"
    assert len(checkpoint["model_state"]) == 13
    for name, shape in checkpoint["spec"]["identity"]["tensor_shapes"].items():
        assert list(torch.tensor(checkpoint["model_state"][name]).shape) == shape
    assert checkpoint["optimizer_state_included"] is False
    no_authority(checkpoint)


def test_counted_raw_28_scores_are_condition_dependent_and_target_free(checkpoint):
    before = torch.get_rng_state().clone()
    first = score(checkpoint)
    second = score(checkpoint, vector=[-1.] + [0.] * 383)
    assert len(first["logits"]) == 28 and all(math.isfinite(x) for x in first["logits"])
    assert first["logits"] != second["logits"]
    assert first["output_shape"] == [1, 1, 28]
    assert first["grammar_mask_applied"] is False and first["grammatical_prefix_verified"] is False
    assert first["raw_argmax_token_id"] == max(range(28), key=lambda i: first["logits"][i])
    assert first["numeric_conditioning"] == VECTOR
    assert torch.equal(before, torch.get_rng_state())
    assert not {"target_ids", "context_raw", "identity_raw"} & set(inspect.signature(subject.score_counted_content_head_v1).parameters)
    no_authority(first)


def test_counted_teacher_forced_unmasked_loss_matches_independent_torch_oracle(checkpoint, tmp_path):
    before = torch.get_rng_state().clone()
    result = evaluate(checkpoint)
    logits = torch.tensor(result["logits"], dtype=torch.float64)
    labels = torch.tensor(IDS[1:], dtype=torch.long)
    losses = torch.nn.functional.cross_entropy(logits, labels, reduction="none")
    assert result["output_shape"] == [1, 292, 28] and list(logits.shape) == [292, 28]
    assert result["input_ids"] == IDS[:-1] and result["label_ids"] == IDS[1:]
    assert result["predicted_tokens"] == 292 and result["eos_included_in_loss"] is True
    assert result["token_losses"] == pytest.approx(losses.tolist(), rel=1e-12, abs=1e-12)
    assert result["mean_cross_entropy"] == pytest.approx(losses.mean().item(), rel=1e-12)
    assert result["prediction_ids"] == logits.argmax(-1).tolist()
    assert result["exact_teacher_forced_token_matches"] == int((logits.argmax(-1) == labels).sum())
    assert 0 < result["mean_cross_entropy"] < 10 and result["exact_teacher_forced_sequence_match"] is False
    assert result["grammar_mask_applied"] is False and result["generation_executed"] is False
    assert result["target_context_role"] == "label_only_target_derived" and result["target_population_size"] == 1
    assert result["optimizer_executed"] is False and torch.equal(before, torch.get_rng_state())
    no_authority(result)
    (tmp_path / "authored-counted28-teacher-forced-observation.json").write_bytes(wire(result))
    (tmp_path / "seeded-counted28-checkpoint.json").write_bytes(wire(checkpoint))


def test_counted_restore_and_independent_transport_preserve_every_weight_and_logit(checkpoint):
    original = deepcopy(checkpoint)
    raw = subject.counted_content_head_bytes_v1(checkpoint, expected_checkpoint_sha256=digest(checkpoint))
    restored = subject.load_counted_content_head_v1(raw, expected_raw_sha256=sha(raw))
    assert restored == checkpoint and subject.counted_content_head_sha256(restored) == digest(checkpoint)
    assert score(restored) == score(checkpoint)
    whitespace = json.dumps(checkpoint, indent=1).encode()
    assert sha(whitespace) != digest(checkpoint)
    assert subject.load_counted_content_head_v1(whitespace, expected_raw_sha256=sha(whitespace)) == checkpoint
    assert checkpoint == original


@pytest.mark.parametrize("prefix", [[], [True], [1.], [0], [2], [1, 1], [1, 0], [1, 2], [1, 28], [1] + [3] * 511],
                         ids=["empty", "bool", "float", "pad", "eos", "interior_bos", "interior_pad", "interior_eos", "outside_vocab", "over_budget"])
def test_counted_malformed_prefix_is_refused_before_forward(checkpoint, monkeypatch, prefix):
    monkeypatch.setattr(subject, "_forward", forbidden)
    with pytest.raises(ValueError):
        score(checkpoint, prefix=prefix)


@pytest.mark.parametrize("vector", [[], [0.] * 383, [True] + [0.] * 383, [float("nan")] + [0.] * 383, [1e100] + [0.] * 383],
                         ids=["empty", "short", "bool", "nan", "overflow"])
def test_counted_bad_conditioning_is_refused_before_forward(checkpoint, monkeypatch, vector):
    monkeypatch.setattr(subject, "_forward", forbidden)
    with pytest.raises(ValueError):
        score(checkpoint, vector=vector)


@pytest.mark.parametrize("damage", ["width537", "missing_tensor", "integer_scalar", "nonexact_float32", "codec", "spec_bool_alias", "init_bool_alias", "profile", "authority", "optimizer", "torch_version"])
def test_counted_resealed_incompatible_checkpoint_is_refused(checkpoint, damage):
    value = deepcopy(checkpoint)
    if damage == "width537":
        value["model_state"]["output.bias"] += [0.] * (537 - 28)
    elif damage == "missing_tensor":
        del value["model_state"]["condition.bias"]
    elif damage in ("integer_scalar", "nonexact_float32"):
        value["model_state"]["condition.bias"][0] = 0 if damage == "integer_scalar" else .1
    elif damage == "codec":
        value["codec"]["vocabulary"][3], value["codec"]["vocabulary"][4] = value["codec"]["vocabulary"][4], value["codec"]["vocabulary"][3]
        value["codec_sha256"] = digest(value["codec"])
    elif damage == "spec_bool_alias":
        value["spec"]["model_calls"] = False
    elif damage == "init_bool_alias":
        value["initialization"]["fresh_optimizer_required"] = 1
    elif damage == "profile":
        value["profile"] = base.PROFILE
    elif damage == "authority":
        value["authority"]["training_qualified"] = True
    elif damage == "optimizer":
        value["optimizer_state_included"] = True
    else:
        value["torch_version"] = "not-the-installed-runtime"
    value["weights_sha256"] = digest(value["model_state"])
    with pytest.raises(ValueError):
        subject.validate_counted_content_head_v1(value, expected_checkpoint_sha256=digest(value))


@pytest.mark.parametrize("damage", ["truncated", "early_eos", "interior_pad", "bool", "out_of_range", "over512", "context", "context_pin"])
def test_counted_bad_complete_labels_refused_by_genuine_decoder_before_forward(checkpoint, monkeypatch, damage):
    monkeypatch.setattr(subject, "_forward", forbidden)
    ids, context, changes = list(IDS), CONTEXT, {}
    if damage == "truncated": ids.pop()
    elif damage == "early_eos": ids = [1, 2]
    elif damage == "interior_pad": ids[4] = 0
    elif damage == "bool": ids[4] = True
    elif damage == "out_of_range": ids[4] = 28
    elif damage == "over512": ids = [1] + [3] * 511 + [2]
    elif damage == "context": context = b"{}"
    else: changes["expected_context_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        evaluate(checkpoint, ids=ids, context=context, **changes)


@pytest.mark.parametrize("raw", [b"not json", b"[]", b"{}", b'{"schema":1,"schema":2}', b'{"value":NaN}'],
                         ids=["non_json", "array", "empty_object", "duplicate", "nonfinite"])
def test_counted_transport_refuses_malformed_duplicate_and_nonfinite_json(raw):
    with pytest.raises(ValueError):
        subject.load_counted_content_head_v1(raw, expected_raw_sha256=sha(raw))


def test_counted_independent_pins_and_source_fences_refuse_drift(checkpoint, monkeypatch):
    with pytest.raises(ValueError):
        score(checkpoint, expected_checkpoint_sha256="0" * 64)
    with pytest.raises(ValueError):
        subject.load_counted_content_head_v1(wire(checkpoint), expected_raw_sha256="0" * 64)
    original = subject._OWNER_SPECS
    monkeypatch.setattr(subject, "_OWNER_SPECS", (*original[:1],
        (original[1][0], original[1][1], "0" * 64), original[2]))
    with pytest.raises(ValueError):
        score(checkpoint)


def test_counted_caller_mutation_during_serialization_cannot_escape_closing_fence(checkpoint, monkeypatch):
    vector = list(VECTOR)
    original = base._detach
    def mutate(value, maximum):
        vector[0] = -1.
        return original(value, maximum)
    monkeypatch.setattr(base, "_detach", mutate)
    with pytest.raises(ValueError):
        score(checkpoint, vector=vector)


def test_counted_hash_helper_refuses_adapter_self_source_pin_drift(checkpoint, monkeypatch):
    monkeypatch.setattr(subject, "_SELF_SHA", "0" * 64)
    with pytest.raises(ValueError):
        subject.counted_content_head_sha256(checkpoint)
