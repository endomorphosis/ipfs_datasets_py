"""Opt-in learned source anchors beside a frozen typed formula decoder.

Teacher proposals supervise only a small span head on the source parent's exact
training cohort. Inference first generates a canonical rule from source alone,
then queries frozen typed-atom embeddings for its complete source anchors.
No source grammar or symbol-to-surface dictionary resolves generated symbols.
These proposals remain unaccepted and do not establish source meaning.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import random
import re
import stat
import time
from pathlib import Path

from . import canonical_byte_codec as byte_codec
from . import canonical_decoder_preflight as preflight_module
from . import canonical_source_guards as source_guards

SCHEMA = "canonical-typed-anchor-checkpoint/v1"
LINEAGE_ID = "frozen-typed-parent-learned-source-anchors/v1"
ARCHITECTURE = "frozen-source-gru-typed-query-bilinear-span/v1"
INFERENCE_SCHEMA = "canonical-typed-anchor-inference/v1"
MAX_BYTES = 8 * 1024 * 1024
MAX_EXAMPLES = 256
MAX_BATCH = 16
_SOURCE_RE = re.compile(r"\w+|[^\w\s]", re.UNICODE)
_FALSE = {field: False for field in (
    "qualified", "proof_authority", "source_fidelity_established", "accepted")}
_REQUEST_FIELDS = {"id", "source_text", "context_text", "requires_context_resolution"}
_CHECKPOINT_FIELDS = {"schema", "lineage_id", "source_checkpoint_sha256", "source_implementation",
                      "implementation", "config", "training_manifest_sha256", "training_pair_count",
                      "training_anchor_count", "model_state", "optimizer_state", "progress",
                      "parent_anchor_checkpoint_sha256", *_FALSE}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _raw(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError, OverflowError) as error:
        raise ValueError("strict finite checkpoint JSON required") from error


def _digest(value):
    return hashlib.sha256(_raw(value)).hexdigest()


def checkpoint_digest(checkpoint):
    """Content identity only; validation is separate."""
    return _digest(checkpoint)


def _hash(value, field):
    _require(type(value) is str and len(value) == 64
             and all(character in "0123456789abcdef" for character in value),
             field + " must be lowercase SHA256")


def _native():
    from ...optimizers.logic_theorem_optimizer import legal_formula_learning
    return legal_formula_learning


def _implementation():
    return {"scope": "listed_files_only", "files": {
        "canonical_typed_anchors.py": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "canonical_byte_codec.py": hashlib.sha256(Path(byte_codec.__file__).read_bytes()).hexdigest(),
        "canonical_decoder_preflight.py": hashlib.sha256(Path(preflight_module.__file__).read_bytes()).hexdigest(),
        "canonical_source_guards.py": hashlib.sha256(Path(source_guards.__file__).read_bytes()).hexdigest(),
    }}


def tokenize_source(source_text):
    """Return exact original character spans aligned to the parent's token IDs."""
    _require(type(source_text) is str and bool(source_text.strip()) and len(source_text) <= 16_384,
             "nonblank source must contain at most 16384 characters")
    try:
        source_text.encode("utf-8")
    except UnicodeEncodeError as error:
        raise ValueError("source must be valid UTF8") from error
    tokens = [{"text": match.group(), "start": match.start(), "end": match.end(),
               "normalized": match.group().casefold()} for match in _SOURCE_RE.finditer(source_text)]
    _require(1 <= len(tokens) <= 64, "source exceeds the exact 64-token parent profile; no truncation performed")
    _require(all(len(token["normalized"]) <= 512 for token in tokens), "source lexeme exceeds 512 characters")
    _require([token["normalized"] for token in tokens] == _SOURCE_RE.findall(source_text.casefold()),
             "Unicode casefold changes source token segmentation; anchor alignment unavailable")
    return tokens


def _config(torch, source_checkpoint, *, learning_rate, batch_size, seed):
    _require(type(learning_rate) in (float, int) and math.isfinite(learning_rate)
             and 0 < learning_rate <= .1, "learning_rate must be finite in (0,0.1]")
    _require(type(batch_size) is int and 1 <= batch_size <= MAX_BATCH, "batch_size must be in 1..16")
    _require(type(seed) is int and 0 <= seed < 2**31, "bounded integer seed required")
    return {"architecture": ARCHITECTURE, "torch_version": str(torch.__version__),
            "device": "cpu", "dtype": "float32", "learning_rate": float(learning_rate),
            "batch_size": batch_size, "seed": seed,
            "source_hidden_size": source_checkpoint["config"]["hidden_size"],
            "query_embedding_dim": source_checkpoint["config"]["embedding_dim"],
            "max_source_tokens": 64, "margin_threshold": 1e-7,
            "source_parent_frozen": True, "latent_inputs": False}


