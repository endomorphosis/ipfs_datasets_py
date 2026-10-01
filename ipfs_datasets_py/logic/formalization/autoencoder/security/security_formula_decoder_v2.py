"""Transferred expanded production decoder with independent source checking.

Learned, factorized production decoding with independent source checking.

This is a small supervised grammar head, not a general code language model.
Frozen inherited lexical rows and source token observations feed learned
low-rank production logits. Candidate construction uses predicted productions;
wrong predictions are rejected, never replaced by deterministic target labels.
"""
from __future__ import annotations

import ast
import hashlib
import json
import math
import re
from pathlib import Path
from types import SimpleNamespace

from . import security_formula_grammar_v2 as grammar
from . import security_formula_decoder as legacy
from . import security_formula_grammar as legacy_grammar
from . import security_autoencoder_checkpoint as portable
from .security_autoencoder_features import _token_features

SCHEMA = "security-formula-production-decoder@2"
REPORT_SCHEMA = "security-learned-formula-candidate@2"
FILES = {"manifest.json", "weights.json", "config.json", "training.json"}
MAX_BYTES = 8 * 1024 * 1024
_AUTHORITY = {"proof_authority": False, "execution_authority": False, "completion_authority": False,
              "security_specification_inferred": False, "whole_program_semantics_verified": False}
_SCOPES = {"authored_development_controls", "publicus_and_authored_development_controls", "caller_declared_development_controls"}


def _digest(value):
    if type(value) is not str or not re.fullmatch(r"[a-f0-9]{64}", value):
        raise ValueError("exact independently pinned SHA256 required")
    return value


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _implementation():
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_autoencoder_cuda as kernel
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_autoencoder_batching as batching
    from . import security_autoencoder_features as lexical
    from ....security_ir import code_program_derivation as guard
    return {"parent_decoder_sha256": _sha(Path(legacy.__file__).read_bytes()), "decoder_sha256": _sha(Path(__file__).read_bytes()), "grammar_sha256": _sha(Path(grammar.__file__).read_bytes()),
        "native_kernel_sha256": _sha(Path(kernel.__file__).read_bytes()), "native_batching_sha256": _sha(Path(batching.__file__).read_bytes()),
        "lexical_projection_sha256": _sha(Path(lexical.__file__).read_bytes()),
        "independent_source_guard_sha256": _sha(Path(guard.__file__).read_bytes()),
        "reused_native_functions": ["modal_autoencoder_cuda._loss_chunk/family_logits", "modal_autoencoder_cuda._gradient_norm", "modal_autoencoder_batching.plan_gradient_accumulation"]}


def expand_parent_parameters(parent: dict) -> tuple[list, dict]:
    """Copy inherited feature rows/head columns exactly; zero only new dimensions."""
    lexical_width = parent["config"]["lexical_width"]
    latent_width = parent["config"]["latent_width"]
    prior = parent["weights"]["parameters"]
    old_features = list(legacy_grammar.FEATURES) + ["inherited-lexical:" + str(i) for i in range(lexical_width)]
    new_features = list(grammar.FEATURES) + ["inherited-lexical:" + str(i) for i in range(lexical_width)]
    old_positions = {name: index for index, name in enumerate(old_features)}
    encoder = [list(prior[0][old_positions[name]]) if name in old_positions else [0.] * latent_width for name in new_features]
    heads = [[0.] * len(grammar.PRODUCTIONS) for _ in range(latent_width)]
    biases = [0.] * len(grammar.PRODUCTIONS)
    for old_index, name in enumerate(legacy_grammar.PRODUCTIONS):
        new_index = grammar.PRODUCTIONS.index(name)
        for row in range(latent_width):
            heads[row][new_index] = prior[2][row][old_index]
        biases[new_index] = prior[3][old_index]
    parameters = [encoder, list(prior[1]), heads, biases]
    return parameters, {"parent_manifest_sha256": parent["descriptor"]["manifest_sha256"],
        "parent_weights_sha256": parent["descriptor"]["weights_sha256"],
        "copied_feature_rows": len(old_features), "zero_added_feature_rows": len(new_features) - len(old_features),
        "copied_production_columns": len(legacy_grammar.PRODUCTIONS),
        "zero_added_production_columns": len(grammar.PRODUCTIONS) - len(legacy_grammar.PRODUCTIONS),
        "initial_parameters_sha256": _sha(_json(parameters)), "parent_modified": False,
        "initialization": "exact copied parent tensors with zero appended dimensions; no random restart"}


