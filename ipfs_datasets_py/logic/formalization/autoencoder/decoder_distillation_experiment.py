"""Bounded, development-only decoder continuation and same-codec distillation.

This owner does not construct embeddings, qualify teachers, decode native logic,
or emit production checkpoints. The caller supplies verified representations and
the original complete token targets. Every trial starts a fresh optimizer. An
expanded output budget belongs only to the new experimental generation; encoder
context, vocabulary and published checkpoint loaders are not changed.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
import re
import time

SCHEMA = "decoder-distillation-development/v1"
_SHA = re.compile(r"[0-9a-f]{64}\Z")
FALSE = dict(qualified=False, admitted=False, proof_authority=False,
             source_semantics_verified=False, production_checkpoint=False)


def _require(condition, reason):
    if not condition:
        raise ValueError(reason)


def _raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(_raw(value)).hexdigest()


def _torch():
    import torch
    _require(torch.get_num_threads() == 1, "reserve one CPU and set torch.set_num_threads(1)")
    return torch


def bind_model(model, *, dimension):
    """Return a private adapter; no attribute or parameter of ``model`` changes."""
    torch = _torch()
    _require(type(dimension) is int and dimension in (8, 384, 768), "explicit supported input dimension required")
    _require(isinstance(model, torch.nn.Module) and all(callable(getattr(model, name, None))
        for name in ("project", "start", "next_logits")), "numerical decoder protocol required")

    class BoundDecoder(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.body = deepcopy(model)
            self.dimension = dimension

        def project(self, inputs):
            return self.body.project(inputs)

        def start(self, projected):
            return self.body.start(projected)

        def next_logits(self, tokens, hidden):
            return self.body.next_logits(tokens, hidden)

    return BoundDecoder()


def tensor_digest(model):
    """Exact names, dtypes, shapes and contiguous bytes, including signed zero."""
    state = hashlib.sha256()
    for name, tensor in sorted(model.state_dict().items()):
        state.update(_raw([name, str(tensor.dtype), list(tensor.shape)]))
        state.update(tensor.detach().cpu().contiguous().numpy().tobytes())
    return state.hexdigest()


def _config(options):
    result = dict(epochs=100, max_optimizer_steps=1000, max_seconds=30., batch_size=16,
        seed=1729, learning_rate=.001, weight_decay=.01, max_grad_norm=1., alpha=.25,
        max_target_tokens=64, validation_interval=1, patience=12, plateau_patience=3,
        plateau_factor=.5, min_learning_rate_ratio=.05, max_memory_bytes=536870912,
        reconstruction_weight=.1, selection_policy="ce_with_baseline_nonregression",
        reconstruction_absolute_tolerance=1e-9, reconstruction_relative_tolerance=1e-6)
    _require(options is None or type(options) is dict and set(options) <= set(result), "unknown trial option")
    result.update(options or {})
    for name, low, high in (("epochs", 1, 2000), ("max_optimizer_steps", 1, 100000),
        ("batch_size", 1, 128), ("seed", 0, 2**31-1), ("max_target_tokens", 4, 1024),
        ("validation_interval", 1, 1000), ("patience", 0, 2000), ("plateau_patience", 1, 1000),
        ("max_memory_bytes", 1048576, 8589934592)):
        _require(type(result[name]) is int and low <= result[name] <= high, "invalid " + name)
    for name, low, high in (("max_seconds", 0., 3600.), ("learning_rate", 0., .1),
        ("max_grad_norm", 0., 100.), ("plateau_factor", 0., 1.),
        ("min_learning_rate_ratio", 0., 1.)):
        value = result[name]
        _require(type(value) in (int, float) and math.isfinite(value) and low < value <= high, "invalid " + name)
    for name, high in (("alpha", 100.), ("weight_decay", 1.), ("reconstruction_weight", 100.),
        ("reconstruction_absolute_tolerance", .1), ("reconstruction_relative_tolerance", .1)):
        value = result[name]
        _require(type(value) in (int, float) and math.isfinite(value) and 0 <= value <= high, "invalid " + name)
    _require(result["plateau_factor"] < 1, "plateau_factor must reduce learning rate")
    _require(result["selection_policy"] in ("ce_with_baseline_nonregression", "ce_only_diagnostic"),
        "invalid selection policy")
    return result


def _finite(torch, value):
    if isinstance(value, torch.Tensor):
        return bool(torch.isfinite(value).all())
    return type(value) in (tuple, list) and all(_finite(torch, part) for part in value)


def _model(model, torch):
    _require(isinstance(model, torch.nn.Module) and type(getattr(model, "dimension", None)) is int
        and model.dimension in (8, 384, 768), "model must bind its actual input dimension")
    _require(all(callable(getattr(model, name, None)) for name in ("project", "start", "next_logits")),
        "decoder protocol required")
    _require(bool(list(model.parameters())), "model parameters required")
    for tensor in model.state_dict().values():
        _require(tensor.device.type == "cpu" and (not tensor.is_floating_point() or tensor.dtype == torch.float32)
            and _finite(torch, tensor), "finite CPU float32 model required")


def _validate(codec, transform, lineage, dimension):
    _require(type(codec) is dict and type(codec.get("target_vocabulary")) is list, "explicit codec required")
    vocabulary = codec["target_vocabulary"]
    _require(4 <= len(vocabulary) <= 4096 and vocabulary[:3] == ["<pad>", "<bos>", "<eos>"]
        and all(type(token) is str and 0 < len(token) <= 16384 for token in vocabulary)
        and len(set(vocabulary)) == len(vocabulary) and len(_raw(codec)) <= 4194304, "invalid shared codec")
    fields = {"teacher_checkpoint_sha256", "teacher_codec_sha256", "input_provenance_sha256",
              "domain", "teacher_lineage", "student_lineage", "teacher_output_limit", "student_role"}
    _require(type(lineage) is dict and set(lineage) == fields, "closed development lineage required")
    for name in ("teacher_checkpoint_sha256", "teacher_codec_sha256", "input_provenance_sha256"):
        _require(type(lineage[name]) is str and _SHA.fullmatch(lineage[name]), "invalid " + name)
    _require(lineage["teacher_codec_sha256"] == digest(codec), "teacher/student codec identity differs")
    for name in ("domain", "teacher_lineage", "student_lineage"):
        _require(type(lineage[name]) is str and 0 < len(lineage[name]) <= 256, "invalid " + name)
    _require(type(lineage["teacher_output_limit"]) is int and 4 <= lineage["teacher_output_limit"] <= 1024,
        "actual teacher output limit required")
    _require(lineage["student_role"] in ("learned_formula_sidecar", "source_conditioned_decoder"), "invalid student role")
    _require(dimension != 8 or lineage["student_role"] == "learned_formula_sidecar",
        "historical linguistic codec is not a trainable neural decoder")
    _require(type(transform) is dict and set(transform) == {"mode", "mean", "scale", "origin"}
        and transform["origin"] == "training_only" and transform["mode"] in ("none", "center_rms"),
        "reuse an explicit training-only input transform")
    _vector(transform["mean"], dimension)
    _require(type(transform["scale"]) in (int, float) and math.isfinite(transform["scale"])
        and .01 <= transform["scale"] <= 1e8, "invalid input scale")
    if transform["mode"] == "none":
        _require(transform["mean"] == [0.] * dimension and transform["scale"] == 1., "identity transform differs")
    return vocabulary


def _vector(value, dimension):
    _require(type(value) is list and len(value) == dimension and all(type(item) in (int, float)
        and math.isfinite(item) and abs(item) <= 1e8 for item in value), "exact finite input width required")


def _rows(rows, dimension, vocabulary, cap):
    _require(type(rows) is list and 1 <= len(rows) <= 4096, "bounded nonempty rows required")
    ids, sources = set(), set()
    for row in rows:
        _require(type(row) is dict and set(row) == {"id", "source_text", "input", "target_ids"}, "closed complete row required")
        _require(type(row["id"]) is str and 0 < len(row["id"]) <= 512 and row["id"] not in ids, "unique bounded row ID required")
        source = row["source_text"]
        _require(type(source) is str and 0 < len(source) <= 32768 and bool(source.strip()), "bounded source provenance required")
        normalized = " ".join(source.casefold().split())
        _require(normalized not in sources, "duplicate normalized source")
        ids.add(row["id"]); sources.add(normalized)
        _vector(row["input"], dimension)
        tokens = row["target_ids"]
        _require(type(tokens) is list and 3 <= len(tokens) <= cap and tokens[0] == 1 and tokens[-1] == 2
            and all(type(token) is int for token in tokens)
            and all(type(token) is int and 3 <= token < len(vocabulary) for token in tokens[1:-1]),
            "complete BOS/content/EOS target must fit cap without truncation")
    _require(len(_raw(rows)) <= 67108864, "row serialization exceeds memory bound")
    return ids, sources


def _batch(torch, rows, transform):
    raw = torch.tensor([row["input"] for row in rows], dtype=torch.float32)
    data = (raw - torch.tensor(transform["mean"], dtype=torch.float32)) / transform["scale"]
    width = max(len(row["target_ids"]) for row in rows)
    labels = torch.tensor([row["target_ids"] + [0] * (width-len(row["target_ids"])) for row in rows], dtype=torch.long)
    return data, labels


def _source_context_kwargs(torch, rows, contexts, transform):
    """Build explicit source-only tensors; absent sidecars preserve the old path."""
    if contexts is None:
        return {}
    from . import clause_source_context
    return {"source_context": clause_source_context.batch_source_context(torch, rows, contexts, transform)}


def _logits(torch, model, data, prefix, vocabulary_size, *, source_context=None):
    projected = model.project(data)
    _require(projected.shape == data.shape and _finite(torch, projected), "invalid reconstructed input")
    logits, hidden = model.next_logits(prefix, model.start(projected,
        **({} if source_context is None else {"source_context": source_context})))
    _require(tuple(logits.shape) == (*prefix.shape, vocabulary_size) and _finite(torch, logits)
        and _finite(torch, hidden), "decoder vocabulary, shape or finite-state mismatch")
    return projected, logits


def _loss(torch, student_logits, teacher_logits, labels, alpha):
    """Both models see the identical complete reference prefix; padding is masked."""
    mask = labels != 0
    ce = torch.nn.functional.cross_entropy(student_logits.flatten(0, 1), labels.flatten(),
        ignore_index=0, reduction="sum") / mask.sum()
    kl = ce.new_zeros(())
    if teacher_logits is not None:
        _require(teacher_logits.shape == student_logits.shape, "teacher/student logit support differs")
        kl_tokens = torch.nn.functional.kl_div(torch.log_softmax(student_logits, -1),
            torch.softmax(teacher_logits.detach(), -1), reduction="none").sum(-1)
        kl = kl_tokens[mask].mean()
    return ce + alpha * kl, ce, kl


def _greedy(torch, model, data, cap, size, deadline, *, source_context=None):
    projected = model.project(data)
    _require(projected.shape == data.shape and _finite(torch, projected), "invalid reconstructed input")
    hidden = model.start(projected, **({} if source_context is None else {"source_context": source_context}))
    current = torch.ones((len(data), 1), dtype=torch.long)
    outputs = [[] for _ in data]
    statuses = ["output_limit"] * len(data)
    active = [True] * len(data)
    for _ in range(cap - 1):
        if time.monotonic() >= deadline:
            return None
        logits, hidden = model.next_logits(current, hidden)
        _require(tuple(logits.shape) == (len(data), 1, size) and _finite(torch, logits)
            and _finite(torch, hidden), "invalid generation state")
        chosen = logits[:, -1].argmax(-1).tolist()
        for index, token in enumerate(chosen):
            if not active[index]:
                continue
            if token in (0, 1, 2):
                statuses[index] = "eos" if token == 2 else "invalid_special_token"
                active[index] = False
            else:
                outputs[index].append(token)
        if not any(active):
            break
        current = torch.tensor(chosen, dtype=torch.long).unsqueeze(1)
    if time.monotonic() >= deadline:
        return None
    return projected, outputs, statuses


def _evaluate(torch, model, rows, transform, config, size, deadline, *, source_contexts=None):
    predictions, ce_sum, token_count, error_sum, coordinates = [], 0., 0, 0., 0
    model.eval()
    with torch.inference_mode():
        for start in range(0, len(rows), config["batch_size"]):
            if time.monotonic() >= deadline:
                return None
            part = rows[start:start+config["batch_size"]]
            data, labels = _batch(torch, part, transform)
            context_kwargs = _source_context_kwargs(torch, part, source_contexts, transform)
            _, logits = _logits(torch, model, data, labels[:, :-1], size, **context_kwargs)
            ce = torch.nn.functional.cross_entropy(logits.flatten(0, 1), labels[:, 1:].flatten(),
                ignore_index=0, reduction="sum")
            _require(_finite(torch, ce), "nonfinite validation cross-entropy reduction")
            ce_sum += float(ce)
            token_count += int((labels[:, 1:] != 0).sum())
            generated = _greedy(torch, model, data, config["max_target_tokens"], size, deadline, **context_kwargs)
            if generated is None:
                return None
            projected, tokens, statuses = generated
            reconstructed = projected * transform["scale"] + torch.tensor(transform["mean"], dtype=torch.float32)
            _require(_finite(torch, reconstructed), "nonfinite reconstructed raw input")
            raw = torch.tensor([row["input"] for row in part], dtype=torch.float32)
            squared_error = (reconstructed - raw).square().sum()
            _require(_finite(torch, squared_error), "nonfinite validation reconstruction reduction")
            error_sum += float(squared_error); coordinates += raw.numel()
            for row, sequence, status, vector in zip(part, tokens, statuses, reconstructed.tolist()):
                predictions.append(dict(id=row["id"], token_ids=sequence, generation_status=status,
                    eos_reached=status == "eos", exact_target=status == "eos" and sequence == row["target_ids"][1:-1],
                    reconstructed_input=vector))
    if time.monotonic() >= deadline:
        return None
    return dict(token_cross_entropy=ce_sum/token_count, target_token_count=token_count, count=len(rows),
        exact_targets=sum(row["exact_target"] for row in predictions),
        eos_count=sum(row["eos_reached"] for row in predictions),
        output_limit_count=sum(row["generation_status"] == "output_limit" for row in predictions),
        invalid_special_token_count=sum(row["generation_status"] == "invalid_special_token" for row in predictions),
        reconstructed_input_mse=error_sum/coordinates, predictions=predictions,
        complete=True, generation_teacher_forced=False, ce_teacher_forced=True)


def _selection(candidate, baseline, incumbent, config):
    """CE progress and generation/reconstruction guards are distinct signals."""
    reasons = []
    if not candidate["token_cross_entropy"] < incumbent["token_cross_entropy"]:
        reasons.append("reference_ce_not_improved")
    if config["selection_policy"] == "ce_with_baseline_nonregression":
        for key in ("exact_targets", "eos_count"):
            if candidate[key] < baseline[key]:
                reasons.append(key + "_below_baseline")
            if candidate[key] < incumbent[key] and incumbent[key] != baseline[key]:
                reasons.append(key + "_below_selected")
        for key in ("output_limit_count", "invalid_special_token_count"):
            if candidate[key] > baseline[key]:
                reasons.append(key + "_above_baseline")
            if candidate[key] > incumbent[key] and incumbent[key] != baseline[key]:
                reasons.append(key + "_above_selected")
        tolerance = config["reconstruction_absolute_tolerance"] + \
            config["reconstruction_relative_tolerance"] * abs(baseline["reconstructed_input_mse"])
        if candidate["reconstructed_input_mse"] > baseline["reconstructed_input_mse"] + tolerance:
            reasons.append("reconstructed_input_mse_above_baseline")
    return not reasons, reasons


def _curriculum(value, rows, config):
    ids = {row["id"] for row in rows}
    if value is None:
        return [dict(name="all_training_rows", training_ids=[row["id"] for row in rows], epochs=config["epochs"])]
    _require(type(value) is list and 1 <= len(value) <= 16, "bounded nonempty curriculum required")
    seen, previous, epochs = set(), set(), 0
    for stage in value:
        _require(type(stage) is dict and set(stage) == {"name", "training_ids", "epochs"}, "closed curriculum stage required")
        _require(type(stage["name"]) is str and 0 < len(stage["name"]) <= 128
            and stage["name"] not in seen, "unique bounded stage name required")
        names = stage["training_ids"]
        _require(type(names) is list and 1 <= len(names) <= len(rows)
            and all(type(name) is str and name in ids for name in names)
            and len(set(names)) == len(names), "curriculum must use existing unique training IDs")
        _require(previous <= set(names), "curriculum training IDs must be cumulative")
        _require(type(stage["epochs"]) is int and 1 <= stage["epochs"] <= 2000, "invalid stage epoch count")
        seen.add(stage["name"]); previous = set(names); epochs += stage["epochs"]
    _require(previous == ids, "final curriculum stage must include all training IDs")
    _require(epochs <= 2000, "curriculum total epoch bound exceeded")
    config["epochs"] = epochs
    return deepcopy(value)


def _optimizer_state(model, optimizer):
    """Moment bytes and steps identify uninterrupted Adam state across stages."""
    sha, steps = hashlib.sha256(), {}
    for name, parameter in model.named_parameters():
        state = optimizer.state.get(parameter)
        if not state:
            continue
        steps[name] = int(state["step"].item())
        for field, value in sorted(state.items()):
            sha.update(_raw([name, field, str(value.dtype), list(value.shape)]))
            sha.update(value.detach().cpu().contiguous().numpy().tobytes())
    return dict(moment_state_sha256=sha.hexdigest(), parameter_steps=steps)


def evaluate_model(model, validation_rows, *, codec, input_transform, lineage,
                   max_target_tokens, max_seconds, batch_size=16, max_memory_bytes=536870912,
                   source_contexts=None):
    """Evaluate fixed experimental weights at an explicit output-stop budget.

    Generation receives input vectors and, when explicitly provided, source-only
    clause vectors and a source-derived padding mask. References are used for separate
    teacher-forced CE and post-generation token equality. This API neither fits
    nor selects weights; repeated caps are readout/cost comparisons, not fresh
    training arms. Original model tensors and training flags remain untouched.
    """
    started = time.monotonic()
    config = _config(dict(max_target_tokens=max_target_tokens, max_seconds=max_seconds,
        batch_size=batch_size, max_memory_bytes=max_memory_bytes, alpha=0.))
    deadline = started + config["max_seconds"]
    torch = _torch()
    _model(model, torch)
    size = len(_validate(codec, input_transform, lineage, model.dimension))
    _rows(validation_rows, model.dimension, codec["target_vocabulary"], config["max_target_tokens"])
    if source_contexts is not None:
        from . import clause_source_context
        clause_source_context.validate_contexts(validation_rows, source_contexts)
    parameter_bytes = sum(tensor.numel() * tensor.element_size() for tensor in model.state_dict().values())
    width = max(len(row["target_ids"]) for row in validation_rows)
    estimate = 4 * parameter_bytes + 8 * config["batch_size"] * width * size * 4 + \
        4 * len(validation_rows) * model.dimension
    if source_contexts is not None:
        estimate += 16 * config["batch_size"] * 8 * model.dimension * 4
        estimate += len(_raw(source_contexts))
    _require(estimate <= config["max_memory_bytes"], "evaluation tensor estimate exceeds explicit memory budget")
    before = tensor_digest(model)
    modes = {name: module.training for name, module in model.named_modules()}
    private = deepcopy(model).eval()
    result = _evaluate(torch, private, validation_rows, input_transform, config, size, deadline,
        **({} if source_contexts is None else {"source_contexts": source_contexts}))
    _require(tensor_digest(model) == before and tensor_digest(private) == before, "evaluation changed weights")
    _require({name: module.training for name, module in model.named_modules()} == modes, "evaluation changed caller modes")
    predictions = [] if result is None else deepcopy(result["predictions"])
    metrics = None if result is None else {key: value for key, value in result.items() if key != "predictions"}
    codec_sha, transform_sha, rows_sha = digest(codec), digest(input_transform), digest(validation_rows)
    elapsed = time.monotonic() - started
    evaluated = dict(report=dict(schema=SCHEMA, operation="fixed_weights_output_budget_evaluation",
        scope="exposed_development_only", lineage=deepcopy(lineage), input_dimension=model.dimension,
        model_weights_sha256=before, codec_sha256=codec_sha, input_transform_sha256=transform_sha,
        validation_rows_sha256=rows_sha, max_target_tokens=max_target_tokens,
        batch_size=batch_size, elapsed_seconds=elapsed, sample_count=len(validation_rows),
        wall_seconds_per_span=elapsed/len(validation_rows), spans_per_wall_second=len(validation_rows)/max(elapsed, 1e-12)
            if result is not None else None,
        timing_scope="bounded_validation_teacher_forced_ce_and_target_free_generation_including_copy_and_identity_checks",
        complete=result is not None, stopped_reason="complete" if result is not None else "deadline_during_evaluation",
        metrics=metrics, optimizer_steps=0, weight_selection_performed=False,
        generation_temperature=0, generation_target_access=False, full_targets_truncated=False,
        encoder_context_changed=False, published_parent_unchanged=True,
        lineage_hashes_are_caller_declarations=True, teacher_qualification="not_established",
        tensor_memory_estimate_bytes=estimate, memory_estimate_excludes_python_import_allocator_rss=True,
        deadline_cooperative=True, **FALSE), predictions=predictions)
    if source_contexts is not None:
        evaluated["report"].update(source_contexts_sha256=digest(source_contexts),
            source_context_schema=clause_source_context.SCHEMA, source_context_target_access=False)
    return evaluated


def run_trial(teacher, train_rows, validation_rows, *, codec, input_transform, lineage,
              config=None, student=None, curriculum=None):
    """Train a fresh experimental student; caller remains responsible for native gates.

    ``teacher`` and optional ``student`` are private, dimension-bound numerical
    modules (see :func:`bind_model`). Rows carry verified input vectors and full
    shared-codec token IDs. Lineage hashes are caller declarations, not proof of
    teacher qualification. The returned state dictionary belongs to this
    experimental owner only; it cannot be substituted into an old checkpoint.
    """
    started = time.monotonic()
    config = _config(config)
    deadline = started + config["max_seconds"]
    torch = _torch()
    _model(teacher, torch)
    if student is not None:
        _model(student, torch)
        _require(student.dimension == teacher.dimension, "teacher/student input dimensions differ")
    size = len(_validate(codec, input_transform, lineage, teacher.dimension))
    train_ids, train_sources = _rows(train_rows, teacher.dimension, codec["target_vocabulary"], config["max_target_tokens"])
    tune_ids, tune_sources = _rows(validation_rows, teacher.dimension, codec["target_vocabulary"], config["max_target_tokens"])
    _require(not train_ids & tune_ids and not train_sources & tune_sources, "training/validation split overlap")
    stages = _curriculum(curriculum, train_rows, config)
    if config["alpha"]:
        _require(all(len(row["target_ids"]) <= lineage["teacher_output_limit"] for row in train_rows),
            "distillation target exceeds actual teacher output limit")
    # Conservative tensor work estimate, not a process RSS or external-resource lease.
    parameters = sum(tensor.numel() * tensor.element_size() for tensor in teacher.state_dict().values())
    parameters += sum(tensor.numel() * tensor.element_size() for tensor in
        (student if student is not None else teacher).state_dict().values())
    width = max(len(row["target_ids"]) for row in (*train_rows, *validation_rows))
    estimate = 12 * parameters + 16 * config["batch_size"] * width * size * 4 + \
        4 * (len(train_rows)+len(validation_rows)) * teacher.dimension
    _require(estimate <= config["max_memory_bytes"], "trial tensor estimate exceeds explicit memory budget")
    teacher_before = tensor_digest(teacher)
    teacher_modes = {name: module.training for name, module in teacher.named_modules()}
    source_student = student if student is not None else teacher
    source_student_digest = tensor_digest(source_student)
    frozen_teacher = deepcopy(teacher).eval()
    for parameter in frozen_teacher.parameters():
        parameter.requires_grad_(False)
    working = deepcopy(source_student)
    initial_digest = tensor_digest(working)
    _require(initial_digest == source_student_digest, "fresh student copy differs")
    trainable = [parameter for parameter in working.parameters() if parameter.requires_grad]
    _require(bool(trainable), "no trainable student parameters")
    trainable_names = [name for name, parameter in working.named_parameters() if parameter.requires_grad]
    frozen_names = [name for name, parameter in working.named_parameters() if not parameter.requires_grad]
    frozen_tensors = {name: parameter.detach().cpu().contiguous().numpy().tobytes()
        for name, parameter in working.named_parameters() if not parameter.requires_grad}
    optimizer = torch.optim.AdamW(trainable, lr=config["learning_rate"], weight_decay=config["weight_decay"], foreach=False)
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer, mode="min", factor=config["plateau_factor"],
        patience=config["plateau_patience"], min_lr=config["learning_rate"] * config["min_learning_rate_ratio"])
    generator = torch.Generator().manual_seed(config["seed"])
    baseline = _evaluate(torch, working, validation_rows, input_transform, config, size, deadline)
    selected = baseline
    best_state = {name: tensor.detach().clone() for name, tensor in working.state_dict().items()}
    selected_epoch = 0 if baseline is not None else None
    steps = presentations = tokens_presented = 0
    history, stale, stopped = [], 0, "epochs_completed"
    stage_reports = [dict(name=stage["name"], training_row_count=len(stage["training_ids"]),
        training_ids_sha256=digest(stage["training_ids"]), planned_epochs=stage["epochs"],
        completed_epochs=0, optimizer_steps=0, training_row_presentations=0,
        optimizer_state_start=None, optimizer_state_end=None, status="not_started") for stage in stages]
    epoch_plan = [(stage_index, local_epoch) for stage_index, stage in enumerate(stages)
        for local_epoch in range(1, stage["epochs"]+1)]
    rows_by_id = {row["id"]: row for row in train_rows}
    if baseline is None:
        stopped = "deadline_before_complete_baseline"
    else:
        for epoch, (stage_index, stage_epoch) in enumerate(epoch_plan, 1):
            stage, stage_report = stages[stage_index], stage_reports[stage_index]
            current_rows = [rows_by_id[row_id] for row_id in stage["training_ids"]]
            if stage_report["status"] == "not_started":
                stage_report.update(status="started", optimizer_step_start=steps,
                    optimizer_state_start=_optimizer_state(working, optimizer))
            before_steps, before_presentations = steps, presentations
            complete_epoch, ce_total, kl_total, mse_total, batches = True, 0., 0., 0., 0
            working.train()
            for offset in range(0, len(current_rows), config["batch_size"]):
                if offset == 0:
                    order = torch.randperm(len(current_rows), generator=generator).tolist()
                if time.monotonic() >= deadline or steps >= config["max_optimizer_steps"]:
                    complete_epoch = False
                    stopped = "deadline" if time.monotonic() >= deadline else "optimizer_step_limit"
                    break
                part = [current_rows[index] for index in order[offset:offset+config["batch_size"]]]
                data, labels = _batch(torch, part, input_transform)
                optimizer.zero_grad(set_to_none=True)
                projected, logits = _logits(torch, working, data, labels[:, :-1], size)
                teacher_logits = None
                if config["alpha"]:
                    with torch.no_grad():
                        _, teacher_logits = _logits(torch, frozen_teacher, data, labels[:, :-1], size)
                objective, ce, kl = _loss(torch, logits, teacher_logits, labels[:, 1:], config["alpha"])
                reconstruction_mse = (projected-data).square().mean() * input_transform["scale"]**2
                objective = objective + config["reconstruction_weight"] * reconstruction_mse
                _require(_finite(torch, objective), "nonfinite objective")
                if time.monotonic() >= deadline:
                    complete_epoch = False; stopped = "deadline"; break
                objective.backward()
                norm = torch.nn.utils.clip_grad_norm_(trainable, config["max_grad_norm"], error_if_nonfinite=True)
                if time.monotonic() >= deadline:
                    optimizer.zero_grad(set_to_none=True)
                    complete_epoch = False; stopped = "deadline"; break
                optimizer.step()
                _require(all(_finite(torch, parameter) for parameter in working.parameters()), "nonfinite updated weights")
                steps += 1; presentations += len(part); tokens_presented += int((labels[:, 1:] != 0).sum())
                ce_total += float(ce.detach()); kl_total += float(kl.detach())
                mse_total += float(reconstruction_mse.detach()); batches += 1
            observed = None
            accepted, rejection_reasons = False, []
            should_validate = complete_epoch and (epoch % config["validation_interval"] == 0
                or stage_epoch == stage["epochs"] or epoch == config["epochs"])
            if should_validate:
                observed = _evaluate(torch, working, validation_rows, input_transform, config, size, deadline)
                if observed is None:
                    stopped = "deadline_during_validation"
                    rejection_reasons = ["validation_incomplete"]
                else:
                    scheduler.step(observed["token_cross_entropy"])
                    accepted, rejection_reasons = _selection(observed, baseline, selected, config)
                    if accepted:
                        candidate_state = {name: tensor.detach().clone() for name, tensor in working.state_dict().items()}
                        if time.monotonic() >= deadline:
                            accepted = False
                            rejection_reasons = ["deadline_before_selection_commit"]
                            stopped = "deadline_before_selection_commit"
                        else:
                            selected, selected_epoch, stale = observed, epoch, 0
                            best_state = candidate_state
                    else:
                        stale += 1
            stage_report["completed_epochs"] += int(complete_epoch)
            stage_report["optimizer_steps"] += steps-before_steps
            stage_report["training_row_presentations"] += presentations-before_presentations
            stage_report.update(optimizer_step_end=steps, optimizer_state_end=_optimizer_state(working, optimizer),
                status="complete" if stage_report["completed_epochs"] == stage["epochs"] else "partial")
            history.append(dict(epoch=epoch, stage=stage["name"], stage_epoch=stage_epoch,
                stage_training_row_count=len(current_rows), complete_epoch=complete_epoch, optimizer_steps=steps,
                learning_rate=float(optimizer.param_groups[0]["lr"]),
                mean_minibatch_reference_ce=ce_total/batches if batches else None,
                mean_minibatch_diagnostic_kl=kl_total/batches if batches else None,
                mean_minibatch_reconstructed_input_mse=mse_total/batches if batches else None,
                validation=None if observed is None else {k: v for k, v in observed.items() if k != "predictions"},
                accepted=accepted, rejection_reasons=rejection_reasons, selected_epoch=selected_epoch))
            if not complete_epoch or (should_validate and observed is None) or stopped == "deadline_before_selection_commit":
                break
            if config["patience"] and stale >= config["patience"]:
                stopped = "validation_patience"; break
            if steps >= config["max_optimizer_steps"]:
                stopped = "optimizer_step_limit"; break
    _require(tensor_digest(teacher) == teacher_before and tensor_digest(frozen_teacher) == teacher_before,
        "teacher tensors changed")
    _require({name: module.training for name, module in teacher.named_modules()} == teacher_modes, "caller teacher modes changed")
    _require(tensor_digest(source_student) == source_student_digest, "caller student tensors changed")
    _require(all(parameter.detach().cpu().contiguous().numpy().tobytes() == frozen_tensors[name]
        for name, parameter in working.named_parameters() if name in frozen_tensors), "frozen student parameters changed")
    working.load_state_dict(best_state, strict=True)
    exported_state = {name: tensor.detach().cpu().clone() for name, tensor in best_state.items()}
    exported_predictions = [] if selected is None else deepcopy(selected["predictions"])
    codec_sha, transform_sha = digest(codec), digest(input_transform)
    train_sha, validation_sha, selected_sha = digest(train_rows), digest(validation_rows), tensor_digest(working)
    elapsed = time.monotonic() - started
    without_predictions = lambda result: None if result is None else {k: v for k, v in result.items() if k != "predictions"}
    report = dict(schema=SCHEMA, scope="exposed_development_only", lineage=deepcopy(lineage), config=deepcopy(config),
        input_dimension=teacher.dimension, codec_sha256=codec_sha, input_transform_sha256=transform_sha,
        training_rows_sha256=train_sha, validation_rows_sha256=validation_sha,
        teacher_weights_sha256=teacher_before, initial_student_weights_sha256=initial_digest,
        selected_student_weights_sha256=selected_sha, teacher_frozen_verified=True,
        shared_codec_and_reference_prefix=True, teacher_qualification="not_established",
        lineage_hashes_are_caller_declarations=True, distillation_temperature=1., generation_temperature=0,
        generation_target_access=False, encoder_context_changed=False, full_targets_truncated=False,
        output_limit_migration=dict(teacher=lineage["teacher_output_limit"], student=config["max_target_tokens"],
            experimental_generation_only=True, published_parent_unchanged=True),
        optimizer="fresh_adamw", optimizer_resumable=False, optimizer_instance_count=1,
        optimizer_reinitialized_between_stages=False, selected_epoch=selected_epoch,
        curriculum=deepcopy(stages), stage_reports=stage_reports,
        curriculum_validation_scope="fixed_complete_validation_rows_at_all_stages",
        trainable_parameter_names=trainable_names, frozen_parameter_names=frozen_names,
        frozen_student_parameters_verified=True,
        baseline_validation=without_predictions(baseline), selected_validation=without_predictions(selected),
        selection=config["selection_policy"], selection_requires_complete_validation=True,
        selection_guard_reference="baseline_and_incumbent_generation_initial_baseline_reconstruction",
        selection_ce_reference="incumbent_selected_state",
        training_objective="reference_ce_plus_alpha_diagnostic_kl_plus_weighted_raw_input_reconstruction_mse",
        optimizer_steps=steps, training_row_presentations=presentations,
        training_token_presentations=tokens_presented, elapsed_seconds=elapsed,
        training_row_presentations_per_total_wall_second=presentations/max(elapsed, 1e-12),
        timing_scope="validation_generation_training_and_preparation_including_state_export",
        deadline_cooperative=True, stopped_reason=stopped, history=history,
        tensor_memory_estimate_bytes=estimate, memory_estimate_excludes_python_import_allocator_rss=True,
        **FALSE)
    return dict(state_dict=exported_state, report=report, predictions=exported_predictions)
