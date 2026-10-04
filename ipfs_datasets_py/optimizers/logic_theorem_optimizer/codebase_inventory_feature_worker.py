"""Isolated finite-shard structural inference with operation-scoped reuse.

This additive profile retains the native v1 contract, feature basis, state and
numerical result.  Its optimization prepares private CPU float64 tensors and
the vocabulary once for this process.  ``optimized=False`` evaluates every
shard through the existing v1 numerical implementation.  Both modes replay
each restored native target independently at this receiving boundary.

There is no fitting, repository execution, registry owner, formula decoder,
proof authority, promotion, or cache surviving this finite invocation.  The
parent owns cancellation, process-tree draining and live source fences.
"""
from __future__ import annotations

from contextlib import redirect_stdout
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import re
import sys
import time

SCHEMA = "codebase-inventory-feature-worker@1"
MAX_BYTES = 32 * 1024 * 1024
MAX_SHARDS = 64
MAX_ROWS_PER_SHARD = 16
MAX_TARGET_BYTES = 4 * 1024 * 1024
MAX_SECONDS = 600.0
_LIMIT_KEYS = {"max_shards", "max_rows_per_shard", "max_target_bytes",
               "max_input_bytes", "max_output_bytes"}


def _wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("utf-8")


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _json_pairs(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, "duplicate worker JSON key")
        result[key] = value
    return result


def _json_constant(value):
    raise ValueError("nonfinite worker JSON constant: " + value)


@dataclass(frozen=True, slots=True)
class InventoryVocabulary:
    """A detached in-process vocabulary; never a trust or source token."""

    domain: str
    projection_ids: tuple
    descriptors: dict
    tokens: tuple
    known_tokens: tuple
    column_indices: tuple


def prepare_inventory_vocabulary(feature_space):
    """Prepare ordered columns without importing Torch or opening an owner.

    The numerical engine separately validates the complete feature contract.
    A coordinator may use this helper to classify zero-coverage entries
    before packing shards; compatibility does not grant any authority.
    """
    from . import autoencoder_projection_features as features

    space = features._plain(feature_space)
    ids, columns = space.get("projection_ids"), space.get("columns")
    _require(type(ids) is list and bool(ids) and all(type(name) is str for name in ids)
             and ids == sorted(set(ids)), "canonical projection IDs required")
    _require(type(columns) is list and 1 <= len(columns) <= features.MAX_FEATURES
             and all(type(row) is list and len(row) == 2 and row[0] in ids
                     and type(row[1]) is str for row in columns)
             and columns == sorted(columns)
             and len({tuple(row) for row in columns}) == len(columns),
             "canonical bounded feature columns required")
    _require(type(space.get("domain_id")) is str
             and type(space.get("projections")) is dict
             and set(space["projections"]) == set(ids), "projection descriptors required")
    tokens = tuple(tuple(token for projection, token in columns if projection == name)
                   for name in ids)
    _require(all(tokens), "every projection requires fitted columns")
    return InventoryVocabulary(space["domain_id"], tuple(ids), space["projections"],
        tokens, tuple(frozenset(block) for block in tokens),
        tuple(tuple(index for index, (projection, _) in enumerate(columns) if projection == name)
              for name in ids))


def _projection_rows(vocabulary, targets):
    from . import autoencoder_projection_features as features

    _require(type(vocabulary) is InventoryVocabulary, "prepared in-process vocabulary required")
    rows, sources, descriptors = features._rows(targets, vocabulary.domain,
                                                vocabulary.projection_ids)
    _require(descriptors == vocabulary.descriptors,
             "target projections differ from fitted feature space")
    return rows, sources


def _coverage(vocabulary, row):
    return [{"projection_id": name,
             "known_atoms": sum(value for token, value in row[name].items() if token in known),
             "unknown_atoms": sum(value for token, value in row[name].items() if token not in known)}
            for name, known in zip(vocabulary.projection_ids, vocabulary.known_tokens)]


def inventory_target_coverage(vocabulary, target):
    """Return the native coverage calculation and explicit zero-vocabulary status."""
    rows, _ = _projection_rows(vocabulary, [target])
    coverage = _coverage(vocabulary, rows[0])
    return {"compatible": all(row["known_atoms"] > 0 for row in coverage),
            "coverage": coverage}