def _model(torch, config):
    class SpanHead(torch.nn.Module):
        def __init__(self):
            super().__init__()
            width, hidden = config["query_embedding_dim"], config["source_hidden_size"]
            self.start_query = torch.nn.Linear(width, hidden)
            self.end_query = torch.nn.Linear(width, hidden)
            self.start_source = torch.nn.Linear(hidden, 1)
            self.end_source = torch.nn.Linear(hidden, 1)

        def forward(self, encoded, queries):
            scale = math.sqrt(config["source_hidden_size"])
            start = self.start_query(queries) @ encoded.transpose(0, 1) / scale
            end = self.end_query(queries) @ encoded.transpose(0, 1) / scale
            return (start + self.start_source(encoded).transpose(0, 1),
                    end + self.end_source(encoded).transpose(0, 1))

    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(config["seed"])
        return SpanHead()


def _state(model):
    return {name: value.detach().tolist() for name, value in model.state_dict().items()}


def _pack(model, optimizer):
    states = {}
    for name, parameter in model.named_parameters():
        state = optimizer.state.get(parameter)
        if state:
            states[name] = {"step": int(state["step"].item()),
                           "exp_avg": state["exp_avg"].detach().tolist(),
                           "exp_avg_sq": state["exp_avg_sq"].detach().tolist()}
    return _state(model), {"schema": "adam-default-betas-eps/v1", "parameters": states}


def _source_parent(source_checkpoint):
    parent = _native().LearnedLegalFormulaDecoder(source_checkpoint)
    for parameter in parent.model.parameters():
        parameter.requires_grad_(False)
    parent.model.eval()
    return parent


def _restore(source_checkpoint, checkpoint):
    parent = _source_parent(source_checkpoint)
    torch = parent.torch
    _require(type(checkpoint) is dict and set(checkpoint) == _CHECKPOINT_FIELDS,
             "closed anchor checkpoint schema required")
    _require(checkpoint["schema"] == SCHEMA and checkpoint["lineage_id"] == LINEAGE_ID
             and all(checkpoint[field] is False for field in _FALSE), "anchor lineage or authority differs")
    _require(len(_raw(checkpoint)) <= MAX_BYTES, "anchor checkpoint exceeds byte bound")
    _require(checkpoint["source_checkpoint_sha256"] == parent.checkpoint_sha256,
             "anchor source parent checkpoint differs")
    _require(checkpoint["source_implementation"] == source_checkpoint["implementation"],
             "anchor source implementation binding differs")
    _require(checkpoint["implementation"] == _implementation(), "anchor implementation source drift")
    config = checkpoint["config"]
    _require(type(config) is dict and all(key in config for key in ("learning_rate", "batch_size", "seed")),
             "complete anchor configuration required")
    expected = _config(torch, source_checkpoint, **{key: config[key] for key in ("learning_rate", "batch_size", "seed")})
    _require(_raw(config) == _raw(expected), "unsupported anchor configuration or runtime")
    _hash(checkpoint["training_manifest_sha256"], "training_manifest_sha256")
    count, anchor_count = checkpoint["training_pair_count"], checkpoint["training_anchor_count"]
    _require(type(count) is int and 1 <= count <= MAX_EXAMPLES
             and count == source_checkpoint["training_pair_count"], "anchor training pair count differs from source parent")
    _require(type(anchor_count) is int and 3 * count <= anchor_count <= 16 * count,
             "invalid complete anchor supervision count")
    ancestor = checkpoint["parent_anchor_checkpoint_sha256"]
    _require(ancestor is None or type(ancestor) is str, "invalid anchor ancestor identity")
    if ancestor is not None:
        _hash(ancestor, "parent_anchor_checkpoint_sha256")
    progress = checkpoint["progress"]
    _require(type(progress) is dict and set(progress) == {"epochs_completed", "row_cursor", "optimizer_steps"}
             and all(type(value) is int and 0 <= value <= 10**9 for value in progress.values()),
             "closed bounded anchor progress required")
    cursor, batch = progress["row_cursor"], config["batch_size"]
    _require(cursor < count and cursor % batch == 0, "invalid anchor row cursor")
    _require(progress["optimizer_steps"] == progress["epochs_completed"] * math.ceil(count / batch) + cursor // batch,
             "anchor optimizer progress identity differs")
    model = _model(torch, config)
    weights = checkpoint["model_state"]
    _require(type(weights) is dict and set(weights) == set(model.state_dict()), "anchor tensor keys differ")
    model.load_state_dict({name: _native()._tensor(torch, weights[name], tensor.shape, name)
                           for name, tensor in model.state_dict().items()})
    model.eval()
    optim = checkpoint["optimizer_state"]
    _require(type(optim) is dict and set(optim) == {"schema", "parameters"}
             and optim["schema"] == "adam-default-betas-eps/v1" and type(optim["parameters"]) is dict,
             "closed supported anchor Adam state required")
    parameters = dict(model.named_parameters())
    _require(set(optim["parameters"]) == (set(parameters) if progress["optimizer_steps"] else set()),
             "anchor optimizer parameter set differs")
    optimizer = torch.optim.Adam(model.parameters(), lr=config["learning_rate"], foreach=False)
    for name, state in optim["parameters"].items():
        _require(type(state) is dict and set(state) == {"step", "exp_avg", "exp_avg_sq"}
                 and type(state["step"]) is int and state["step"] == progress["optimizer_steps"],
                 "anchor Adam step differs")
        parameter = parameters[name]
        optimizer.state[parameter] = {"step": torch.tensor(float(state["step"]), dtype=torch.float32),
            "exp_avg": _native()._tensor(torch, state["exp_avg"], parameter.shape, name + ".exp_avg"),
            "exp_avg_sq": _native()._tensor(torch, state["exp_avg_sq"], parameter.shape, name + ".exp_avg_sq", nonnegative=True)}
    return parent, model, optimizer


