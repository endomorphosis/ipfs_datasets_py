"""Run frozen learned code productions and independent formal source models."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--source-ledger", type=Path, required=True)
    parser.add_argument("--decoder-descriptor", type=Path, required=True)
    parser.add_argument("--protocol", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-functions", type=int, default=1024)
    parser.add_argument("--model-off", action="store_true")
    parser.add_argument("--check-headers", action="store_true")
    parser.add_argument("--allow-diagnostic-only", action="store_true")
    args = parser.parse_args(argv)
    from ipfs_datasets_py.logic.formalization.autoencoder.security import security_autoencoder_checkpoint as portable
    from ipfs_datasets_py.logic.formalization.autoencoder.security.security_formalization_pipeline import (
        run_security_formalization_pipeline, validate_security_formalization_pipeline,
    )
    try:
        inputs = [args.source_ledger, args.decoder_descriptor]
        if args.protocol is not None:
            inputs.append(args.protocol)
        pinned = {path.absolute(): portable._read(path.absolute(), 1024 * 1024) for path in inputs}
        ledger, decoder = (portable._decode(pinned[path.absolute()]) for path in inputs[:2])
        protocol = portable._decode(pinned[args.protocol.absolute()]) if args.protocol else None
        receipt = run_security_formalization_pipeline(repository=args.repository.absolute(),
            source_hashes=ledger, decoder=decoder, protocol=protocol, output=args.output.absolute(),
            max_functions=args.max_functions, model_enabled=not args.model_off, check_headers=args.check_headers)
        replay = validate_security_formalization_pipeline(repository=args.repository.absolute(), receipt=receipt)
        if any(portable._read(path, 1024 * 1024) != raw for path, raw in pinned.items()):
            raise ValueError("formalization input descriptor changed")
        passed = receipt["summary"]["learned_formula_generation_passed"]
        result = {**receipt, "capability_check": "passed" if passed else "failed",
            "model_off": args.model_off,
            "generation_solver_calls": replay["solver_calls"],
            "validation_solver_calls": replay["solver_calls"],
            "total_solver_calls": 2 * replay["solver_calls"],
            "exit_code": 0 if passed or args.allow_diagnostic_only else 2,
            "input_sha256": {str(path): portable._sha(raw) for path, raw in pinned.items()}}
    except Exception as error:
        result = {"capability_check": "not_established", "error_type": type(error).__name__, "exit_code": 2}
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return result["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
