#!/usr/bin/env python3
"""Prepare/review a source merge, then validate and update an internal Git ref.

Never updates main, the live checkout, model weights, or an active generation.
A successful source integration is not Lean admission or model qualification.
Apply uses the existing resource ledger and an exclusively created attempt.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_source_merge import (
    MAX_VALIDATOR_LOG_BYTES, apply_source_merge, prepare_source_merge, write_merge_plan,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_daemon_resources import (
    DaemonResourceReservation, MAX_LEDGER_BYTES, _safe_path,
)

DEFAULT_LEDGER = ROOT / "workspace/test-logs/federal-corpus-audits/owned-daemon-resource-control/disk-reservations.json"


def _durable_write(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _apply(args):
    # Only an existing ledger may authorize this command. Its named roots and
    # retained reservations are preserved; this CLI does not bootstrap a new cap.
    ledger = _safe_path(args.resource_ledger)
    descriptor = os.open(ledger, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        raw = stream.read(MAX_LEDGER_BYTES + 1)
    if len(raw) > MAX_LEDGER_BYTES:
        raise ValueError("resource ledger exceeds byte bound")
    roots = [Path(row["path"]) for row in json.loads(raw)["roots"]]
    directory = Path(os.path.abspath(args.output_directory))
    if not any(directory == root or root in directory.parents for root in roots):
        raise ValueError("output directory must be under the existing ledger's named roots")
    _safe_path(directory.parent, directory=True)
    directory.mkdir(exist_ok=False)
    evidence = directory / "evidence"
    evidence.mkdir()
    validator = args.validator[1:] if args.validator[:1] == ["--"] else args.validator
    if not validator:
        raise ValueError("an explicit validator command after -- is required")
    if not 0 < args.max_checkout_bytes <= 2 * 1024**3:
        raise ValueError("checkout bound must be positive and at most 2 GiB")
    # Account both the temporary log and its durable copy in the receipt, with
    # additional space for worktree administration and test-created small files.
    storage = args.max_checkout_bytes + 7 * MAX_VALIDATOR_LOG_BYTES + 16 * 1024 * 1024
    reservation = DaemonResourceReservation(ledger, roots=roots, storage_bytes=storage,
        memory_mb=args.memory_mb, cpu_slots=1, child_process_slots=3,
        timeout_seconds=0, ledger_lock_timeout_seconds=60)
    with reservation:
        try:
            reservation.check_usage(evidence)
            reservation.account_external_bytes("isolated-source-checkout",
                args.max_checkout_bytes + MAX_VALIDATOR_LOG_BYTES + 8 * 1024 * 1024)
            result = apply_source_merge(args.repo, plan_path=args.plan,
                expected_plan_sha256=args.plan_sha256, validator_argv=validator,
                validation_timeout_seconds=args.validation_timeout_seconds,
                lease_timeout_seconds=args.lease_timeout_seconds,
                max_checkout_bytes=args.max_checkout_bytes, scratch_directory=directory,
                resource_reservation=reservation, resource_attempt_directory=evidence)
            result["resource_reservation_id"] = reservation.reservation_id
            _durable_write(evidence / "receipt.json", result)
            resource_receipt = reservation.finalize(evidence, artifacts_durable=True)
            _durable_write(evidence / "resources.json", resource_receipt)
            return result
        except BaseException as exc:
            _durable_write(evidence / "failure.json", {"applied": None,
                "error": type(exc).__name__, "message": str(exc), "resources": reservation.to_dict(),
                "scope": "Failure can occur after internal-ref CAS; inspect the exact ref before retrying.",
                "admitted": False, "model_qualified": False})
            raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=ROOT)
    commands = parser.add_subparsers(dest="command", required=True)
    plan = commands.add_parser("plan", help="merge immutable commits without changing refs or checkout")
    plan.add_argument("--base", required=True)
    plan.add_argument("--candidate", required=True, action="append")
    plan.add_argument("--integration-ref", required=True)
    plan.add_argument("--output", type=Path, required=True)
    apply = commands.add_parser("apply", help="resource-admit source checks then CAS-update an internal ref")
    apply.add_argument("--plan", type=Path, required=True)
    apply.add_argument("--plan-sha256", required=True)
    apply.add_argument("--output-directory", type=Path, required=True, help="new attempt directory under ledger roots")
    apply.add_argument("--resource-ledger", type=Path, default=DEFAULT_LEDGER)
    apply.add_argument("--memory-mb", type=int, default=1024)
    apply.add_argument("--validation-timeout-seconds", type=float, default=300)
    apply.add_argument("--lease-timeout-seconds", type=float, default=300)
    apply.add_argument("--max-checkout-bytes", type=int, required=True,
        help="explicit isolated checkout bound, at most 2 GiB; admitted through the existing campaign ledger")
    apply.add_argument("validator", nargs=argparse.REMAINDER, help="-- <executable> <arguments...>")
    args = parser.parse_args(argv)
    if args.command == "plan":
        result = prepare_source_merge(args.repo, base_commit=args.base,
            candidate_commits=args.candidate, integration_ref=args.integration_ref)
        digest = write_merge_plan(args.output, result)
        print(json.dumps({"plan": str(args.output), "sha256": digest, "status": result["status"]}))
        return 0 if result["status"] == "prepared" else 2
    result = _apply(args)
    print(json.dumps({"receipt": str(args.output_directory / "evidence/receipt.json"), "applied": result["applied"]}))
    return 0 if result["applied"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
