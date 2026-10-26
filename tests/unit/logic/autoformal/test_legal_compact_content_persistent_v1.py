"""Finite persistent-source mechanics on the existing four authored384 fixtures.

Only the owned native qualification runner may execute these two cases. Neither
the reused fixture targets nor caller-supplied vectors establish statutory
meaning, native encoder compatibility, permitted context or held-out accuracy.
"""
from copy import deepcopy
import hashlib
import json
import math
import os

import pytest
import torch

from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_head_v1 as head
from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_persistent_v1 as subject
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_latent_formula as numerical
from tests.unit.logic.autoformal import test_legal_compact_content_training_v2 as authored


SOURCE_SPACE = "authored-varied-unverified384/persistent-mechanics-v1"
PREFIX = [1, 3, 4]  # Independently fixed scoring IDs; no reference-target prefix.
COUNTERS = ("gru_constructions", "state_restores", "adam_constructions", "gru_forwards",
    "cross_entropy_calls", "autograd_grad_calls", "backward_calls", "clip_calls", "optimizer_updates")


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False).encode("utf-8")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def digest(value):
    return sha(wire(value))


def exclusive(path, raw):
    with path.open("xb") as stream:
        assert stream.write(raw) == len(raw)
        stream.flush()
        os.fsync(stream.fileno())


def no_authority(value):
    assert value["authority"] and all(flag is False for flag in value["authority"].values())
    assert type(value["training_mask"]) is int and value["training_mask"] == 0
    assert type(value["evaluation_gold_mask"]) is int and value["evaluation_gold_mask"] == 0


def max_difference(a, b):
    assert len(a) == len(b)
    return max(abs(x - y) for left, right in zip(a, b) for x, y in zip(left, right, strict=True))


@pytest.fixture(scope="module", autouse=True)
def one_torch_thread():
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    try:
        yield
    finally:
        torch.set_num_threads(previous)


def _baseline_matrix(parent, vector, prefix):
    """One genuine original body restore/forward, without Adam or selectors."""
    owners = head._owners(numeric=True)
    failure = None
    try:
        model = head._model(parent, owners)
        with torch.inference_mode():
            _, logits = model(torch.tensor([vector], dtype=torch.float32),
                torch.tensor([prefix], dtype=torch.long))
        assert list(logits.shape) == [1, len(prefix), 537]
        return logits[0].tolist()
    except BaseException as error:
        failure = error
        raise
    finally:
        head._finish(failure, lambda: head._closing(owners))


