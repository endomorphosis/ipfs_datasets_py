"""Isolated numerical worker for the explicitly selected CodebaseIR profile.

This process consumes inert native target/state JSON. It never imports or runs
repository code, opens registry owners, promotes models, or produces proofs.
The parent owns wall/output/RSS bounds and cancellation through the existing
native tool lifecycle. Numerical v1 files remain unchanged for compatibility.
"""
from __future__ import annotations

import json
import math
from contextlib import redirect_stdout
from pathlib import Path
import sys

SCHEMA = "codebase-feature-worker@1"
MAX_BYTES = 32 * 1024 * 1024


def _wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("utf-8")


def _evaluate(features, runtime, targets):
    inference = runtime.infer(targets)
    vectors, identities, coverage = features._matrix(runtime.feature_space, targets)
    rows = inference["rows"]
    if [row["source_digest"] for row in rows] != identities:
        raise ValueError("native inference changed evaluation source order")
    losses = []
    for vector, row in zip(vectors, rows):
        decoded = [value for name in runtime.feature_space["projection_ids"]
                   for value in row["reconstructed_projection_features"][name]]
        if len(decoded) != len(vector):
            raise ValueError("native inference changed feature layout")
        losses.append(sum((left - right) ** 2 for left, right in zip(vector, decoded)) / len(vector))
    if not all(math.isfinite(value) for value in losses):
        raise ValueError("nonfinite diagnostic reconstruction")
    return {"source_digests": identities, "mean_squared_errors": losses,
            "mean_squared_error": sum(losses) / len(losses), "coverage": coverage,
            "inference": inference, "used_for_selection": False,
            "semantic_or_property_evaluation": False}


def execute(request):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_projection_features as features
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import codebase_runtime_8d as runtimes
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_modality_contracts import ModalityContract
    expected = {"schema", "action", "contract", "feature_space", "base_state", "training_targets",
                "tuning_targets", "canary_targets", "replay_targets", "epochs",
                "learning_rate", "seed", "max_seconds"}
    if type(request) is not dict or set(request) != expected or request["schema"] != SCHEMA:
        raise ValueError("closed CodebaseIR numerical worker request required")
    if type(request["action"]) is not str or request["action"] not in {"train", "infer"}:
        raise ValueError("unknown native worker action")
    import torch
    # One reserved CPU slot. BLAS environment bounds also precede this import.
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    contract = ModalityContract.from_dict(request["contract"])
    runtime = runtimes.open_runtime("codebase_ir", runtimes.CODEBASE_SOURCE_FEATURE_VERSION,
        contract=contract, feature_space=request["feature_space"], state=request["base_state"])
    if request["action"] == "infer":
        if runtime.state is None:
            raise ValueError("inference requires an exact registered state")
        return {"schema": SCHEMA, "inference": runtime.infer(request["training_targets"]),
                "training_executed": False, "proof_authority": False}
    if request["action"] != "train":
        raise ValueError("unknown native worker action")
    before = None if runtime.state is None else _evaluate(features, runtime, request["canary_targets"])
    result = runtime.train(request["training_targets"], validation_samples=request["tuning_targets"],
        epochs=request["epochs"], learning_rate=request["learning_rate"], seed=request["seed"],
        max_seconds=request["max_seconds"])
    after = _evaluate(features, runtime, request["canary_targets"])
    replay = _evaluate(features, runtime, request["replay_targets"])
    return {"schema": SCHEMA, "result": result,
            "canary_before": before, "canary_after": after, "replay_after": replay,
            "worker": {"python": sys.version.split()[0], "torch": torch.__version__,
                       "device": "cpu", "dtype": "float64", "cpu_threads": 1,
                       "repository_code_executed": False, "registry_opened": False,
                       "training_executed": True, "proof_authority": False}}


def main():
    # -I isolates invocation from working-tree import shadowing. Select exactly
    # the package containing this installed worker, never a caller module path.
    # The universal runner resolves executable symlinks to their native binary,
    # which strips a venv's interpreter prefix. The parent supplies its exact
    # installed library paths (not repository or caller-selected import paths).
    if len(sys.argv) != 2:
        raise ValueError("exact installed Python library paths required")
    libraries = json.loads(sys.argv[1])
    if (type(libraries) is not list or not 1 <= len(libraries) <= 2
            or any(type(path) is not str or not Path(path).is_absolute()
                   or not Path(path).is_dir() for path in libraries)):
        raise ValueError("exact installed Python library paths required")
    sys.path[:0] = libraries
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    raw = sys.stdin.buffer.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("numerical worker input exceeds byte bound")
    # Native imports can print tree-pin diagnostics. Reserve stdout exclusively
    # for the protocol response and retain those diagnostics on stderr.
    with redirect_stdout(sys.stderr):
        response = execute(json.loads(raw))
    result = _wire(response)
    if len(result) > MAX_BYTES:
        raise ValueError("numerical worker result exceeds byte bound")
    sys.stdout.buffer.write(result)


if __name__ == "__main__":
    main()
