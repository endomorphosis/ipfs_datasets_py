#!/usr/bin/env python3
"""Freeze matched cold/warm modal-autoencoder cycle throughput evidence.

Production usage consumes one or more source-free daemon JSON/JSONL summaries::

    python benchmarks/bench_modal_autoencoder_cycle.py \
      --input artifacts/cold.json --input artifacts/warm.json \
      --output-directory artifacts/cycle-baseline

Each input summary must declare ``benchmark_cache_state`` (``cold`` or
``warm``) and carry the same ordered canonical sample IDs.  ``--dry-run`` uses
deterministic schema-complete evidence and performs no model, prover, child
process, network, dataset, or trainer work.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.cycle_throughput_benchmark import (  # noqa: E402
    BaselineEvidenceError,
    build_matched_cycle_throughput_baseline,
    canonical_json,
    write_content_addressed_baselines,
    write_immutable_baseline_document,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_family_evaluator import (  # noqa: E402
    LEGAL_IR_EVALUATION_FAMILIES,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.runtime_telemetry import (  # noqa: E402
    RUNTIME_PHASES,
)


def _canonical_dry_sample_ids() -> list[str]:
    return [f"legal-ir-cycle-canary-{index:02d}" for index in range(1, 17)]


def _family_guardrails(cache_state: str) -> dict[str, Any]:
    adjustment = 0.002 if cache_state == "warm" else 0.0
    result: dict[str, Any] = {}
    for index, family in enumerate(LEGAL_IR_EVALUATION_FAMILIES):
        score = min(1.0, 0.96 + index * 0.002 + adjustment)
        result[family] = {
            "sample_count": 16,
            "ir_cross_entropy_loss": round(0.40 - index * 0.01, 6),
            "ir_cosine_similarity": round(0.91 + index * 0.005, 6),
            "hammer_proof_success_rate": round(score, 6),
            "reconstruction_success_rate": round(score - 0.01, 6),
            "source_copy_penalty": 0.0,
            "semantic_equivalence": {
                "structural_equivalence": score,
                "obligation_equivalence": score,
                "counterexample_equivalence": score,
                "graph_isomorphism": score,
                "temporal_window_agreement": score,
                "decompiler_round_trip_preservation": score - 0.01,
                "proof_obligation_delta_score": score,
            },
        }
    return result


def _dry_summary(cache_state: str) -> dict[str, Any]:
    """Return deterministic, complete, representative cycle evidence."""

    cold = cache_state == "cold"
    scale = 1.0 if cold else 0.62
    base_seconds = 426.656 if cold else 264.52672
    resources = {
        "cpu_percent": 11.691 if cold else 18.4,
        "process_cpu_percent": 9.2 if cold else 14.8,
        "memory_used_bytes": 34_359_738_368,
        "process_memory_bytes": 2_147_483_648,
        "swap_used_bytes": 0,
        "gpu_utilization_percent": 37.0 if cold else 61.0,
        "gpu_memory_used_bytes": 25_769_803_776,
        "process_gpu_memory_used_bytes": 12_884_901_888,
        "unified_memory_used_bytes": 60_129_542_144,
        "child_process_count": 8,
        "gpu_telemetry_available": True,
    }
    spans: list[dict[str, Any]] = []
    for index, phase in enumerate(RUNTIME_PHASES):
        duration = round((1.2 + index * 0.31) * scale, 9)
        spans.append(
            {
                "phase": phase,
                "duration_seconds": duration,
                "unit_count": 16 if phase in {"compilation", "embeddings", "validation"} else 1,
                "status": "ok",
                "cache_hit": (not cold) if phase == "cache_lookup" else None,
                "resources_start": resources,
                "resources_end": resources,
            }
        )
    # Serialization is tracked independently of state persistence, even though
    # the v1 runtime phase catalog predates this benchmark-specific subphase.
    spans.append(
        {
            "phase": "state_serialization",
            "duration_seconds": round(7.42 * scale, 9),
            "unit_count": 577_871_788,
            "status": "ok",
            "resources_start": resources,
            "resources_end": resources,
        }
    )
    spans.append(
        {
            "phase": "cycle",
            "duration_seconds": base_seconds,
            "unit_count": 16,
            "status": "ok",
            "resources_start": resources,
            "resources_end": resources,
        }
    )
    return {
        "benchmark_cache_state": cache_state,
        "benchmark_sample_ids": _canonical_dry_sample_ids(),
        "benchmark_elapsed_seconds": base_seconds,
        "runtime_telemetry": {
            "spans": spans,
            "resources": {"latest": resources},
        },
        "latest_autoencoder_state_telemetry": {
            "schema_version": "modal-autoencoder-state-v1",
            "generalizable_entry_count": 145_012,
            "vector_entry_count": 101_337,
            "vector_scalar_count": 48_122_592,
            "nested_logit_entry_count": 43_675,
            "nested_logit_scalar_count": 4_234_111,
            "sample_memory_entry_count": 32,
            "state_file": {"exists": True, "size_bytes": 577_871_788},
        },
        "io_telemetry": {
            "bytes_read": 577_871_788 if cold else 8_388_608,
            "bytes_written": 1_585_384_879 if cold else 577_871_788,
        },
        "leanstral_service": {
            "leanstral_startup_count": 1 if cold else 0,
            "leanstral_startup_seconds": 207.0 if cold else 0.0,
            "leanstral_reuse_count": 0 if cold else 1,
            "leanstral_request_count": 8,
            "healthy_cuda_service_reused": not cold,
        },
        "hammer_metrics": {
            "hammer_attempt_count": 72,
            "hammer_proved_count": 68,
            "hammer_reconstruction_success_count": 66,
            "hammer_work_seconds": round(42.0 * scale, 9),
        },
        "codex_metrics": {
            "codex_attempt_count": 6,
            "validation_attempt_count": 5,
            "validation_passed_count": 4,
            "failed_validation_count": 1,
            "accepted_patch_count": 3,
        },
        "legal_ir_view_family_metrics": _family_guardrails(cache_state),
    }


def dry_run_summaries() -> tuple[list[Mapping[str, Any]], list[Mapping[str, Any]]]:
    """Return the public deterministic cold/warm installation-check fixture."""

    return [_dry_summary("cold")], [_dry_summary("warm")]


def _load_documents(path: Path) -> list[Mapping[str, Any]]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".jsonl":
        values: Any = [json.loads(line) for line in text.splitlines() if line.strip()]
    else:
        values = json.loads(text)
    if isinstance(values, Mapping):
        if isinstance(values.get("summaries"), Sequence):
            values = values["summaries"]
        else:
            values = [values]
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes, bytearray)):
        raise BaselineEvidenceError(f"input must contain JSON objects: {path}")
    result = list(values)
    if not all(isinstance(item, Mapping) for item in result):
        raise BaselineEvidenceError(f"input contains a non-object value: {path}")
    return result


def _partition_summaries(paths: Sequence[Path]) -> tuple[list[Mapping[str, Any]], list[Mapping[str, Any]]]:
    cold: list[Mapping[str, Any]] = []
    warm: list[Mapping[str, Any]] = []
    for path in paths:
        for summary in _load_documents(path):
            state = str(
                summary.get("benchmark_cache_state") or summary.get("cache_state") or ""
            ).strip().lower()
            if state == "cold":
                cold.append(summary)
            elif state == "warm":
                warm.append(summary)
            else:
                raise BaselineEvidenceError(
                    f"summary from {path} must declare benchmark_cache_state as cold or warm"
                )
    if not cold or not warm:
        raise BaselineEvidenceError("at least one cold and one warm summary are required")
    return cold, warm


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        action="append",
        type=Path,
        default=[],
        help="Daemon JSON/JSONL input; repeat for cold/warm runs.",
    )
    parser.add_argument(
        "--output-directory",
        type=Path,
        help="Write immutable digest-named cold, warm, and matched artifacts.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Also write the matched document at this explicit path.",
    )
    parser.add_argument(
        "--expected-sample-digest",
        default="",
        help="Fail if the matched canonical sample has a different SHA-256 identity.",
    )
    parser.add_argument(
        "--allow-incomplete",
        action="store_true",
        help="Emit diagnostic legacy evidence instead of failing on missing measurements.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Use deterministic complete evidence; launch no workload.",
    )
    parser.add_argument("--pretty", action="store_true", help="Pretty-print stdout JSON.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.dry_run:
            if args.input:
                raise BaselineEvidenceError("--dry-run and --input are mutually exclusive")
            cold, warm = dry_run_summaries()
        else:
            if not args.input:
                raise BaselineEvidenceError("provide --input or use --dry-run")
            cold, warm = _partition_summaries(args.input)
        baseline = build_matched_cycle_throughput_baseline(
            cold,
            warm,
            strict=not args.allow_incomplete,
            dry_run=bool(args.dry_run),
        )
        document = baseline.to_dict()
        expected = str(args.expected_sample_digest or "").strip()
        actual = str(document["canonical_sample_digest"])
        if expected and expected != actual:
            raise BaselineEvidenceError(
                f"canonical sample digest mismatch: expected {expected}, observed {actual}"
            )
        if args.output_directory:
            paths = write_content_addressed_baselines(baseline, args.output_directory)
            print(
                "cycle baseline artifacts: "
                + ", ".join(f"{name}={path}" for name, path in paths.items()),
                file=sys.stderr,
            )
        rendered = (
            json.dumps(document, allow_nan=False, ensure_ascii=True, indent=2, sort_keys=True)
            if args.pretty
            else canonical_json(document)
        ) + "\n"
        if args.output:
            write_immutable_baseline_document(document, args.output)
        sys.stdout.write(rendered)
        return 0
    except (BaselineEvidenceError, OSError, json.JSONDecodeError) as exc:
        print(f"cycle throughput benchmark failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
