"""Alignment-supervised full-weight continuation of a shared paired-copy checkpoint.

Children carry their own inert tensor JSON and implementation pins. Loading a
child does not require the parent file. Training reads the parent without
changing it, inherits every recurrent/attention/gate parameter, and transfers
lexical rows by token identity. Added training-only vocabulary rows copy the
parent's unknown-token row; no randomly initialized parameter reaches fitting.
The inherited lexical feature buffer stays frozen, as in the original model.

This backend predicts strings. Grammar, source alignment, semantic admission,
and formal projections remain the responsibility of the domain adapter.
"""
from __future__ import annotations

import math
from pathlib import Path
import time

from . import autoencoder_paired_copy as shared
from . import autoencoder_paired_copy_continuation as parent_backend
from . import autoencoder_copy_alignment as objective

SCHEMA = "shared-paired-copy-aligned-continuation/v2"
_require, _raw, _sha, _read, _json = shared._require, shared._raw, shared._sha, shared._read, shared._json
_FALSE = dict(shared._FALSE)
_INITIALIZATION = "all parent tensors inherited; added vocabulary rows copy parent unknown-token row"
_ROW_TENSORS = {"lexical", "embedding.weight", "output.weight", "output.bias"}


def _implementation():
    return {"aligned_backend_sha256": _sha(Path(__file__).read_bytes()),
            "alignment_objective_sha256": _sha(Path(objective.__file__).read_bytes()),
            **parent_backend._implementation()}


def _digest(value):
    return type(value) is str and shared.legacy._SHA.fullmatch(value) is not None


def _number(value, *, minimum=0, maximum=None):
    return (type(value) in (int, float) and math.isfinite(value) and value >= minimum
            and (maximum is None or value <= maximum))


def _vocabulary(value):
    _require(type(value) is list and 7 <= len(value) <= 4096 and
             value[:6] == list(shared.SPECIAL) and
             all(type(token) is str and 0 < len(token) <= 16384 for token in value) and
             len(set(value)) == len(value) and value[6:] == sorted(value[6:]) and
             all(shared.tokenize(token) == [token] for token in value[6:]),
             "invalid continuation vocabulary")


def _load_parent(descriptor):
    _require(type(descriptor) is dict, "shared paired-copy parent descriptor required")
    if descriptor.get("schema") == shared.SCHEMA:
        return shared.load_paired_copy(descriptor)
    if descriptor.get("schema") == parent_backend.SCHEMA:
        return parent_backend.load_paired_copy_continuation(descriptor)
    if descriptor.get("schema") == SCHEMA:
        return load_paired_copy_continuation(descriptor)
    raise ValueError("shared paired-copy or continuation parent checkpoint required")


def _transfer(torch, parent, config):
    """Materialize a complete transferred state before creating the optimizer."""
    prior = parent["model"].state_dict()
    indices = {token: index for index, token in enumerate(parent["config"]["vocabulary"])}
    mapping = torch.tensor([indices.get(token, 3) for token in config["vocabulary"]], dtype=torch.long)
    inherited = {name: tensor.index_select(0, mapping).clone() if name in _ROW_TENSORS
                 else tensor.clone() for name, tensor in prior.items()}
    # Module constructors allocate parameters, but every byte is overwritten by
    # transferred tensors before any forward pass or optimizer is created.
    model = shared._model(torch, config, inherited["lexical"].tolist())
    model.load_state_dict(inherited, strict=True)
    _require(all(torch.equal(value, model.state_dict()[name]) for name, value in inherited.items()),
             "full parent tensor transfer differs")
    return model, inherited


