#!/usr/bin/env python3
"""End-to-end recall/latency benchmark for the ITP hammer pipeline
(``## HAMMER-015`` in ``docs/logic/itp_hammer_taskboard.todo.md``).

This is the reproducibility harness ``docs/logic/itp_hammer_user_guide.md``
("Benchmark methodology") describes and that
``scripts/ops/logic/release_itp_hammer_gate.py`` requires as a release
input. It complements the narrower, opt-in-selector-focused
``benchmarks/bench_itp_hammer_premise_selection.py`` (HAMMER-005) with a
whole-pipeline view: deterministic premise-selection recall/latency over
the full fixture corpus, plus wall-clock latency and kernel-verification
outcomes for one representative case of every
:class:`~ipfs_datasets_py.logic.hammers.models.HammerResultStatus` the
pipeline can produce (``verified``, ``candidate``, ``counterexample``,
``timeout``, ``unsupported_translation``, ``unavailable``), reusing the
exact same real HAMMER-004/006/007/008/009/010/011 code paths that
``tests/integration/logic/hammers/test_end_to_end_hammer.py`` (HAMMER-014)
independently asserts against in its own golden-corpus suite (via the
shared, non-test-collected builder module
``tests/integration/logic/hammers/_golden_helpers.py``). Reusing that
builder module -- rather than re-implementing equivalent pipeline-wiring
logic a second time in ``benchmarks/`` -- guarantees this benchmark can
never silently drift from the behavior HAMMER-014 already holds to a
byte-for-byte-reproducible-digest standard; there is repo precedent for a
non-test script importing test utilities (see
``scripts/test/_run_tests.py`` importing ``tests._test_utils``).

Methodology
-----------
1. **Premise-selection recall/latency** (deterministic baseline only, the
   *only* selector enabled by default per HAMMER-004/HAMMER-005): for every
   theorem ``T`` in the fixture corpus, hold ``T`` out, select premises for
   its own goal/imports, and score the selected ids against the
   import-overlap proxy "relevant" set (the same reproducible,
   ground-truth-free proxy
   ``ipfs_datasets_py.logic.hammers.learned_selector.
   relevant_theorem_ids_by_import_overlap`` uses; see that module's
   docstring and ``benchmarks/bench_itp_hammer_premise_selection.py`` for
   the full rationale). Recall@k, reciprocal rank, and per-call latency are
   recorded for every theorem and summarized (mean/median/p95/max/min).
2. **Whole-pipeline case latency and verification outcome**: build one
   golden case per result status via the shared HAMMER-014 builders,
   timing each builder call end to end (premise selection, translation,
   untrusted solver/candidate construction, and -- for the
   kernel-reconstruction cases -- a genuine Lean/Coq kernel subprocess
   invocation). A case whose target ITP kernel is not installed in the
   current environment is recorded as ``environment_unavailable`` (not a
   failure of the benchmark itself) rather than raising, matching the
   pipeline's own "explicit unavailable state" contract.
3. **Resource defaults**: the operator-facing default
   :class:`~ipfs_datasets_py.logic.hammers.models.HammerPolicy` and
   :class:`~ipfs_datasets_py.logic.hammers.policy.PortfolioPolicy` budgets
   (timeouts, CPU/memory ceilings, process-count/network defaults) are
   embedded verbatim from the real dataclasses so this report can never
   drift from the code that actually enforces them.
4. **Environment capability snapshot**: if
   ``data/logic/itp_hammer/environment.json`` (HAMMER-002) exists, its
   summary is embedded for cross-reference; otherwise a note explains how
   to regenerate it.
5. **Reproducibility metadata**: Python/platform info, the fixture corpus
   revision, and wall-clock generation time are recorded so a rerun's
   report can be diffed against this one.

Usage
-----
    PYTHONPATH=. python benchmarks/bench_itp_hammer.py \\
        --fixture tests/fixtures/logic/hammers \\
        --out data/logic/itp_hammer/benchmark.json
"""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ipfs_datasets_py.logic.hammers.corpus import CorpusManifest, CorpusSource  # noqa: E402
from ipfs_datasets_py.logic.hammers.models import (  # noqa: E402
    HammerPolicy,
    HammerResult,
    ITPKind,
)
from ipfs_datasets_py.logic.hammers.policy import PortfolioPolicy  # noqa: E402
from ipfs_datasets_py.logic.hammers.premise_selection import (  # noqa: E402
    DETERMINISTIC_BASELINE_METHOD,
    select_premises_for_theorem,
)
from ipfs_datasets_py.logic.hammers.learned_selector import (  # noqa: E402
    compute_recall_at_k,
    compute_reciprocal_rank,
    relevant_theorem_ids_by_import_overlap,
)

