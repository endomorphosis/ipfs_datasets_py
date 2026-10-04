"""Experimental source-embedding conditioned native IR decoding at 384 dimensions.

Reuses modal_latent_formula's residual projection, conditioning layer and GRU.
A trained Legal checkpoint supplies every recurrent/projection tensor. New
target-token rows receive trained parent lexical means, never random weights.

Generated documents and fragments remain unqualified candidates. Native shape
validation establishes neither source fidelity nor proof correctness.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import fields
import hashlib
import json
import math
from pathlib import Path
import re
import threading
import time

SCHEMA = "domain-384-typed-autoencoder/v1"
DIMENSION = 384
DOMAINS = ("intent_ir", "security_ir", "ui_ux_ir")
MAX_BYTES = 48 * 1024 * 1024
SPECIAL = ("<pad>", "<bos>", "<eos>")
FALSE = {
    "qualified": False,
    "admitted": False,
    "proof_authority": False,
    "source_semantics_verified": False,
    "publication_performed": False,
}
_TOKEN = re.compile(
    r'"(?:[^"\\\x00-\x1f]|\\(?:["\\/bfnrt]|u[0-9a-fA-F]{4}))*"'
    r'|-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?'
    r'|true|false|null|[{}\[\],:]'
)
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_CPU_LOCK = threading.RLock()


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _raw(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=True, allow_nan=False,
    ).encode()


def digest(value):
    return hashlib.sha256(_raw(value)).hexdigest()


def _parse(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            _require(key not in result, "duplicate JSON key")
            result[key] = value
        return result

    def invalid(_):
        raise ValueError("nonfinite JSON value")

    return json.loads(raw, object_pairs_hook=unique, parse_constant=invalid)


def _preserved(original, native):
    """Reject fields silently dropped or coerced by permissive native loaders."""
    if type(original) is dict:
        return (
            type(native) is dict
            and all(k in native and _preserved(v, native[k])
                    for k, v in original.items())
        )
    if type(original) is list:
        return (
            type(native) is list
            and len(original) == len(native)
            and all(_preserved(a, b) for a, b in zip(original, native))
        )
    return type(original) is type(native) and original == native


def validate_target(domain, target):
    """Validate a compact native document or explicitly named native fragment.

    Supported fragment wrappers are ``{kind, document}`` with kinds
    ``intent_rich_ast``, ``program_expression`` or ``ui_component``.

    ProgramExpression validation is local: references still require a complete
    ProgramIR to establish referential and type correctness. Missing defaults
    may be omitted; supplied fields must survive the native loader exactly.
    """
    _require(
        domain in DOMAINS and type(target) is dict,
        "supported domain and typed target required",
    )
    _require(len(_raw(target)) <= 128 * 1024, "target exceeds bound")
    kind, document = "document", target
    if set(target) == {"kind", "document"}:
        kind, document = target["kind"], target["document"]
        _require(type(document) is dict, "fragment document must be an object")

    if domain == "intent_ir":
        if kind == "intent_rich_ast":
            from ...logic.intent_ir.formalize.rich_grammar import validate_ast
            native = deepcopy(validate_ast(document))
        else:
            _require(kind == "document", "unsupported Intent fragment")
            from ...logic.intent_ir.decoder import decode_intent_ir
            native = decode_intent_ir(document).to_dict()
    elif domain == "security_ir":
        if kind == "program_expression":
            from ...logic.software_verification.program import ProgramExpression
            native = ProgramExpression.from_dict(document).to_dict()
        else:
            _require(kind == "document", "unsupported Security fragment")
            from ...logic.security_ir.model import SecurityIR
            native = SecurityIR.from_dict(document).to_dict()
    else:
        if kind == "ui_component":
            from ...logic.ui_ux_ir.schema import UIComponent
            _require(
                set(document) <= {field.name for field in fields(UIComponent)},
                "unknown UI component field",
            )
            values = deepcopy(document)
            for key, value in tuple(values.items()):
                if key.endswith("_ids"):
                    _require(type(value) is list, "UI ID arrays must be lists")
                    values[key] = tuple(value)
            component = UIComponent(**values)
            component.validate()
            native = component.to_dict()
        else:
            _require(kind == "document", "unsupported UI fragment")
            from ...logic.ui_ux_ir.decoder import decode_ui_ir
            native = decode_ui_ir(document).to_dict()

    _require(
        _preserved(document, native),
        "native decoder dropped, reordered, or coerced target fields",
    )
    return {
        "valid": True,
        "domain_id": domain,
        "kind": kind,
        "canonical_ir": _parse(_raw(target)),
        "native_ir": native,
        "scope": (
            "native_document" if kind == "document"
            else "locally_validated_native_fragment"
        ),
        **FALSE,
    }


def _implementation():
    from . import modal_latent_formula
    from ...logic.intent_ir import decoder as intent_decoder, schema as intent_schema
    from ...logic.intent_ir.formalize import rich_grammar
    from ...logic.security_ir import model as security_model
    from ...logic.software_verification import program
    from ...logic.ui_ux_ir import decoder as ui_decoder, schema as ui_schema

    modules = (
        modal_latent_formula, intent_decoder, intent_schema, rich_grammar,
        security_model, program, ui_decoder, ui_schema,
    )
    return {
        "runtime": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "dependencies": {
            module.__name__: hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
            for module in modules
        },
        "scope": "listed_numerical_and_native_validator_modules_only",
    }


@contextmanager
def _cpu():
    """Serialize this runtime's thread-count changes and restore caller state."""
    import torch
    with _CPU_LOCK:
        previous = torch.get_num_threads()
        torch.set_num_threads(1)
        try:
            yield torch
        finally:
            torch.set_num_threads(previous)