def validate_checkpoint(source_checkpoint, anchor_checkpoint):
    """Restore closed source-bound tensors and Adam state without a fit step."""
    _restore(source_checkpoint, anchor_checkpoint)


def _leaf_queries(codec, canonical_ir):
    ir = byte_codec._canonical_ir(canonical_ir)
    vocabulary = {token: index for index, token in enumerate(codec["target_vocabulary"])}
    result = []
    for path, (facet, symbol) in byte_codec._leaves(ir).items():
        atom = json.dumps(["atom", facet, symbol], ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), allow_nan=False)
        _require(atom in vocabulary, "generated typed atom has no frozen query embedding")
        result.append({"field_path": path, "facet": facet, "canonical_symbol": symbol,
                       "query_token_id": vocabulary[atom]})
    return result


def _features(parent, source_text, canonical_ir):
    tokens = tokenize_source(source_text)
    source_ids = _native().codec_module.encode_source(parent.codec, source_text)
    _require(len(source_ids) == len(tokens), "source encoding and original offsets differ")
    queries = _leaf_queries(parent.codec, canonical_ir)
    torch = parent.torch
    parent.model.eval()
    with torch.no_grad():
        encoded, _ = parent.model.encode(torch.tensor([source_ids], dtype=torch.long),
                                        torch.tensor([len(source_ids)]))
        query_vectors = parent.model.target_embedding(torch.tensor([query["query_token_id"] for query in queries]))
    return tokens, encoded[0].detach(), queries, query_vectors.detach()


def _examples(parent, training_examples):
    _require(type(training_examples) in (list, tuple) and 1 <= len(training_examples) <= MAX_EXAMPLES,
             "bounded nonempty anchor TRAIN examples required")
    ids, sources, rows = set(), set(), []
    for row in training_examples:
        _require(type(row) is dict and set(row) == {"id", "source_text", "proposal"},
                 "closed anchor training example schema required")
        identity = row["id"]
        _require(type(identity) is str and bool(identity.strip()) and len(identity) <= 512 and identity not in ids,
                 "unique bounded TRAIN id required")
        _raw(identity)
        proposal = byte_codec.validate_proposal(row["proposal"], row["source_text"])
        _require(row["source_text"] not in sources, "duplicate anchor training source")
        preflight = preflight_module.analyze_decoder_source(row["source_text"])
        _require(preflight["outcome"] == "unassessed", "anchor supervision source is outside unassessed parent profile")
        ids.add(identity)
        sources.add(row["source_text"])
        rows.append({"id": identity, "source_text": row["source_text"], "proposal": proposal})
    typed = [{"id": row["id"], "source_text": row["source_text"],
              "canonical_ir": row["proposal"]["canonical_ir"]} for row in rows]
    _require(_native()._digest(typed) == parent.checkpoint["training_manifest_sha256"]
             and len(rows) == parent.checkpoint["training_pair_count"],
             "anchor TRAIN examples differ from exact source-parent training manifest")
    records = []
    for row in rows:
        _native().codec_module.encode_target(parent.codec, row["proposal"]["canonical_ir"])
        tokens, encoded, queries, vectors = _features(parent, row["source_text"], row["proposal"]["canonical_ir"])
        starts, ends = {token["start"]: index for index, token in enumerate(tokens)}, {token["end"]: index for index, token in enumerate(tokens)}
        labels = []
        for anchor, query in zip(row["proposal"]["anchors"], queries, strict=True):
            _require(anchor["field_path"] == query["field_path"] and anchor["start"] in starts and anchor["end"] in ends,
                     "TRAIN anchor must align exactly to original source token boundaries")
            labels.append((starts[anchor["start"]], ends[anchor["end"]]))
        records.append((encoded, vectors, labels))
    return rows, records


def _loss(torch, model, records):
    losses, count = [], 0
    for encoded, queries, labels in records:
        start, end = model(encoded, queries)
        _require(bool(torch.isfinite(start).all()) and bool(torch.isfinite(end).all()), "nonfinite anchor logits")
        target = torch.tensor(labels, dtype=torch.long)
        losses.append(torch.nn.functional.cross_entropy(start, target[:, 0], reduction="sum")
                      + torch.nn.functional.cross_entropy(end, target[:, 1], reduction="sum"))
        count += len(labels)
    return sum(losses) / (2 * count), count


def _metrics(torch, model, records, batch_size, deadline):
    total, anchors, rows = 0., 0, 0
    model.eval()
    with torch.no_grad():
        for index in range(0, len(records), batch_size):
            if time.monotonic() >= deadline:
                break
            batch = records[index:index + batch_size]
            loss, count = _loss(torch, model, batch)
            _require(bool(torch.isfinite(loss)), "nonfinite anchor metric")
            total += float(loss) * count
            anchors += count
            rows += len(batch)
    return {"start_end_cross_entropy": total / anchors if anchors else None,
            "rows_evaluated": rows, "anchors_evaluated": anchors,
            "complete": rows == len(records), "teacher_forcing": True}


