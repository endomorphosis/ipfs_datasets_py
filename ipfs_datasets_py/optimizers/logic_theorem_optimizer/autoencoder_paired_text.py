"""Small, domain-neutral paired text/IR training and frozen sequence inference.

This supervised bottleneck has two directions, selected by an input tag. A
GRU encoder and attention decoder predict every output token. No sample
memory, nearest-neighbour lookup, parser labels or teacher targets are used
at inference. Domain codecs and semantic admission remain the caller's job.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import time
from types import SimpleNamespace

SCHEMA = "shared-paired-text-autoencoder/v1"
MAX_BYTES = 48 * 1024 * 1024
MAX_TOKENS = 192
SPECIAL = ("<pad>", "<bos>", "<eos>", "<unk>", "<encode>", "<decode>")
TOKEN_PATTERN = r"<[A-Za-z_][A-Za-z_0-9-]*>|\w+|[^\w\s]"
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_FALSE = {"proof_authority": False, "execution_authority": False,
          "semantic_correctness_verified": False, "publication_performed": False}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode()


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _unique(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, "duplicate paired checkpoint key")
        result[key] = value
    return result


def _read(path, bound=MAX_BYTES):
    path = Path(path)
    _require(path.is_absolute() and path.resolve(strict=True) == path,
             "canonical absolute artifact path required")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        _require(stat.S_ISREG(before.st_mode) and before.st_size <= bound,
                 "bounded regular paired artifact required")
        raw = stream.read(bound + 1)
        after = os.fstat(stream.fileno())
    _require(len(raw) <= bound and (before.st_size, before.st_mtime_ns) ==
             (after.st_size, after.st_mtime_ns), "paired artifact changed while reading")
    return raw


def _json(raw):
    def reject(_):
        raise ValueError("nonfinite JSON number")
    return json.loads(raw, object_pairs_hook=_unique, parse_constant=reject)


def tokenize(text):
    _require(type(text) is str and 0 < len(text) <= 16384, "bounded nonempty paired text required")
    tokens = re.findall(TOKEN_PATTERN, text)
    _require(0 < len(tokens) <= MAX_TOKENS, "paired text exceeds token bound")
    _require(not any(token in SPECIAL for token in tokens), "reserved model token in user text")
    return tokens


def _pairs(rows):
    _require(type(rows) in (list, tuple) and 1 <= len(rows) <= 8192,
             "one to 8192 paired examples required")
    seen, result, targets = set(), [], {}
    for row in rows:
        _require(type(row) is dict and set(row) == {"id", "source", "target", "direction"},
                 "closed paired example schema required")
        _require(type(row["id"]) is str and 0 < len(row["id"]) <= 512 and row["id"] not in seen,
                 "unique bounded paired example IDs required")
        _require(row["direction"] in ("encode", "decode"), "unknown paired direction")
        source, target = tokenize(row["source"]), tokenize(row["target"])
        _require(len(source) < MAX_TOKENS and len(target) < MAX_TOKENS,
                 "paired examples must leave room for boundary tokens")
        identity = row["direction"], tuple(source)
        _require(identity not in targets or targets[identity] == target,
                 "one source cannot have conflicting paired targets")
        targets[identity] = target
        result.append((row, source, target)); seen.add(row["id"])
    return result


def _implementation():
    from . import modal_autoencoder_cuda as kernel, modal_autoencoder_batching as batching
    return {"backend_sha256": _sha(Path(__file__).read_bytes()),
            "native_kernel_sha256": _sha(Path(kernel.__file__).read_bytes()),
            "native_batching_sha256": _sha(Path(batching.__file__).read_bytes())}


def _model(torch, config, lexical_rows):
    class PairedSequenceModel(torch.nn.Module):
        def __init__(self):
            super().__init__()
            width, hidden, count = config["embedding_dim"], config["hidden_size"], len(config["vocabulary"])
            lexical = torch.tensor(lexical_rows, dtype=torch.float32)
            self.register_buffer("lexical", lexical)
            self.embedding = torch.nn.Embedding(count, width, padding_idx=0)
            self.encoder = torch.nn.GRU(width + lexical.shape[1], hidden, batch_first=True)
            self.decoder = torch.nn.GRU(width + lexical.shape[1], hidden, batch_first=True)
            self.output = torch.nn.Linear(hidden * 2, count)

        def embed(self, ids):
            return torch.cat((self.embedding(ids), self.lexical[ids]), dim=-1)

        def encode(self, ids, lengths):
            packed = torch.nn.utils.rnn.pack_padded_sequence(self.embed(ids), lengths.cpu(),
                                                             batch_first=True, enforce_sorted=False)
            encoded, hidden = self.encoder(packed)
            encoded, _ = torch.nn.utils.rnn.pad_packed_sequence(encoded, batch_first=True,
                                                               total_length=ids.shape[1])
            return encoded, hidden

        def decode(self, ids, hidden, encoded, mask):
            outputs, hidden = self.decoder(self.embed(ids), hidden)
            scores = torch.bmm(outputs, encoded.transpose(1, 2)) / math.sqrt(config["hidden_size"])
            scores = scores.masked_fill(~mask[:, None, :], -1e9)
            context = torch.bmm(torch.softmax(scores, dim=-1), encoded)
            return self.output(torch.cat((outputs, context), dim=-1)), hidden

        def forward(self, source, lengths, target):
            encoded, hidden = self.encode(source, lengths)
            return self.decode(target, hidden, encoded, source != 0)[0]
    return PairedSequenceModel()


def _lexical(vocabulary, path):
    if path is None:
        return [[0.0] * 8 for _ in vocabulary], {"present": False, "initializer_sha256": None,
            "parent_checkpoint_sha256": None, "inherited_width": 8, "matched_tokens": 0,
            "frozen": True, "parent_modified": False, "numeric_conversion": "float32 inference branch"}
    raw = _read(Path(path), 8 * 1024 * 1024)
    value = _json(raw)
    _require(type(value) is dict and type(value.get("keys")) is list and
             type(value.get("weights")) is list and type(value.get("embedding_width")) is int,
             "shared lexical initializer required")
    keys, weights, width = value["keys"], value["weights"], value["embedding_width"]
    _require(1 <= len(keys) <= 8192 and keys == sorted(set(keys)) and
             all(type(key) is str and re.fullmatch(r"token:[a-z0-9]{3,}", key) for key in keys) and
             2 <= width <= 64 and len(weights) == len(keys), "invalid inherited lexical basis")
    _require(all(type(row) is list and len(row) == width and all(type(v) in (int, float) and
             math.isfinite(v) for v in row) for row in weights), "invalid inherited lexical tensor")
    parent = value.get("source_checkpoint_sha256")
    _require(type(parent) is str and _SHA.fullmatch(parent), "inherited parent identity required")
    lookup = dict(zip(keys, weights))
    rows = [lookup.get("token:" + token.casefold(), [0.0] * width) for token in vocabulary]
    return rows, {"present": True, "initializer_sha256": _sha(raw),
        "parent_checkpoint_sha256": parent, "inherited_width": width,
        "matched_tokens": sum("token:" + token.casefold() in lookup for token in vocabulary),
        "frozen": True, "parent_modified": False, "numeric_conversion": "float32 inference branch"}


def _batch(torch, records, vocabulary):
    positions = {word: index for index, word in enumerate(vocabulary)}
    inputs, outputs = [], []
    for row, source, target in records:
        inputs.append([positions["<" + row["direction"] + ">"]] + [positions.get(word, 3) for word in source])
        outputs.append([1] + [positions.get(word, 3) for word in target] + [2])
    def pad(rows):
        width = max(map(len, rows))
        return torch.tensor([row + [0] * (width - len(row)) for row in rows], dtype=torch.long)
    return pad(inputs), torch.tensor(list(map(len, inputs))), pad(outputs)


def _loss(torch, model, source, lengths, target):
    from .modal_autoencoder_cuda import _loss_chunk
    logits = model(source, lengths, target[:, :-1])
    expected = target[:, 1:].reshape(-1)
    observed = logits.reshape(-1, logits.shape[-1])
    keep = expected != 0
    observed, expected = observed[keep], expected[keep]
    count = len(expected)
    state = SimpleNamespace(torch=torch, device=torch.device("cpu"),
        family_targets=torch.nn.functional.one_hot(expected, num_classes=observed.shape[-1]).float(),
        family_mask=torch.ones(count, dtype=torch.bool))
    parameters = list(model.parameters())
    session = SimpleNamespace(blocks={}, parameters=parameters,
                              parameter_count=sum(item.numel() for item in parameters))
    empty = observed.new_zeros((count, 0))
    loss, _, calls = _loss_chunk(state, session, (empty, observed, empty), {"family_logits"},
                                0, count, count, 0.0, 0.0, False)
    return loss, calls, count


def _report(model, records, config, *, max_new_tokens=96):
    rows = []
    for row, source, target in records:
        decoded = _generate(model, config, row["source"], row["direction"], max_new_tokens)
        actual = decoded["tokens"]
        rows.append({"id": row["id"], "direction": row["direction"], "status": decoded["status"],
            "generated_text": decoded["generated_text"], "exact_tokens": actual == target and decoded["ended"],
            "expected_token_count": len(target), "generated_token_count": len(actual),
            "positional_token_accuracy": sum(a == b for a, b in zip(actual, target)) / max(len(actual), len(target)),
            "input_oov_tokens": decoded["input_oov_tokens"],
            "target_oov_tokens": sorted(set(target) - set(config["vocabulary"]))})
    return {"count": len(rows), "exact_token_rate": sum(row["exact_tokens"] for row in rows) / len(rows),
            "positional_token_accuracy": sum(row["positional_token_accuracy"] for row in rows) / len(rows),
            "rows": rows, "teacher_forcing": False, **_FALSE}


def _generate(model, config, source, direction, maximum):
    import torch
    _require(direction in ("encode", "decode"), "unknown paired direction")
    _require(type(maximum) is int and 1 <= maximum <= MAX_TOKENS, "bounded decoder length required")
    tokens = tokenize(source)
    _require(len(tokens) < MAX_TOKENS, "source must leave room for direction token")
    vocabulary = config["vocabulary"]
    positions = {word: index for index, word in enumerate(vocabulary)}
    input_ids = [positions["<" + direction + ">"]] + [positions.get(word, 3) for word in tokens]
    ids = torch.tensor([input_ids], dtype=torch.long)
    predicted, ended = [], False
    model.eval()
    with torch.inference_mode():
        encoded, hidden = model.encode(ids, torch.tensor([len(input_ids)]))
        current = torch.tensor([[1]], dtype=torch.long)
        for _ in range(maximum):
            logits, hidden = model.decode(current, hidden, encoded, ids != 0)
            _require(bool(torch.isfinite(logits).all()), "nonfinite inference logits")
            index = int(logits[0, -1].argmax())
            if index == 2:
                ended = True; break
            predicted.append(vocabulary[index])
            if index in (0, 1, 4, 5):
                break
            current = torch.tensor([[index]], dtype=torch.long)
    bad = any(token in SPECIAL for token in predicted)
    status = "generated" if ended and predicted and not bad else "invalid_or_incomplete_output"
    return {"generated_text": " ".join(predicted), "tokens": predicted, "ended": ended,
        "status": status, "input_oov_tokens": sorted(set(tokens) - set(vocabulary)),
        "teacher_forcing": False, "target_access": False, "training_executed": False,
        "provider_calls": 0, "download_calls": 0, **_FALSE}


def train_paired_text(training_pairs, tuning_pairs, *, output_dir,
        lexical_initializer_path=None, epochs=100, max_seconds=180,
        hidden_size=96, embedding_dim=48, seed=1729):
    """Fit both learned directions; vocabulary uses training text only.

    Tuning examples are only evaluated after fitting. They never affect the
    tokenizer, optimizer, stopping decision or selected final weights.
    """
    import torch
    from .modal_autoencoder_cuda import _gradient_norm
    from .modal_autoencoder_batching import plan_gradient_accumulation
    train, tuning = _pairs(training_pairs), _pairs(tuning_pairs)
    _require(type(epochs) is int and 1 <= epochs <= 1000 and type(seed) is int and 0 <= seed < 2**31,
             "bounded integer training settings required")
    _require(type(hidden_size) is int and 8 <= hidden_size <= 256 and
             type(embedding_dim) is int and 8 <= embedding_dim <= 128,
             "bounded sequence model dimensions required")
    _require(type(max_seconds) in (int, float) and math.isfinite(max_seconds) and 0 < max_seconds <= 3600,
             "bounded training deadline required")
    _require({row[0]["direction"] for row in train} == {"encode", "decode"}, "both training directions required")
    def identities(rows):
        return {(row["direction"], tuple(source)) for row, source, _ in rows}
    _require(not identities(train) & identities(tuning), "training and tuning source overlap")
    _require(not {row[0]["id"] for row in train} & {row[0]["id"] for row in tuning}, "training and tuning ID overlap")
    output = Path(output_dir).absolute()
    _require(not output.exists() and output.parent.resolve(strict=True) == output.parent,
             "fresh output under a canonical existing parent required")
    vocabulary = list(SPECIAL) + sorted({token for _, source, target in train for token in source + target})
    _require(len(vocabulary) <= 4096, "paired vocabulary exceeds 4096 tokens")
    lexical, lineage = _lexical(vocabulary, lexical_initializer_path)
    config = {"schema": SCHEMA, "architecture": "gru_encoder_attention_gru_decoder/v1",
        "hidden_size": hidden_size, "embedding_dim": embedding_dim,
        "lexical_width": lineage["inherited_width"], "vocabulary": vocabulary,
        "token_pattern": TOKEN_PATTERN, "max_tokens": MAX_TOKENS,
        "implementation": _implementation(), "device": "cpu", "dtype": "float32"}
    started = time.monotonic()
    # Fork RNG state so this helper does not alter the host application's RNG.
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(seed)
        model = _model(torch, config, lexical)
        optimizer = torch.optim.Adam(model.parameters(), lr=0.008)
        initial = _sha(_raw({key: value.tolist() for key, value in model.state_dict().items()}))
        generator = torch.Generator().manual_seed(seed)
        history, norms, calls, steps = [], [], 0, 0
        batch_plan = plan_gradient_accumulation(len(train), microbatch_size=64)
        for epoch in range(epochs):
            model.train()
            order = torch.randperm(len(train), generator=generator).tolist()
            weighted_loss, tokens_total = 0.0, 0
            for begin, end in batch_plan.ranges:
                rows = [train[index] for index in order[begin:end]]
                source, lengths, target = _batch(torch, rows, vocabulary)
                optimizer.zero_grad(set_to_none=True)
                loss, native_calls, token_count = _loss(torch, model, source, lengths, target)
                _require(bool(torch.isfinite(loss)), "nonfinite paired training loss")
                loss.backward()
                gradient = _gradient_norm(torch, list(model.parameters()))
                _require(math.isfinite(gradient), "nonfinite paired training gradient")
                torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0)
                optimizer.step()
                weighted_loss += float(loss.detach()) * token_count
                tokens_total += token_count; calls += native_calls; steps += 1; norms.append(gradient)
            history.append(weighted_loss / tokens_total)
            if time.monotonic() - started >= max_seconds:
                break
        weights = {key: value.detach().tolist() for key, value in model.state_dict().items()}
        _require(weights["lexical"] == torch.tensor(lexical, dtype=torch.float32).tolist(),
                 "frozen inherited lexical rows changed")
        # Domain-independent free-running metrics have no semantic authority.
        tuning_metrics = _report(model, tuning, config)
    training = {"schema": SCHEMA, "epochs_requested": epochs, "epochs_completed": len(history),
        "optimizer_steps": steps, "native_kernel_calls": calls, "training_loss": history,
        "gradient_norm_max": max(norms), "seed": seed, "training_seconds": time.monotonic() - started,
        "stopping": "epoch_limit" if len(history) == epochs else "wall_clock_budget_at_epoch_boundary",
        "training_pair_count": len(train), "tuning_pair_count": len(tuning),
        "training_pairs_sha256": _sha(_raw(training_pairs)), "tuning_pairs_sha256": _sha(_raw(tuning_pairs)),
        "initial_state_sha256": initial, "final_state_sha256": _sha(_raw(weights)),
        "lexical_lineage": lineage, "tuning": tuning_metrics,
        "new_parameters_initialization": "seeded PyTorch initialization; shared lexical branch frozen",
        "vocabulary_fit_scope": "training_only", "tuning_used_for_fit_or_selection": False,
        "sample_memory_used": False, "training_source_bodies_persisted": False,
        "provider_calls": 0, "download_calls": 0, **_FALSE}
    if lexical_initializer_path is not None:
        _require(_sha(_read(Path(lexical_initializer_path), 8 * 1024 * 1024)) == lineage["initializer_sha256"],
                 "inherited initializer changed during training")
    package = {"schema": SCHEMA, "config": config, "weights": weights, "training": training, **_FALSE}
    raw = _raw(package)
    _require(len(raw) <= MAX_BYTES, "paired artifact exceeds byte bound")
    output.mkdir()
    candidate = output / "candidate.json"
    candidate.write_bytes(raw)
    descriptor = {"schema": SCHEMA, "path": str(candidate), "sha256": _sha(raw)}
    load_paired_text(descriptor)
    return descriptor


def load_paired_text(descriptor):
    """Validate inert tensor JSON; loading never executes artifact code."""
    import torch
    _require(type(descriptor) is dict and set(descriptor) == {"schema", "path", "sha256"},
             "closed paired checkpoint descriptor required")
    _require(descriptor["schema"] == SCHEMA and type(descriptor["sha256"]) is str and
             _SHA.fullmatch(descriptor["sha256"]) and type(descriptor["path"]) is str,
             "exact paired checkpoint schema and hash required")
    raw = _read(Path(descriptor["path"]))
    _require(_sha(raw) == descriptor["sha256"], "paired checkpoint hash differs")
    package = _json(raw)
    _require(type(package) is dict and set(package) == {"schema", "config", "weights", "training", *_FALSE} and
             package["schema"] == SCHEMA and all(package[key] is False for key in _FALSE),
             "closed paired package with no admission authority required")
    config, weights, training = package["config"], package["weights"], package["training"]
    _require(type(config) is dict and set(config) == {"schema", "architecture", "hidden_size", "embedding_dim",
             "lexical_width", "vocabulary", "token_pattern", "max_tokens", "implementation", "device", "dtype"},
             "closed paired architecture required")
    _require(config["schema"] == SCHEMA and config["architecture"] == "gru_encoder_attention_gru_decoder/v1" and
             config["implementation"] == _implementation() and config["token_pattern"] == TOKEN_PATTERN and
             config["max_tokens"] == MAX_TOKENS and config["device"] == "cpu" and config["dtype"] == "float32",
             "paired implementation or architecture differs")
    _require(type(config["hidden_size"]) is int and 8 <= config["hidden_size"] <= 256 and
             type(config["embedding_dim"]) is int and 8 <= config["embedding_dim"] <= 128 and
             type(config["lexical_width"]) is int and 2 <= config["lexical_width"] <= 64,
             "invalid paired dimensions")
    vocabulary = config["vocabulary"]
    _require(type(vocabulary) is list and 7 <= len(vocabulary) <= 4096 and vocabulary[:6] == list(SPECIAL) and
             all(type(token) is str and 0 < len(token) <= 16384 for token in vocabulary) and
             len(vocabulary) == len(set(vocabulary)) and vocabulary[6:] == sorted(vocabulary[6:]),
             "invalid paired vocabulary")
    lexical = [[0.0] * config["lexical_width"] for _ in vocabulary]
    with torch.random.fork_rng(devices=[]):
        model = _model(torch, config, lexical)
    expected = model.state_dict()
    _require(type(weights) is dict and set(weights) == set(expected), "paired tensor names differ")
    tensors = {}
    for name, reference in expected.items():
        def finite(value):
            if type(value) is list:
                return all(finite(item) for item in value)
            return type(value) in (int, float) and math.isfinite(value)
        _require(finite(weights[name]), "nonfinite paired tensor")
        try:
            tensor = torch.tensor(weights[name], dtype=torch.float32)
        except (ValueError, TypeError) as exc:
            raise ValueError("invalid paired tensor shape") from exc
        _require(tensor.shape == reference.shape and bool(torch.isfinite(tensor).all()), "paired tensor shape or range differs")
        tensors[name] = tensor
    training_fields = {"schema", "epochs_requested", "epochs_completed", "optimizer_steps", "native_kernel_calls",
        "training_loss", "gradient_norm_max", "seed", "training_seconds", "stopping", "training_pair_count",
        "tuning_pair_count", "training_pairs_sha256", "tuning_pairs_sha256", "initial_state_sha256",
        "final_state_sha256", "lexical_lineage", "tuning", "new_parameters_initialization", "vocabulary_fit_scope",
        "tuning_used_for_fit_or_selection", "sample_memory_used", "training_source_bodies_persisted",
        "provider_calls", "download_calls", *_FALSE}
    _require(type(training) is dict and set(training) == training_fields and training.get("schema") == SCHEMA and
             training.get("final_state_sha256") == _sha(_raw(weights)) and
             training.get("tuning_used_for_fit_or_selection") is False and
             training.get("sample_memory_used") is False and
             all(training.get(key) is False for key in _FALSE) and
             type(training.get("optimizer_steps")) is int and training["optimizer_steps"] > 0,
             "paired training evidence differs")
    _require(all(type(training[key]) is str and _SHA.fullmatch(training[key]) for key in
                 ("training_pairs_sha256", "tuning_pairs_sha256", "initial_state_sha256", "final_state_sha256")) and
             type(training["epochs_requested"]) is int and 1 <= training["epochs_requested"] <= 1000 and
             type(training["epochs_completed"]) is int and 1 <= training["epochs_completed"] <= training["epochs_requested"] and
             type(training["training_loss"]) is list and len(training["training_loss"]) == training["epochs_completed"] and
             all(type(value) in (int, float) and math.isfinite(value) and value >= 0 for value in training["training_loss"]) and
             all(type(training[key]) is int and 1 <= training[key] <= 8192 for key in ("training_pair_count", "tuning_pair_count")) and
             training["optimizer_steps"] == training["epochs_completed"] * math.ceil(training["training_pair_count"] / 64) and
             training["native_kernel_calls"] == 3 * training["optimizer_steps"] and
             training["vocabulary_fit_scope"] == "training_only" and
             training["training_source_bodies_persisted"] is False and
             training["provider_calls"] == training["download_calls"] == 0,
             "invalid paired training counts or numerical evidence")
    lineage = training["lexical_lineage"]
    _require(type(lineage) is dict and set(lineage) == {"present", "initializer_sha256", "parent_checkpoint_sha256",
             "inherited_width", "matched_tokens", "frozen", "parent_modified", "numeric_conversion"} and
             type(lineage["present"]) is bool and lineage["frozen"] is True and lineage["parent_modified"] is False and
             lineage["inherited_width"] == config["lexical_width"] and type(lineage["matched_tokens"]) is int and
             0 <= lineage["matched_tokens"] <= len(vocabulary) and lineage["numeric_conversion"] == "float32 inference branch",
             "invalid paired initializer lineage")
    for key in ("initializer_sha256", "parent_checkpoint_sha256"):
        _require((type(lineage[key]) is str and _SHA.fullmatch(lineage[key])) if lineage["present"] else lineage[key] is None,
                 "paired parent identity differs")
    model.load_state_dict(tensors); model.eval()
    return {"descriptor": dict(descriptor), "config": config, "training": training, "model": model}


def infer_paired_text(descriptor, source, direction, max_new_tokens=96, *, weight_ablation=None):
    loaded = load_paired_text(descriptor)
    _ablate(loaded["model"], weight_ablation)
    return {**_generate(loaded["model"], loaded["config"], source, direction, max_new_tokens),
            "checkpoint_weights_sha256": loaded["training"]["final_state_sha256"], "weight_ablation": weight_ablation}


def _ablate(model, selection):
    _require(selection in (None, "zero_output_head"), "unknown paired weight ablation")
    if selection is not None:
        import torch
        with torch.no_grad():
            model.output.weight.zero_(); model.output.bias.zero_()


def evaluate_paired_text(descriptor, pairs, *, weight_ablation=None, max_new_tokens=96):
    loaded = load_paired_text(descriptor)
    _ablate(loaded["model"], weight_ablation)
    return {**_report(loaded["model"], _pairs(pairs), loaded["config"], max_new_tokens=max_new_tokens),
            "checkpoint_weights_sha256": loaded["training"]["final_state_sha256"], "weight_ablation": weight_ablation}
