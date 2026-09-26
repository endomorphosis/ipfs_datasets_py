#!/usr/bin/env python3
"""Time the daemon's full-sample bridge evaluation on the pinned checkpoint.

The two-pass mode disables only the native evaluator reuse guard. Both modes
evaluate the same three gate sentences with all five metric bridges. Optional
warm pairs isolate reconstruction work after the genuine targets are cached;
those timings must not be reported as cold compiler timings. No state is saved.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from statistics import median
import sys
from time import perf_counter


REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))
os.environ["IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE"] = "0"
os.environ["IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI"] = "0"
os.environ["CUDA_VISIBLE_DEVICES"] = ""

from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree  # noqa: E402
from ipfs_datasets_py.logic.deontic import formula_builder  # noqa: E402
from ipfs_datasets_py.logic.deontic.utils import deontic_parser  # noqa: E402
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_autoencoder as model  # noqa: E402
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import uscode_modal_daemon_runner as runner  # noqa: E402
from scripts.ops.legal_ir.evaluate_daemon_state_bridge import (  # noqa: E402
    BRIDGE_NAMES,
    DEFAULT_STATE,
    gate_samples,
)


PINNED_STATE_SHA256 = "1446cb1859ddf4ed40fb5576f6e320eece4cec268a008c5c07bffeaf959cd8dd"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mode", choices=("reuse", "two-pass"), default="reuse")
    parser.add_argument("--warm-pairs", type=int, default=0)
    args = parser.parse_args()
    if os.path.lexists(args.output):
        parser.error("--output already exists; refusing to overwrite any existing artifact")
    require_workspace_logic_tree()
    samples = gate_samples()
    state_bytes = DEFAULT_STATE.read_bytes()
    state_hash = hashlib.sha256(state_bytes).hexdigest()
    if state_hash != PINNED_STATE_SHA256:
        raise RuntimeError("Pinned restart12 checkpoint hash changed")
    autoencoder = model.AdaptiveModalAutoencoder(
        state=model.ModalAutoencoderTrainingState.from_dict(json.loads(state_bytes))
    )
    native_evaluate = autoencoder.evaluate

    def measure(mode: str):
        # An evaluator adapter retains the old two-pass wrapper contract.
        autoencoder.evaluate = (
            native_evaluate
            if mode == "reuse"
            else lambda *rows, **kwargs: native_evaluate(*rows, **kwargs)
        )
        started = perf_counter()
        evaluation = runner.evaluate_autoencoder_with_bounded_metric_bridges(
            autoencoder,
            samples,
            legal_ir_bridge_names=BRIDGE_NAMES,
            legal_ir_evaluate_provers=False,
            legal_ir_parallel_workers=1,
            max_bridge_sample_text_chars=0,
            use_sample_memory=False,
        )
        elapsed = perf_counter() - started
        if evaluation.legal_ir_target_count != len(samples):
            raise RuntimeError("Bridge measurement did not produce all three genuine targets")
        return elapsed, evaluation

    source_hashes = {
        name: hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
        for name, module in (
            ("modal_autoencoder", model),
            ("runner", runner),
            ("formula_builder", formula_builder),
            ("deontic_parser", deontic_parser),
        )
    }
    elapsed, evaluation = measure(args.mode)
    result = {
        "admitted": False,
        "bridge_names": list(BRIDGE_NAMES),
        "cache_cold_process": True,
        "elapsed_seconds": elapsed,
        "evaluation": evaluation.to_dict(),
        "legal_ir_evaluate_provers": False,
        "legal_ir_parallel_workers": 1,
        "legal_ir_target_count": evaluation.legal_ir_target_count,
        "max_bridge_sample_text_chars": 0,
        "metric_disk_cache": False,
        "mode": args.mode,
        "optimizer_step": False,
        "sample_count": len(samples),
        "source_sha256": source_hashes,
        "state_path": str(DEFAULT_STATE),
        "state_sha256": state_hash,
        "use_sample_memory": False,
        "wall_seconds_per_sample": elapsed / len(samples),
    }
    if args.warm_pairs > 0:
        measurements: dict[str, list[float]] = {"two-pass": [], "reuse": []}
        for index in range(args.warm_pairs):
            modes = ("two-pass", "reuse") if index % 2 == 0 else ("reuse", "two-pass")
            for mode in modes:
                seconds, repeated = measure(mode)
                if repeated.to_dict() != evaluation.to_dict():
                    raise RuntimeError("Repeated bridge evaluations changed metrics")
                measurements[mode].append(seconds)
        result["warm_comparison"] = {
            "all_evaluations_exactly_equal": True,
            "cache_cold_process": False,
            "in_process_bridge_cache": "warm",
            "measurements_seconds": measurements,
            "median_seconds": {mode: median(values) for mode, values in measurements.items()},
        }
    if hashlib.sha256(DEFAULT_STATE.read_bytes()).hexdigest() != state_hash:
        raise RuntimeError("Pinned checkpoint changed during measurement")
    result["checkpoint_unchanged"] = True
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({key: value for key, value in result.items() if key != "evaluation"}))


if __name__ == "__main__":
    main()