def _vector(value):
    _require(
        type(value) is list
        and len(value) == DIMENSION
        and all(
            type(number) in (int, float)
            and math.isfinite(number)
            and abs(number) <= 1e6
            for number in value
        ),
        "embedding must contain exactly 384 bounded finite numbers",
    )


def _rows(domain, rows, *, training):
    _require(
        type(rows) is list and 1 <= len(rows) <= 4096,
        "bounded nonempty rows required",
    )
    expected = {"id", "source_text", "embedding"} | (
        {"target"} if training else set()
    )
    seen = set()
    for row in rows:
        _require(
            type(row) is dict and set(row) == expected,
            "closed domain row schema required",
        )
        _require(
            type(row["id"]) is str
            and 0 < len(row["id"]) <= 256
            and row["id"] not in seen,
            "unique bounded row ID required",
        )
        _require(
            type(row["source_text"]) is str
            and 0 < len(row["source_text"]) <= 16384
            and row["source_text"].strip(),
            "bounded nonempty source provenance required",
        )
        _vector(row["embedding"])
        if training:
            validate_target(domain, row["target"])
        seen.add(row["id"])
    return deepcopy(rows)


def _tokens(target):
    raw = _raw(target).decode()
    pieces = _TOKEN.findall(raw)
    _require(
        "".join(pieces) == raw and len(pieces) <= 1022,
        "bounded JSON lexical target required",
    )
    return pieces


def _config(options, parent_config):
    defaults = {
        "epochs": 80,
        "max_seconds": 180.0,
        "learning_rate": .003,
        "batch_size": 8,
        "seed": 1729,
        "patience": 12,
        "reconstruction_weight": .1,
        "max_target_tokens": 512,
        "embedding_provenance": {
            "model_id": "caller_supplied",
            "verified_by_runtime": False,
        },
    }
    _require(
        options is None
        or type(options) is dict and set(options) <= set(defaults),
        "unknown training option",
    )
    defaults.update(options or {})
    for name, high in (
        ("epochs", 1000), ("batch_size", 64), ("seed", 2**31 - 1),
        ("patience", 1000), ("max_target_tokens", 1024),
    ):
        value = defaults[name]
        _require(
            type(value) is int
            and (0 if name == "seed" else 1) <= value <= high,
            "invalid " + name,
        )
    for name, high in (
        ("max_seconds", 3600),
        ("learning_rate", .1),
        ("reconstruction_weight", 100),
    ):
        value = defaults[name]
        _require(
            type(value) in (int, float)
            and math.isfinite(value)
            and 0 < value <= high,
            "invalid " + name,
        )
    _require(
        type(defaults["embedding_provenance"]) is dict
        and len(_raw(defaults["embedding_provenance"])) <= 16384,
        "bounded embedding provenance required",
    )
    return {
        **defaults,
        **{
            name: parent_config[name]
            for name in ("hidden_size", "token_embedding_dim", "projection_width")
        },
    }


