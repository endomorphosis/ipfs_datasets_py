"""Lineage-bound joint residual projection and latent-conditioned formula decoder.

The frozen 8D or current 384D numerical core supplies a raw representation.
This module trains a new residual projection and token decoder together using
embedding reconstruction and formula token losses. Formula gradients reach the
new projection; they do not differentiate the historical sparse core. Source
strings bind observations only and never enter the decoder. The first head
supports one exact canonical deontic rule; other logic projections abstain.
No checkpoint, metric or syntax check grants semantic or Lake admission.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path
import random
import re
import stat
import time

from . import legal_formula_codec as codec_module

SCHEMA = "modal-latent-formula-checkpoint/v1"
ARCHITECTURE = "residual-projection-latent-formula-gru/v1"
PROJECTION_ID = "typed_deontic_rule_v1"
MAX_BYTES = 48 * 1024 * 1024
MAX_ROWS = 4096
FALSE = {"qualified": False, "admitted": False, "formalized": False,
         "roundtrip_ok": False, "proof_authority": False,
         "semantic_correctness_verified": False, "promotion_performed": False,
         "publication_performed": False, "lake_executed": False}
_SHA = re.compile(r"[0-9a-f]{64}\Z")


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode()


def checkpoint_digest(value):
    return hashlib.sha256(_raw(value)).hexdigest()


def _pins():
    from ...logic.autoformal import tree_pin
    from ...logic.legal_ir import canonical_contracts
    from . import legal_ir_grammar_decoder
    expected = next((parent / "ipfs_datasets_py" for parent in Path(__file__).resolve().parents
                     if (parent / "ipfs_datasets_py/logic/autoformal/tree_pin.py").is_file()), None)
    _require(expected is not None, "canonical package root is missing")
    modules = (codec_module, tree_pin, canonical_contracts, legal_ir_grammar_decoder)
    for module in modules:
        _require(expected.resolve() in Path(module.__file__).resolve().parents,
                 "latent formula dependency loaded outside pinned package tree")
    tree_pin.require_workspace_logic_tree()
    files = {Path(module.__file__).name: hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
             for module in modules}
    files[Path(__file__).name] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    return {"scope": "listed_latent_decoder_and_grammar_sources_only", "files": files}


_IMPLEMENTATION_AT_IMPORT = _pins()


def _implementation():
    current = _pins()
    _require(current == _IMPLEMENTATION_AT_IMPORT, "latent formula implementation changed since import")
    return current


def _torch():
    import torch
    _require(torch.get_num_threads() == 1, "caller must reserve CPU and set torch.set_num_threads(1)")
    return torch


def _binding(value):
    fields = {"domain", "lineage_id", "dimension", "runtime_profile", "core_sha256"}
    _require(type(value) is dict and set(value) == fields, "closed latent binding required")
    _require(value["domain"] == "legal_ir", "legal latent decoder requires legal_ir domain")
    dimension = {"legacy_hub_v1": 8, "current_legal_v2": 384}.get(value["lineage_id"])
    _require(type(value["dimension"]) is int and dimension == value["dimension"],
             "lineage and latent dimension differ")
    _require(type(value["runtime_profile"]) is str and 0 < len(value["runtime_profile"]) <= 256,
             "bounded runtime profile required")
    _require(type(value["core_sha256"]) is str and _SHA.fullmatch(value["core_sha256"]),
             "exact core state SHA256 required")
    return copy.deepcopy(value)


def _config(*, learning_rate=.01, batch_size=8, seed=1729, hidden_size=32,
            token_embedding_dim=16, projection_width=16, formula_weight=1., reconstruction_weight=1.):
    for name, value, low, high in (("batch_size", batch_size, 1, 16), ("seed", seed, 0, 2**31 - 1),
            ("hidden_size", hidden_size, 8, 128), ("token_embedding_dim", token_embedding_dim, 8, 64),
            ("projection_width", projection_width, 1, 64)):
        _require(type(value) is int and low <= value <= high, name + " is outside bounded integer range")
    for name, value, high in (("learning_rate", learning_rate, .1), ("formula_weight", formula_weight, 100.),
                              ("reconstruction_weight", reconstruction_weight, 100.)):
        _require(type(value) in (int, float) and math.isfinite(value) and 0 < value <= high,
                 name + " must be finite and positive within its bound")
    return {"architecture": ARCHITECTURE, "device": "cpu", "dtype": "float32", "temperature": 0,
        "max_target_tokens": 64, "source_input": "provenance_only_not_neural_input",
        "torch_version": str(_torch().__version__), "learning_rate": float(learning_rate),
        "batch_size": batch_size, "seed": seed, "hidden_size": hidden_size,
        "token_embedding_dim": token_embedding_dim, "projection_width": projection_width,
        "formula_weight": float(formula_weight), "reconstruction_weight": float(reconstruction_weight)}


def _vector(value, dimension, label):
    _require(type(value) is list and len(value) == dimension and all(
        type(number) in (int, float) and math.isfinite(number) and abs(number) <= 1e8 for number in value),
        label + " requires bounded finite values with exact lineage width")


def _rows(rows, dimension, *, training, allow_empty=False):
    _require(type(rows) in (list, tuple) and (0 if allow_empty else 1) <= len(rows) <= MAX_ROWS,
             "bounded rows required")
    fields = {"id", "source_text", "latent"} | ({"embedding", "canonical_ir"} if training else set())
    ids, sources = set(), set()
    for row in rows:
        _require(type(row) is dict and set(row) == fields, "closed latent row schema required")
        _require(type(row["id"]) is str and 0 < len(row["id"]) <= 512 and row["id"] not in ids,
                 "unique bounded row id required")
        _require(type(row["source_text"]) is str and 0 < len(row["source_text"]) <= 16384
                 and row["source_text"].strip(), "bounded nonempty source provenance required")
        source = " ".join(row["source_text"].casefold().split())
        _require(not training or source not in sources, "duplicate normalized training source")
        ids.add(row["id"])
        sources.add(source)
        _vector(row["latent"], dimension, "latent")
        if training:
            _vector(row["embedding"], dimension, "embedding")
    return list(rows)


def _splits(training, tuning, dimension):
    train = _rows(training, dimension, training=True)
    tune = _rows(tuning, dimension, training=True, allow_empty=True)
    _require(not {row["id"] for row in train} & {row["id"] for row in tune}, "training/tuning IDs overlap")
    key = lambda row: " ".join(row["source_text"].casefold().split())
    _require(not {key(row) for row in train} & {key(row) for row in tune}, "training/tuning sources overlap")
    return train, tune


def _model(binding, codec, config):
    torch = _torch()
    class JointDecoder(torch.nn.Module):
        def __init__(self):
            super().__init__()
            dimension, width, hidden = binding["dimension"], config["projection_width"], config["hidden_size"]
            self.projection_down = torch.nn.Linear(dimension, width)
            self.projection_up = torch.nn.Linear(width, dimension)
            self.condition = torch.nn.Linear(dimension, hidden)
            self.target_embedding = torch.nn.Embedding(len(codec["target_vocabulary"]),
                                                      config["token_embedding_dim"], padding_idx=0)
            self.decoder = torch.nn.GRU(config["token_embedding_dim"], hidden, batch_first=True)
            self.output = torch.nn.Linear(hidden, len(codec["target_vocabulary"]))

        def project(self, latent):
            return latent + self.projection_up(torch.tanh(self.projection_down(latent)))

        def start(self, projected):
            return torch.tanh(self.condition(projected)).unsqueeze(0)

        def next_logits(self, tokens, hidden):
            outputs, hidden = self.decoder(self.target_embedding(tokens), hidden)
            return self.output(outputs), hidden

        def forward(self, latent, target):
            projected = self.project(latent)
            return projected, self.next_logits(target, self.start(projected))[0]
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(config["seed"])
        model = JointDecoder()
    return model


def _optimizer(model, config):
    return _torch().optim.Adam(model.parameters(), lr=config["learning_rate"], foreach=False)


def _pack(model, optimizer):
    states = {}
    for name, parameter in model.named_parameters():
        state = optimizer.state.get(parameter)
        if state:
            states[name] = {"step": int(state["step"].item()), "exp_avg": state["exp_avg"].detach().tolist(),
                           "exp_avg_sq": state["exp_avg_sq"].detach().tolist()}
    return ({name: value.detach().tolist() for name, value in model.state_dict().items()},
            {"schema": "adam-default-betas-eps/v1", "parameters": states})


def _tensor(value, template, label, *, nonnegative=False):
    def check(part, shape):
        if shape:
            _require(type(part) is list and len(part) == shape[0], label + " tensor shape differs")
            for item in part:
                check(item, shape[1:])
        else:
            _require(type(part) in (int, float) and math.isfinite(part) and (not nonnegative or part >= 0),
                     label + " tensor values must be finite and valid")
    check(value, tuple(template.shape))
    tensor = _torch().tensor(value, dtype=_torch().float32)
    _require(bool(_torch().isfinite(tensor).all()), label + " overflows float32")
    return tensor


def build_checkpoint(binding, train_rows, tune_rows, **options):
    """Initialize a separate head; no existing weights are converted or updated."""
    binding, config, implementation = _binding(binding), _config(**options), _implementation()
    train, tune = _splits(train_rows, tune_rows, binding["dimension"])
    # Reuse only the exact target grammar. The sentinel creates no textual model
    # vocabulary, and actual source strings never condition generation.
    codec = codec_module.fit_codec([{"id": row["id"], "source_text": "latent", "canonical_ir": row["canonical_ir"]}
                                    for row in train])
    for row in tune:
        codec_module.encode_target(codec, row["canonical_ir"])
    model = _model(binding, codec, config)
    weights, optimizer = _pack(model, _optimizer(model, config))
    checkpoint = {"schema": SCHEMA, "binding": binding, "projection_id": PROJECTION_ID, "config": config,
        "codec": codec, "implementation": implementation, "training_manifest_sha256": checkpoint_digest(train),
        "tuning_manifest_sha256": checkpoint_digest(tune), "training_count": len(train), "tuning_count": len(tune),
        "model_state": weights, "optimizer_state": optimizer,
        "progress": {"epochs_completed": 0, "row_cursor": 0, "optimizer_steps": 0},
        "parent_checkpoint_sha256": None, **FALSE}
    validate_checkpoint(checkpoint)
    return checkpoint


def _restore(checkpoint, expected_binding=None):
    torch = _torch()
    fields = {"schema", "binding", "projection_id", "config", "codec", "implementation",
        "training_manifest_sha256", "tuning_manifest_sha256", "training_count", "tuning_count",
        "model_state", "optimizer_state", "progress", "parent_checkpoint_sha256", *FALSE}
    _require(type(checkpoint) is dict and set(checkpoint) == fields and checkpoint["schema"] == SCHEMA,
             "closed latent checkpoint schema required")
    _require(len(_raw(checkpoint)) <= MAX_BYTES, "latent checkpoint exceeds byte bound")
    _require(all(checkpoint[key] is False for key in FALSE), "latent checkpoint cannot grant authority")
    binding = _binding(checkpoint["binding"])
    if expected_binding is not None:
        _require(binding == _binding(expected_binding), "latent checkpoint binding differs")
    _require(checkpoint["projection_id"] == PROJECTION_ID, "unsupported formula projection")
    _require(checkpoint["implementation"] == _implementation(), "latent formula source provenance differs")
    config = checkpoint["config"]
    keys = ("learning_rate", "batch_size", "seed", "hidden_size", "token_embedding_dim", "projection_width",
            "formula_weight", "reconstruction_weight")
    _require(type(config) is dict and all(name in config for name in keys), "closed model config required")
    _require(_raw(config) == _raw(_config(**{name: config[name] for name in keys})), "model config differs")
    codec_module.validate_codec(checkpoint["codec"])
    _require(checkpoint["codec"]["source_vocabulary"] == ["<pad>", "<unk>", "latent"],
             "latent model must not contain source vocabulary")
    for name in ("training_manifest_sha256", "tuning_manifest_sha256"):
        _require(type(checkpoint[name]) is str and _SHA.fullmatch(checkpoint[name]), "invalid manifest hash")
    parent = checkpoint["parent_checkpoint_sha256"]
    _require(parent is None or type(parent) is str and _SHA.fullmatch(parent), "invalid parent checkpoint hash")
    count, tune_count = checkpoint["training_count"], checkpoint["tuning_count"]
    _require(type(count) is int and 1 <= count <= MAX_ROWS and type(tune_count) is int and 0 <= tune_count <= MAX_ROWS,
             "invalid split counts")
    progress = checkpoint["progress"]
    _require(type(progress) is dict and set(progress) == {"epochs_completed", "row_cursor", "optimizer_steps"}
             and all(type(number) is int and 0 <= number <= 10**9 for number in progress.values()),
             "closed bounded integer training progress required")
    batch, cursor = config["batch_size"], progress["row_cursor"]
    _require(cursor < count and cursor % batch == 0 and progress["optimizer_steps"] ==
             progress["epochs_completed"] * math.ceil(count / batch) + cursor // batch,
             "optimizer step and row cursor differ")
    model = _model(binding, checkpoint["codec"], config)
    templates = model.state_dict()
    weights = checkpoint["model_state"]
    _require(type(weights) is dict and set(weights) == set(templates), "model state keys differ")
    model.load_state_dict({name: _tensor(weights[name], template, name) for name, template in templates.items()})
    optimizer = _optimizer(model, config)
    moments = checkpoint["optimizer_state"]
    _require(type(moments) is dict and set(moments) == {"schema", "parameters"}
             and moments["schema"] == "adam-default-betas-eps/v1" and type(moments["parameters"]) is dict,
             "closed Adam moments required")
    parameters = dict(model.named_parameters())
    _require(set(moments["parameters"]) == (set(parameters) if progress["optimizer_steps"] else set()),
             "Adam parameter set differs")
    for name, item in moments["parameters"].items():
        _require(type(item) is dict and set(item) == {"step", "exp_avg", "exp_avg_sq"}
                 and type(item["step"]) is int and item["step"] == progress["optimizer_steps"],
                 "Adam parameter step differs")
        parameter = parameters[name]
        optimizer.state[parameter] = {"step": torch.tensor(float(item["step"])),
            "exp_avg": _tensor(item["exp_avg"], parameter, name + ".exp_avg"),
            "exp_avg_sq": _tensor(item["exp_avg_sq"], parameter, name + ".exp_avg_sq", nonnegative=True)}
    model.eval()
    return torch, model, optimizer


def validate_checkpoint(checkpoint, *, expected_binding=None):
    _restore(checkpoint, expected_binding)


def _batch(rows, codec):
    torch = _torch()
    targets = [codec_module.encode_target(codec, row["canonical_ir"]) for row in rows]
    width = max(map(len, targets))
    return (torch.tensor([row["latent"] for row in rows], dtype=torch.float32),
            torch.tensor([row["embedding"] for row in rows], dtype=torch.float32),
            torch.tensor([target + [0] * (width - len(target)) for target in targets], dtype=torch.long))


def _loss(model, rows, codec, config):
    torch = _torch()
    latent, expected_embedding, target = _batch(rows, codec)
    projected, logits = model(latent, target[:, :-1])
    expected = target[:, 1:]
    formula = torch.nn.functional.cross_entropy(logits.reshape(-1, logits.shape[-1]), expected.reshape(-1), ignore_index=0)
    reconstruction = torch.nn.functional.mse_loss(projected, expected_embedding)
    total = config["formula_weight"] * formula + config["reconstruction_weight"] * reconstruction
    return total, formula, reconstruction, int((expected != 0).sum())


def _norm(values):
    return math.sqrt(sum(float(value.detach().double().square().sum()) for value in values if value is not None))


def _metrics(model, rows, codec, config, deadline):
    torch = _torch()
    evaluated, tokens, ce, reconstruction = 0, 0, 0., 0.
    model.eval()
    with torch.no_grad():
        for start in range(0, len(rows), config["batch_size"]):
            if time.monotonic() >= deadline:
                break
            batch = rows[start:start + config["batch_size"]]
            loss, formula, mse, count = _loss(model, batch, codec, config)
            _require(bool(torch.isfinite(loss)), "nonfinite evaluation loss")
            ce += float(formula) * count
            reconstruction += float(mse) * len(batch)
            tokens += count
            evaluated += len(batch)
    return {"token_cross_entropy": ce / tokens if tokens else None,
        "reconstruction_mse": reconstruction / evaluated if evaluated else None,
        "rows_evaluated": evaluated, "token_count": tokens, "complete": evaluated == len(rows),
        "teacher_forcing": True, "used_for_fit_or_selection": False}


def train(checkpoint, train_rows, tune_rows, *, epochs=20, max_seconds=60, max_optimizer_steps=None):
    """Continue complete batches, retaining exact Adam and partial-epoch cursor.

    Formula and reconstruction losses jointly update the residual projection.
    Tuning metrics are observational; this API does not select or promote a
    candidate. The deadline is soft at numeric-batch and evaluation boundaries.
    """
    started = time.monotonic()
    _require(type(epochs) is int and 1 <= epochs <= 1000, "epochs must be in 1..1000")
    _require(type(max_seconds) in (int, float) and math.isfinite(max_seconds) and 0 <= max_seconds <= 3600,
             "bounded nonnegative deadline required")
    _require(max_optimizer_steps is None or type(max_optimizer_steps) is int and 0 <= max_optimizer_steps <= 100000,
             "bounded optimizer step budget required")
    deadline = started + max_seconds
    torch, model, optimizer = _restore(checkpoint)
    training, tuning = _splits(train_rows, tune_rows, checkpoint["binding"]["dimension"])
    _require(checkpoint_digest(training) == checkpoint["training_manifest_sha256"]
             and checkpoint_digest(tuning) == checkpoint["tuning_manifest_sha256"], "resume manifests differ")
    config, codec = checkpoint["config"], checkpoint["codec"]
    progress = dict(checkpoint["progress"])
    start_step, start_epoch = progress["optimizer_steps"], progress["epochs_completed"]
    goal = start_epoch + epochs
    before = _metrics(model, training, codec, config, deadline)
    initial, _ = _pack(model, optimizer)
    groups = {"projection": [parameter for name, parameter in model.named_parameters() if name.startswith("projection_")],
              "decoder": [parameter for name, parameter in model.named_parameters() if not name.startswith("projection_")]}
    maximum = {"projection": 0., "decoder": 0., "formula_to_projection": 0.}
    history, stopped = [], "epoch_limit"
    while progress["epochs_completed"] < goal:
        if time.monotonic() >= deadline:
            stopped = "deadline_before_batch"; break
        if max_optimizer_steps is not None and progress["optimizer_steps"] - start_step >= max_optimizer_steps:
            stopped = "optimizer_step_budget"; break
        order = list(range(len(training)))
        random.Random(config["seed"] + progress["epochs_completed"]).shuffle(order)
        indices = order[progress["row_cursor"]:progress["row_cursor"] + config["batch_size"]]
        batch = [training[index] for index in indices]
        model.train()
        optimizer.zero_grad(set_to_none=True)
        loss, formula, mse, tokens = _loss(model, batch, codec, config)
        _require(bool(torch.isfinite(loss)), "nonfinite joint training loss")
        formula_gradients = torch.autograd.grad(formula, groups["projection"], retain_graph=True)
        _require(all(bool(torch.isfinite(value).all()) for value in formula_gradients), "nonfinite formula projection gradient")
        maximum["formula_to_projection"] = max(maximum["formula_to_projection"], _norm(formula_gradients))
        loss.backward()
        for name, parameters in groups.items():
            _require(all(parameter.grad is not None and bool(torch.isfinite(parameter.grad).all()) for parameter in parameters),
                     "missing or nonfinite joint gradient")
            maximum[name] = max(maximum[name], _norm(parameter.grad for parameter in parameters))
        torch.nn.utils.clip_grad_norm_(list(model.parameters()), 5., error_if_nonfinite=True)
        optimizer.step()
        _require(all(bool(torch.isfinite(parameter).all()) for parameter in model.parameters()), "nonfinite updated weights")
        _require(all(bool(torch.isfinite(value).all()) for item in optimizer.state.values() for value in item.values()
                     if torch.is_tensor(value)), "nonfinite updated Adam moments")
        progress["optimizer_steps"] += 1
        progress["row_cursor"] += len(indices)
        if progress["row_cursor"] == len(training):
            progress["epochs_completed"] += 1
            progress["row_cursor"] = 0
        history.append({"step": progress["optimizer_steps"], "token_cross_entropy": float(formula.detach()),
                        "reconstruction_mse": float(mse.detach()), "joint_loss": float(loss.detach()), "token_count": tokens})
    after = _metrics(model, training, codec, config, deadline)
    tuning_metrics = _metrics(model, tuning, codec, config, deadline)
    weights, moments = _pack(model, optimizer)
    result = copy.deepcopy(checkpoint)
    result.update(model_state=weights, optimizer_state=moments, progress=progress,
                  parent_checkpoint_sha256=checkpoint_digest(checkpoint))
    _require(result["implementation"] == _implementation(), "latent producer changed during training")
    _require(len(_raw(result)) <= MAX_BYTES, "latent checkpoint exceeds byte bound")
    selected = lambda state, prefix: {name: value for name, value in state.items()
                                     if name.startswith("projection_") == (prefix == "projection")}
    evidence = {name: {"gradient_norm_max": maximum[name],
        "initial_parameters_sha256": checkpoint_digest(selected(initial, name)),
        "final_parameters_sha256": checkpoint_digest(selected(weights, name)),
        "parameter_update_l2": _norm(torch.tensor(weights[key], dtype=torch.float64) - torch.tensor(initial[key], dtype=torch.float64)
                                      for key in selected(weights, name))} for name in groups}
    report = {"schema": "modal-latent-formula-training/v1", "binding": copy.deepcopy(checkpoint["binding"]),
        "checkpoint_sha256": checkpoint_digest(result), "parent_checkpoint_sha256": checkpoint_digest(checkpoint),
        "projection_id": PROJECTION_ID, "training_executed": progress["optimizer_steps"] > start_step,
        "optimizer_steps": progress["optimizer_steps"] - start_step,
        "epochs_completed": progress["epochs_completed"] - start_epoch, "progress": dict(progress),
        "stopped_reason": stopped, "elapsed_seconds": time.monotonic() - started,
        "deadline_scope": "soft_before_batch; preparation_serialization_and_inflight_batch_not_interruptible",
        "training_before": before, "training_after": after, "tuning": tuning_metrics, "batch_losses": history,
        "parameter_evidence": evidence, "formula_projection_gradient_norm_max": maximum["formula_to_projection"],
        "objective": "formula_token_cross_entropy_plus_projected_embedding_mse",
        "core_sparse_weights_frozen_for_formula_gradient": True, "sample_memory_used": False,
        "source_text_is_neural_input": False, "formula_conditioning": "learned_residual_projection_of_core_representation",
        "heldout_canary": False, "selection_performed": False, "family_backend_syntax_checked": False,
        "unsupported_projection_policy": "explicit_abstention", "examples_persisted": False,
        "download_calls": 0, "provider_calls": 0, **FALSE}
    return {"checkpoint": result, "report": report}


def _display(canonical_ir):
    rule = canonical_ir["rules"][0]
    atom = lambda value: value if re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", value) else json.dumps(value, ensure_ascii=False)
    text = rule["modality"] + "(" + atom(rule["action"]) + "(" + atom(rule["actor"]) + ", " + atom(rule["object"]) + "))"
    qualifiers = {field: rule[field] for field in ("conditions", "exceptions", "temporal") if rule[field]}
    return text + (" scope=" + json.dumps(qualifiers, sort_keys=True, ensure_ascii=False) if qualifiers else "")


class LatentFormulaDecoder:
    """Worker-private cached inference; inputs never include formula targets."""
    def __init__(self, checkpoint, *, expected_binding=None):
        self.torch, self.model, _ = _restore(checkpoint, expected_binding)
        self._checkpoint = copy.deepcopy(checkpoint)
        self._checkpoint_sha256 = checkpoint_digest(checkpoint)
        self._codec = self._checkpoint["codec"]
        # A version-counter-only check misses writes through tensor.data. Keep
        # one tensor-sized reference, rather than repeatedly serializing the
        # full JSON checkpoint (which also contains Adam and provenance).
        self._reference_weights = {name: tensor.detach().clone()
                                   for name, tensor in self.model.state_dict().items()}

    @property
    def checkpoint(self):
        """A diagnostic snapshot; callers cannot mutate inference metadata."""
        return copy.deepcopy(self._checkpoint)

    @property
    def codec(self):
        return copy.deepcopy(self._codec)

    @property
    def checkpoint_sha256(self):
        return self._checkpoint_sha256

    def _check(self):
        _torch()
        _require(self._checkpoint["implementation"] == _implementation(), "latent source provenance differs")
        state = self.model.state_dict()
        _require(set(state) == set(self._reference_weights), "cached decoder weights differ from checkpoint")
        _require(all(tensor.shape == self._reference_weights[name].shape
                     and tensor.dtype == self._reference_weights[name].dtype
                     and tensor.device == self._reference_weights[name].device
                     and self.torch.equal(tensor, self._reference_weights[name])
                     for name, tensor in state.items()), "cached decoder weights differ from checkpoint")

    def project(self, latents):
        self._check()
        _require(type(latents) in (list, tuple) and 1 <= len(latents) <= 128, "one to 128 vectors required")
        for latent in latents:
            _vector(latent, self._checkpoint["binding"]["dimension"], "latent")
        self.model.eval()
        with self.torch.no_grad():
            values = self.model.project(self.torch.tensor(latents, dtype=self.torch.float32))
            _require(bool(self.torch.isfinite(values).all()), "nonfinite learned projection")
            result = values.tolist()
        self._check()
        return result

    def _decode(self, row, projection_id):
        base = {"id": row["id"], "source_sha256": hashlib.sha256(row["source_text"].encode()).hexdigest(),
            "latent_sha256": checkpoint_digest(row["latent"]), "projection_id": projection_id,
            "status": "abstained", "reason": None, "canonical_ir": None, "formula_text": None, "formal_outputs": [],
            "teacher_forcing": False, "target_access": False, "training_executed": False,
            "source_text_is_neural_input": False, "latent_input_conditioned": True, "independent_text_to_logic": False,
            "learned_formula_generation": True, "sample_memory_used": False, "family_syntax_checked": False,
            "temperature": 0, **FALSE}
        if projection_id != PROJECTION_ID:
            return {**base, "reason": "unsupported_formula_projection"}
        if not self._checkpoint["progress"]["optimizer_steps"]:
            return {**base, "reason": "untrained_formula_head"}
        if not bool(self.model.output.weight.detach().any()) and not bool(self.model.output.bias.detach().any()):
            return {**base, "reason": "zero_output_head"}
        torch = self.torch
        prefix, minimum_margin = [codec_module.TARGET_BOS], None
        self.model.eval()
        with torch.no_grad():
            projected = self.model.project(torch.tensor([row["latent"]], dtype=torch.float32))
            if not bool(torch.isfinite(projected).all()):
                return {**base, "reason": "nonfinite_learned_projection"}
            hidden = self.model.start(projected)
            if not bool(torch.isfinite(hidden).all()):
                return {**base, "reason": "nonfinite_decoder_condition"}
            for _ in range(63):
                allowed = codec_module.allowed_token_ids(self._codec, prefix)
                if not allowed:
                    return {**base, "reason": "no_allowed_grammar_token", "generated_token_ids": prefix}
                logits, hidden = self.model.next_logits(torch.tensor([[prefix[-1]]], dtype=torch.long), hidden)
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
                        canonical_ir = codec_module.decode_target(self._codec, prefix)
                    except ValueError as error:
                        return {**base, "reason": "generated_ir_rejected", "detail": str(error), "generated_token_ids": prefix}
                    display = _display(canonical_ir)
                    output = {"family": "deontic", "format": "typed-deontic-rule/v1",
                        "payload": canonical_ir["rules"][0], "formula_text": display,
                        "formula_text_role": "display_only_full_ast_is_authoritative",
                        "syntax_scope": "canonical_rule_schema_and_decoder_grammar",
                        "origin": "learned_latent_conditioned_formula_decoder", **FALSE}
                    return {**base, "status": "decoded", "canonical_ir": canonical_ir, "formula_text": display,
                        "formal_outputs": [output], "generated_token_ids": prefix,
                        "minimum_decision_logit_margin": minimum_margin,
                        "syntax_scope": "canonical_rule_schema_and_decoder_grammar"}
        return {**base, "reason": "generation_length_limit", "generated_token_ids": prefix}

    def infer(self, rows, *, projection_id=PROJECTION_ID):
        self._check()
        _require(type(projection_id) is str and 0 < len(projection_id) <= 256, "bounded projection id required")
        _require(type(rows) in (list, tuple) and 1 <= len(rows) <= 128, "one to 128 inference rows required")
        validated = _rows(rows, self._checkpoint["binding"]["dimension"], training=False)
        results = [self._decode(row, projection_id) for row in validated]
        self._check()
        count = sum(row["status"] == "decoded" for row in results)
        return {"schema": "modal-latent-formula-inference/v1", "binding": copy.deepcopy(self._checkpoint["binding"]),
            "checkpoint_sha256": self.checkpoint_sha256, "rows": results, "decoded_count": count,
            "status": "decoded" if count == len(rows) else "partial" if count else "abstained",
            "decoded_formulas_generated": count > 0, "training_executed": False,
            "source_text_is_neural_input": False, "latent_input_conditioned": True,
            "teacher_forcing": False, "target_access": False, "learned_formula_generation": True,
            "independent_text_to_logic": False, "sample_memory_used": False, **FALSE}


def infer(checkpoint, rows, *, expected_binding=None, projection_id=PROJECTION_ID):
    return LatentFormulaDecoder(checkpoint, expected_binding=expected_binding).infer(rows, projection_id=projection_id)


def project(checkpoint, latents, *, expected_binding=None):
    return LatentFormulaDecoder(checkpoint, expected_binding=expected_binding).project(latents)


def save_checkpoint(checkpoint, path):
    validate_checkpoint(checkpoint)
    data = _raw(checkpoint)
    destination = Path(path)
    with destination.open("xb") as handle:
        handle.write(data)
    return {"path": str(destination), "sha256": hashlib.sha256(data).hexdigest(), "size_bytes": len(data), **FALSE}


def load_checkpoint(path, *, expected_sha256, expected_binding=None):
    _require(type(expected_sha256) is str and _SHA.fullmatch(expected_sha256), "expected checkpoint SHA256 required")
    source = Path(path)
    _require(not source.is_symlink(), "checkpoint symlink is forbidden")
    metadata = source.stat()
    _require(stat.S_ISREG(metadata.st_mode) and metadata.st_size <= MAX_BYTES, "bounded regular checkpoint file required")
    data = source.read_bytes()
    _require(len(data) <= MAX_BYTES and hashlib.sha256(data).hexdigest() == expected_sha256, "checkpoint hash differs")
    def pairs(items):
        result = {}
        for key, value in items:
            _require(key not in result, "duplicate JSON keys are forbidden")
            result[key] = value
        return result
    result = json.loads(data, object_pairs_hook=pairs)
    _require(_raw(result) == data, "checkpoint requires canonical finite JSON")
    validate_checkpoint(result, expected_binding=expected_binding)
    return result


__all__ = ["SCHEMA", "ARCHITECTURE", "PROJECTION_ID", "FALSE", "build_checkpoint", "train", "infer", "project",
           "LatentFormulaDecoder", "checkpoint_digest", "validate_checkpoint", "save_checkpoint", "load_checkpoint"]
