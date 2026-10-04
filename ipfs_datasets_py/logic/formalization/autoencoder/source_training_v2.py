"""Shared experimental 384D source-to-typed-IR training and batched inference.

The baseline and semantic strategies share transferred Legal weights, vocabulary,
input transformation and batching. Semantic selection uses free-running tuning
predictions. Native validation is local shape evidence, never semantic proof.
Published v1 implementations and checkpoints are intentionally untouched.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import time

from ....optimizers.logic_theorem_optimizer import domain_384_autoencoder as native
from ....optimizers.logic_theorem_optimizer import modal_latent_formula as numerical
from ....optimizers.logic_theorem_optimizer import legal_formula_codec as legal_codec

SCHEMA = "shared-source-384-autoencoder/v2"
DOMAINS = (*native.DOMAINS, "legal_ir")
DIMENSION = 384
MAX_BYTES = native.MAX_BYTES
FALSE = native.FALSE
_require, _raw, digest = native._require, native._raw, native.digest
_MISSING = object()


def validate_target(domain, target):
    if domain != "legal_ir":
        return native.validate_target(domain, target)
    legal_codec._rule(target)
    return {"valid": True, "domain_id": domain, "kind": "canonical_deontic_rule",
            "canonical_ir": deepcopy(target), "scope": "one_canonical_deontic_rule", **FALSE}


def _implementation():
    return {"runtime_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "native": native._implementation(), "numerical": numerical._implementation(),
            "legal_codec_sha256": hashlib.sha256(Path(legal_codec.__file__).read_bytes()).hexdigest()}


def _rows(domain, rows, *, training):
    _require(domain in DOMAINS, "unsupported source decoder domain")
    # Reuse the closed provenance and numerical row checks without invoking a
    # different domain's target validator for Legal.
    if domain in native.DOMAINS:
        return native._rows(domain, rows, training=training)
    _require(type(rows) is list and 1 <= len(rows) <= 4096, "bounded nonempty rows required")
    fields = {"id", "source_text", "embedding"} | ({"target"} if training else set())
    _require(all(type(row) is dict and set(row) == fields for row in rows), "closed domain row schema required")
    native._rows("intent_ir", [{key: row[key] for key in ("id", "source_text", "embedding")} for row in rows], training=False)
    if training:
        for row in rows:
            validate_target(domain, row["target"])
    return deepcopy(rows)


def _leaves(value, path=()):
    if type(value) in (dict, list) and not value:
        return {path: value}
    if type(value) is dict:
        return {item: leaf for key in sorted(value) for item, leaf in _leaves(value[key], (*path, key)).items()}
    if type(value) is list:
        return {item: leaf for index, child in enumerate(value) for item, leaf in _leaves(child, (*path, index)).items()}
    return {path: value}


def _token_records(value, path=()):
    """Canonical JSON tokens with exact paths; keys never count as leaf values."""
    if type(value) is dict:
        if not value:
            return [("{", "leaf", path), ("}", "leaf", path)]
        result = [("{", "structure", path)]
        for index, key in enumerate(sorted(value)):
            if index:
                result.append((",", "structure", path))
            result.extend([(_raw(key).decode(), "key", path), (":", "structure", path)])
            result.extend(_token_records(value[key], (*path, key)))
        return result + [("}", "structure", path)]
    if type(value) is list:
        if not value:
            return [("[", "leaf", path), ("]", "leaf", path)]
        result = [("[", "structure", path)]
        for index, child in enumerate(value):
            if index:
                result.append((",", "structure", path))
            result.extend(_token_records(child, (*path, index)))
        return result + [("]", "structure", path)]
    return [(_raw(value).decode(), "leaf", path)]


def _varying_paths(rows):
    leaves = [_leaves(row["target"]) for row in rows]
    paths = set().union(*(row.keys() for row in leaves))
    # None tags an absent path; real JSON null is encoded as b"null".
    return sorted((list(path) for path in paths if len({
        _raw(row[path]) if path in row else None for row in leaves}) > 1), key=_raw)


def _same_leaf(actual, expected):
    if actual is _MISSING or expected is _MISSING:
        return actual is expected
    return _raw(actual) == _raw(expected)


def _config(options, parent):
    defaults = dict(strategy="semantic_v2", epochs=500, max_seconds=180., learning_rate=.003,
        batch_size=32, seed=1729, patience=30, max_optimizer_steps=None, reconstruction_weight=.1,
        max_target_tokens=512, validation_interval=5, semantic_weight=4.,
        constant_weight=1., structure_weight=.25, input_normalization="center_rms",
        embedding_provenance={"model_id": "caller_supplied", "verified_by_runtime": False})
    _require(options is None or type(options) is dict and set(options) <= set(defaults), "unknown training option")
    defaults.update(options or {})
    _require(defaults["strategy"] in ("reference_ce", "semantic_v2"), "unknown training strategy")
    _require(defaults["input_normalization"] in ("none", "center_rms"), "unknown input normalization")
    for name, low, high in (("epochs", 1, 2000), ("batch_size", 1, 256), ("seed", 0, 2**31-1),
                            ("patience", 0, 2000), ("max_target_tokens", 4, 1024), ("validation_interval", 1, 1000)):
        value = defaults[name]
        _require(type(value) is int and low <= value <= high, "invalid " + name)
    _require(defaults["max_optimizer_steps"] is None or type(defaults["max_optimizer_steps"]) is int
        and 1 <= defaults["max_optimizer_steps"] <= 1000000, "invalid optimizer step budget")
    for name, high in (("max_seconds", 3600), ("learning_rate", .1), ("reconstruction_weight", 100),
                       ("semantic_weight", 100), ("constant_weight", 100), ("structure_weight", 100)):
        value = defaults[name]
        _require(type(value) in (int, float) and math.isfinite(value) and 0 < value <= high, "invalid " + name)
    _require(type(defaults["embedding_provenance"]) is dict and len(_raw(defaults["embedding_provenance"])) <= 16384,
             "bounded embedding provenance required")
    return {**defaults, **{key: parent[key] for key in ("hidden_size", "token_embedding_dim", "projection_width")}}


def _transform(torch, rows, mode):
    data = torch.tensor([row["embedding"] for row in rows], dtype=torch.float32)
    if mode == "none":
        return {"mode": mode, "mean": [0.] * DIMENSION, "scale": 1., "origin": "training_only"}
    mean = data.mean(0)
    # One scale preserves angles and relative coordinate scales. A floor avoids
    # division by an almost-zero empirical spread in a degenerate corpus.
    scale = max(float((data - mean).square().sum(1).mean().sqrt()), .01)
    return {"mode": mode, "mean": mean.tolist(), "scale": scale, "origin": "training_only"}


def _encoded(torch, rows, vocabulary, varying_paths, config, transform):
    positions = {token: index for index, token in enumerate(vocabulary)}
    varying = {tuple(path) for path in varying_paths}
    encoded, weights = [], []
    for row in rows:
        records = _token_records(row["target"])
        _require(len(records) + 2 <= config["max_target_tokens"], "target exceeds configured token limit")
        _require(all(token in positions for token, _, _ in records), "target token outside training vocabulary")
        encoded.append([1] + [positions[token] for token, _, _ in records] + [2])
        weights.append([0.] + [1. if config["strategy"] == "reference_ce" else
            config["semantic_weight"] if role == "leaf" and path in varying else
            config["constant_weight"] if role == "leaf" else config["structure_weight"]
            for _, role, path in records] + [1.])
    width = max(map(len, encoded))
    labels = torch.tensor([row + [0] * (width-len(row)) for row in encoded], dtype=torch.long)
    weight = torch.tensor([row + [0.] * (width-len(row)) for row in weights], dtype=torch.float32)
    raw = torch.tensor([row["embedding"] for row in rows], dtype=torch.float32)
    normalized = (raw - torch.tensor(transform["mean"])) / transform["scale"]
    return normalized, labels, weight


def _loss(torch, model, data, labels, weights, config):
    projected, logits = model(data, labels[:, :-1])
    ce = torch.nn.functional.cross_entropy(logits.flatten(0, 1), labels[:, 1:].reshape(-1),
                                           ignore_index=0, reduction="none").reshape(labels.shape[0], -1)
    mask = labels[:, 1:] != 0
    token_ce = ce.sum() / mask.sum()
    weighted = (ce * weights[:, 1:]).sum() / weights[:, 1:].sum()
    # Report and optimize reconstruction in the original embedding coordinates.
    mse = (projected - data).square().mean() * config["_input_scale"]**2
    return weighted + config["reconstruction_weight"] * mse, token_ce, weighted, mse


def _greedy(torch, model, data, max_tokens):
    """One recurrent step per batch, with no target strings or candidate memory."""
    projected = model.project(data)
    hidden = model.start(projected)
    _require(bool(torch.isfinite(projected).all()), "nonfinite reconstructed embedding")
    current = torch.ones((len(data), 1), dtype=torch.long)
    active = torch.ones(len(data), dtype=torch.bool)
    sequences, ended = [[] for _ in range(len(data))], [False] * len(data)
    for _ in range(max_tokens - 1):
        logits, hidden = model.next_logits(current, hidden)
        _require(bool(torch.isfinite(logits).all()) and bool(torch.isfinite(hidden).all()), "nonfinite generated state")
        indices = logits[:, -1].argmax(-1)
        for index, token in enumerate(indices.tolist()):
            if not active[index]:
                continue
            if token == 2:
                ended[index] = True
                active[index] = False
            elif token in (0, 1):
                active[index] = False
            else:
                sequences[index].append(token)
        if not bool(active.any()):
            break
        current = indices.unsqueeze(1)
    return projected, sequences, ended


def _candidate(domain, indices, ended, vocabulary):
    tokens = [vocabulary[index] for index in indices]
    candidate, reason = None, None
    if ended:
        try:
            value = native._parse("".join(tokens))
            candidate = validate_target(domain, value)["canonical_ir"]
        except (ValueError, TypeError, KeyError, RecursionError) as exc:
            reason = str(exc)[:512]
    return candidate, tokens, reason


def _validation(torch, model, batch, rows, vocabulary, paths, domain, config):
    model.eval()
    with torch.inference_mode():
        objective, ce, weighted, mse = _loss(torch, model, *batch, config)
        _require(all(bool(torch.isfinite(value)) for value in (objective, ce, weighted, mse)), "nonfinite validation")
        _, sequences, ended = _greedy(torch, model, batch[0], config["max_target_tokens"])
    exact = valid = leaf_correct = leaf_count = 0
    for row, sequence, end in zip(rows, sequences, ended):
        candidate, _, _ = _candidate(domain, sequence, end, vocabulary)
        exact += candidate is not None and _raw(candidate) == _raw(row["target"])
        valid += candidate is not None
        actual = _leaves(candidate) if candidate is not None else {}
        gold = _leaves(row["target"])
        # Score train-derived varying paths, even when generation is malformed.
        for path in map(tuple, paths):
            leaf_count += 1
            leaf_correct += candidate is not None and _same_leaf(actual.get(path, _MISSING), gold.get(path, _MISSING))
    return dict(objective=float(objective), token_cross_entropy=float(ce), weighted_cross_entropy=float(weighted),
        embedding_mse=float(mse), exact_targets=int(exact), valid_candidates=int(valid), count=len(rows),
        semantic_leaf_correct=int(leaf_correct), semantic_leaf_count=leaf_count,
        semantic_leaf_accuracy=leaf_correct / max(leaf_count, 1),
        teacher_forcing_for_selection=True, free_running_metrics_teacher_forced=False,
        teacher_forcing_selection_role=("primary_objective" if config["strategy"] == "reference_ce" else "tertiary_tiebreaker"))


def _selection(observed, strategy):
    if strategy == "reference_ce":
        return (-observed["objective"],)
    return (observed["exact_targets"], observed["semantic_leaf_accuracy"], -observed["objective"])


def _parent(parent_projection):
    if type(parent_projection) is dict and set(parent_projection) == {"path", "sha256"}:
        path = Path(parent_projection["path"])
        _require(path.is_file() and 0 < path.stat().st_size <= MAX_BYTES, "bounded parent required")
        raw = path.read_bytes()
        _require(hashlib.sha256(raw).hexdigest() == parent_projection["sha256"], "parent hash differs")
        return native._parse(raw), parent_projection["sha256"], (path, raw)
    return deepcopy(parent_projection), digest(parent_projection), None


def _length_buckets(torch, lengths, batch_size, generator):
    # Shuffle before a stable length sort so identical target lengths never
    # retain source-order composition groups across epochs.
    order = torch.randperm(len(lengths), generator=generator)
    order = order[lengths[order].argsort(stable=True)]
    buckets = [order[offset:offset+batch_size] for offset in range(0, len(order), batch_size)]
    return [buckets[index] for index in torch.randperm(len(buckets), generator=generator).tolist()]


def train(domain, training_rows, validation_rows, *, parent_projection, config=None):
    """Train an isolated candidate; validation selects weights, no test API exists."""
    started = time.monotonic()
    parent, parent_sha, parent_file = _parent(parent_projection)
    training = _rows(domain, training_rows, training=True)
    validation = _rows(domain, validation_rows, training=True)
    for key in (lambda row: row["id"], lambda row: " ".join(row["source_text"].casefold().split()),
                lambda row: digest(row["embedding"])):
        _require(not {key(row) for row in training} & {key(row) for row in validation},
                 "training/validation identity, source, or embedding overlap")
    options = _config(config, parent["config"])
    paths = _varying_paths(training)
    vocabulary = [*native.SPECIAL, *sorted({token for row in training for token, _, _ in _token_records(row["target"])})]
    _require(len(vocabulary) <= 4096, "training vocabulary exceeds bound")
    codec = {"schema": "typed-json-lexical/v1", "target_vocabulary": vocabulary}
    with native._cpu() as torch:
        numerical.validate_checkpoint(parent)
        _require(parent["binding"]["dimension"] == DIMENSION and parent["progress"]["optimizer_steps"] > 0,
                 "trained 384D Legal parent required")
        transform = _transform(torch, training, options["input_normalization"])
        settings = {**options, "_input_scale": transform["scale"]}
        batch = _encoded(torch, training, vocabulary, paths, options, transform)
        tuning = _encoded(torch, validation, vocabulary, paths, options, transform)
        model, lineage = native._transfer(parent, codec, options)
        optimizer = torch.optim.Adam(model.parameters(), lr=options["learning_rate"])
        before = _validation(torch, model, tuning, validation, vocabulary, paths, domain, settings)
        best, best_state = before, deepcopy(model.state_dict())
        selected_epoch = selected_steps = steps = examples_seen = tokens_seen = stale = last_validated_steps = 0
        selected_epoch_complete = True
        optimizer_seconds = validation_seconds = 0.
        history, stop = [], "epoch_budget"
        generator = torch.Generator().manual_seed(options["seed"])
        lengths = (batch[1] != 0).sum(1)
        fit_started = time.monotonic()
        for epoch in range(1, options["epochs"] + 1):
            model.train()
            completed = True
            for index in _length_buckets(torch, lengths, options["batch_size"], generator):
                if options["max_optimizer_steps"] is not None and steps >= options["max_optimizer_steps"]:
                    completed, stop = False, "optimizer_step_budget"
                    break
                if time.monotonic() - fit_started >= options["max_seconds"]:
                    completed, stop = False, "deadline"
                    break
                tick = time.monotonic()
                width = int((batch[1][index] != 0).sum(1).max())
                values = (batch[0][index], batch[1][index, :width], batch[2][index, :width])
                optimizer.zero_grad(set_to_none=True)
                loss, _, _, _ = _loss(torch, model, *values, settings)
                _require(bool(torch.isfinite(loss)), "nonfinite training objective")
                loss.backward()
                norm = torch.nn.utils.clip_grad_norm_(model.parameters(), 5.)
                _require(bool(torch.isfinite(norm)), "nonfinite gradient")
                optimizer.step()
                optimizer_seconds += time.monotonic() - tick
                steps += 1
                examples_seen += len(index)
                tokens_seen += int((values[1][:, 1:] != 0).sum())
            if not completed and steps == last_validated_steps:
                break
            reached_steps = options["max_optimizer_steps"] is not None and steps >= options["max_optimizer_steps"]
            if completed and epoch % options["validation_interval"] and epoch != options["epochs"] and not reached_steps:
                continue
            tick = time.monotonic()
            observed = _validation(torch, model, tuning, validation, vocabulary, paths, domain, settings)
            validation_seconds += time.monotonic() - tick
            last_validated_steps = steps
            # A final tuning pass can finish after the optimizer deadline. The
            # actual elapsed time includes it; every selected state was checked.
            selected = _selection(observed, options["strategy"]) > _selection(best, options["strategy"])
            if selected:
                best, best_state, selected_epoch, stale = observed, deepcopy(model.state_dict()), epoch, 0
                selected_steps, selected_epoch_complete = steps, completed
            else:
                stale += 1
            history.append({"epoch": epoch, "epoch_complete": completed, "optimizer_steps": steps, **observed, "selected": selected})
            if not completed:
                break
            if reached_steps:
                stop = "optimizer_step_budget"
                break
            if options["patience"] and stale >= options["patience"]:
                stop = "validation_patience"
                break
            if time.monotonic() - fit_started >= options["max_seconds"]:
                stop = "deadline"
                break
        _require(steps > 0, "no training steps completed")
        fit_seconds = time.monotonic() - fit_started
        model.load_state_dict(best_state)
        weights = {name: tensor.detach().tolist() for name, tensor in model.state_dict().items()}
        def manifest(rows):
            return [{"id": row["id"], "source_sha256": hashlib.sha256(row["source_text"].encode()).hexdigest(),
                     "normalized_source_sha256": hashlib.sha256(" ".join(row["source_text"].casefold().split()).encode()).hexdigest(),
                     "embedding_sha256": digest(row["embedding"]), "target_sha256": digest(row["target"])} for row in rows]
        metrics = dict(before_validation=before, selected_validation=best, selected_epoch=selected_epoch,
            optimizer_steps=steps, selected_optimizer_steps=selected_steps, selected_epoch_complete=selected_epoch_complete,
            examples_seen=examples_seen, training_tokens=tokens_seen,
            optimizer_seconds=optimizer_seconds, validation_seconds=validation_seconds, fit_seconds=fit_seconds,
            optimizer_tokens_per_second=tokens_seen/max(optimizer_seconds, 1e-9),
            optimizer_examples_per_second=examples_seen/max(optimizer_seconds, 1e-9),
            fit_tokens_per_second=tokens_seen/max(fit_seconds, 1e-9),
            fit_examples_per_second=examples_seen/max(fit_seconds, 1e-9),
            pre_checkpoint_seconds=time.monotonic()-started, stopped_reason=stop, history=history,
            test_used_for_selection=False, selection=("weighted_teacher_forced_objective" if options["strategy"] == "reference_ce"
                else "free_running_exact_then_train_variable_leaves_then_weighted_objective"))
        checkpoint = dict(schema=SCHEMA, domain_id=domain, dimension=DIMENSION, architecture=numerical.ARCHITECTURE,
            codec=codec, config=options, implementation=_implementation(), parent_sha256=parent_sha,
            parent_binding=deepcopy(parent["binding"]), lineage=lineage, model_state=weights,
            weights_sha256=digest(weights), input_transform=transform, semantic_paths=paths,
            training_manifest=manifest(training), validation_manifest=manifest(validation), training=metrics, **FALSE)
        _require(len(_raw(checkpoint)) <= MAX_BYTES, "checkpoint exceeds bound")
        if parent_file:
            _require(parent_file[0].read_bytes() == parent_file[1], "parent changed during training")
        Runtime(checkpoint)
        return {"checkpoint": checkpoint, "metrics": deepcopy(metrics)}


class Runtime:
    """Frozen shared numerical inference without target access or source parsing."""
    def __init__(self, checkpoint):
        fields = {"schema", "domain_id", "dimension", "architecture", "codec", "config", "implementation",
            "parent_sha256", "parent_binding", "lineage", "model_state", "weights_sha256", "input_transform",
            "semantic_paths", "training_manifest", "validation_manifest", "training", *FALSE}
        _require(type(checkpoint) is dict and set(checkpoint) == fields and checkpoint["schema"] == SCHEMA,
                 "closed source v2 checkpoint required")
        _require(len(_raw(checkpoint)) <= MAX_BYTES, "checkpoint exceeds bound")
        _require(checkpoint["domain_id"] in DOMAINS and type(checkpoint["dimension"]) is int and checkpoint["dimension"] == DIMENSION,
                 "checkpoint requires genuine 384D domain")
        _require(all(checkpoint[key] is False for key in FALSE), "checkpoint cannot grant authority")
        _require(checkpoint["implementation"] == _implementation(), "implementation pins differ")
        _require(checkpoint["architecture"] == numerical.ARCHITECTURE, "architecture differs")
        config = checkpoint["config"]
        shape = {name: config[name] for name in ("hidden_size", "token_embedding_dim", "projection_width")}
        for name, low, high in (("hidden_size", 8, 128), ("token_embedding_dim", 8, 64), ("projection_width", 1, 64)):
            _require(type(shape[name]) is int and low <= shape[name] <= high, "invalid model shape")
        _require(_config({key: value for key, value in config.items() if key not in shape}, shape) == config,
                 "configuration differs")
        codec = checkpoint["codec"]
        _require(type(codec) is dict and set(codec) == {"schema", "target_vocabulary"} and codec["schema"] == "typed-json-lexical/v1", "invalid codec")
        vocabulary = codec["target_vocabulary"]
        _require(type(vocabulary) is list and 4 <= len(vocabulary) <= 4096 and vocabulary[:3] == list(native.SPECIAL)
            and all(type(token) is str and len(token) <= 16384 and native._TOKEN.fullmatch(token) for token in vocabulary[3:])
            and vocabulary[3:] == sorted(set(vocabulary[3:])), "invalid training vocabulary")
        _require(digest(checkpoint["model_state"]) == checkpoint["weights_sha256"], "weight digest differs")
        transform = checkpoint["input_transform"]
        _require(type(transform) is dict and set(transform) == {"mode", "mean", "scale", "origin"}
            and transform["mode"] == config["input_normalization"] and transform["origin"] == "training_only", "invalid input transform")
        native._vector(transform["mean"])
        _require(type(transform["scale"]) in (int, float) and math.isfinite(transform["scale"]) and .01 <= transform["scale"] <= 1e8,
                 "invalid input scale")
        if transform["mode"] == "none":
            _require(transform["mean"] == [0.]*DIMENSION and transform["scale"] == 1., "identity transform differs")
        paths = checkpoint["semantic_paths"]
        _require(type(paths) is list and len(paths) <= 4096 and all(type(path) is list and len(path) <= 128
            and all(type(part) in (int, str) for part in path) for path in paths)
            and paths == sorted(paths, key=_raw) and len({_raw(path) for path in paths}) == len(paths), "invalid semantic paths")
        for name in ("training_manifest", "validation_manifest"):
            rows = checkpoint[name]
            _require(type(rows) is list and 1 <= len(rows) <= 4096, "invalid split manifest")
            _require(all(type(row) is dict and set(row) == {"id", "source_sha256", "normalized_source_sha256", "embedding_sha256", "target_sha256"}
                and type(row["id"]) is str and 0 < len(row["id"]) <= 256
                and all(type(row[key]) is str and native._SHA.fullmatch(row[key]) for key in row if key != "id") for row in rows), "invalid split row")
            _require(len({row["id"] for row in rows}) == len(rows), "duplicate split ID")
        for key in ("id", "source_sha256", "normalized_source_sha256", "embedding_sha256"):
            _require(not {row[key] for row in checkpoint["training_manifest"]} & {row[key] for row in checkpoint["validation_manifest"]}, "checkpoint split overlap")
        training = checkpoint["training"]
        _require(type(training) is dict and type(training.get("optimizer_steps")) is int and training["optimizer_steps"] > 0
            and type(training.get("selected_epoch")) is int and 0 <= training["selected_epoch"] <= config["epochs"]
            and training.get("test_used_for_selection") is False, "invalid training provenance")
        _require(type(checkpoint["parent_sha256"]) is str and native._SHA.fullmatch(checkpoint["parent_sha256"])
            and type(checkpoint["parent_binding"]) is dict and checkpoint["parent_binding"].get("dimension") == DIMENSION,
            "invalid parent binding")
        with native._cpu():
            model = numerical._model({"dimension": DIMENSION}, codec, config)
            state = checkpoint["model_state"]
            _require(type(state) is dict and set(state) == set(model.state_dict()), "model tensor names differ")
            model.load_state_dict({name: numerical._tensor(state[name], template, name)
                for name, template in model.state_dict().items()}, strict=True)
        self.checkpoint, self.model = deepcopy(checkpoint), model.eval()

    def describe(self):
        return dict(schema=SCHEMA, domain_id=self.checkpoint["domain_id"], dimension=DIMENSION,
            weights_sha256=self.checkpoint["weights_sha256"], strategy=self.checkpoint["config"]["strategy"],
            source_text_is_neural_input=False, input_representation="source_embedding_384",
            sample_memory_used=False, independent_source_fidelity_check_required=True,
            zero_projection_ablation="zero_residual_branch_identity_embedding_retained", **FALSE)

    def infer(self, rows, *, weight_ablation=None):
        rows = _rows(self.checkpoint["domain_id"], rows, training=False)
        _require(weight_ablation in (None, "zero_projection", "zero_condition", "zero_decoder"), "unknown weight ablation")
        model = self.model if weight_ablation is None else deepcopy(self.model)
        config, transform = self.checkpoint["config"], self.checkpoint["input_transform"]
        vocabulary = self.checkpoint["codec"]["target_vocabulary"]
        reports = []
        with native._cpu() as torch, torch.inference_mode():
            if weight_ablation:
                for name, parameter in model.named_parameters():
                    if (weight_ablation == "zero_projection" and name.startswith("projection_")) or (
                        weight_ablation == "zero_condition" and name.startswith("condition.")) or (
                        weight_ablation == "zero_decoder" and name.startswith(("decoder.", "output."))):
                        parameter.zero_()
            for offset in range(0, len(rows), config["batch_size"]):
                part = rows[offset:offset+config["batch_size"]]
                raw = torch.tensor([row["embedding"] for row in part], dtype=torch.float32)
                data = (raw - torch.tensor(transform["mean"])) / transform["scale"]
                projected, sequences, ended = _greedy(torch, model, data, config["max_target_tokens"])
                reconstructed = projected * transform["scale"] + torch.tensor(transform["mean"])
                for row, sequence, end, embedding in zip(part, sequences, ended, reconstructed):
                    candidate, tokens, reason = _candidate(self.checkpoint["domain_id"], sequence, end, vocabulary)
                    reports.append(dict(id=row["id"], source_sha256=hashlib.sha256(row["source_text"].encode()).hexdigest(),
                        status="unqualified_candidate" if candidate is not None else "fail_open_invalid_output", reason=reason,
                        candidate_ir=candidate, generated_tokens=tokens, ended=end, reconstructed_embedding=embedding.tolist(),
                        weight_ablation=weight_ablation, weights_sha256=self.checkpoint["weights_sha256"],
                        target_access=False, teacher_forcing=False, continue_planning=True, **FALSE))
        return dict(schema=SCHEMA, domain_id=self.checkpoint["domain_id"], dimension=DIMENSION, rows=reports, **FALSE)


def evaluate(checkpoint, rows):
    gold = _rows(checkpoint["domain_id"], rows, training=True)
    report = Runtime(checkpoint).infer([{key: row[key] for key in ("id", "source_text", "embedding")} for row in gold])
    correct = total = 0
    for actual, expected in zip(report["rows"], gold):
        actual["exact_target"] = actual["candidate_ir"] is not None and _raw(actual["candidate_ir"]) == _raw(expected["target"])
        leaves = _leaves(actual["candidate_ir"]) if actual["candidate_ir"] is not None else {}
        targets = _leaves(expected["target"])
        for path in map(tuple, checkpoint["semantic_paths"]):
            total += 1
            correct += actual["candidate_ir"] is not None and _same_leaf(leaves.get(path, _MISSING), targets.get(path, _MISSING))
    return {**report, "exact_targets": sum(row["exact_target"] for row in report["rows"]),
        "valid_candidates": sum(row["candidate_ir"] is not None for row in report["rows"]),
        "count": len(gold), "semantic_leaf_correct": correct, "semantic_leaf_count": total,
        "semantic_leaf_accuracy": correct/max(total, 1)}


def load_checkpoint(path, *, expected_sha256, expected_domain):
    path = Path(path)
    _require(path.is_file() and not path.is_symlink() and 0 < path.stat().st_size <= MAX_BYTES, "bounded regular checkpoint required")
    raw = path.read_bytes()
    _require(hashlib.sha256(raw).hexdigest() == expected_sha256, "checkpoint bytes differ")
    checkpoint = native._parse(raw)
    _require(type(checkpoint) is dict and checkpoint.get("domain_id") == expected_domain, "checkpoint belongs to another domain")
    return Runtime(checkpoint)


__all__ = ["SCHEMA", "DOMAINS", "DIMENSION", "train", "Runtime", "evaluate", "load_checkpoint", "validate_target"]
