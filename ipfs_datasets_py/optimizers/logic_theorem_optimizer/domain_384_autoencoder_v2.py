"""Separate 384D lineage with scalar-aware loss and generated-output selection.

All parent tensors are inherited. The original v1 runtime and 8D linguistic
lineage remain unchanged. Native-valid output is still an unqualified candidate;
this numerical path cannot replace modality projections or actual Lake builds.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import math
from pathlib import Path
import time

from . import domain_384_autoencoder as base
from . import domain_384_fidelity as fidelity
from . import modal_latent_formula as numerical

SCHEMA = "domain-384-typed-autoencoder/v2"
DIMENSION, DOMAINS, FALSE = base.DIMENSION, base.DOMAINS, dict(base.FALSE)
_require, _raw, digest = base._require, base._raw, base.digest
_SHAPES = {"hidden_size", "token_embedding_dim", "projection_width"}
_EXTRA = {"scalar_value_weight": 8., "source_conditioning": "none", "eval_interval": 10,
    "plateau_patience": 3, "plateau_factor": .5, "min_learning_rate_ratio": .05,
    "embedding_nonregression": True, "memory_budget_bytes": 512 * 1024 * 1024}


class EvaluationDeadline(TimeoutError):
    """An incomplete evaluation carries no selection evidence."""


def _deadline(deadline):
    if deadline is not None and time.monotonic() >= deadline:
        raise EvaluationDeadline("generated evaluation exceeded numerical deadline")


def _implementation():
    from ...logic.formalization.autoencoder import ui_source_contract_384
    from ...logic.ui_ux_ir.model import components
    return {"runtime": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "fidelity": hashlib.sha256(Path(fidelity.__file__).read_bytes()).hexdigest(),
        "ui_semantic_owners": {m.__name__: hashlib.sha256(Path(m.__file__).read_bytes()).hexdigest()
            for m in (ui_source_contract_384, components)},
        "inherited": base._implementation()}


_IMPORTED = _implementation()


def _guard():
    _require(_implementation() == _IMPORTED, "source384 v2 producer changed after import")


def validate_target(domain, target):
    return fidelity.validate_native_target(domain, target)


def _config(config, parent):
    config = {} if config is None else deepcopy(config)
    _require(type(config) is dict, "configuration must be an object")
    extra = {key: config.pop(key, default) for key, default in _EXTRA.items()}
    config.setdefault("max_target_tokens", parent["max_target_tokens"])
    options = base._config(config, parent)
    _require(options["max_target_tokens"] <= parent["max_target_tokens"], "target window cannot exceed parent")
    for key, low, high in (("scalar_value_weight", 1, 32), ("plateau_factor", .01, .99),
                          ("min_learning_rate_ratio", .001, 1)):
        _require(type(extra[key]) in (int, float) and math.isfinite(extra[key]) and low <= extra[key] <= high,
                 "invalid " + key)
    for key, low, high in (("eval_interval", 1, 100), ("plateau_patience", 1, 1000),
                          ("memory_budget_bytes", 1024 * 1024, 8 * 1024**3)):
        _require(type(extra[key]) is int and low <= extra[key] <= high, "invalid " + key)
    _require(extra["source_conditioning"] in ("none", "train_rms"), "unknown source conditioning")
    _require(type(extra["embedding_nonregression"]) is bool, "embedding gate must be boolean")
    return {**options, **extra}


def _normalizer(torch, data, mode, max_gain=64):
    _require(mode in ("none", "train_rms"), "unknown source conditioning")
    _require(type(max_gain) in (int, float) and math.isfinite(max_gain) and 1 <= max_gain <= 64,
             "invalid conditioning gain bound")
    mean = data.mean(0) if mode == "train_rms" else torch.zeros(DIMENSION, dtype=data.dtype)
    # A single global L2 RMS avoids unstable per-coordinate variance estimates.
    rms = float(((data - mean).square().sum(1).mean()).sqrt()) if mode == "train_rms" else 1.
    scale = max(rms, 1. / max_gain) if mode == "train_rms" else 1.
    return {"schema": "training-only-centered-l2-rms/v1", "mode": mode, "mean": mean.tolist(),
        "scale": scale, "observed_rms": rms, "max_gain": float(max_gain), "fitted_rows": len(data),
        "scope": "decoder_condition_only; raw_projection_reconstruction_unchanged"}


def _conditioning(torch, projected, normalizer):
    return (projected - torch.tensor(normalizer["mean"], dtype=projected.dtype)) / normalizer["scale"]


def _loss(torch, model, data, labels, token_weights, config, normalizer):
    projected = model.project(data)
    logits, _ = model.next_logits(labels[:, :-1], model.start(_conditioning(torch, projected, normalizer)))
    losses = torch.nn.functional.cross_entropy(logits.reshape(-1, logits.shape[-1]),
        labels[:, 1:].reshape(-1), ignore_index=0, reduction="none").reshape(labels.shape[0], -1)
    _require(token_weights.shape == losses.shape and bool((token_weights >= 0).all()), "token weight shape differs")
    _require(bool(((token_weights > 0) == (labels[:, 1:] != 0)).all()), "every non-padding token needs positive weight")
    weighted = (losses * token_weights).sum() / token_weights.sum()
    ce = losses.sum() / (labels[:, 1:] != 0).sum()
    mse = torch.nn.functional.mse_loss(projected, data)
    return weighted + config["reconstruction_weight"] * mse, ce, mse, weighted


def _metrics(torch, model, batch, config, normalizer, *, deadline=None):
    sums = [0., 0., 0.]
    tokens = weight_total = elements = 0
    data, labels, weights = batch
    model.eval()
    with torch.inference_mode():
        for offset in range(0, len(data), config["batch_size"]):
            _deadline(deadline)
            x, y, w = (value[offset:offset + config["batch_size"]] for value in batch)
            _, ce, mse, weighted = _loss(torch, model, x, y, w, config, normalizer)
            _require(all(bool(torch.isfinite(v)) for v in (ce, mse, weighted)), "nonfinite evaluation")
            n, total, count = int((y[:, 1:] != 0).sum()), float(w.sum()), x.numel()
            sums[0] += float(ce) * n; sums[1] += float(mse) * count; sums[2] += float(weighted) * total
            tokens += n; elements += count; weight_total += total
    ce, mse, weighted = sums[0] / tokens, sums[1] / elements, sums[2] / weight_total
    return {"objective": weighted + config["reconstruction_weight"] * mse,
        "token_cross_entropy": ce, "weighted_token_cross_entropy": weighted, "embedding_mse": mse}


def _generate(torch, model, rows, vocabulary, config, normalizer, *, deadline=None):
    """Batched greedy generation. Gold targets are structurally forbidden."""
    _require(all(set(row) == {"id", "source_text", "embedding"} for row in rows), "target-free inference rows required")
    results = []
    model.eval()
    with torch.inference_mode():
        for offset in range(0, len(rows), config["batch_size"]):
            _deadline(deadline)
            group = rows[offset:offset + config["batch_size"]]
            data = torch.tensor([row["embedding"] for row in group], dtype=torch.float32)
            projected = model.project(data)
            _require(bool(torch.isfinite(projected).all()), "nonfinite reconstructed embedding")
            hidden = model.start(_conditioning(torch, projected, normalizer))
            current = torch.ones((len(group), 1), dtype=torch.long)
            active = [True] * len(group)
            ended, sequences = [False] * len(group), [[] for _ in group]
            for _ in range(config["max_target_tokens"] - 1):
                _deadline(deadline)
                logits, hidden = model.next_logits(current, hidden)
                _require(bool(torch.isfinite(logits).all()) and bool(torch.isfinite(hidden).all()), "nonfinite generation")
                indices = logits[:, -1].argmax(-1).tolist()
                for i, index in enumerate(indices):
                    if not active[i]:
                        continue
                    if index in (0, 1, 2):
                        active[i], ended[i] = False, index == 2
                    else:
                        sequences[i].append(vocabulary[index])
                if not any(active):
                    break
                current = torch.tensor([[indices[i] if active[i] else 2] for i in range(len(group))])
            for i, row in enumerate(group):
                results.append({"id": row["id"], "source_sha256": hashlib.sha256(row["source_text"].encode()).hexdigest(),
                    "generated_tokens": sequences[i], "ended": ended[i], "reconstructed_embedding": projected[i].tolist(),
                    "target_access": False, "teacher_forcing": False, **FALSE})
    return results


def _generated_metrics(domain, generated, expected, *, deadline=None):
    _require(len(generated) == len(expected), "generated/reference count differs")
    fields, reports = {}, []
    for actual, gold in zip(generated, expected):
        _deadline(deadline)
        _require(actual["id"] == gold["id"] and actual["target_access"] is False, "generated/reference identity differs")
        row = fidelity.evaluate_generated(gold["target"], actual["generated_tokens"], ended=actual["ended"], domain_id=domain)
        reports.append(row)
        for item in row["per_path"]:
            record = fields.setdefault(item["path"], {"correct": 0, "total": 0})
            record["correct"] += int(item["correct"]); record["total"] += 1
    correct = sum(row["scalar_correct"] for row in reports)
    total = sum(row["scalar_total"] for row in reports)
    return {"exact_count": sum(row["exact"] for row in reports),
        "native_valid_count": sum(row["native_valid"] for row in reports), "count": len(reports),
        "field_accuracy": correct / total if total else 0., "scalar_correct": correct, "scalar_total": total,
        "per_field": fields, "generated_outputs_sha256": digest([{key: row[key] for key in
            ("id", "source_sha256", "generated_tokens", "ended", "reconstructed_embedding")} for row in generated]),
        "target_free_generation": True}


def _selection(candidate, best, before, embedding_nonregression=True):
    """Selection cannot trade a known field's accuracy for prettier syntax."""
    left, right = candidate["generated"], best["generated"]
    _require(set(left["per_field"]) == set(right["per_field"]), "selection field coverage differs")
    regressions = [path for path, row in left["per_field"].items()
        if row["total"] != right["per_field"][path]["total"] or row["correct"] < right["per_field"][path]["correct"]]
    if regressions or left["exact_count"] < right["exact_count"] or left["native_valid_count"] < right["native_valid_count"]:
        return False, "generated_field_regression"
    if embedding_nonregression and candidate["embedding_mse"] > before["embedding_mse"] + 1e-12:
        return False, "embedding_regression_against_initialization"
    rank = lambda r: (r["generated"]["exact_count"], r["generated"]["field_accuracy"], -r["objective"])
    return (True, "generated_fidelity_then_loss") if rank(candidate) > rank(best) else (False, "no_selection_improvement")


