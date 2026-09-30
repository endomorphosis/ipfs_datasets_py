"""Bounded, resumable source-conditioned formula learning; no admission authority.

This is a new GRU sequence lineage, not a decoder retrofitted into old weights.
Teacher targets enter training only. Generation receives source text and uses
model logits under the codec's structural grammar. Checkpoints contain no
training examples, retrieval index, executable metadata, or pickle objects.
Sessions are worker-private; CPU thread/process allocation belongs to the caller.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
from pathlib import Path
import random
import re
import stat
import time

from . import legal_formula_codec as codec_module

SCHEMA = "learned-legal-formula-checkpoint/v1"
LINEAGE_ID = "source_conditioned_formula_v1"
ARCHITECTURE = "source-gru-attention-formula-gru/v1"
MAX_BYTES = 48 * 1024 * 1024
MAX_EXAMPLES = 4096
MAX_BATCH = 16
FALSE = {"qualified": False, "admitted": False, "formalized": False, "roundtrip_ok": False,
         "proof_authority": False, "semantic_correctness_verified": False,
         "promotion_performed": False, "publication_performed": False}
_SHA = re.compile(r"[0-9a-f]{64}\Z")


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("utf-8")


def _digest(value):
    return hashlib.sha256(_raw(value)).hexdigest()


def checkpoint_digest(checkpoint):
    """Canonical content identity; validation is separate and explicit."""
    return _digest(checkpoint)


def _capture_implementation():
    from ...logic.legal_ir import canonical_contracts
    from ...logic.autoformal import tree_pin
    from . import legal_ir_grammar_decoder
    return {"scope": "listed_files_only", "files": {
        "legal_formula_learning.py": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "legal_formula_codec.py": hashlib.sha256(Path(codec_module.__file__).read_bytes()).hexdigest(),
        "canonical_contracts.py": hashlib.sha256(Path(canonical_contracts.__file__).read_bytes()).hexdigest(),
        "legal_ir_grammar_decoder.py": hashlib.sha256(Path(legal_ir_grammar_decoder.__file__).read_bytes()).hexdigest(),
        "tree_pin.py": hashlib.sha256(Path(tree_pin.__file__).read_bytes()).hexdigest(),
    }}


_IMPLEMENTATION_AT_IMPORT = _capture_implementation()


def _implementation():
    current = _capture_implementation()
    _require(current == _IMPLEMENTATION_AT_IMPORT, "formula implementation changed since decoder import")
    return current


def _require_workspace_tree():
    from ...logic.autoformal import tree_pin
    from ...logic.legal_ir import canonical_contracts
    from . import legal_ir_grammar_decoder
    expected = None
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "ipfs_datasets_py"
        if (candidate / "logic/autoformal/tree_pin.py").is_file():
            expected = candidate.resolve()
            break
    _require(expected is not None, "cannot identify canonical formula package tree")
    for module in (tree_pin, canonical_contracts, legal_ir_grammar_decoder):
        _require(expected in Path(module.__file__).resolve().parents,
                 "formula dependency loaded outside canonical workspace tree")
    _require(Path(codec_module.__file__).resolve().parent == Path(__file__).resolve().parent,
             "formula codec loaded from a different runtime tree")
    tree_pin.require_workspace_logic_tree()


def _config(torch, *, learning_rate, batch_size, seed, hidden_size, embedding_dim):
    _require(type(learning_rate) in (int, float) and math.isfinite(learning_rate)
             and 0 < learning_rate <= 0.1, "learning_rate must be finite in (0, 0.1]")
    for name, value, lower, upper in (("batch_size", batch_size, 1, MAX_BATCH),
            ("seed", seed, 0, 2**31 - 1), ("hidden_size", hidden_size, 8, 128),
            ("embedding_dim", embedding_dim, 8, 64)):
        _require(type(value) is int and lower <= value <= upper,
                 name + " is outside the bounded integer range")
    return {"architecture": ARCHITECTURE, "device": "cpu", "dtype": "float32",
            "torch_version": str(torch.__version__), "learning_rate": float(learning_rate),
            "batch_size": batch_size, "seed": seed, "hidden_size": hidden_size,
            "embedding_dim": embedding_dim, "temperature": 0,
            "max_source_tokens": 64, "max_target_tokens": 64}


def _model(torch, codec, config):
    class SequenceDecoder(torch.nn.Module):
        def __init__(self):
            super().__init__()
            width, hidden = config["embedding_dim"], config["hidden_size"]
            self.source_embedding = torch.nn.Embedding(len(codec["source_vocabulary"]), width, padding_idx=0)
            self.target_embedding = torch.nn.Embedding(len(codec["target_vocabulary"]), width, padding_idx=0)
            self.encoder = torch.nn.GRU(width, hidden, batch_first=True)
            self.decoder = torch.nn.GRU(width, hidden, batch_first=True)
            self.output = torch.nn.Linear(hidden * 2, len(codec["target_vocabulary"]))

        def encode(self, source, lengths):
            packed = torch.nn.utils.rnn.pack_padded_sequence(self.source_embedding(source), lengths,
                                                             batch_first=True, enforce_sorted=False)
            encoded, hidden = self.encoder(packed)
            encoded, _ = torch.nn.utils.rnn.pad_packed_sequence(encoded, batch_first=True,
                                                               total_length=source.shape[1])
            return encoded, hidden

        def next_logits(self, tokens, hidden, encoded, mask):
            outputs, hidden = self.decoder(self.target_embedding(tokens), hidden)
            scores = torch.bmm(outputs, encoded.transpose(1, 2)) / math.sqrt(config["hidden_size"])
            attention = torch.softmax(scores.masked_fill(~mask[:, None, :], -1e9), dim=-1)
            context = torch.bmm(attention, encoded)
            return self.output(torch.cat((outputs, context), dim=-1)), hidden

        def forward(self, source, lengths, target):
            encoded, hidden = self.encode(source, lengths)
            return self.next_logits(target, hidden, encoded, source != 0)[0]

    # Do not perturb a host application's random generator when loading a model.
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(config["seed"])
        return SequenceDecoder()


def _examples(examples, *, allow_empty=False):
    _require(type(examples) in (list, tuple) and (0 if allow_empty else 1) <= len(examples) <= MAX_EXAMPLES,
             "bounded list of formula examples required")
    ids, sources = set(), set()
    for row in examples:
        _require(type(row) is dict and set(row) == {"id", "source_text", "canonical_ir"},
                 "closed formula example schema required")
        _require(type(row["id"]) is str and 0 < len(row["id"]) <= 512 and row["id"] not in ids,
                 "unique bounded example id required")
        _require(type(row["source_text"]) is str and 0 < len(row["source_text"]) <= 16384,
                 "bounded nonempty source required")
        _require(row["source_text"] not in sources, "duplicate source text in examples")
        ids.add(row["id"])
        sources.add(row["source_text"])
    return list(examples)


def _tensor(torch, value, shape, label, *, nonnegative=False):
    def check(part, dims):
        if dims:
            _require(type(part) is list and len(part) == dims[0], label + " tensor shape differs")
            for item in part:
                check(item, dims[1:])
        else:
            _require(type(part) in (float, int) and math.isfinite(part)
                     and (not nonnegative or part >= 0), label + " tensor values must be finite")
    check(value, tuple(shape))
    tensor = torch.tensor(value, dtype=torch.float32)
    _require(bool(torch.isfinite(tensor).all()), label + " overflows float32")
    return tensor


def _restore(checkpoint):
    """Validate closed data before loading model/optimizer; no metadata imports."""
    import torch
    _require_workspace_tree()
    fields = {"schema", "lineage_id", "config", "codec", "implementation",
              "training_manifest_sha256", "tuning_manifest_sha256", "training_pair_count",
              "tuning_pair_count", "model_state", "optimizer_state", "progress",
              "parent_checkpoint_sha256", *FALSE}
    _require(type(checkpoint) is dict and set(checkpoint) == fields,
             "closed learned formula checkpoint schema required")
    _require(checkpoint["schema"] == SCHEMA and checkpoint["lineage_id"] == LINEAGE_ID
             and all(checkpoint[key] is False for key in FALSE), "checkpoint authority or lineage differs")
    _require(len(_raw(checkpoint)) <= MAX_BYTES, "checkpoint exceeds byte bound")
    _require(checkpoint["implementation"] == _implementation(), "formula implementation source drift")
    config = checkpoint["config"]
    _require(type(config) is dict, "checkpoint config must be an object")
    required = ("learning_rate", "batch_size", "seed", "hidden_size", "embedding_dim")
    _require(all(key in config for key in required), "incomplete checkpoint config")
    _require(_raw(config) == _raw(_config(torch, **{key: config[key] for key in required})),
             "unsupported formula architecture/config/runtime")
    codec_module.validate_codec(checkpoint["codec"])
    for field in ("training_manifest_sha256", "tuning_manifest_sha256"):
        _require(type(checkpoint[field]) is str and _SHA.fullmatch(checkpoint[field]), "invalid manifest identity")
    parent = checkpoint["parent_checkpoint_sha256"]
    _require(parent is None or (type(parent) is str and _SHA.fullmatch(parent)), "invalid parent checkpoint identity")
    count, tuning_count = checkpoint["training_pair_count"], checkpoint["tuning_pair_count"]
    _require(type(count) is int and 1 <= count <= MAX_EXAMPLES and type(tuning_count) is int
             and 0 <= tuning_count <= MAX_EXAMPLES, "invalid checkpoint pair counts")
    progress = checkpoint["progress"]
    _require(type(progress) is dict and set(progress) == {"epochs_completed", "row_cursor", "optimizer_steps"},
             "closed training progress required")
    _require(all(type(value) is int and 0 <= value <= 10**9 for value in progress.values()),
             "invalid training progress")
    cursor, batch = progress["row_cursor"], config["batch_size"]
    _require(cursor < count and cursor % batch == 0, "invalid within-epoch row cursor")
    _require(progress["optimizer_steps"] == progress["epochs_completed"] * math.ceil(count / batch) + cursor // batch,
             "optimizer step/cursor identity differs")
    model = _model(torch, checkpoint["codec"], config)
    expected = model.state_dict()
    weights = checkpoint["model_state"]
    _require(type(weights) is dict and set(weights) == set(expected), "model state keys differ")
    tensors = {name: _tensor(torch, weights[name], tensor.shape, name) for name, tensor in expected.items()}
    model.load_state_dict(tensors)
    model.eval()
    optim = checkpoint["optimizer_state"]
    _require(type(optim) is dict and set(optim) == {"schema", "parameters"}
             and optim["schema"] == "adam-default-betas-eps/v1" and type(optim["parameters"]) is dict,
             "unsupported optimizer state")
    names = dict(model.named_parameters())
    _require(set(optim["parameters"]) == (set(names) if progress["optimizer_steps"] else set()),
             "optimizer parameter set differs")
    optimizer = torch.optim.Adam(model.parameters(), lr=config["learning_rate"], foreach=False)
    for name, state in optim["parameters"].items():
        _require(type(state) is dict and set(state) == {"step", "exp_avg", "exp_avg_sq"}
                 and type(state["step"]) is int and state["step"] == progress["optimizer_steps"],
                 "optimizer moment step differs")
        parameter = names[name]
        optimizer.state[parameter] = {
            "step": torch.tensor(float(state["step"]), dtype=torch.float32),
            "exp_avg": _tensor(torch, state["exp_avg"], parameter.shape, name + ".exp_avg"),
            "exp_avg_sq": _tensor(torch, state["exp_avg_sq"], parameter.shape, name + ".exp_avg_sq", nonnegative=True),
        }
    return torch, model, optimizer


def validate_checkpoint(checkpoint):
    _restore(checkpoint)


def _pack(model, optimizer):
    weights = {name: value.detach().tolist() for name, value in model.state_dict().items()}
    states = {}
    for name, parameter in model.named_parameters():
        state = optimizer.state.get(parameter)
        if state:
            states[name] = {"step": int(state["step"].item()),
                           "exp_avg": state["exp_avg"].detach().tolist(),
                           "exp_avg_sq": state["exp_avg_sq"].detach().tolist()}
    return weights, {"schema": "adam-default-betas-eps/v1", "parameters": states}


def _batch(torch, records):
    sources, targets = zip(*records)
    def padded(rows):
        width = max(map(len, rows))
        return torch.tensor([list(row) + [0] * (width - len(row)) for row in rows], dtype=torch.long)
    return padded(sources), torch.tensor(list(map(len, sources))), padded(targets)


def _loss(torch, model, records):
    source, lengths, target = _batch(torch, records)
    logits = model(source, lengths, target[:, :-1])
    expected = target[:, 1:]
    loss = torch.nn.functional.cross_entropy(logits.reshape(-1, logits.shape[-1]), expected.reshape(-1), ignore_index=0)
    return loss, int((expected != 0).sum())


def _teacher_metrics(torch, model, records, batch_size, deadline):
    total, tokens, rows = 0.0, 0, 0
    model.eval()
    with torch.no_grad():
        for start in range(0, len(records), batch_size):
            if time.monotonic() >= deadline:
                break
            batch = records[start:start + batch_size]
            loss, count = _loss(torch, model, batch)
            _require(bool(torch.isfinite(loss)), "nonfinite token cross entropy")
            total += float(loss) * count
            tokens += count
            rows += len(batch)
    return {"token_cross_entropy": total / tokens if tokens else None,
            "rows_evaluated": rows, "complete": rows == len(records), "teacher_forcing": True}


def train_decoder(training_examples, tuning_examples, *, epochs=20, max_seconds=60,
                  learning_rate=0.008, batch_size=8, seed=1729, hidden_size=64,
                  embedding_dim=32, checkpoint=None):
    """Fit additional completed epochs; resume uses the same manifests/settings.

    Source and ID splits are disjoint. Targets may overlap; token CE is not a
    semantic generalization claim. A deadline commits only completed batches;
    an individual in-flight batch is not interrupted or partially published.
    """
    import torch
    started = time.monotonic()
    _require_workspace_tree()
    provenance = _implementation()
    _require(type(epochs) is int and 1 <= epochs <= 1000, "epochs must be in 1..1000")
    _require(type(max_seconds) in (int, float) and math.isfinite(max_seconds)
             and 0 <= max_seconds <= 3600, "bounded nonnegative max_seconds required")
    deadline = started + max_seconds
    train, tuning = _examples(training_examples), _examples(tuning_examples, allow_empty=True)
    _require(not {row["id"] for row in train} & {row["id"] for row in tuning}, "training/tuning IDs overlap")
    _require(not {row["source_text"] for row in train} & {row["source_text"] for row in tuning},
             "training/tuning sources overlap")
    config = _config(torch, learning_rate=learning_rate, batch_size=batch_size,
                     seed=seed, hidden_size=hidden_size, embedding_dim=embedding_dim)
    codec = codec_module.fit_codec(train)
    records = [(codec_module.encode_source(codec, row["source_text"]),
                codec_module.encode_target(codec, row["canonical_ir"])) for row in train]
    source_identities = {tuple(source) for source, _ in records}
    _require(len(source_identities) == len(records), "duplicate tokenized training source")
    tuning_records, rejected_tuning = [], []
    tuning_identities = set()
    for row in tuning:
        try:
            source = codec_module.encode_source(codec, row["source_text"])
        except ValueError as exc:
            rejected_tuning.append({"id": row["id"], "reason": str(exc)})
            continue
        identity = tuple(source)
        _require(identity not in source_identities, "training/tuning tokenized sources overlap")
        _require(identity not in tuning_identities, "duplicate tokenized tuning source")
        tuning_identities.add(identity)
        try:
            tuning_records.append((source, codec_module.encode_target(codec, row["canonical_ir"])))
        except ValueError as exc:
            rejected_tuning.append({"id": row["id"], "reason": str(exc)})
    parent = None if checkpoint is None else checkpoint_digest(checkpoint)
    if checkpoint is None:
        model = _model(torch, codec, config)
        optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate, foreach=False)
        progress = {"epochs_completed": 0, "row_cursor": 0, "optimizer_steps": 0}
    else:
        _, model, optimizer = _restore(checkpoint)
        _require(checkpoint["config"] == config and checkpoint["codec"] == codec,
                 "resume configuration or codec differs")
        _require(checkpoint["training_manifest_sha256"] == _digest(train)
                 and checkpoint["tuning_manifest_sha256"] == _digest(tuning), "resume manifests differ")
        progress = dict(checkpoint["progress"])
    initial_weights, _ = _pack(model, optimizer)
    initial_head = _digest({key: value for key, value in initial_weights.items() if key.startswith("output.")})
    start_steps, start_epochs = progress["optimizer_steps"], progress["epochs_completed"]
    desired_epoch = start_epochs + epochs
    before = _teacher_metrics(torch, model, records, batch_size, deadline)
    history, head_gradient_norm_max, gradient_norm_max = [], 0.0, 0.0
    stopped = "epoch_limit"
    while progress["epochs_completed"] < desired_epoch:
        if time.monotonic() >= deadline:
            stopped = "deadline_before_batch"
            break
        epoch = progress["epochs_completed"]
        order = list(range(len(records)))
        random.Random(seed + epoch).shuffle(order)
        start = progress["row_cursor"]
        indices = order[start:start + batch_size]
        batch = [records[index] for index in indices]
        model.train()
        optimizer.zero_grad(set_to_none=True)
        loss, token_count = _loss(torch, model, batch)
        _require(bool(torch.isfinite(loss)), "nonfinite formula training loss")
        loss.backward()
        parameters = list(model.parameters())
        _require(all(parameter.grad is not None and bool(torch.isfinite(parameter.grad).all())
                     for parameter in parameters), "missing or nonfinite formula reconstruction gradients")
        head_norm = math.sqrt(sum(float(parameter.grad.detach().double().square().sum())
                                  for name, parameter in model.named_parameters() if name.startswith("output.")))
        norm = float(torch.nn.utils.clip_grad_norm_(parameters, 5.0, error_if_nonfinite=True))
        optimizer.step()
        _require(all(bool(torch.isfinite(parameter).all()) for parameter in parameters), "nonfinite updated formula parameters")
        _require(all(bool(torch.isfinite(value).all()) for state in optimizer.state.values()
                     for value in state.values() if torch.is_tensor(value)), "nonfinite optimizer moments")
        # Publish progress only after the complete numerical update is valid.
        progress["optimizer_steps"] += 1
        progress["row_cursor"] += len(indices)
        if progress["row_cursor"] == len(records):
            progress["epochs_completed"] += 1
            progress["row_cursor"] = 0
        history.append({"step": progress["optimizer_steps"], "epoch": epoch,
                        "token_cross_entropy": float(loss.detach()), "token_count": token_count})
        head_gradient_norm_max = max(head_gradient_norm_max, head_norm)
        gradient_norm_max = max(gradient_norm_max, norm)
    after = _teacher_metrics(torch, model, records, batch_size, deadline)
    tuning_metrics = _teacher_metrics(torch, model, tuning_records, batch_size, deadline)
    tuning_metrics.update({"scope": "held_out_sources_with_in_vocabulary_targets",
                          "rejected_rows": rejected_tuning, "split_source_and_id_disjoint": True,
                          "complete": not rejected_tuning and tuning_metrics["rows_evaluated"] == len(tuning),
                          "targets_required_disjoint": False, "used_for_fit_or_selection": False})
    weights, optim = _pack(model, optimizer)
    result = {"schema": SCHEMA, "lineage_id": LINEAGE_ID, "config": config, "codec": codec,
              "implementation": provenance, "training_manifest_sha256": _digest(train),
              "tuning_manifest_sha256": _digest(tuning), "training_pair_count": len(train),
              "tuning_pair_count": len(tuning), "model_state": weights, "optimizer_state": optim,
              "progress": progress, "parent_checkpoint_sha256": parent, **FALSE}
    _require(_implementation() == provenance, "formula source changed during training")
    _require(len(_raw(result)) <= MAX_BYTES, "checkpoint exceeds byte bound")
    report = {"schema": "learned-legal-formula-training/v1", "lineage_id": LINEAGE_ID,
              "parent_checkpoint_sha256": parent, "checkpoint_sha256": checkpoint_digest(result),
              "epochs_requested": epochs, "epochs_completed": progress["epochs_completed"] - start_epochs,
              "optimizer_steps": progress["optimizer_steps"] - start_steps, "progress": dict(progress),
              "stopped_reason": stopped, "elapsed_seconds": time.monotonic() - started,
              "deadline_scope": "soft_deadline_before_numeric_or_metric_batch; preparation_and_serialization_not_interruptible",
              "training_before": before, "training_after": after, "tuning": tuning_metrics,
              "batch_losses": history, "output_head_gradient_norm_max": head_gradient_norm_max,
              "gradient_norm_max": gradient_norm_max, "initial_model_state_sha256": _digest(initial_weights),
              "final_model_state_sha256": _digest(weights), "initial_output_head_sha256": initial_head,
              "final_output_head_sha256": _digest({key: value for key, value in weights.items() if key.startswith("output.")}),
              "training_executed": progress["optimizer_steps"] > start_steps,
              "independent_source_conditioning": True, "objective": "teacher_forced_formula_token_cross_entropy",
              "legacy_weights_used": False, "download_calls": 0, "provider_calls": 0,
              "sample_memory_used": False, "examples_persisted": False, **FALSE}
    return {"checkpoint": result, "report": report}


def _display(canonical_ir):
    rule = canonical_ir["rules"][0]
    name = lambda value: value if re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", value) else json.dumps(value, ensure_ascii=False)
    text = rule["modality"] + "(" + name(rule["action"]) + "(" + name(rule["actor"]) + ", " + name(rule["object"]) + "))"
    scope = {key: rule[key] for key in ("conditions", "exceptions", "temporal") if rule[key]}
    return text + (" scope=" + json.dumps(scope, sort_keys=True, ensure_ascii=False) if scope else "")


class LearnedLegalFormulaDecoder:
    """Cached worker-private inference; no targets, source parser or training API."""
    def __init__(self, checkpoint):
        self.torch, self.model, _ = _restore(checkpoint)
        self.checkpoint = copy.deepcopy(checkpoint)
        self.checkpoint_sha256 = checkpoint_digest(checkpoint)
        self.codec = self.checkpoint["codec"]

    def _decode(self, text):
        base = {"source_sha256": hashlib.sha256(text.encode()).hexdigest(),
                "status": "abstained", "canonical_ir": None, "formula_text": None, "formal_outputs": [],
                "teacher_forcing": False, "target_access": False, "training_executed": False,
                "source_input_conditioned": True, "independent_text_to_logic": True,
                "learned_formula_generation": True, "sample_memory_used": False,
                "family_syntax_checked": False, "temperature": 0, **FALSE}
        try:
            source_ids = codec_module.encode_source(self.codec, text)
        except ValueError as exc:
            return {**base, "reason": "source_encoding_rejected", "detail": str(exc)}
        torch = self.torch
        if not bool(self.model.output.weight.detach().any()) and not bool(self.model.output.bias.detach().any()):
            return {**base, "reason": "zero_output_head"}
        source = torch.tensor([source_ids], dtype=torch.long)
        prefix, minimum_margin = [1], None
        self.model.eval()
        with torch.no_grad():
            encoded, hidden = self.model.encode(source, torch.tensor([len(source_ids)]))
            for _ in range(63):
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
                if prefix[-1] == 2:
                    try:
                        canonical_ir = codec_module.decode_target(self.codec, prefix)
                    except ValueError as exc:
                        return {**base, "reason": "generated_ir_rejected", "detail": str(exc), "generated_token_ids": prefix}
                    display = _display(canonical_ir)
                    output = {"family": "deontic", "format": "typed-deontic-rule/v1",
                              "payload": canonical_ir["rules"][0], "formula_text": display,
                              "formula_text_role": "display_only_full_ast_is_authoritative",
                              "syntax_scope": "canonical_rule_schema_and_decoder_grammar",
                              "origin": "learned_source_conditioned_formula_decoder", **FALSE}
                    return {**base, "status": "decoded", "reason": None, "canonical_ir": canonical_ir,
                            "formula_text": display, "formal_outputs": [output],
                            "generated_token_ids": prefix, "minimum_decision_logit_margin": minimum_margin,
                            "syntax_scope": "canonical_rule_schema_and_decoder_grammar"}
        return {**base, "reason": "generation_length_limit", "generated_token_ids": prefix}

    def decode_formal_logic(self, texts):
        _require(type(texts) in (list, tuple) and 1 <= len(texts) <= 128
                 and all(type(text) is str and 0 < len(text) <= 16384 for text in texts),
                 "one to 128 bounded source strings required")
        _require_workspace_tree()
        _require(_implementation() == self.checkpoint["implementation"], "formula implementation source drift")
        rows = [self._decode(text) for text in texts]
        count = sum(row["status"] == "decoded" for row in rows)
        return {"schema": "learned-legal-formula-inference/v1", "lineage_id": LINEAGE_ID,
                "checkpoint_sha256": self.checkpoint_sha256, "rows": rows,
                "trained_checkpoint": self.checkpoint["progress"]["optimizer_steps"] > 0,
                "checkpoint_optimizer_steps": self.checkpoint["progress"]["optimizer_steps"],
                "status": "decoded" if count == len(rows) else "partial" if count else "abstained",
                "decoded_formulas_generated": count > 0, "decoded_count": count,
                "training_executed": False, "source_input_conditioned": True,
                "independent_text_to_logic": True, "learned_formula_generation": True,
                "teacher_forcing": False, "target_access": False, **FALSE}


def decode_formula(checkpoint, text):
    return LearnedLegalFormulaDecoder(checkpoint).decode_formal_logic([text])["rows"][0]


def save_checkpoint(checkpoint, path):
    """Write a new bounded JSON file exclusively; never overwrite a checkpoint."""
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
    return {"schema": SCHEMA, "path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def load_checkpoint(path, *, expected_sha256):
    _require(type(expected_sha256) is str and _SHA.fullmatch(expected_sha256), "expected checkpoint hash required")
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
        raise ValueError("invalid checkpoint JSON constant: " + value)
    checkpoint = json.loads(raw, object_pairs_hook=unique, parse_constant=reject)
    validate_checkpoint(checkpoint)
    return checkpoint