def _transfer(parent, codec, config):
    from . import modal_latent_formula as numerical
    import torch

    model = numerical._model({"dimension": DIMENSION}, codec, config)
    prior = parent["model_state"]
    old_vocab = parent["codec"]["target_vocabulary"]
    positions = {token: index for index, token in enumerate(old_vocab)}
    lexical = {"target_embedding.weight", "output.weight", "output.bias"}
    transferred, inherited, mapped = {}, [], []
    for name, template in model.state_dict().items():
        _require(name in prior, "parent is missing numerical tensor " + name)
        value = torch.tensor(prior[name], dtype=torch.float32)
        _require(bool(torch.isfinite(value).all()), "nonfinite parent tensor")
        if name in lexical:
            _require(
                value.shape[0] == len(old_vocab)
                and value.shape[1:] == template.shape[1:],
                "parent lexical shape differs",
            )
            mean = value.mean(0)
            value = torch.stack([
                value[positions[token]] if token in positions else mean
                for token in codec["target_vocabulary"]
            ])
            mapped.append(name)
        else:
            _require(value.shape == template.shape, "parent architecture differs")
            inherited.append(name)
        transferred[name] = value
    model.load_state_dict(transferred, strict=True)
    return model, {
        "exact_inherited_tensors": sorted(inherited),
        "lexical_mapped_tensors": sorted(mapped),
        "new_token_initialization": "trained_parent_lexical_row_mean",
        "random_parameters_used": False,
        "parent_modified": False,
        "initial_state_sha256": digest({
            name: tensor.tolist() for name, tensor in transferred.items()
        }),
    }


def _batch(torch, rows, vocabulary, max_tokens):
    positions = {token: index for index, token in enumerate(vocabulary)}
    encoded = []
    for row in rows:
        tokens = _tokens(row["target"])
        _require(
            len(tokens) + 2 <= max_tokens,
            "target exceeds configured token limit",
        )
        missing = sorted(set(tokens) - set(positions))
        _require(
            not missing,
            "target token outside training vocabulary: " + str(missing[:3]),
        )
        encoded.append([1] + [positions[token] for token in tokens] + [2])
    width = max(map(len, encoded))
    return (
        torch.tensor([row["embedding"] for row in rows], dtype=torch.float32),
        torch.tensor([
            row + [0] * (width - len(row)) for row in encoded
        ], dtype=torch.long),
    )


def _loss(torch, model, data, targets, config):
    projected, logits = model(data, targets[:, :-1])
    ce = torch.nn.functional.cross_entropy(
        logits.reshape(-1, logits.shape[-1]),
        targets[:, 1:].reshape(-1),
        ignore_index=0,
    )
    mse = torch.nn.functional.mse_loss(projected, data)
    return ce + config["reconstruction_weight"] * mse, ce, mse


def _metrics(torch, model, batch, config):
    with torch.inference_mode():
        loss, ce, mse = _loss(torch, model, *batch, config)
    _require(
        all(bool(torch.isfinite(value)) for value in (loss, ce, mse)),
        "nonfinite evaluation",
    )
    return {
        "objective": float(loss),
        "token_cross_entropy": float(ce),
        "embedding_mse": float(mse),
    }