def _manifest(rows):
    return [{"id": row["id"], "source_sha256": hashlib.sha256(row["source_text"].encode()).hexdigest(),
        "embedding_sha256": digest(row["embedding"]), "target_sha256": digest(row["target"])} for row in rows]


def _memory(config, rows, vocabulary, parameter_count):
    # Full input panels plus a conservative autograd/logit/Adam reservation.
    estimate = rows * (DIMENSION * 4 + config["max_target_tokens"] * 12) + parameter_count * 48
    estimate += config["batch_size"] * config["max_target_tokens"] * (vocabulary + config["hidden_size"]) * 32
    _require(estimate <= config["memory_budget_bytes"], "estimated tensor reservation exceeds budget")
    return {"estimated_tensor_bytes": estimate, "budget_bytes": config["memory_budget_bytes"],
        "scope": "conservative_tensor_estimate_excludes_python_imports_allocator_and_process_rss"}


def train(domain, training_rows, validation_rows, *, parent_projection, config=None):
    _guard()
    call_started = time.monotonic()
    original, parent_path = None, None
    if type(parent_projection) is dict and set(parent_projection) == {"path", "sha256"}:
        parent_path = Path(parent_projection["path"])
        _require(parent_path.is_file() and not parent_path.is_symlink() and parent_path.stat().st_size <= base.MAX_BYTES,
                 "bounded regular parent required")
        original = parent_path.read_bytes()
        _require(hashlib.sha256(original).hexdigest() == parent_projection["sha256"], "parent hash differs")
        parent, parent_sha = base._parse(original), parent_projection["sha256"]
    else:
        parent, parent_sha = deepcopy(parent_projection), digest(parent_projection)
    with base._cpu() as torch:
        numerical.validate_checkpoint(parent)
        _require(parent["binding"]["dimension"] == DIMENSION and parent["progress"]["optimizer_steps"] > 0,
                 "trained 384D Legal parent required")
        options = _config(config, parent["config"])
        train_rows, tune = base._rows(domain, training_rows, training=True), base._rows(domain, validation_rows, training=True)
        for row in train_rows + tune:
            validate_target(domain, row["target"])
        for key in (lambda r: r["id"], lambda r: " ".join(r["source_text"].casefold().split()), lambda r: digest(r["embedding"])):
            _require(not {key(r) for r in train_rows} & {key(r) for r in tune}, "training/tuning overlap")
        vocabulary = [*base.SPECIAL, *sorted({token for r in train_rows for token in base._tokens(r["target"])})]
        _require(len(vocabulary) <= 4096, "training vocabulary exceeds bound")
        codec = {"schema": "typed-json-lexical/v1", "target_vocabulary": vocabulary}
        # Size a model before allocating panels; all inherited parameters have bounded shapes.
        model, lineage = base._transfer(parent, codec, options)
        memory = _memory(options, len(train_rows) + len(tune), len(vocabulary), sum(p.numel() for p in model.parameters()))
        def batch(rows):
            x, y = base._batch(torch, rows, vocabulary, options["max_target_tokens"])
            weights = torch.tensor([fidelity.teacher_forcing_weights(row["target"], width=y.shape[1] - 1,
                scalar_value_weight=options["scalar_value_weight"]) for row in rows], dtype=torch.float32)
            return x, y, weights
        training, tuning = batch(train_rows), batch(tune)
        train_manifest, tune_manifest = _manifest(train_rows), _manifest(tune)
        normalizer = _normalizer(torch, training[0], options["source_conditioning"])
        normalizer["training_embedding_digest"] = digest([r["embedding_sha256"] for r in train_manifest])
        inference_rows = [{key: row[key] for key in ("id", "source_text", "embedding")} for row in tune]
        started = time.monotonic()
        deadline = started + options["max_seconds"]
        def observe():
            result = _metrics(torch, model, tuning, options, normalizer, deadline=deadline)
            generated = _generate(torch, model, inference_rows, vocabulary, options, normalizer, deadline=deadline)
            return {**result, "generated": _generated_metrics(domain, generated, tune, deadline=deadline)}
        before = observe()
        _require(time.monotonic() < deadline, "deadline exhausted during initial evaluation")
        best, best_state, selected_epoch = before, deepcopy(model.state_dict()), 0
        trajectory_best_objective = before["objective"]
        optimizer = torch.optim.Adam(model.parameters(), lr=options["learning_rate"])
        generator = torch.Generator().manual_seed(options["seed"])
        steps = stale = plateau = examples_seen = tokens_seen = 0
        optimizer_seconds = validation_seconds = 0.
        history, stop = [], "epoch_budget"
        for epoch in range(1, options["epochs"] + 1):
            order = torch.randperm(len(train_rows), generator=generator)
            complete = True
            model.train()
            for offset in range(0, len(order), options["batch_size"]):
                if time.monotonic() >= deadline:
                    complete, stop = False, "deadline"; break
                tick = time.monotonic()
                index = order[offset:offset + options["batch_size"]]
                x, y, w = (value[index] for value in training)
                width = int((y != 0).sum(1).max())
                y, w = y[:, :width], w[:, :width - 1]
                optimizer.zero_grad(set_to_none=True)
                loss, _, _, _ = _loss(torch, model, x, y, w, options, normalizer)
                _require(bool(torch.isfinite(loss)), "nonfinite training loss")
                loss.backward()
                norm = torch.nn.utils.clip_grad_norm_(model.parameters(), 5.)
                _require(bool(torch.isfinite(norm)), "nonfinite gradient")
                optimizer.step()
                steps += 1; examples_seen += len(index); tokens_seen += int((y[:, 1:] != 0).sum())
                optimizer_seconds += time.monotonic() - tick
            if not complete or time.monotonic() >= deadline:
                stop = "deadline"; break
            if epoch != 1 and epoch % options["eval_interval"] and epoch != options["epochs"]:
                continue
            tick = time.monotonic()
            try:
                observed = observe()
            except EvaluationDeadline:
                validation_seconds += time.monotonic() - tick
                stop = "deadline_incomplete_generated_evaluation"
                break
            selected, reason = _selection(observed, best, before, options["embedding_nonregression"])
            if time.monotonic() >= deadline:
                selected, reason = False, "late_evaluation"
            if selected:
                candidate = deepcopy(model.state_dict())
                if time.monotonic() < deadline:
                    best, best_state, selected_epoch = observed, candidate, epoch
                else:
                    selected, reason = False, "late_state_copy"
            # Keep learning while the continuous candidate trajectory improves,
            # even when it has not yet cleared the stricter saved-state gates.
            # Rejection is not evidence of an optimization plateau.
            progressed = time.monotonic() < deadline and (selected or observed["objective"] < trajectory_best_objective - 1e-9)
            if progressed:
                trajectory_best_objective = min(trajectory_best_objective, observed["objective"])
                stale = plateau = 0
            else:
                stale += 1; plateau += 1
            lr = optimizer.param_groups[0]["lr"]
            next_lr = lr
            if plateau >= options["plateau_patience"]:
                next_lr = max(options["learning_rate"] * options["min_learning_rate_ratio"], lr * options["plateau_factor"])
                for group in optimizer.param_groups: group["lr"] = next_lr
                plateau = 0
            history.append({"epoch": epoch, **observed, "selected": selected, "selection_reason": reason,
                "learning_rate": lr, "next_learning_rate": next_lr, "stale_evaluations": stale,
                "candidate_learning_progress": progressed, "trajectory_best_objective": trajectory_best_objective,
                "gradient_norm_last_batch": float(norm)})
            validation_seconds += time.monotonic() - tick
            if time.monotonic() >= deadline:
                stop = "deadline"; break
            if stale >= options["patience"]:
                stop = "generated_validation_patience"; break
        _require(steps > 0, "no training steps completed")
        model.load_state_dict(best_state)
        weights = {name: tensor.detach().tolist() for name, tensor in model.state_dict().items()}
        report = {"before_validation": before, "selected_validation": best, "selected_epoch": selected_epoch,
            "optimizer_steps": steps, "examples_seen": examples_seen, "training_tokens": tokens_seen,
            "optimizer_seconds": optimizer_seconds, "validation_seconds": validation_seconds,
            "fit_seconds": time.monotonic() - started, "stopped_reason": stop, "history": history,
            "training": _metrics(torch, model, training, options, normalizer), "test_used_for_selection": False,
            "selection": "generated_exact_and_all_scalar_paths_then_weighted_loss_with_embedding_gate",
            "patience_unit": "completed_generated_evaluations", "numerical_memory_estimate": memory,
            "schedule_signal": "candidate_weighted_objective_or_accepted_generated_progress; rejection_alone_is_not_plateau",
            "deadline_scope": "initial_evaluation_optimization_generated_selection_including_state_copy",
            "optimizer_state": "continuous_adam_during_fit; not_serialized_for_resume",
            "whole_call_seconds": time.monotonic() - call_started}
        checkpoint = {"schema": SCHEMA, "domain_id": domain, "dimension": DIMENSION,
            "architecture": numerical.ARCHITECTURE, "codec": codec, "config": options,
            "implementation": _implementation(), "parent_sha256": parent_sha,
            "parent_binding": deepcopy(parent["binding"]), "parent_context_limit": parent["config"]["max_target_tokens"],
            "lineage": lineage, "normalizer": normalizer, "normalizer_sha256": digest(normalizer),
            "model_state": weights, "weights_sha256": digest(weights), "training_manifest": train_manifest,
            "validation_manifest": tune_manifest, "training": report, **FALSE}
        _guard()
        _require(original is None or parent_path.read_bytes() == original, "parent changed during training")
        _require(len(_raw(checkpoint)) <= base.MAX_BYTES, "checkpoint exceeds bound")
        Runtime(checkpoint)
        return {"checkpoint": checkpoint, "metrics": deepcopy(report)}