# The numeric kernel and lexical projection are shared with the frozen decoder.
_matrix = legacy._matrix
_numeric_rows = legacy._numeric_rows
_forward = legacy._forward


def _predictions(loaded, observed, *, weight_ablation=None):
    import torch
    parameters = [torch.tensor(value, dtype=torch.float64) for value in loaded["weights"]["parameters"]]
    if weight_ablation == "zero_production_heads":
        parameters[2] = torch.zeros_like(parameters[2]); parameters[3] = torch.zeros_like(parameters[3])
    elif weight_ablation is not None:
        raise ValueError("unsupported explicit weight ablation")
    with torch.no_grad():
        data = torch.tensor(_numeric_rows(observed, loaded["weights"]["lexical"]), dtype=torch.float64)
        logits = _forward(torch, data, parameters)
        if not torch.isfinite(logits).all():
            raise ValueError("nonfinite production logits")
        scores = torch.softmax(logits, dim=1).tolist()
        raw_indexes = logits.argmax(dim=1).tolist()
        allowed = [grammar.feasible_productions(node) for node in observed["nodes"]]
        if any(not names for names in allowed):
            raise ValueError("source binding/arity has no feasible grammar production")
        masked_logits = logits.clone()
        for row_index, names in enumerate(allowed):
            allowed_indexes = {grammar.PRODUCTIONS.index(name) for name in names}
            for column in range(len(grammar.PRODUCTIONS)):
                if column not in allowed_indexes:
                    masked_logits[row_index, column] = -torch.inf
        indexes = masked_logits.argmax(dim=1).tolist()
        constrained_scores = torch.softmax(masked_logits, dim=1).tolist()
    return [{"node_id": node["node_id"], "production": grammar.PRODUCTIONS[index],
             "raw_production": grammar.PRODUCTIONS[raw_index], "logits": row.tolist(),
             "confidence": probabilities[index], "raw_confidence": probabilities[raw_index],
             "constrained_confidence": constrained[index], "feasible_productions": list(names),
             "constraint_changed_argmax": index != raw_index,
             "selection": "learned_logits_with_generic_binding_arity_feasibility_mask"}
            for node, index, raw_index, row, probabilities, constrained, names in zip(
                observed["nodes"], indexes, raw_indexes, logits, scores, constrained_scores, allowed)]


def _descriptor(output, raw, manifest):
    return {"schema": SCHEMA, "output": str(output), "manifest_sha256": _sha(raw),
        "weights_sha256": manifest["files"]["weights.json"]["sha256"], "mode": "frozen_production_inference",
        "authority": "independently_checked_candidate_only", **_AUTHORITY}


