"""Root-bound shared transport with one restored native target at a time.

This additive worker retains the existing CPU float64 numerical arithmetic and
complete native lowering/equality checks. A receiver validates the captured
manifest and publication receipt once, then restores each compact target only
while extracting that target's feature row. Only bounded numerical rows,
source identities and coverage survive to the next target. Torch is imported
after all inert and native checks succeed. No training, repository execution,
registry access, semantic decoding or proof authority is provided.
"""
from __future__ import annotations

from contextlib import redirect_stdout
import json
import math
from pathlib import Path
import sys
import time

SCHEMA = "codebase-inventory-resume-shared-worker@1"
MAX_BYTES = 32 * 1024 * 1024
MAX_OUTPUT_BYTES = 16 * 1024 * 1024
MAX_TARGET_BYTES = 4 * 1024 * 1024
MAX_FEATURE_CELLS = 262144
MAX_SECONDS = 600.0
_LIMIT_FIELDS = {"max_rows", "max_target_bytes", "max_input_bytes", "max_output_bytes",
                 "max_feature_cells", "max_retained_restored_targets"}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode("utf-8")


def _json_pairs(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, "duplicate worker JSON key")
        result[key] = value
    return result


def _json_constant(value):
    raise ValueError("nonfinite worker JSON constant: " + value)


def _validate_request(request, input_bytes):
    _require(type(request) is dict and set(request) == {"schema", "root_cid", "root", "optimized",
        "contract", "feature_space", "state", "shared_inventory", "targets", "member_indices",
        "max_seconds", "limits"} and request["schema"] == SCHEMA
        and type(request["optimized"]) is bool, "closed root-bound shared worker request required")
    limits = request["limits"]
    _require(type(limits) is dict and set(limits) == _LIMIT_FIELDS,
             "closed shared page worker limits required")
    for key, ceiling in (("max_rows", 64), ("max_target_bytes", MAX_TARGET_BYTES),
                         ("max_input_bytes", MAX_BYTES), ("max_output_bytes", MAX_OUTPUT_BYTES)):
        _require(type(limits[key]) is int and 0 < limits[key] <= ceiling,
                 "bounded shared worker limits required")
    _require(type(limits["max_feature_cells"]) is int
             and limits["max_feature_cells"] == MAX_FEATURE_CELLS
             and type(limits["max_retained_restored_targets"]) is int
             and limits["max_retained_restored_targets"] == 1,
             "fixed streaming feature and restored-target bounds required")
    _require(type(input_bytes) is int and 0 <= input_bytes <= limits["max_input_bytes"],
             "shared worker input exceeds byte bound")
    seconds = request["max_seconds"]
    _require(type(seconds) in {int, float} and math.isfinite(seconds)
             and 0 < seconds <= MAX_SECONDS, "bounded shared page duration required")
    values, indices = request["targets"], request["member_indices"]
    _require(type(values) is list and 1 <= len(values) <= limits["max_rows"]
             and all(type(value) is dict for value in values),
             "bounded nonempty compact native target list required")
    _require(type(indices) is list and len(indices) == len(values)
             and all(type(index) is int and 0 <= index < 1024 for index in indices)
             and indices == sorted(set(indices)), "ordered exact page member indices required")
    _require(type(request["shared_inventory"]) is dict, "plain shared native inventory required")
    _require(all(len(_wire(value)) <= limits["max_target_bytes"] for value in values),
             "compact native target exceeds byte bound")


def _stream_feature_row(compact, index, *, shared, replay, replay_counts, optimized,
                        root, vocabulary, target_bound, counters, transport, numerical, legacy):
    """Restore, replay and detach one row; no target escapes this stack frame.

    Native lowering may transiently rebuild the target being checked. Neither
    that reconstruction nor a full target dictionary is kept for another row.
    The retention counter describes restored input envelopes, not transient
    dictionaries or the receiver-owned shared inventory.
    """
    target = transport.restore_resume_target(shared, compact)
    counters["target_restorations"] += 1
    counters["max_retained_restored_targets"] = 1
    _require(len(target.canonical_bytes) <= target_bound, "restored native target exceeds byte bound")
    if optimized:
        target = transport.validate_resume_target(target, replay, counters=replay_counts)
        value = target.to_dict()
        details = value["validation"][0]["details"]
        binding = details["source_binding"]
    else:
        # This unchanged opt-out performs two genuine full native replays:
        # validation followed by source_binding_from_target's validation.
        native_value = target.to_dict()
        del target
        target, value, binding = legacy._replay_target(native_value, False)
        del native_value
        counters["native_target_replays"] += 2
        counters["native_lowering_replays"] += 2
        counters["full_target_comparisons"] += 2
    _require(len(target.canonical_bytes) <= target_bound, "native target exceeds byte bound")
    _require(value["ready_for_training"] is True
             and _wire(binding["head"]) == _wire(root["head"]),
             "complete native target/head required")
    member = root["members"][index]
    _require(binding["source_key"] == member["source_key"]
             and binding["entry"]["entry_cid"] == member["entry_cid"]
             and binding["source_cid"] == member["source_cid"]
             and binding["ast_cid"] == member["ast_cid"],
             "exact root page target membership differs")
    values, sources, coverage = numerical._matrix(vocabulary, [target])
    _require(len(values) == len(sources) == 1 and sources == [value["source_digest"]],
             "streamed numerical source order differs")
    counters["streamed_feature_rows"] += 1
    del target, value, binding
    if optimized:
        del details
    else:
        # The unchanged legacy validators can leave collectable traceback
        # frames containing reconstructed envelopes. Drain those row-local
        # cycles before restoring the next input; optimized replay explicitly
        # clears its own locals and needs no forced collection.
        import gc
        gc.collect()
        counters["gc_collections"] += 1
    return values[0], sources[0], coverage


