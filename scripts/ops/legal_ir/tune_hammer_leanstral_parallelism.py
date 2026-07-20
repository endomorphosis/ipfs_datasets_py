#!/usr/bin/env python3
"""Select a resource- and trust-bounded DGX Spark parallel pipeline profile.

The command consumes measured output from
``benchmarks/bench_legal_ir_optimizer_pipeline.py``.  It never infers that a
busier CPU is a better configuration: every candidate must beat the fixed
baseline on a balanced end-to-end score while satisfying global scheduler,
single-trainer, proof/reconstruction, quality, failure, memory/swap, and queue
bounds.  The production profile is canonical and contains digests rather than
timestamps, so it can be reproduced exactly from the same benchmark evidence.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.parallelism_autotuner import (  # noqa: E402,F401
    DGX_SPARK_PROFILE_SCHEMA_VERSION,
    FIXED_DGX_SPARK_BASELINE,
    AutotuneResult,
    BenchmarkTrial,
    GlobalResourceBounds,
    ParallelismAutotuner,
    ParallelismProfile,
    PipelineBenchmarkMetrics,
    TrustBounds,
    autotune_parallelism,
    write_reproducible_profile,
)


DEFAULT_PROFILE_OUTPUT = Path("workspace/legal-ir-optimizer/dgx-spark-production-profile.json")


def load_benchmark_trials(path: str | os.PathLike[str]) -> list[BenchmarkTrial]:
    """Load and validate the benchmark report's measured trial objects."""

    source = Path(path)
    value = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise ValueError("benchmark report must be a JSON object")
    raw_trials = value.get("trials")
    if not isinstance(raw_trials, Sequence) or isinstance(raw_trials, (str, bytes, bytearray)):
        raise ValueError("benchmark report must contain a trials array")
    trials = [BenchmarkTrial.from_dict(item) for item in raw_trials if isinstance(item, Mapping)]
    if len(trials) != len(raw_trials):
        raise ValueError("benchmark trials must all be JSON objects")
    names = [trial.profile.name for trial in trials]
    if len(names) != len(set(names)):
        raise ValueError("benchmark profile names must be unique")
    return trials


def tune_benchmark_trials(
    trials: Sequence[BenchmarkTrial],
    *,
    resource_bounds: GlobalResourceBounds | None = None,
    trust_bounds: TrustBounds | None = None,
) -> AutotuneResult:
    """Compare all trials against the one mandatory fixed baseline."""

    baselines = [trial for trial in trials if trial.profile.name == "fixed_baseline"]
    if len(baselines) != 1:
        raise ValueError("benchmark evidence must contain exactly one fixed_baseline trial")
    candidates = [trial for trial in trials if trial.profile.name != "fixed_baseline"]
    return autotune_parallelism(
        baselines[0], candidates, resource_bounds=resource_bounds, trust_bounds=trust_bounds
    )


def build_dgx_spark_profile(
    baseline: BenchmarkTrial,
    candidates: Sequence[BenchmarkTrial],
    *,
    resource_bounds: GlobalResourceBounds | None = None,
    trust_bounds: TrustBounds | None = None,
) -> dict[str, Any]:
    """Compatibility helper returning only the reproducible production artifact."""

    return autotune_parallelism(
        baseline, candidates, resource_bounds=resource_bounds, trust_bounds=trust_bounds
    ).production_profile()


def generate_candidate_profiles() -> tuple[ParallelismProfile, ...]:
    """Return a small deterministic search design around the fixed baseline.

    Operators benchmark these profiles; the tuner only selects among measured
    results.  Every design respects the initial 8/4/4/2/2 scheduler lanes and
    one-trainer trust boundary.
    """

    return (
        ParallelismProfile(
            name="proof_heavy",
            hammer_workers=5,
            lean_reconstruction_workers=2,
            leanstral_workers=1,
            leanstral_batch_min=4,
            leanstral_batch_max=8,
        ),
        ParallelismProfile(
            name="balanced_batches",
            hammer_workers=4,
            lean_reconstruction_workers=2,
            leanstral_workers=2,
            leanstral_batch_min=6,
            leanstral_batch_max=8,
        ),
        ParallelismProfile(
            name="latency_first",
            hammer_workers=3,
            lean_reconstruction_workers=2,
            leanstral_workers=2,
            codex_workers=3,
            leanstral_batch_min=4,
            leanstral_batch_max=6,
        ),
    )


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(payload, allow_nan=False, indent=2, sort_keys=True) + "\n"
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(rendered)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark", type=Path, help="Complete pipeline benchmark report JSON.")
    parser.add_argument("--profile-output", type=Path, default=DEFAULT_PROFILE_OUTPUT)
    parser.add_argument(
        "--report-output",
        type=Path,
        default=None,
        help="Optional full decision report JSON.",
    )
    parser.add_argument(
        "--emit-candidates",
        action="store_true",
        help="Print the deterministic candidate design and exit.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Tune deterministic representative trials and do not write files.",
    )
    parser.add_argument("--total-cpu-slots", type=int, default=20)
    parser.add_argument("--total-memory-mb", type=int, default=128 * 1024)
    parser.add_argument("--max-memory-percent", type=float, default=90.0)
    parser.add_argument("--max-swap-percent", type=float, default=1.0)
    parser.add_argument("--max-gpu-memory-percent", type=float, default=92.0)
    parser.add_argument("--max-queue-lag-p95-seconds", type=float, default=120.0)
    parser.add_argument("--target-cycle-seconds", type=float, default=400.0)
    parser.add_argument("--max-transient-failure-rate", type=float, default=0.10)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.emit_candidates:
        print(json.dumps([item.to_dict() for item in generate_candidate_profiles()], indent=2, sort_keys=True))
        return 0
    if args.dry_run:
        if args.benchmark is not None:
            raise SystemExit("--dry-run cannot be combined with --benchmark")
        # Import lazily so normal operations never depend on a benchmarks package.
        from benchmarks.bench_legal_ir_optimizer_pipeline import dry_run_trials

        trials = dry_run_trials()
    else:
        if args.benchmark is None:
            raise SystemExit("--benchmark is required unless --dry-run or --emit-candidates is used")
        trials = load_benchmark_trials(args.benchmark)

    resources = GlobalResourceBounds(
        total_cpu_slots=args.total_cpu_slots,
        total_memory_mb=args.total_memory_mb,
        max_memory_percent=args.max_memory_percent,
        max_swap_percent=args.max_swap_percent,
        max_gpu_memory_percent=args.max_gpu_memory_percent,
        max_queue_lag_p95_seconds=args.max_queue_lag_p95_seconds,
        target_cycle_seconds=args.target_cycle_seconds,
    )
    trust = TrustBounds(max_transient_failure_rate=args.max_transient_failure_rate)
    result = tune_benchmark_trials(trials, resource_bounds=resources, trust_bounds=trust)
    report = result.to_dict()
    print(json.dumps(report, allow_nan=False, indent=2, sort_keys=True))
    if not args.dry_run:
        write_reproducible_profile(args.profile_output, result)
        if args.report_output is not None:
            _atomic_json(args.report_output, report)
    return 0


# Friendly alias used by operator integrations and older task packets.
select_best_profile = tune_benchmark_trials


if __name__ == "__main__":
    raise SystemExit(main())
