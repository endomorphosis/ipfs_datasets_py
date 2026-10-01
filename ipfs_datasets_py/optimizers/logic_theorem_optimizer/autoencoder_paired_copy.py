"""Domain-neutral paired sequence learning with an input-local copy vocabulary.

The learned gate mixes generator probabilities with learned source attention.
Only the current input supplies copy strings: no examples, semantic parser, or
target text enter inference. This additive backend leaves older checkpoints and
their pinned producer modules untouched. Copying establishes lexical coverage,
not semantic correctness.
"""
from __future__ import annotations

import math
from pathlib import Path
import time
from types import SimpleNamespace

from . import autoencoder_paired_text as legacy

SCHEMA = "shared-paired-copy-autoencoder/v1"
ARCHITECTURE = "gru_attention_pointer_generator/v1"
SPECIAL, MAX_TOKENS, MAX_BYTES = legacy.SPECIAL, legacy.MAX_TOKENS, legacy.MAX_BYTES
tokenize = legacy.tokenize
_require, _raw, _sha, _read, _json = legacy._require, legacy._raw, legacy._sha, legacy._read, legacy._json
_FALSE = dict(legacy._FALSE)


def _implementation():
    return {"copy_backend_sha256": _sha(Path(__file__).read_bytes()), **legacy._implementation()}


def _model(torch, config, lexical_rows):
    class PairedCopyModel(torch.nn.Module):
        def __init__(self):
            super().__init__()
            width, hidden, count = config["embedding_dim"], config["hidden_size"], len(config["vocabulary"])
            lexical = torch.tensor(lexical_rows, dtype=torch.float32)
            self.register_buffer("lexical", lexical)
            self.embedding = torch.nn.Embedding(count, width, padding_idx=0)
            full_width = width + lexical.shape[1]
            self.encoder = torch.nn.GRU(full_width, hidden, batch_first=True)
            self.decoder = torch.nn.GRU(full_width, hidden, batch_first=True)
            self.output = torch.nn.Linear(hidden * 2, count)
            self.copy_gate = torch.nn.Linear(hidden * 2 + full_width, 1)

        def embed(self, ids):
            ids = ids.masked_fill(ids >= len(config["vocabulary"]), 3)
            return torch.cat((self.embedding(ids), self.lexical[ids]), dim=-1)

        def encode(self, ids, lengths):
            packed = torch.nn.utils.rnn.pack_padded_sequence(self.embed(ids), lengths.cpu(),
                                                             batch_first=True, enforce_sorted=False)
            encoded, hidden = self.encoder(packed)
            encoded, _ = torch.nn.utils.rnn.pad_packed_sequence(encoded, batch_first=True,
                                                               total_length=ids.shape[1])
            return encoded, hidden

        def decode(self, ids, hidden, encoded, mask, source_copy_ids, extended_size,
                   *, disable_copy=False):
            embedded = self.embed(ids)
            output, hidden = self.decoder(embedded, hidden)
            scores = torch.bmm(output, encoded.transpose(1, 2)) / math.sqrt(config["hidden_size"])
            attention = torch.softmax(scores.masked_fill(~mask[:, None, :], -1e9), dim=-1)
            context = torch.bmm(attention, encoded)
            joined = torch.cat((output, context), dim=-1)
            generator = torch.softmax(self.output(joined), dim=-1)
            gate = torch.sigmoid(self.copy_gate(torch.cat((joined, embedded), dim=-1)))
            if disable_copy:
                gate = torch.ones_like(gate)
            generator = torch.nn.functional.pad(generator * gate,
                                                 (0, extended_size - generator.shape[-1]))
            copy = generator.new_zeros(generator.shape)
            indices = source_copy_ids[:, None, :].expand(-1, ids.shape[1], -1)
            copy.scatter_add_(2, indices, attention * (1.0 - gate))
            return generator + copy, hidden, generator, copy, attention, gate

    return PairedCopyModel()