def train(domain, training_rows, validation_rows, *, parent_projection, config=None):
    """Fork a trained Legal 384D projection into a distinct domain checkpoint.

    parent_projection is a complete modal-latent-formula checkpoint or its
    {path, sha256} descriptor. Only embeddings condition the neural decoder.
    Validation selects weights; test examples never enter this API.
    """
    from . import modal_latent_formula as numerical

    original_parent = None
    if type(parent_projection) is dict and set(parent_projection) == {"path", "sha256"}:
        parent_path = Path(parent_projection["path"])
        _require(
            parent_path.is_file() and parent_path.stat().st_size <= MAX_BYTES,
            "bounded parent file required",
        )
        original_parent = parent_path.read_bytes()
        _require(
            hashlib.sha256(original_parent).hexdigest() == parent_projection["sha256"],
            "parent hash differs",
        )
        parent = _parse(original_parent)
        parent_sha = parent_projection["sha256"]
    else:
        parent = deepcopy(parent_projection)
        parent_sha = digest(parent)

    with _cpu() as torch:
        numerical.validate_checkpoint(parent)
        _require(
            parent["binding"]["dimension"] == DIMENSION
            and parent["progress"]["optimizer_steps"] > 0,
            "trained 384D Legal parent required",
        )
        train_rows = _rows(domain, training_rows, training=True)
        validation = _rows(domain, validation_rows, training=True)
        keys = (
            lambda row: row["id"],
            lambda row: " ".join(row["source_text"].casefold().split()),
            lambda row: digest(row["embedding"]),
        )
        for key in keys:
            _require(
                not {key(row) for row in train_rows}
                & {key(row) for row in validation},
                "training/validation identity, source, or embedding overlap",
            )

        options = _config(config, parent["config"])
        vocabulary = [
            *SPECIAL,
            *sorted({
                token
                for row in train_rows
                for token in _tokens(row["target"])
            }),
        ]
        _require(len(vocabulary) <= 4096, "training vocabulary exceeds bound")
        codec = {
            "schema": "typed-json-lexical/v1",
            "target_vocabulary": vocabulary,
        }
        data, labels = _batch(
            torch, train_rows, vocabulary, options["max_target_tokens"]
        )
        validation_batch = _batch(
            torch, validation, vocabulary, options["max_target_tokens"]
        )
        model, lineage = _transfer(parent, codec, options)
        optimizer = torch.optim.Adam(
            model.parameters(), lr=options["learning_rate"]
        )
        before = _metrics(torch, model, validation_batch, options)
        best, best_state, selected_epoch = before, deepcopy(model.state_dict()), 0
        generator = torch.Generator().manual_seed(options["seed"])
        started = time.monotonic()
        steps = seen_tokens = examples_seen = stale = 0
        optimizer_seconds = validation_seconds = 0.0
        history, stop = [], "epoch_budget"

        for epoch in range(options["epochs"]):
            model.train()
            order = torch.randperm(len(train_rows), generator=generator)
            complete = True
            for offset in range(0, len(train_rows), options["batch_size"]):
                if time.monotonic() - started >= options["max_seconds"]:
                    complete, stop = False, "deadline"
                    break
                step_started = time.monotonic()
                index = order[offset:offset + options["batch_size"]]
                batch_target = labels[index]
                width = int((batch_target != 0).sum(1).max())
                batch_target = batch_target[:, :width]
                optimizer.zero_grad(set_to_none=True)
                loss, _, _ = _loss(
                    torch, model, data[index], batch_target, options
                )
                _require(bool(torch.isfinite(loss)), "nonfinite training loss")
                loss.backward()
                norm = torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0)
                _require(bool(torch.isfinite(norm)), "nonfinite gradient")
                optimizer.step()
                optimizer_seconds += time.monotonic() - step_started
                steps += 1
                examples_seen += len(index)
                seen_tokens += int((batch_target[:, 1:] != 0).sum())
            if not complete:
                break

            validation_started = time.monotonic()
            observed = _metrics(torch, model, validation_batch, options)
            validation_seconds += time.monotonic() - validation_started
            # A deadline-truncated epoch cannot become the selected checkpoint.
            selected = (
                time.monotonic() - started < options["max_seconds"]
                and observed["objective"] < best["objective"]
            )
            if selected:
                best = observed
                best_state = deepcopy(model.state_dict())
                selected_epoch, stale = epoch + 1, 0
            else:
                stale += 1
            history.append({
                "epoch": epoch + 1, **observed, "selected": selected,
            })
            if stale >= options["patience"]:
                stop = "validation_patience"
                break
            if time.monotonic() - started >= options["max_seconds"]:
                stop = "deadline"
                break

        elapsed = time.monotonic() - started
        _require(steps > 0, "no training steps completed")
        model.load_state_dict(best_state)
        weights = {
            name: tensor.detach().tolist()
            for name, tensor in model.state_dict().items()
        }

        def manifest(rows):
            return [{
                "id": row["id"],
                "source_sha256": hashlib.sha256(row["source_text"].encode()).hexdigest(),
                "embedding_sha256": digest(row["embedding"]),
                "target_sha256": digest(row["target"]),
            } for row in rows]

        metrics = {
            "before_validation": before,
            "selected_validation": best,
            "selected_epoch": selected_epoch,
            "optimizer_steps": steps,
            "training_tokens": seen_tokens,
            "examples_seen": examples_seen,
            "optimizer_seconds": optimizer_seconds,
            "validation_seconds": validation_seconds,
            "fit_seconds": elapsed,
            "optimizer_tokens_per_second": seen_tokens / max(optimizer_seconds, 1e-9),
            "optimizer_examples_per_second": examples_seen / max(optimizer_seconds, 1e-9),
            "fit_tokens_per_second": seen_tokens / max(elapsed, 1e-9),
            "stopped_reason": stop,
            "history": history,
            "test_used_for_selection": False,
            "training": _metrics(torch, model, (data, labels), options),
        }
        checkpoint = {
            "schema": SCHEMA,
            "domain_id": domain,
            "dimension": DIMENSION,
            "architecture": numerical.ARCHITECTURE,
            "codec": codec,
            "config": options,
            "implementation": _implementation(),
            "parent_sha256": parent_sha,
            "parent_binding": deepcopy(parent["binding"]),
            "lineage": lineage,
            "model_state": weights,
            "weights_sha256": digest(weights),
            "training_manifest": manifest(train_rows),
            "validation_manifest": manifest(validation),
            "training": metrics,
            **FALSE,
        }
        _require(len(_raw(checkpoint)) <= MAX_BYTES, "checkpoint exceeds bound")
        if original_parent is not None:
            _require(
                parent_path.read_bytes() == original_parent,
                "parent changed during training",
            )
        Runtime(checkpoint)
        return {"checkpoint": checkpoint, "metrics": deepcopy(metrics)}


