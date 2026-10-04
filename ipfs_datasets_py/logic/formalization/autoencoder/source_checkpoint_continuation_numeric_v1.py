"""Numerical adapter for continuing an authenticated source-v2 saved decoder.

The public facade prepares a closed, pinned plan before importing this module.
Numerical dependencies are imported only by ``run``.  The retained runtime
validates and loads the donor; its codec, normalization and runtime provenance
remain intact.  Adam starts empty because source-v2 saved no optimizer state.

The deadline covers setup, training and validation and is checked at operation
boundaries.  An in-flight numerical operation and final serialization may finish
after it.  These finite limits do not provide general effect containment.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import math
from pathlib import Path
import time


def run(plan):
    """Run a validated same-family, same-geometry saved-weight continuation.

    Selection uses only the supplied original validation rows.  The parent is
    the initial best candidate and remains selected unless a validated update
    improves the configured selection key.  No test rows are accepted.
    """
    started = time.monotonic()
    from . import source_training_v2 as source

    require = source._require
    expected = {
        "checkpoint", "checkpoint_pin", "domain_id", "training_rows",
        "validation_rows", "config", "binding", "prior_selected_optimizer_steps",
        "schema", "numerical_execution", *source.FALSE,
    }
    require(type(plan) is dict and set(plan) == expected, "closed continuation plan required")
    require(plan["schema"] == "source-checkpoint-continuation/v1"
            and plan["numerical_execution"] is False
            and all(plan[key] is False for key in source.FALSE),
            "unqualified metadata continuation plan required")
    parent = deepcopy(plan["checkpoint"])
    config = deepcopy(plan["config"])
    domain = plan["domain_id"]
    pin = plan["checkpoint_pin"]
    require(type(pin) is dict and set(pin) == {"path", "bytes", "sha256"}, "closed checkpoint pin required")
    require(type(pin["path"]) is str and type(pin["bytes"]) is int
            and 0 < pin["bytes"] <= source.MAX_BYTES
            and type(pin["sha256"]) is str and source.native._SHA.fullmatch(pin["sha256"]),
            "invalid checkpoint pin")
    require(type(plan["binding"]) is dict and len(plan["binding"]) == 6,
            "detached six-selector binding required")
    prior_steps = plan["prior_selected_optimizer_steps"]
    require(type(prior_steps) is int and prior_steps >= 0, "invalid selected donor step")
    require(type(parent) is dict and parent.get("domain_id") == domain
            and parent.get("dimension") == source.DIMENSION, "continuation family or geometry differs")
    require(type(config) is dict, "complete continuation configuration required")
    shape_names = ("hidden_size", "token_embedding_dim", "projection_width")
    shape = {name: parent["config"][name] for name in shape_names}
    checked_config = source._config({key: value for key, value in config.items()
                                     if key not in shape_names}, shape)
    require(checked_config == config, "continuation configuration differs")
    for name in (*shape_names, "input_normalization", "embedding_provenance"):
        require(config[name] == parent["config"][name], "continuation changed frozen " + name)
    require(parent["training"].get("selected_optimizer_steps") == prior_steps,
            "selected donor step differs")

    owner_path = Path(__file__)
    require(owner_path.is_file() and not owner_path.is_symlink()
            and 0 < owner_path.stat().st_size <= 128 * 1024,
            "bounded numerical adapter source required")
    owner_bytes = owner_path.read_bytes()
    owner_sha = hashlib.sha256(owner_bytes).hexdigest()
    training = source._rows(domain, plan["training_rows"], training=True)
    validation = source._rows(domain, plan["validation_rows"], training=True)

    def manifest(rows):
        return [{
            "id": row["id"],
            "source_sha256": hashlib.sha256(row["source_text"].encode()).hexdigest(),
            "normalized_source_sha256": hashlib.sha256(
                " ".join(row["source_text"].casefold().split()).encode()).hexdigest(),
            "embedding_sha256": source.digest(row["embedding"]),
            "target_sha256": source.digest(row["target"]),
        } for row in rows]

    require(manifest(training) == parent["training_manifest"]
            and manifest(validation) == parent["validation_manifest"],
            "continuation requires the original ordered split manifests")
    deadline = started + config["max_seconds"]
    vocabulary = deepcopy(parent["codec"]["target_vocabulary"])
    paths = deepcopy(parent["semantic_paths"])
    transform = deepcopy(parent["input_transform"])
    settings = {**config, "_input_scale": transform["scale"]}

    with source.native._cpu() as torch, torch.random.fork_rng(devices=[]):
        # Seed only the CPU generator whose state fork_rng saves and restores.
        torch.random.default_generator.manual_seed(config["seed"])
        runtime = source.Runtime(parent)
        model = runtime.model

        def state():
            return {name: tensor.detach().tolist()
                    for name, tensor in model.state_dict().items()}

        initial_sha = source.digest(state())
        require(initial_sha == parent["weights_sha256"], "loaded donor weights differ")
        batch = source._encoded(torch, training, vocabulary, paths, config, transform)
        tuning = source._encoded(torch, validation, vocabulary, paths, config, transform)
        optimizer = torch.optim.Adam(model.parameters(), lr=config["learning_rate"], foreach=False)
        initial_optimizer_entries = len(optimizer.state)
        require(initial_optimizer_entries == 0, "fresh Adam unexpectedly contains state")

        def checked_validation():
            # Check the actual target-free generation cardinality independently
            # of the frozen helper's zip aggregation, then compare its totals.
            count = len(validation)
            require(len(tuning) == 3 and all(len(item) == count for item in tuning),
                    "validation batch cardinality differs")
            require(tuning[1].shape == tuning[2].shape, "validation labels and weights differ")
            observed = source._validation(torch, model, tuning, validation,
                                          vocabulary, paths, domain, settings)
            require(type(observed) is dict and observed.get("count") == count,
                    "validation report cardinality differs")
            for name in ("objective", "token_cross_entropy", "weighted_cross_entropy",
                         "embedding_mse", "semantic_leaf_accuracy"):
                value = observed.get(name)
                require(type(value) in (int, float) and math.isfinite(value) and value >= 0,
                        "nonfinite or invalid validation " + name)
            model.eval()
            with torch.inference_mode():
                projected, sequences, ended = source._greedy(torch, model, tuning[0],
                                                             config["max_target_tokens"])
            require(len(projected) == count and type(sequences) is list
                    and type(ended) is list and len(sequences) == count and len(ended) == count,
                    "generated validation cardinality differs")
            require(all(type(sequence) is list and len(sequence) < config["max_target_tokens"]
                        for sequence in sequences)
                    and all(type(value) is bool for value in ended),
                    "generated validation sequence schema differs")
            exact = valid = leaf_correct = 0
            for index in range(count):
                candidate, _, _ = source._candidate(domain, sequences[index], ended[index], vocabulary)
                row = validation[index]
                exact += candidate is not None and source._raw(candidate) == source._raw(row["target"])
                valid += candidate is not None
                actual = source._leaves(candidate) if candidate is not None else {}
                gold = source._leaves(row["target"])
                for path in map(tuple, paths):
                    leaf_correct += candidate is not None and source._same_leaf(
                        actual.get(path, source._MISSING), gold.get(path, source._MISSING))
            totals = {"exact_targets": int(exact), "valid_candidates": int(valid),
                      "semantic_leaf_correct": int(leaf_correct),
                      "semantic_leaf_count": count * len(paths)}
            require(all(type(observed.get(name)) is int and observed[name] == value
                        for name, value in totals.items()),
                    "validation aggregation differs from complete ordered generation")
            require(observed["semantic_leaf_accuracy"] == leaf_correct / max(count * len(paths), 1),
                    "validation semantic accuracy differs")
            require(observed.get("free_running_metrics_teacher_forced") is False,
                    "free validation was teacher forced")
            return observed

        require(time.monotonic() < deadline, "continuation deadline before baseline validation")
        tick = time.monotonic()
        before = checked_validation()
        validation_seconds = time.monotonic() - tick
        best = deepcopy(before)
        best_state = deepcopy(model.state_dict())
        selected_epoch = selected_steps = steps = examples_seen = tokens_seen = stale = 0
        selected_epoch_complete = True
        last_validated_steps = 0
        optimizer_seconds = 0.0
        history = []
        stop = "epoch_budget"
        generator = torch.Generator().manual_seed(config["seed"])
        lengths = (batch[1] != 0).sum(1)
        require(len(lengths) == len(training) and all(len(item) == len(training) for item in batch),
                "training batch cardinality differs")
        fit_started = time.monotonic()

        for epoch in range(1, config["epochs"] + 1):
            model.train()
            completed = True
            epoch_indices = set()
            for index in source._length_buckets(torch, lengths, config["batch_size"], generator):
                if config["max_optimizer_steps"] is not None and steps >= config["max_optimizer_steps"]:
                    completed, stop = False, "optimizer_step_budget"
                    break
                if time.monotonic() >= deadline:
                    completed, stop = False, "deadline_before_batch"
                    break
                indices = index.tolist()
                require(1 <= len(indices) <= config["batch_size"]
                        and all(type(value) is int and 0 <= value < len(training) for value in indices)
                        and len(set(indices)) == len(indices) and not epoch_indices.intersection(indices),
                        "training batch indices differ")
                epoch_indices.update(indices)
                tick = time.monotonic()
                width = int((batch[1][index] != 0).sum(1).max())
                values = (batch[0][index], batch[1][index, :width], batch[2][index, :width])
                optimizer.zero_grad(set_to_none=True)
                loss, ce, weighted, mse = source._loss(torch, model, *values, settings)
                require(all(bool(torch.isfinite(value)) for value in (loss, ce, weighted, mse)),
                        "nonfinite continuation training loss")
                loss.backward()
                norm = torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0)
                require(bool(torch.isfinite(norm)), "nonfinite continuation gradient")
                optimizer.step()
                require(all(bool(torch.isfinite(parameter).all()) for parameter in model.parameters()),
                        "nonfinite updated continuation weights")
                require(all(bool(torch.isfinite(value).all()) for item in optimizer.state.values()
                            for value in item.values() if torch.is_tensor(value)),
                        "nonfinite updated Adam state")
                optimizer_seconds += time.monotonic() - tick
                steps += 1
                examples_seen += len(indices)
                tokens_seen += int((values[1][:, 1:] != 0).sum())
            if completed:
                require(len(epoch_indices) == len(training), "incomplete supposedly complete training epoch")
            if not completed and steps == last_validated_steps:
                break
            reached_steps = config["max_optimizer_steps"] is not None and steps >= config["max_optimizer_steps"]
            if completed and epoch % config["validation_interval"] and epoch != config["epochs"] and not reached_steps:
                continue
            if time.monotonic() >= deadline:
                stop = "deadline_before_validation"
                history.append({"epoch": epoch, "epoch_complete": completed, "optimizer_steps": steps,
                                "validation_performed": False, "selected": False})
                break
            tick = time.monotonic()
            observed = checked_validation()
            validation_seconds += time.monotonic() - tick
            last_validated_steps = steps
            selected = source._selection(observed, config["strategy"]) > source._selection(best, config["strategy"])
            if selected:
                best, best_state, selected_epoch, stale = deepcopy(observed), deepcopy(model.state_dict()), epoch, 0
                selected_steps, selected_epoch_complete = steps, completed
            else:
                stale += 1
            history.append({"epoch": epoch, "epoch_complete": completed, "optimizer_steps": steps,
                            "validation_performed": True, **observed, "selected": selected})
            if not completed:
                break
            if reached_steps:
                stop = "optimizer_step_budget"
                break
            if config["patience"] and stale >= config["patience"]:
                stop = "validation_patience"
                break
            if time.monotonic() >= deadline:
                stop = "deadline_after_validation"
                break

        require(steps > 0, "no continuation training steps completed")
        fit_seconds = time.monotonic() - fit_started
        model.load_state_dict(best_state, strict=True)
        weights = state()
        final_sha = source.digest(weights)
        selection = ("weighted_teacher_forced_objective" if config["strategy"] == "reference_ce"
                     else "free_running_exact_then_train_variable_leaves_then_weighted_objective")
        metrics = {
            "before_validation": before, "selected_validation": best,
            "selected_epoch": selected_epoch, "selected_epoch_complete": selected_epoch_complete,
            "optimizer_steps": steps, "selected_optimizer_steps": selected_steps,
            "donor_selected_optimizer_steps": prior_steps,
            "examples_seen": examples_seen, "training_tokens": tokens_seen,
            "optimizer_seconds": optimizer_seconds, "validation_seconds": validation_seconds,
            "fit_seconds": fit_seconds, "pre_checkpoint_seconds": time.monotonic() - started,
            "stopped_reason": stop, "history": history, "test_used_for_selection": False,
            "selection": selection, "fresh_optimizer": True, "exact_optimizer_resume": False,
            "initial_optimizer_state_entries": initial_optimizer_entries,
            "parent_retained_as_validation_baseline": True,
            "selected_parent_weights": selected_steps == 0,
            "soft_deadline_seconds": config["max_seconds"],
            "validation_generation_cardinality_checked": True,
        }
        payload = deepcopy(parent)
        payload.update(config=config, model_state=weights, weights_sha256=final_sha, training=deepcopy(metrics))
        require(len(source._raw(payload)) <= source.MAX_BYTES, "continuation checkpoint exceeds byte bound")
        restored = source.Runtime(payload)
        restored_sha = source.digest({name: tensor.detach().tolist()
                                      for name, tensor in restored.model.state_dict().items()})
        require(restored_sha == final_sha, "returned continuation runtime weights differ")
        require(owner_path.read_bytes() == owner_bytes, "numerical adapter changed during continuation")
        metrics["total_elapsed_seconds"] = time.monotonic() - started
        payload["training"] = deepcopy(metrics)
        return {
            "checkpoint": payload, "metrics": deepcopy(metrics),
            "initial_weights_sha256": initial_sha, "final_weights_sha256": final_sha,
            "numerical_owner_sha256": owner_sha, "numerical_execution": True,
        }


def load_runtime_payload(checkpoint):
    """Load through the same frozen runtime that validates the donor pins."""
    from . import source_training_v2 as source
    return source.Runtime(checkpoint)


__all__ = ["run", "load_runtime_payload"]