def _source_ids(tokens, vocabulary, direction, *, masked=()):
    """Map source tokens to fixed embeddings and an ephemeral copy alphabet."""
    positions = {token: index for index, token in enumerate(vocabulary)}
    masked = set(masked)
    extended = []
    extra_ids = {}
    embedded, copied = [positions["<" + direction + ">"]], [0]
    for token in tokens:
        if token not in positions or token in masked:
            if token not in extra_ids:
                extra_ids[token] = len(vocabulary) + len(extended)
                extended.append(token)
            embedded.append(3)
            copied.append(extra_ids[token])
        else:
            embedded.append(positions[token])
            copied.append(positions[token])
    return embedded, copied, extended, extra_ids


def _batch(torch, records, vocabulary, *, generator=None, dropout=0.0):
    positions = {word: index for index, word in enumerate(vocabulary)}
    inputs, copy_inputs, outputs, sizes = [], [], [], []
    mask_counts = {direction: 0 for direction in ("encode", "decode")}
    for row, source, target in records:
        # Domain-neutral type masking: labels are untouched; dropped lexical
        # types get temporary copy IDs in both source and teacher targets.
        eligible = sorted({token for token in source if not token.startswith("<")
                           and any(char.isalnum() for char in token)})
        masked = set()
        if dropout:
            _require(generator is not None, "training masking requires a seeded generator")
            chosen = torch.rand(len(eligible), generator=generator).tolist()
            masked = {token for token, draw in zip(eligible, chosen) if draw < dropout}
        source_ids, copy_ids, extended, extra_ids = _source_ids(source, vocabulary, row["direction"], masked=masked)
        target_ids = [extra_ids[token] if token in extra_ids else positions.get(token, 3) for token in target]
        inputs.append(source_ids); copy_inputs.append(copy_ids); outputs.append([1] + target_ids + [2])
        sizes.append(len(vocabulary) + len(extended))
        mask_counts[row["direction"]] += len(masked)
    def pad(rows):
        width = max(map(len, rows))
        return torch.tensor([row + [0] * (width - len(row)) for row in rows], dtype=torch.long)
    source = pad(inputs)
    mask = source != 0
    mask[:, 0] = False  # Direction tags are context, never copyable user tokens.
    return (source, torch.tensor(list(map(len, inputs))), pad(copy_inputs), pad(outputs),
            mask, max(sizes), mask_counts)


def _loss(torch, model, batch):
    from .modal_autoencoder_cuda import _loss_chunk
    source, lengths, copied, target, mask, size, _ = batch
    encoded, hidden = model.encode(source, lengths)
    probabilities, _, _, _, _, _ = model.decode(target[:, :-1], hidden, encoded, mask, copied, size)
    _require(bool(torch.isfinite(probabilities).all()), "nonfinite copy probabilities")
    # The native cross-entropy kernel accepts logits. Log probabilities are
    # logits for this normalized mixture and retain gradients through copying.
    observed = probabilities.clamp_min(1e-30).log().reshape(-1, size)
    expected = target[:, 1:].reshape(-1)
    keep = expected != 0
    observed, expected = observed[keep], expected[keep]
    count = len(expected)
    state = SimpleNamespace(torch=torch, device=torch.device("cpu"),
        family_targets=torch.nn.functional.one_hot(expected, num_classes=size).float(),
        family_mask=torch.ones(count, dtype=torch.bool))
    parameters = list(model.parameters())
    session = SimpleNamespace(blocks={}, parameters=parameters,
                              parameter_count=sum(item.numel() for item in parameters))
    empty = observed.new_zeros((count, 0))
    loss, _, calls = _loss_chunk(state, session, (empty, observed, empty), {"family_logits"},
                                0, count, count, 0.0, 0.0, False)
    return loss, calls, count