def load_security_formula_decoder_v2(checkpoint: dict) -> dict:
    if type(checkpoint) is not dict or set(checkpoint) != {"schema", "output", "manifest_sha256", "weights_sha256", "mode", "authority", *_AUTHORITY}:
        raise ValueError("exact independently pinned formula checkpoint descriptor required")
    if any(checkpoint[k] is not False for k in _AUTHORITY):
        raise ValueError("decoder descriptors grant no authority")
    _digest(checkpoint["manifest_sha256"]); _digest(checkpoint["weights_sha256"])
    output = portable._namespace(Path(checkpoint["output"]))
    if {path.name for path in output.iterdir()} != FILES:
        raise ValueError("closed inert formula package required")
    raw = portable._read(output / "manifest.json", MAX_BYTES)
    manifest = portable._decode(raw)
    if (type(manifest) is not dict or set(manifest) != {"schema", "files", "authority", *_AUTHORITY}
            or manifest["schema"] != SCHEMA or manifest["authority"] != "independently_checked_candidate_only"
            or any(manifest[k] is not False for k in _AUTHORITY)
            or type(manifest["files"]) is not dict or set(manifest["files"]) != FILES - {"manifest.json"}
            or _descriptor(output, raw, manifest) != checkpoint):
        raise ValueError("formula package identity or authority differs")
    values = {}
    for name, info in manifest["files"].items():
        raw = portable._read(output / name, MAX_BYTES)
        if type(info) is not dict or set(info) != {"sha256", "bytes"} or type(info["bytes"]) is not int or len(raw) != info["bytes"] or _sha(raw) != info["sha256"]:
            raise ValueError("formula package artifact drift")
        values[name] = portable._decode(raw)
    config, weights, training = values["config.json"], values["weights.json"], values["training.json"]
    expected_config = _config(config.get("lexical_width"), config.get("latent_width"))
    if config != expected_config:
        raise ValueError("formula grammar, implementation or architecture drift")
    if type(weights) is not dict or set(weights) != {"schema", "parameters", "lexical"} or weights["schema"] != SCHEMA:
        raise ValueError("closed decoder weight state required")
    lexical = weights["lexical"]
    if type(lexical) is not dict or set(lexical) != {"keys", "weights", "width", "initializer_sha256", "parent_checkpoint_sha256", "published_source_pin"}:
        raise ValueError("closed inherited lexical state required")
    keys = lexical["keys"]
    if (type(keys) is not list or not 1 <= len(keys) <= 8192 or keys != sorted(set(keys))
            or any(type(key) is not str or not re.fullmatch(r"token:[a-z0-9]{3,}", key) for key in keys)
            or lexical["width"] != config["lexical_width"]):
        raise ValueError("inherited lexical identities differ")
    _digest(lexical["initializer_sha256"]); _digest(lexical["parent_checkpoint_sha256"])
    if lexical["published_source_pin"] is not None:
        from .published_legal_initializer import validate_published_legal_source_pin
        pin = validate_published_legal_source_pin(lexical["published_source_pin"])
        if pin["state_sha256"] != lexical["parent_checkpoint_sha256"]:
            raise ValueError("published parent identity differs")
    _matrix(lexical["weights"], len(keys), config["lexical_width"])
    shapes = [(len(grammar.FEATURES) + config["lexical_width"], config["latent_width"]),
              (config["latent_width"], None), (config["latent_width"], len(grammar.PRODUCTIONS)), (len(grammar.PRODUCTIONS), None)]
    if type(weights["parameters"]) is not list or len(weights["parameters"]) != 4:
        raise ValueError("exact four production tensors required")
    for value, shape in zip(weights["parameters"], shapes):
        _matrix(value, *shape)
    _training_receipt(training)
    transfer = training["parent_transfer"]
    if (transfer["copied_feature_rows"] != len(legacy_grammar.FEATURES) + config["lexical_width"]
            or transfer["zero_added_feature_rows"] != len(grammar.FEATURES) - len(legacy_grammar.FEATURES)):
        raise ValueError("parent feature transfer dimensions differ")
    if (training.get("weights_sha256") != _sha(_json(weights))
            or training.get("inherited_lexical_sha256") != _sha(_json(lexical))
            or training.get("final_head_sha256") != _sha(_json(weights["parameters"]))
            or training.get("legal_parent_modified") is not False or training.get("heldout_used_for_fit") is not False
            or training.get("proof_authority") is not False):
        raise ValueError("training lineage or final weight binding differs")
    return {"descriptor": dict(checkpoint), "manifest": manifest, "config": config, "weights": weights, "training": training}