def train_anchor_decoder(source_checkpoint, training_examples, *, epochs=20, max_seconds=60,
                         learning_rate=.008, batch_size=8, seed=1729, checkpoint=None):
    """Fit only the anchor head on the exact frozen source-parent TRAIN cohort.

    A zero-second budget creates a reproducible zero-step head. Preparation and
    an in-flight completed optimizer batch are outside the soft deadline. Resume
    requires identical parent, manifest and configuration; no query labels enter.
    """
    started = time.monotonic()
    _require(type(epochs) is int and 1 <= epochs <= 1000, "epochs must be in 1..1000")
    _require(type(max_seconds) in (int, float) and math.isfinite(max_seconds)
             and 0 <= max_seconds <= 3600, "bounded nonnegative max_seconds required")
    deadline = started + max_seconds
    provenance = _implementation()
    if checkpoint is None:
        parent = _source_parent(source_checkpoint)
        config = _config(parent.torch, source_checkpoint, learning_rate=learning_rate, batch_size=batch_size, seed=seed)
        model = _model(parent.torch, config)
        optimizer = parent.torch.optim.Adam(model.parameters(), lr=learning_rate, foreach=False)
        progress = {"epochs_completed": 0, "row_cursor": 0, "optimizer_steps": 0}
    else:
        parent, model, optimizer = _restore(source_checkpoint, checkpoint)
        config = _config(parent.torch, source_checkpoint, learning_rate=learning_rate, batch_size=batch_size, seed=seed)
        _require(config == checkpoint["config"], "resume anchor configuration differs")
        progress = dict(checkpoint["progress"])
    torch = parent.torch
    parent_before = _digest(_state(parent.model))
    rows, records = _examples(parent, training_examples)
    manifest = _digest(rows)
    anchor_count = sum(len(record[2]) for record in records)
    if checkpoint is not None:
        _require(checkpoint["training_manifest_sha256"] == manifest
                 and checkpoint["training_anchor_count"] == anchor_count, "resume anchor TRAIN manifest differs")
    initial_weights, _ = _pack(model, optimizer)
    start_steps, start_epochs = progress["optimizer_steps"], progress["epochs_completed"]
    before = _metrics(torch, model, records, batch_size, deadline)
    history, gradient_norm_max = [], 0.
    stopped = "epoch_limit"
    while progress["epochs_completed"] < start_epochs + epochs:
        if time.monotonic() >= deadline:
            stopped = "deadline_before_batch"
            break
        epoch = progress["epochs_completed"]
        order = list(range(len(records)))
        random.Random(seed + epoch).shuffle(order)
        indices = order[progress["row_cursor"]:progress["row_cursor"] + batch_size]
        model.train()
        optimizer.zero_grad(set_to_none=True)
        loss, count = _loss(torch, model, [records[index] for index in indices])
        _require(bool(torch.isfinite(loss)), "nonfinite anchor training loss")
        loss.backward()
        parameters = list(model.parameters())
        _require(all(parameter.grad is not None and bool(torch.isfinite(parameter.grad).all()) for parameter in parameters),
                 "missing or nonfinite anchor gradients")
        norm = float(torch.nn.utils.clip_grad_norm_(parameters, 5., error_if_nonfinite=True))
        optimizer.step()
        _require(all(bool(torch.isfinite(parameter).all()) for parameter in parameters), "nonfinite updated anchor parameters")
        _require(all(bool(torch.isfinite(value).all()) for state in optimizer.state.values()
                     for value in state.values() if torch.is_tensor(value)), "nonfinite anchor Adam moments")
        _require(all(parameter.grad is None and not parameter.requires_grad for parameter in parent.model.parameters()),
                 "frozen parent accumulated gradients")
        progress["optimizer_steps"] += 1
        progress["row_cursor"] += len(indices)
        if progress["row_cursor"] == len(records):
            progress["epochs_completed"] += 1
            progress["row_cursor"] = 0
        history.append({"step": progress["optimizer_steps"], "epoch": epoch,
                        "start_end_cross_entropy": float(loss.detach()), "anchor_count": count})
        gradient_norm_max = max(gradient_norm_max, norm)
    after = _metrics(torch, model, records, batch_size, deadline)
    weights, optim = _pack(model, optimizer)
    parent_after = _digest(_state(parent.model))
    _require(parent_before == parent_after, "frozen source parent state changed during anchor fit")
    _require(provenance == _implementation(), "anchor source changed during fit")
    result = {"schema": SCHEMA, "lineage_id": LINEAGE_ID,
              "source_checkpoint_sha256": parent.checkpoint_sha256,
              "source_implementation": copy.deepcopy(source_checkpoint["implementation"]),
              "implementation": provenance, "config": config, "training_manifest_sha256": manifest,
              "training_pair_count": len(rows), "training_anchor_count": anchor_count,
              "model_state": weights, "optimizer_state": optim, "progress": progress,
              "parent_anchor_checkpoint_sha256": None if checkpoint is None else checkpoint_digest(checkpoint), **_FALSE}
    _require(len(_raw(result)) <= MAX_BYTES, "anchor checkpoint exceeds byte bound")
    report = {"schema": "canonical-typed-anchor-training/v1", "lineage_id": LINEAGE_ID,
              "source_checkpoint_sha256": parent.checkpoint_sha256,
              "checkpoint_sha256": checkpoint_digest(result), "training_manifest_sha256": manifest,
              "training_pair_count": len(rows), "training_anchor_count": anchor_count,
              "epochs_requested": epochs, "epochs_completed": progress["epochs_completed"] - start_epochs,
              "optimizer_steps": progress["optimizer_steps"] - start_steps, "progress": dict(progress),
              "stopped_reason": stopped, "elapsed_seconds": time.monotonic() - started,
              "deadline_scope": "soft_deadline_before_numeric_batch; preparation_and_serialization_not_interruptible",
              "training_before": before, "training_after": after, "batch_losses": history,
              "gradient_norm_max": gradient_norm_max,
              "initial_model_state_sha256": _digest(initial_weights), "final_model_state_sha256": _digest(weights),
              "source_parent_before_sha256": parent_before, "source_parent_after_sha256": parent_after,
              "frozen_feature_source_forwards": len(records), "source_parent_training_executed": False,
              "training_executed": progress["optimizer_steps"] > start_steps,
              "objective": "teacher_forced_exact_anchor_start_end_cross_entropy",
              "supervision_scope": "same_source_parent_TRAIN_cohort_only",
              "examples_persisted": False, "query_targets_accessed": False, "latent_inputs": False,
              "download_calls": 0, "provider_calls": 0, **_FALSE}
    return {"checkpoint": result, "report": report}


