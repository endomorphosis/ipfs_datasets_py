#!/usr/bin/env python3
"""Measure cold bridge-on evaluation or a bounded, in-memory projection epoch.

Run each measurement in a fresh process. This never saves model weights and
never reports an admit. The three gate sentences are an in-sample speed fixture,
not a held-out canary or evidence that the Constitution is formalized.
"""

from __future__ import annotations

import argparse
import cProfile
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import pstats
import sys
import time


REPO_ROOT = Path(__file__).resolve().parents[3]
PINNED_STATE = REPO_ROOT / "workspace/todo-queues/legal-ir-daemon-restart12-20260608T075001Z-best-8h-autoencoder.state.json"
PINNED_SHA256 = "1446cb1859ddf4ed40fb5576f6e320eece4cec268a008c5c07bffeaf959cd8dd"
BRIDGE_NAMES = (
    "modal_frame_logic", "deontic_norms", "fol_tdfol", "cec_dcec", "external_prover_router",
)
GATE_SENTENCES = (
    ("backup", "Company A shall submit backup report within 10 days unless emergency."),
    ("prohibit", "The agency shall not disclose records."),
    ("minimum", "The officer shall retain the file for at least 20 days."),
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("evaluate", "train"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--profile", action="store_true", help="Diagnostic only: cProfile overhead can affect bridge timeouts.")
    parser.add_argument("--projection-profile", action="store_true", help="Record the training phase wall-clock profile.")
    args = parser.parse_args()
    if args.output.exists():
        parser.error(f"Refusing to overwrite existing receipt: {args.output}")

    # Set these before imports. Never rely on the editable HACC installation.
    sys.path.insert(0, str(REPO_ROOT))
    os.environ["IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE"] = "0"
    os.environ["IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI"] = "0"
    os.environ["CUDA_VISIBLE_DEVICES"] = ""
    from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree
    from ipfs_datasets_py.logic.deontic import formula_builder
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_autoencoder
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import build_us_code_sample
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.projection_profiler import ProjectionProfiler

    resolved = require_workspace_logic_tree()
    for name, module in (("formula_builder", formula_builder), ("autoencoder", modal_autoencoder)):
        path = Path(module.__file__).resolve()
        if REPO_ROOT not in path.parents:
            raise RuntimeError(f"Refusing drifted {name}: {path}")
        resolved[name] = str(path)
    state_hash = _sha256(PINNED_STATE)
    if state_hash != PINNED_SHA256:
        raise RuntimeError("Pinned restart12 checkpoint hash changed")
    if modal_autoencoder._LEGAL_IR_TARGET_CACHE:
        raise RuntimeError("Run this benchmark in a fresh process: target cache is already warm")

    source_hashes = {str(Path(path).relative_to(REPO_ROOT)): _sha256(Path(path)) for path in resolved.values()}
    started = time.perf_counter()
    state = modal_autoencoder.ModalAutoencoderTrainingState.load_json(PINNED_STATE)
    load_seconds = time.perf_counter() - started
    started = time.perf_counter()
    model = modal_autoencoder.AdaptiveModalAutoencoder(state=state)
    initialization_seconds = time.perf_counter() - started
    started = time.perf_counter()
    samples = [build_us_code_sample(title="gate", section=section, text=text) for section, text in GATE_SENTENCES]
    sample_seconds = time.perf_counter() - started
    common = dict(legal_ir_bridge_names=BRIDGE_NAMES, legal_ir_evaluate_provers=False, legal_ir_parallel_workers=1)
    projection_settings = dict(epochs=1, max_seconds=180, max_line_search_attempts=1,
                               projection_max_update_families=1, projection_update_backend="python_sparse_batch")
    profile = cProfile.Profile() if args.profile else None
    started = time.perf_counter()
    if profile is not None:
        profile.enable()
    try:
        if args.mode == "evaluate":
            result = asdict(model.evaluate(samples, use_sample_memory=False, **common))
            target_count = result["legal_ir_target_count"]
        else:
            result = model.train_generalizable_projection(
                samples, validation_samples=samples, **common, **projection_settings,
                projection_profiler=ProjectionProfiler() if args.projection_profile else None,
            )
            target_count = result["after"]["legal_ir_target_count"]
    finally:
        if profile is not None:
            profile.disable()
    elapsed = time.perf_counter() - started
    if _sha256(PINNED_STATE) != state_hash:
        raise RuntimeError("Pinned checkpoint changed during measurement")
    receipt = {
        "schema": "legal-autoformal-speed-v1", "mode": args.mode,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "elapsed_seconds": elapsed, "seconds_per_sample": elapsed / len(samples),
        "state_load_seconds": load_seconds, "model_init_seconds": initialization_seconds,
        "sample_build_seconds": sample_seconds, "sample_count": len(samples),
        "samples": [dict(section=section, text=text) for section, text in GATE_SENTENCES],
        "bridge_names": list(BRIDGE_NAMES), "legal_ir_evaluate_provers": False,
        "disk_cache": "0", "process_cold": True, "target_cache_initial_entries": 0,
        "legal_ir_parallel_workers": 1, "use_sample_memory": False,
        "cuda_visible_devices": "", "profile_enabled": args.profile,
        "lazy_install_ergoai": "0",
        "source_hashes": source_hashes, "resolved_modules": resolved,
        "state_path": str(PINNED_STATE), "state_sha256": state_hash,
        "projection_settings": projection_settings if args.mode == "train" else None,
        "optimizer_step": args.mode == "train", "admitted": False,
        "corpus": "three_gate_sentences_not_a_held_out_canary", "result": result,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation also protects against concurrent receipt writers.
    with args.output.open("x") as stream:
        json.dump(receipt, stream, indent=2, sort_keys=True)
        stream.write("\n")
    if profile is not None:
        profile.dump_stats(str(args.output) + ".prof")
        with Path(str(args.output) + ".profile.txt").open("x") as stream:
            pstats.Stats(profile, stream=stream).strip_dirs().sort_stats("cumtime").print_stats(60)
    print(json.dumps({"receipt": str(args.output), "mode": args.mode, "elapsed_seconds": elapsed,
                      "legal_ir_target_count": target_count, "admitted": False}))
    if target_count != len(samples):
        raise RuntimeError(f"Expected three bridge targets; observed {target_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
