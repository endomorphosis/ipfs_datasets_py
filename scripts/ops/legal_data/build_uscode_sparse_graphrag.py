#!/usr/bin/env python3
"""Resumable full/delta US Code sparse GraphRAG build CLI (USCIR-030).

Orchestrates title × artifact-family builds with atomic checkpoints,
resumable receipts, deterministic configuration, explicit global BM25/cluster
rebuild decisions, resource limits, and validation-only mode.

Partial output can never be sealed. Stale or config-mismatched checkpoints
fail closed.

Examples
--------
Full fixture build::

    python scripts/ops/legal_data/build_uscode_sparse_graphrag.py \\
        --fixture-only --output-dir /tmp/uscode-build --titles 1,35

Resume after interrupt::

    python scripts/ops/legal_data/build_uscode_sparse_graphrag.py \\
        --fixture-only --output-dir /tmp/uscode-build --titles 1,35 --resume

Validation-only plan (no artifact writes)::

    python scripts/ops/legal_data/build_uscode_sparse_graphrag.py \\
        --fixture-only --validation-only --titles 1,35 --mode full
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Final, Sequence

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ipfs_datasets_py.processors.legal_data.uscode_build import (  # noqa: E402
    DEFAULT_BM25_REBUILD_THRESHOLD,
    DEFAULT_BUILD_FAMILIES,
    DEFAULT_CLUSTER_REBUILD_THRESHOLD,
    BuildConfig,
    BuildMode,
    GlobalRebuildKind,
    ResourceLimits,
    UscodeBuildError,
    UscodeBuildOrchestrator,
    fixture_title_snapshots,
    plan_build,
)
from ipfs_datasets_py.processors.legal_data.uscode_source_policy import (  # noqa: E402
    DEFAULT_APPROVED_RELEASE_POINT,
)

TASK_ID: Final = "USCIR-030"
GOAL_ID: Final = "USCIR-G080"
PRODUCER: Final = "build_uscode_sparse_graphrag.py"


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
        prog="build_uscode_sparse_graphrag.py",
        description=(
            "Resumable full and delta US Code sparse GraphRAG build "
            "orchestration (USCIR-030). Global BM25/cluster rebuild "
            "decisions are explicit; partial output cannot be sealed."
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
        default=Path("build/uscode-sparse-graphrag"),
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
        "--release-point",
        default=DEFAULT_APPROVED_RELEASE_POINT,
        help=f"Exact approved release point pin (default: {DEFAULT_APPROVED_RELEASE_POINT})",
    )
    parser.add_argument(
        "--titles",
        default="1,35",
        help="Comma-separated title numbers (default: 1,35 for fixture builds)",
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
        action="store_true",
        help="Offline fixture producer mode (no network, no optional backends)",
    )
    parser.add_argument(
        "--plan-only",
        action="store_true",
        help="Emit the build plan JSON and exit without executing producers",
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
        help="Fixture salt for current title snapshots (fixture-only)",
    )
    parser.add_argument(
        "--prior-salt",
        default="prior-fixture",
        help="Fixture salt for prior title snapshots (delta + fixture-only)",
    )
    parser.add_argument(
        "--max-titles",
        type=int,
        default=53,
        help="Resource limit: maximum titles in one plan",
    )
    parser.add_argument(
        "--max-work-units",
        type=int,
        default=512,
        help="Resource limit: maximum work units in one plan",
    )
    parser.add_argument(
        "--resource-class",
        default="memory-large",
        help="Resource class label recorded in the config",
    )
    parser.add_argument(
        "--determinism-seed",
        type=int,
        default=20260330,
        help="Determinism seed bound into the config digest",
    )
    parser.add_argument(
        "--interrupt-after-units",
        type=int,
        default=None,
        help=argparse.SUPPRESS,  # harness-only; not advertised in --help detail
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON result on stdout",
    )
    return parser


def _build_config(args: argparse.Namespace) -> BuildConfig:
    titles = _split_csv(args.titles)
    families = _split_csv(args.families) or DEFAULT_BUILD_FAMILIES
    return BuildConfig(
        release_point=args.release_point,
        mode=BuildMode.coerce(args.mode),
        titles=titles,
        families=families,
        determinism_seed=int(args.determinism_seed),
        bm25_rebuild_threshold=float(args.bm25_rebuild_threshold),
        cluster_rebuild_threshold=float(args.cluster_rebuild_threshold),
        bm25_decision=_parse_global_decision(args.bm25_rebuild),
        cluster_decision=_parse_global_decision(args.cluster_rebuild),
        resource_limits=ResourceLimits(
            max_titles=int(args.max_titles),
            max_work_units=int(args.max_work_units),
            resource_class=str(args.resource_class),
        ),
        validation_only=bool(args.validation_only),
        resume=bool(args.resume),
        notes="cli:" + PRODUCER,
    )


def _emit(payload: MappingLike, *, as_json: bool) -> None:
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
    # Human-readable summary.
    if "plan" in payload and "seal" not in payload and "executed_keys" not in payload:
        plan = payload["plan"]
        print(f"mode: {plan.get('mode')}")
        print(f"build_id: {plan.get('build_id')}")
        print(f"config_digest: {plan.get('config_digest')}")
        print(f"units: {plan.get('unit_count')} (runnable={plan.get('runnable_count')})")
        print(f"changed_titles: {', '.join(plan.get('changed_titles') or ()) or '(none)'}")
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


# typing alias for the emit helper without importing Mapping in signature noise
MappingLike = dict[str, Any]


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    if not args.fixture_only and not args.plan_only and not args.validation_only:
        # Non-fixture production producers are injected by later release tasks;
        # this CLI always supports fixture-only offline builds and plan/validate.
        print(
            "note: production producers are delegated; defaulting to "
            "--fixture-only offline producer for this invocation",
            file=sys.stderr,
        )
        args.fixture_only = True

    try:
        config = _build_config(args)
    except UscodeBuildError as exc:
        raise CliError(str(exc)) from exc

    current = fixture_title_snapshots(config.titles, salt=args.current_salt)
    prior = None
    if config.mode is BuildMode.DELTA:
        prior = fixture_title_snapshots(config.titles, salt=args.prior_salt)

    try:
        if args.plan_only:
            plan = plan_build(config, current=current, prior=prior)
            _emit({"plan": plan.to_dict(), "task_id": TASK_ID}, as_json=args.json)
            return 0

        orchestrator = UscodeBuildOrchestrator(
            output_dir=args.output_dir,
            checkpoint_dir=args.checkpoint_dir,
        )
        result = orchestrator.run(
            config,
            current=current,
            prior=prior,
            interrupt_after_units=args.interrupt_after_units,
        )
    except UscodeBuildError as exc:
        raise CliError(str(exc)) from exc

    payload = result.to_dict()
    payload["task_id"] = TASK_ID
    payload["goal_id"] = GOAL_ID
    _emit(payload, as_json=args.json)

    if result.interrupted:
        return 3
    if result.seal is None and not result.validation_only:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