def _score_rows(value, leaves, tokens, field):
    if hasattr(value, "detach"):
        value = value.detach().tolist()
    _require(type(value) is list and len(value) == leaves, field + " leaf count differs")
    _require(all(type(row) is list and len(row) == tokens for row in value), field + " token count differs")
    _require(all(type(score) in (int, float) and math.isfinite(score) and abs(score) <= 3.4028234e38
                 for row in value for score in row), "nonfinite anchor scores")
    return value


def _predict_spans(start, end, tokens, leaf_queries, *, source_text):
    """Select all complete nonempty spans, rejecting score ties and overlaps."""
    _require(type(tokens) is list and 1 <= len(tokens) <= 64
             and type(leaf_queries) is list and 1 <= len(leaf_queries) <= 16, "bounded complete anchor inputs required")
    _require(tokens == tokenize_source(source_text), "anchor tokens differ from exact source character spans")
    paths = []
    for query in leaf_queries:
        _require(type(query) is dict and set(query) == {"field_path", "facet", "canonical_symbol", "query_token_id"},
                 "closed typed leaf query required")
        _require(type(query["field_path"]) is str and 0 < len(query["field_path"]) <= 128
                 and type(query["facet"]) is str
                 and query["facet"] in ("actor", "action", "modality", "object", "conditions", "exceptions", "temporal")
                 and query["field_path"].startswith("/rules/0/" + query["facet"]), "typed query field path differs")
        _require(type(query["canonical_symbol"]) is str and 0 < len(query["canonical_symbol"]) <= 512
                 and bool(query["canonical_symbol"].strip())
                 and type(query["query_token_id"]) is int and 3 <= query["query_token_id"] <= 65_535,
                 "bounded typed query symbol and token ID required")
        paths.append(query["field_path"])
    _require(paths == sorted(set(paths)), "typed leaf queries must be complete ordered unique paths")
    starts = _score_rows(start, len(leaf_queries), len(tokens), "start")
    ends = _score_rows(end, len(leaf_queries), len(tokens), "end")
    anchors, diagnostics = [], []
    for query, left_scores, right_scores in zip(leaf_queries, starts, ends, strict=True):
        best, runner_up = None, None
        for left in range(len(tokens)):
            for right in range(left, len(tokens)):
                candidate = (left_scores[left] + right_scores[right], left, right)
                _require(math.isfinite(candidate[0]) and abs(candidate[0]) <= 3.4028234e38,
                         "nonfinite or float32-overflowing joint anchor score")
                if best is None or candidate[0] > best[0]:
                    runner_up, best = best, candidate
                elif runner_up is None or candidate[0] > runner_up[0]:
                    runner_up = candidate
        margin = None if runner_up is None else best[0] - runner_up[0]
        _require(margin is None or margin > 1e-7, "ambiguous_anchor_scores")
        left, right = best[1:]
        begin, finish = tokens[left]["start"], tokens[right]["end"]
        anchors.append({"field_path": query["field_path"], "facet": query["facet"],
                        "canonical_symbol": query["canonical_symbol"], "start": begin, "end": finish,
                        "source_text": source_text[begin:finish], "offset_unit": "unicode_character_half_open"})
        diagnostics.append({"field_path": query["field_path"], "query_token_id": query["query_token_id"],
                            "token_start": left, "token_end_inclusive": right,
                            "char_start": begin, "char_end": finish,
                            "best_joint_score": best[0], "best_runner_up_margin": margin})
    ordered = sorted(anchors, key=lambda anchor: anchor["start"])
    _require(all(left["end"] <= right["start"] for left, right in zip(ordered, ordered[1:], strict=False)),
             "predicted_source_spans_overlap")
    return {"anchors": anchors, "diagnostics": diagnostics}