class Runtime:
    """Inference consumes source embeddings; gold targets are never accepted."""

    def __init__(self, checkpoint):
        from . import modal_latent_formula as numerical

        required = {
            "schema", "domain_id", "dimension", "architecture", "codec", "config",
            "implementation", "parent_sha256", "parent_binding", "lineage",
            "model_state", "weights_sha256", "training_manifest",
            "validation_manifest", "training", *FALSE,
        }
        _require(
            type(checkpoint) is dict
            and set(checkpoint) == required
            and checkpoint["schema"] == SCHEMA,
            "closed domain checkpoint required",
        )
        _require(len(_raw(checkpoint)) <= MAX_BYTES, "checkpoint exceeds bound")
        _require(
            checkpoint["domain_id"] in DOMAINS
            and type(checkpoint["dimension"]) is int
            and checkpoint["dimension"] == DIMENSION,
            "checkpoint requires genuine 384D domain binding",
        )
        _require(
            all(checkpoint[key] is False for key in FALSE),
            "checkpoint cannot grant authority",
        )
        _require(
            checkpoint["implementation"] == _implementation(),
            "domain implementation pins differ",
        )
        _require(
            checkpoint["architecture"] == numerical.ARCHITECTURE,
            "numerical architecture differs",
        )
        _require(
            type(checkpoint["parent_binding"]) is dict
            and checkpoint["parent_binding"].get("dimension") == DIMENSION
            and type(checkpoint["parent_sha256"]) is str
            and _SHA.fullmatch(checkpoint["parent_sha256"]),
            "invalid parent binding",
        )
        codec = checkpoint["codec"]
        _require(
            type(codec) is dict
            and set(codec) == {"schema", "target_vocabulary"}
            and codec["schema"] == "typed-json-lexical/v1",
            "invalid target codec",
        )
        vocabulary = codec["target_vocabulary"]
        _require(
            type(vocabulary) is list
            and 4 <= len(vocabulary) <= 4096
            and vocabulary[:3] == list(SPECIAL)
            and all(type(token) is str and 0 < len(token) <= 16384 for token in vocabulary)
            and vocabulary[3:] == sorted(set(vocabulary[3:]))
            and not set(vocabulary[3:]) & set(SPECIAL),
            "invalid training vocabulary",
        )
        _require(
            all(_TOKEN.fullmatch(token) is not None for token in vocabulary[3:]),
            "invalid JSON vocabulary token",
        )
        config = checkpoint["config"]
        config_fields = {
            "epochs", "max_seconds", "learning_rate", "batch_size", "seed",
            "patience", "reconstruction_weight", "max_target_tokens",
            "embedding_provenance", "hidden_size", "token_embedding_dim",
            "projection_width",
        }
        _require(
            type(config) is dict and set(config) == config_fields,
            "closed model configuration required",
        )
        for key, low, high in (
            ("hidden_size", 8, 128),
            ("token_embedding_dim", 8, 64),
            ("projection_width", 1, 64),
        ):
            _require(
                type(config[key]) is int and low <= config[key] <= high,
                "invalid model shape",
            )
        options = {
            key: value for key, value in config.items()
            if key not in {"hidden_size", "token_embedding_dim", "projection_width"}
        }
        _require(_config(options, config) == config, "configuration differs")
        _require(
            digest(checkpoint["model_state"]) == checkpoint["weights_sha256"],
            "weight digest differs",
        )
        training = checkpoint["training"]
        _require(
            type(training) is dict
            and type(training.get("optimizer_steps")) is int
            and training["optimizer_steps"] > 0
            and type(training.get("selected_epoch")) is int
            and 0 <= training["selected_epoch"] <= config["epochs"]
            and training.get("test_used_for_selection") is False,
            "invalid training provenance",
        )
        for name in ("training_manifest", "validation_manifest"):
            rows = checkpoint[name]
            _require(
                type(rows) is list and 1 <= len(rows) <= 4096,
                "invalid split manifest",
            )
            seen = set()
            for row in rows:
                _require(
                    type(row) is dict
                    and set(row) == {
                        "id", "source_sha256", "embedding_sha256", "target_sha256"
                    }
                    and type(row["id"]) is str
                    and 0 < len(row["id"]) <= 256
                    and row["id"] not in seen,
                    "invalid split row",
                )
                _require(
                    all(
                        type(row[key]) is str and _SHA.fullmatch(row[key])
                        for key in ("source_sha256", "embedding_sha256", "target_sha256")
                    ),
                    "invalid split digest",
                )
                seen.add(row["id"])
        for key in ("id", "source_sha256", "embedding_sha256"):
            _require(
                not {row[key] for row in checkpoint["training_manifest"]}
                & {row[key] for row in checkpoint["validation_manifest"]},
                "checkpoint split overlap",
            )

        with _cpu():
            model = numerical._model({"dimension": DIMENSION}, codec, config)
            state = checkpoint["model_state"]
            _require(
                type(state) is dict and set(state) == set(model.state_dict()),
                "model tensor names differ",
            )
            model.load_state_dict({
                name: numerical._tensor(state[name], template, name)
                for name, template in model.state_dict().items()
            }, strict=True)
        self.checkpoint = deepcopy(checkpoint)
        self.model = model.eval()

    def describe(self):
        checkpoint = self.checkpoint
        return {
            "schema": SCHEMA,
            "domain_id": checkpoint["domain_id"],
            "dimension": DIMENSION,
            "input_representation": "explicit_source_embedding_384",
            "architecture": checkpoint["architecture"],
            "weights_sha256": checkpoint["weights_sha256"],
            "parent_sha256": checkpoint["parent_sha256"],
            "embedding_provenance": deepcopy(
                checkpoint["config"]["embedding_provenance"]
            ),
            "embedding_provenance_verified_by_runtime": False,
            "trained_optimizer_steps": checkpoint["training"]["optimizer_steps"],
            "selected_epoch": checkpoint["training"]["selected_epoch"],
            "output_scope": (
                "native_documents_or_explicit_local_fragments"
                "_in_training_target_vocabulary"
            ),
            "source_text_is_neural_input": False,
            "sample_memory_used": False,
            "independent_source_fidelity_check_required": True,
            **FALSE,
        }

    def infer(self, rows, *, weight_ablation=None):
        rows = _rows(self.checkpoint["domain_id"], rows, training=False)
        _require(
            weight_ablation in (
                None, "zero_projection", "zero_condition", "zero_decoder"
            ),
            "unknown weight ablation",
        )
        model = self.model if weight_ablation is None else deepcopy(self.model)
        vocabulary = self.checkpoint["codec"]["target_vocabulary"]
        config = self.checkpoint["config"]
        reports = []
        with _cpu() as torch, torch.inference_mode():
            if weight_ablation:
                for name, parameter in model.named_parameters():
                    selected = (
                        weight_ablation == "zero_projection"
                        and name.startswith("projection_")
                    ) or (
                        weight_ablation == "zero_condition"
                        and name.startswith("condition.")
                    ) or (
                        weight_ablation == "zero_decoder"
                        and name.startswith(("decoder.", "output."))
                    )
                    if selected:
                        parameter.zero_()
            for row in rows:
                embedded = torch.tensor(
                    [row["embedding"]], dtype=torch.float32
                )
                projected = model.project(embedded)
                _require(
                    bool(torch.isfinite(projected).all()),
                    "nonfinite reconstructed embedding",
                )
                hidden = model.start(projected)
                current = torch.tensor([[1]], dtype=torch.long)
                generated, ended = [], False
                for _ in range(config["max_target_tokens"] - 1):
                    logits, hidden = model.next_logits(current, hidden)
                    _require(
                        bool(torch.isfinite(logits).all())
                        and bool(torch.isfinite(hidden).all()),
                        "nonfinite generated logits or hidden state",
                    )
                    index = int(logits[0, -1].argmax())
                    if index == 2:
                        ended = True
                        break
                    if index in (0, 1):
                        break
                    generated.append(vocabulary[index])
                    current = torch.tensor([[index]], dtype=torch.long)
                candidate = None
                status, reason = "fail_open_invalid_output", None
                if ended:
                    try:
                        value = _parse("".join(generated))
                        candidate = validate_target(
                            self.checkpoint["domain_id"], value
                        )["canonical_ir"]
                        status = "unqualified_candidate"
                    except (
                        ValueError, TypeError, KeyError, RecursionError
                    ) as exc:
                        reason = str(exc)[:512]
                reports.append({
                    "id": row["id"],
                    "source_sha256": hashlib.sha256(
                        row["source_text"].encode()
                    ).hexdigest(),
                    "status": status,
                    "reason": reason,
                    "candidate_ir": candidate,
                    "generated_tokens": generated,
                    "ended": ended,
                    "reconstructed_embedding": projected[0].tolist(),
                    "weight_ablation": weight_ablation,
                    "weights_sha256": self.checkpoint["weights_sha256"],
                    "target_access": False,
                    "teacher_forcing": False,
                    "continue_planning": True,
                    **FALSE,
                })
        return {
            "schema": SCHEMA,
            "domain_id": self.checkpoint["domain_id"],
            "dimension": DIMENSION,
            "rows": reports,
            **FALSE,
        }