def _generate(model, config, source, direction, maximum, *, disable_copy=False):
    import torch
    _require(direction in ("encode", "decode"), "unknown paired direction")
    _require(type(maximum) is int and 1 <= maximum <= MAX_TOKENS, "bounded decoder length required")
    tokens = tokenize(source)
    _require(len(tokens) < MAX_TOKENS, "source must leave room for direction token")
    vocabulary = config["vocabulary"]
    inputs, copied, extra, _ = _source_ids(tokens, vocabulary, direction)
    alphabet = vocabulary + extra
    source_ids = torch.tensor([inputs], dtype=torch.long)
    copy_ids = torch.tensor([copied], dtype=torch.long)
    mask = source_ids != 0
    mask[:, 0] = False
    predicted, traces, ended = [], [], False
    model.eval()
    with torch.inference_mode():
        encoded, hidden = model.encode(source_ids, torch.tensor([len(inputs)]))
        current = torch.tensor([[1]], dtype=torch.long)
        for _ in range(maximum):
            probabilities, hidden, generated, copy, attention, gate = model.decode(
                current, hidden, encoded, mask, copy_ids, len(alphabet), disable_copy=disable_copy)
            _require(all(bool(torch.isfinite(tensor).all()) for tensor in
                         (probabilities, generated, copy, attention, gate, hidden)),
                     "nonfinite copy inference probabilities")
            index = int(probabilities[0, -1].argmax())
            if index == 2:
                ended = True
                break
            token = alphabet[index]
            predicted.append(token)
            gen_mass, copy_mass = float(generated[0, -1, index]), float(copy[0, -1, index])
            traces.append({"token": token, "extended_copy_token": index >= len(vocabulary),
                "generator_probability": gen_mass, "copy_probability": copy_mass,
                "copy_source_positions": [i for i, value in enumerate(tokens) if value == token],
                "dominant_branch": "copy" if copy_mass > gen_mass else "generator"})
            if index in (0, 1, 3, 4, 5):
                break
            current = torch.tensor([[index]], dtype=torch.long)
    bad = any(token in SPECIAL for token in predicted)
    status = "generated" if ended and predicted and not bad else "invalid_or_incomplete_output"
    unknown = sorted(set(tokens) - set(vocabulary))
    return {"generated_text": " ".join(predicted), "tokens": predicted, "ended": ended,
        "status": status, "input_oov_tokens": unknown,
        "uncovered_input_tokens": unknown if disable_copy else [],
        "input_coverage_complete": not unknown or not disable_copy,
        "copy_trace": traces, "copy_enabled": not disable_copy,
        "copy_vocabulary_scope": "current_input_only", "copy_probability_is_semantic_confidence": False,
        "teacher_forcing": False, "target_access": False, "training_executed": False,
        "provider_calls": 0, "download_calls": 0, **_FALSE}


def _report(model, records, config, *, max_new_tokens=96, disable_copy=False):
    rows = []
    vocabulary = set(config["vocabulary"])
    for row, source, target in records:
        result = _generate(model, config, row["source"], row["direction"], max_new_tokens,
                           disable_copy=disable_copy)
        actual = result["tokens"]
        rows.append({"id": row["id"], "direction": row["direction"], **result,
            "exact_tokens": actual == target and result["ended"],
            "expected_token_count": len(target), "generated_token_count": len(actual),
            "positional_token_accuracy": sum(a == b for a, b in zip(actual, target)) / max(len(actual), len(target)),
            "target_oov_tokens": sorted(set(target) - vocabulary),
            "uncovered_target_tokens": sorted(set(target) - vocabulary - (set(source) if not disable_copy else set()))})
    return {"count": len(rows), "exact_token_rate": sum(row["exact_tokens"] for row in rows) / len(rows),
        "positional_token_accuracy": sum(row["positional_token_accuracy"] for row in rows) / len(rows),
        "rows": rows, "teacher_forcing": False, **_FALSE}


