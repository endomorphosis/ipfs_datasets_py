"""Private CPU numerical worker for bounded CodebaseIR feature candidates.

The parent owns admission, native process limits, source observation and model
publication. Only inert captured targets and numerical state enter this process.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
import sys

MAX_BYTES = 16 * 1024 * 1024
REQUEST_SCHEMA = "codebase-feature-worker-request@1"
RESULT_SCHEMA = "codebase-feature-worker-result@1"


def _memory_observation():
    """Sample this worker's Linux peaks without inherited getrusage maxima."""
    fields = {"VmHWM": "peak_resident_bytes", "VmPeak": "peak_virtual_bytes",
              "VmRSS": "resident_bytes", "VmSize": "virtual_bytes"}
    result = {"measurement": "unavailable", "scope": "worker_process_only",
              "phase": "after_training_before_response_serialization",
              **{name: None for name in fields.values()}}
    try:
        with Path("/proc/self/status").open("rb") as stream:
            raw = stream.read(16385)
        if len(raw) > 16384:
            return result
        observed = {}
        for line in raw.decode("ascii").splitlines():
            key, _, value = line.partition(":")
            if key in fields:
                parts = value.split()
                if (key in observed or len(parts) != 2 or parts[1] != "kB"
                        or not parts[0].isdigit() or len(parts[0]) > 20):
                    return result
                observed[key] = int(parts[0]) * 1024
        if set(observed) == set(fields):
            result.update(measurement="linux_proc_self_status",
                          **{fields[key]: value for key, value in observed.items()})
    except (OSError, UnicodeError, ValueError):
        pass
    return result


def execute(request):
    from ..formalization.autoencoder import codebase_targets
    from ...optimizers.logic_theorem_optimizer import autoencoder_projection_features as features
    from ...optimizers.logic_theorem_optimizer.autoencoder_modality_contracts import ModalityContract
    from ...optimizers.logic_theorem_optimizer.autoencoder_runtime_registry import CodebaseFeatureRuntime

    if (type(request) is not dict or set(request) != {
            "schema", "contract", "feature_space", "base_state", "training", "tuning", "canary", "options"}
            or request["schema"] != REQUEST_SCHEMA):
        raise ValueError("closed CodebaseIR numerical request required")
    if len(features._raw(request)) > MAX_BYTES:
        raise ValueError("CodebaseIR worker input exceeds bound")
    contract = ModalityContract.from_dict(request["contract"])
    space = request["feature_space"]
    if (contract.domain != "codebase_ir" or type(space) is not dict
            or type(space.get("columns")) is not list or not 1 <= len(space["columns"]) <= 512):
        raise ValueError("bounded CodebaseIR feature basis required")
    options = request["options"]
    if (type(options) is not dict or set(options) != {"epochs", "latent_width", "learning_rate", "max_seconds", "seed"}
            or type(options["latent_width"]) is not int or options["latent_width"] != 8
            or type(options["epochs"]) is not int or not 1 <= options["epochs"] <= 8
            or type(options["seed"]) is not int or not 0 <= options["seed"] < 2**31
            or type(options["learning_rate"]) not in (int, float)
            or not math.isfinite(options["learning_rate"]) or not 0 < options["learning_rate"] <= .1
            or type(options["max_seconds"]) not in (int, float)
            or not math.isfinite(options["max_seconds"]) or not 0 < options["max_seconds"] <= 120):
        raise ValueError("closed bounded 8D numerical options required")
    # Validate the pinned adapter, exact feature profile, authority fields and
    # any numerical parent before loading the tensor runtime. This constructor
    # has no model-registry or database access.
    runtime = CodebaseFeatureRuntime(contract=contract, feature_space=space, state=request["base_state"])
    if runtime.describe()["latent_width"] != 8:
        raise ValueError("closed bounded 8D numerical options required")
    groups = {}
    for role in ("training", "tuning", "canary"):
        rows = request[role]
        if type(rows) is not list or not 1 <= len(rows) <= 16:
            raise ValueError("each role needs 1–16 bounded targets")
        from ..formalization.autoencoder.domain_targets import DomainTargetEnvelope
        groups[role] = [codebase_targets.validate_codebase_targets(DomainTargetEnvelope.from_dict(row)) for row in rows]
    if sum(len(rows) for rows in groups.values()) > 32:
        raise ValueError("cohort exceeds 32 bounded targets")
    all_ids = [row.source_digest for group in groups.values() for row in group]
    if len(set(all_ids)) != len(all_ids):
        raise ValueError("duplicate source across numerical roles")
    paths, source_hashes = set(), set()
    for rows in groups.values():
        for row in rows:
            evidence = row.to_dict()["validation"][0]["details"]
            path = evidence["inputs"]["contract"]["path"]
            source_hash = evidence["binding"]["source_sha256"]
            if path in paths or source_hash in source_hashes:
                raise ValueError("duplicate captured source or path across numerical roles")
            paths.add(path)
            source_hashes.add(source_hash)
    # Filtering novel literals can collapse different semantics to one vector.
    # Every role therefore requires full coverage of the frozen training basis.
    for role, rows in groups.items():
        _, _, coverage = features._matrix(space, rows)
        if any(row["unknown_atoms"] for row in coverage):
            raise ValueError(f"new {role} atoms require an explicit feature-basis migration")

    import torch
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    result = features.train_projection_features(contract, space, groups["training"], groups["tuning"],
        base_state=request["base_state"], **options)
    values, _, _ = features._matrix(space, groups["canary"])

    def canary(state):
        observation = features.infer_projection_features(contract, space, state, groups["canary"])
        losses = {}
        for name in space["projection_ids"]:
            positions = [i for i, (projection, _) in enumerate(space["columns"]) if projection == name]
            errors = []
            for expected, row in zip(values, observation["rows"]):
                predicted = row["reconstructed_projection_features"][name]
                errors.extend((expected[index] - actual) ** 2 for index, actual in zip(positions, predicted))
            losses[name] = sum(errors) / len(errors)
        return {"mean_squared_error": losses, "inference": observation}

    before = None if request["base_state"] is None else canary(request["base_state"])
    after = canary(result["state"])
    accepted = before is None or all(after["mean_squared_error"][name] <= value + 1e-12
                                    for name, value in before["mean_squared_error"].items())
    return {"schema": RESULT_SCHEMA, "request_sha256": features.digest(request), "result": result,
            "canary_before": before, "canary_after": after, "canary_nonregression": accepted,
            "canary_gate": "initial_baseline" if before is None else "parent_nonregression",
            "runtime": {"python": sys.version, "torch": torch.__version__, "device": "cpu",
                        "intraop_threads": torch.get_num_threads(), "interop_threads": torch.get_num_interop_threads(),
                        "memory": _memory_observation()},
            "training_executed": True, "decoded_formulas_generated": False, **features.FALSE}


def main():
    path = Path("request.json")
    if path.stat().st_size > MAX_BYTES:
        raise ValueError("CodebaseIR worker input exceeds bound")
    with path.open("rb") as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("CodebaseIR worker input grew beyond bound")
    response = execute(json.loads(raw))
    encoded = json.dumps(response, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    if len(encoded) > MAX_BYTES:
        raise ValueError("CodebaseIR worker output exceeds bound")
    Path("response.json").write_bytes(encoded)


if __name__ == "__main__":
    main()