def _training_receipt(value):
    constants = {"schema": SCHEMA, "new_head_initialization": "exact parent feature rows, encoder biases and production columns; zero new dimensions",
        "inherited_lexical_weights": "exact frozen selected parent rows; no gradient updates",
        "source_bodies_persisted": False, "teacher_whole_formula_lookup": False,
        "heldout_used_for_fit": False, "legal_parent_modified": False, "provider_calls": 0, "download_calls": 0,
        "development_holdout_reuse": True,
        "heldout_scope": "development capability controls excluded from gradient updates; no blind statistical generalization claim", **_AUTHORITY}
    fields = set(constants) | {"splits", "metrics", "raw_metrics", "epochs", "seed", "inherited_lexical_sha256", "initial_head_sha256",
        "final_head_sha256", "weights_sha256", "native_kernel_calls", "training_losses", "gradient_norms", "training_steps",
        "training_data_scope", "training_provenance_sha256", "parent_transfer"}
    if (type(value) is not dict or set(value) != fields
            or any(type(value[k]) is not type(v) or value[k] != v for k, v in constants.items())
            or value["training_data_scope"] not in _SCOPES):
        raise ValueError("closed source-free development training receipt required")
    if (type(value["epochs"]) is not int or not 1 <= value["epochs"] <= 256
            or type(value["training_steps"]) is not int or value["training_steps"] != value["epochs"]
            or type(value["seed"]) is not int or not 0 <= value["seed"] < 2**31
            or type(value["native_kernel_calls"]) is not int or value["native_kernel_calls"] <= 0):
        raise ValueError("bounded actual gradient and native kernel counts required")
    for key in ("inherited_lexical_sha256", "initial_head_sha256", "final_head_sha256", "weights_sha256"):
        _digest(value[key])
    if value["training_provenance_sha256"] is not None:
        _digest(value["training_provenance_sha256"])
    for name in ("training_losses", "gradient_norms"):
        sequence = value[name]
        if type(sequence) is not list or len(sequence) != value["epochs"] or any(type(v) not in (int, float) or not math.isfinite(v) or v < 0 for v in sequence):
            raise ValueError("finite epoch observations required")
    transfer = value["parent_transfer"]
    if (type(transfer) is not dict or set(transfer) != {"parent_manifest_sha256", "parent_weights_sha256", "copied_feature_rows", "zero_added_feature_rows", "copied_production_columns", "zero_added_production_columns", "initial_parameters_sha256", "parent_modified", "initialization"}
            or transfer["parent_modified"] is not False
            or transfer["initialization"] != "exact copied parent tensors with zero appended dimensions; no random restart"
            or transfer["initial_parameters_sha256"] != value["initial_head_sha256"]
            or transfer["copied_production_columns"] != len(legacy_grammar.PRODUCTIONS)
            or transfer["zero_added_production_columns"] != len(grammar.PRODUCTIONS) - len(legacy_grammar.PRODUCTIONS)):
        raise ValueError("closed parent weight transfer receipt required")
    for key in ("parent_manifest_sha256", "parent_weights_sha256", "initial_parameters_sha256"):
        _digest(transfer[key])
    for key in ("copied_feature_rows", "zero_added_feature_rows", "copied_production_columns", "zero_added_production_columns"):
        if type(transfer[key]) is not int or transfer[key] < 0:
            raise ValueError("exact transfer tensor counts required")
    splits, metrics, raw_metrics = value["splits"], value["metrics"], value["raw_metrics"]
    if type(splits) is not dict or set(splits) != {"train", "validation", "test"} or type(metrics) is not dict or set(metrics) != set(splits) or type(raw_metrics) is not dict or set(raw_metrics) != set(splits):
        raise ValueError("closed independent development splits required")
    identifiers, shape_splits = set(), {}
    for split, rows in splits.items():
        if type(rows) is not list or not 1 <= len(rows) <= 384:
            raise ValueError("bounded split inventory required")
        for row in rows:
            if type(row) is not dict or set(row) != {"id", "source_sha256", "program_shape_sha256"} or type(row["id"]) is not str or not re.fullmatch(r"[a-zA-Z0-9_.:-]{1,128}", row["id"]) or row["id"] in identifiers:
                raise ValueError("closed source identity inventory required")
            identifiers.add(row["id"])
            _digest(row["source_sha256"]); shape = _digest(row["program_shape_sha256"])
            if shape in shape_splits and shape_splits[shape] != split:
                raise ValueError("cross-split program overlap in receipt")
            shape_splits[shape] = split
        for metric in (metrics[split], raw_metrics[split]):
            if type(metric) is not dict or set(metric) != {"programs", "production_count", "correct_productions", "production_accuracy", "exact_programs", "exact_program_accuracy"}:
                raise ValueError("closed measured production metrics required")
            if (any(type(metric[k]) is not int for k in ("programs", "production_count", "correct_productions", "exact_programs"))
                    or metric["programs"] != len(rows) or not 0 <= metric["exact_programs"] <= len(rows)
                    or not 0 <= metric["correct_productions"] <= metric["production_count"] <= 8192 or metric["production_count"] == 0
                    or type(metric["production_accuracy"]) is not float or metric["production_accuracy"] != metric["correct_productions"] / metric["production_count"]
                    or type(metric["exact_program_accuracy"]) is not float or metric["exact_program_accuracy"] != metric["exact_programs"] / len(rows)):
                raise ValueError("split counts or measured accuracy differ")


