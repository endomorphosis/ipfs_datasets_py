#!/usr/bin/env python3
"""Replay historical Hammer cycle obligations under the current trust policy."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ipfs_datasets_py.logic.integration.reasoning.legal_ir_proof_feedback import (  # noqa: E402
    ProofFeedbackStore,
    ProofFeedbackVersions,
    write_proof_feedback_jsonl,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_proof_feedback_replay import (  # noqa: E402
    CANONICAL_HISTORICAL_CYCLE_FILE_COUNT,
    CANONICAL_HISTORICAL_NESTED_ARTIFACT_COUNT,
    CANONICAL_HISTORICAL_UNIQUE_OBLIGATION_COUNT,
    HistoricalHammerExecutionError,
    HistoricalHammerProofFeedbackReplay,
    HistoricalHammerReplayError,
    HistoricalHammerReplayPolicy,
    load_historical_hammer_obligations,
    load_replay_executor,
    write_historical_hammer_replay_json,
)


def _versions(path: Path) -> ProofFeedbackVersions:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise HistoricalHammerReplayError(f"cannot read versions JSON: {path}") from exc
    if not isinstance(value, Mapping):
        raise HistoricalHammerReplayError("versions JSON must contain an object")
    return ProofFeedbackVersions.from_dict(value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "inputs",
        nargs="+",
        type=Path,
        help="Historical cycle JSON/JSONL files or directories.",
    )
    parser.add_argument(
        "--state-dir",
        type=Path,
        required=True,
        help="Resumable, content-addressed replay state directory.",
    )
    parser.add_argument(
        "--report",
        type=Path,
        help="Replay report destination (defaults to STATE_DIR/replay-report.json).",
    )
    parser.add_argument(
        "--feedback-jsonl",
        type=Path,
        help="Optional source-free trusted proof-feedback JSONL export.",
    )
    parser.add_argument(
        "--executor",
        help=(
            "Current proof executor as package.module:callable. Required unless "
            "--inventory-only is selected."
        ),
    )
    parser.add_argument(
        "--versions-json",
        type=Path,
        help=(
            "Current ProofFeedbackVersions JSON. Required for execution so "
            "compiler, translator, solver, Lean, theorem, and schema versions "
            "are included in the cache key."
        ),
    )
    parser.add_argument("--compiler-schema-version")
    parser.add_argument(
        "--solver-policy-fingerprint",
        default="unspecified",
        help="Content fingerprint of the current allowlist and per-solver budgets.",
    )
    parser.add_argument(
        "--proof-routing-policy-fingerprint",
        default="unspecified",
        help="Content fingerprint of the current cheap-first proof routing policy.",
    )
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument(
        "--trusted-proof-checker",
        action="append",
        default=[],
        help="Allowlisted current proof checker identifier; repeatable.",
    )
    parser.add_argument(
        "--trust-root",
        action="append",
        default=[],
        help="Allowlisted current trust-root identifier; repeatable.",
    )
    parser.add_argument(
        "--resource-wait-timeout-seconds",
        type=float,
        help="Maximum wait for a host-global Hammer solver-budget lease.",
    )
    parser.add_argument(
        "--inventory-only",
        action="store_true",
        help="Audit and deduplicate inputs without executing proof obligations.",
    )
    parser.add_argument(
        "--no-global-solver-budget",
        action="store_true",
        help="Disable the host-global solver lease (intended only for isolated tests).",
    )
    parser.add_argument(
        "--allow-inventory-mismatch",
        action="store_true",
        help="Do not enforce the canonical 115/1196/96 historical corpus counts.",
    )
    parser.add_argument(
        "--expected-cycle-files",
        type=int,
        default=CANONICAL_HISTORICAL_CYCLE_FILE_COUNT,
    )
    parser.add_argument(
        "--expected-nested-artifacts",
        type=int,
        default=CANONICAL_HISTORICAL_NESTED_ARTIFACT_COUNT,
    )
    parser.add_argument(
        "--expected-unique-obligations",
        type=int,
        default=CANONICAL_HISTORICAL_UNIQUE_OBLIGATION_COUNT,
    )
    return parser


def _policy(args: argparse.Namespace, versions: ProofFeedbackVersions) -> HistoricalHammerReplayPolicy:
    enforce = not args.allow_inventory_mismatch
    return HistoricalHammerReplayPolicy(
        versions=versions,
        compiler_schema_version=(
            args.compiler_schema_version or versions.obligation_schema_version
        ),
        solver_policy_fingerprint=args.solver_policy_fingerprint,
        proof_routing_policy_fingerprint=args.proof_routing_policy_fingerprint,
        timeout_seconds=args.timeout_seconds,
        max_workers=args.workers,
        trusted_proof_checkers=tuple(sorted(set(args.trusted_proof_checker))),
        trusted_root_ids=tuple(sorted(set(args.trust_root))),
        use_global_solver_budget=not args.no_global_solver_budget,
        resource_wait_timeout_seconds=args.resource_wait_timeout_seconds,
        expected_cycle_file_count=args.expected_cycle_files if enforce else None,
        expected_nested_artifact_count=(
            args.expected_nested_artifacts if enforce else None
        ),
        expected_unique_obligation_count=(
            args.expected_unique_obligations if enforce else None
        ),
    )


def _print_inventory(inventory: Any) -> None:
    print(
        "inventory_decision=historical_inputs_untrusted "
        f"cycle_files={inventory.cycle_file_count} "
        f"nested_artifacts={inventory.nested_artifact_count} "
        f"obligation_occurrences={inventory.obligation_occurrence_count} "
        f"unique_obligations={inventory.unique_obligation_count} "
        f"historically_trusted={inventory.historically_trusted_count} "
        f"inventory_id={inventory.inventory_id}"
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        inventory = load_historical_hammer_obligations(args.inputs)
        _print_inventory(inventory)
        if args.inventory_only:
            policy = _policy(args, ProofFeedbackVersions())
            policy.validate_inventory(inventory)
            destination = args.report or args.state_dir / "inventory.json"
            write_historical_hammer_replay_json(destination, inventory)
            return 0
        if not args.executor:
            raise HistoricalHammerExecutionError(
                "--executor is required unless --inventory-only is selected"
            )
        if args.versions_json is None:
            raise HistoricalHammerExecutionError(
                "--versions-json is required for a current-policy replay"
            )
        versions = _versions(args.versions_json)
        policy = _policy(args, versions)
        executor = load_replay_executor(args.executor)
        feedback_store = ProofFeedbackStore(args.state_dir / "proof-feedback")
        coordinator = HistoricalHammerProofFeedbackReplay(
            executor,
            state_dir=args.state_dir,
            policy=policy,
            feedback_store=feedback_store,
        )
        report = coordinator.run(inventory, report_path=args.report)
        if args.feedback_jsonl is not None:
            write_proof_feedback_jsonl(
                args.feedback_jsonl,
                report.feedback_replay.records,
            )
    except (HistoricalHammerReplayError, OSError, ValueError) as exc:
        raise SystemExit(f"historical Hammer replay failed: {exc}") from exc
    print(
        "replay_decision=fresh_current_receipts_only "
        f"replayed={len(report.outcomes)} "
        f"trusted_feedback={len(report.feedback_replay.records)} "
        f"cache_hits={sum(item.cache_hit for item in report.outcomes)} "
        f"report_id={report.report_id}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