def evaluate(checkpoint, rows):
    """Post-selection evaluation; gold targets never enter numerical inference."""
    runtime = Runtime(checkpoint)
    prepared = _rows(checkpoint["domain_id"], rows, training=True)
    report = runtime.infer([
        {key: row[key] for key in ("id", "source_text", "embedding")}
        for row in prepared
    ])
    for actual, gold in zip(report["rows"], prepared):
        actual["exact_target"] = actual["candidate_ir"] == gold["target"]
    report["exact_targets"] = sum(
        row["exact_target"] for row in report["rows"]
    )
    report["valid_candidates"] = sum(
        row["candidate_ir"] is not None for row in report["rows"]
    )
    report["count"] = len(prepared)
    return report


def load_checkpoint(path, *, expected_sha256, expected_domain):
    """Load bounded inert JSON with an explicit digest and expected domain."""
    path = Path(path)
    _require(
        path.is_file()
        and not path.is_symlink()
        and 0 < path.stat().st_size <= MAX_BYTES,
        "bounded regular checkpoint required",
    )
    raw = path.read_bytes()
    _require(
        len(raw) <= MAX_BYTES
        and hashlib.sha256(raw).hexdigest() == expected_sha256,
        "checkpoint bytes differ",
    )
    checkpoint = _parse(raw)
    _require(
        type(checkpoint) is dict
        and checkpoint.get("domain_id") == expected_domain,
        "checkpoint belongs to another domain",
    )
    return Runtime(checkpoint)


__all__ = [
    "SCHEMA", "DIMENSION", "DOMAINS", "Runtime", "train", "evaluate",
    "validate_target", "load_checkpoint", "digest",
]