def train_paired_copy_continuation(training_pairs, tuning_pairs, *, parent_descriptor,
        output_dir, epochs=100, max_seconds=180, copy_dropout=0.20,
        learning_rate=0.0005, seed=1729, alignment_weight=0.1, coverage_weight=0.05):
    """Fit a standalone child from all parent weights, using training rows only.

    Parent vocabulary is retained. Only training pairs may add vocabulary;
    tuning is evaluated once after fitting and cannot choose weights or epochs.
    A fresh Adam state is used because original checkpoints contain no optimizer
    moments. ``max_seconds`` is checked at epoch boundaries, matching the shared
    training backend. The caller owns split provenance beyond pair identities.
    """
    import torch
    from .modal_autoencoder_cuda import _gradient_norm
    from .modal_autoencoder_batching import plan_gradient_accumulation

    objective_config = objective.validate_settings({"alignment_weight": alignment_weight, "coverage_weight": coverage_weight})
    train, tuning = shared.legacy._pairs(training_pairs), shared.legacy._pairs(tuning_pairs)
    _require(type(epochs) is int and 1 <= epochs <= 1000 and type(seed) is int and 0 <= seed < 2**31,
             "bounded integer continuation settings required")
    _require(_number(max_seconds, maximum=3600) and max_seconds > 0,
             "bounded continuation training deadline required")
    _require(_number(copy_dropout, maximum=0.75), "bounded continuation copy dropout required")
    _require(_number(learning_rate, maximum=0.05) and learning_rate > 0,
             "bounded continuation learning rate required")
    _require({row[0]["direction"] for row in train} == {"encode", "decode"},
             "both continuation training directions required")
    identities = lambda rows: {(row["direction"], tuple(source)) for row, source, _ in rows}
    _require(not identities(train) & identities(tuning), "training and tuning source overlap")
    _require(not {row[0]["id"] for row in train} & {row[0]["id"] for row in tuning},
             "training and tuning ID overlap")
    output = Path(output_dir).absolute()
    _require(not output.exists() and not output.is_symlink() and
             output.parent.resolve(strict=True) == output.parent,
             "fresh output under a canonical existing parent required")
    parent = _load_parent(parent_descriptor)
    parent_descriptor = dict(parent["descriptor"])
    parent_raw = _read(Path(parent_descriptor["path"]))
    _require(_sha(parent_raw) == parent_descriptor["sha256"], "parent changed before continuation")
    parent_vocabulary = parent["config"]["vocabulary"]
    additions = sorted({token for _, source, target in train for token in source + target}
                       - set(parent_vocabulary))
    vocabulary = list(shared.SPECIAL) + sorted(set(parent_vocabulary[6:]) | set(additions))
    _vocabulary(vocabulary)
    config = {**parent["config"], "schema": SCHEMA, "vocabulary": vocabulary,
              "copy_dropout": float(copy_dropout), "implementation": _implementation(),
              "alignment_objective": objective_config}
    parent_identity = {"schema": parent_descriptor["schema"],
        "artifact_sha256": parent_descriptor["sha256"],
        "weights_sha256": parent["training"]["final_state_sha256"],
        "config_sha256": _sha(_raw(parent["config"])),
        "vocabulary": list(parent_vocabulary),
        "lexical_lineage": parent["training"]["lexical_lineage"]}
    started = time.monotonic()
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(seed)
        model, inherited = _transfer(torch, parent, config)
        initial = _sha(_raw({name: tensor.tolist() for name, tensor in inherited.items()}))
        optimizer = torch.optim.Adam(model.parameters(), lr=float(learning_rate))
        generator = torch.Generator().manual_seed(seed)
        history, norms, calls, steps = [], [], 0, 0
        mask_counts = {direction: 0 for direction in ("encode", "decode")}
        batch_plan = plan_gradient_accumulation(len(train), microbatch_size=64)
        for _epoch in range(epochs):
            model.train()
            order = torch.randperm(len(train), generator=generator).tolist()
            weighted_loss, tokens_total = 0.0, 0
            for begin, end in batch_plan.ranges:
                rows = [train[index] for index in order[begin:end]]
                batch = objective.batch(torch, rows, vocabulary, generator=generator, dropout=float(copy_dropout))
                for direction, count in batch[-1].items():
                    mask_counts[direction] += count
                optimizer.zero_grad(set_to_none=True)
                loss, native_calls, token_count = objective.loss(torch, model, batch, objective_config)
                _require(bool(torch.isfinite(loss)), "nonfinite continuation training loss")
                loss.backward()
                gradient = _gradient_norm(torch, list(model.parameters()))
                _require(math.isfinite(gradient), "nonfinite continuation training gradient")
                torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0)
                optimizer.step()
                weighted_loss += float(loss.detach()) * token_count
                tokens_total += token_count
                calls += native_calls
                steps += 1
                norms.append(gradient)
            history.append(weighted_loss / tokens_total)
            if time.monotonic() - started >= max_seconds:
                break
        weights = {key: value.detach().tolist() for key, value in model.state_dict().items()}
        _require(weights["lexical"] == inherited["lexical"].tolist(), "frozen inherited lexical rows changed")
        changed = sorted(name for name, value in model.state_dict().items()
                         if not torch.equal(value, inherited[name]))
        tuning_metrics = shared._report(model, tuning, config)
    _require(_read(Path(parent_descriptor["path"])) == parent_raw, "parent changed during continuation")
    training = {"schema": SCHEMA, "epochs_requested": epochs, "epochs_completed": len(history),
        "optimizer_steps": steps, "native_kernel_calls": calls, "training_loss": history,
        "gradient_norm_max": max(norms), "seed": seed, "learning_rate": float(learning_rate),
        "training_seconds": time.monotonic() - started,
        "stopping": "epoch_limit" if len(history) == epochs else "wall_clock_budget_at_epoch_boundary",
        "training_pair_count": len(train), "tuning_pair_count": len(tuning),
        "training_pairs_sha256": _sha(_raw(training_pairs)), "tuning_pairs_sha256": _sha(_raw(tuning_pairs)),
        "initial_state_sha256": initial, "final_state_sha256": _sha(_raw(weights)),
        "parent": parent_identity, "lexical_lineage": parent["training"]["lexical_lineage"],
        "tuning": tuning_metrics, "new_parameters_initialization": _INITIALIZATION,
        "vocabulary_fit_scope": "parent_and_training_only", "added_vocabulary": additions,
        "inherited_token_count": len(parent_vocabulary), "parent_modified": False,
        "optimizer_state": "fresh_adam_no_parent_optimizer_state_available",
        "trainable_parameters": sorted(name for name, _ in model.named_parameters()),
        "changed_tensors": changed,
        "tuning_used_for_fit_or_selection": False,
        "copy_masked_types_by_direction": mask_counts, "copy_dropout_scope": "training_only",
        "inference_copy_strings": "current_input_tokens_only",
        "sample_memory_used": False, "training_source_bodies_persisted": False,
        "provider_calls": 0, "download_calls": 0, **_FALSE}
    package = {"schema": SCHEMA, "config": config, "weights": weights, "training": training, **_FALSE}
    raw = _raw(package)
    _require(len(raw) <= shared.MAX_BYTES, "continuation artifact exceeds byte bound")
    output.mkdir()
    candidate = output / "candidate.json"
    with candidate.open("xb") as stream:
        stream.write(raw)
    descriptor = {"schema": SCHEMA, "path": str(candidate), "sha256": _sha(raw)}
    load_paired_copy_continuation(descriptor)
    return descriptor