def execute(request, *, _input_bytes=None):
    input_bytes = len(_wire(request)) if _input_bytes is None else _input_bytes
    _validate_request(request, input_bytes)
    started = time.monotonic()

    def checkpoint():
        _require(time.monotonic() - started < request["max_seconds"],
                 "shared page inference exceeded duration bound")

    from . import autoencoder_projection_features as features
    from . import codebase_inventory_feature_worker as numerical
    from . import codebase_inventory_resume_worker as legacy
    from .autoencoder_modality_contracts import ModalityContract
    from ...logic.software_contracts import codebase_inventory_resume as resume
    from ...logic.software_contracts import codebase_ir_targets as adapter
    from ...logic.software_contracts import codebase_resume_shared_targets as transport

    counters = {name: 0 for name in ("shared_inventory_validations", "shared_manifest_parses",
        "shared_receipt_parses", "shared_replay_preparations", "target_restorations",
        "native_target_replays", "native_lowering_replays", "full_target_comparisons",
        "streamed_feature_rows", "matrix_builds", "vocabulary_builds", "weight_tensor_builds",
        "input_tensor_builds", "contract_validations", "state_validations", "rows", "training_calls",
        "max_retained_restored_targets", "gc_collections")}
    root = resume.CodebaseScanResumeRoot.from_dict(request["root_cid"], request["root"])
    r = root.to_dict()
    _require(r["limits"]["max_inventory_entries"] <= transport.MAX_INVENTORY_ENTRIES,
             "root exceeds the separate shared resume inventory profile")
    _require(request["optimized"] is r["optimized"], "root opt-out differs")
    expected_limits = {"max_rows": r["limits"]["page_entries"],
        "max_target_bytes": r["limits"]["max_target_bytes"],
        "max_input_bytes": r["limits"]["max_input_bytes"],
        "max_output_bytes": r["limits"]["max_output_bytes"],
        "max_feature_cells": MAX_FEATURE_CELLS, "max_retained_restored_targets": 1}
    _require(request["limits"] == expected_limits, "root shared numerical limits differ")
    indices = request["member_indices"]
    _require(indices[-1] < len(r["members"]) and indices[0] // expected_limits["max_rows"]
             == indices[-1] // expected_limits["max_rows"], "targets cross root page boundary")
    contract = ModalityContract.from_dict(request["contract"])
    space, state = features._plain(request["feature_space"]), features._plain(request["state"])
    numerical._validate_profile(contract, space, adapter)
    features._contract(contract, space)
    counters["contract_validations"] += 1
    features._validate_state(contract, space, state)
    counters["state_validations"] += 1
    _require(contract.sha256 == r["model"]["contract_sha256"]
             and features.digest(space) == r["model"]["feature_space_sha256"]
             and features.digest(state) == r["model"]["state_sha256"]
             and state["latent_width"] == r["model"]["latent_width"]
             and len(space["columns"]) == r["model"]["feature_columns"]
             and space["projection_ids"] == r["model"]["projection_ids"],
             "root frozen model/basis differs")
    _require(len(indices) * len(space["columns"]) <= request["limits"]["max_feature_cells"],
             "streamed feature matrix exceeds cell bound")
    checkpoint()
    shared = transport.validate_resume_shared_inventory(request["shared_inventory"])
    counters["shared_inventory_validations"] += 1
    counters["shared_manifest_parses"] += 1
    counters["shared_receipt_parses"] += 1
    _require(_wire(shared.head.to_dict()) == _wire(r["head"])
             and _wire(resume._members(shared.manifest)) == _wire(r["members"]),
             "shared native head/global membership differs from root")
    captured = shared.manifest.snapshot
    _require(captured.max_entries <= r["limits"]["max_inventory_entries"]
             and len(captured.entries) <= r["limits"]["max_inventory_entries"]
             and captured.max_file_bytes <= r["limits"]["max_file_bytes"]
             and len(resume.canonical_dag_json_bytes(shared.manifest.to_dict()))
                 <= r["limits"]["max_manifest_bytes"],
             "shared native capture exceeds root profile")
    replay = replay_counts = None
    if request["optimized"]:
        replay_counts = transport.InventoryReplayCounters()
        replay = transport.prepare_resume_replay(shared, counters=replay_counts)
    vocabulary = numerical.prepare_inventory_vocabulary(space)
    counters["vocabulary_builds"] += 1
    # One final matrix is assembled from independently streamed feature rows.
    # _matrix's one-row extraction retains the unchanged summation arithmetic.
    values, source_ids, coverage, sources = [], [], [], set()
    for compact, index in zip(request["targets"], indices):
        checkpoint()
        row, source, row_coverage = _stream_feature_row(compact, index,
            shared=shared, replay=replay, replay_counts=replay_counts, optimized=request["optimized"],
            root=r, vocabulary=vocabulary, target_bound=request["limits"]["max_target_bytes"],
            counters=counters, transport=transport, numerical=numerical, legacy=legacy)
        _require(source not in sources, "duplicate native source target")
        _require(len(row) == len(space["columns"]) and all(type(cell) is float and math.isfinite(cell)
             for cell in row), "exact finite streamed feature row required")
        sources.add(source)
        values.append(row)
        source_ids.append(source)
        coverage.extend(row_coverage)
        checkpoint()
    counters["matrix_builds"] += 1
    counters["rows"] = len(values)
    if replay_counts is not None:
        counters["shared_replay_preparations"] = replay_counts.shared_replay_preparations
        counters["native_target_replays"] = replay_counts.target_replays
        counters["native_lowering_replays"] = replay_counts.native_lowering_replays
        counters["full_target_comparisons"] = replay_counts.full_target_comparisons
    if not request["optimized"]:
        # Repeat the real legacy inference-boundary validation without retaining
        # full targets or creating a second vocabulary/matrix/tensor engine.
        features._contract(contract, space)
        counters["contract_validations"] += 1
        features._validate_state(contract, space, state)
        counters["state_validations"] += 1
    checkpoint()
    # Dependency import follows complete inert/native replay for every row.
    import torch
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    checkpoint()
    engine = numerical._PreparedProjectionEngine(features, torch, contract, space, state, vocabulary)
    counters["weight_tensor_builds"] += 4
    inference = engine.infer(values, source_ids, coverage)
    counters["input_tensor_builds"] += 1
    _require([row["source_digest"] for row in inference["rows"]] == source_ids,
             "native numerical source order differs")
    response = {"schema": SCHEMA, "optimized": request["optimized"], "inference": inference,
        "counters": counters,
        "worker": {"python": sys.version.split()[0], "torch": torch.__version__, "device": "cpu",
            "dtype": "float64", "cpu_threads": 1, "repository_code_executed": False,
            "registry_opened": False, "training_executed": False, "proof_authority": False,
            "decoded_formulas_generated": False}}
    checkpoint()
    _require(len(_wire(response)) <= request["limits"]["max_output_bytes"],
             "shared page numerical output exceeds byte bound")
    return response


def main():
    if len(sys.argv) != 2:
        raise ValueError("exact installed Python library paths required")
    libraries = json.loads(sys.argv[1], object_pairs_hook=_json_pairs, parse_constant=_json_constant)
    _require(type(libraries) is list and 1 <= len(libraries) <= 2
             and all(type(path) is str and Path(path).is_absolute() and Path(path).is_dir()
                     for path in libraries), "exact installed Python library paths required")
    sys.path[:0] = libraries
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    raw = sys.stdin.buffer.read(MAX_BYTES + 1)
    _require(len(raw) <= MAX_BYTES, "shared page worker input exceeds byte bound")
    request = json.loads(raw, object_pairs_hook=_json_pairs, parse_constant=_json_constant)
    global __package__
    __package__ = "ipfs_datasets_py.optimizers.logic_theorem_optimizer"
    with redirect_stdout(sys.stderr):
        response = execute(request, _input_bytes=len(raw))
    result = _wire(response)
    _require(len(result) <= request["limits"]["max_output_bytes"],
             "shared page worker output exceeds byte bound")
    sys.stdout.buffer.write(result)


if __name__ == "__main__":
    main()
