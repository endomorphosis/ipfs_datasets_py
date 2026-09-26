#!/usr/bin/env python3
"""Measure the five-case typed deontic pilot without model or proof calls.

By default every module comes from this checkout. ``--baseline-source`` can
explicitly replace formula_builder with a saved original source for an isolated
comparison. The receipt records that override. A pilot result is not a Lean admit.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.abc
import importlib.util
import json
import os
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[3]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--baseline-source",
        type=Path,
        help="Explicit saved original formula_builder.py; omitted for the current checkout.",
    )
    args = parser.parse_args()
    if args.output.exists():
        parser.error(f"Refusing to overwrite existing receipt: {args.output}")
    if args.baseline_source is not None:
        args.baseline_source = args.baseline_source.resolve()
        if not args.baseline_source.is_file():
            parser.error(f"baseline source does not exist: {args.baseline_source}")

    workspace_entry = str(REPO_ROOT)
    if workspace_entry in sys.path:
        sys.path.remove(workspace_entry)
    sys.path.insert(0, workspace_entry)
    os.environ.setdefault("IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI", "0")

    if args.baseline_source is not None:
        class BaselineFormulaBuilder(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path, target=None):
                if fullname == "ipfs_datasets_py.logic.deontic.formula_builder":
                    return importlib.util.spec_from_file_location(fullname, args.baseline_source)
                return None

        sys.meta_path.insert(0, BaselineFormulaBuilder())

    from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree
    from ipfs_datasets_py.logic.deontic import formula_builder

    resolved = require_workspace_logic_tree()
    spec = importlib.util.spec_from_file_location(
        "semantic_speed_benchmark", REPO_ROOT / "benchmarks/bench_semantic_logic_roundtrip.py"
    )
    if spec is None or spec.loader is None:
        raise ImportError("the checked-in semantic pilot benchmark is unavailable")
    benchmark = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = benchmark
    spec.loader.exec_module(benchmark)
    results = []
    print(f"formula_builder={formula_builder.__file__}", flush=True)
    for case in benchmark._load_cases(benchmark.DEFAULT_FIXTURE):
        result = benchmark.run_deontic_codec(case)
        results.append({"case_id": case["id"], "result": result})
        print(json.dumps({
            "case_id": case["id"],
            "forward": result["forward_vs_gold"]["semantic_score"],
            "cycle": result["cycle_l1_vs_l2"]["semantic_score"],
            "l1_cid": result["l1_cid"], "l2_cid": result["l2_cid"],
        }), flush=True)

    output = {
        "admitted": False,
        "resolved_logic_tree": resolved,
        "formula_builder_path": formula_builder.__file__,
        "formula_builder_sha256": hashlib.sha256(Path(formula_builder.__file__).read_bytes()).hexdigest(),
        "baseline_source": None if args.baseline_source is None else str(args.baseline_source),
        "measurement_scope": "five-case typed deontic text round trip; no bridge evaluate or Lean admit",
        "cases": results,
        "aggregate": benchmark._aggregate_standard_arm([item["result"] for item in results]),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(output, indent=2) + "\n")
    print(json.dumps(output["aggregate"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
