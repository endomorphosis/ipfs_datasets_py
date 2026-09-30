#!/usr/bin/env python3
"""Bounded local learned formula training and separate source-only inference."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
# The script also runs from workspace staging before a single package install.
if not (ROOT / "ipfs_datasets_py/logic/autoformal/tree_pin.py").is_file():
    ROOT = next(parent for parent in ROOT.parents
                if (parent / "ipfs_datasets_py/logic/autoformal/tree_pin.py").is_file())
sys.path.insert(0, str(ROOT))


def _read(path):
    path = Path(path)
    if not path.is_file() or path.stat().st_size > 8 * 1024 * 1024:
        raise ValueError("input must be a regular JSON file no larger than 8 MiB")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate input JSON key")
            result[key] = value
        return result
    def reject(value):
        raise ValueError("nonfinite input JSON")
    with path.open("rb") as stream:
        raw = stream.read(8 * 1024 * 1024 + 1)
    if len(raw) > 8 * 1024 * 1024:
        raise ValueError("input exceeds 8 MiB")
    return json.loads(raw, object_pairs_hook=unique, parse_constant=reject)


def _write(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    train = sub.add_parser("train", help="fit source-to-formula token reconstruction")
    train.add_argument("--corpus", required=True, help="JSON containing train and tuning example arrays")
    train.add_argument("--output", required=True, help="fresh output directory")
    train.add_argument("--epochs", type=int, default=100)
    train.add_argument("--seconds", type=float, default=120)
    train.add_argument("--batch-size", type=int, default=8)
    train.add_argument("--learning-rate", type=float, default=0.008)
    train.add_argument("--seed", type=int, default=1729)
    train.add_argument("--resume")
    train.add_argument("--resume-sha256")
    infer = sub.add_parser("infer", help="generate from a JSON array of source strings")
    infer.add_argument("--checkpoint", required=True)
    infer.add_argument("--sha256", required=True)
    infer.add_argument("--input", required=True)
    infer.add_argument("--output", required=True, help="fresh report file")
    args = parser.parse_args(argv)

    from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree
    require_workspace_logic_tree()
    import torch
    # One small, private CPU worker. This CLI does not change global fleet policy.
    torch.set_num_threads(1)
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_formula_learning as learning
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_runtime_registry as runtimes

    if args.command == "train":
        output = Path(args.output).absolute()
        if output.exists() or output.parent.resolve(strict=True) != output.parent:
            raise ValueError("output must be a fresh directory under a canonical existing parent")
        corpus = _read(args.corpus)
        if type(corpus) is not dict or not {"train", "tuning"} <= set(corpus):
            raise ValueError("corpus needs separate train and tuning arrays")
        runtime = runtimes.open_runtime("legal_ir", runtimes.LEARNED_FORMULA_VERSION,
                                       checkpoint=args.resume, expected_sha256=args.resume_sha256)
        result = runtime.train(corpus["train"], validation_samples=corpus["tuning"],
            epochs=args.epochs, max_seconds=args.seconds, batch_size=args.batch_size,
            learning_rate=args.learning_rate, seed=args.seed)
        output.mkdir()
        artifact = learning.save_checkpoint(result["checkpoint"], output / "checkpoint.json")
        _write(output / "report.json", {"training": result["report"], "checkpoint": artifact,
            "runtime": runtime.describe(), "heldout_evaluated": False,
            "admitted": False, "qualified": False, "formalized": False})
        print(json.dumps({"checkpoint": artifact, "report": str(output / "report.json")}))
    else:
        sources = _read(args.input)
        runtime = runtimes.open_formal_decoder("legal_ir", runtimes.LEARNED_FORMULA_VERSION,
            checkpoint=args.checkpoint, expected_sha256=args.sha256)
        report = runtime.decode_formal_logic(sources)
        _write(args.output, report)
        print(json.dumps({"report": str(Path(args.output).absolute())}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