def train_paired_copy(training_pairs, tuning_pairs, *, output_dir, lexical_initializer_path=None,
                      epochs=100, max_seconds=180, hidden_size=96, embedding_dim=48,
                      seed=1729, copy_dropout=0.20):
    """Fit both directions with train-only lexical masking; evaluate tuning last.

    Tuning never sets the vocabulary, updates weights, or selects an epoch.
    An unknown source token can be copied; its meaning remains unverified.
    """
    import torch
    from .modal_autoencoder_cuda import _gradient_norm
    from .modal_autoencoder_batching import plan_gradient_accumulation
    train, tuning = legacy._pairs(training_pairs), legacy._pairs(tuning_pairs)
    _require(type(epochs) is int and 1 <= epochs <= 1000 and type(seed) is int and 0 <= seed < 2**31,
             "bounded integer training settings required")
    _require(type(hidden_size) is int and 8 <= hidden_size <= 256 and
             type(embedding_dim) is int and 8 <= embedding_dim <= 128, "bounded sequence model dimensions required")
    _require(type(max_seconds) in (int, float) and math.isfinite(max_seconds) and 0 < max_seconds <= 3600,
             "bounded training deadline required")
    _require(type(copy_dropout) in (int, float) and math.isfinite(copy_dropout) and 0 <= copy_dropout <= 0.75,
             "bounded copy dropout required")
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
    lexical, lineage = legacy._lexical(vocabulary, lexical_initializer_path)
    config = {"schema": SCHEMA, "architecture": ARCHITECTURE, "hidden_size": hidden_size,
        "embedding_dim": embedding_dim, "lexical_width": lineage["inherited_width"],
        "vocabulary": vocabulary, "token_pattern": legacy.TOKEN_PATTERN, "max_tokens": MAX_TOKENS,
        "copy_dropout": float(copy_dropout), "copy_vocabulary_scope": "current_input_only",
        "implementation": _implementation(), "device": "cpu", "dtype": "float32"}
    started = time.monotonic()
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(seed)
        model = _model(torch, config, lexical)
        optimizer = torch.optim.Adam(model.parameters(), lr=0.008)
        initial = _sha(_raw({key: value.tolist() for key, value in model.state_dict().items()}))
        generator = torch.Generator().manual_seed(seed)
        history, norms, calls, steps = [], [], 0, 0
        mask_counts = {direction: 0 for direction in ("encode", "decode")}
        batch_plan = plan_gradient_accumulation(len(train), microbatch_size=64)
        for epoch in range(epochs):
            model.train()
            order = torch.randperm(len(train), generator=generator).tolist()
            weighted_loss, tokens_total = 0.0, 0
            for begin, end in batch_plan.ranges:
                rows = [train[index] for index in order[begin:end]]
                batch = _batch(torch, rows, vocabulary, generator=generator, dropout=float(copy_dropout))
                for direction, count in batch[-1].items():
                    mask_counts[direction] += count
                optimizer.zero_grad(set_to_none=True)
                loss, native_calls, token_count = _loss(torch, model, batch)
                _require(bool(torch.isfinite(loss)), "nonfinite paired copy training loss")
                loss.backward()
                gradient = _gradient_norm(torch, list(model.parameters()))
                _require(math.isfinite(gradient), "nonfinite paired copy training gradient")
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
        "copy_masked_types_by_direction": mask_counts, "copy_dropout_scope": "training_only",
        "inference_copy_strings": "current_input_tokens_only",
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
    load_paired_copy(descriptor)
    return descriptor


def _finite(value):
    if type(value) is list:
        return all(_finite(item) for item in value)
    return type(value) in (int, float) and math.isfinite(value)