def _matrix(vocabulary, targets):
    # Preserve the exact v1 summation order, log1p and normalization arithmetic.
    rows, sources = _projection_rows(vocabulary, targets)
    values, coverage = [], []
    for row in rows:
        vector = []
        coverage.extend(_coverage(vocabulary, row))
        for name, tokens in zip(vocabulary.projection_ids, vocabulary.tokens):
            block = [math.log1p(row[name][token]) for token in tokens]
            norm = math.sqrt(sum(value * value for value in block))
            _require(norm > 0, "projection has no coverage in the training feature space")
            vector.extend(value / norm for value in block)
        values.append(vector)
    return values, sources, coverage


def _validate_profile(contract, space, adapter):
    _require(contract.domain == "codebase_ir"
             and contract.ir_schema == adapter.CODEBASE_TARGET_SCHEMA,
             "source-bound CodebaseIR contract required")
    _require(set(space.get("projection_ids", ())) <= {
        adapter.CODEBASE_PROGRAM_PROJECTION, adapter.CODEBASE_CONTRACTS_PROJECTION},
        "source-bound CodebaseIR feature basis contains an unsupported projection")
    _require(contract.adapter.identifier == "native-domain-target-adapter"
             and contract.adapter.version == "1" and contract.optimizer.version == "1"
             and re.fullmatch(r"1:latent-([1-9]|[1-5][0-9]|6[0-4])", contract.state_codec.version),
             "implementation labels differ from the source-bound native v1 profile")
    _require(contract.adapter.sha256 == hashlib.sha256(Path(adapter.__file__).read_bytes()).hexdigest(),
             "installed native target adapter differs from contract")


class _PreparedProjectionEngine:
    """Private finite-operation numerical state with no training interface."""

    def __init__(self, features, torch, contract, space, state, vocabulary):
        self._features, self._torch = features, torch
        self._contract, self._space, self._vocabulary = contract, space, vocabulary
        self._state_sha = features.digest(state)
        self._space_sha = features.digest(space)
        self._parameters = tuple(torch.tensor(value, dtype=torch.float64, device="cpu")
                                 for value in state["parameters"])

    def infer(self, values, sources, coverage):
        torch = self._torch
        encoder, bias, decoder, output_bias = self._parameters
        with torch.no_grad():
            inputs = torch.tensor(values, dtype=torch.float64, device="cpu")
            latent = torch.tanh(inputs @ encoder + bias)
            decoded = latent @ decoder + output_bias
            _require(bool(torch.isfinite(latent).all()) and bool(torch.isfinite(decoded).all()),
                     "nonfinite inference output")
            rows = []
            for index, source in enumerate(sources):
                projections = {
                    name: [float(decoded[index, column]) for column in columns]
                    for name, columns in zip(self._vocabulary.projection_ids,
                                             self._vocabulary.column_indices)}
                rows.append({"source_digest": source, "latent": latent[index].tolist(),
                             "reconstructed_projection_features": projections})
        return {"schema": "native-projection-feature-inference/v1",
                "contract_sha256": self._contract.sha256,
                "state_sha256": self._state_sha, "feature_space_sha256": self._space_sha,
                "rows": rows, "coverage": coverage, "training_executed": False,
                "decoded_formulas_generated": False,
                "representation": "native_compiler_structural_features_not_semantic_text_embeddings",
                **self._features.FALSE}


def _validate_request(request, input_bytes):
    expected = {"schema", "optimized", "contract", "feature_space", "state",
                "shared_inventory", "shards", "limits", "max_seconds"}
    _require(type(request) is dict and set(request) == expected and request["schema"] == SCHEMA,
             "closed finite inventory numerical worker request required")
    _require(type(request["optimized"]) is bool, "optimized must be a boolean")
    limits = request["limits"]
    _require(type(limits) is dict and set(limits) == _LIMIT_KEYS,
             "closed finite inventory worker limits required")
    ceilings = {"max_shards": MAX_SHARDS, "max_rows_per_shard": MAX_ROWS_PER_SHARD,
                "max_target_bytes": MAX_TARGET_BYTES, "max_input_bytes": MAX_BYTES,
                "max_output_bytes": MAX_BYTES}
    _require(all(type(limits[name]) is int and 0 < limits[name] <= ceiling
                 for name, ceiling in ceilings.items()), "invalid finite worker limit")
    _require(input_bytes <= limits["max_input_bytes"], "numerical worker input exceeds byte bound")
    maximum = request["max_seconds"]
    _require(type(maximum) in (int, float) and math.isfinite(maximum)
             and 0 < maximum <= MAX_SECONDS, "bounded finite inference duration required")
    shards = request["shards"]
    _require(type(shards) is list and 1 <= len(shards) <= limits["max_shards"],
             "bounded nonempty finite shard list required")
    for index, shard in enumerate(shards):
        _require(type(shard) is dict and set(shard) == {"shard_index", "targets"}
                 and type(shard["shard_index"]) is int and shard["shard_index"] == index,
                 "canonical ordered finite shards required")
        targets = shard["targets"]
        _require(type(targets) is list and 1 <= len(targets) <= limits["max_rows_per_shard"],
                 "bounded nonempty target shard required")
        _require(all(type(target) is dict for target in targets), "compact native target mappings required")