def _config(lexical_width, latent_width):
    if type(lexical_width) is not int or not 2 <= lexical_width <= 16 or type(latent_width) is not int or not 8 <= latent_width <= 64:
        raise ValueError("bounded factorized decoder dimensions required")
    return {"schema": SCHEMA, "architecture": "source-and-inherited-lexical-tanh-factorized-production-head@2",
        "lexical_width": lexical_width, "latent_width": latent_width, "dtype": "float64",
        "feature_vocabulary": list(grammar.FEATURES), "production_vocabulary": list(grammar.PRODUCTIONS),
        "grammar_schema": grammar.SCHEMA, "implementation": _implementation(),
        "deterministic_inputs": ["syntax topology", "source binder identities", "literal values", "exact source token shell"],
        "learned_outputs": "one production distribution per compositional node",
        "production_selection": "neural logits restricted by generic binder/arity feasibility; raw argmax retained",
        "constraint_failure": "reject; never substitute a source teacher label", **_AUTHORITY}


def train_security_formula_decoder_v2(*, samples: list[dict], parent_checkpoint: dict, output: Path,
        epochs=200, seed=1729,
        training_data_scope="authored_development_controls", training_provenance_sha256=None) -> dict:
    """Fork actual v1 weights, fit train examples, and evaluate held-out compositions."""
    if type(epochs) is not int or not 1 <= epochs <= 256 or type(seed) is not int or not 0 <= seed < 2**31:
        raise ValueError("explicit bounded decoder training budget required")
    if type(samples) is not list or not 3 <= len(samples) <= 384:
        raise ValueError("bounded explicit train/validation/test examples required")
    if training_data_scope not in _SCOPES:
        raise ValueError("explicit development corpus scope required")
    if training_provenance_sha256 is not None and (type(training_provenance_sha256) is not str or not re.fullmatch(r"[a-f0-9]{64}", training_provenance_sha256)):
        raise ValueError("independent training provenance SHA256 required")
    output = portable._namespace(Path(output), fresh=True, excluded=(Path(parent_checkpoint["output"]),))
    parent = legacy.load_security_formula_decoder(parent_checkpoint)
    lexical = parent["weights"]["lexical"]
    latent_width = parent["config"]["latent_width"]
    initial_parameters, parent_transfer = expand_parent_parameters(parent)
    config = _config(lexical["width"], latent_width)
    observed, splits, identities, shapes = {}, {name: [] for name in ("train", "validation", "test")}, set(), {}
    for sample in samples:
        if (type(sample) is not dict or set(sample) not in ({"id", "split", "source"}, {"id", "split", "source", "source_sha256"})
                or type(sample["id"]) is not str or not re.fullmatch(r"[a-zA-Z0-9_.:-]{1,128}", sample["id"])
                or sample["id"] in identities or sample["split"] not in splits or type(sample["source"]) is not str):
            raise ValueError("closed uniquely identified authored sample required")
        raw = sample["source"].encode()
        digest = _sha(raw)
        if sample.get("source_sha256", digest) != digest:
            raise ValueError("training source identity differs")
        parsed = grammar.parse_formula_source(raw)
        shape = grammar.source_shape(raw)
        if shape in shapes and shapes[shape] != sample["split"]:
            raise ValueError("cross-split alpha/literal-normalized program overlap")
        shapes[shape] = sample["split"]
        identities.add(sample["id"])
        observed[sample["id"]] = parsed
        splits[sample["split"]].append({"id": sample["id"], "source_sha256": digest, "program_shape_sha256": shape})
    if any(not rows for rows in splits.values()) or sum(len(x["nodes"]) for x in observed.values()) > 8192:
        raise ValueError("nonempty independent splits and bounded production observations required")
    rows = [row for item in splits["train"] for row in _numeric_rows(observed[item["id"]], lexical)]
    targets = [grammar.PRODUCTIONS.index(node["teacher_production"]) for item in splits["train"] for node in observed[item["id"]]["nodes"]]
    if not any(any(value for value in row[-lexical["width"]:]) for row in rows):
        raise ValueError("training has zero inherited lexical contribution")
    import torch
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_autoencoder_cuda as kernel
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_autoencoder_batching as batching
    previous_threads = torch.get_num_threads()
    torch.set_num_threads(1)
    try:
        parameters = [torch.tensor(value, dtype=torch.float64, requires_grad=True) for value in initial_parameters]
        initial_hash = _sha(_json([value.detach().tolist() for value in parameters]))
        data = torch.tensor(rows, dtype=torch.float64)
        one_hot = torch.nn.functional.one_hot(torch.tensor(targets), num_classes=len(grammar.PRODUCTIONS)).double()
        state = SimpleNamespace(torch=torch, device=torch.device("cpu"), family_targets=one_hot,
            family_mask=torch.ones(len(rows), dtype=torch.bool))
        session = SimpleNamespace(blocks={}, parameters=parameters, parameter_count=sum(value.numel() for value in parameters))
        plan = batching.plan_gradient_accumulation(len(rows), microbatch_size=128)
        empty = torch.zeros((len(rows), 0), dtype=torch.float64)
        optimizer = torch.optim.Adam(parameters, lr=.04)
        losses, gradients, kernel_calls = [], [], 0
        for _ in range(epochs):
            optimizer.zero_grad()
            logits = _forward(torch, data, parameters)
            total = 0.0
            for index, (start, stop) in enumerate(plan.ranges):
                loss, _, calls = kernel._loss_chunk(state, session, (empty, logits, empty), {"family_logits"},
                    start, stop, len(rows), 0., 0., False)
                if not torch.isfinite(loss):
                    raise ValueError("nonfinite native production loss")
                loss.backward(retain_graph=index + 1 < len(plan.ranges))
                total += float(loss.detach()); kernel_calls += calls
            gradient = kernel._gradient_norm(torch, parameters)
            if not math.isfinite(gradient):
                raise ValueError("nonfinite native production gradient")
            gradients.append(gradient)
            torch.nn.utils.clip_grad_norm_(parameters, 5.)
            optimizer.step(); losses.append(total)
        weights = {"schema": SCHEMA, "lexical": lexical, "parameters": [value.detach().tolist() for value in parameters]}
        final_head_hash = _sha(_json(weights["parameters"]))
        if final_head_hash == initial_hash or not any(gradient > 0 for gradient in gradients):
            raise ValueError("production weights did not learn")
        loaded = {"weights": weights}
        metrics, raw_metrics = {}, {}
        for split, items in splits.items():
            correct = total = exact = raw_correct = raw_exact = 0
            for item in items:
                sample = observed[item["id"]]
                predictions = _predictions(loaded, sample)
                matched = [pred["production"] == node["teacher_production"] for pred, node in zip(predictions, sample["nodes"])]
                raw_matched = [pred["raw_production"] == node["teacher_production"] for pred, node in zip(predictions, sample["nodes"])]
                raw_correct += sum(raw_matched); raw_exact += all(raw_matched)
                correct += sum(matched); total += len(matched); exact += all(matched)
            metrics[split] = {"programs": len(items), "production_count": total, "correct_productions": correct,
                "production_accuracy": correct / total, "exact_programs": exact, "exact_program_accuracy": exact / len(items)}
            raw_metrics[split] = {"programs": len(items), "production_count": total, "correct_productions": raw_correct,
                "production_accuracy": raw_correct / total, "exact_programs": raw_exact, "exact_program_accuracy": raw_exact / len(items)}
    finally:
        torch.set_num_threads(previous_threads)
    if legacy.load_security_formula_decoder(parent_checkpoint) != parent:
        raise ValueError("parent checkpoint changed during decoder training")
    training = {"schema": SCHEMA, "splits": splits, "metrics": metrics, "raw_metrics": raw_metrics, "parent_transfer": parent_transfer,
        "epochs": epochs, "seed": seed, "new_head_initialization": "exact parent feature rows, encoder biases and production columns; zero new dimensions",
        "inherited_lexical_weights": "exact frozen selected parent rows; no gradient updates",
        "inherited_lexical_sha256": _sha(_json(lexical)), "initial_head_sha256": initial_hash,
        "final_head_sha256": final_head_hash, "weights_sha256": _sha(_json(weights)),
        "native_kernel_calls": kernel_calls, "training_losses": losses, "gradient_norms": gradients,
        "training_steps": epochs, "source_bodies_persisted": False, "teacher_whole_formula_lookup": False,
        "heldout_used_for_fit": False, "legal_parent_modified": False, "provider_calls": 0, "download_calls": 0,
        "training_data_scope": training_data_scope, "training_provenance_sha256": training_provenance_sha256,
        "development_holdout_reuse": True,
        "heldout_scope": "development capability controls excluded from gradient updates; no blind statistical generalization claim", **_AUTHORITY}
    payloads = {"weights.json": _json(weights), "config.json": _json(config), "training.json": _json(training)}
    manifest = {"schema": SCHEMA, "files": {name: {"sha256": _sha(raw), "bytes": len(raw)} for name, raw in payloads.items()},
        "authority": "independently_checked_candidate_only", **_AUTHORITY}
    manifest_raw = _json(manifest)
    output.mkdir(parents=True, mode=0o700)
    for name, raw in {**payloads, "manifest.json": manifest_raw}.items():
        if len(raw) > MAX_BYTES:
            raise ValueError("bounded formula package required")
        portable._write(output / name, raw)
    descriptor = _descriptor(output, manifest_raw, manifest)
    load_security_formula_decoder_v2(descriptor)
    return descriptor


