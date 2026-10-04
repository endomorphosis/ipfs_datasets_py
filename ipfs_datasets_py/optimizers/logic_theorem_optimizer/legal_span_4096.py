"""Separate native 4096D source-span checkpoint and resumable Adam lineage.

The frozen byte/span numerical kernels are reused with an actual 4096-wide
adapter. Neither the old dimensional schema nor any embedding width changes.
Caller supplied vectors describe inputs, and do not authenticate Leanstral.
Synthetic fixtures are explicitly untrained architecture controls and cannot
be fitted. All checkpoints retain false qualification and proof authority.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import random
import stat
import time

from . import legal_span_formula as span

SCHEMA = "native-4096-source-span-checkpoint/v1"
LINEAGE_ID = "native_4096_source_span_v1"
ARCHITECTURE = "utf8-byte-bidirectional-gru-native-4096-film-spans/v1"
DIMENSION = 4096
MAX_BYTES = 128 * 1024 * 1024
FALSE = span.FALSE
_require, _raw, checkpoint_digest = span._require, span._raw, span.checkpoint_digest
_CONFIG_KEYS = ("latent_enabled", "learning_rate", "batch_size", "seed", "hidden_size",
                "embedding_dim", "projection_width", "residual_scale")
_BASE_CONFIG_KEYS = ("latent_dimension", *_CONFIG_KEYS)
_PROVENANCE_SCHEMA = "native-4096-source-span-provenance/v1"
_CALLER_KIND = "caller_supplied_native_vectors"
_SYNTHETIC_KIND = "synthetic_untrained_architecture_control"
_FACTORY_AT_IMPORT = span._model
_SPLITS_AT_IMPORT = span._splits
_BATCH_AT_IMPORT = span._batch
_LOSS_AT_IMPORT = span._loss
_DECODE_AT_IMPORT = span.SpanLegalFormulaDecoder._decode
_TOKENIZER_AT_IMPORT = span.tokenize_source
_RULE_AT_IMPORT = span.codec_module._rule


def _capture_implementation():
    return {"native4096_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "base_span": span._implementation()}


_IMPLEMENTATION_AT_IMPORT = _capture_implementation()


def _implementation():
    current = _capture_implementation()
    _require(current == _IMPLEMENTATION_AT_IMPORT and span._model is _FACTORY_AT_IMPORT
             and span._splits is _SPLITS_AT_IMPORT and span._batch is _BATCH_AT_IMPORT
             and span._loss is _LOSS_AT_IMPORT and span.SpanLegalFormulaDecoder._decode is _DECODE_AT_IMPORT
             and span.tokenize_source is _TOKENIZER_AT_IMPORT and span.codec_module._rule is _RULE_AT_IMPORT,
             "native4096 implementation changed since import")
    return deepcopy(current)


def _plain_json(value):
    pending, items = [(value, 0)], 0
    while pending:
        part, depth = pending.pop()
        items += 1
        _require(depth <= 64 and items <= 8_000_000, "bounded plain checkpoint JSON required")
        if type(part) is dict:
            _require(all(type(key) is str for key in part), "plain JSON string keys required")
            pending.extend((child, depth + 1) for child in part.values())
        elif type(part) is list:
            pending.extend((child, depth + 1) for child in part)
        else:
            _require(type(part) in (str, int, float, bool, type(None))
                     and (type(part) is not float or math.isfinite(part)), "plain finite checkpoint JSON required")


def _config(*, latent_enabled=True, learning_rate=.001, batch_size=12, seed=1729,
            hidden_size=32, embedding_dim=16, projection_width=16, residual_scale=.25):
    import torch
    for value, low, high, label in ((batch_size, 1, 32, "batch size"), (seed, 0, 2**31 - 1, "seed"),
            (hidden_size, 8, 128, "hidden size"), (embedding_dim, 4, 64, "embedding dimension"),
            (projection_width, 4, 128, "projection width")):
        _require(type(value) is int and low <= value <= high, "invalid " + label)
    _require(type(latent_enabled) is bool, "latent_enabled must be boolean")
    for value, high, label in ((learning_rate, .1, "learning rate"), (residual_scale, 1, "residual scale")):
        _require(type(value) in (int, float) and math.isfinite(value) and 0 < value <= high,
                 "invalid " + label)
    return {"architecture": ARCHITECTURE, "latent_dimension": DIMENSION, "latent_enabled": latent_enabled,
            "learning_rate": float(learning_rate), "batch_size": batch_size, "seed": seed,
            "hidden_size": hidden_size, "embedding_dim": embedding_dim, "projection_width": projection_width,
            "residual_scale": float(residual_scale), "device": "cpu", "dtype": "float32",
            "torch_version": str(torch.__version__), "max_source_characters": span.MAX_SOURCE_CHARACTERS,
            "max_source_tokens": span.MAX_SOURCE_TOKENS, "max_token_bytes": span.MAX_TOKEN_BYTES,
            "tokenizer": "unicode_word_or_punctuation_exact_offsets/v1", "byte_alphabet": "casefold_utf8_plus1_pad0/v1",
            "initialization": "fresh_native4096_adapter_exact_zero_output/v1",
            "loss": "equal_facet_modality_presence_mean_start_end/v1"}


def _context_contract(contract):
    _require(type(contract) is dict and set(contract) == {
        "dimension", "representation_id", "producer_sha256", "training_index_sha256"},
        "closed native4096 context contract required")
    _require(type(contract["dimension"]) is int and contract["dimension"] == DIMENSION,
             "native4096 context dimension differs")
    _require(type(contract["representation_id"]) is str and
             0 < len(contract["representation_id"].strip()) <= 512, "bounded representation identity required")
    for name in ("producer_sha256", "training_index_sha256"):
        _require(type(contract[name]) is str and span._SHA.fullmatch(contract[name]), "invalid native context hash")
    return deepcopy(contract)


def _provenance(kind):
    _require(kind in (_CALLER_KIND, _SYNTHETIC_KIND), "unsupported native4096 provenance")
    return {"schema": _PROVENANCE_SCHEMA, "kind": kind, "synthetic_embeddings": kind == _SYNTHETIC_KIND,
            "trusted_native_owner_verified": False}


class _CpuFactoryTorch:
    def __init__(self, torch):
        self._torch = torch

    def manual_seed(self, seed):
        return self._torch.random.default_generator.manual_seed(seed)

    def __getattr__(self, name):
        return getattr(self._torch, name)


def _fresh_model(torch, config):
    _require(torch.get_default_dtype() == torch.float32 and str(torch.get_default_device()) == "cpu",
             "native4096 factory requires CPU float32 defaults")
    return _FACTORY_AT_IMPORT(_CpuFactoryTorch(torch), deepcopy(config))


def _source_state(state):
    return {name: value for name, value in state.items() if not name.startswith(("latent_down.", "latent_up."))}


def _weights(torch, model, saved):
    template = model.state_dict()
    _require(type(saved) is dict and set(saved) == set(template), "model state keys differ")
    tensors = {name: span._tensor(torch, saved[name], value.shape, name) for name, value in template.items()}
    _require(checkpoint_digest({name: value.tolist() for name, value in tensors.items()}) == checkpoint_digest(saved),
             "checkpoint weights are not exact float32 serialization")
    model.load_state_dict(tensors, strict=True)


def _progress(checkpoint):
    count, tune = checkpoint["training_count"], checkpoint["tuning_count"]
    _require(type(count) is int and 1 <= count <= span.MAX_EXAMPLES and type(tune) is int
             and 0 <= tune <= span.MAX_EXAMPLES, "invalid checkpoint split counts")
    for name in ("training_manifest_sha256", "tuning_manifest_sha256"):
        _require(type(checkpoint[name]) is str and span._SHA.fullmatch(checkpoint[name]), "invalid manifest hash")
    progress = checkpoint["progress"]
    _require(type(progress) is dict and set(progress) == {"epochs_completed", "row_cursor", "optimizer_steps"}
             and all(type(value) is int and 0 <= value <= 10**9 for value in progress.values()), "invalid progress")
    cursor, batch = progress["row_cursor"], checkpoint["config"]["batch_size"]
    _require(cursor < count and cursor % batch == 0 and progress["optimizer_steps"] ==
             progress["epochs_completed"] * math.ceil(count / batch) + cursor // batch,
             "checkpoint step/cursor identity differs")
    previous = checkpoint["parent_checkpoint_sha256"]
    _require(previous is None or type(previous) is str and span._SHA.fullmatch(previous), "invalid preceding checkpoint hash")
    _require((progress["optimizer_steps"] == 0) == (previous is None), "preceding checkpoint/progress differs")


def _moments(torch, model, checkpoint):
    state, steps = checkpoint["optimizer_state"], checkpoint["progress"]["optimizer_steps"]
    _require(type(state) is dict and set(state) == {"schema", "parameters"}
             and state["schema"] == "adam-default-betas-eps/v1" and type(state["parameters"]) is dict,
             "unsupported stored optimizer state")
    parameters = dict(model.named_parameters())
    _require(set(state["parameters"]) == (set(parameters) if steps else set()), "stored optimizer parameter keys differ")
    step_tensor = torch.tensor(float(steps), dtype=torch.float32, device="cpu")
    _require(step_tensor.item() == steps, "stored optimizer step is not exactly representable as float32")
    result = {}
    for name, moment in state["parameters"].items():
        _require(type(moment) is dict and set(moment) == {"step", "exp_avg", "exp_avg_sq"}
                 and type(moment["step"]) is int and moment["step"] == steps, "stored optimizer step differs")
        first = span._tensor(torch, moment["exp_avg"], parameters[name].shape, name)
        second = span._tensor(torch, moment["exp_avg_sq"], parameters[name].shape, name, nonnegative=True)
        _require(_raw(first.tolist()) == _raw(moment["exp_avg"]) and _raw(second.tolist()) == _raw(moment["exp_avg_sq"]),
                 "stored optimizer moments are not exact float32 serialization")
        result[name] = {"step": step_tensor.clone(), "exp_avg": first, "exp_avg_sq": second}
    return result


def _source_parent(torch, parent):
    fields = {"schema", "lineage_id", "config", "implementation", "training_manifest_sha256", "training_count",
              "tuning_manifest_sha256", "tuning_count", "model_state", "optimizer_state", "progress",
              "parent_checkpoint_sha256", *FALSE}
    _require(type(parent) is dict and set(parent) == fields and parent["schema"] == span.SCHEMA
             and parent["lineage_id"] == span.LINEAGE_ID and all(parent[name] is False for name in FALSE),
             "closed original source-parent checkpoint required")
    _plain_json(parent)
    _require(len(_raw(parent)) <= span.MAX_BYTES and parent["implementation"] == span._implementation(),
             "source-parent size or implementation differs")
    config = parent["config"]
    _require(type(config) is dict and set(_BASE_CONFIG_KEYS) <= set(config)
             and _raw(config) == _raw(span._config(**{name: config[name] for name in _BASE_CONFIG_KEYS})),
             "source-parent configuration differs")
    _progress(parent)
    _require(parent["progress"]["optimizer_steps"] > 0 and config["latent_dimension"] == 0,
             "trained source-only parent required")
    model = _fresh_model(torch, config)
    _weights(torch, model, parent["model_state"])
    _moments(torch, model, parent)
    return model


def _initial_model(torch, config, parent):
    model = _fresh_model(torch, config)
    if parent is not None:
        _source_parent(torch, parent)
        for name in ("seed", "hidden_size", "embedding_dim", "projection_width", "residual_scale"):
            _require(_raw(config[name]) == _raw(parent["config"][name]), "inherited configuration differs: " + name)
        state = {name: value.detach().tolist() for name, value in model.state_dict().items()}
        source = _source_state(parent["model_state"])
        _require(set(source) == set(_source_state(state)), "source architecture tensor names differ")
        state.update(deepcopy(source))
        _weights(torch, model, state)
    return model


def _build(training_examples, tuning_examples, *, context_contract, source_parent, kind, **settings):
    import torch
    _implementation()
    config, context = _config(**settings), _context_contract(context_contract)
    _SPLITS_AT_IMPORT(training_examples, tuning_examples, DIMENSION)
    _require(kind != _SYNTHETIC_KIND or source_parent is None, "synthetic fixture must initialize from scratch")
    initial = _initial_model(torch, config, source_parent)
    state = {name: value.detach().tolist() for name, value in initial.state_dict().items()}
    result = {"schema": SCHEMA, "lineage_id": LINEAGE_ID, "implementation": _implementation(),
        "provenance": _provenance(kind), "config": config, "context_contract": context,
        "context_contract_sha256": checkpoint_digest(context), "source_parent_checkpoint": deepcopy(source_parent),
        "source_parent_checkpoint_sha256": checkpoint_digest(source_parent) if source_parent is not None else None,
        "source_parent_optimizer_steps": source_parent["progress"]["optimizer_steps"] if source_parent is not None else 0,
        "initial_source_model_sha256": checkpoint_digest(_source_state(state)), "initial_model_state_sha256": checkpoint_digest(state),
        "training_manifest_sha256": checkpoint_digest(training_examples), "training_count": len(training_examples),
        "tuning_manifest_sha256": checkpoint_digest(tuning_examples), "tuning_count": len(tuning_examples),
        "model_state": state, "optimizer_state": {"schema": "adam-default-betas-eps/v1", "parameters": {}},
        "progress": {"epochs_completed": 0, "row_cursor": 0, "optimizer_steps": 0},
        "parent_checkpoint_sha256": None, **FALSE}
    _plain_json(result)
    _require(len(_raw(result)) <= MAX_BYTES, "native4096 checkpoint exceeds byte bound")
    return result


def build_checkpoint(training_examples, tuning_examples=(), *, context_contract, source_parent=None, **settings):
    """Create an unqualified 4096 lineage with a fresh adapter and fresh Adam.

    Optional warm starts copy a trained source-only parent's nonlatent tensors;
    numeric architecture settings must match that parent's declared settings.
    This API does not authenticate caller-supplied embeddings or their context.
    """
    return _build(training_examples, tuning_examples, context_contract=context_contract,
                  source_parent=source_parent, kind=_CALLER_KIND, **settings)


def build_synthetic_fixture(training_examples, tuning_examples=(), *, context_contract, **settings):
    """Create explicitly untrained CPU architecture controls, never fit evidence."""
    return _build(training_examples, tuning_examples, context_contract=context_contract,
                  source_parent=None, kind=_SYNTHETIC_KIND, **settings)


def _restore_for_inference(torch, checkpoint):
    """Validate the full retained checkpoint and return a private CPU model.

    No optimizer is constructed. Every retained Adam moment is checked using
    the exact same validation path used by resumable training restoration.
    """
    _implementation()
    _plain_json(checkpoint)
    fields = {"schema", "lineage_id", "implementation", "provenance", "config", "context_contract",
              "context_contract_sha256", "source_parent_checkpoint", "source_parent_checkpoint_sha256",
              "source_parent_optimizer_steps", "initial_source_model_sha256", "initial_model_state_sha256",
              "training_manifest_sha256", "training_count", "tuning_manifest_sha256", "tuning_count",
              "model_state", "optimizer_state", "progress", "parent_checkpoint_sha256", *FALSE}
    _require(type(checkpoint) is dict and set(checkpoint) == fields and checkpoint["schema"] == SCHEMA
             and checkpoint["lineage_id"] == LINEAGE_ID and all(checkpoint[name] is False for name in FALSE),
             "closed native4096 checkpoint required")
    _require(len(_raw(checkpoint)) <= MAX_BYTES and checkpoint["implementation"] == _implementation(),
             "native4096 checkpoint size or implementation differs")
    provenance = checkpoint["provenance"]
    _require(type(provenance) is dict and type(provenance.get("kind")) is str
             and _raw(provenance) == _raw(_provenance(provenance["kind"])), "native4096 provenance differs")
    config = checkpoint["config"]
    _require(type(config) is dict and set(_CONFIG_KEYS) <= set(config)
             and _raw(config) == _raw(_config(**{name: config[name] for name in _CONFIG_KEYS})),
             "native4096 configuration differs")
    context = _context_contract(checkpoint["context_contract"])
    _require(checkpoint["context_contract_sha256"] == checkpoint_digest(context), "native4096 context changed")
    parent = checkpoint["source_parent_checkpoint"]
    _require(type(checkpoint["source_parent_optimizer_steps"]) is int, "source-parent step count must be integer")
    if parent is None:
        _require(checkpoint["source_parent_checkpoint_sha256"] is None and checkpoint["source_parent_optimizer_steps"] == 0,
                 "absent source-parent lineage differs")
    else:
        _require(provenance["kind"] != _SYNTHETIC_KIND, "synthetic fixture must initialize from scratch")
        _source_parent(torch, parent)
        _require(checkpoint["source_parent_checkpoint_sha256"] == checkpoint_digest(parent)
                 and checkpoint["source_parent_optimizer_steps"] == parent["progress"]["optimizer_steps"],
                 "source-parent content or progress differs")
    model = _initial_model(torch, config, parent)
    initial = {name: value.detach().tolist() for name, value in model.state_dict().items()}
    _require(checkpoint["initial_source_model_sha256"] == checkpoint_digest(_source_state(initial))
             and checkpoint["initial_model_state_sha256"] == checkpoint_digest(initial), "initial native4096 state differs")
    _progress(checkpoint)
    if checkpoint["progress"]["optimizer_steps"] == 0:
        _require(_raw(checkpoint["model_state"]) == _raw(initial), "zero-update native4096 state differs")
    _require(provenance["kind"] != _SYNTHETIC_KIND or checkpoint["progress"]["optimizer_steps"] == 0,
             "synthetic architecture fixture must remain untrained")
    _weights(torch, model, checkpoint["model_state"])
    _moments(torch, model, checkpoint)
    model.eval()
    _implementation()
    return model


def _optimizer_for_model(torch, model, checkpoint):
    optimizer = torch.optim.Adam(model.parameters(), lr=checkpoint["config"]["learning_rate"], foreach=False)
    moments = _moments(torch, model, checkpoint)
    for name, parameter in model.named_parameters():
        if name in moments:
            optimizer.state[parameter] = moments[name]
    return optimizer


def _restore(checkpoint):
    import torch
    model = _restore_for_inference(torch, checkpoint)
    return torch, model, _optimizer_for_model(torch, model, checkpoint)


def validate_checkpoint(checkpoint):
    import torch
    _restore_for_inference(torch, checkpoint)


def train_decoder(checkpoint, training_examples, tuning_examples=(), *, max_steps=100, max_seconds=60):
    """Resume only this lineage's exact manifest, source context and Adam state."""
    _require(type(max_steps) is int and 0 <= max_steps <= 10000, "max_steps must be in 0..10000")
    _require(type(max_seconds) in (int, float) and math.isfinite(max_seconds) and 0 <= max_seconds <= 3600,
             "max_seconds must be in 0..3600")
    started = time.monotonic()
    import torch
    model = _restore_for_inference(torch, checkpoint)
    _require(max_steps == 0 or checkpoint["provenance"]["kind"] != _SYNTHETIC_KIND,
             "synthetic architecture fixtures cannot be trained")
    _require(max_steps == 0, "trusted_native_owner_integration_required")
    _require(checkpoint["training_manifest_sha256"] == checkpoint_digest(training_examples)
             and checkpoint["tuning_manifest_sha256"] == checkpoint_digest(tuning_examples), "resume manifests differ")
    records, tuning = _SPLITS_AT_IMPORT(training_examples, tuning_examples, DIMENSION)
    optimizer = _optimizer_for_model(torch, model, checkpoint)
    config, progress = checkpoint["config"], dict(checkpoint["progress"])
    losses, maximum_gradient, reason = [], 0., "step_limit"
    deadline = started + max_seconds
    for _ in range(max_steps):
        if time.monotonic() >= deadline:
            reason = "deadline_before_batch"
            break
        order = list(range(len(records)))
        random.Random(config["seed"] + progress["epochs_completed"]).shuffle(order)
        indices = order[progress["row_cursor"]:progress["row_cursor"] + config["batch_size"]]
        model.train()
        optimizer.zero_grad(set_to_none=True)
        loss = _LOSS_AT_IMPORT(torch, model, [records[index] for index in indices])
        _require(bool(torch.isfinite(loss)), "nonfinite training loss")
        loss.backward()
        parameters = list(model.parameters())
        _require(all(parameter.grad is not None and bool(torch.isfinite(parameter.grad).all()) for parameter in parameters),
                 "missing or nonfinite gradients")
        norm = torch.nn.utils.clip_grad_norm_(parameters, 5, error_if_nonfinite=True)
        maximum_gradient = max(maximum_gradient, float(norm))
        optimizer.step()
        _require(all(bool(torch.isfinite(parameter).all()) for parameter in parameters), "nonfinite updated weights")
        _require(all(bool(torch.isfinite(value).all()) for moment in optimizer.state.values()
                     for value in moment.values() if torch.is_tensor(value)), "nonfinite optimizer moments")
        progress["optimizer_steps"] += 1
        progress["row_cursor"] += len(indices)
        if progress["row_cursor"] == len(records):
            progress["epochs_completed"] += 1
            progress["row_cursor"] = 0
        losses.append(float(loss.detach()))
    model.eval()
    total, measured = 0., 0
    with torch.no_grad():
        for start in range(0, len(tuning), config["batch_size"]):
            if time.monotonic() >= deadline:
                break
            chunk = tuning[start:start + config["batch_size"]]
            loss = _LOSS_AT_IMPORT(torch, model, chunk)
            _require(bool(torch.isfinite(loss)), "nonfinite tuning loss")
            total += float(loss) * len(chunk)
            measured += len(chunk)
    weights, moments = span._pack(model, optimizer)
    result = ({**deepcopy(checkpoint), "model_state": weights, "optimizer_state": moments, "progress": progress,
               "parent_checkpoint_sha256": checkpoint_digest(checkpoint)} if losses else deepcopy(checkpoint))
    _require(_implementation() == checkpoint["implementation"], "native4096 source changed during training")
    validate_checkpoint(result)
    return {"checkpoint": result, "report": {"schema": "native-4096-source-span-training/v1",
        "checkpoint_sha256": checkpoint_digest(result), "optimizer_steps": len(losses), "training_executed": bool(losses),
        "new_optimizer_steps_total": progress["optimizer_steps"], "source_parent_optimizer_steps": checkpoint["source_parent_optimizer_steps"],
        "batch_losses": losses, "gradient_norm_max": maximum_gradient,
        "changed_parameter_names": [name for name in weights if weights[name] != checkpoint["model_state"][name]],
        "stopped_reason": reason, "elapsed_seconds": time.monotonic() - started,
        "deadline_scope": "soft_boundary_before_numeric_batch; initialization_and_serialization_not_interruptible",
        "trusted_native_owner_verified": False,
        "tuning": {"objective_loss": total / measured if measured else None, "rows_evaluated": measured,
                   "complete": measured == len(tuning), "teacher_forcing": False, "used_for_fit_or_selection": False}, **FALSE}}


