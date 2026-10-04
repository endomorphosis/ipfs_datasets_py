"""Experimental source attention plus dimension-bound latent residual decoder.

The entire source decoder and its frozen codec are copied from an explicitly
validated checkpoint. A zero-initialized residual preserves that parent's
initial logits exactly. Training starts a new optimizer and lineage; inference
accepts only source text and vectors. Neither syntax nor training grants legal
semantic correctness, proof authority, or Lake admission.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
from pathlib import Path
import random
import stat
import time

from . import legal_formula_codec as codec_module
from . import legal_formula_learning as source_module

SCHEMA = "hybrid-legal-formula-checkpoint/v1"
ARCHITECTURE = "source-gru-attention-zero-init-latent-residual/v1"
LINEAGE_ID = "source_latent_formula_v1"
MAX_BYTES = 64 * 1024 * 1024
FALSE = source_module.FALSE
_require = source_module._require
_raw = source_module._raw
checkpoint_digest = source_module.checkpoint_digest


def _capture_implementation():
    return {"source": source_module._implementation(),
            "hybrid_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}


_IMPLEMENTATION_AT_IMPORT = _capture_implementation()


def _implementation():
    current = _capture_implementation()
    _require(current == _IMPLEMENTATION_AT_IMPORT, "hybrid implementation changed since import")
    return current


def _contract(contract):
    _require(type(contract) is dict and set(contract) == {
        "dimension", "representation_id", "encoder_sha256"}, "closed latent contract required")
    _require(type(contract["dimension"]) is int and contract["dimension"] in (8, 384, 768),
             "latent dimension must be 8, 384, or 768")
    _require(type(contract["representation_id"]) is str
             and 0 < len(contract["representation_id"].strip()) <= 512,
             "explicit latent representation identity required")
    _require(type(contract["encoder_sha256"]) is str
             and source_module._SHA.fullmatch(contract["encoder_sha256"]), "encoder hash required")
    return copy.deepcopy(contract)


def _latent(vector, dimension):
    _require(type(vector) in (list, tuple) and len(vector) == dimension,
             "latent vector dimension differs from contract")
    _require(all(type(value) in (float, int) and math.isfinite(value)
                 and abs(value) <= 3.4028234e38 for value in vector),
             "latent values must be finite float32 numbers")
    return list(vector)


def _config(source_config, *, learning_rate, batch_size, seed, projection_width,
            latent_enabled, loss_mode, residual_scale):
    import torch
    _require(type(source_config) is dict, "source configuration required")
    keys = ("learning_rate", "batch_size", "seed", "hidden_size", "embedding_dim")
    _require(all(key in source_config for key in keys), "incomplete source configuration")
    _require(source_config == source_module._config(torch, **{key: source_config[key] for key in keys}),
             "source configuration/runtime differs")
    _require(type(learning_rate) in (float, int) and math.isfinite(learning_rate)
             and 0 < learning_rate <= 0.1, "learning rate outside (0, 0.1]")
    for value, low, high, label in ((batch_size, 1, 16, "batch size"),
            (seed, 0, 2**31 - 1, "seed"), (projection_width, 8, 128, "projection width")):
        _require(type(value) is int and low <= value <= high, "invalid " + label)
    _require(type(latent_enabled) is bool, "latent_enabled must be boolean")
    _require(loss_mode in ("token_ce", "facet_balanced"), "unsupported loss mode")
    _require(type(residual_scale) in (int, float) and math.isfinite(residual_scale)
             and 0 < residual_scale <= 1, "residual scale outside (0, 1]")
    return {"architecture": ARCHITECTURE, "source_config": copy.deepcopy(source_config),
            "learning_rate": float(learning_rate), "batch_size": batch_size, "seed": seed,
            "projection_width": projection_width, "latent_enabled": latent_enabled,
            "loss_mode": loss_mode, "residual_scale": float(residual_scale),
            "device": "cpu", "dtype": "float32", "torch_version": str(torch.__version__),
            "optimizer_initialization": "restart_adam; source_parent_moments_not_transferred"}


def _model(torch, codec, config, contract):
    source_model = source_module._model(torch, codec, config["source_config"])

    class HybridSequenceDecoder(type(source_model)):
        def __init__(self):
            super().__init__()
            self.latent_down = torch.nn.Linear(contract["dimension"], config["projection_width"])
            self.latent_up = torch.nn.Linear(config["projection_width"], config["source_config"]["hidden_size"])
            torch.nn.init.zeros_(self.latent_up.weight)
            torch.nn.init.zeros_(self.latent_up.bias)

        def encode(self, source, lengths, latent, *, enabled=True):
            encoded, hidden = super().encode(source, lengths)
            residual = torch.tanh(self.latent_up(torch.tanh(self.latent_down(latent))))
            # Multiplication keeps identical parameter shapes/gradient presence
            # for the source-only experimental control.
            residual = residual * config["residual_scale"] * float(enabled and config["latent_enabled"])
            return encoded + residual[:, None, :], hidden + residual[None, :, :]

        def forward(self, source, lengths, target, latent, *, enabled=True):
            encoded, hidden = self.encode(source, lengths, latent, enabled=enabled)
            return self.next_logits(target, hidden, encoded, source != 0)[0]

    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(config["seed"])
        return HybridSequenceDecoder()


def _records(rows, codec, dimension, *, allow_empty=False, allow_rejection=False):
    _require(type(rows) in (list, tuple), "example sequence required")
    _require(all(type(row) is dict and set(row) == {
        "id", "source_text", "latent", "canonical_ir"} for row in rows), "closed hybrid example schema required")
    source_module._examples([{key: row[key] for key in ("id", "source_text", "canonical_ir")}
                            for row in rows], allow_empty=allow_empty)
    records, rejected, identities = [], [], set()
    for row in rows:
        vector = _latent(row["latent"], dimension)
        try:
            source = codec_module.encode_source(codec, row["source_text"])
            identity = tuple(source)
            _require(identity not in identities, "duplicate tokenized source")
            identities.add(identity)
            target = codec_module.encode_target(codec, row["canonical_ir"])
        except ValueError as error:
            if not allow_rejection:
                raise
            rejected.append({"id": row["id"], "reason": str(error)})
            continue
        records.append((source, target, vector))
    return records, rejected, identities


def _splits(training, tuning, codec, dimension):
    train, _, train_ids = _records(training, codec, dimension)
    tune, rejected, tune_ids = _records(tuning, codec, dimension, allow_empty=True, allow_rejection=True)
    _require(not {row["id"] for row in training} & {row["id"] for row in tuning}, "training/tuning IDs overlap")
    _require(not {row["source_text"] for row in training} & {row["source_text"] for row in tuning},
             "training/tuning sources overlap")
    _require(not train_ids & tune_ids, "training/tuning tokenized sources overlap")
    return train, tune, rejected


def build_checkpoint(source_checkpoint, latent_contract, training_examples, tuning_examples=(), *,
                     learning_rate=0.003, batch_size=8, seed=1729, projection_width=32,
                     latent_enabled=True, loss_mode="token_ce", residual_scale=0.25):
    """Warm-start every shared weight and exact vocabulary; no optimizer update."""
    torch, parent, _ = source_module._restore(source_checkpoint)
    contract = _contract(latent_contract)
    config = _config(source_checkpoint["config"], learning_rate=learning_rate, batch_size=batch_size,
        seed=seed, projection_width=projection_width, latent_enabled=latent_enabled,
        loss_mode=loss_mode, residual_scale=residual_scale)
    codec = copy.deepcopy(source_checkpoint["codec"])
    _splits(training_examples, tuning_examples, codec, contract["dimension"])
    model = _model(torch, codec, config, contract)
    state = model.state_dict()
    state.update(parent.state_dict())
    model.load_state_dict(state)
    optimizer = torch.optim.Adam(model.parameters(), lr=config["learning_rate"], foreach=False)
    weights, moments = source_module._pack(model, optimizer)
    return {"schema": SCHEMA, "lineage_id": LINEAGE_ID, "config": config, "codec": codec,
        "latent_contract": contract, "latent_contract_sha256": checkpoint_digest(contract),
        "source_parent_checkpoint_sha256": source_module.checkpoint_digest(source_checkpoint),
        "source_parent_optimizer_steps": source_checkpoint["progress"]["optimizer_steps"],
        "implementation": _implementation(), "training_manifest_sha256": checkpoint_digest(training_examples),
        "tuning_manifest_sha256": checkpoint_digest(tuning_examples), "training_count": len(training_examples),
        "tuning_count": len(tuning_examples), "model_state": weights, "optimizer_state": moments,
        "progress": {"epochs_completed": 0, "row_cursor": 0, "optimizer_steps": 0},
        "parent_checkpoint_sha256": None, **FALSE}


def _restore(checkpoint):
    import torch
    source_module._require_workspace_tree()
    fields = {"schema", "lineage_id", "config", "codec", "latent_contract", "latent_contract_sha256",
        "source_parent_checkpoint_sha256", "source_parent_optimizer_steps", "implementation",
        "training_manifest_sha256", "tuning_manifest_sha256", "training_count", "tuning_count",
        "model_state", "optimizer_state", "progress", "parent_checkpoint_sha256", *FALSE}
    _require(type(checkpoint) is dict and set(checkpoint) == fields, "closed hybrid checkpoint schema required")
    _require(checkpoint["schema"] == SCHEMA and checkpoint["lineage_id"] == LINEAGE_ID
             and all(checkpoint[key] is False for key in FALSE), "hybrid lineage or authority differs")
    _require(len(_raw(checkpoint)) <= MAX_BYTES, "checkpoint exceeds byte bound")
    _require(checkpoint["implementation"] == _implementation(), "hybrid implementation source drift")
    config = checkpoint["config"]
    keys = ("learning_rate", "batch_size", "seed", "projection_width", "latent_enabled", "loss_mode", "residual_scale")
    _require(type(config) is dict and all(key in config for key in (*keys, "source_config")), "incomplete configuration")
    _require(_raw(config) == _raw(_config(config["source_config"], **{key: config[key] for key in keys})),
             "hybrid configuration/runtime differs")
    contract = _contract(checkpoint["latent_contract"])
    _require(checkpoint["latent_contract_sha256"] == checkpoint_digest(contract), "latent contract hash differs")
    codec_module.validate_codec(checkpoint["codec"])
    for key in ("training_manifest_sha256", "tuning_manifest_sha256", "source_parent_checkpoint_sha256"):
        _require(type(checkpoint[key]) is str and source_module._SHA.fullmatch(checkpoint[key]), "invalid identity hash")
    parent = checkpoint["parent_checkpoint_sha256"]
    _require(parent is None or type(parent) is str and source_module._SHA.fullmatch(parent), "invalid parent hash")
    _require(type(checkpoint["source_parent_optimizer_steps"]) is int
             and 0 <= checkpoint["source_parent_optimizer_steps"] <= 10**9, "invalid source parent steps")
    count = checkpoint["training_count"]
    _require(type(count) is int and 1 <= count <= 4096 and type(checkpoint["tuning_count"]) is int
             and 0 <= checkpoint["tuning_count"] <= 4096, "invalid split counts")
    progress = checkpoint["progress"]
    _require(type(progress) is dict and set(progress) == {"epochs_completed", "row_cursor", "optimizer_steps"}
             and all(type(value) is int and 0 <= value <= 10**9 for value in progress.values()), "invalid progress")
    cursor, batch = progress["row_cursor"], config["batch_size"]
    _require(cursor < count and cursor % batch == 0 and progress["optimizer_steps"] ==
        progress["epochs_completed"] * math.ceil(count / batch) + cursor // batch, "step/cursor identity differs")
    model = _model(torch, checkpoint["codec"], config, contract)
    template = model.state_dict()
    weights = checkpoint["model_state"]
    _require(type(weights) is dict and set(weights) == set(template), "model state keys differ")
    model.load_state_dict({key: source_module._tensor(torch, weights[key], value.shape, key)
                           for key, value in template.items()})
    optimizer = torch.optim.Adam(model.parameters(), lr=config["learning_rate"], foreach=False)
    moments = checkpoint["optimizer_state"]
    _require(type(moments) is dict and set(moments) == {"schema", "parameters"}
             and moments["schema"] == "adam-default-betas-eps/v1" and type(moments["parameters"]) is dict,
             "unsupported optimizer state")
    names = dict(model.named_parameters())
    _require(set(moments["parameters"]) == (set(names) if progress["optimizer_steps"] else set()),
             "optimizer parameter keys differ")
    for name, state in moments["parameters"].items():
        _require(type(state) is dict and set(state) == {"step", "exp_avg", "exp_avg_sq"}
                 and type(state["step"]) is int and state["step"] == progress["optimizer_steps"],
                 "optimizer moment step differs")
        parameter = names[name]
        optimizer.state[parameter] = {
            "step": torch.tensor(float(state["step"]), dtype=torch.float32),
            "exp_avg": source_module._tensor(torch, state["exp_avg"], parameter.shape, name),
            "exp_avg_sq": source_module._tensor(torch, state["exp_avg_sq"], parameter.shape, name, nonnegative=True)}
    model.eval()
    return torch, model, optimizer


def validate_checkpoint(checkpoint):
    _restore(checkpoint)


def _facet_weights(codec, targets, torch):
    """Each of seven facets receives equal mass, including qualifier stops."""
    rows = []
    for target in targets:
        fields = []
        for token_id in target[1:]:
            token = codec["target_vocabulary"][token_id]
            value = json.loads(token) if token.startswith("[") else []
            fields.append(value[1] if value and value[0] in ("atom", "end") else None)
        counts = {field: fields.count(field) for field in codec_module.FIELDS}
        rows.append([1 / counts[field] if field is not None else 0.0 for field in fields])
    width = max(map(len, rows))
    return torch.tensor([row + [0.0] * (width - len(row)) for row in rows], dtype=torch.float32)


def _loss(torch, model, records, checkpoint):
    source, lengths, target = source_module._batch(torch, [(row[0], row[1]) for row in records])
    latent = torch.tensor([row[2] for row in records], dtype=torch.float32)
    logits = model(source, lengths, target[:, :-1], latent)
    expected = target[:, 1:]
    losses = torch.nn.functional.cross_entropy(logits.reshape(-1, logits.shape[-1]),
        expected.reshape(-1), ignore_index=0, reduction="none").reshape(expected.shape)
    if checkpoint["config"]["loss_mode"] == "facet_balanced":
        weights = _facet_weights(checkpoint["codec"], [row[1] for row in records], torch)
        return (losses * weights).sum() / weights.sum()
    return losses.sum() / (expected != 0).sum()


def train_decoder(checkpoint, training_examples, tuning_examples=(), *, max_steps=100, max_seconds=60):
    """Perform bounded additional steps, resuming exact data/optimizer state."""
    _require(type(max_steps) is int and 0 <= max_steps <= 10000, "max_steps must be in 0..10000")
    _require(type(max_seconds) in (int, float) and math.isfinite(max_seconds)
             and 0 <= max_seconds <= 3600, "max_seconds must be in 0..3600")
    started = time.monotonic()
    deadline = started + max_seconds
    torch, model, optimizer = _restore(checkpoint)
    _require(checkpoint["training_manifest_sha256"] == checkpoint_digest(training_examples)
             and checkpoint["tuning_manifest_sha256"] == checkpoint_digest(tuning_examples), "resume manifests differ")
    records, tuning, rejected = _splits(training_examples, tuning_examples, checkpoint["codec"],
                                       checkpoint["latent_contract"]["dimension"])
    config = checkpoint["config"]
    progress = dict(checkpoint["progress"])
    initial = copy.deepcopy(checkpoint["model_state"])
    losses = []
    reason = "step_limit"
    max_gradient = 0.0
    for _ in range(max_steps):
        if time.monotonic() >= deadline:
            reason = "deadline_before_batch"
            break
        order = list(range(len(records)))
        random.Random(config["seed"] + progress["epochs_completed"]).shuffle(order)
        indices = order[progress["row_cursor"]:progress["row_cursor"] + config["batch_size"]]
        model.train()
        optimizer.zero_grad(set_to_none=True)
        loss = _loss(torch, model, [records[index] for index in indices], checkpoint)
        _require(bool(torch.isfinite(loss)), "nonfinite training loss")
        loss.backward()
        parameters = list(model.parameters())
        _require(all(parameter.grad is not None and bool(torch.isfinite(parameter.grad).all())
                     for parameter in parameters), "missing or nonfinite gradients")
        norm = float(torch.nn.utils.clip_grad_norm_(parameters, 5, error_if_nonfinite=True))
        max_gradient = max(max_gradient, norm)
        optimizer.step()
        _require(all(bool(torch.isfinite(parameter).all()) for parameter in parameters), "nonfinite updated weights")
        _require(all(bool(torch.isfinite(value).all()) for state in optimizer.state.values()
                     for value in state.values() if torch.is_tensor(value)), "nonfinite optimizer moments")
        progress["optimizer_steps"] += 1
        progress["row_cursor"] += len(indices)
        if progress["row_cursor"] == len(records):
            progress["row_cursor"] = 0
            progress["epochs_completed"] += 1
        losses.append(float(loss.detach()))
    model.eval()
    total, measured = 0.0, 0
    with torch.no_grad():
        for start in range(0, len(tuning), config["batch_size"]):
            if time.monotonic() >= deadline:
                break
            batch = tuning[start:start + config["batch_size"]]
            loss = _loss(torch, model, batch, checkpoint)
            _require(bool(torch.isfinite(loss)), "nonfinite tuning loss")
            total += float(loss) * len(batch)
            measured += len(batch)
    weights, moments = source_module._pack(model, optimizer)
    result = {**copy.deepcopy(checkpoint), "model_state": weights, "optimizer_state": moments,
              "progress": progress, "parent_checkpoint_sha256": checkpoint_digest(checkpoint)}
    _require(_implementation() == checkpoint["implementation"], "hybrid source changed during training")
    _require(len(_raw(result)) <= MAX_BYTES, "checkpoint exceeds byte bound")
    report = {"schema": "hybrid-legal-formula-training/v1", "checkpoint_sha256": checkpoint_digest(result),
        "source_parent_checkpoint_sha256": checkpoint["source_parent_checkpoint_sha256"],
        "latent_contract_sha256": checkpoint["latent_contract_sha256"], "optimizer_steps": len(losses),
        "training_executed": bool(losses), "loss_mode": config["loss_mode"], "batch_losses": losses,
        "gradient_norm_max": max_gradient, "changed_parameter_names": [key for key in weights if weights[key] != initial[key]],
        "stopped_reason": reason, "elapsed_seconds": time.monotonic() - started,
        "deadline_scope": "soft_boundary_before_numeric_batch; initialization_and_serialization_not_interruptible",
        "tuning": {"objective_loss": total / measured if measured else None, "rows_evaluated": measured,
                   "rejected_rows": rejected, "complete": measured == len(tuning_examples),
                   "teacher_forcing": True, "used_for_fit_or_selection": False}, **FALSE}
    return {"checkpoint": result, "report": report}


class HybridLegalFormulaDecoder:
    """Source/vector-only inference with exact codec grammar and explicit ablations."""
    def __init__(self, checkpoint):
        self.torch, self.model, _ = _restore(checkpoint)
        self.checkpoint = copy.deepcopy(checkpoint)
        self.checkpoint_sha256 = checkpoint_digest(checkpoint)
        self.codec = self.checkpoint["codec"]

    def _decode(self, text, vector, *, enabled):
        base = {"source_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "latent_sha256": checkpoint_digest(vector), "status": "abstained", "canonical_ir": None,
            "formal_outputs": [], "formula_text": None, "teacher_forcing": False, "target_access": False,
            "training_executed": False, "source_input_conditioned": True,
            "latent_input_enabled": enabled and self.checkpoint["config"]["latent_enabled"],
            "family_syntax_checked": False, **FALSE}
        try:
            source_ids = codec_module.encode_source(self.codec, text)
        except ValueError as error:
            return {**base, "reason": "source_encoding_rejected", "detail": str(error)}
        torch = self.torch
        if not bool(self.model.output.weight.detach().any()) and not bool(self.model.output.bias.detach().any()):
            return {**base, "reason": "zero_output_head"}
        source = torch.tensor([source_ids], dtype=torch.long)
        prefix, minimum_margin = [codec_module.TARGET_BOS], None
        self.model.eval()
        with torch.no_grad():
            encoded, hidden = self.model.encode(source, torch.tensor([len(source_ids)]),
                torch.tensor([vector], dtype=torch.float32), enabled=enabled)
            for _ in range(codec_module.MAX_TARGET_TOKENS - 1):
                allowed = codec_module.allowed_token_ids(self.codec, prefix)
                if not allowed:
                    return {**base, "reason": "no_allowed_grammar_token", "generated_token_ids": prefix}
                logits, hidden = self.model.next_logits(torch.tensor([[prefix[-1]]]), hidden, encoded, source != 0)
                scores = logits[0, -1, allowed]
                if not bool(torch.isfinite(scores).all()):
                    return {**base, "reason": "nonfinite_decoder_scores"}
                ranking = torch.argsort(scores, descending=True, stable=True)
                if len(allowed) > 1:
                    margin = float(scores[ranking[0]] - scores[ranking[1]])
                    minimum_margin = margin if minimum_margin is None else min(minimum_margin, margin)
                    if margin <= 1e-7:
                        return {**base, "reason": "ambiguous_decoder_scores", "generated_token_ids": prefix}
                prefix.append(allowed[int(ranking[0])])
                if prefix[-1] == codec_module.TARGET_EOS:
                    try:
                        canonical_ir = codec_module.decode_target(self.codec, prefix)
                    except ValueError as error:
                        return {**base, "reason": "generated_ir_rejected", "detail": str(error)}
                    display = source_module._display(canonical_ir)
                    return {**base, "status": "decoded", "reason": None, "canonical_ir": canonical_ir,
                        "formula_text": display, "generated_token_ids": prefix,
                        "minimum_decision_logit_margin": minimum_margin,
                        "syntax_scope": "canonical_rule_schema_and_decoder_grammar",
                        "formal_outputs": [{"family": "deontic", "format": "typed-deontic-rule/v1",
                            "payload": canonical_ir["rules"][0], "formula_text": display,
                            "formula_text_role": "display_only_full_ast_is_authoritative",
                            "origin": "learned_source_latent_formula_decoder", **FALSE}]}
        return {**base, "reason": "generation_length_limit", "generated_token_ids": prefix}

    def decode_formal_logic(self, texts, latents, *, latent_ablation="none"):
        _require(type(texts) in (list, tuple) and 1 <= len(texts) <= 128
                 and all(type(text) is str and 0 < len(text) <= 16384 for text in texts),
                 "one to 128 bounded source strings required")
        _require(type(latents) in (list, tuple) and len(latents) == len(texts), "one latent per source required")
        _require(latent_ablation in ("none", "zero", "rotate", "disabled"), "unsupported latent ablation")
        _require(latent_ablation != "rotate" or len(texts) > 1, "rotate ablation requires at least two rows")
        source_module._require_workspace_tree()
        _require(_implementation() == self.checkpoint["implementation"], "hybrid implementation source drift")
        dimension = self.checkpoint["latent_contract"]["dimension"]
        vectors = [_latent(vector, dimension) for vector in latents]
        if latent_ablation == "zero":
            vectors = [[0.0] * dimension for _ in vectors]
        elif latent_ablation == "rotate":
            vectors = vectors[1:] + vectors[:1]
        rows = [self._decode(text, vector, enabled=latent_ablation != "disabled")
                for text, vector in zip(texts, vectors)]
        count = sum(row["status"] == "decoded" for row in rows)
        return {"schema": "hybrid-legal-formula-inference/v1", "lineage_id": LINEAGE_ID,
            "checkpoint_sha256": self.checkpoint_sha256, "latent_contract_sha256": self.checkpoint["latent_contract_sha256"],
            "latent_ablation": latent_ablation, "rows": rows, "decoded_count": count,
            "status": "decoded" if count == len(rows) else "partial" if count else "abstained",
            "target_access": False, "teacher_forcing": False, "training_executed": False, **FALSE}


def save_checkpoint(checkpoint, path):
    """Exclusive JSON write, with full validation and no executable payloads."""
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
    _require(type(expected_sha256) is str and source_module._SHA.fullmatch(expected_sha256), "expected checkpoint hash required")
    path = Path(path).absolute()
    _require(path.resolve(strict=True) == path, "canonical checkpoint path required")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        _require(stat.S_ISREG(before.st_mode) and before.st_size <= MAX_BYTES, "bounded regular checkpoint required")
        raw = stream.read(MAX_BYTES + 1)
        after = os.fstat(stream.fileno())
    _require(len(raw) <= MAX_BYTES and (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns),
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
