#!/usr/bin/env python3
"""Time vocabulary, compiler, and span calls without changing admission state.

Run in a fresh process for each receipt. This never runs the Constitution
checkpoint evaluation, writes a ledger, or calls a model or Lean.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
os.environ["IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE"] = "0"
os.environ.setdefault("IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI", "0")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--constitution", type=Path, default=ROOT.parents[1] / "JevOps/.improve-watch/us-constitution/constitution.txt")
    args = parser.parse_args()
    if args.output.exists():
        parser.error(f"Refusing to overwrite existing receipt: {args.output}")
    from ipfs_datasets_py.logic.autoformal import (
        AutoformalSession, _vocabulary, compile_span, vocabulary_from_clause,
    )
    from ipfs_datasets_py.logic.autoformal.constitution_inventory import inventory_constitution
    from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree
    from ipfs_datasets_py.logic.legal_ir.canonical_compiler import TypedDeonticCanonicalCompiler
    from ipfs_datasets_py.logic.legal_ir.canonical_contracts import CompilerRequest

    source = args.constitution.read_text()
    spans = [s for s in inventory_constitution(source)["spans"] if s["status"] == "uncompiled"]
    if args.limit > 0:
        spans = spans[:args.limit]
    receipt = {
        "pin": require_workspace_logic_tree(),
        "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
        "source_files": {},
        "sample_count": len(spans),
        "bridge_names": [],
        "legal_ir_evaluate_provers": False,
        "legal_ir_parallel_workers": 1,
        "metric_disk_cache": False,
        "cold_process": True,
        "timing_order": "separate vocabulary/compiler calls, then span calls; regex patterns may be warm, parser results are not cached",
        "admitted": False,
        "formalized": False,
        "roundtrip_ok_count": 0,
        "separate_calls": [],
        "span_calls": [],
    }
    for rel in ("logic/autoformal/__init__.py", "logic/deontic/formula_builder.py", "logic/deontic/utils/deontic_parser.py", "logic/legal_ir/canonical_compiler.py"):
        receipt["source_files"][rel] = hashlib.sha256((ROOT / "ipfs_datasets_py" / rel).read_bytes()).hexdigest()
    for span in spans:
        started = time.perf_counter()
        vocabulary = vocabulary_from_clause(span["text"])
        vocabulary_seconds = time.perf_counter() - started
        started = time.perf_counter()
        result = TypedDeonticCanonicalCompiler().compile(CompilerRequest(
            source_text=span["text"], request_id=span["id"], atom_vocabulary=_vocabulary(vocabulary),
        ))
        compile_seconds = time.perf_counter() - started
        receipt["separate_calls"].append({
            "id": span["id"], "vocabulary": vocabulary,
            "vocabulary_seconds": vocabulary_seconds, "compile_seconds": compile_seconds,
            "result": result.to_dict(),
        })
    session = AutoformalSession()
    for span in spans:
        started = time.perf_counter()
        # Preserve the existing census runner's shared-ID vocabulary behavior.
        outcome = compile_span(session, span["text"], "constitution")
        receipt["span_calls"].append({"id": span["id"], "wall_seconds": time.perf_counter() - started, "outcome": outcome})
    count = max(1, len(spans))
    receipt["seconds_per_span"] = sum(r["wall_seconds"] for r in receipt["span_calls"]) / count
    receipt["vocabulary_seconds_per_span"] = sum(r["vocabulary_seconds"] for r in receipt["separate_calls"]) / count
    receipt["compiler_seconds_per_span"] = sum(r["compile_seconds"] for r in receipt["separate_calls"]) / count
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        stream.write(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps({k: v for k, v in receipt.items() if k.endswith("per_span") or k == "sample_count"}))


if __name__ == "__main__":
    main()