class Leanstral4096SpanDecoder(span.SpanLegalFormulaDecoder):
    """CPU singleton reference restricted to explicitly synthetic controls.

    Actual Leanstral vectors need a trusted native owner integration before any
    candidate inference lane accepts them. Checkpoint metadata cannot grant it.
    """
    def __init__(self, checkpoint):
        import torch
        self.checkpoint = deepcopy(checkpoint)
        self.torch, self.model = torch, _restore_for_inference(torch, self.checkpoint)
        self.checkpoint_sha256 = checkpoint_digest(self.checkpoint)

    def decode_formal_logic(self, texts, latents=None, *, latent_ablation="none"):
        _require(type(texts) in (list, tuple) and 1 <= len(texts) <= 128 and all(type(text) is str for text in texts),
                 "one to128 source strings required")
        _require(self.checkpoint["provenance"]["kind"] == _SYNTHETIC_KIND, "trusted_native_owner_integration_required")
        _require(type(latents) in (list, tuple) and len(latents) == len(texts), "one native4096 vector per source required")
        vectors = [span._vector(vector, DIMENSION) for vector in latents]
        _require(latent_ablation in ("none", "zero", "rotate", "disabled"), "unsupported latent ablation")
        _require(latent_ablation != "rotate" or len(texts) > 1, "rotate requires at least two sources")
        _implementation()
        _require(checkpoint_digest(self.checkpoint) == self.checkpoint_sha256, "inference checkpoint changed")
        if latent_ablation == "zero":
            vectors = [[0.] * DIMENSION for _ in vectors]
        elif latent_ablation == "rotate":
            vectors = vectors[1:] + vectors[:1]
        before = checkpoint_digest({name: value.detach().tolist() for name, value in self.model.state_dict().items()})
        rows = [self._decode(text, vector, enabled=latent_ablation != "disabled") for text, vector in zip(texts, vectors)]
        after = checkpoint_digest({name: value.detach().tolist() for name, value in self.model.state_dict().items()})
        _require(before == after == checkpoint_digest(self.checkpoint["model_state"]), "inference model state changed")
        _require(checkpoint_digest(self.checkpoint) == self.checkpoint_sha256, "inference checkpoint changed")
        _implementation()
        count = sum(row["status"] == "decoded" for row in rows)
        return {"schema": "native-4096-source-span-inference/v1", "lineage_id": LINEAGE_ID,
            "checkpoint_sha256": self.checkpoint_sha256, "context_contract_sha256": self.checkpoint["context_contract_sha256"],
            "input_dimension": DIMENSION, "rows": rows, "decoded_count": count,
            "status": "decoded" if count == len(rows) else "partial" if count else "abstained", "latent_ablation": latent_ablation,
            "synthetic_architecture_control": True, "trusted_native_owner_verified": False,
            "target_access": False, "teacher_forcing": False, "training_executed": False, "model_state_unchanged": True, **FALSE}