def _validate_parent_batch(parent, backend, sources):
    """Check unchanged native receipts, without authenticating their predictions."""
    native = _native()
    fields = {"schema", "lineage_id", "checkpoint_sha256", "rows", "trained_checkpoint",
              "checkpoint_optimizer_steps", "status", "decoded_formulas_generated", "decoded_count",
              "training_executed", "source_input_conditioned", "independent_text_to_logic",
              "learned_formula_generation", "teacher_forcing", "target_access", *native.FALSE}
    _require(type(backend) is dict and set(backend) == fields, "closed source parent batch receipt required")
    _require(backend["schema"] == "learned-legal-formula-inference/v1"
             and backend["lineage_id"] == native.LINEAGE_ID
             and backend["checkpoint_sha256"] == parent.checkpoint_sha256,
             "source parent batch identity differs")
    _require(all(backend[field] is False for field in (*native.FALSE, "target_access", "teacher_forcing", "training_executed"))
             and all(backend[field] is True for field in ("source_input_conditioned", "independent_text_to_logic", "learned_formula_generation")),
             "source parent batch authority or conditioning differs")
    steps = parent.checkpoint["progress"]["optimizer_steps"]
    _require(type(backend["checkpoint_optimizer_steps"]) is int and backend["checkpoint_optimizer_steps"] == steps
             and backend["trained_checkpoint"] is (steps > 0), "source parent training-state metadata differs")
    _require(type(backend["rows"]) is list and len(backend["rows"]) == len(sources), "source parent row count differs")
    base = {"source_sha256", "status", "canonical_ir", "formula_text", "formal_outputs",
            "teacher_forcing", "target_access", "training_executed", "source_input_conditioned",
            "independent_text_to_logic", "learned_formula_generation", "sample_memory_used",
            "family_syntax_checked", "temperature", *native.FALSE}
    reasons = {"source_encoding_rejected": {"detail"}, "zero_output_head": set(),
               "no_allowed_grammar_token": {"generated_token_ids"}, "nonfinite_decoder_scores": set(),
               "ambiguous_decoder_scores": {"generated_token_ids"},
               "generated_ir_rejected": {"detail", "generated_token_ids"},
               "generation_length_limit": {"generated_token_ids"}}
    for row, source in zip(backend["rows"], sources, strict=True):
        _require(type(row) is dict and row.get("status") in ("decoded", "abstained"), "source parent row status differs")
        decoded = row["status"] == "decoded"
        reason = row.get("reason")
        if decoded:
            extra = {"reason", "generated_token_ids", "minimum_decision_logit_margin", "syntax_scope"}
            _require(reason is None, "decoded source parent reason must be null")
        else:
            _require(type(reason) is str and reason in reasons, "source parent abstention reason differs")
            extra = {"reason", *reasons[reason]}
        _require(set(row) == base | extra, "closed source parent row receipt required")
        _require(row["source_sha256"] == hashlib.sha256(source.encode("utf-8")).hexdigest(), "source parent row source join differs")
        _require(all(row[field] is False for field in (*native.FALSE, "target_access", "teacher_forcing", "training_executed", "sample_memory_used"))
                 and all(row[field] is True for field in ("source_input_conditioned", "independent_text_to_logic", "learned_formula_generation"))
                 and row["family_syntax_checked"] is False and type(row["temperature"]) is int and row["temperature"] == 0,
                 "source parent row authority or conditioning differs")
        if "generated_token_ids" in row:
            token_ids = row["generated_token_ids"]
            _require(type(token_ids) is list and 1 <= len(token_ids) <= 64 and token_ids[0] == 1
                     and all(type(token) is int and 0 <= token < len(parent.codec["target_vocabulary"]) for token in token_ids),
                     "source parent generated token IDs differ")
        if "detail" in row:
            _require(type(row["detail"]) is str and len(row["detail"]) <= 8192, "bounded source parent error detail required")
        if decoded:
            ir = byte_codec._canonical_ir(row["canonical_ir"])
            _require(native.codec_module.decode_target(parent.codec, row["generated_token_ids"]) == ir,
                     "source parent generated token/IR join differs")
            display = native._display(ir)
            _require(row["formula_text"] == display and row["syntax_scope"] == "canonical_rule_schema_and_decoder_grammar",
                     "source parent display or syntax scope differs")
            margin = row["minimum_decision_logit_margin"]
            _require(margin is None or type(margin) in (int, float) and math.isfinite(margin) and margin > 1e-7,
                     "source parent decoded decision margin differs")
            output = {"family": "deontic", "format": "typed-deontic-rule/v1", "payload": ir["rules"][0],
                      "formula_text": display, "formula_text_role": "display_only_full_ast_is_authoritative",
                      "syntax_scope": "canonical_rule_schema_and_decoder_grammar",
                      "origin": "learned_source_conditioned_formula_decoder", **native.FALSE}
            _require(_raw(row["formal_outputs"]) == _raw([output]), "source parent formal output differs")
        else:
            _require(row["canonical_ir"] is None and row["formula_text"] is None
                     and type(row["formal_outputs"]) is list and row["formal_outputs"] == [],
                     "abstained source parent cannot supply a candidate")
    count = sum(row["status"] == "decoded" for row in backend["rows"])
    status = "decoded" if count == len(sources) else "partial" if count else "abstained"
    _require(type(backend["decoded_count"]) is int and backend["decoded_count"] == count
             and backend["decoded_formulas_generated"] is (count > 0) and backend["status"] == status,
             "source parent decoded-count/status identity differs")


