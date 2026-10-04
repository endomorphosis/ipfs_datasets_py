"""Explicit joint/frozen-projection training, separate from immutable v3.

The decoder architecture and all fidelity gates are inherited unchanged.
Only the frozen_parent_residual policy excludes the two projection modules
from optimization. No numerical artifact grants native or Lake authority.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import math
from pathlib import Path
import time

from . import domain_384_autoencoder_v3 as v3

base, fidelity, numerical = v3.base, v3.fidelity, v3.numerical
SCHEMA = "domain-384-typed-autoencoder/v4"
ARCHITECTURE, MODES = v3.ARCHITECTURE, v3.MODES
PROJECTION_POLICIES = ("joint", "frozen_parent_residual")
DIMENSION, DOMAINS, FALSE = v3.DIMENSION, v3.DOMAINS, dict(v3.FALSE)
_require, _raw, digest = v3._require, v3._raw, v3.digest
_SHAPES = {"hidden_size", "token_embedding_dim", "projection_width"}
PROJECTION_TENSORS = ("projection_down.weight", "projection_down.bias",
    "projection_up.weight", "projection_up.bias")

EvaluationDeadline = v3.EvaluationDeadline
_deadline, _normalizer, _conditioning = v3._deadline, v3._normalizer, v3._conditioning
_loss, _metrics, _generate = v3._loss, v3._metrics, v3._generate
_generated_metrics, _selection, _manifest = v3._generated_metrics, v3._selection, v3._manifest
_model, _transfer, _decoder_spec = v3._model, v3._transfer, v3._decoder_spec
_validate_lineage, validate_target = v3._validate_lineage, v3.validate_target


def _implementation():
    return {"runtime": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "v3_policy": v3._implementation()}


_IMPORTED = _implementation()


def _guard():
    v3._guard()
    _require(_implementation() == _IMPORTED, "source384 v4 producer changed after import")


def _config(config, parent):
    _require(type(config) is dict, "explicit projection_update_policy configuration required")
    options = deepcopy(config)
    policy = options.pop("projection_update_policy", None)
    _require(type(policy) is str and policy in PROJECTION_POLICIES, "explicit projection_update_policy required")
    return {**v3._config(options, parent), "projection_update_policy": policy}


def _projection_tensors(model):
    state = dict(model.named_parameters())
    _require(all(name in state for name in PROJECTION_TENSORS), "projection tensor inventory differs")
    for name in PROJECTION_TENSORS:
        tensor = state[name]
        _require(tensor.dtype == numerical._torch().float32 and bool(tensor.isfinite().all()),
                 "finite float32 projection tensors required")
        yield name, tensor.detach().contiguous()


def _projection_sha256(model):
    """Hash named, shaped float32 projection bytes, including signed zero."""
    result = hashlib.sha256()
    torch = numerical._torch()
    for name, tensor in _projection_tensors(model):
        metadata = _raw({"name": name, "shape": list(tensor.shape), "dtype": "float32"})
        result.update(len(metadata).to_bytes(8, "big")); result.update(metadata)
        payload = tensor.cpu().view(torch.uint8).numpy().tobytes()
        result.update(len(payload).to_bytes(8, "big")); result.update(payload)
    return result.hexdigest()


def _configure_projection(model, config):
    frozen = config["projection_update_policy"] == "frozen_parent_residual"
    for name, parameter in model.named_parameters():
        parameter.requires_grad_(not (frozen and name in PROJECTION_TENSORS))
    return [parameter for parameter in model.parameters() if parameter.requires_grad]


def _projection_snapshot(model, config):
    if config["projection_update_policy"] != "frozen_parent_residual":
        return None
    torch = numerical._torch()
    return {name: tensor.view(torch.uint8).clone() for name, tensor in _projection_tensors(model)}


def _verify_projection(model, snapshot):
    if snapshot is None:
        return
    torch = numerical._torch()
    # No serialization, CPU transfer or digest computation in the hot loop.
    parameters = dict(model.named_parameters())
    _require(set(snapshot) == set(PROJECTION_TENSORS), "frozen projection reference inventory differs")
    for name in PROJECTION_TENSORS:
        tensor = parameters[name]
        _require(not tensor.requires_grad and tensor.grad is None
            and torch.equal(tensor.detach().contiguous().view(torch.uint8), snapshot[name]),
            "frozen projection changed during training: " + name)


def _policy_record(model, config, inherited_sha256):
    frozen = config["projection_update_policy"] == "frozen_parent_residual"
    return {"schema": "source384-projection-update-policy/v1", "mode": config["projection_update_policy"],
        "tensor_names": list(PROJECTION_TENSORS), "inherited_projection_sha256": inherited_sha256,
        "selected_projection_sha256": _projection_sha256(model),
        "trainable_tensor_names": [name for name, value in model.named_parameters() if value.requires_grad],
        "frozen_tensor_names": [name for name, value in model.named_parameters() if not value.requires_grad],
        "frozen_projection_verified": frozen,
        "digest_scope": "ordered_named_shape_dtype_and_contiguous_float32_bytes/v1"}


def _validate_policy(model, config, record):
    _require(type(record) is dict and type(record.get("inherited_projection_sha256")) is str
        and base._SHA.fullmatch(record["inherited_projection_sha256"]), "invalid inherited projection digest")
    _require(type(record.get("frozen_projection_verified")) is bool, "projection verification flag must be boolean")
    expected = _policy_record(model, config, record["inherited_projection_sha256"])
    _require(record == expected, "projection policy, parameter inventory or weight provenance differs")
    if config["projection_update_policy"] == "frozen_parent_residual":
        _require(record["selected_projection_sha256"] == record["inherited_projection_sha256"],
                 "frozen projection differs from inherited projection")


def _validate_training_policy(model, config, report):
    expected = {
        "trainable_parameter_count": sum(p.numel() for p in model.parameters() if p.requires_grad),
        "frozen_parameter_count": sum(p.numel() for p in model.parameters() if not p.requires_grad),
        "frozen_projection_checks_after_optimizer_steps": report["optimizer_steps"]
            if config["projection_update_policy"] == "frozen_parent_residual" else 0}
    _require(report.get("projection_update_policy") == config["projection_update_policy"]
        and all(type(report.get(key)) is int and report[key] == value for key, value in expected.items()),
        "training projection policy or verification counts differ")


def _memory(config, rows, vocabulary, parameter_count=None, *, ablation_copy=False):
    result = v3._memory(config, rows, vocabulary, parameter_count, ablation_copy=ablation_copy)
    reference_bytes = 0
    if config["projection_update_policy"] == "frozen_parent_residual":
        shapes = _decoder_spec(config, vocabulary)["tensor_shapes"]
        reference_bytes = sum(math.prod(shapes[name]) * 4 for name in PROJECTION_TENSORS)
    result = {**result, "estimated_tensor_bytes": result["estimated_tensor_bytes"] + reference_bytes,
        "frozen_projection_reference_bytes": reference_bytes}
    _require(result["estimated_tensor_bytes"] <= config["memory_budget_bytes"],
             "estimated tensor reservation exceeds budget")
    return result


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
        memory = _memory(options, len(train_rows) + len(tune), len(vocabulary))
        model, lineage = _transfer(parent, codec, options)
        trainable = _configure_projection(model, options)
        inherited_projection_sha = _projection_sha256(model)
        frozen_projection = _projection_snapshot(model, options)
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
        optimizer = torch.optim.Adam(trainable, lr=options["learning_rate"])
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
                _verify_projection(model, frozen_projection)
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
        _verify_projection(model, frozen_projection)
        model.load_state_dict(best_state)
        _verify_projection(model, frozen_projection)
        projection_policy = _policy_record(model, options, inherited_projection_sha)
        _validate_policy(model, options, projection_policy)
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
            "whole_call_seconds": time.monotonic() - call_started,
            "projection_update_policy": options["projection_update_policy"],
            "trainable_parameter_count": sum(p.numel() for p in model.parameters() if p.requires_grad),
            "frozen_parameter_count": sum(p.numel() for p in model.parameters() if not p.requires_grad),
            "frozen_projection_checks_after_optimizer_steps": steps if frozen_projection is not None else 0}
        checkpoint = {"schema": SCHEMA, "domain_id": domain, "dimension": DIMENSION,
            "architecture": ARCHITECTURE, "decoder_spec": _decoder_spec(options, len(vocabulary)),
            "codec": codec, "config": options, "projection_policy": projection_policy,
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
    """Strict v4 loader with explicit conditioning and projection-update policies."""
    def __init__(self, checkpoint):
        _guard()
        required = {"schema", "domain_id", "dimension", "architecture", "codec", "config", "implementation",
            "parent_sha256", "parent_binding", "parent_context_limit", "lineage", "normalizer", "normalizer_sha256", "decoder_spec",
            "model_state", "weights_sha256", "training_manifest", "validation_manifest", "training", "projection_policy", *FALSE}
        _require(type(checkpoint) is dict and set(checkpoint) == required and checkpoint["schema"] == SCHEMA,
                 "closed v4 domain checkpoint required")
        _require(len(_raw(checkpoint)) <= base.MAX_BYTES, "checkpoint exceeds bound")
        _require(checkpoint["domain_id"] in DOMAINS and type(checkpoint["dimension"]) is int and checkpoint["dimension"] == DIMENSION,
                 "genuine 384D domain required")
        _require(all(checkpoint[k] is False for k in FALSE), "checkpoint cannot grant authority")
        _require(checkpoint["implementation"] == _implementation(), "v4 implementation pins differ")
        _require(checkpoint["architecture"] == ARCHITECTURE, "architecture differs")
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
        _require(checkpoint["decoder_spec"] == _decoder_spec(config, len(vocabulary)), "decoder mode, shape or parameter specification differs")
        _validate_lineage(checkpoint["lineage"], config)
        manifests = [checkpoint[name] for name in ("training_manifest", "validation_manifest")]
        for rows in manifests:
            _require(type(rows) is list and 1 <= len(rows) <= 4096, "invalid split manifest")
            seen = set()
            for row in rows:
                _require(type(row) is dict and set(row) == {"id", "source_sha256", "normalized_source_sha256", "embedding_sha256", "target_sha256"}
                    and type(row["id"]) is str and 0 < len(row["id"]) <= 256 and row["id"] not in seen
                    and all(type(row[k]) is str and base._SHA.fullmatch(row[k]) for k in row if k != "id"), "invalid split row")
                seen.add(row["id"])
        for key in ("id", "source_sha256", "normalized_source_sha256", "embedding_sha256"):
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
        _memory(config, 1, len(vocabulary))
        with base._cpu():
            model = _model(codec, config)
            _require(type(state) is dict and set(state) == set(model.state_dict()), "tensor names differ")
            model.load_state_dict({name: numerical._tensor(state[name], template, name)
                for name, template in model.state_dict().items()}, strict=True)
            _configure_projection(model, config)
            _validate_policy(model, config, checkpoint["projection_policy"])
            _validate_training_policy(model, config, training)
        self.checkpoint, self.model = deepcopy(checkpoint), model.eval()

    def describe(self):
        c = self.checkpoint
        return {"schema": SCHEMA, "domain_id": c["domain_id"], "dimension": DIMENSION,
            "architecture": c["architecture"], "source_conditioning": c["normalizer"]["mode"],
            "decoder_conditioning": c["config"]["decoder_conditioning"], "decoder_spec": deepcopy(c["decoder_spec"]),
            "projection_update_policy": c["config"]["projection_update_policy"], "projection_policy": deepcopy(c["projection_policy"]),
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
        _memory(c["config"], len(rows), len(c["codec"]["target_vocabulary"]), ablation_copy=weight_ablation is not None)
        model = self.model if weight_ablation is None else deepcopy(self.model)
        with base._cpu() as torch:
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


__all__ = ["SCHEMA", "ARCHITECTURE", "MODES", "PROJECTION_POLICIES", "DIMENSION", "DOMAINS", "Runtime", "train", "evaluate", "load_checkpoint", "validate_target", "digest"]
