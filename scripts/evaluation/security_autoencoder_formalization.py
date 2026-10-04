"""Evaluate a frozen security checkpoint against learned-formula capability.

Example (source ledger is a JSON object mapping permitted relative paths to SHA256):
    python scripts/evaluation/security_autoencoder_formalization.py \
        --repository /absolute/repository --source-ledger /absolute/sources.json \
        --checkpoint-descriptor /absolute/checkpoint.json --output /absolute/new-evaluation

Exit 2 means required learned formula generation is unavailable or evaluation
failed. --allow-diagnostic-only permits exit 0 for a completed diagnostic while
explicitly preserving a failed capability result. No training or download occurs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

SCHEMA = "security-autoencoder-formalization-cli@1"


def _evaluate(**kwargs):
    from ipfs_datasets_py.logic.formalization.autoencoder.security.security_formalization_evaluation import (
        run_security_formalization_evaluation,
    )
    return run_security_formalization_evaluation(**kwargs)


def _read_json(path):
    from ipfs_datasets_py.logic.formalization.autoencoder.security import security_autoencoder_checkpoint as portable
    path = Path(path).absolute()
    raw = portable._read(path, maximum=1024 * 1024)
    value = portable._decode(raw)
    if type(value) is not dict:
        raise ValueError("JSON object descriptor or source ledger required")
    return path, raw, value


def _execute(args):
    from ipfs_datasets_py.logic.formalization.autoencoder.security import security_autoencoder_checkpoint as portable
    repository = Path(args.repository).absolute()
    ledger_path, ledger_raw, ledger = _read_json(args.source_ledger)
    descriptor_path, descriptor_raw, descriptor = _read_json(args.checkpoint_descriptor)
    if any(type(value) is not str for value in ledger.values()):
        raise ValueError("source ledger must map relative paths directly to SHA256 strings")
    ledger = portable._ledger(ledger)
    portable._sources(repository, ledger)
    if not 1 <= args.max_functions <= 1024:
        raise ValueError("max-functions must be between 1 and 1024")
    output = Path(args.output).absolute()
    if output.exists() or output.resolve() != output:
        raise ValueError("fresh canonical evaluation output required")

    report = _evaluate(repository=repository, paths=sorted(ledger), source_hashes=ledger,
        checkpoint=descriptor, output=output, polarity=args.polarity, max_functions=args.max_functions)
    # Prevent a successful CLI receipt from silently describing input files that
    # changed while the evaluator was running, including in diagnostic mode.
    if (portable._read(ledger_path, maximum=1024 * 1024) != ledger_raw
            or portable._read(descriptor_path, maximum=1024 * 1024) != descriptor_raw):
        raise ValueError("evaluation input descriptor drift")
    portable._sources(repository, ledger)
    summary = report["summary"]
    passed = summary["learned_formula_generation_passed"]
    counts = {key: summary[key] for key in ("sample_count", "program_ir_count", "learned_formula_count")}
    if (type(passed) is not bool or any(type(count) is not int or count < 0 for count in counts.values())
            or type(summary["missing_capabilities"]) is not list
            or any(type(value) is not str for value in summary["missing_capabilities"])
            or (passed and (not counts["learned_formula_count"] or summary["missing_capabilities"]))):
        raise ValueError("closed, consistent formula capability summary required")
    status = {"schema": SCHEMA, "evaluation_schema": report["schema"],
        "mode": "diagnostic_only" if args.allow_diagnostic_only else "required_learned_formulas",
        "capability_check": "passed" if passed else "failed",
        "learned_formula_generation_passed": passed, **counts,
        "missing_capabilities": summary["missing_capabilities"],
        "classification_scores_are_not_formulas": True,
        "source_ledger_sha256": hashlib.sha256(ledger_raw).hexdigest(),
        "checkpoint_descriptor_sha256": hashlib.sha256(descriptor_raw).hexdigest(),
        "evaluation": str(output / "evaluation.json"),
        "exit_code": 0 if passed or args.allow_diagnostic_only else 2}
    raw = portable._read(output / "evaluation.json", maximum=32 * 1024 * 1024)
    if portable._decode(raw) != report:
        raise ValueError("persisted evaluation differs from returned report")
    status["evaluation_sha256"] = hashlib.sha256(raw).hexdigest()
    with (output / "cli-receipt.json").open("x") as stream:
        json.dump(status, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
    return status


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--source-ledger", type=Path, required=True)
    parser.add_argument("--checkpoint-descriptor", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--polarity", choices=("vulnerable", "fixed"), default="vulnerable")
    parser.add_argument("--max-functions", type=int, default=1024)
    parser.add_argument("--allow-diagnostic-only", action="store_true")
    args = parser.parse_args(argv)
    try:
        status = _execute(args)
    except Exception as error:
        # Input code or model metadata must not leak through exception messages.
        status = {"schema": SCHEMA, "mode": "diagnostic_only" if args.allow_diagnostic_only else "required_learned_formulas",
            "capability_check": "not_established", "error_type": type(error).__name__, "exit_code": 2}
    print(json.dumps(status, sort_keys=True, allow_nan=False))
    return status["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