class TypedAnchorDecoder:
    """Worker-private source-only free generation followed by learned anchors."""
    def __init__(self, source_checkpoint, anchor_checkpoint):
        self.parent, self.model, _ = _restore(source_checkpoint, anchor_checkpoint)
        self.checkpoint = copy.deepcopy(anchor_checkpoint)
        self.source_checkpoint_sha256 = self.parent.checkpoint_sha256
        self.anchor_checkpoint_sha256 = checkpoint_digest(self.checkpoint)
        self._parent_state_sha256 = _digest(_state(self.parent.model))
        self._head_state_sha256 = _digest(_state(self.model))
        self.model.eval()

    def _assert_state(self):
        _require(self.checkpoint["implementation"] == _implementation(), "anchor implementation source drift")
        _require(self.anchor_checkpoint_sha256 == checkpoint_digest(self.checkpoint), "anchor checkpoint metadata changed")
        _require(self.source_checkpoint_sha256 == _native().checkpoint_digest(self.parent.checkpoint),
                 "source parent checkpoint metadata changed")
        _require(self._parent_state_sha256 == _digest(_state(self.parent.model)), "source parent numerical state changed")
        _require(self._head_state_sha256 == _digest(_state(self.model)), "anchor head numerical state changed")
        _require(all(parameter.grad is None and not parameter.requires_grad for parameter in self.parent.model.parameters()),
                 "source parent is not frozen")

    def _source_decode(self, texts):
        return self.parent.decode_formal_logic(texts)

    def _anchor_generated(self, source_text, canonical_ir):
        tokens, encoded, queries, vectors = _features(self.parent, source_text, canonical_ir)
        self.model.eval()
        with self.parent.torch.no_grad():
            start, end = self.model(encoded, vectors)
        result = _predict_spans(start, end, tokens, queries, source_text=source_text)
        proposal = {"schema": byte_codec.PROPOSAL_SCHEMA,
                    "source_sha256": hashlib.sha256(source_text.encode("utf-8")).hexdigest(),
                    "canonical_ir": canonical_ir, "anchors": result["anchors"],
                    "facet_operators": {"conditions": "all", "exceptions": "any", "temporal": "all"},
                    "single_rule_scope": True, **{field: False for field in (
                        "target_access", "model_executed", "source_fidelity_established", "qualified", "proof_authority", "accepted")}}
        return {"proposal": byte_codec.validate_proposal(proposal, source_text),
                "diagnostics": result["diagnostics"], "source_tokens": tokens}

    def decode_proposals(self, requests):
        """Use closed source/context requests; no vocabulary or target argument."""
        _require(type(requests) in (list, tuple) and 1 <= len(requests) <= 128, "one to 128 source requests required")
        requests = copy.deepcopy(requests)
        seen, rows, positions = set(), [], []
        for position, request in enumerate(requests):
            _require(type(request) is dict and set(request) == _REQUEST_FIELDS, "closed source-only anchor request required")
            identity = request["id"]
            _require(type(identity) is str and bool(identity.strip()) and len(identity) <= 256 and identity not in seen,
                     "unique bounded request ID required")
            _raw(identity)
            seen.add(identity)
            preflight = preflight_module.analyze_decoder_source(request["source_text"], context_text=request["context_text"],
                requires_context_resolution=request["requires_context_resolution"])
            outcome = "clarification_required" if preflight["outcome"] == "clarification_required" else "source_blocked"
            encoding = {"outcome": "not_assessed", "token_count": None, "reason": None}
            reason = None
            if preflight["outcome"] == "unassessed":
                try:
                    tokens = tokenize_source(request["source_text"])
                    _native().codec_module.encode_source(self.parent.codec, request["source_text"])
                except ValueError as error:
                    outcome, reason = "source_encoding_unavailable", str(error)
                    encoding.update(outcome="unavailable", reason=reason)
                else:
                    outcome = "parent_unavailable"
                    encoding.update(outcome="encoded", token_count=len(tokens))
                    positions.append(position)
            rows.append({"id": identity, "position": position, "source_sha256": preflight["source_sha256"],
                         "context_sha256": preflight["context"]["sha256"], "preflight": preflight,
                         "source_encoding": encoding, "outcome": outcome, "reason": reason,
                         "parent_row": None, "anchor_diagnostics": None, "proposal": None,
                         "parent_inference_attempted": False, "anchor_inference_attempted": False,
                         "proposal_flag_scope": "transport_validation_only_not_generation_provenance"})
        self._assert_state()
        backend, exception_type, completion = None, None, 0
        if positions:
            for position in positions:
                rows[position]["parent_inference_attempted"] = True
            try:
                backend = self._source_decode([requests[position]["source_text"] for position in positions])
            except (ImportError, OSError, RuntimeError) as error:
                exception_type = ("ImportError" if isinstance(error, ImportError) else
                                  "OSError" if isinstance(error, OSError) else "RuntimeError")
                for position in positions:
                    rows[position]["reason"] = "source_parent_unavailable"
            else:
                _validate_parent_batch(self.parent, backend, [requests[position]["source_text"] for position in positions])
                completion = 1
                for position, native_row in zip(positions, backend["rows"], strict=True):
                    row, source = rows[position], requests[position]["source_text"]
                    row["parent_row"] = copy.deepcopy(native_row)
                    if native_row["status"] == "abstained":
                        _require(native_row.get("canonical_ir") is None, "abstained parent cannot supply canonical IR")
                        row.update(outcome="parent_abstained", reason=native_row.get("reason"))
                        continue
                    ir = byte_codec._canonical_ir(native_row.get("canonical_ir"))
                    _require(_native().codec_module.decode_target(self.parent.codec, native_row.get("generated_token_ids")) == ir,
                             "source parent generated token/IR join differs")
                    try:
                        row["anchor_inference_attempted"] = True
                        predicted = self._anchor_generated(source, ir)
                    except ValueError as error:
                        row.update(outcome="anchor_abstained", reason=str(error))
                    else:
                        proposal = byte_codec.validate_proposal(predicted["proposal"], source)
                        _require(proposal["canonical_ir"] == ir, "anchors changed source-generated canonical IR")
                        row.update(outcome="anchored_proposal", reason=None, proposal=proposal,
                                   anchor_diagnostics=copy.deepcopy(predicted["diagnostics"]))
        self._assert_state()
        counts = {outcome: sum(row["outcome"] == outcome for row in rows) for outcome in (
            "source_blocked", "clarification_required", "source_encoding_unavailable", "parent_abstained",
            "parent_unavailable", "anchor_abstained", "anchored_proposal")}
        result = {"schema": INFERENCE_SCHEMA, "lineage_id": LINEAGE_ID,
                  "source_checkpoint_sha256": self.source_checkpoint_sha256,
                  "anchor_checkpoint_sha256": self.anchor_checkpoint_sha256,
                  "input_count": len(rows), "submitted_positions": positions, "rows": rows,
                  "outcome_counts": counts, "proposal_count": counts["anchored_proposal"],
                  "parent_invocation_count": int(bool(positions)), "parent_completion_count": completion,
                  "parent_submitted_row_count": len(positions), "parent_backend": copy.deepcopy(backend),
                  "parent_exception_type": exception_type,
                  "anchor_row_count": sum(row["parent_row"] is not None and row["parent_row"]["status"] == "decoded" for row in rows),
                  "inference_attempted": bool(positions), "target_access": False, "teacher_forcing": False,
                  "parent_inference_attempted": bool(positions),
                  "anchor_inference_attempted": any(row["anchor_inference_attempted"] for row in rows),
                  "anchor_invocation_count": sum(row["anchor_inference_attempted"] for row in rows),
                  "model_execution_scope": "recorded_method_attempts_not_independent_numerical_forward_attestation",
                  "proposal_flag_scope": "transport_validation_only_not_generation_provenance",
                  "training_executed": False, "context_applied": False, "latent_inputs": False,
                  "execution_scope": "source_parent_free_generation_then_learned_complete_anchors", **_FALSE}
        return {**result, "content_sha256": _digest(result)}