@pytest.mark.parametrize("mode", ["every_step", "first_step"])
def test_persistent_compact_zero_adapter_update_resume_and_prefix_mechanics(mode, tmp_path):
    case = authored._authored_varied_population_v2()
    original_case = deepcopy(case)
    counts = dict.fromkeys(COUNTERS, 0)
    events, cross_entropies, updates, gradients = [], [], [], []
    stage = {"value": "seed"}
    real_init, real_load = torch.nn.GRU.__init__, torch.nn.Module.load_state_dict
    real_adam, real_forward = torch.optim.Adam.__init__, torch.nn.GRU.forward
    real_ce, real_grad = torch.nn.functional.cross_entropy, torch.autograd.grad
    real_backward, real_clip = torch.Tensor.backward, torch.nn.utils.clip_grad_norm_
    real_step = torch.optim.Adam.step

    def observed_init(model, *args, **kwargs):
        result = real_init(model, *args, **kwargs)
        counts["gru_constructions"] += 1
        events.append({"stage": stage["value"], "event": "gru_construction"})
        return result

    def observed_load(model, *args, **kwargs):
        result = real_load(model, *args, **kwargs)
        counts["state_restores"] += 1
        events.append({"stage": stage["value"], "event": "state_restore",
            "parameter_names": list(model.state_dict())})
        return result

    def observed_adam(optimizer, *args, **kwargs):
        result = real_adam(optimizer, *args, **kwargs)
        counts["adam_constructions"] += 1
        events.append({"stage": stage["value"], "event": "adam_construction"})
        return result

    def observed_forward(model, inputs, *args, **kwargs):
        result = real_forward(model, inputs, *args, **kwargs)
        counts["gru_forwards"] += 1
        events.append({"stage": stage["value"], "event": "gru_forward",
            "input_shape": list(inputs.shape), "output_shape": list(result[0].shape)})
        return result

    def observed_ce(logits, labels, *args, **kwargs):
        result = real_ce(logits, labels, *args, **kwargs)
        assert not args and kwargs == {"ignore_index": 0}
        assert list(logits.shape) == [labels.numel(), 537]
        ids, matrix = labels.detach().tolist(), logits.detach().double().tolist()
        assert ids and ids[-1] == 2 and 0 not in ids
        terms = []
        for scores, target in zip(matrix, ids, strict=True):
            maximum = max(scores)
            terms.append(maximum + math.log(math.fsum(math.exp(x - maximum) for x in scores)) - scores[target])
        independent = math.fsum(terms) / len(ids)
        assert math.isclose(float(result.detach()), independent, rel_tol=0., abs_tol=2e-6)
        counts["cross_entropy_calls"] += 1
        cross_entropies.append({"stage": stage["value"], "labels": ids, "logits": matrix,
            "torch_mean": float(result.detach()), "independent_mean": independent})
        return result

    def observed_grad(*args, **kwargs):
        result = real_grad(*args, **kwargs)
        counts["autograd_grad_calls"] += 1
        gradients.append({"stage": stage["value"],
            "shapes": [list(value.shape) for value in result],
            "all_finite": all(bool(torch.isfinite(value).all()) for value in result),
            "squared_norm": math.fsum(float(value.detach().double().square().sum()) for value in result)})
        return result

    def observed_backward(loss, *args, **kwargs):
        counts["backward_calls"] += 1
        return real_backward(loss, *args, **kwargs)

    def observed_clip(*args, **kwargs):
        counts["clip_calls"] += 1
        return real_clip(*args, **kwargs)

    def observed_step(optimizer, *args, **kwargs):
        parameters = optimizer.param_groups[0]["params"]
        assert len(parameters) == 14 and list(parameters[-1].shape) == [8, 384]
        adapter = parameters[-1]
        assert adapter.grad is not None and bool(torch.isfinite(adapter.grad).all())
        before = adapter.detach().clone()
        gradient = adapter.grad.detach().tolist()
        before_steps = [int(optimizer.state[p]["step"]) if optimizer.state[p] else 0 for p in parameters]
        result = real_step(optimizer, *args, **kwargs)
        after_steps = [int(optimizer.state[p]["step"]) for p in parameters]
        delta = adapter.detach().double() - before.double()
        assert all(new == old + 1 for old, new in zip(before_steps, after_steps, strict=True))
        assert bool(torch.isfinite(delta).all())
        counts["optimizer_updates"] += 1
        updates.append({"stage": stage["value"], "before_steps": before_steps,
            "after_steps": after_steps, "adapter_gradient": gradient,
            "adapter_update_l2": float(torch.linalg.vector_norm(delta)),
            "all_parameters_finite": all(bool(torch.isfinite(p).all()) for p in parameters)})
        return result

    def forbidden(*args, **kwargs):
        pytest.fail("model-only persistent scoring reached optimizer construction, backward or training")

    def train(checkpoint, steps, **changes):
        arguments = dict(expected_checkpoint_sha256=digest(checkpoint),
            expected_population_sha256=sha(case["population_raw"]), expected_conditioning_mode=mode,
            expected_source_space=SOURCE_SPACE, max_optimizer_steps=steps, max_seconds=60)
        arguments.update(changes)
        return subject.train_compact_content_persistent_v1(checkpoint,
            case["population_raw"], case["rows"], **arguments)

    def score(checkpoint, vector, *, incremental=False):
        before = dict(counts)
        with pytest.MonkeyPatch.context() as patch:
            for owner, name in ((torch.optim.Adam, "__init__"), (torch.optim.Optimizer, "__init__"),
                    (torch.optim.Adam, "step"), (torch.Tensor, "backward"), (torch.autograd, "grad"),
                    (numerical, "_optimizer")):
                patch.setattr(owner, name, forbidden)
            result = subject.score_compact_content_persistent_v1(checkpoint, vector, PREFIX,
                expected_checkpoint_sha256=digest(checkpoint), expected_conditioning_mode=mode,
                expected_source_space=SOURCE_SPACE, incremental=incremental)
        assert counts["gru_forwards"] - before["gru_forwards"] == (len(PREFIX) if incremental else 1)
        assert all(counts[key] == before[key] for key in COUNTERS if key not in
            ("gru_constructions", "state_restores", "gru_forwards"))
        assert len(result["logits"]) == len(PREFIX)
        assert all(len(row) == 537 and all(math.isfinite(x) for x in row) for row in result["logits"])
        assert type(result["positions_consumed"]) is int and result["positions_consumed"] == len(PREFIX)
        no_authority(result)
        return result

    rng = torch.get_rng_state().clone()
    with pytest.MonkeyPatch.context() as patch:
        for owner, name, wrapped in ((torch.nn.GRU, "__init__", observed_init),
                (torch.nn.Module, "load_state_dict", observed_load),
                (torch.optim.Adam, "__init__", observed_adam), (torch.nn.GRU, "forward", observed_forward),
                (torch.nn.functional, "cross_entropy", observed_ce), (torch.autograd, "grad", observed_grad),
                (torch.Tensor, "backward", observed_backward), (torch.nn.utils, "clip_grad_norm_", observed_clip),
                (torch.optim.Adam, "step", observed_step)):
            patch.setattr(owner, name, wrapped)
        parent = head.create_compact_content_head_v1(config={"hidden_size": 8,
            "token_embedding_dim": 8, "projection_width": 4, "seed": 1729})
        original_parent = deepcopy(parent)
        stage["value"] = "build"
        start = subject.build_compact_content_persistent_v1(parent, case["population_raw"], case["rows"],
            expected_initial_checkpoint_sha256=digest(parent), expected_population_sha256=sha(case["population_raw"]),
            conditioning_mode=mode, source_space=SOURCE_SPACE, learning_rate=.001)
        original_start = deepcopy(start)
        expected_names = ["body." + name for name in head._shapes(parent["config"])] + ["source_to_embedding.weight"]
        assert set(start["model_state"]) == set(expected_names) and len(expected_names) == 14
        assert start["parameter_order"] == expected_names
        assert all(start["model_state"]["body." + name] == values for name, values in parent["model_state"].items())
        assert start["model_state"]["source_to_embedding.weight"] == [[0.] * 384 for _ in range(8)]
        assert start["optimizer_state"]["parameters"] == {}
        row = case["rows"][2]
        stage["value"] = "original_baseline"
        baseline = _baseline_matrix(parent, row["conditioning"], PREFIX)
        stage["value"] = "zero_adapter_score"
        initial_score = score(start, row["conditioning"])
        assert initial_score["logits"] == baseline

        # Each refusal uses a newly valid independent digest. These are not
        # stale-hash tests, and any attempted update is counted or forbidden.
        wrong_mode = "first_step" if mode == "every_step" else "every_step"
        stage["value"] = "closed_refusals"
        refusal_before = dict(counts)
        with pytest.raises(ValueError):
            train(start, 1, expected_conditioning_mode=wrong_mode)
        with pytest.raises(ValueError):
            train(start, 1, expected_source_space="different-unverified-source-space")
        with pytest.raises(ValueError):
            train(parent, 1)
        altered_raw = wire({**case["population"], "rows": list(reversed(case["population"]["rows"]))})
        with pytest.raises(ValueError):
            subject.train_compact_content_persistent_v1(start, altered_raw, case["rows"],
                expected_checkpoint_sha256=digest(start), expected_population_sha256=sha(altered_raw),
                expected_conditioning_mode=mode, expected_source_space=SOURCE_SPACE,
                max_optimizer_steps=1, max_seconds=60)
        with pytest.raises(ValueError):
            subject.score_compact_content_persistent_v1(start, row["conditioning"], PREFIX,
                expected_checkpoint_sha256=digest(start), expected_conditioning_mode=wrong_mode,
                expected_source_space=SOURCE_SPACE)
        assert counts["optimizer_updates"] == refusal_before["optimizer_updates"] == 0
        assert counts["gru_forwards"] == refusal_before["gru_forwards"]

        stage["value"] = "uninterrupted"
        uninterrupted = train(start, 5)
        stage["value"] = "split_first"
        first = train(start, 3)
        stage["value"] = "save"
        saved = subject.compact_content_persistent_bytes_v1(first["checkpoint"],
            expected_checkpoint_sha256=digest(first["checkpoint"]))
        saved_path = tmp_path / "split-first-exclusive-save.json"
        exclusive(saved_path, saved)
        with pytest.raises(FileExistsError):
            exclusive(saved_path, saved)
        assert saved_path.read_bytes() == saved
        stage["value"] = "load"
        restored = subject.load_compact_content_persistent_v1(saved_path.read_bytes(),
            expected_raw_sha256=sha(saved), expected_conditioning_mode=mode, expected_source_space=SOURCE_SPACE)
        assert restored == first["checkpoint"] and restored is not first["checkpoint"]
        original_restored = deepcopy(restored)
        stage["value"] = "resumed"
        resumed = train(restored, 2)
        assert restored == original_restored

        a, b = uninterrupted["checkpoint"], resumed["checkpoint"]
        assert a["progress"] == b["progress"] == {"optimizer_steps": 5, "epochs_completed": 1, "row_cursor": 1}
        assert first["checkpoint"]["progress"] == {"optimizer_steps": 3, "epochs_completed": 0, "row_cursor": 3}
        assert a["parent_checkpoint_sha256"] == digest(start)
        assert b["parent_checkpoint_sha256"] == digest(first["checkpoint"])
        assert a["parent_checkpoint_sha256"] != b["parent_checkpoint_sha256"]
        assert {k: v for k, v in a.items() if k != "parent_checkpoint_sha256"} == {
            k: v for k, v in b.items() if k != "parent_checkpoint_sha256"}
        adapter = a["model_state"]["source_to_embedding.weight"]
        assert any(value != 0. for values in adapter for value in values)
        assert set(a["optimizer_state"]["parameters"]) == set(expected_names)
        assert all(state["step"] == 5 for state in a["optimizer_state"]["parameters"].values())
        for result in (uninterrupted, first, resumed):
            no_authority(result["checkpoint"])
            no_authority(result["report"])
            assert result["report"]["adapter_update_l2"] > 0
            assert result["report"]["adapter_gradient_norm_max"] > 0

        stage["value"] = "trained_full_prefix"
        full = score(a, row["conditioning"])
        stage["value"] = "trained_incremental_prefix"
        incremental = score(a, row["conditioning"], incremental=True)
        full_incremental_error = max_difference(full["logits"], incremental["logits"])
        assert full_incremental_error <= 1e-6
        stage["value"] = "resumed_full_prefix"
        resumed_score = score(b, row["conditioning"])
        assert resumed_score["logits"] == full["logits"]
        stage["value"] = "zero_vector_control"
        zero_score = score(a, [0.] * 384)
        stage["value"] = "shuffled_vector_control"
        shifted = row["conditioning"][-1:] + row["conditioning"][:-1]
        shifted_score = score(a, shifted)

        stage["value"] = "retained_state_refusals"
        refusal_steps = counts["optimizer_updates"]
        malformed = deepcopy(a)
        malformed["model_state"]["source_to_embedding.weight"][0].pop()
        malformed["weights_sha256"] = digest(malformed["model_state"])
        with pytest.raises(ValueError):
            train(malformed, 1)
        bad_moments = deepcopy(a)
        bad_moments["optimizer_state"]["parameters"]["source_to_embedding.weight"]["step"] += 1
        with pytest.raises(ValueError):
            train(bad_moments, 1)
        duplicate = b'{"schema":"duplicate",' + saved[1:]
        with pytest.raises(ValueError):
            subject.load_compact_content_persistent_v1(duplicate, expected_raw_sha256=sha(duplicate),
                expected_conditioning_mode=mode, expected_source_space=SOURCE_SPACE)
        with pytest.raises(ValueError):
            subject.load_compact_content_persistent_v1(saved, expected_raw_sha256=sha(saved),
                expected_conditioning_mode=wrong_mode, expected_source_space=SOURCE_SPACE)
        with pytest.raises(ValueError):
            subject.load_compact_content_persistent_v1(saved, expected_raw_sha256=sha(saved),
                expected_conditioning_mode=mode, expected_source_space="different-unverified-source-space")
        assert counts["optimizer_updates"] == refusal_steps == 10

    assert parent == original_parent and start == original_start and case == original_case
    assert torch.equal(rng, torch.get_rng_state()) and torch.get_num_threads() == 1
    assert counts == {"gru_constructions": 12, "state_restores": 20, "adam_constructions": 4,
        "gru_forwards": 19, "cross_entropy_calls": 10, "autograd_grad_calls": 10,
        "backward_calls": 10, "clip_calls": 10, "optimizer_updates": 10}
    assert len(cross_entropies) == len(updates) == 10
    assert all(update["all_parameters_finite"] and update["adapter_update_l2"] > 0 for update in updates)
    assert all(gradient["all_finite"] for gradient in gradients)
    ids = [item["id"] for item in case["rows"]]
    expected_sequences = {"uninterrupted": ids + ids[:1], "split_first": ids[:3], "resumed": ids[3:] + ids[:1]}
    for name, result in (("uninterrupted", uninterrupted), ("split_first", first), ("resumed", resumed)):
        assert [loss["row_id"] for loss in result["report"]["batch_losses"]] == expected_sequences[name]
        assert result["report"]["optimizer_steps"] == len(expected_sequences[name])
        observed = [loss for loss in cross_entropies if loss["stage"] == name]
        assert len(observed) == len(expected_sequences[name])
        for identity, loss in zip(expected_sequences[name], observed, strict=True):
            assert loss["labels"] == case["encodings"][ids.index(identity)]["target_ids"][1:]

    artifacts = {"population.json": case["population_raw"], "context.json": case["context_raw"],
        "signature.json": case["signature_raw"], "argument-roles.json": case["roles_raw"],
        "codec.json": wire(case["codec"]), "parent-v1.json": wire(parent),
        "initial-persistent.json": wire(start), "uninterrupted-result.json": wire(uninterrupted),
        "split-first-result.json": wire(first), "resumed-result.json": wire(resumed),
        "original-baseline-logits.json": wire(baseline), "initial-persistent-score.json": wire(initial_score),
        "trained-full-score.json": wire(full), "trained-incremental-score.json": wire(incremental),
        "resumed-full-score.json": wire(resumed_score), "zero-vector-score.json": wire(zero_score),
        "shifted-vector-score.json": wire(shifted_score), "observed-events.json": wire(events),
        "observed-cross-entropy.json": wire(cross_entropies), "observed-updates.json": wire(updates),
        "observed-gradients.json": wire(gradients),
        "authored-rows.json": wire([{"id": item["id"], "source_group": item["source_group"],
            "source_utf8": item["source_raw"].decode("utf-8"), "context_utf8": item["context_raw"].decode("utf-8"),
            "target_utf8": item["target_raw"].decode("utf-8"), "conditioning": item["conditioning"],
            "encoding": encoding} for item, encoding in zip(case["rows"], case["encodings"], strict=True)])}
    references = {saved_path.name: {"path": str(saved_path), "bytes": len(saved), "sha256": sha(saved)}}
    for name, raw in artifacts.items():
        path = tmp_path / name
        exclusive(path, raw)
        references[name] = {"path": str(path), "bytes": len(raw), "sha256": sha(raw)}
    panel = {"schema": "authored-compact-persistent-mechanics-panel/v1", "mode": mode,
        "artifacts": references, "counts": counts, "parameter_names": expected_names,
        "population_rows": 4, "source_groups": 4, "source_space": SOURCE_SPACE,
        "initial_donor_weights_sha256": parent["weights_sha256"],
        "initial_persistent_weights_sha256": start["weights_sha256"],
        "uninterrupted_steps": 5, "split_first_steps": 3, "resumed_steps": 2,
        "physical_optimizer_updates": 10, "unique_trajectory_steps": 5,
        "checkpoint_values_equal_except_immediate_parent": True,
        "fixed_inference_prefix": PREFIX, "full_incremental_max_absolute_error": full_incremental_error,
        "source_control_max_absolute_differences": {
            "original_vs_zero": max_difference(full["logits"], zero_score["logits"]),
            "original_vs_shifted": max_difference(full["logits"], shifted_score["logits"])},
        "scope": {"origin": "authored_engineering_fixture", "partition": "engineering_training",
            "source_encoder_executed": False, "conditioning_producer_verified": False,
            "permitted_context_verified": False, "training_gain_established": False,
            "heldout_evaluated": False, "generation_executed": False,
            "statutory_meaning_verified": False, "Lean_executed": False,
            "source_controls_are_accuracy_measurements": False,
            "strict_checkpoint_validation_reads_retained_training_targets": True,
            "score_prefix_derived_from_target": False, "training_mask": 0, "evaluation_gold_mask": 0}}
    exclusive(tmp_path / "authored-compact-persistent-mechanics-panel-v1.json", wire(panel))
    directory = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