def execute(request, *, _input_bytes=None):
    """Evaluate exactly one bounded request; optimized reuse is opt-out."""
    started = time.monotonic()
    stages = {}
    counters = {name: 0 for name in (
        "shared_inventory_validations", "target_restorations", "native_target_replays",
        "matrix_builds", "vocabulary_builds", "weight_tensor_builds", "input_tensor_builds",
        "contract_validations", "state_validations", "rows", "shards")}
    replay_names = ("shared_replay_preparations", "target_replay_attempts", "target_replays",
        "source_digest_checks", "ast_digest_checks", "authored_contract_replays",
        "native_lowering_replays", "full_target_comparisons",
        "shared_manifest_parses_avoided", "shared_receipt_parses_avoided")
    counters.update({"replay_" + name: 0 for name in replay_names})

    def timed(name, operation):
        began = time.monotonic()
        try:
            return operation()
        finally:
            stages[name] = stages.get(name, 0.0) + time.monotonic() - began

    def check_time():
        _require(time.monotonic() - started < request["max_seconds"],
                 "finite inventory inference exceeded duration bound")

    input_bytes = len(_wire(request)) if _input_bytes is None else _input_bytes
    _require(type(input_bytes) is int and input_bytes >= 0, "exact worker input byte count required")
    timed("request_validation", lambda: _validate_request(request, input_bytes))

    def native_imports():
        from . import autoencoder_projection_features as features
        from .autoencoder_modality_contracts import ModalityContract
        from ...logic.software_contracts import codebase_ir_targets as adapter
        from ...logic.software_contracts import codebase_inventory_targets as transport
        import torch
        return features, ModalityContract, adapter, transport, torch

    features, ModalityContract, adapter, transport, torch = timed("native_imports", native_imports)
    # One reserved CPU slot, with BLAS environment bounds owned by the parent.
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    check_time()
    contract = timed("contract_decode", lambda: ModalityContract.from_dict(request["contract"]))
    space = timed("feature_space_detach", lambda: features._plain(request["feature_space"]))
    state = timed("state_detach", lambda: features._plain(request["state"]))
    timed("source_profile_validation", lambda: _validate_profile(contract, space, adapter))
    shared = timed("shared_inventory_validation",
        lambda: transport.validate_shared_inventory_envelope(request["shared_inventory"]))
    counters["shared_inventory_validations"] += 1
    optimized = request["optimized"]
    engine = vocabulary = None
    replay_context = replay_counts = None
    if optimized:
        from ...logic.software_contracts import codebase_inventory_replay as native_replay
        replay_counts = native_replay.InventoryReplayCounters()
        replay_context = timed("native_replay_preparation",
            lambda: native_replay.prepare_inventory_replay(shared, counters=replay_counts))
        timed("contract_validation", lambda: features._contract(contract, space))
        counters["contract_validations"] += 1
        timed("state_validation", lambda: features._validate_state(contract, space, state))
        counters["state_validations"] += 1
        vocabulary = timed("vocabulary_preparation", lambda: prepare_inventory_vocabulary(space))
        counters["vocabulary_builds"] += 1
        engine = timed("weight_tensor_preparation",
            lambda: _PreparedProjectionEngine(features, torch, contract, space, state, vocabulary))
        counters["weight_tensor_builds"] += 4
    seen_sources, outputs = set(), []
    for shard in request["shards"]:
        check_time()
        targets = []
        for compact in shard["targets"]:
            check_time()
            target = timed("target_restoration", lambda: transport.restore_inventory_target(shared, compact))
            counters["target_restorations"] += 1
            _require(len(target.canonical_bytes) <= request["limits"]["max_target_bytes"],
                     "restored native target exceeds requested byte bound")
            if optimized:
                target = timed("native_target_replay", lambda: native_replay.validate_inventory_codebase_target(
                    target, replay_context, counters=replay_counts))
            else:
                target = timed("native_target_replay", lambda: adapter.validate_codebase_targets(target))
                for name in ("target_replay_attempts", "target_replays", "source_digest_checks",
                             "authored_contract_replays", "native_lowering_replays", "full_target_comparisons"):
                    counters["replay_" + name] += 1
            counters["native_target_replays"] += 1
            value = target.to_dict()
            if not optimized and value["validation"][0]["details"]["captured_ast"] is not None:
                counters["replay_ast_digest_checks"] += 1
            _require(value["ready_for_training"] is True,
                     "native target is not ready for structural feature inference")
            source = value["source_digest"]
            _require(source not in seen_sources, "duplicate source in finite inventory invocation")
            seen_sources.add(source)
            targets.append(target)
        check_time()
        if optimized:
            values, sources, coverage = timed("feature_matrix", lambda: _matrix(vocabulary, targets))
            inference = timed("numerical_inference", lambda: engine.infer(values, sources, coverage))
        else:
            # This is the real v1 reference, including its per-shard state
            # validation, vocabulary construction and four weight tensors.
            inference = timed("reference_inference",
                lambda: features.infer_projection_features(contract, space, state, targets))
            counters["contract_validations"] += 1
            counters["state_validations"] += 1
            counters["vocabulary_builds"] += 1
            counters["weight_tensor_builds"] += 4
        counters["matrix_builds"] += 1
        counters["input_tensor_builds"] += 1
        counters["rows"] += len(targets)
        counters["shards"] += 1
        expected_sources = [target.to_dict()["source_digest"] for target in targets]
        _require([row["source_digest"] for row in inference["rows"]] == expected_sources,
                 "native inference changed finite source order")
        outputs.append({"shard_index": shard["shard_index"], "inference": inference})
        check_time()
    if replay_counts is not None:
        counters.update({"replay_" + name: value for name, value in replay_counts.to_dict().items()})
    response = {"schema": SCHEMA, "optimized": optimized, "shards": outputs,
        "metrics": {"counters": counters, "stage_seconds": stages,
                    "elapsed_seconds": time.monotonic() - started,
                    "time_scope": "execute_before_final_protocol_serialization_and_write"},
        "worker": {"python": sys.version.split()[0], "torch": torch.__version__,
                   "device": "cpu", "dtype": "float64", "cpu_threads": 1,
                   "repository_code_executed": False, "registry_opened": False,
                   "training_executed": False, "proof_authority": False,
                   "decoded_formulas_generated": False}}
    result = timed("response_bound_serialization", lambda: _wire(response))
    _require(len(result) <= request["limits"]["max_output_bytes"],
             "numerical worker result exceeds byte bound")
    response["metrics"]["elapsed_seconds"] = time.monotonic() - started
    check_time()
    # The accounting fields added above also consume protocol bytes.  Check
    # the final response, including them, for direct execute callers as well.
    _require(len(_wire(response)) <= request["limits"]["max_output_bytes"],
             "numerical worker result exceeds byte bound")
    return response


