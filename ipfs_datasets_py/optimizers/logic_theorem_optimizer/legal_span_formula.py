"""Experimental learned source-span decoder for one canonical deontic rule.

A fixed UTF-8 byte alphabet encodes source lexemes, a bidirectional GRU
contextualizes them, and learned heads choose modality, facet presence, and
token-aligned source spans. No fitted word/atom vocabulary, semantic source
parser, or target lookup participates in inference. This restricted architecture
cannot express paraphrased atoms, multiple rules, or multiple atoms per facet.
Schema validation and grounded copying do not establish legal correctness.
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

SCHEMA = "span-legal-formula-checkpoint/v1"
ARCHITECTURE = "utf8-byte-pool-bidirectional-gru-tied-film-span-heads/v1"
LINEAGE_ID = "source_span_formula_v1"
MAX_BYTES = 64 * 1024 * 1024
MAX_SOURCE_CHARACTERS = 16384
MAX_SOURCE_TOKENS = 256
MAX_TOKEN_BYTES = 2048
MAX_EXAMPLES = 4096
SPAN_FIELDS = ("actor", "action", "object", "conditions", "exceptions", "temporal")
OPTIONAL_FIELDS = ("object", "conditions", "exceptions", "temporal")
MODALITIES = ("O", "P", "F")
FALSE = {"qualified": False, "admitted": False, "formalized": False, "roundtrip_ok": False,
         "proof_authority": False, "semantic_correctness_verified": False,
         "promotion_performed": False, "publication_performed": False}
_TOKEN_RE = re.compile(r"\w+|[^\w\s]", re.UNICODE)
_SHA = re.compile(r"[0-9a-f]{64}\Z")


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("utf-8")


def checkpoint_digest(value):
    return hashlib.sha256(_raw(value)).hexdigest()


def _capture_implementation():
    # Include the transitive canonical/grammar validators used by _rule.
    paths = {"span": Path(__file__), "codec": Path(codec_module.__file__)}
    for name, value in (("canonical", codec_module.CanonicalRoundTripIR),
                        ("grammar", codec_module.LegalIRGrammarDecoder)):
        import importlib
        paths[name] = Path(importlib.import_module(value.__module__).__file__)
    return {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in paths.items()}


_IMPLEMENTATION_AT_IMPORT = _capture_implementation()


def _implementation():
    current = _capture_implementation()
    _require(current == _IMPLEMENTATION_AT_IMPORT, "span implementation changed since import")
    return current


def tokenize_source(text):
    """Structural Unicode lexemes with exact Python character offsets; no parsing."""
    _require(type(text) is str and text.strip(), "source_text must be nonempty text")
    _require(len(text) <= MAX_SOURCE_CHARACTERS, "source_too_long: character limit; truncation forbidden")
    matches = list(_TOKEN_RE.finditer(text))
    _require(0 < len(matches) <= MAX_SOURCE_TOKENS, "source_too_long: token limit; truncation forbidden")
    tokens = []
    for match in matches:
        encoded = match.group().casefold().encode("utf-8")
        _require(len(encoded) <= MAX_TOKEN_BYTES, "source_too_long: token byte limit; truncation forbidden")
        tokens.append({"text": match.group(), "start": match.start(), "end": match.end(),
                       "byte_ids": [byte + 1 for byte in encoded]})
    return tokens


def _vector(value, dimension):
    _require(type(value) in (list, tuple) and len(value) == dimension, "latent dimension differs")
    _require(all(type(item) in (int, float) and math.isfinite(item) and abs(item) <= 3.4028234e38
                 for item in value), "latent must contain finite float32 numbers")
    return list(value)


def _labels(text, canonical_ir, tokens):
    rule = codec_module._rule(canonical_ir)
    _require(all(len(rule[field]) <= 1 for field in codec_module.QUALIFIERS),
             "unsupported_target: at most one source span per qualifier facet")
    starts = {token["start"]: index for index, token in enumerate(tokens)}
    ends = {token["end"]: index for index, token in enumerate(tokens)}
    spans, presence = [], []
    for field in SPAN_FIELDS:
        atom = (rule[field][0] if rule[field] else "") if field in codec_module.QUALIFIERS else rule[field]
        if not atom:
            _require(field in OPTIONAL_FIELDS, "unsupported_target: actor/action must be nonempty")
            spans.append((-100, -100))
            presence.append(False)
            continue
        locations, cursor = [], 0
        while True:
            offset = text.find(atom, cursor)
            if offset < 0:
                break
            if offset in starts and offset + len(atom) in ends:
                locations.append((starts[offset], ends[offset + len(atom)]))
            cursor = offset + 1
        _require(len(locations) == 1, "unsupported_target: " + field +
                 (" atom is not an exact token-aligned source span" if not locations else " source span is ambiguous"))
        spans.append(locations[0])
        presence.append(True)
    occupied = set()
    for left, right in spans:
        if left < 0:
            continue
        positions = set(range(left, right + 1))
        _require(not occupied & positions, "unsupported_target: copied facet spans overlap")
        occupied.update(positions)
    return {"modality": MODALITIES.index(rule["modality"]), "spans": spans, "presence": presence}


def audit_examples(examples):
    """Report expressibility before training; never repair or silently omit labels."""
    _require(type(examples) in (list, tuple) and len(examples) <= MAX_EXAMPLES, "bounded example sequence required")
    accepted, rejected = [], []
    for row in examples:
        _require(type(row) is dict and {"id", "source_text", "canonical_ir"} <= set(row), "example fields missing")
        try:
            _labels(row["source_text"], row["canonical_ir"], tokenize_source(row["source_text"]))
        except ValueError as error:
            rejected.append({"id": row["id"], "reason": str(error)})
        else:
            accepted.append(row["id"])
    return {"accepted_ids": accepted, "rejected_rows": rejected, "all_supported": not rejected}


def _records(examples, dimension, *, allow_empty=False):
    _require(type(examples) in (list, tuple) and (allow_empty or len(examples))
             and len(examples) <= MAX_EXAMPLES, "one to 4096 examples required")
    fields = {"id", "source_text", "canonical_ir"} | ({"latent"} if dimension else set())
    records, identifiers, sources = [], set(), set()
    for row in examples:
        _require(type(row) is dict and set(row) == fields, "closed span training example schema required")
        identifier = row["id"]
        _require(type(identifier) is str and 0 < len(identifier.strip()) <= 512 and identifier not in identifiers,
                 "unique bounded example ID required")
        tokens = tokenize_source(row["source_text"])
        _require(row["source_text"] not in sources, "duplicate source text")
        identifiers.add(identifier)
        sources.add(row["source_text"])
        records.append({"tokens": tokens, "labels": _labels(row["source_text"], row["canonical_ir"], tokens),
                        "latent": _vector(row["latent"], dimension) if dimension else []})
    return records, identifiers, sources


def _splits(training, tuning, dimension):
    train, train_ids, train_sources = _records(training, dimension)
    tune, tune_ids, tune_sources = _records(tuning, dimension, allow_empty=True)
    _require(not train_ids & tune_ids and not train_sources & tune_sources, "training/tuning overlap")
    return train, tune


def _config(*, latent_dimension, latent_enabled, learning_rate, batch_size, seed,
            hidden_size, embedding_dim, projection_width, residual_scale):
    import torch
    for value, low, high, label in ((batch_size, 1, 32, "batch size"), (seed, 0, 2**31 - 1, "seed"),
            (hidden_size, 8, 128, "hidden size"), (embedding_dim, 4, 64, "embedding dimension"),
            (projection_width, 4, 128, "projection width")):
        _require(type(value) is int and low <= value <= high, "invalid " + label)
    _require(type(latent_dimension) is int and latent_dimension in (0, 384), "latent dimension must be 0 or 384")
    _require(type(latent_enabled) is bool, "latent_enabled must be boolean")
    _require(type(learning_rate) in (float, int) and math.isfinite(learning_rate) and 0 < learning_rate <= .1,
             "learning rate outside (0, .1]")
    _require(type(residual_scale) in (float, int) and math.isfinite(residual_scale) and 0 < residual_scale <= 1,
             "residual scale outside (0, 1]")
    return {"architecture": ARCHITECTURE, "latent_dimension": latent_dimension, "latent_enabled": latent_enabled,
            "learning_rate": float(learning_rate), "batch_size": batch_size, "seed": seed,
            "hidden_size": hidden_size, "embedding_dim": embedding_dim, "projection_width": projection_width,
            "residual_scale": float(residual_scale), "device": "cpu", "dtype": "float32",
            "torch_version": str(torch.__version__), "max_source_characters": MAX_SOURCE_CHARACTERS,
            "max_source_tokens": MAX_SOURCE_TOKENS, "max_token_bytes": MAX_TOKEN_BYTES,
            "tokenizer": "unicode_word_or_punctuation_exact_offsets/v1", "byte_alphabet": "casefold_utf8_plus1_pad0/v1",
            "initialization": "from_scratch", "loss": "equal_facet_modality_presence_mean_start_end/v1"}


def _model(torch, config):
    class SpanModel(torch.nn.Module):
        def __init__(self):
            super().__init__()
            width, hidden = config["embedding_dim"], config["hidden_size"]
            self.byte_embedding = torch.nn.Embedding(257, width, padding_idx=0)
            self.token_projection = torch.nn.Linear(width * 3 + 1, width * 2)
            self.encoder = torch.nn.GRU(width * 2, hidden, batch_first=True, bidirectional=True)
            self.modality = torch.nn.Linear(hidden * 2, 3)
            self.presence = torch.nn.Linear(hidden * 2, len(OPTIONAL_FIELDS) * 2)
            self.start = torch.nn.Linear(hidden * 2, len(SPAN_FIELDS))
            self.end = torch.nn.Linear(hidden * 2, len(SPAN_FIELDS))
            if config["latent_dimension"]:
                self.latent_down = torch.nn.Linear(config["latent_dimension"], config["projection_width"])
                self.latent_up = torch.nn.Linear(config["projection_width"], hidden * 2)
                torch.nn.init.zeros_(self.latent_up.weight)
                torch.nn.init.zeros_(self.latent_up.bias)

        def forward(self, byte_ids, byte_lengths, lengths, latent, *, enabled=True):
            embedded = self.byte_embedding(byte_ids)
            mean = embedded.sum(2) / byte_lengths.clamp(min=1)[..., None]
            first = embedded[:, :, 0, :]
            last = embedded.gather(2, (byte_lengths.clamp(min=1) - 1)[:, :, None, None].expand(
                -1, -1, 1, config["embedding_dim"])).squeeze(2)
            size = torch.log1p(byte_lengths.to(torch.float32))[..., None] / math.log1p(MAX_TOKEN_BYTES)
            token = torch.tanh(self.token_projection(torch.cat((mean, first, last, size), dim=-1)))
            packed = torch.nn.utils.rnn.pack_padded_sequence(token, lengths.cpu(), batch_first=True, enforce_sorted=False)
            encoded, _ = self.encoder(packed)
            encoded, _ = torch.nn.utils.rnn.pad_packed_sequence(encoded, batch_first=True)
            mask = torch.arange(encoded.shape[1])[None, :] < lengths[:, None]
            if config["latent_dimension"]:
                residual = torch.tanh(self.latent_up(torch.tanh(self.latent_down(latent))))
                gated = residual * config["residual_scale"] * float(enabled and config["latent_enabled"])
                # A global additive shift alone cancels in the linear pointer
                # softmax. Bounded feature scaling makes token-relative span
                # scores depend on context; tied scale/shift adds no parameters.
                encoded = encoded * (1 + gated[:, None, :]) + gated[:, None, :]
            pooled = (encoded * mask[..., None]).sum(1) / lengths[:, None]
            return {"modality": self.modality(pooled), "presence": self.presence(pooled).reshape(-1, 4, 2),
                    "start": self.start(encoded).transpose(1, 2).masked_fill(~mask[:, None, :], -1e9),
                    "end": self.end(encoded).transpose(1, 2).masked_fill(~mask[:, None, :], -1e9)}

    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(config["seed"])
        return SpanModel()


def _batch(torch, records):
    width = max(len(row["tokens"]) for row in records)
    byte_width = max(len(token["byte_ids"]) for row in records for token in row["tokens"])
    ids = torch.zeros((len(records), width, byte_width), dtype=torch.long)
    sizes = torch.zeros((len(records), width), dtype=torch.long)
    for i, row in enumerate(records):
        for j, token in enumerate(row["tokens"]):
            values = token["byte_ids"]
            ids[i, j, :len(values)] = torch.tensor(values, dtype=torch.long)
            sizes[i, j] = len(values)
    return (ids, sizes, torch.tensor([len(row["tokens"]) for row in records], dtype=torch.long),
            torch.tensor([row["latent"] for row in records], dtype=torch.float32))


def _loss(torch, model, records):
    output = model(*_batch(torch, records))
    labels = [row["labels"] for row in records]
    modality = torch.nn.functional.cross_entropy(output["modality"], torch.tensor([x["modality"] for x in labels]))
    facets = []
    for index, field in enumerate(SPAN_FIELDS):
        present = torch.tensor([x["presence"][index] for x in labels], dtype=torch.bool)
        start = torch.tensor([x["spans"][index][0] for x in labels], dtype=torch.long)
        end = torch.tensor([x["spans"][index][1] for x in labels], dtype=torch.long)
        # All absent batches still traverse both pointer heads with zero loss.
        pointer = (torch.nn.functional.cross_entropy(output["start"][:, index], start,
                    ignore_index=-100, reduction="none") +
                   torch.nn.functional.cross_entropy(output["end"][:, index], end,
                    ignore_index=-100, reduction="none")) * .5
        if field in OPTIONAL_FIELDS:
            presence = torch.nn.functional.cross_entropy(output["presence"][:, OPTIONAL_FIELDS.index(field)],
                         present.to(torch.long), reduction="none")
            facets.append((presence + pointer).mean())
        else:
            facets.append(pointer.mean())
    return (modality + sum(facets)) / 7


def _pack(model, optimizer):
    weights = {name: value.detach().tolist() for name, value in model.state_dict().items()}
    moments = {}
    for name, parameter in model.named_parameters():
        state = optimizer.state.get(parameter)
        if state:
            moments[name] = {"step": int(state["step"].item()), "exp_avg": state["exp_avg"].detach().tolist(),
                             "exp_avg_sq": state["exp_avg_sq"].detach().tolist()}
    return weights, {"schema": "adam-default-betas-eps/v1", "parameters": moments}


def _tensor(torch, value, shape, label, *, nonnegative=False):
    def check(part, dimensions):
        if dimensions:
            _require(type(part) is list and len(part) == dimensions[0], label + " tensor shape differs")
            for item in part:
                check(item, dimensions[1:])
        else:
            _require(type(part) in (float, int) and math.isfinite(part) and (not nonnegative or part >= 0),
                     label + " tensor values must be finite")
    check(value, tuple(shape))
    result = torch.tensor(value, dtype=torch.float32)
    _require(bool(torch.isfinite(result).all()), label + " overflows float32")
    return result


def build_checkpoint(training_examples, tuning_examples=(), *, latent_dimension=0, latent_enabled=True,
                     learning_rate=.003, batch_size=12, seed=1729, hidden_size=32, embedding_dim=16,
                     projection_width=16, residual_scale=.25):
    """Initialize a new architecture; no parent weights, targets, or words are stored."""
    import torch
    config = _config(latent_dimension=latent_dimension, latent_enabled=latent_enabled, learning_rate=learning_rate,
        batch_size=batch_size, seed=seed, hidden_size=hidden_size, embedding_dim=embedding_dim,
        projection_width=projection_width, residual_scale=residual_scale)
    _splits(training_examples, tuning_examples, latent_dimension)
    model = _model(torch, config)
    optimizer = torch.optim.Adam(model.parameters(), lr=config["learning_rate"], foreach=False)
    weights, moments = _pack(model, optimizer)
    return {"schema": SCHEMA, "lineage_id": LINEAGE_ID, "config": config, "implementation": _implementation(),
            "training_manifest_sha256": checkpoint_digest(training_examples), "training_count": len(training_examples),
            "tuning_manifest_sha256": checkpoint_digest(tuning_examples), "tuning_count": len(tuning_examples),
            "model_state": weights, "optimizer_state": moments,
            "progress": {"epochs_completed": 0, "row_cursor": 0, "optimizer_steps": 0},
            "parent_checkpoint_sha256": None, **FALSE}


def _restore(checkpoint):
    import torch
    fields = {"schema", "lineage_id", "config", "implementation", "training_manifest_sha256", "training_count",
              "tuning_manifest_sha256", "tuning_count", "model_state", "optimizer_state", "progress",
              "parent_checkpoint_sha256", *FALSE}
    _require(type(checkpoint) is dict and set(checkpoint) == fields, "closed span checkpoint schema required")
    _require(checkpoint["schema"] == SCHEMA and checkpoint["lineage_id"] == LINEAGE_ID and
             all(checkpoint[key] is False for key in FALSE), "span schema/authority differs")
    _require(len(_raw(checkpoint)) <= MAX_BYTES, "checkpoint exceeds byte bound")
    _require(checkpoint["implementation"] == _implementation(), "span implementation source drift")
    config = checkpoint["config"]
    keys = ("latent_dimension", "latent_enabled", "learning_rate", "batch_size", "seed", "hidden_size",
            "embedding_dim", "projection_width", "residual_scale")
    _require(type(config) is dict and all(key in config for key in keys), "incomplete span configuration")
    _require(_raw(config) == _raw(_config(**{key: config[key] for key in keys})), "span configuration/runtime differs")
    for key in ("training_manifest_sha256", "tuning_manifest_sha256"):
        _require(type(checkpoint[key]) is str and _SHA.fullmatch(checkpoint[key]), "invalid manifest hash")
    parent = checkpoint["parent_checkpoint_sha256"]
    _require(parent is None or type(parent) is str and _SHA.fullmatch(parent), "invalid parent hash")
    count = checkpoint["training_count"]
    _require(type(count) is int and 1 <= count <= MAX_EXAMPLES and type(checkpoint["tuning_count"]) is int
             and 0 <= checkpoint["tuning_count"] <= MAX_EXAMPLES, "invalid split counts")
    progress = checkpoint["progress"]
    _require(type(progress) is dict and set(progress) == {"epochs_completed", "row_cursor", "optimizer_steps"}
             and all(type(value) is int and 0 <= value <= 10**9 for value in progress.values()), "invalid progress")
    cursor, batch = progress["row_cursor"], config["batch_size"]
    _require(cursor < count and cursor % batch == 0 and progress["optimizer_steps"] ==
             progress["epochs_completed"] * math.ceil(count / batch) + cursor // batch, "step/cursor identity differs")
    model = _model(torch, config)
    template = model.state_dict()
    weights = checkpoint["model_state"]
    _require(type(weights) is dict and set(weights) == set(template), "model state keys differ")
    model.load_state_dict({key: _tensor(torch, weights[key], value.shape, key) for key, value in template.items()})
    optimizer = torch.optim.Adam(model.parameters(), lr=config["learning_rate"], foreach=False)
    state = checkpoint["optimizer_state"]
    _require(type(state) is dict and set(state) == {"schema", "parameters"} and
             state["schema"] == "adam-default-betas-eps/v1" and type(state["parameters"]) is dict,
             "unsupported optimizer state")
    parameters = dict(model.named_parameters())
    _require(set(state["parameters"]) == (set(parameters) if progress["optimizer_steps"] else set()),
             "optimizer parameter keys differ")
    for name, moment in state["parameters"].items():
        _require(type(moment) is dict and set(moment) == {"step", "exp_avg", "exp_avg_sq"} and
                 type(moment["step"]) is int and moment["step"] == progress["optimizer_steps"], "optimizer step differs")
        parameter = parameters[name]
        optimizer.state[parameter] = {"step": torch.tensor(float(moment["step"])),
            "exp_avg": _tensor(torch, moment["exp_avg"], parameter.shape, name),
            "exp_avg_sq": _tensor(torch, moment["exp_avg_sq"], parameter.shape, name, nonnegative=True)}
    model.eval()
    return torch, model, optimizer


def validate_checkpoint(checkpoint):
    _restore(checkpoint)


def train_decoder(checkpoint, training_examples, tuning_examples=(), *, max_steps=100, max_seconds=60):
    """Bounded Adam updates with deterministic shuffling and exact resumption."""
    _require(type(max_steps) is int and 0 <= max_steps <= 10000, "max_steps must be in 0..10000")
    _require(type(max_seconds) in (int, float) and math.isfinite(max_seconds) and 0 <= max_seconds <= 3600,
             "max_seconds must be in 0..3600")
    started = time.monotonic()
    deadline = started + max_seconds
    torch, model, optimizer = _restore(checkpoint)
    _require(checkpoint["training_manifest_sha256"] == checkpoint_digest(training_examples) and
             checkpoint["tuning_manifest_sha256"] == checkpoint_digest(tuning_examples), "resume manifests differ")
    records, tuning = _splits(training_examples, tuning_examples, checkpoint["config"]["latent_dimension"])
    config, progress = checkpoint["config"], dict(checkpoint["progress"])
    losses, maximum_gradient, reason = [], 0., "step_limit"
    for _ in range(max_steps):
        if time.monotonic() >= deadline:
            reason = "deadline_before_batch"
            break
        order = list(range(len(records)))
        random.Random(config["seed"] + progress["epochs_completed"]).shuffle(order)
        indices = order[progress["row_cursor"]:progress["row_cursor"] + config["batch_size"]]
        model.train()
        optimizer.zero_grad(set_to_none=True)
        loss = _loss(torch, model, [records[index] for index in indices])
        _require(bool(torch.isfinite(loss)), "nonfinite training loss")
        loss.backward()
        parameters = list(model.parameters())
        _require(all(parameter.grad is not None and bool(torch.isfinite(parameter.grad).all()) for parameter in parameters),
                 "missing or nonfinite gradients")
        maximum_gradient = max(maximum_gradient, float(torch.nn.utils.clip_grad_norm_(parameters, 5, error_if_nonfinite=True)))
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
            batch = tuning[start:start + config["batch_size"]]
            loss = _loss(torch, model, batch)
            _require(bool(torch.isfinite(loss)), "nonfinite tuning loss")
            total += float(loss) * len(batch)
            measured += len(batch)
    weights, moments = _pack(model, optimizer)
    result = {**copy.deepcopy(checkpoint), "model_state": weights, "optimizer_state": moments,
              "progress": progress, "parent_checkpoint_sha256": checkpoint_digest(checkpoint)}
    _require(_implementation() == checkpoint["implementation"], "span source changed during training")
    _require(len(_raw(result)) <= MAX_BYTES, "checkpoint exceeds byte bound")
    return {"checkpoint": result, "report": {"schema": "span-legal-formula-training/v1",
        "checkpoint_sha256": checkpoint_digest(result), "optimizer_steps": len(losses), "training_executed": bool(losses),
        "batch_losses": losses, "gradient_norm_max": maximum_gradient,
        "changed_parameter_names": [key for key in weights if weights[key] != checkpoint["model_state"][key]],
        "stopped_reason": reason, "elapsed_seconds": time.monotonic() - started,
        "deadline_scope": "soft_boundary_before_numeric_batch; initialization_and_serialization_not_interruptible",
        "tuning": {"objective_loss": total / measured if measured else None, "rows_evaluated": measured,
                   "complete": measured == len(tuning), "teacher_forcing": True, "used_for_fit_or_selection": False}, **FALSE}}


def _display(canonical_ir):
    # Display only; the typed canonical AST remains authoritative.
    return json.dumps(canonical_ir, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class SpanLegalFormulaDecoder:
    """Inference accepts source strings and optional context vectors, never targets."""
    def __init__(self, checkpoint):
        self.torch, self.model, _ = _restore(checkpoint)
        self.checkpoint = copy.deepcopy(checkpoint)
        self.checkpoint_sha256 = checkpoint_digest(checkpoint)

    def _decode(self, text, latent, *, enabled):
        base = {"source_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "latent_sha256": checkpoint_digest(latent), "status": "abstained", "canonical_ir": None,
            "formal_outputs": [], "formula_text": None, "teacher_forcing": False, "target_access": False,
            "training_executed": False, "source_input_conditioned": True, "learned_formula_generation": True,
            "sample_memory_used": False, "family_syntax_checked": False,
            "latent_input_enabled": enabled and self.checkpoint["config"]["latent_enabled"] and bool(latent), **FALSE}
        try:
            tokens = tokenize_source(text)
        except ValueError as error:
            return {**base, "reason": "source_too_long" if "source_too_long:" in str(error) else "source_encoding_rejected",
                    "detail": str(error)}
        torch = self.torch
        self.model.eval()
        with torch.no_grad():
            output = self.model(*_batch(torch, [{"tokens": tokens, "latent": latent}]), enabled=enabled)
        if not all(bool(torch.isfinite(value).all()) for value in output.values()):
            return {**base, "reason": "nonfinite_decoder_scores"}
        diagnostics = {"tokens": [{key: token[key] for key in ("text", "start", "end")} for token in tokens],
                       "facets": {}, "modality_logits": output["modality"][0].tolist()}
        rank = torch.argsort(output["modality"][0], descending=True, stable=True)
        minimum_margin = float(output["modality"][0, rank[0]] - output["modality"][0, rank[1]])
        if minimum_margin <= 1e-7:
            return {**base, "reason": "ambiguous_decoder_scores", "span_diagnostics": diagnostics}
        rule = {"modality": MODALITIES[int(rank[0])]}
        occupied = set()
        for index, field in enumerate(SPAN_FIELDS):
            present, presence_margin = True, None
            if field in OPTIONAL_FIELDS:
                scores = output["presence"][0, OPTIONAL_FIELDS.index(field)]
                presence_margin = float(abs(scores[1] - scores[0]))
                if presence_margin <= 1e-7:
                    return {**base, "reason": "ambiguous_decoder_scores", "span_diagnostics": diagnostics}
                minimum_margin = min(minimum_margin, presence_margin)
                present = bool(scores[1] > scores[0])
            diagnostic = {"present": present, "presence_logit_margin": presence_margin,
                          "token_start": None, "token_end_inclusive": None, "char_start": None, "char_end": None,
                          "text": None, "span_logit_margin": None}
            atom = ""
            if present:
                scores = output["start"][0, index, :, None] + output["end"][0, index, None, :]
                allowed = torch.triu(torch.ones_like(scores, dtype=torch.bool))
                candidates = torch.nonzero(allowed.flatten(), as_tuple=False).flatten()
                values = scores.flatten()[candidates]
                ranking = torch.argsort(values, descending=True, stable=True)
                span_margin = float(values[ranking[0]] - values[ranking[1]]) if len(values) > 1 else None
                if span_margin is not None and span_margin <= 1e-7:
                    return {**base, "reason": "ambiguous_decoder_scores", "span_diagnostics": diagnostics}
                if span_margin is not None:
                    minimum_margin = min(minimum_margin, span_margin)
                location = int(candidates[ranking[0]])
                left, right = divmod(location, len(tokens))
                begin, end = tokens[left]["start"], tokens[right]["end"]
                atom = text[begin:end]
                diagnostic.update(token_start=left, token_end_inclusive=right, char_start=begin,
                                  char_end=end, text=atom, span_logit_margin=span_margin)
                positions = set(range(left, right + 1))
                if occupied & positions:
                    diagnostics["facets"][field] = diagnostic
                    return {**base, "reason": "copied_spans_overlap", "span_diagnostics": diagnostics}
                occupied.update(positions)
            rule[field] = ([atom] if present else []) if field in codec_module.QUALIFIERS else atom
            diagnostics["facets"][field] = diagnostic
        canonical_ir = {"rules": [rule]}
        try:
            codec_module._rule(canonical_ir)
        except ValueError as error:
            return {**base, "reason": "generated_ir_rejected", "detail": str(error), "span_diagnostics": diagnostics}
        display = _display(canonical_ir)
        return {**base, "status": "decoded", "reason": None, "canonical_ir": canonical_ir,
                "formula_text": display, "minimum_decision_logit_margin": minimum_margin,
                "span_diagnostics": diagnostics, "family_syntax_checked": True,
                "syntax_scope": "single_canonical_deontic_rule_with_one_copied_span_per_facet",
                "formal_outputs": [{"family": "deontic", "format": "typed-deontic-rule/v1",
                    "payload": rule, "formula_text": display, "formula_text_role": "display_only_full_ast_is_authoritative",
                    "origin": "learned_source_span_formula_decoder", **FALSE}]}

    def decode_formal_logic(self, texts, latents=None, *, latent_ablation="none"):
        _require(type(texts) in (list, tuple) and 1 <= len(texts) <= 128 and all(type(text) is str for text in texts),
                 "one to 128 source strings required")
        dimension = self.checkpoint["config"]["latent_dimension"]
        if dimension:
            _require(type(latents) in (list, tuple) and len(latents) == len(texts), "one latent per source required")
            vectors = [_vector(vector, dimension) for vector in latents]
        else:
            _require(latents is None, "zero-dimensional decoder does not accept latent input")
            vectors = [[] for _ in texts]
        _require(latent_ablation in ("none", "zero", "rotate", "disabled"), "unsupported latent ablation")
        _require(latent_ablation != "rotate" or len(texts) > 1, "rotate requires at least two rows")
        _require(_implementation() == self.checkpoint["implementation"], "span implementation source drift")
        if latent_ablation == "zero":
            vectors = [[0.] * dimension for _ in vectors]
        elif latent_ablation == "rotate":
            vectors = vectors[1:] + vectors[:1]
        rows = [self._decode(text, vector, enabled=latent_ablation != "disabled") for text, vector in zip(texts, vectors)]
        count = sum(row["status"] == "decoded" for row in rows)
        return {"schema": "span-legal-formula-inference/v1", "lineage_id": LINEAGE_ID,
                "checkpoint_sha256": self.checkpoint_sha256, "rows": rows, "decoded_count": count,
                "status": "decoded" if count == len(rows) else "partial" if count else "abstained",
                "latent_ablation": latent_ablation, "target_access": False, "teacher_forcing": False,
                "training_executed": False, **FALSE}


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
        raise ValueError("invalid JSON constant: " + value)
    checkpoint = json.loads(raw, object_pairs_hook=unique, parse_constant=reject)
    validate_checkpoint(checkpoint)
    return checkpoint
