"""Isolated root-bound full-native-target page inference, without fitting.

The complete target envelope is independently replayed by the unchanged source
adapter. Reuse covers frozen vocabulary/weights for one bounded page only. No
caller-selected compact inventory token, owner database, repository import,
training, semantic decoder or planner authority is accepted.
"""
from __future__ import annotations

from contextlib import redirect_stdout
import json
import math
from pathlib import Path
import sys
import time

SCHEMA = "codebase-inventory-resume-worker@1"
MAX_BYTES = 32 * 1024 * 1024
MAX_OUTPUT_BYTES = 16 * 1024 * 1024
MAX_SECONDS = 600.0


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("utf-8")


def _json_pairs(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, "duplicate worker JSON key")
        result[key] = value
    return result


def _json_constant(value):
    raise ValueError("nonfinite worker JSON constant: " + value)


def _validate_request(request, input_bytes):
    _require(type(request) is dict and set(request) == {"schema", "root_cid", "root", "optimized", "contract",
        "feature_space", "state", "targets", "member_indices", "max_seconds", "limits"}
        and request["schema"] == SCHEMA and type(request["optimized"]) is bool, "closed root-bound worker request required")
    limits = request["limits"]
    _require(type(limits) is dict and set(limits) == {"max_rows", "max_target_bytes", "max_input_bytes", "max_output_bytes"},
             "closed page worker limits required")
    for key, ceiling in (("max_rows", 64), ("max_target_bytes", 4 * 1024 * 1024),
                         ("max_input_bytes", MAX_BYTES), ("max_output_bytes", MAX_OUTPUT_BYTES)):
        _require(type(limits[key]) is int and 0 < limits[key] <= ceiling, "bounded worker limits required")
    _require(type(input_bytes) is int and 0 <= input_bytes <= limits["max_input_bytes"], "worker input exceeds byte bound")
    seconds = request["max_seconds"]
    _require(type(seconds) in {int, float} and math.isfinite(seconds) and 0 < seconds <= MAX_SECONDS, "bounded page duration required")
    values, indices = request["targets"], request["member_indices"]
    _require(type(values) is list and 1 <= len(values) <= limits["max_rows"] and all(type(value) is dict for value in values),
             "bounded nonempty full native target list required")
    _require(type(indices) is list and len(indices) == len(values)
             and all(type(index) is int and 0 <= index < 1024 for index in indices)
             and indices == sorted(set(indices)), "ordered exact page member indices required")
    _require(all(len(_wire(value)) <= limits["max_target_bytes"] for value in values), "full native target exceeds byte bound")


def _replay_target(value, optimized):
    """Detach a binding from this operation's freshly native-rebuilt envelope."""
    from ...logic.software_contracts import codebase_ir_targets as adapter
    from ...logic.formalization.autoencoder.domain_targets import DomainTargetEnvelope
    _require(type(optimized) is bool, "exact native replay opt-out required")
    target = adapter.validate_codebase_targets(DomainTargetEnvelope.from_dict(value))
    validated = target.to_dict()
    if optimized:
        details = validated["validation"][0]["details"]
        binding = {**details["source_binding"], "authored_contracts": details["authored_contracts"]}
    else:
        binding = adapter.source_binding_from_target(target)
    return target, validated, binding