class Runtime:
    """Strict v2 loader and target-free batched greedy inference."""
    def __init__(self, checkpoint):
        _guard()
        required = {"schema", "domain_id", "dimension", "architecture", "codec", "config", "implementation",
            "parent_sha256", "parent_binding", "parent_context_limit", "lineage", "normalizer", "normalizer_sha256",
            "model_state", "weights_sha256", "training_manifest", "validation_manifest", "training", *FALSE}
        _require(type(checkpoint) is dict and set(checkpoint) == required and checkpoint["schema"] == SCHEMA,
                 "closed v2 domain checkpoint required")
        _require(len(_raw(checkpoint)) <= base.MAX_BYTES, "checkpoint exceeds bound")
        _require(checkpoint["domain_id"] in DOMAINS and type(checkpoint["dimension"]) is int and checkpoint["dimension"] == DIMENSION,
                 "genuine 384D domain required")
        _require(all(checkpoint[k] is False for k in FALSE), "checkpoint cannot grant authority")
        _require(checkpoint["implementation"] == _implementation(), "v2 implementation pins differ")
        _require(checkpoint["architecture"] == numerical.ARCHITECTURE, "architecture differs")
        _require(type(checkpoint["parent_sha256"]) is str and base._SHA.fullmatch(checkpoint["parent_sha256"])
                 and type(checkpoint["parent_binding"]) is dict and checkpoint["parent_binding"].get("dimension") == DIMENSION,
                 "invalid parent identity")
        config = checkpoint["config"]
        _require(type(config) is dict and _SHAPES <= set(config), "invalid configuration")
        for key, low, high in (("hidden_size", 8, 128), ("token_embedding_dim", 8, 64), ("projection_width", 1, 64)):
            _require(type(config[key]) is int and low <= config[key] <= high, "invalid shape")
        limit = checkpoint["parent_context_limit"]
        _require(type(limit) is int and 1 <= limit <= 1024, "invalid parent token limit")
        parent_config = {**{k: config[k] for k in _SHAPES}, "max_target_tokens": limit}
        _require(_config({k: v for k, v in config.items() if k not in _SHAPES}, parent_config) == config,
                 "configuration differs")
        codec = checkpoint["codec"]
        _require(type(codec) is dict and set(codec) == {"schema", "target_vocabulary"} and codec["schema"] == "typed-json-lexical/v1",
                 "invalid codec")
        vocabulary = codec["target_vocabulary"]
        _require(type(vocabulary) is list and 4 <= len(vocabulary) <= 4096 and vocabulary[:3] == list(base.SPECIAL)
                 and all(type(t) is str and 0 < len(t) <= 16384 for t in vocabulary)
                 and vocabulary[3:] == sorted(set(vocabulary[3:]))
                 and all(base._TOKEN.fullmatch(t) for t in vocabulary[3:]), "invalid vocabulary")
        manifests = [checkpoint[name] for name in ("training_manifest", "validation_manifest")]
        for rows in manifests:
            _require(type(rows) is list and 1 <= len(rows) <= 4096, "invalid split manifest")
            seen = set()
            for row in rows:
                _require(type(row) is dict and set(row) == {"id", "source_sha256", "embedding_sha256", "target_sha256"}
                    and type(row["id"]) is str and 0 < len(row["id"]) <= 256 and row["id"] not in seen
                    and all(type(row[k]) is str and base._SHA.fullmatch(row[k]) for k in row if k != "id"), "invalid split row")
                seen.add(row["id"])
        for key in ("id", "source_sha256", "embedding_sha256"):
            _require(not {r[key] for r in manifests[0]} & {r[key] for r in manifests[1]}, "checkpoint split overlap")
        n = checkpoint["normalizer"]
        _require(type(n) is dict and set(n) == {"schema", "mode", "mean", "scale", "observed_rms", "max_gain", "fitted_rows", "scope", "training_embedding_digest"}
            and digest(n) == checkpoint["normalizer_sha256"] and n["schema"] == "training-only-centered-l2-rms/v1"
            and n["mode"] == config["source_conditioning"] and type(n["fitted_rows"]) is int and n["fitted_rows"] == len(manifests[0])
            and n["scope"] == "decoder_condition_only; raw_projection_reconstruction_unchanged"
            and n["training_embedding_digest"] == digest([r["embedding_sha256"] for r in manifests[0]]), "invalid fitted normalizer identity")
        base._vector(n["mean"])
        _require(type(n["scale"]) in (int, float) and math.isfinite(n["scale"]) and n["scale"] >= 1 / 64
            and n["max_gain"] == 64. and type(n["observed_rms"]) in (int, float)
            and math.isfinite(n["observed_rms"]) and n["observed_rms"] >= 0, "invalid conditioning scale")
        _require(n["scale"] == (max(n["observed_rms"], 1 / 64) if n["mode"] == "train_rms" else 1.)
            and (n["mode"] != "none" or n["mean"] == [0.] * DIMENSION), "conditioning transform differs")
        training = checkpoint["training"]
        _require(type(training) is dict and type(training.get("optimizer_steps")) is int and training["optimizer_steps"] > 0
            and type(training.get("selected_epoch")) is int and 0 <= training["selected_epoch"] <= config["epochs"]
            and training.get("test_used_for_selection") is False, "invalid training provenance")
        state = checkpoint["model_state"]
        _require(digest(state) == checkpoint["weights_sha256"], "weight digest differs")
        with base._cpu():
            model = numerical._model({"dimension": DIMENSION}, codec, config)
            _require(type(state) is dict and set(state) == set(model.state_dict()), "tensor names differ")
            _memory(config, 1, len(vocabulary), sum(p.numel() for p in model.parameters()))
            model.load_state_dict({name: numerical._tensor(state[name], template, name)
                for name, template in model.state_dict().items()}, strict=True)
        self.checkpoint, self.model = deepcopy(checkpoint), model.eval()

    def describe(self):
        c = self.checkpoint
        return {"schema": SCHEMA, "domain_id": c["domain_id"], "dimension": DIMENSION,
            "architecture": c["architecture"], "source_conditioning": c["normalizer"]["mode"],
            "weights_sha256": c["weights_sha256"], "parent_sha256": c["parent_sha256"],
            "embedding_provenance": deepcopy(c["config"]["embedding_provenance"]),
            "embedding_provenance_verified_by_runtime": False, "source_text_is_neural_input": False,
            "trained_optimizer_steps": c["training"]["optimizer_steps"], "sample_memory_used": False,
            "independent_source_fidelity_check_required": True, **FALSE}

    def infer(self, rows, *, weight_ablation=None):
        _guard()
        c = self.checkpoint
        rows = base._rows(c["domain_id"], rows, training=False)
        _require(weight_ablation in (None, "zero_projection", "zero_condition", "zero_decoder"), "unknown weight ablation")
        model = self.model if weight_ablation is None else deepcopy(self.model)
        with base._cpu() as torch:
            _memory(c["config"], len(rows), len(c["codec"]["target_vocabulary"]), sum(p.numel() for p in model.parameters()))
            if weight_ablation:
                with torch.no_grad():
                    for name, parameter in model.named_parameters():
                        if (weight_ablation == "zero_projection" and name.startswith("projection_")) or (
                            weight_ablation == "zero_condition" and name.startswith("condition.")) or (
                            weight_ablation == "zero_decoder" and name.startswith(("decoder.", "output."))):
                            parameter.zero_()
            results = _generate(torch, model, rows, c["codec"]["target_vocabulary"], c["config"], c["normalizer"])
        for row in results:
            parsed = fidelity.parse_generated(row["generated_tokens"], ended=row["ended"])
            candidate, reason = None, parsed["error"]
            if parsed["json_valid"]:
                try:
                    candidate = validate_target(c["domain_id"], parsed["candidate"])["canonical_ir"]
                except (ValueError, TypeError, KeyError, RecursionError) as exc:
                    reason = str(exc)[:512]
            row.update(candidate_ir=candidate, status="unqualified_candidate" if candidate is not None else "invalid_generated_output",
                reason=reason, weights_sha256=c["weights_sha256"], weight_ablation=weight_ablation, continue_planning=True)
        _guard()
        return {"schema": SCHEMA, "domain_id": c["domain_id"], "dimension": DIMENSION, "rows": results, **FALSE}


def evaluate(checkpoint, rows):
    runtime = Runtime(checkpoint)
    expected = base._rows(checkpoint["domain_id"], rows, training=True)
    inferred = runtime.infer([{k: row[k] for k in ("id", "source_text", "embedding")} for row in expected])
    inferred["fidelity"] = _generated_metrics(checkpoint["domain_id"], inferred["rows"], expected)
    return inferred


def load_checkpoint(path, *, expected_sha256, expected_domain):
    path = Path(path)
    _require(path.is_file() and not path.is_symlink() and 0 < path.stat().st_size <= base.MAX_BYTES, "bounded checkpoint required")
    raw = path.read_bytes()
    _require(hashlib.sha256(raw).hexdigest() == expected_sha256, "checkpoint bytes differ")
    checkpoint = base._parse(raw)
    _require(type(checkpoint) is dict and checkpoint.get("domain_id") == expected_domain, "checkpoint belongs to another domain")
    return Runtime(checkpoint)


__all__ = ["SCHEMA", "DIMENSION", "DOMAINS", "Runtime", "train", "evaluate", "load_checkpoint", "validate_target", "digest"]
