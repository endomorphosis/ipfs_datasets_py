#!/usr/bin/env python3
"""Train, persist, decode and Lake-check a bounded native formula candidate.

Uses existing local dependencies; never downloads models or promotes outputs.
Input JSON contains training_targets, tuning_targets and projection_ids.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
if (ROOT / "ipfs_datasets_py").is_dir():
    sys.path.insert(0, str(ROOT))


def _read(path):
    with Path(path).open("rb") as stream:
        raw = stream.read(8 * 1024 * 1024 + 1)
    if len(raw) > 8 * 1024 * 1024:
        raise ValueError("native training input exceeds 8 MiB")
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate native corpus key")
            result[key] = value
        return result
    def nonfinite(value):
        raise ValueError("nonfinite native corpus number")
    value = json.loads(raw, object_pairs_hook=pairs, parse_constant=nonfinite)
    if type(value) is not dict or set(value) != {"training_targets", "tuning_targets", "projection_ids"}:
        raise ValueError("closed native corpus requires training_targets, tuning_targets, projection_ids")
    ids = value["projection_ids"]
    if (type(ids) is not list or not ids or any(type(item) is not str or not item for item in ids)
            or len(set(ids)) != len(ids)):
        raise ValueError("nonempty unique projection_ids required")
    return value


def _save(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--domain", required=True, choices=("intent_ir", "security_ir", "ui_ux_ir"))
    parser.add_argument("--corpus", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path, help="Fresh directory; never overwritten")
    parser.add_argument("--registry", required=True, type=Path)
    parser.add_argument("--artifact-root", required=True, type=Path)
    parser.add_argument("--parent-version", help="Exact existing registered numerical parent")
    parser.add_argument("--epochs", type=int, default=20)
    parser.add_argument("--max-seconds", type=float, default=60)
    parser.add_argument("--latent-width", type=int, help="Fresh default 16; resume must match the saved configuration")
    parser.add_argument("--learning-rate", type=float, help="Fresh default .01; resume must match the saved configuration")
    parser.add_argument("--batch-size", type=int, help="Fresh default 8; resume must match the saved configuration")
    parser.add_argument("--seed", type=int, help="Fresh default 1729; resume must match the saved configuration")
    parser.add_argument("--lake-timeout-seconds", type=float, default=60)
    args = parser.parse_args(argv)
    from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree
    require_workspace_logic_tree()
    import torch
    torch.set_num_threads(1)
    from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_runtime_registry as runtimes
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import native_formula_training as learning
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_decoded_schema import (
        validate_decoded_outputs, MAX_SAMPLES, MAX_PROJECTIONS)
    corpus = _read(args.corpus)
    tuning = corpus["tuning_targets"]
    if type(tuning) is not list or not 1 <= len(tuning) <= MAX_SAMPLES:
        raise ValueError(f"CLI schema validation requires 1..{MAX_SAMPLES} tuning targets")
    if len(tuning) * len(corpus["projection_ids"]) > MAX_PROJECTIONS:
        raise ValueError("CLI schema validation projection count exceeds bounded report capacity")
    if args.output.exists():
        raise FileExistsError("native training output directory must be fresh")
    configuration = {"latent_width": args.latent_width, "learning_rate": args.learning_rate,
                     "batch_size": args.batch_size, "seed": args.seed}
    # One owner opens DuckDB; workers must use the existing owner transport.
    with AutoencoderRegistry(args.registry, args.artifact_root) as registry:
        if args.parent_version:
            runtime = runtimes.load_version(registry, args.parent_version, domain=args.domain,
                                            version=runtimes.NATIVE_FORMULA_VERSION)
            if sorted(corpus["projection_ids"]) != runtime.checkpoint["feature_space"]["projection_ids"]:
                raise ValueError("resume projection selection differs")
            saved_config = runtime.checkpoint["config"]
            for key, value in configuration.items():
                if value is not None and value != saved_config[key]:
                    raise ValueError(f"resume {key} differs from immutable checkpoint configuration")
        else:
            defaults = {"latent_width": 16, "learning_rate": .01, "batch_size": 8, "seed": 1729}
            configuration = {key: defaults[key] if value is None else value for key, value in configuration.items()}
            runtime = runtimes.build_native_formula_runtime(args.domain, corpus["training_targets"],
                validation_samples=corpus["tuning_targets"], projection_ids=corpus["projection_ids"],
                **configuration)
        args.output.mkdir(parents=False, exist_ok=False)
        result = runtime.train(corpus["training_targets"], validation_samples=corpus["tuning_targets"],
                               epochs=args.epochs, max_seconds=args.max_seconds)
        _save(args.output / "training.json", result["report"])
        if not result["report"]["training_executed"]:
            print(json.dumps({"status": "no_optimizer_update", "report": str(args.output / "training.json")}))
            return 2
        saved = learning.save_checkpoint(runtime.checkpoint, args.output / "checkpoint.json")
        candidate = runtime.register_candidate(registry, args.output / "registered")
    checked = validate_decoded_outputs(runtime, corpus["tuning_targets"],
        output_directory=args.output / "decoded-schema", timeout_seconds=args.lake_timeout_seconds)
    _save(args.output / "schema-validation.json", checked)
    print(json.dumps({"status": "candidate_recorded", "candidate": candidate, "checkpoint": saved,
        "schema_report": str(args.output / "schema-validation.json"), "admitted": False, "qualified": False}))
    return 0 if checked["schema_checks_complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