def execute(request, *, _input_bytes=None):
    input_bytes = len(_wire(request)) if _input_bytes is None else _input_bytes
    _validate_request(request, input_bytes)
    started = time.monotonic()
    def checkpoint():
        _require(time.monotonic() - started < request["max_seconds"], "page inference exceeded duration bound")
    from . import autoencoder_projection_features as features
    from . import codebase_inventory_feature_worker as numerical
    from .autoencoder_modality_contracts import ModalityContract
    from ...logic.software_contracts import codebase_inventory_resume as resume
    from ...logic.software_contracts import codebase_ir_targets as adapter
    from ...logic.software_contracts.codebase_ir import CodebaseIRManifest

    root = resume.CodebaseScanResumeRoot.from_dict(request["root_cid"], request["root"])
    r = root.to_dict()
    _require(request["optimized"] is r["optimized"], "root opt-out differs")
    expected_limits = {"max_rows": r["limits"]["page_entries"], "max_target_bytes": r["limits"]["max_target_bytes"],
        "max_input_bytes": r["limits"]["max_input_bytes"], "max_output_bytes": r["limits"]["max_output_bytes"]}
    _require(request["limits"] == expected_limits, "root numerical limits differ")
    indices = request["member_indices"]
    _require(indices[-1] < len(r["members"]) and indices[0] // expected_limits["max_rows"]
             == indices[-1] // expected_limits["max_rows"], "targets cross root page boundary")
    contract = ModalityContract.from_dict(request["contract"])
    space, state = features._plain(request["feature_space"]), features._plain(request["state"])
    numerical._validate_profile(contract, space, adapter)
    features._contract(contract, space)
    features._validate_state(contract, space, state)
    _require(contract.sha256 == r["model"]["contract_sha256"]
             and features.digest(space) == r["model"]["feature_space_sha256"]
             and features.digest(state) == r["model"]["state_sha256"]
             and state["latent_width"] == r["model"]["latent_width"]
             and len(space["columns"]) == r["model"]["feature_columns"]
             and space["projection_ids"] == r["model"]["projection_ids"], "root frozen model/basis differs")
    targets, sources = [], set()
    for value, index in zip(request["targets"], indices):
        checkpoint()
        target, v, binding = _replay_target(value, request["optimized"])
        _require(len(target.canonical_bytes) <= request["limits"]["max_target_bytes"], "native target exceeds bound")
        _require(v["ready_for_training"] is True and resume._wire(binding["head"]) == resume._wire(r["head"]),
                 "complete native target/head required")
        member = r["members"][index]
        _require(binding["source_key"] == member["source_key"] and binding["entry"]["entry_cid"] == member["entry_cid"]
                 and binding["source_cid"] == member["source_cid"] and binding["ast_cid"] == member["ast_cid"],
                 "exact root page target membership differs")
        native_manifest = CodebaseIRManifest.from_dict(v["validation"][0]["details"]["manifest"])
        _require(resume._wire(resume._members(native_manifest)) == resume._wire(r["members"]),
                 "full native manifest/global membership differs")
        _require(v["source_digest"] not in sources, "duplicate native source target")
        sources.add(v["source_digest"])
        targets.append(target)
        checkpoint()
    # Dependency import follows the complete inert/native protocol replay.
    import torch
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    checkpoint()
    if request["optimized"]:
        vocabulary = numerical.prepare_inventory_vocabulary(space)
        values, source_ids, coverage = numerical._matrix(vocabulary, targets)
        engine = numerical._PreparedProjectionEngine(features, torch, contract, space, state, vocabulary)
        inference = engine.infer(values, source_ids, coverage)
    else:
        inference = features.infer_projection_features(contract, space, state, targets)
    _require([row["source_digest"] for row in inference["rows"]]
             == [target.to_dict()["source_digest"] for target in targets], "native numerical source order differs")
    response = {"schema": SCHEMA, "optimized": request["optimized"], "inference": inference,
        "counters": {"native_target_replays": (1 if request["optimized"] else 2) * len(targets),
            "matrix_builds": 1, "vocabulary_builds": 1,
            "weight_tensor_builds": 4, "input_tensor_builds": 1,
            "contract_validations": 1 if request["optimized"] else 2,
            "state_validations": 1 if request["optimized"] else 2, "rows": len(targets), "training_calls": 0},
        "worker": {"python": sys.version.split()[0], "torch": torch.__version__, "device": "cpu", "dtype": "float64",
            "cpu_threads": 1, "repository_code_executed": False, "registry_opened": False,
            "training_executed": False, "proof_authority": False, "decoded_formulas_generated": False}}
    checkpoint()
    _require(len(_wire(response)) <= request["limits"]["max_output_bytes"], "page numerical output exceeds bound")
    return response


def main():
    if len(sys.argv) != 2:
        raise ValueError("exact installed Python library paths required")
    libraries = json.loads(sys.argv[1], object_pairs_hook=_json_pairs, parse_constant=_json_constant)
    _require(type(libraries) is list and 1 <= len(libraries) <= 2
             and all(type(path) is str and Path(path).is_absolute() and Path(path).is_dir() for path in libraries),
             "exact installed Python library paths required")
    sys.path[:0] = libraries
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    raw = sys.stdin.buffer.read(MAX_BYTES + 1)
    _require(len(raw) <= MAX_BYTES, "page worker input exceeds byte bound")
    request = json.loads(raw, object_pairs_hook=_json_pairs, parse_constant=_json_constant)
    global __package__
    __package__ = "ipfs_datasets_py.optimizers.logic_theorem_optimizer"
    with redirect_stdout(sys.stderr):
        response = execute(request, _input_bytes=len(raw))
    result = _wire(response)
    _require(len(result) <= request["limits"]["max_output_bytes"], "page worker output exceeds byte bound")
    sys.stdout.buffer.write(result)


if __name__ == "__main__":
    main()
