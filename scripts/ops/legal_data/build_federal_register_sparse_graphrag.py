#!/usr/bin/env python3
"""Resumable full/cutoff-delta Federal Register sparse GraphRAG CLI (LCR-061).

Plans and resumes streaming family checkpoints, invalidates dependency
closures, and assembles atomic candidate roots under resource budgets.

Fixture-only default. No Hub upload. Partial output cannot be sealed.
Stale or config-mismatched checkpoints fail closed.

Examples
--------
Hermetic CI gate::

    python scripts/ops/legal_data/build_federal_register_sparse_graphrag.py \\
        --fixture-only --check

Full fixture build::

    python scripts/ops/legal_data/build_federal_register_sparse_graphrag.py \\
        --fixture-only --output-dir /tmp/fr-build --mode full

Resume after interrupt::

    python scripts/ops/legal_data/build_federal_register_sparse_graphrag.py \\
        --fixture-only --output-dir /tmp/fr-build --resume
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Final, Mapping, Sequence

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ipfs_datasets_py.processors.legal_data.federal_register_release import (  # noqa: E402
    DEFAULT_BM25_REBUILD_THRESHOLD,
    DEFAULT_BUILD_FAMILIES,
    DEFAULT_CLUSTER_REBUILD_THRESHOLD,
    DEFAULT_MAX_PARTITIONS,
    DEFAULT_MAX_RECORDS_IN_MEMORY,
    DEFAULT_MAX_WORK_UNITS,
    DEFAULT_PARTITIONS,
    DEFAULT_RESOURCE_CLASS,
    GOAL_ID,
    PROGRAM_ID,
    TASK_ID,
    BuildConfig,
    BuildMode,
    FamilyBuilderProducer,
    FederalRegisterBuildOrchestrator,
    FederalRegisterReleaseError,
    GlobalRebuildKind,
    ResourceLimits,
    default_fixture_producer,
    fixture_partition_snapshots,
    plan_build,
    reject_hub_upload,
    run_hermetic_check,
)
from ipfs_datasets_py.processors.legal_data.federal_register_source_policy import (  # noqa: E402
    DEFAULT_OBSERVATION_CUTOFF,
    LEGACY_BASELINE_END_INCLUSIVE,
)

PRODUCER: Final = "build_federal_register_sparse_graphrag.py"


class CliError(SystemExit):
    """CLI-level failure with a non-zero exit code."""

    def __init__(self, message: str, *, code: int = 2) -> None:
        super().__init__(code)
        self.message = message
        print(f"error: {message}", file=sys.stderr)


def _split_csv(raw: str | None) -> tuple[str, ...]:
    if raw is None or raw.strip() == "":
        return ()
    parts = [p.strip() for p in raw.replace(";", ",").split(",") if p.strip()]
    return tuple(parts)


def _parse_global_decision(raw: str | None) -> GlobalRebuildKind | None:
    if raw is None or raw.strip() == "" or raw.strip().lower() == "auto":
        return None
    return GlobalRebuildKind.coerce(raw)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="build_federal_register_sparse_graphrag.py",
        description=(
            "Resumable full and cutoff-delta Federal Register sparse GraphRAG "
            "build orchestration (LCR-061). Fixture-only default; no Hub upload. "
            "Partial output cannot be sealed."
        ),
    )
    parser.add_argument(
        "--mode",
        choices=("full", "delta"),
        default="full",
        help="Build planning mode (default: full)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("build/federal-register-sparse-graphrag"),
        help="Root directory for producer artifacts",
    )
    parser.add_argument(
        "--checkpoint-dir",
        type=Path,
        default=None,
        help="Directory for atomic checkpoints/receipts/seals "
        "(default: <output-dir>/.checkpoints)",
    )
    parser.add_argument(
        "--observation-cutoff",
        default=DEFAULT_OBSERVATION_CUTOFF,
        help=(
            "Immutable UTC observation cutoff pin "
            f"(default: {DEFAULT_OBSERVATION_CUTOFF})"
        ),
    )
    parser.add_argument(
        "--prior-cutoff",
        default=LEGACY_BASELINE_END_INCLUSIVE,
        help=(
            "Prior cutoff for delta planning "
            f"(default: {LEGACY_BASELINE_END_INCLUSIVE})"
        ),
    )
    parser.add_argument(
        "--partitions",
        default=",".join(DEFAULT_PARTITIONS),
        help="Comma-separated year-month partitions (default: 2026-03,2026-08)",
    )
    parser.add_argument(
        "--families",
        default=",".join(DEFAULT_BUILD_FAMILIES),
        help="Comma-separated artifact families to build",
    )
    parser.add_argument(
        "--resume",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Resume from a compatible checkpoint (default: true)",
    )
    parser.add_argument(
        "--validation-only",
        action="store_true",
        help="Plan and dry-run without writing artifacts, checkpoints, or seals",
    )
    parser.add_argument(
        "--fixture-only",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Offline fixture producer mode (default: true; no network, no Hub)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Run the hermetic fixture self-check and exit (no Hub, tempfile only)",
    )
    parser.add_argument(
        "--plan-only",
        action="store_true",
        help="Emit the build plan JSON and exit without executing producers",
    )
    parser.add_argument(
        "--use-family-builders",
        action="store_true",
        help="Delegate work units to existing FR family builders (fixture recipes)",
    )
    parser.add_argument(
        "--bm25-rebuild",
        default="auto",
        help="Global BM25 decision: auto|full_rebuild|delta_refresh|unchanged",
    )
    parser.add_argument(
        "--cluster-rebuild",
        default="auto",
        help="Global vector-cluster decision: auto|full_rebuild|delta_refresh|unchanged",
    )
    parser.add_argument(
        "--bm25-rebuild-threshold",
        type=float,
        default=DEFAULT_BM25_REBUILD_THRESHOLD,
        help=f"Auto full-rebuild threshold for BM25 (default: {DEFAULT_BM25_REBUILD_THRESHOLD})",
    )
    parser.add_argument(
        "--cluster-rebuild-threshold",
        type=float,
        default=DEFAULT_CLUSTER_REBUILD_THRESHOLD,
        help=(
            "Auto full-rebuild threshold for vector clusters "
            f"(default: {DEFAULT_CLUSTER_REBUILD_THRESHOLD})"
        ),
    )
    parser.add_argument(
        "--current-salt",
        default="fixture",
        help="Fixture salt for current partition snapshots (fixture-only)",
    )
    parser.add_argument(
        "--prior-salt",
        default="prior-fixture",
        help="Fixture salt for prior partition snapshots (delta + fixture-only)",
    )
    parser.add_argument(
        "--max-partitions",
        type=int,
        default=DEFAULT_MAX_PARTITIONS,
        help="Resource limit: maximum year-month partitions in one plan",
    )
    parser.add_argument(
        "--max-work-units",
        type=int,
        default=DEFAULT_MAX_WORK_UNITS,
        help="Resource limit: maximum work units in one plan",
    )
    parser.add_argument(
        "--max-resident-records",
        type=int,
        default=DEFAULT_MAX_RECORDS_IN_MEMORY,
        help="Streaming memory budget: max resident records",
    )
    parser.add_argument(
        "--resource-class",
        default=DEFAULT_RESOURCE_CLASS,
        help=f"Resource class label (default: {DEFAULT_RESOURCE_CLASS})",
    )
    parser.add_argument(
        "--determinism-seed",
        type=int,
        default=20260810,
        help="Determinism seed bound into the config digest",
    )
    parser.add_argument(
        "--interrupt-after-units",
        type=int,
        default=None,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON result on stdout",
    )
    parser.add_argument(
        "--hub-upload",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    return parser


def _build_config(args: argparse.Namespace) -> BuildConfig:
    partitions = _split_csv(args.partitions) or DEFAULT_PARTITIONS
    families = _split_csv(args.families) or DEFAULT_BUILD_FAMILIES
    return BuildConfig(
        observation_cutoff=str(args.observation_cutoff),
        prior_cutoff=str(args.prior_cutoff),
        mode=BuildMode.coerce(args.mode),
        partitions=partitions,
        families=families,
        determinism_seed=int(args.determinism_seed),
        bm25_rebuild_threshold=float(args.bm25_rebuild_threshold),
        cluster_rebuild_threshold=float(args.cluster_rebuild_threshold),
        bm25_decision=_parse_global_decision(args.bm25_rebuild),
        cluster_decision=_parse_global_decision(args.cluster_rebuild),
        resource_limits=ResourceLimits(
            max_partitions=int(args.max_partitions),
            max_work_units=int(args.max_work_units),
            max_resident_records=int(args.max_resident_records),
            resource_class=str(args.resource_class),
        ),
        validation_only=bool(args.validation_only),
        resume=bool(args.resume),
        fixture_only=True,
        use_family_builders=bool(args.use_family_builders),
        notes="cli:" + PRODUCER,
    )


def _emit(payload: Mapping[str, Any], *, as_json: bool) -> None:
    if as_json:
        print(
            json.dumps(
                payload,
                indent=2,
                ensure_ascii=False,
                sort_keys=True,
                allow_nan=False,
            )
        )
        return
    if payload.get("ok") is True and "proofs" in payload:
        print(f"task_id: {payload.get('task_id')}")
        print(f"goal_id: {payload.get('goal_id')}")
        print(f"ok: {payload.get('ok')}")
        print(f"proofs: {', '.join(payload.get('proofs') or ())}")
        print(f"seal_digest: {payload.get('seal_digest')}")
        print(f"candidate_root: {payload.get('candidate_root')}")
        print(f"hub_upload: {payload.get('authorizing_hub_upload')}")
        return
    if "plan" in payload and "seal" not in payload and "executed_keys" not in payload:
        plan = payload["plan"]
        print(f"mode: {plan.get('mode')}")
        print(f"build_id: {plan.get('build_id')}")
        print(f"config_digest: {plan.get('config_digest')}")
        print(f"units: {plan.get('unit_count')} (runnable={plan.get('runnable_count')})")
        print(
            "changed_partitions: "
            + (", ".join(plan.get("changed_partitions") or ()) or "(none)")
        )
        print(
            "invalidated_families: "
            + (", ".join(plan.get("invalidated_families") or ()) or "(none)")
        )
        decisions = plan.get("global_decisions") or {}
        for fam, dec in sorted(decisions.items()):
            print(
                f"global[{fam}]: {dec.get('kind')} "
                f"(equivalent_to_full={dec.get('equivalent_to_full')}; "
                f"source={dec.get('source')})"
            )
        return
    print(f"mode: {payload.get('plan', {}).get('mode')}")
    print(f"build_id: {payload.get('plan', {}).get('build_id')}")
    print(f"config_digest: {payload.get('plan', {}).get('config_digest')}")
    print(
        f"verified: {payload.get('checkpoint', {}).get('verified_count')}/"
        f"{payload.get('checkpoint', {}).get('total_count')}"
    )
    print(f"executed: {len(payload.get('executed_keys') or ())}")
    print(f"resumed: {len(payload.get('resumed_keys') or ())}")
    print(f"skipped: {len(payload.get('skipped_keys') or ())}")
    print(f"interrupted: {payload.get('interrupted')}")
    print(f"sealed: {payload.get('checkpoint', {}).get('sealed')}")
    print(f"candidate_root: {payload.get('candidate_root')}")
    seal = payload.get("seal")
    if seal:
        print(f"seal_digest: {seal.get('seal_digest')}")
    decisions = (payload.get("plan") or {}).get("global_decisions") or {}
    for fam, dec in sorted(decisions.items()):
        print(
            f"global[{fam}]: {dec.get('kind')} "
            f"(equivalent_to_full={dec.get('equivalent_to_full')})"
        )
    if payload.get("checkpoint_path"):
        print(f"checkpoint: {payload.get('checkpoint_path')}")
    if payload.get("seal_path"):
        print(f"seal: {payload.get('seal_path')}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    if getattr(args, "hub_upload", False):
        raise CliError("Hub upload is forbidden in LCR-061")
    if not args.fixture_only:
        raise CliError("this CLI is fixture-only; live/Hub builds are out of scope")

    try:
        reject_hub_upload(False)
        if args.check:
            payload = run_hermetic_check()
            payload["producer"] = PRODUCER
            _emit(payload, as_json=args.json)
            return 0 if payload.get("ok") else 1

        config = _build_config(args)
        current = fixture_partition_snapshots(
            config.partitions,
            salt=args.current_salt,
            observation_cutoff=config.observation_cutoff,
        )
        prior = None
        if config.mode is BuildMode.DELTA:
            prior = fixture_partition_snapshots(
                config.partitions,
                salt=args.prior_salt,
                observation_cutoff=config.prior_cutoff,
            )

        if args.plan_only:
            plan = plan_build(config, current=current, prior=prior)
            _emit(
                {
                    "goal_id": GOAL_ID,
                    "plan": plan.to_dict(),
                    "program_id": PROGRAM_ID,
                    "task_id": TASK_ID,
                },
                as_json=args.json,
            )
            return 0

        producer = (
            FamilyBuilderProducer()
            if args.use_family_builders
            else default_fixture_producer
        )
        orchestrator = FederalRegisterBuildOrchestrator(
            output_dir=args.output_dir,
            checkpoint_dir=args.checkpoint_dir,
            producer=producer,
        )
        result = orchestrator.run(
            config,
            current=current,
            prior=prior,
            interrupt_after_units=args.interrupt_after_units,
        )
    except FederalRegisterReleaseError as exc:
        raise CliError(str(exc)) from exc

    payload = result.to_dict()
    payload["task_id"] = TASK_ID
    payload["goal_id"] = GOAL_ID
    payload["program_id"] = PROGRAM_ID
    payload["producer"] = PRODUCER
    _emit(payload, as_json=args.json)

    if result.interrupted:
        return 3
    if result.seal is None and not result.validation_only:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
