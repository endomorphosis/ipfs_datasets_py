#!/usr/bin/env python3
"""Compile pinned caller-declared source definitions without admitting legal truth."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from ipfs_datasets_py.logic.autoformal import legal_source_definition_bridge as bridge
from ipfs_datasets_py.logic.autoformal import legal_source_definition_lake as gate
from scripts.ops.legal_ir.evaluate_legal_uscode_fidelity import reference, write


def run(args):
    ref = reference(args.requests)
    bridge.require(ref["sha256"] == args.requests_sha256, "pinned definition input hash differs")
    requests = json.loads(Path(args.requests).read_text())
    reports = [bridge.prepare_definition(request) for request in requests]
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    prepared = write(output / "bridge-reports.json", reports)
    freeze = write(output / "freeze.json", {"schema": "legal-source-definition-pilot/v1", "requests": ref,
        "reports": prepared, "producer_pins": gate.pins(), "runner": reference(__file__),
        "caller_declarations_are_gold": False, "training_performed": False})
    receipt = gate.build(requests, toolchain=args.toolchain, lake_executable=args.lake_executable,
                         output_directory=output / "native-build")
    bridge.require(reference(args.requests) == ref, "definition inputs changed during build")
    return write(output / "summary.json", {"schema": "legal-source-definition-pilot/v1", "freeze": freeze,
        "receipt": reference(output / "native-build/receipt.json"), "request_count": len(requests),
        "declarations": len({r["declaration"]["declaration_id"] for r in requests}),
        "families": sorted({r["family"] for r in requests}),
        "build_passed": receipt["build_passed"], "compiled_modules": len(receipt["compiled_modules"]),
        "native_build_calls": int(receipt["backend_executed"]), "source_semantics_verified": False,
        "training_qualified": False, "learned_definition_decoder": False,
        "scope": "Caller-supplied unreviewed unary category definitions with exact source occurrence bindings; native FOL structure only."})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--requests", required=True)
    parser.add_argument("--requests-sha256", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--toolchain", required=True)
    parser.add_argument("--lake-executable", required=True)
    print(run(parser.parse_args()))