def load_paired_copy(descriptor):
    """Validate inert bounded tensor JSON, implementation pins and lineage."""
    import torch
    _require(type(descriptor) is dict and set(descriptor) == {"schema", "path", "sha256"},
             "closed paired copy checkpoint descriptor required")
    _require(descriptor["schema"] == SCHEMA and type(descriptor["sha256"]) is str and
             legacy._SHA.fullmatch(descriptor["sha256"]) and type(descriptor["path"]) is str,
             "exact paired copy checkpoint schema and hash required")
    raw = _read(Path(descriptor["path"]))
    _require(_sha(raw) == descriptor["sha256"], "paired checkpoint hash differs")
    package = _json(raw)
    _require(type(package) is dict and set(package) == {"schema", "config", "weights", "training", *_FALSE} and
             package["schema"] == SCHEMA and all(package[key] is False for key in _FALSE),
             "closed paired package with no admission authority required")
    config, weights, training = package["config"], package["weights"], package["training"]
    _require(type(config) is dict and set(config) == {"schema", "architecture", "hidden_size", "embedding_dim",
             "lexical_width", "vocabulary", "token_pattern", "max_tokens", "copy_dropout", "copy_vocabulary_scope",
             "implementation", "device", "dtype"}, "closed paired copy architecture required")
    _require(config["schema"] == SCHEMA and config["architecture"] == ARCHITECTURE and
             config["implementation"] == _implementation() and config["token_pattern"] == legacy.TOKEN_PATTERN and
             config["max_tokens"] == MAX_TOKENS and config["copy_vocabulary_scope"] == "current_input_only" and
             config["device"] == "cpu" and config["dtype"] == "float32",
             "paired copy implementation or architecture differs")
    _require(type(config["hidden_size"]) is int and 8 <= config["hidden_size"] <= 256 and
             type(config["embedding_dim"]) is int and 8 <= config["embedding_dim"] <= 128 and
             type(config["lexical_width"]) is int and 2 <= config["lexical_width"] <= 64 and
             type(config["copy_dropout"]) in (int, float) and math.isfinite(config["copy_dropout"]) and
             0 <= config["copy_dropout"] <= 0.75, "invalid paired copy dimensions or dropout")
    vocabulary = config["vocabulary"]
    _require(type(vocabulary) is list and 7 <= len(vocabulary) <= 4096 and vocabulary[:6] == list(SPECIAL) and
             all(type(token) is str and 0 < len(token) <= 16384 for token in vocabulary) and
             len(vocabulary) == len(set(vocabulary)) and vocabulary[6:] == sorted(vocabulary[6:]) and
             all(tokenize(token) == [token] for token in vocabulary[6:]), "invalid paired vocabulary")
    with torch.random.fork_rng(devices=[]):
        model = _model(torch, config, [[0.0] * config["lexical_width"] for _ in vocabulary])
    expected = model.state_dict()
    _require(type(weights) is dict and set(weights) == set(expected), "paired tensor names differ")
    tensors = {}
    for name, reference in expected.items():
        _require(_finite(weights[name]), "nonfinite paired tensor")
        try:
            tensor = torch.tensor(weights[name], dtype=torch.float32)
        except (ValueError, TypeError) as exc:
            raise ValueError("invalid paired tensor shape") from exc
        _require(tensor.shape == reference.shape and bool(torch.isfinite(tensor).all()),
                 "paired tensor shape or range differs")
        tensors[name] = tensor
    fields = {"schema", "epochs_requested", "epochs_completed", "optimizer_steps", "native_kernel_calls",
        "training_loss", "gradient_norm_max", "seed", "training_seconds", "stopping", "training_pair_count",
        "tuning_pair_count", "training_pairs_sha256", "tuning_pairs_sha256", "initial_state_sha256",
        "final_state_sha256", "lexical_lineage", "tuning", "new_parameters_initialization", "vocabulary_fit_scope",
        "tuning_used_for_fit_or_selection", "copy_masked_types_by_direction", "copy_dropout_scope",
        "inference_copy_strings", "sample_memory_used", "training_source_bodies_persisted",
        "provider_calls", "download_calls", *_FALSE}
    _require(type(training) is dict and set(training) == fields and training["schema"] == SCHEMA and
             training["final_state_sha256"] == _sha(_raw(weights)) and
             all(training.get(key) is False for key in (*_FALSE, "tuning_used_for_fit_or_selection",
                 "sample_memory_used", "training_source_bodies_persisted")), "paired copy training evidence differs")
    _require(all(type(training[key]) is str and legacy._SHA.fullmatch(training[key]) for key in
                 ("training_pairs_sha256", "tuning_pairs_sha256", "initial_state_sha256", "final_state_sha256")) and
             type(training["epochs_requested"]) is int and 1 <= training["epochs_requested"] <= 1000 and
             type(training["epochs_completed"]) is int and 1 <= training["epochs_completed"] <= training["epochs_requested"] and
             type(training["training_loss"]) is list and len(training["training_loss"]) == training["epochs_completed"] and
             all(type(v) in (int, float) and math.isfinite(v) and v >= 0 for v in training["training_loss"]) and
             all(type(training[k]) is int and 1 <= training[k] <= 8192 for k in ("training_pair_count", "tuning_pair_count")) and
             type(training["optimizer_steps"]) is int and
             training["optimizer_steps"] == training["epochs_completed"] * math.ceil(training["training_pair_count"] / 64) and
             type(training["native_kernel_calls"]) is int and training["native_kernel_calls"] == 3 * training["optimizer_steps"] and
             training["vocabulary_fit_scope"] == "training_only" and training["copy_dropout_scope"] == "training_only" and
             training["inference_copy_strings"] == "current_input_tokens_only" and
             type(training["seed"]) is int and 0 <= training["seed"] < 2**31 and
             all(type(training[k]) in (int, float) and math.isfinite(training[k]) and training[k] >= 0 for k in
                 ("gradient_norm_max", "training_seconds")) and
             training["stopping"] == ("epoch_limit" if training["epochs_completed"] == training["epochs_requested"]
                                      else "wall_clock_budget_at_epoch_boundary") and
             type(training["provider_calls"]) is int and type(training["download_calls"]) is int and
             training["provider_calls"] == training["download_calls"] == 0,
             "invalid paired copy training counts or numerical evidence")
    counts = training["copy_masked_types_by_direction"]
    _require(type(counts) is dict and set(counts) == {"encode", "decode"} and
             all(type(value) is int and 0 <= value <= training["epochs_completed"] * training["training_pair_count"] * MAX_TOKENS
                 for value in counts.values()) and (config["copy_dropout"] > 0 or not any(counts.values())),
             "invalid train-only copy masking evidence")
    _require(training["new_parameters_initialization"] ==
             "seeded PyTorch initialization; shared lexical branch frozen", "invalid parameter initialization evidence")
    lineage = training["lexical_lineage"]
    _require(type(lineage) is dict and set(lineage) == {"present", "initializer_sha256", "parent_checkpoint_sha256",
             "inherited_width", "matched_tokens", "frozen", "parent_modified", "numeric_conversion"} and
             type(lineage["present"]) is bool and lineage["frozen"] is True and lineage["parent_modified"] is False and
             lineage["inherited_width"] == config["lexical_width"] and type(lineage["matched_tokens"]) is int and
             0 <= lineage["matched_tokens"] <= len(vocabulary) and lineage["numeric_conversion"] == "float32 inference branch",
             "invalid paired initializer lineage")
    for key in ("initializer_sha256", "parent_checkpoint_sha256"):
        _require((type(lineage[key]) is str and legacy._SHA.fullmatch(lineage[key])) if lineage["present"] else lineage[key] is None,
                 "paired parent identity differs")
    if not lineage["present"]:
        _require(lineage["matched_tokens"] == 0 and not bool(tensors["lexical"].any()), "unexpected lexical inheritance")
    model.load_state_dict(tensors)
    model.eval()
    return {"descriptor": dict(descriptor), "config": config, "training": training, "model": model}


def _ablate(model, selection):
    _require(selection in (None, "zero_output_head", "disable_copy"), "unknown paired copy weight ablation")
    if selection == "zero_output_head":
        import torch
        with torch.no_grad():
            model.output.weight.zero_(); model.output.bias.zero_()
    return selection == "disable_copy"


def infer_paired_copy(descriptor, source, direction, max_new_tokens=96, *, weight_ablation=None):
    loaded = load_paired_copy(descriptor)
    disabled = _ablate(loaded["model"], weight_ablation)
    return {**_generate(loaded["model"], loaded["config"], source, direction, max_new_tokens, disable_copy=disabled),
        "checkpoint_weights_sha256": loaded["training"]["final_state_sha256"], "weight_ablation": weight_ablation}


def evaluate_paired_copy(descriptor, pairs, *, weight_ablation=None, max_new_tokens=96):
    loaded = load_paired_copy(descriptor)
    disabled = _ablate(loaded["model"], weight_ablation)
    return {**_report(loaded["model"], legacy._pairs(pairs), loaded["config"],
                     max_new_tokens=max_new_tokens, disable_copy=disabled),
        "checkpoint_weights_sha256": loaded["training"]["final_state_sha256"], "weight_ablation": weight_ablation}