def save_checkpoint(source_checkpoint, anchor_checkpoint, path):
    """Exclusively write a validated JSON anchor checkpoint."""
    validate_checkpoint(source_checkpoint, anchor_checkpoint)
    raw = _raw(anchor_checkpoint)
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
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def load_checkpoint(source_checkpoint, path, *, expected_sha256):
    """Read a bounded exact-hash regular file and restore its closed state."""
    _hash(expected_sha256, "expected_sha256")
    path = Path(path).absolute()
    _require(path.resolve(strict=True) == path, "canonical anchor checkpoint path required")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        _require(stat.S_ISREG(before.st_mode) and before.st_size <= MAX_BYTES, "bounded regular anchor file required")
        raw = stream.read(MAX_BYTES + 1)
        after = os.fstat(stream.fileno())
    _require(len(raw) <= MAX_BYTES and (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns),
             "anchor checkpoint changed while reading")
    _require(hashlib.sha256(raw).hexdigest() == expected_sha256, "anchor checkpoint file hash differs")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            _require(key not in result, "duplicate anchor checkpoint JSON key")
            result[key] = value
        return result
    def reject(value):
        raise ValueError("nonfinite anchor checkpoint JSON constant: " + value)
    checkpoint = json.loads(raw, object_pairs_hook=unique, parse_constant=reject)
    validate_checkpoint(source_checkpoint, checkpoint)
    return checkpoint


__all__ = ["train_anchor_decoder", "validate_checkpoint", "checkpoint_digest", "tokenize_source",
           "TypedAnchorDecoder", "save_checkpoint", "load_checkpoint"]