def _validate_lexical_lineage(lineage, config, parent_count):
    fields = {"present", "initializer_sha256", "parent_checkpoint_sha256", "inherited_width",
              "matched_tokens", "frozen", "parent_modified", "numeric_conversion"}
    _require(type(lineage) is dict and set(lineage) == fields and
             type(lineage["present"]) is bool and lineage["frozen"] is True and
             lineage["parent_modified"] is False and lineage["inherited_width"] == config["lexical_width"] and
             type(lineage["matched_tokens"]) is int and 0 <= lineage["matched_tokens"] <= parent_count and
             lineage["numeric_conversion"] == "float32 inference branch", "invalid inherited lexical lineage")
    for key in ("initializer_sha256", "parent_checkpoint_sha256"):
        _require(_digest(lineage[key]) if lineage["present"] else lineage[key] is None,
                 "invalid lexical parent digest")
    _require(lineage["present"] or lineage["matched_tokens"] == 0, "unexpected lexical inheritance")


def load_paired_copy_continuation(descriptor):
    """Validate a bounded standalone child without consulting the parent file."""
    import torch
    _require(type(descriptor) is dict and set(descriptor) == {"schema", "path", "sha256"},
             "closed paired continuation checkpoint descriptor required")
    _require(descriptor["schema"] == SCHEMA and _digest(descriptor["sha256"]) and
             type(descriptor["path"]) is str, "exact continuation schema and hash required")
    raw = _read(Path(descriptor["path"]))
    _require(_sha(raw) == descriptor["sha256"], "continuation checkpoint hash differs")
    package = _json(raw)
    _require(type(package) is dict and set(package) == {"schema", "config", "weights", "training", *_FALSE} and
             package["schema"] == SCHEMA and all(package[key] is False for key in _FALSE),
             "closed continuation package with no admission authority required")
    config, weights, training = package["config"], package["weights"], package["training"]
    _require(type(config) is dict and set(config) == {"schema", "architecture", "hidden_size", "embedding_dim",
        "lexical_width", "vocabulary", "token_pattern", "max_tokens", "copy_dropout", "copy_vocabulary_scope",
        "implementation", "device", "dtype", "alignment_objective"}, "closed continuation architecture required")
    _require(config["schema"] == SCHEMA and config["architecture"] == shared.ARCHITECTURE and
        config["implementation"] == _implementation() and config["token_pattern"] == shared.legacy.TOKEN_PATTERN and
        config["max_tokens"] == shared.MAX_TOKENS and config["copy_vocabulary_scope"] == "current_input_only" and
        config["device"] == "cpu" and config["dtype"] == "float32", "continuation architecture or implementation differs")
    _require(type(config["hidden_size"]) is int and 8 <= config["hidden_size"] <= 256 and
        type(config["embedding_dim"]) is int and 8 <= config["embedding_dim"] <= 128 and
        type(config["lexical_width"]) is int and 2 <= config["lexical_width"] <= 64 and
        _number(config["copy_dropout"], maximum=0.75), "invalid continuation dimensions or dropout")
    objective.validate_settings(config["alignment_objective"])
    _vocabulary(config["vocabulary"])
    with torch.random.fork_rng(devices=[]):
        model = shared._model(torch, config, [[0.0] * config["lexical_width"] for _ in config["vocabulary"]])
    expected = model.state_dict()
    _require(type(weights) is dict and set(weights) == set(expected), "continuation tensor names differ")
    tensors = {}
    for name, reference in expected.items():
        _require(shared._finite(weights[name]), "nonfinite continuation tensor")
        try:
            tensor = torch.tensor(weights[name], dtype=torch.float32)
        except (ValueError, TypeError) as exc:
            raise ValueError("invalid continuation tensor shape") from exc
        _require(tensor.shape == reference.shape and bool(torch.isfinite(tensor).all()),
                 "continuation tensor shape or range differs")
        tensors[name] = tensor
    fields = {"schema", "epochs_requested", "epochs_completed", "optimizer_steps", "native_kernel_calls",
        "training_loss", "gradient_norm_max", "seed", "learning_rate", "training_seconds", "stopping",
        "training_pair_count", "tuning_pair_count", "training_pairs_sha256", "tuning_pairs_sha256",
        "initial_state_sha256", "final_state_sha256", "parent", "lexical_lineage", "tuning",
        "new_parameters_initialization", "vocabulary_fit_scope", "added_vocabulary", "inherited_token_count",
        "parent_modified", "optimizer_state", "trainable_parameters", "changed_tensors",
        "tuning_used_for_fit_or_selection", "copy_masked_types_by_direction", "copy_dropout_scope",
        "inference_copy_strings", "sample_memory_used", "training_source_bodies_persisted",
        "provider_calls", "download_calls", *_FALSE}
    _require(type(training) is dict and set(training) == fields and training["schema"] == SCHEMA and
        training["final_state_sha256"] == _sha(_raw(weights)) and all(training[key] is False for key in
        (*_FALSE, "parent_modified", "tuning_used_for_fit_or_selection", "sample_memory_used",
         "training_source_bodies_persisted")), "continuation training evidence differs")
    _require(all(_digest(training[key]) for key in ("training_pairs_sha256", "tuning_pairs_sha256",
        "initial_state_sha256", "final_state_sha256")) and
        type(training["epochs_requested"]) is int and 1 <= training["epochs_requested"] <= 1000 and
        type(training["epochs_completed"]) is int and 1 <= training["epochs_completed"] <= training["epochs_requested"] and
        type(training["training_loss"]) is list and len(training["training_loss"]) == training["epochs_completed"] and
        all(_number(value) for value in training["training_loss"]) and
        all(type(training[key]) is int and 1 <= training[key] <= 8192 for key in ("training_pair_count", "tuning_pair_count")) and
        type(training["optimizer_steps"]) is int and
        training["optimizer_steps"] == training["epochs_completed"] * math.ceil(training["training_pair_count"] / 64) and
        type(training["native_kernel_calls"]) is int and training["native_kernel_calls"] == 3 * training["optimizer_steps"] and
        type(training["seed"]) is int and 0 <= training["seed"] < 2**31 and
        _number(training["learning_rate"], maximum=0.05) and training["learning_rate"] > 0 and
        all(_number(training[key]) for key in ("gradient_norm_max", "training_seconds")) and
        training["stopping"] == ("epoch_limit" if training["epochs_completed"] == training["epochs_requested"]
                                 else "wall_clock_budget_at_epoch_boundary") and
        all(type(training[key]) is int and training[key] == 0 for key in ("provider_calls", "download_calls")),
        "invalid continuation training counts or numerical evidence")
    _require(training["new_parameters_initialization"] == _INITIALIZATION and
        training["vocabulary_fit_scope"] == "parent_and_training_only" and
        training["copy_dropout_scope"] == "training_only" and
        training["inference_copy_strings"] == "current_input_tokens_only" and
        training["optimizer_state"] == "fresh_adam_no_parent_optimizer_state_available" and
        training["trainable_parameters"] == sorted(name for name, _ in model.named_parameters()) and
        type(training["changed_tensors"]) is list and
        all(type(name) is str for name in training["changed_tensors"]) and
        training["changed_tensors"] == sorted(set(training["changed_tensors"])) and
        set(training["changed_tensors"]) <= set(training["trainable_parameters"]),
        "invalid continuation transfer or training scope")
    counts = training["copy_masked_types_by_direction"]
    _require(type(counts) is dict and set(counts) == {"encode", "decode"} and
        all(type(value) is int and 0 <= value <= training["epochs_completed"] * training["training_pair_count"] * shared.MAX_TOKENS
            for value in counts.values()) and (config["copy_dropout"] > 0 or not any(counts.values())),
        "invalid train-only continuation masking evidence")
    parent = training["parent"]
    _require(type(parent) is dict and set(parent) == {"schema", "artifact_sha256", "weights_sha256",
        "config_sha256", "vocabulary", "lexical_lineage"} and parent["schema"] in (shared.SCHEMA, parent_backend.SCHEMA, SCHEMA) and
        all(_digest(parent[key]) for key in ("artifact_sha256", "weights_sha256", "config_sha256")),
        "invalid continuation parent lineage")
    _vocabulary(parent["vocabulary"])
    additions = sorted(set(config["vocabulary"]) - set(parent["vocabulary"]))
    _require(set(parent["vocabulary"]) <= set(config["vocabulary"]) and
        training["added_vocabulary"] == additions and type(training["inherited_token_count"]) is int and
        training["inherited_token_count"] == len(parent["vocabulary"]) and
        training["lexical_lineage"] == parent["lexical_lineage"], "continuation vocabulary or lexical transfer differs")
    _validate_lexical_lineage(training["lexical_lineage"], config, len(parent["vocabulary"]))
    if not additions:
        _require(training["initial_state_sha256"] == parent["weights_sha256"],
                 "unexpanded continuation initial state differs from parent")
    if not training["lexical_lineage"]["present"]:
        _require(not bool(tensors["lexical"].any()), "unexpected lexical inheritance")
    tuning = training["tuning"]
    _require(type(tuning) is dict and tuning.get("count") == training["tuning_pair_count"] and
        tuning.get("teacher_forcing") is False and all(tuning.get(key) is False for key in _FALSE),
        "invalid post-fit tuning evidence")
    model.load_state_dict(tensors, strict=True)
    model.eval()
    return {"descriptor": dict(descriptor), "config": config, "training": training, "model": model}


