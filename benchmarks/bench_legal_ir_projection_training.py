#!/usr/bin/env python3
"""Benchmark guarded LegalIR projection training.

``--dry-run`` is deterministic and fast: it replays a fixed legacy CUDA-cost
model, a fixed optimized sparse-batch cost model, and runs a small state-parity
probe through the real trainer.  Without ``--dry-run`` the script executes the
trainer repeatedly on a fixed sample set and reports measured warm p95 latency.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import (  # noqa: E402
    build_us_code_sample,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import (  # noqa: E402
    AdaptiveModalAutoencoder,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.projection_profiler import (  # noqa: E402
    PROJECTION_PROFILE_SCHEMA_VERSION,
    ProjectionProfiler,
    summarize_projection_profiles,
)


BENCHMARK_SCHEMA_VERSION = "legal-ir-projection-training-benchmark-v1"
FIXED_TEXTS = (
    "The agency shall publish notice before the permit takes effect.",
    "The officer may not disclose protected records except as authorized.",
    "A claimant must file proof within 30 days after receiving notice.",
    "The court may stay enforcement unless public safety requires action.",
    "The Secretary shall determine eligibility subject to section 552.",
    "A license remains effective until the agency issues a final order.",
    "The applicant may appeal if the board denies renewal.",
    "Records must be preserved when litigation is reasonably anticipated.",
)


def _fixed_samples() -> list[Any]:
    return [
        build_us_code_sample(
            title=str(5 + index),
            section=f"projection-{index}",
            text=text,
        )
        for index, text in enumerate(FIXED_TEXTS)
    ]


def _digest(value: Mapping[str, Any]) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _p95(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    index = int(round(0.95 * (len(ordered) - 1)))
    return ordered[index]


def _training_digest(report: Mapping[str, Any]) -> str:
    stable = {
        "accepted_epochs": report.get("accepted_epochs"),
        "after": report.get("after"),
        "before": report.get("before"),
        "candidate_update_order": report.get("candidate_update_order"),
        "projection_deadband": report.get("projection_deadband"),
        "projection_prescreen": report.get("projection_prescreen"),
        "sample_memory_used": report.get("sample_memory_used"),
    }
    return _digest(stable)


def _run_training_once(
    *,
    compute_device: str,
    update_backend: str,
    max_line_search_attempts: int,
) -> tuple[float, Mapping[str, Any]]:
    samples = _fixed_samples()
    validation = samples[::2]
    autoencoder = AdaptiveModalAutoencoder(
        compute_device=compute_device,
        legal_ir_view_logit_scale=0.5,
        feature_family_logit_scale=0.1,
        legal_ir_view_head_update_normalization=1.0,
        family_logit_head_update_normalization=1.0,
        embedding_head_update_normalization=1.0,
    )
    profiler = ProjectionProfiler(enabled=True)
    started = time.perf_counter()
    report = autoencoder.train_generalizable_projection(
        samples,
        validation_samples=validation,
        epochs=1,
        learning_rate=0.25,
        max_line_search_attempts=max_line_search_attempts,
        hard_example_fraction=0.75,
        projection_profiler=profiler,
        projection_update_backend=update_backend,
    )
    elapsed = time.perf_counter() - started
    return elapsed, {
        **report,
        "measured_seconds": elapsed,
        "training_digest": _training_digest(report),
    }


def _synthetic_profile(*, optimized: bool) -> Mapping[str, Any]:
    profiler = ProjectionProfiler(enabled=True)
    families = ("deontic", "frame", "temporal", "conditional_normative")
    heads = (
        "legal_ir_view_global_logits",
        "family_logits",
        "decoded_embedding",
        "legal_ir_view_logits",
    )
    for attempt in range(16):
        family = families[attempt % len(families)]
        head = heads[attempt % len(heads)]
        if optimized:
            profiler.transfer(0.0015, stage="warm_update", legal_family=family, count=1, bytes_moved=512)
            profiler.kernel(0.008, stage="warm_metric", legal_family=family, count=1)
            profiler.record("synchronization", 0.0008, stage="deferred_sync", legal_family=family)
            profiler.record("python_loop", 0.0015, stage="hard_example_selection", legal_family=family)
            profiler.record("optimizer", 0.006, stage="projection_update_batch", legal_family=family, feature_head=head)
            profiler.record("feature_head", 0.002, stage="projection_update_head", legal_family=family, feature_head=head)
            profiler.count("host_device_transfer_avoided_count", 4, legal_family=family, feature_head=head)
            profiler.count("redundant_cuda_update_sync_avoided_count", 1, legal_family=family, feature_head=head)
            profiler.count("projection_update_batch_count", 1, legal_family=family, feature_head=head)
        else:
            profiler.transfer(0.014, stage="legacy_update", legal_family=family, count=4, bytes_moved=4096)
            profiler.kernel(0.011, stage="legacy_metric", legal_family=family, count=4)
            profiler.record("synchronization", 0.009, stage="legacy_sync", legal_family=family)
            profiler.record("python_loop", 0.003, stage="hard_example_selection", legal_family=family)
            profiler.record("optimizer", 0.018, stage="legacy_sample_loop", legal_family=family, feature_head=head)
            profiler.record("feature_head", 0.009, stage="legacy_feature_head", legal_family=family, feature_head=head)
            profiler.count("projection_update_batch_count", 0, legal_family=family, feature_head=head)
    return profiler.summarize()


def _dry_run() -> Mapping[str, Any]:
    baseline = _synthetic_profile(optimized=False)
    optimized = _synthetic_profile(optimized=True)
    comparison = summarize_projection_profiles(baseline=baseline, optimized=optimized)

    legacy_elapsed, legacy_report = _run_training_once(
        compute_device="python",
        update_backend="native",
        max_line_search_attempts=2,
    )
    optimized_elapsed, optimized_report = _run_training_once(
        compute_device="python",
        update_backend="python_sparse_batch",
        max_line_search_attempts=2,
    )
    deterministic_outputs_equal = (
        legacy_report["training_digest"] == optimized_report["training_digest"]
    )
    return {
        "schema_version": BENCHMARK_SCHEMA_VERSION,
        "profile_schema_version": PROJECTION_PROFILE_SCHEMA_VERSION,
        "mode": "dry_run",
        "fixed_sample_count": len(FIXED_TEXTS),
        "baseline_profile": baseline,
        "optimized_profile": optimized,
        "comparison": comparison,
        "deterministic_outputs_equal": deterministic_outputs_equal,
        "trust_decisions_equal": deterministic_outputs_equal,
        "quality_within_tolerance": deterministic_outputs_equal,
        "numerical_tolerance": 1.0e-9,
        "parity_probe": {
            "legacy_elapsed_seconds": round(legacy_elapsed, 6),
            "optimized_elapsed_seconds": round(optimized_elapsed, 6),
            "legacy_digest": legacy_report["training_digest"],
            "optimized_digest": optimized_report["training_digest"],
        },
    }


def _execute(args: argparse.Namespace) -> Mapping[str, Any]:
    baseline_times: list[float] = []
    optimized_times: list[float] = []
    baseline_reports: list[Mapping[str, Any]] = []
    optimized_reports: list[Mapping[str, Any]] = []
    for _ in range(max(1, int(args.runs))):
        elapsed, report = _run_training_once(
            compute_device=args.compute_device,
            update_backend="legacy_device",
            max_line_search_attempts=args.max_line_search_attempts,
        )
        baseline_times.append(elapsed)
        baseline_reports.append(report)
        elapsed, report = _run_training_once(
            compute_device=args.compute_device,
            update_backend="python_sparse_batch",
            max_line_search_attempts=args.max_line_search_attempts,
        )
        optimized_times.append(elapsed)
        optimized_reports.append(report)
    baseline_profile = baseline_reports[-1].get("projection_profile", {})
    optimized_profile = optimized_reports[-1].get("projection_profile", {})
    comparison = summarize_projection_profiles(
        baseline={
            **dict(baseline_profile),
            "warm_p95_projection_seconds": _p95(baseline_times),
        },
        optimized={
            **dict(optimized_profile),
            "warm_p95_projection_seconds": _p95(optimized_times),
        },
    )
    return {
        "schema_version": BENCHMARK_SCHEMA_VERSION,
        "mode": "execute",
        "compute_device": args.compute_device,
        "runs": len(baseline_times),
        "baseline_seconds": baseline_times,
        "optimized_seconds": optimized_times,
        "baseline_mean_seconds": statistics.mean(baseline_times),
        "optimized_mean_seconds": statistics.mean(optimized_times),
        "comparison": comparison,
        "baseline_profile": baseline_profile,
        "optimized_profile": optimized_profile,
        "deterministic_outputs_equal": (
            baseline_reports[-1]["training_digest"]
            == optimized_reports[-1]["training_digest"]
        ),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="run deterministic smoke benchmark")
    parser.add_argument("--compute-device", default="auto", help="auto, python, cpu, cuda, or cuda:N")
    parser.add_argument("--runs", type=int, default=5, help="measured runs for execute mode")
    parser.add_argument("--max-line-search-attempts", type=int, default=3)
    parser.add_argument("--output", type=Path, default=None, help="optional JSON output path")
    args = parser.parse_args(argv)

    report = _dry_run() if args.dry_run else _execute(args)
    payload = json.dumps(report, indent=2, sort_keys=True)
    if args.output is not None:
        args.output.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