def decode_security_formula_v2(*, source_bytes: bytes, checkpoint: dict, source_path: str,
        loaded: dict | None = None, model_enabled=True, weight_ablation=None) -> dict:
    """Frozen learned production inference, followed by exact syntax and native checks."""
    if type(model_enabled) is not bool or type(source_path) is not str or not source_path or len(source_path) > 512:
        raise ValueError("explicit decoder selection and source identity required")
    current = load_security_formula_decoder_v2(checkpoint)
    if loaded is not None and _json(loaded) != _json(current):
        raise ValueError("cached decoder differs from exact package")
    loaded = current
    report = {"schema": REPORT_SCHEMA, "checkpoint": checkpoint, "source_path": source_path,
        "source_sha256": _sha(source_bytes), "status": "unsupported", "learned_formula_count": 0,
        "predicted_productions": [], "candidate": None, "candidate_source": None, "native_artifact": None,
        "native_adapter": None, "validation": {"source_AST_equivalent": False, "native_lowering_complete": False},
        "frontiers": [], "model_enabled": model_enabled, "weight_ablation": weight_ablation,
        "producer": "learned_compositional_productions_with_deterministic_source_bindings",
        "compiler": "independent_AST_check_then_separate_typed_logic_projection", "training_steps": 0,
        "provider_calls": 0, "download_calls": 0, "solver_calls": 0, "neural_forward_count": 0, **_AUTHORITY}
    if not model_enabled:
        report["frontiers"] = ["learned_model_disabled; no deterministic production fallback"]
        return report
    try:
        observed = grammar.parse_formula_source(source_bytes)
    except grammar.UnsupportedFormulaSource as exc:
        report["frontiers"] = [str(exc)]
        return report
    predicted = _predictions(loaded, observed, weight_ablation=weight_ablation)
    report["predicted_productions"] = predicted
    report["neural_forward_count"] = 1
    try:
        candidate_bytes, tree = grammar.compose_candidate(observed, [row["production"] for row in predicted])
    except ValueError as exc:
        report.update(status="rejected", frontiers=[str(exc)])
        return report
    report.update(candidate=tree, candidate_source=candidate_bytes.decode())
    report["validation"]["source_AST_equivalent"] = True
    report.update(status="candidate", frontiers=[
        "learned syntax agrees with independent source AST; typed semantic lowering remains required",
        "no security specification or source runtime equivalence theorem inferred"])
    return report


def validate_security_formula_decode_v2(report, *, source_bytes, checkpoint):
    expected = decode_security_formula_v2(source_bytes=source_bytes, checkpoint=checkpoint, source_path=report["source_path"],
        model_enabled=report["model_enabled"], weight_ablation=report["weight_ablation"])
    if _json(expected) != _json(report):
        raise ValueError("learned formula production/source/native artifact replay differs")
    return expected