def infer_paired_copy_continuation(descriptor, source, direction, max_new_tokens=96, *, weight_ablation=None):
    loaded = load_paired_copy_continuation(descriptor)
    disabled = shared._ablate(loaded["model"], weight_ablation)
    return {**shared._generate(loaded["model"], loaded["config"], source, direction, max_new_tokens,
                              disable_copy=disabled),
        "checkpoint_weights_sha256": loaded["training"]["final_state_sha256"], "weight_ablation": weight_ablation}


def evaluate_paired_copy_continuation(descriptor, pairs, *, weight_ablation=None, max_new_tokens=96):
    loaded = load_paired_copy_continuation(descriptor)
    disabled = shared._ablate(loaded["model"], weight_ablation)
    return {**shared._report(loaded["model"], shared.legacy._pairs(pairs), loaded["config"],
                            max_new_tokens=max_new_tokens, disable_copy=disabled),
        "checkpoint_weights_sha256": loaded["training"]["final_state_sha256"], "weight_ablation": weight_ablation}


def infer_paired_copy_continuation_beam(descriptor, source, direction, *, beam_width=8,
                                       max_new_tokens=96, weight_ablation=None):
    """Generic learned alternatives; no grammar, source parser or target access.

    The search matches the frozen shared beam algorithm. It is additive here
    because that algorithm's public entrypoint loads only v1 checkpoints.
    """
    import torch
    _require(type(beam_width) is int and 1 <= beam_width <= 16, "beam width must be between 1 and 16")
    _require(type(max_new_tokens) is int and 1 <= max_new_tokens <= shared.MAX_TOKENS,
             "bounded decoder length required")
    _require(direction in ("encode", "decode") and type(source) is str,
             "source string and paired direction required")
    tokens = shared.tokenize(source)
    _require(len(tokens) < shared.MAX_TOKENS, "source must leave room for direction token")
    loaded = load_paired_copy_continuation(descriptor)
    model, config = loaded["model"], loaded["config"]
    disabled = shared._ablate(model, weight_ablation)
    vocabulary = config["vocabulary"]
    inputs, copied, extra, _ = shared._source_ids(tokens, vocabulary, direction)
    alphabet = vocabulary + extra
    source_ids = torch.tensor([inputs], dtype=torch.long)
    copy_ids = torch.tensor([copied], dtype=torch.long)
    mask = source_ids != 0
    mask[:, 0] = False
    completed, calls = [], 0
    with torch.inference_mode():
        encoded, hidden = model.encode(source_ids, torch.tensor([len(inputs)]))
        active = [(0.0, (), hidden, 1, ())]
        for _ in range(max_new_tokens):
            expanded = []
            for score, ids, state, current, traces in active:
                probs, state, generator, copy, attention, gate = model.decode(
                    torch.tensor([[current]], dtype=torch.long), state,
                    encoded, mask, copy_ids, len(alphabet), disable_copy=disabled)
                calls += 1
                _require(all(bool(torch.isfinite(t).all()) for t in
                    (probs, state, generator, copy, attention, gate)), "nonfinite continuation beam inference")
                values = probs[0, -1]
                indices = torch.argsort(values, descending=True, stable=True)[:beam_width].tolist()
                for index in indices:
                    probability = float(values[index])
                    if probability <= 0:
                        continue
                    score_next = score + math.log(probability)
                    if index == 2:
                        if ids:
                            completed.append((score_next, ids, traces))
                        continue
                    if index in (0, 1, 3, 4, 5):
                        continue
                    token = alphabet[index]
                    gen_mass, copy_mass = float(generator[0, -1, index]), float(copy[0, -1, index])
                    trace = {"token": token, "extended_copy_token": index >= len(vocabulary),
                        "generator_probability": gen_mass, "copy_probability": copy_mass,
                        "copy_source_positions": [i for i, value in enumerate(tokens) if value == token],
                        "dominant_branch": "copy" if copy_mass > gen_mass else "generator"}
                    expanded.append((score_next, ids + (index,), state, index, traces + (trace,)))
            active = sorted(expanded, key=lambda row: (-row[0], row[1]))[:beam_width]
            completed = sorted(completed, key=lambda row: (-row[0], row[1]))[:beam_width]
            if not active or (len(completed) >= beam_width and completed[-1][0] >= active[0][0]):
                break
    unknown = sorted(set(tokens) - set(vocabulary))
    rows = []
    for rank, (score, ids, traces) in enumerate(completed):
        predicted = [alphabet[index] for index in ids]
        rows.append({"rank": rank, "log_probability": score,
            "generated_text": " ".join(predicted), "tokens": predicted,
            "ended": True, "status": "generated", "input_oov_tokens": unknown,
            "uncovered_input_tokens": unknown if disabled else [],
            "input_coverage_complete": not unknown or not disabled,
            "copy_trace": list(traces), "copy_enabled": not disabled,
            "checkpoint_weights_sha256": loaded["training"]["final_state_sha256"],
            "weight_ablation": weight_ablation, "teacher_forcing": False,
            "target_access": False, "training_executed": False,
            "copy_probability_is_semantic_confidence": False,
            "provider_calls": 0, "download_calls": 0, **_FALSE})
    return {"schema": "shared-paired-copy-aligned-beam-search/v2", "direction": direction,
        "source_sha256": _sha(source.encode()), "checkpoint": dict(descriptor),
        "checkpoint_weights_sha256": loaded["training"]["final_state_sha256"],
        "search_producer_sha256": _sha(Path(__file__).read_bytes()),
        "beam_width": beam_width, "max_new_tokens": max_new_tokens,
        "ranking": "descending_raw_autoregressive_log_probability", "native_decoder_calls": calls,
        "rows": rows, "weight_ablation": weight_ablation, "teacher_forcing": False,
        "target_access": False, "training_executed": False,
        "provider_calls": 0, "download_calls": 0, **_FALSE}
