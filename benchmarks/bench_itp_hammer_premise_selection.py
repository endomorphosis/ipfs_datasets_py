#!/usr/bin/env python3
"""Held-out recall/latency benchmark: deterministic baseline vs. the
opt-in learned/graph-based premise selector (HAMMER-005).

This is the reproducibility harness the ``## HAMMER-005`` entry of
``docs/logic/itp_hammer_taskboard.todo.md`` requires: "a pinned model
digest, held-out recall/latency comparison, reproducible feature
extraction, opt-in configuration, and a fallback to the baseline when the
model is missing or fails." See ``docs/logic/itp_hammer_learned_selection.md``
for the full narrative methodology this script implements.

Methodology
-----------
For every theorem ``T`` in the fixture corpus, held one out at a time:

1. Build the goal from ``T``'s own statement/imports
   (``GoalFeatures.from_theorem_entry``), self-excluding ``T`` from its own
   candidate pool -- exactly the shape
   ``premise_selection.select_premises_for_theorem`` and
   ``learned_selector.select_premises_for_theorem_gated`` already use.
2. Compute the proxy "relevant" set for ``T``:
   ``learned_selector.relevant_theorem_ids_by_import_overlap`` -- every
   *other* corpus theorem sharing at least one import/module with ``T``.
   This is a reproducible, ground-truth-free proxy (the corpus manifest
   does not record an explicit theorem-to-theorem dependency graph, only
   each theorem's own imports); see the module docstring for the rationale.
3. Run the deterministic baseline (``premise_selection.select_premises_for_theorem``)
   and the gated learned/graph-based selector
   (``learned_selector.select_premises_for_theorem_gated``, opted in via a
   ``LearnedSelectorConfig``/``HammerPolicy`` pinned to the fixture model's
   digest), timing each call.
4. Score both selectors' ``selected`` premise-id lists against the relevant
   set with recall@k and reciprocal rank.

The script also runs an explicit "fallback smoke test": it points a second,
otherwise-identical gated call at a nonexistent model path, and asserts
(recording the result rather than raising) that the call transparently
falls back to the deterministic baseline rather than erroring out --
directly exercising the "fallback to the baseline when the model is missing"
acceptance criterion.

Usage
-----
    PYTHONPATH=. python benchmarks/bench_itp_hammer_premise_selection.py \\
        --fixture tests/fixtures/logic/hammers \\
        --out data/logic/itp_hammer/premise-selection-benchmark.json
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ipfs_datasets_py.logic.hammers.corpus import CorpusManifest, CorpusSource  # noqa: E402
from ipfs_datasets_py.logic.hammers.models import HammerPolicy, ITPKind  # noqa: E402
from ipfs_datasets_py.logic.hammers.premise_selection import (  # noqa: E402
    DETERMINISTIC_BASELINE_METHOD,
    select_premises_for_theorem,
)
from ipfs_datasets_py.logic.hammers.learned_selector import (  # noqa: E402
    LEARNED_SELECTION_METHOD_PREFIX,
    LearnedModelArtifact,
    LearnedSelectorConfig,
    SelectorFallbackReason,
    compute_recall_at_k,
    compute_reciprocal_rank,
    relevant_theorem_ids_by_import_overlap,
    select_premises_for_theorem_gated,
)

#: Default fixture directory/file names, resolved relative to ``--fixture``.
DEFAULT_CORPUS_FILENAME = "premise_selection_corpus.json"
DEFAULT_MODEL_FILENAME = "learned_selector_model.json"
DEFAULT_TOP_K = 5

#: Default output path when ``--out`` is not given, matching the taskboard's
#: validation command.
DEFAULT_OUT = Path("data/logic/itp_hammer/premise-selection-benchmark.json")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def load_fixture_manifest(corpus_path: Path) -> CorpusManifest:
    """Build a :class:`CorpusManifest` from the declarative fixture JSON at
    ``corpus_path`` (see ``tests/fixtures/logic/hammers/premise_selection_corpus.json``
    for the schema this expects: a single declared corpus source plus a list
    of theorem statements/imports)."""

    payload = json.loads(corpus_path.read_text(encoding="utf-8"))

    manifest = CorpusManifest(manifest_id=f"{payload['corpus_id']}-benchmark")
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
    return manifest


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


def run_held_out_comparison(
    manifest: CorpusManifest,
    *,
    top_k: int,
    learned_config: LearnedSelectorConfig,
    policy: HammerPolicy,
) -> Dict[str, Any]:
    """Run the held-out baseline-vs-learned comparison over every theorem in
    ``manifest`` and return a JSON-serializable report."""

    per_theorem: List[Dict[str, Any]] = []
    baseline_latencies: List[float] = []
    learned_latencies: List[float] = []
    baseline_recalls: List[float] = []
    learned_recalls: List[float] = []
    baseline_mrrs: List[float] = []
    learned_mrrs: List[float] = []
    learned_fallback_count = 0

    for entry in manifest.iter_theorems():
        theorem_id = entry.theorem_id
        relevant_ids = relevant_theorem_ids_by_import_overlap(manifest, theorem_id)

        start = time.perf_counter()
        baseline_result = select_premises_for_theorem(manifest, theorem_id, top_k=top_k)
        baseline_latency_ms = (time.perf_counter() - start) * 1000.0

        baseline_selected_ids = [p.premise_id for p in baseline_result.selected]
        baseline_recall = compute_recall_at_k(baseline_selected_ids, relevant_ids)
        baseline_mrr = compute_reciprocal_rank(baseline_selected_ids, relevant_ids)

        learned_outcome = select_premises_for_theorem_gated(
            manifest,
            theorem_id,
            top_k=top_k,
            policy=policy,
            learned_config=learned_config,
        )
        learned_selected_ids = [p.premise_id for p in learned_outcome.selection.selected]
        learned_recall = compute_recall_at_k(learned_selected_ids, relevant_ids)
        learned_mrr = compute_reciprocal_rank(learned_selected_ids, relevant_ids)

        if not learned_outcome.used_learned_selector:
            learned_fallback_count += 1

        baseline_latencies.append(baseline_latency_ms)
        learned_latencies.append(learned_outcome.latency_ms)
        baseline_recalls.append(baseline_recall)
        learned_recalls.append(learned_recall)
        baseline_mrrs.append(baseline_mrr)
        learned_mrrs.append(learned_mrr)

        per_theorem.append(
            {
                "theorem_id": theorem_id,
                "relevant_count": len(relevant_ids),
                "baseline": {
                    "selected_ids": baseline_selected_ids,
                    "recall_at_k": round(baseline_recall, 4),
                    "reciprocal_rank": round(baseline_mrr, 4),
                    "latency_ms": round(baseline_latency_ms, 4),
                },
                "learned": {
                    "selected_ids": learned_selected_ids,
                    "recall_at_k": round(learned_recall, 4),
                    "reciprocal_rank": round(learned_mrr, 4),
                    "latency_ms": round(learned_outcome.latency_ms, 4),
                    "used_learned_selector": learned_outcome.used_learned_selector,
                    "fallback_reason": learned_outcome.fallback_reason.value,
                },
            }
        )

    return {
        "theorem_count": len(per_theorem),
        "top_k": top_k,
        "baseline": {
            "selection_method": DETERMINISTIC_BASELINE_METHOD,
            "mean_recall_at_k": round(statistics.mean(baseline_recalls), 4) if baseline_recalls else 0.0,
            "mean_reciprocal_rank": round(statistics.mean(baseline_mrrs), 4) if baseline_mrrs else 0.0,
            "latency": _summarize_latency(baseline_latencies),
        },
        "learned": {
            "selection_method_prefix": LEARNED_SELECTION_METHOD_PREFIX,
            "mean_recall_at_k": round(statistics.mean(learned_recalls), 4) if learned_recalls else 0.0,
            "mean_reciprocal_rank": round(statistics.mean(learned_mrrs), 4) if learned_mrrs else 0.0,
            "latency": _summarize_latency(learned_latencies),
            "fallback_count": learned_fallback_count,
            "fallback_rate": round(learned_fallback_count / len(per_theorem), 4) if per_theorem else 0.0,
        },
        "per_theorem": per_theorem,
    }


def run_fallback_smoke_test(
    manifest: CorpusManifest,
    *,
    top_k: int,
    policy: HammerPolicy,
) -> Dict[str, Any]:
    """Directly exercise the "fallback to the baseline when the model is
    missing" acceptance criterion: point a gated call at a model path that
    does not exist and confirm the call still returns a valid baseline
    selection rather than raising."""

    missing_config = LearnedSelectorConfig(
        enabled=True,
        model_path=str(_repo_root() / "data" / "logic" / "itp_hammer" / "__does_not_exist__.json"),
        pinned_model_digest="sha256:" + "0" * 64,
    )
    theorem_id = manifest.iter_theorems()[0].theorem_id
    outcome = select_premises_for_theorem_gated(
        manifest,
        theorem_id,
        top_k=top_k,
        policy=policy,
        learned_config=missing_config,
    )
    ok = (
        not outcome.used_learned_selector
        and outcome.fallback_reason == SelectorFallbackReason.MODEL_MISSING
        and outcome.selection.selection_method == DETERMINISTIC_BASELINE_METHOD
    )
    return {
        "theorem_id": theorem_id,
        "used_learned_selector": outcome.used_learned_selector,
        "fallback_reason": outcome.fallback_reason.value,
        "selection_method": outcome.selection.selection_method,
        "passed": ok,
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--fixture",
        type=Path,
        default=Path("tests/fixtures/logic/hammers"),
        help="Fixture directory containing the corpus/model JSON files "
        "(default: tests/fixtures/logic/hammers)",
    )
    parser.add_argument(
        "--corpus-file",
        type=str,
        default=DEFAULT_CORPUS_FILENAME,
        help=f"Corpus fixture filename within --fixture (default: {DEFAULT_CORPUS_FILENAME})",
    )
    parser.add_argument(
        "--model-file",
        type=str,
        default=DEFAULT_MODEL_FILENAME,
        help=f"Learned-model fixture filename within --fixture (default: {DEFAULT_MODEL_FILENAME})",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=DEFAULT_TOP_K,
        help=f"Premise selection cutoff for both selectors (default: {DEFAULT_TOP_K})",
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
    corpus_path = fixture_dir / args.corpus_file
    model_path = fixture_dir / args.model_file

    if not corpus_path.is_file():
        print(f"error: corpus fixture not found: {corpus_path}", file=sys.stderr)
        return 2
    if not model_path.is_file():
        print(f"error: model fixture not found: {model_path}", file=sys.stderr)
        return 2

    manifest = load_fixture_manifest(corpus_path)

    # Pin the digest from the artifact actually shipped in the fixture --
    # in a real deployment this pinned value would come from a separate,
    # trusted operator-controlled config, not be re-derived from the same
    # file being loaded (see docs/logic/itp_hammer_learned_selection.md
    # section 6 for that caveat). Loading it here still exercises the full
    # digest-verification code path (`LearnedModelArtifact.load` recomputes
    # and checks the digest against the value stamped *inside* the file).
    pinned_artifact = LearnedModelArtifact.load(model_path)
    learned_config = LearnedSelectorConfig(
        enabled=True,
        model_path=str(model_path),
        pinned_model_digest=pinned_artifact.model_digest,
    )
    policy = HammerPolicy(allow_learned_premise_selector=True, max_premises=max(64, args.top_k))

    comparison = run_held_out_comparison(
        manifest, top_k=args.top_k, learned_config=learned_config, policy=policy
    )
    fallback_smoke_test = run_fallback_smoke_test(manifest, top_k=args.top_k, policy=policy)

    report = {
        "benchmark_name": "itp_hammer_premise_selection",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "corpus_revision": manifest.revision,
        "corpus_fixture": str(corpus_path.relative_to(repo_root))
        if corpus_path.is_relative_to(repo_root)
        else str(corpus_path),
        "model_fixture": str(model_path.relative_to(repo_root))
        if model_path.is_relative_to(repo_root)
        else str(model_path),
        "model_id": pinned_artifact.model_id,
        "model_digest": pinned_artifact.model_digest,
        "feature_version": pinned_artifact.feature_version,
        "comparison": comparison,
        "fallback_smoke_test": fallback_smoke_test,
    }

    out_path = args.out if args.out.is_absolute() else repo_root / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    summary = {
        "out": out_path.as_posix(),
        "theorem_count": comparison["theorem_count"],
        "baseline_mean_recall_at_k": comparison["baseline"]["mean_recall_at_k"],
        "learned_mean_recall_at_k": comparison["learned"]["mean_recall_at_k"],
        "baseline_mean_latency_ms": comparison["baseline"]["latency"]["mean_ms"],
        "learned_mean_latency_ms": comparison["learned"]["latency"]["mean_ms"],
        "learned_fallback_count": comparison["learned"]["fallback_count"],
        "fallback_smoke_test_passed": fallback_smoke_test["passed"],
    }
    print(json.dumps(summary, sort_keys=True))

    if not fallback_smoke_test["passed"]:
        print(
            "error: fallback smoke test did not fall back to the deterministic baseline "
            "as expected",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