def main():
    # Match the existing isolated worker's installed-library selection.  The
    # script path chooses its package; no caller-selected repository import.
    if len(sys.argv) != 2:
        raise ValueError("exact installed Python library paths required")
    libraries = json.loads(sys.argv[1], object_pairs_hook=_json_pairs,
                           parse_constant=_json_constant)
    if (type(libraries) is not list or not 1 <= len(libraries) <= 2
            or any(type(path) is not str or not Path(path).is_absolute()
                   or not Path(path).is_dir() for path in libraries)):
        raise ValueError("exact installed Python library paths required")
    sys.path[:0] = libraries
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    raw = sys.stdin.buffer.read(MAX_BYTES + 1)
    _require(len(raw) <= MAX_BYTES, "numerical worker input exceeds byte bound")
    request = json.loads(raw, object_pairs_hook=_json_pairs, parse_constant=_json_constant)
    # The -I script is not imported as a package.  Set its own package only
    # after choosing the installed source root, retaining relative imports.
    global __package__
    __package__ = "ipfs_datasets_py.optimizers.logic_theorem_optimizer"
    with redirect_stdout(sys.stderr):
        response = execute(request, _input_bytes=len(raw))
    result = _wire(response)
    _require(len(result) <= request["limits"]["max_output_bytes"],
             "numerical worker result exceeds byte bound")
    sys.stdout.buffer.write(result)


if __name__ == "__main__":
    main()


__all__ = ["SCHEMA", "InventoryVocabulary", "prepare_inventory_vocabulary",
           "inventory_target_coverage", "execute"]
