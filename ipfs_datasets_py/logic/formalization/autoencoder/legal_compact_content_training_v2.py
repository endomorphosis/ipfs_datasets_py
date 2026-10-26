"""Bounded engineering-only compact teacher forcing with named Adam resume.

This additive owner consumes a validated zero-step v1 head. It never changes the
v1 checkpoint contract, produces a source encoder, or admits statutory targets.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import platform
import re
import stat
import time

SCHEMA = "legal-compact-content-training-checkpoint/v2"
REPORT_SCHEMA = "legal-compact-content-training/v2"
POPULATION_SCHEMA = "legal-compact-content-training-population/v2"
PROFILE = "authored-compact-content-training-384/v2"
MAX_ROWS, MAX_STEPS_PER_CALL, MAX_TOTAL_STEPS = 16, 16, 100000
MAX_CHECKPOINT_BYTES = 64 * 1024 * 1024
MAX_INPUT_BYTES, MAX_REPORT_BYTES = 128 * 1024 * 1024, 64 * 1024 * 1024
MAX_POPULATION_BYTES = 128 * 1024
_SELF_PATH = Path(__file__).absolute()
_SELF_SHA = hashlib.sha256(_SELF_PATH.read_bytes()).hexdigest()
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_SPECS = (
    ("head", "ipfs_datasets_py.logic.formalization.autoencoder.legal_compact_content_head_v1",
     "logic/formalization/autoencoder/legal_compact_content_head_v1.py",
     "8e32341e5962c01193ec46313011b83ba67b340a8996f866e417b10179b5c021"),
    ("numerical", "ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_latent_formula",
     "optimizers/logic_theorem_optimizer/modal_latent_formula.py",
     "ec5bdcd752d157c9fc0257a45551cfe9ce7be172af767e8ed769bf1bc8a31d36"),
    ("tokens", "ipfs_datasets_py.logic.formalization.autoencoder.legal_compact_content_tokens_v1",
     "logic/formalization/autoencoder/legal_compact_content_tokens_v1.py",
     "145e4598616100c58b01f0e38ffbb378ee2938d091e98834fe2b01f4b348486e"),
)
_AUTHORITY = dict.fromkeys((
    "source_semantics_verified", "source_bound", "source_encoder_authenticated",
    "conditioning_producer_verified", "target_independence_verified", "legal_roles_verified",
    "applicability_verified", "governing_use_verified", "accepted", "admitted",
    "training_qualified", "training_gold_qualified", "evaluation_gold_qualified",
    "statutory_checkpoint_qualified", "source_fidelity_verified", "legal_accuracy_established",
    "held_out_generation_verified", "permitted_inference_context_verified", "proof_authority", "Lean_admitted",
), False)
_LIMITATIONS = [
    "Only caller-declared authored engineering fixtures are accepted; this declaration is not authenticated provenance or permission.",
    "384-coordinate conditioning is caller-supplied and unverified; source text is hashed, not encoded or supplied to the neural model.",
    "Independent supplied contexts are validated without constructing a dictionary from targets; their independence and legal meanings remain unverified.",
    "Teacher-forced compact-token cross-entropy is not free-running reconstruction, held-out performance, legal equivalence or proof checking.",
    "The original v1 head and donor ledger are retained separately from current trained weights and the immediate v2 parent.",
    "Exact resume requires the same complete ordered population, runtime, optimizer policy, source pins and named float32 state.",
    "The current v1 scorer and generator intentionally reject this v2 checkpoint; a trained inference consumer is a separate implementation.",
    "Source endpoint pins do not authenticate arbitrary loaded bytecode, third-party binaries, private provenance or an operating-system sandbox.",
]


class CompactContentTrainingError(ValueError):
    """Closed engineering input, pinned source, numerical or resume refusal."""


def _need(okay, message):
    if not okay:
        raise CompactContentTrainingError(message)


def _hash(value, label):
    _need(type(value) is str and _SHA.fullmatch(value) is not None,
          "independent lowercase SHA256 required: " + label)


def _source(path, expected):
    _need(path.is_absolute() and all(stat.S_ISDIR(p.lstat().st_mode) for p in path.parents),
          "unaliased source parents required")
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as stream:
        before = os.fstat(stream.fileno())
        _need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and 0 < before.st_size <= 131072,
              "bounded single-link regular source required")
        raw, after = stream.read(before.st_size + 1), os.fstat(stream.fileno())
    identity = lambda row: (row.st_dev, row.st_ino, row.st_mode, row.st_size,
                            row.st_mtime_ns, row.st_ctime_ns, row.st_nlink)
    _need(identity(before) == identity(after) == identity(path.lstat())
          and len(raw) == before.st_size and hashlib.sha256(raw).hexdigest() == expected,
          "source identity or raw pin changed")
    return {"path": str(path), "bytes": len(raw), "sha256": expected}, identity(before)


def _sources():
    root = None
    for parent in _SELF_PATH.parents:
        for candidate in (parent / "ipfs_datasets_py", parent / "external/ipfs_datasets/ipfs_datasets_py"):
            if (candidate / _SPECS[0][2]).is_file():
                _need(candidate.resolve() == candidate, "canonical source root required")
                root = candidate
                break
        if root is not None:
            break
    _need(root is not None, "compact training owners unavailable")
    return root, [_source(_SELF_PATH, _SELF_SHA),
                  *[_source(root / relative, sha) for _, _, relative, sha in _SPECS]]


def _head():
    root, pins = _sources()
    head = importlib.import_module(_SPECS[0][1])
    _need(type(head.__file__) is str and Path(head.__file__).absolute() == root / _SPECS[0][2],
          "canonical head owner import required")
    _need(_sources() == (root, pins), "source changed during owner import")
    return head, (root, pins)


def _implementation():
    return {"training_sha256": _SELF_SHA,
            "direct_owners": {relative: sha for _, _, relative, sha in _SPECS}}


def _operation(original, work, *, as_bytes=False):
    head, source_pin = _head()
    snapshot = head._copy(original, MAX_INPUT_BYTES, allow_bytes=True)
    token = head._fingerprint(snapshot)
    loaded, runtime, failure = None, None, None
    def fence():
        _need(_sources() == source_pin and head._fingerprint(snapshot) == token
              and head._fingerprint(head._copy(original, MAX_INPUT_BYTES, allow_bytes=True)) == token,
              "source or original/captured input custody changed")
        if loaded is not None:
            head._closing(loaded)
            if runtime is not None:
                _need(_runtime(head, loaded) == runtime, "numerical runtime changed during operation")
    try:
        loaded = head._owners(numeric=True)
        runtime = _runtime(head, loaded)
        result = work(snapshot, head, loaded)
        if as_bytes:
            _need(type(result) is bytes and len(result) <= MAX_CHECKPOINT_BYTES,
                  "bounded checkpoint transport required")
        else:
            result = head._detach(result, MAX_REPORT_BYTES)
        fence()
        return result
    except BaseException as error:
        failure = error
        raise
    finally:
        head._finish(failure, fence)


def _runtime(head, loaded):
    torch = head._torch(loaded)
    return {"python_version": platform.python_version(), "python_implementation": platform.python_implementation(),
            "machine": platform.machine(), "torch_version": str(torch.__version__),
            "torch_build_sha256": hashlib.sha256(torch.__config__.show().encode("utf-8")).hexdigest(),
            "device": "cpu", "dtype": "float32", "num_threads": torch.get_num_threads(),
            "num_interop_threads": torch.get_num_interop_threads(),
            "mkldnn_enabled": bool(torch.backends.mkldnn.enabled),
            "deterministic_algorithms": bool(torch.are_deterministic_algorithms_enabled())}


def _parse(raw, expected, maximum, label, head):
    _hash(expected, label)
    _need(type(raw) is bytes and 0 < len(raw) <= maximum
          and hashlib.sha256(raw).hexdigest() == expected, label + " raw identity differs")
    def pairs(rows):
        result = {}
        for key, value in rows:
            _need(key not in result, "duplicate " + label + " JSON key")
            result[key] = value
        return result
    def nonfinite(_):
        raise CompactContentTrainingError("nonfinite " + label + " JSON refused")
    try:
        return head._copy(json.loads(raw.decode("utf-8"), object_pairs_hook=pairs,
                                     parse_constant=nonfinite), maximum)
    except (UnicodeError, RecursionError, OverflowError) as error:
        raise CompactContentTrainingError("bounded ordinary UTF8 JSON required: " + label) from error


def _population(raw, expected, head):
    value = _parse(raw, expected, MAX_POPULATION_BYTES, "training population", head)
    _need(type(value) is dict and set(value) == {"schema", "origin", "partition", "rows"}
          and value["schema"] == POPULATION_SCHEMA and value["origin"] == "authored_engineering_fixture"
          and value["partition"] == "engineering_training" and type(value["rows"]) is list
          and 1 <= len(value["rows"]) <= MAX_ROWS, "complete authored engineering population required")
    seen = set()
    for row in value["rows"]:
        _need(type(row) is dict and set(row) == {"id", "source_group", "source_sha256", "context_sha256",
                                               "target_sha256", "conditioning_sha256"},
              "closed training population row required")
        for field in ("id", "source_group"):
            _need(type(row[field]) is str and 0 < len(row[field]) <= 256 and bool(row[field].strip()),
                  "nonempty bounded population identity required")
        _need(row["id"] not in seen, "duplicate training occurrence")
        seen.add(row["id"])
        for field in ("source_sha256", "context_sha256", "target_sha256", "conditioning_sha256"):
            _hash(row[field], field)
    return value


def _rows(rows, population, codec, codec_sha, head, loaded):
    _need(type(rows) is list and len(rows) == len(population["rows"]), "complete ordered training rows required")
    result = []
    for row, bound in zip(rows, population["rows"]):
        _need(type(row) is dict and set(row) == {"id", "source_group", "source_raw", "context_raw", "target_raw", "conditioning"}
              and row["id"] == bound["id"] and row["source_group"] == bound["source_group"],
              "closed rows must preserve the complete population order and groups")
        for name, maximum in (("source", 65536), ("context", 524288), ("target", 16384)):
            raw = row[name + "_raw"]
            _need(type(raw) is bytes and 0 < len(raw) <= maximum
                  and hashlib.sha256(raw).hexdigest() == bound[name + "_sha256"], name + " population identity differs")
        try:
            text = row["source_raw"].decode("utf-8")
        except UnicodeError as error:
            raise CompactContentTrainingError("source must be exact UTF8") from error
        _need(bool(text.strip()) and "\x00" not in text, "nonempty ordinary fixture source required")
        vector = row["conditioning"]
        _need(type(vector) is list and len(vector) == 384 and all(
            type(number) in (int, float) and math.isfinite(number) and abs(number) <= 1e8 for number in vector),
            "bounded plain384 conditioning required")
        _need(head._digest(vector) == bound["conditioning_sha256"], "conditioning population identity differs")
        numeric = head._conditioning(vector)
        encoded = loaded["modules"]["tokens"].encode_compact_content_tokens_v1(
            row["target_raw"], row["context_raw"], expected_content_sha256=bound["target_sha256"],
            expected_context_sha256=bound["context_sha256"], codec=codec, expected_codec_sha256=codec_sha)
        ids = encoded["target_ids"]
        _need(type(ids) is list and 3 <= len(ids) <= 512 and ids[0] == 1 and ids[-1] == 2
              and all(type(token) is int and 3 <= token < 537 for token in ids[1:-1]),
              "public compact complete target framing differs")
        result.append({"id": row["id"], "conditioning": numeric, "target_ids": ids})
    return result


def _learning_rate(value):
    _need(type(value) in (int, float) and math.isfinite(value) and 0 < value <= 0.1,
          "learning rate must be a finite plain number in (0, 0.1]")
    return float(value)


def _optimizer_policy(optimizer, learning_rate):
    expected = {"lr": learning_rate, "betas": (0.9, 0.999), "eps": 1e-8, "weight_decay": 0,
                "amsgrad": False, "maximize": False, "foreach": False, "capturable": False,
                "differentiable": False, "fused": None}
    if "decoupled_weight_decay" in optimizer.defaults:
        expected["decoupled_weight_decay"] = False
    _need(optimizer.defaults == expected and len(optimizer.param_groups) == 1,
          "existing default Adam policy differs")
    for key, value in expected.items():
        _need(optimizer.param_groups[0][key] == value, "optimizer group policy differs")
    return {"name": "Adam", "defaults": {key: list(value) if type(value) is tuple else value
                                            for key, value in expected.items()}, "gradient_clip_l2": 5.0,
            "batch_size": 1, "row_order": "population_order_repeated", "objective": "compact_token_cross_entropy"}


def _optimizer_state(value, progress, config, head):
    _need(type(value) is dict and set(value) == {"schema", "parameters"}
          and value["schema"] == "adam-default-betas-eps/v1" and type(value["parameters"]) is dict,
          "closed named Adam state required")
    parameters, steps = value["parameters"], progress["optimizer_steps"]
    _need(set(parameters) == (set(head._shapes(config)) if steps else set()), "complete named Adam state inventory differs")
    for state in parameters.values():
        _need(type(state) is dict and set(state) == {"step", "exp_avg", "exp_avg_sq"}
              and type(state["step"]) is int and state["step"] == steps, "named Adam step differs from progress")
    if steps:
        for field in ("exp_avg", "exp_avg_sq"):
            head._state({name: state[field] for name, state in parameters.items()}, config)
        def nonnegative(value):
            return all(nonnegative(child) for child in value) if type(value) is list else value >= 0
        _need(all(nonnegative(state["exp_avg_sq"]) for state in parameters.values()), "Adam second moments must be nonnegative")


def _checkpoint(offered, expected, head, loaded):
    _hash(expected, "complete v2 checkpoint")
    value = head._copy(offered, MAX_CHECKPOINT_BYTES)
    _need(head._digest(value, MAX_CHECKPOINT_BYTES) == expected, "independent v2 checkpoint identity differs")
    fields = {"schema", "profile", "architecture", "input_dimension", "input_role", "codec", "codec_sha256",
              "max_total_ids", "config", "optimizer_config", "optimizer_policy", "parameter_order", "runtime", "implementation",
              "initial_checkpoint", "initial_checkpoint_sha256", "initial_weights_sha256", "model_state", "weights_sha256",
              "optimizer_state", "progress", "parent_checkpoint_sha256", "population_raw_utf8", "population_sha256",
              "population_count", "authority", "training_mask", "evaluation_gold_mask", "limitations"}
    _need(type(value) is dict and set(value) == fields, "closed v2 training checkpoint required")
    _need(value["schema"] == SCHEMA and value["profile"] == PROFILE and value["architecture"] == head.ARCHITECTURE
          and type(value["input_dimension"]) is int and value["input_dimension"] == 384
          and value["input_role"] == "caller_supplied_unverified_conditioning_vector"
          and type(value["max_total_ids"]) is int and value["max_total_ids"] == 512,
          "compact training profile or geometry differs")
    _need(value["implementation"] == _implementation(), "training implementation pins differ")
    _need(head._wire(value["runtime"], 32768) == head._wire(_runtime(head, loaded), 32768), "resume runtime differs")
    initial = head.validate_compact_content_head_v1(value["initial_checkpoint"],
                expected_checkpoint_sha256=value["initial_checkpoint_sha256"])
    _need(value["config"] == initial["config"] and head._wire(value["config"], 1024) == head._wire(initial["config"], 1024),
          "initial model configuration changed")
    _need(value["initial_weights_sha256"] == initial["weights_sha256"], "permanent initial weights commitment differs")
    fixed, codec_sha = head._codec(loaded, value["codec"])
    _need(value["codec_sha256"] == codec_sha == initial["codec_sha256"], "fixed compact codec differs")
    _need(type(value["optimizer_config"]) is dict and set(value["optimizer_config"]) == {"learning_rate"}
          and type(value["optimizer_config"]["learning_rate"]) is float,
          "closed optimizer configuration required")
    _learning_rate(value["optimizer_config"]["learning_rate"])
    _need(type(value["population_raw_utf8"]) is str, "retained exact population UTF8 required")
    population = _population(value["population_raw_utf8"].encode("utf-8"), value["population_sha256"], head)
    count = len(population["rows"])
    _need(type(value["population_count"]) is int and value["population_count"] == count, "population count differs")
    progress = value["progress"]
    _need(type(progress) is dict and set(progress) == {"optimizer_steps", "epochs_completed", "row_cursor"}
          and all(type(number) is int for number in progress.values())
          and 0 <= progress["optimizer_steps"] <= MAX_TOTAL_STEPS
          and progress["epochs_completed"] == progress["optimizer_steps"] // count
          and progress["row_cursor"] == progress["optimizer_steps"] % count,
          "complete deterministic row/epoch/step progress differs")
    _need(type(value["parameter_order"]) is list and value["parameter_order"] == list(head._shapes(value["config"])),
          "fixed named parameter order differs")
    head._state(value["model_state"], value["config"])
    _need(value["weights_sha256"] == head._digest(value["model_state"]), "current weights identity differs")
    _optimizer_state(value["optimizer_state"], progress, value["config"], head)
    if progress["optimizer_steps"]:
        _hash(value["parent_checkpoint_sha256"], "immediate v2 parent")
    else:
        _need(value["parent_checkpoint_sha256"] is None and value["weights_sha256"] == value["initial_weights_sha256"],
              "zero-step checkpoint must retain unchanged initialization")
    _need(value["authority"] == _AUTHORITY and all(flag is False for flag in value["authority"].values())
          and type(value["training_mask"]) is int and value["training_mask"] == 0
          and type(value["evaluation_gold_mask"]) is int and value["evaluation_gold_mask"] == 0
          and value["limitations"] == _LIMITATIONS, "engineering authority boundary differs")
    return value, population


def _restore(value, head, loaded):
    numerical, torch = loaded["modules"]["numerical"], head._torch(loaded)
    numerical._implementation()
    rng = torch.get_rng_state().clone()
    try:
        model = numerical._model({"dimension": 384}, {"target_vocabulary": value["codec"]["vocabulary"]}, value["config"])
        templates = model.state_dict()
        _need(list(templates) == value["parameter_order"], "restored model parameter order differs")
        state = {name: numerical._tensor(value["model_state"][name], template, name) for name, template in templates.items()}
        model.load_state_dict(state, strict=True)
        optimizer = numerical._optimizer(model, value["optimizer_config"])
        policy = _optimizer_policy(optimizer, value["optimizer_config"]["learning_rate"])
        _need(head._wire(policy, 4096) == head._wire(value["optimizer_policy"], 4096), "exact Adam policy differs")
        for name, parameter in model.named_parameters():
            state = value["optimizer_state"]["parameters"].get(name)
            if state is not None:
                optimizer.state[parameter] = {
                    "step": torch.tensor(float(state["step"]), dtype=torch.float32, device="cpu"),
                    "exp_avg": numerical._tensor(state["exp_avg"], parameter, name + ".exp_avg"),
                    "exp_avg_sq": numerical._tensor(state["exp_avg_sq"], parameter, name + ".exp_avg_sq", nonnegative=True)}
        packed_weights, packed_optimizer = numerical._pack(model, optimizer)
        _need(packed_weights == value["model_state"] and packed_optimizer == value["optimizer_state"],
              "named float32 restoration changed weights or Adam state")
        return model, optimizer
    finally:
        _need(torch.equal(rng, torch.get_rng_state()), "model restoration changed ambient CPU RNG")


def build_compact_content_training_v2(initial_checkpoint, population_raw, rows, *,
                                      expected_initial_checkpoint_sha256, expected_population_sha256, learning_rate=0.001):
    """Freeze a complete authored fixture population and fresh Adam around v1 weights."""
    def work(data, head, loaded):
        initial = head.validate_compact_content_head_v1(data["initial_checkpoint"],
                    expected_checkpoint_sha256=data["expected_initial_checkpoint_sha256"])
        population = _population(data["population_raw"], data["expected_population_sha256"], head)
        _rows(data["rows"], population, initial["codec"], initial["codec_sha256"], head, loaded)
        lr = _learning_rate(data["learning_rate"])
        model = head._model(initial, loaded)
        numerical = loaded["modules"]["numerical"]
        optimizer = numerical._optimizer(model, {"learning_rate": lr})
        weights, moments = numerical._pack(model, optimizer)
        value = {"schema": SCHEMA, "profile": PROFILE, "architecture": head.ARCHITECTURE,
            "input_dimension": 384, "input_role": "caller_supplied_unverified_conditioning_vector",
            "codec": initial["codec"], "codec_sha256": initial["codec_sha256"], "max_total_ids": 512,
            "config": initial["config"], "optimizer_config": {"learning_rate": lr},
            "optimizer_policy": _optimizer_policy(optimizer, lr), "parameter_order": [name for name, _ in model.named_parameters()],
            "runtime": _runtime(head, loaded), "implementation": _implementation(),
            "initial_checkpoint": initial, "initial_checkpoint_sha256": data["expected_initial_checkpoint_sha256"],
            "initial_weights_sha256": initial["weights_sha256"], "model_state": weights, "weights_sha256": head._digest(weights),
            "optimizer_state": moments, "progress": {"optimizer_steps": 0, "epochs_completed": 0, "row_cursor": 0},
            "parent_checkpoint_sha256": None, "population_raw_utf8": data["population_raw"].decode("utf-8"),
            "population_sha256": data["expected_population_sha256"], "population_count": len(population["rows"]),
            "authority": dict(_AUTHORITY), "training_mask": 0, "evaluation_gold_mask": 0, "limitations": list(_LIMITATIONS)}
        _checkpoint(value, head._digest(value, MAX_CHECKPOINT_BYTES), head, loaded)
        return value
    return _operation(dict(initial_checkpoint=initial_checkpoint, population_raw=population_raw, rows=rows,
        expected_initial_checkpoint_sha256=expected_initial_checkpoint_sha256,
        expected_population_sha256=expected_population_sha256, learning_rate=learning_rate), work)


def compact_content_training_sha256(checkpoint):
    """Bounded canonical JSON identity; no numerical restoration or validation."""
    head, pin = _head()
    captured = head._copy(checkpoint, MAX_CHECKPOINT_BYTES)
    result = head._digest(captured, MAX_CHECKPOINT_BYTES)
    _need(_sources() == pin and head._digest(checkpoint, MAX_CHECKPOINT_BYTES) == result,
          "checkpoint or source changed during hashing")
    return result


def validate_compact_content_training_v2(checkpoint, *, expected_checkpoint_sha256):
    """Validate the full successor contract, then restore named model and Adam state."""
    def work(data, head, loaded):
        value, _ = _checkpoint(data["checkpoint"], data["expected_checkpoint_sha256"], head, loaded)
        _restore(value, head, loaded)
        return value
    return _operation(dict(checkpoint=checkpoint, expected_checkpoint_sha256=expected_checkpoint_sha256), work)


def compact_content_training_bytes_v2(checkpoint, *, expected_checkpoint_sha256):
    """Return complete validated canonical transport bytes, without writing a file."""
    def work(data, head, loaded):
        value, _ = _checkpoint(data["checkpoint"], data["expected_checkpoint_sha256"], head, loaded)
        _restore(value, head, loaded)
        return head._wire(value, MAX_CHECKPOINT_BYTES)
    return _operation(dict(checkpoint=checkpoint, expected_checkpoint_sha256=expected_checkpoint_sha256), work, as_bytes=True)


def load_compact_content_training_v2(checkpoint_raw, *, expected_raw_sha256):
    """Check independent transport bytes, reject duplicate keys, and restore v2 state."""
    def work(data, head, loaded):
        offered = _parse(data["checkpoint_raw"], data["expected_raw_sha256"], MAX_CHECKPOINT_BYTES, "checkpoint", head)
        value, _ = _checkpoint(offered, head._digest(offered, MAX_CHECKPOINT_BYTES), head, loaded)
        _restore(value, head, loaded)
        return value
    return _operation(dict(checkpoint_raw=checkpoint_raw, expected_raw_sha256=expected_raw_sha256), work)


def train_compact_content_v2(checkpoint, population_raw, rows, *, expected_checkpoint_sha256,
                             expected_population_sha256, max_optimizer_steps, max_seconds=60):
    """Apply at most sixteen sequential one-row compact CE updates; retain exact resume.

    Deadlines are soft checks before complete batches. Callers own admission and
    process limits. A zero-update call returns the identical checkpoint value.
    """
    started = time.monotonic()
    def work(data, head, loaded):
        _need(type(data["max_optimizer_steps"]) is int and 0 <= data["max_optimizer_steps"] <= MAX_STEPS_PER_CALL,
              "optimizer step budget must be a plain integer in 0..16")
        _need(type(data["max_seconds"]) in (int, float) and math.isfinite(data["max_seconds"])
              and 0 <= data["max_seconds"] <= 300, "soft batch deadline must be in 0..300 seconds")
        deadline = started + data["max_seconds"]
        value, population = _checkpoint(data["checkpoint"], data["expected_checkpoint_sha256"], head, loaded)
        _need(data["expected_population_sha256"] == value["population_sha256"]
              and type(data["population_raw"]) is bytes
              and data["population_raw"] == value["population_raw_utf8"].encode("utf-8"),
              "resume requires the unchanged complete original population bytes")
        prepared = _rows(data["rows"], population, value["codec"], value["codec_sha256"], head, loaded)
        _need(value["progress"]["optimizer_steps"] + data["max_optimizer_steps"] <= MAX_TOTAL_STEPS,
              "cumulative optimizer step bound exceeded")
        model, optimizer = _restore(value, head, loaded)
        torch, numerical = head._torch(loaded), loaded["modules"]["numerical"]
        groups = {"projection": [parameter for name, parameter in model.named_parameters() if name.startswith("projection_")],
                  "decoder": [parameter for name, parameter in model.named_parameters() if not name.startswith("projection_")]}
        progress, history = dict(value["progress"]), []
        maximum = {"projection": 0.0, "decoder": 0.0, "formula_to_projection": 0.0}
        optimizer_seconds, token_count = 0.0, 0
        stopped = "optimizer_step_budget"
        for _ in range(data["max_optimizer_steps"]):
            if time.monotonic() >= deadline:
                stopped = "deadline_before_batch"
                break
            row = prepared[progress["row_cursor"]]
            batch_started = time.monotonic()
            vector = torch.tensor([row["conditioning"]], dtype=torch.float32, device="cpu")
            target = torch.tensor([row["target_ids"]], dtype=torch.long, device="cpu")
            model.train()
            optimizer.zero_grad(set_to_none=True)
            projected, logits = model(vector, target[:, :-1])
            _need(list(logits.shape) == [1, len(row["target_ids"]) - 1, 537]
                  and list(projected.shape) == [1, 384]
                  and bool(torch.isfinite(logits).all()) and bool(torch.isfinite(projected).all()),
                  "invalid compact teacher-forced numerical output")
            labels = target[:, 1:]
            loss = torch.nn.functional.cross_entropy(logits.reshape(-1, 537), labels.reshape(-1), ignore_index=0)
            _need(bool(torch.isfinite(loss)), "nonfinite compact cross-entropy")
            formula_gradients = torch.autograd.grad(loss, groups["projection"], retain_graph=True)
            _need(all(bool(torch.isfinite(gradient).all()) for gradient in formula_gradients), "nonfinite formula-to-projection gradient")
            maximum["formula_to_projection"] = max(maximum["formula_to_projection"], numerical._norm(formula_gradients))
            loss.backward()
            for name, parameters in groups.items():
                _need(all(parameter.grad is not None and bool(torch.isfinite(parameter.grad).all()) for parameter in parameters),
                      "missing or nonfinite compact gradient")
                maximum[name] = max(maximum[name], numerical._norm(parameter.grad for parameter in parameters))
            torch.nn.utils.clip_grad_norm_(list(model.parameters()), 5.0, error_if_nonfinite=True)
            optimizer.step()
            _need(all(bool(torch.isfinite(parameter).all()) for parameter in model.parameters())
                  and all(bool(torch.isfinite(item).all()) for state in optimizer.state.values()
                          for item in state.values() if torch.is_tensor(item)), "nonfinite updated model or Adam state")
            batch_seconds = time.monotonic() - batch_started
            optimizer_seconds += batch_seconds
            tokens = len(row["target_ids"]) - 1
            token_count += tokens
            progress["optimizer_steps"] += 1
            progress["row_cursor"] += 1
            if progress["row_cursor"] == len(prepared):
                progress["epochs_completed"] += 1
                progress["row_cursor"] = 0
            history.append({"step": progress["optimizer_steps"], "row_id": row["id"], "token_count": tokens,
                            "token_cross_entropy": float(loss.detach()), "optimizer_seconds": batch_seconds})
        weights, moments = numerical._pack(model, optimizer)
        result = head._copy(value, MAX_CHECKPOINT_BYTES)
        if history:
            result.update(model_state=weights, weights_sha256=head._digest(weights), optimizer_state=moments,
                          progress=progress, parent_checkpoint_sha256=data["expected_checkpoint_sha256"])
        _checkpoint(result, head._digest(result, MAX_CHECKPOINT_BYTES), head, loaded)
        evidence = {}
        for group in groups:
            names = [name for name in value["model_state"] if name.startswith("projection_") == (group == "projection")]
            before = {name: value["model_state"][name] for name in names}
            after = {name: weights[name] for name in names}
            evidence[group] = {"gradient_norm_max": maximum[group],
                "initial_parameters_sha256": head._digest(before), "final_parameters_sha256": head._digest(after),
                "parameter_update_l2": numerical._norm(torch.tensor(after[name], dtype=torch.float64)
                    - torch.tensor(before[name], dtype=torch.float64) for name in names)}
        report = {"schema": REPORT_SCHEMA, "profile": PROFILE, "checkpoint_sha256": head._digest(result, MAX_CHECKPOINT_BYTES),
            "parent_checkpoint_sha256": data["expected_checkpoint_sha256"], "population_sha256": value["population_sha256"],
            "population_count": len(prepared), "training_executed": bool(history), "optimizer_steps": len(history),
            "progress": dict(progress), "stopped_reason": stopped, "teacher_forcing": True,
            "objective": "compact_token_cross_entropy", "token_count": token_count, "batch_losses": history,
            "parameter_evidence": evidence, "formula_projection_gradient_norm_max": maximum["formula_to_projection"],
            "optimizer_seconds": optimizer_seconds, "elapsed_seconds": time.monotonic() - started,
            "optimizer_tokens_per_second": token_count / optimizer_seconds if optimizer_seconds else None,
            "clock_scope": "elapsed starts at public train entry; ends before final output serialization/custody checks; optimizer sums complete batch tensor/forward/backward/update checks",
            "deadline_scope": "soft before batches; preparation and in-flight work are not interrupted",
            "source_text_is_neural_input": False, "conditioning_producer_verified": False,
            "heldout_evaluated": False, "free_running_evaluated": False, "selection_performed": False,
            "encoder_sha256": None, "runtime": value["runtime"], "implementation": _implementation(),
            "authority": dict(_AUTHORITY), "training_mask": 0, "evaluation_gold_mask": 0, "limitations": list(_LIMITATIONS)}
        return {"checkpoint": result, "report": report}
    return _operation(dict(checkpoint=checkpoint, population_raw=population_raw, rows=rows,
        expected_checkpoint_sha256=expected_checkpoint_sha256, expected_population_sha256=expected_population_sha256,
        max_optimizer_steps=max_optimizer_steps, max_seconds=max_seconds), work)
