#!/usr/bin/env python3
"""Post-process spans that failed to compile.

Draws a seeded random sample of gap rows from the federal cache, holds out
part of that draw, and retrains the autoencoder on the rest with the holdout
learning-rate schedule. Codec output that still fails the compiler becomes one
supervisor goal per failure class. A Lake success is not an admit.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault("IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI", "0")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=16)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--rounds", type=int, default=1)
    parser.add_argument(
        "--database",
        type=Path,
        default=None,
        help="Supervisor control-plane DuckDB. The replay process owns it through Quack for this upsert. Not the span cache.",
    )
    args = parser.parse_args(argv)
    from ipfs_datasets_py.logic.autoformal import AutoformalSession, compile_span
    from ipfs_datasets_py.logic.autoformal.gap_compile_replay import (
        CompileReplayMemory,
        FailureClassLedger,
        replay_gaps,
        upsert_failure_goals_through_quack,
    )
    from ipfs_datasets_py.logic.autoformal.repair_report import codec_capture
    from ipfs_datasets_py.logic.autoformal.span_agreement import (
        consensus_summary,
        sample_federal_spans,
        train_until_canary_improves,
    )

    def compile_one(text: str) -> dict:
        span_id = "gap-" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
        return compile_span(AutoformalSession(), text, span_id)

    drawn = sample_federal_spans(
        args.cache,
        count=min(max(args.limit, 2), 64),
        seed=args.seed,
        status="gap",
    )
    training = train_until_canary_improves(
        spans=drawn,
        seed=args.seed,
        rounds=max(1, args.rounds),
        cache_path=str(args.cache),
    )
    memory = CompileReplayMemory()
    ledger = FailureClassLedger()
    report = replay_gaps(
        drawn,
        lambda text: text,
        compile_one,
        capture=codec_capture,
        observe=memory.observe,
        goals=ledger,
    )
    from ipfs_datasets_py.logic.autoformal.span_cache import SpanCache

    span_repairs = 0
    cache = SpanCache(args.cache)
    try:
        span_repairs = cache.save_gap_repairs(report["rows"])
    finally:
        cache.close()
    fed = {"ingested": False}
    git_sync = {"pulled": False, "pushed": False, "conflict": False}
    if args.database is not None and ledger.class_count():
        from ipfs_datasets_py.logic.autoformal.goal_git_sync import sync_origin_main

        repo_root = Path(
            subprocess.check_output(
                ["git", "-C", str(Path(__file__).resolve().parent), "rev-parse", "--show-toplevel"],
                text=True,
            ).strip()
        )
        git_sync = sync_origin_main(repo_root)
        fed = upsert_failure_goals_through_quack(ledger, args.database)
    print(
        json.dumps(
            {
                "admitted": False,
                "compiled": report["compiled"],
                "consensus": consensus_summary(report["rows"]),
                "holdout_ids": training.get("holdout_ids"),
                "learning_rates": training.get("learning_rates"),
                "opens_catalog_file": True,
                "seed": args.seed,
                "span_repairs": span_repairs,
                "train_ids": training.get("train_ids"),
                "training": {
                    "admitted": False,
                    "after": training.get("after"),
                    "before": training.get("before"),
                    "formalized": False,
                    "improved": training.get("improved"),
                    "rounds": training.get("rounds"),
                },
                "duplicate_observations": report["duplicate_observations"],
                "failure_classes": report["failure_classes"],
                "failure_goals": report["failure_goals"],
                "formalized": False,
                "control_plane_upsert": {
                    "catalog_owner": fed.get("catalog_owner"),
                    "ducklake_activation_held": fed.get("ducklake_activation_held"),
                    "ducklake_loaded": fed.get("ducklake_loaded"),
                    "goal_rows": fed.get("goal_rows"),
                    "listen_uri": fed.get("listen_uri"),
                    "open_goal_rows": fed.get("open_goal_rows"),
                    "transport": fed.get("transport"),
                },
                "git_sync": {
                    "conflict": bool(git_sync.get("conflict")),
                    "pulled": bool(git_sync.get("pulled")),
                    "pushed": bool(git_sync.get("pushed")),
                },
                "goal_count": fed.get("goal_count"),
                "ingested": bool(fed.get("ingested")),
                "loss": report["loss"],
                "memory": memory.receipt(),
                "objective": "compile_replay",
                "replayed": report["replayed"],
                "wrote_compiler": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