def save_checkpoint(checkpoint, path):
    validate_checkpoint(checkpoint)
    raw = _raw(checkpoint)
    path = Path(path).absolute()
    _require(path.parent.resolve(strict=True) == path.parent, "canonical existing checkpoint parent required")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw), "schema": SCHEMA}


def load_checkpoint(path, *, expected_sha256):
    _require(type(expected_sha256) is str and span._SHA.fullmatch(expected_sha256), "expected checkpoint hash required")
    path = Path(path).absolute()
    _require(path.resolve(strict=True) == path, "canonical checkpoint path required")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        _require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_size <= MAX_BYTES,
                 "bounded nonaliased regular checkpoint required")
        raw = stream.read(MAX_BYTES + 1)
        after = os.fstat(stream.fileno())
    identity = lambda value: (value.st_dev, value.st_ino, value.st_nlink, value.st_size, value.st_mtime_ns, value.st_ctime_ns)
    _require(len(raw) <= MAX_BYTES and identity(before) == identity(after) == identity(path.stat(follow_symlinks=False)),
             "checkpoint changed while reading")
    _require(hashlib.sha256(raw).hexdigest() == expected_sha256, "checkpoint hash differs")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            _require(key not in result, "duplicate checkpoint JSON key")
            result[key] = value
        return result
    def reject(value):
        raise ValueError("invalid JSON constant: " + value)
    checkpoint = json.loads(raw, object_pairs_hook=unique, parse_constant=reject)
    validate_checkpoint(checkpoint)
    return checkpoint