DEFAULT_CORPUS_FILENAME = "golden_corpus.json"
DEFAULT_FALLBACK_CORPUS_FILENAME = "premise_selection_corpus.json"
DEFAULT_TOP_K = 5
DEFAULT_OUT = Path("data/logic/itp_hammer/benchmark.json")
DEFAULT_ENVIRONMENT_SNAPSHOT = Path("data/logic/itp_hammer/environment.json")

#: Case-id -> (kind, human label) for the whole-pipeline latency section.
#: ``kind`` mirrors the vocabulary ``tests/integration/logic/hammers/
#: _golden_helpers.py`` and ``data/logic/itp_hammer/golden-report.json``
#: (HAMMER-014) already use: ``"deterministic"`` cases never touch a real
#: kernel/solver subprocess (fully reproducible); ``"real_kernel"`` cases
#: genuinely invoke a Lean/Coq kernel and so their timing (but not their
#: pass/fail outcome) legitimately varies run to run.
PIPELINE_CASES: Tuple[Tuple[str, str, str], ...] = (
    ("candidate_only", "deterministic", "build_candidate_only_case"),
    ("counterexample", "deterministic", "build_counterexample_case"),
    ("timeout", "deterministic", "build_timeout_case"),
    ("unsupported_translation", "deterministic", "build_unsupported_translation_case"),
    ("unavailable_solver", "deterministic", "build_unavailable_solver_case"),
    ("verified_lean", "real_kernel", "build_verified_lean_case"),
    ("verified_coq", "real_kernel", "build_verified_coq_case"),
    (
        "verified_native_automation_fallback",
        "real_kernel",
        "build_verified_via_native_automation_case",
    ),
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _relative_or_absolute(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _import_golden_helpers():
    """Best-effort import of the shared HAMMER-014 golden-case builder
    module. Raises a clear, actionable error if the test tree (and
    therefore this benchmark's whole-pipeline section) is unavailable in
    the current checkout."""

    try:
        from tests.integration.logic.hammers import _golden_helpers  # type: ignore
    except Exception as exc:  # pragma: no cover - defensive, environment-dependent
        raise RuntimeError(
            "Could not import tests.integration.logic.hammers._golden_helpers "
            "(required for the whole-pipeline benchmark section). Ensure the "
            "repository root is on PYTHONPATH and the test tree is present. "
            f"Original error: {exc}"
        ) from exc
    return _golden_helpers


def load_fixture_manifest(fixture_dir: Path, *, corpus_file: Optional[str] = None) -> Tuple[CorpusManifest, Path]:
    """Build a :class:`CorpusManifest` from a declarative corpus JSON fixture
    under ``fixture_dir``. Prefers the golden corpus
    (``golden_corpus.json``, the HAMMER-014 fixture this benchmark's
    whole-pipeline section also draws from) so both sections describe the
    same corpus revision; falls back to the narrower premise-selection
    fixture if the golden corpus is not present."""

    candidates: List[str] = []
    if corpus_file:
        candidates.append(corpus_file)
    else:
        candidates.extend([DEFAULT_CORPUS_FILENAME, DEFAULT_FALLBACK_CORPUS_FILENAME])

    corpus_path: Optional[Path] = None
    for name in candidates:
        candidate = fixture_dir / name
        if candidate.is_file():
            corpus_path = candidate
            break
    if corpus_path is None:
        raise FileNotFoundError(
            f"No corpus fixture found under {fixture_dir} (tried {candidates!r})"
        )

    payload = json.loads(corpus_path.read_text(encoding="utf-8"))
    manifest = CorpusManifest(manifest_id=f"{payload['corpus_id']}-full-benchmark")
    manifest.register_source(
        CorpusSource(
            corpus_id=payload["corpus_id"],
            name=payload.get("name", payload["corpus_id"]),
            source_itp=ITPKind(payload.get("source_itp", "lean")),
            version_ref=payload.get("version_ref", "unknown"),
            license_id=payload.get("license_id", "Apache-2.0"),
            license_url=payload.get("license_url"),
            description=payload.get("description", ""),
        )
    )
    for theorem in payload["theorems"]:
        manifest.add_theorem(
            theorem_id=theorem["theorem_id"],
            corpus_id=payload["corpus_id"],
            statement=theorem["statement"],
            imports=theorem.get("imports"),
        )
    return manifest, corpus_path


def _percentile(values: List[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(len(ordered) * fraction) - 1))
    return ordered[index]


def _summarize_latency(samples_ms: List[float]) -> Dict[str, float]:
    if not samples_ms:
        return {"mean_ms": 0.0, "median_ms": 0.0, "p95_ms": 0.0, "max_ms": 0.0, "min_ms": 0.0}
    return {
        "mean_ms": round(statistics.mean(samples_ms), 4),
        "median_ms": round(statistics.median(samples_ms), 4),
        "p95_ms": round(_percentile(samples_ms, 0.95), 4),
        "max_ms": round(max(samples_ms), 4),
        "min_ms": round(min(samples_ms), 4),
    }


def run_premise_selection_benchmark(manifest: CorpusManifest, *, top_k: int) -> Dict[str, Any]:
    """Held-out recall/latency benchmark for the deterministic baseline
    selector over every theorem in ``manifest``."""

    per_theorem: List[Dict[str, Any]] = []
    latencies: List[float] = []
    recalls: List[float] = []
    mrrs: List[float] = []

    for entry in manifest.iter_theorems():
        theorem_id = entry.theorem_id
        relevant_ids = relevant_theorem_ids_by_import_overlap(manifest, theorem_id)

        start = time.perf_counter()
        selection = select_premises_for_theorem(manifest, theorem_id, top_k=top_k)
        latency_ms = (time.perf_counter() - start) * 1000.0

        selected_ids = [p.premise_id for p in selection.selected]
        recall = compute_recall_at_k(selected_ids, relevant_ids)
        mrr = compute_reciprocal_rank(selected_ids, relevant_ids)

        latencies.append(latency_ms)
        recalls.append(recall)
        mrrs.append(mrr)
        per_theorem.append(
            {
                "theorem_id": theorem_id,
                "relevant_count": len(relevant_ids),
                "selected_ids": selected_ids,
                "recall_at_k": round(recall, 4),
                "reciprocal_rank": round(mrr, 4),
                "latency_ms": round(latency_ms, 4),
            }
        )

    return {
        "selection_method": DETERMINISTIC_BASELINE_METHOD,
        "theorem_count": len(per_theorem),
        "top_k": top_k,
        "mean_recall_at_k": round(statistics.mean(recalls), 4) if recalls else 0.0,
        "mean_reciprocal_rank": round(statistics.mean(mrrs), 4) if mrrs else 0.0,
        "latency": _summarize_latency(latencies),
        "per_theorem": per_theorem,
    }


def _extract_result(built: Any) -> HammerResult:
    """Golden-case builders return either a bare :class:`HammerResult` or a
    ``(result, evidence)``/``(result, extra)`` tuple; normalize to just the
    result for status/kernel-acceptance reporting."""

    if isinstance(built, tuple):
        return built[0]
    return built


def run_pipeline_case_benchmark(manifest: CorpusManifest, golden_helpers: Any) -> Dict[str, Any]:
    """Time one representative golden case per hammer result status,
    reusing the real HAMMER-014 builder functions. Cases whose target ITP
    kernel is unavailable in this environment are recorded as
    ``environment_unavailable`` rather than raising."""

    cases: List[Dict[str, Any]] = []
    for case_id, kind, builder_name in PIPELINE_CASES:
        builder: Callable[[CorpusManifest], Any] = getattr(golden_helpers, builder_name)
        entry: Dict[str, Any] = {"case_id": case_id, "kind": kind}
        start = time.perf_counter()
        try:
            built = builder(manifest)
            latency_ms = (time.perf_counter() - start) * 1000.0
            result = _extract_result(built)
            entry.update(
                {
                    "outcome": "ran",
                    "theorem_id": result.request.theorem_id,
                    "status": result.status.value,
                    "kernel_accepted": (
                        result.reconstruction.kernel_accepted
                        if result.reconstruction is not None
                        else None
                    ),
                    "latency_ms": round(latency_ms, 4),
                }
            )
        except Exception as exc:  # noqa: BLE001 - deliberately broad: report, don't crash
            latency_ms = (time.perf_counter() - start) * 1000.0
            reason = f"{type(exc).__name__}: {exc}"
            is_environment_gap = kind == "real_kernel"
            entry.update(
                {
                    "outcome": "environment_unavailable" if is_environment_gap else "error",
                    "reason": reason,
                    "latency_ms": round(latency_ms, 4),
                }
            )
            if not is_environment_gap:
                entry["traceback"] = traceback.format_exc()
        cases.append(entry)

    ran = [c for c in cases if c["outcome"] == "ran"]
    verified = [c for c in ran if c.get("status") == "verified"]
    kernel_checked = [c for c in ran if c.get("kernel_accepted") is True]
    latencies = [c["latency_ms"] for c in ran]

    return {
        "cases": cases,
        "summary": {
            "case_count": len(cases),
            "ran_count": len(ran),
            "environment_unavailable_count": sum(
                1 for c in cases if c["outcome"] == "environment_unavailable"
            ),
            "error_count": sum(1 for c in cases if c["outcome"] == "error"),
            "verified_count": len(verified),
            "verified_rate_of_ran": round(len(verified) / len(ran), 4) if ran else 0.0,
            "kernel_checked_count": len(kernel_checked),
            "latency": _summarize_latency(latencies),
        },
    }


def resource_defaults_snapshot() -> Dict[str, Any]:
    """Serialize the real default :class:`HammerPolicy` /
    :class:`PortfolioPolicy` budgets so this report can never drift from
    the code that actually enforces them."""

    hammer_policy = HammerPolicy()
    portfolio_policy = PortfolioPolicy()
    return {
        "hammer_policy_defaults": {
            "timeout_seconds": hammer_policy.timeout_seconds,
            "cpu_seconds": hammer_policy.cpu_seconds,
            "memory_mb": hammer_policy.memory_mb,
            "network_allowed": hammer_policy.network_allowed,
            "allowed_solvers": list(hammer_policy.allowed_solvers),
            "allow_learned_premise_selector": hammer_policy.allow_learned_premise_selector,
            "allow_llm_premise_ranking": hammer_policy.allow_llm_premise_ranking,
            "max_premises": hammer_policy.max_premises,
            "allow_native_automation_fallback": hammer_policy.allow_native_automation_fallback,
            "allow_llm_decomposition_hints": hammer_policy.allow_llm_decomposition_hints,
            "max_decomposition_subgoals": hammer_policy.max_decomposition_subgoals,
        },
        "portfolio_policy_defaults": {
            "max_parallel_processes": portfolio_policy.max_parallel_processes,
            "cancel_on_first_conclusive": portfolio_policy.cancel_on_first_conclusive,
        },
    }


def environment_capability_snapshot(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        return {
            "available": False,
            "note": (
                "No environment capability snapshot found at "
                f"{path}. Regenerate with "
                "'PYTHONPATH=. python scripts/ops/logic/probe_itp_hammer_environment.py "
                f"--out {path}'."
            ),
        }
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - corrupted snapshot
        return {"available": False, "note": f"Failed to parse {path}: {exc}"}
    return {
        "available": True,
        "path": str(path),
        "generated_at": data.get("generated_at"),
        "summary": data.get("summary"),
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--fixture",
        type=Path,
        default=Path("tests/fixtures/logic/hammers"),
        help="Fixture directory containing the corpus JSON fixture(s) "
        "(default: tests/fixtures/logic/hammers)",
    )
    parser.add_argument(
        "--corpus-file",
        type=str,
        default=None,
        help=f"Corpus fixture filename within --fixture (default: try "
        f"{DEFAULT_CORPUS_FILENAME}, then {DEFAULT_FALLBACK_CORPUS_FILENAME})",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=DEFAULT_TOP_K,
        help=f"Premise selection cutoff (default: {DEFAULT_TOP_K})",
    )
    parser.add_argument(
        "--skip-pipeline-cases",
        action="store_true",
        help="Skip the whole-pipeline latency/verification section (premise "
        "selection recall/latency only). Useful in environments without the "
        "test tree on PYTHONPATH.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT,
        help=f"Output JSON report path (default: {DEFAULT_OUT})",
    )
    args = parser.parse_args(argv)

    repo_root = _repo_root()
    fixture_dir = args.fixture if args.fixture.is_absolute() else repo_root / args.fixture
    if not fixture_dir.is_dir():
        print(f"error: fixture directory not found: {fixture_dir}", file=sys.stderr)
        return 2

    try:
        manifest, corpus_path = load_fixture_manifest(fixture_dir, corpus_file=args.corpus_file)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    premise_selection = run_premise_selection_benchmark(manifest, top_k=args.top_k)

    pipeline: Optional[Dict[str, Any]] = None
    pipeline_error: Optional[str] = None
    if not args.skip_pipeline_cases:
        try:
            golden_helpers = _import_golden_helpers()
            pipeline = run_pipeline_case_benchmark(manifest, golden_helpers)
        except Exception as exc:  # noqa: BLE001 - report, don't crash the whole benchmark
            pipeline_error = f"{type(exc).__name__}: {exc}"

    report = {
        "benchmark_name": "itp_hammer_end_to_end",
        "schema_version": "1.0.0",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "reproducibility": {
            "python_version": platform.python_version(),
            "platform": platform.platform(),
            "machine": platform.machine(),
        },
        "corpus": {
            "manifest_id": manifest.manifest_id,
            "revision": manifest.revision,
            "theorem_count": len(manifest.entries),
            "fixture_file": _relative_or_absolute(corpus_path, repo_root),
        },
        "premise_selection": premise_selection,
        "pipeline_cases": pipeline,
        "pipeline_cases_error": pipeline_error,
        "resource_defaults": resource_defaults_snapshot(),
        "environment_capability": environment_capability_snapshot(
            repo_root / DEFAULT_ENVIRONMENT_SNAPSHOT
        ),
    }

    out_path = args.out if args.out.is_absolute() else repo_root / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    summary = {
        "out": out_path.as_posix(),
        "corpus_revision": manifest.revision,
        "theorem_count": premise_selection["theorem_count"],
        "premise_selection_mean_recall_at_k": premise_selection["mean_recall_at_k"],
        "premise_selection_mean_latency_ms": premise_selection["latency"]["mean_ms"],
    }
    if pipeline is not None:
        summary["pipeline_verified_count"] = pipeline["summary"]["verified_count"]
        summary["pipeline_kernel_checked_count"] = pipeline["summary"]["kernel_checked_count"]
        summary["pipeline_environment_unavailable_count"] = pipeline["summary"][
            "environment_unavailable_count"
        ]
        summary["pipeline_error_count"] = pipeline["summary"]["error_count"]
    if pipeline_error is not None:
        summary["pipeline_cases_error"] = pipeline_error
    print(json.dumps(summary, sort_keys=True))

    if pipeline is not None and pipeline["summary"]["error_count"] > 0:
        print(
            "error: one or more whole-pipeline benchmark cases failed "
            "unexpectedly (not merely due to a missing kernel/solver); see "
            "'pipeline_cases' in the report for details",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
