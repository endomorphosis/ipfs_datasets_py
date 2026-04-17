from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ipfs_datasets_py.processors.legal_data.bluebook_linker_fuzz_harness import (
    run_bluebook_linker_fuzz_harness,
)


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def _read_input_candidates(path_value: str | None) -> str | None:
    path_text = str(path_value or "").strip()
    if not path_text:
        return None
    if path_text == "-":
        return sys.stdin.read()
    return Path(path_text).expanduser().read_text(encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate Bluebook citation fuzz cases with llm_router and exercise linker + recovery flows."
    )
    parser.add_argument("--samples", type=int, default=12, help="Number of LLM-generated citation cases to execute.")
    parser.add_argument("--provider", help="llm_router provider name, e.g. openrouter or hf_inference_api.")
    parser.add_argument("--model", dest="model_name", help="Model name to pass to llm_router.")
    parser.add_argument("--temperature", type=float, default=1.0, help="Sampling temperature for citation generation.")
    parser.add_argument("--corpora", default="", help="Comma-separated corpus hints for generation.")
    parser.add_argument("--states", default="", help="Comma-separated state-code hints for generation.")
    parser.add_argument(
        "--input-candidates",
        help=(
            "Read Bluebook fuzz candidates from a JSON/fenced-JSON file instead of calling llm_router. "
            "Use '-' to read from stdin. Prior harness artifacts with a top-level candidates list are accepted."
        ),
    )
    parser.add_argument("--adversarial-ratio", type=float, default=0.35, help="Approximate ratio of adversarial citations.")
    parser.add_argument("--disable-hf-fallback", action="store_true", help="Disable Hugging Face dataset fallback in the linker.")
    parser.add_argument("--disable-exhaustive", action="store_true", help="Skip exhaustive canonical corpus lookup before recovery.")
    parser.add_argument("--disable-recovery", action="store_true", help="Skip search/recovery for unresolved citations.")
    parser.add_argument("--seed-from-corpora", action="store_true", help="Sample real corpus rows first and feed seeded examples into the LLM prompt.")
    parser.add_argument("--seed-only", action="store_true", help="Execute grounded sampled corpus citations directly without LLM generation.")
    parser.add_argument("--seed-examples-per-corpus", type=int, default=2, help="How many grounded seed examples to sample from each corpus.")
    parser.add_argument("--max-seed-examples-per-state", type=int, default=0, help="Optional cap for grounded seed examples per corpus/state partition.")
    parser.add_argument("--max-seed-examples-per-source", type=int, default=0, help="Optional cap for grounded seed examples per source parquet slice.")
    parser.add_argument("--sampling-shuffle-seed", type=int, default=0, help="Deterministic shuffle seed for stratified seeded sampling.")
    parser.add_argument("--recovery-max-candidates", type=int, default=8, help="Max live/archive candidates per unresolved citation.")
    parser.add_argument("--recovery-archive-top-k", type=int, default=3, help="How many recovered URLs to archive.")
    parser.add_argument("--max-acceptable-failure-rate", type=float, default=0.10, help="Failure-rate threshold used for corpus-level actionability.")
    parser.add_argument("--min-actionable-failures", type=int, default=2, help="Minimum failing samples before a corpus/cluster becomes actionable.")
    parser.add_argument("--merge-recovered-rows", action="store_true", help="Merge produced recovery manifests into local canonical parquet files.")
    parser.add_argument("--publish-to-hf", action="store_true", help="Upload recovery manifests to the canonical Hugging Face repo.")
    parser.add_argument("--hf-token", help="Optional Hugging Face token override.")
    parser.add_argument("--output-dir", default="artifacts/bluebook_linker_fuzz", help="Directory for run artifacts.")
    parser.add_argument("--json", action="store_true", help="Emit the full run payload as JSON.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    input_candidates = _read_input_candidates(args.input_candidates)
    input_generate = (lambda *_, **__: input_candidates) if input_candidates is not None else None

    run = asyncio.run(
        run_bluebook_linker_fuzz_harness(
            sample_count=max(1, int(args.samples)),
            provider=args.provider,
            model_name=args.model_name,
            temperature=float(args.temperature),
            corpus_keys=_split_csv(args.corpora),
            state_codes=_split_csv(args.states),
            adversarial_ratio=float(args.adversarial_ratio),
            allow_hf_fallback=not bool(args.disable_hf_fallback),
            exhaustive=not bool(args.disable_exhaustive),
            enable_recovery=not bool(args.disable_recovery),
            seed_from_corpora=bool(args.seed_from_corpora),
            seed_only=bool(args.seed_only),
            seed_examples_per_corpus=max(1, int(args.seed_examples_per_corpus)),
            max_seed_examples_per_state=(max(1, int(args.max_seed_examples_per_state)) if int(args.max_seed_examples_per_state) > 0 else None),
            max_seed_examples_per_source=(max(1, int(args.max_seed_examples_per_source)) if int(args.max_seed_examples_per_source) > 0 else None),
            sampling_shuffle_seed=int(args.sampling_shuffle_seed),
            max_acceptable_failure_rate=max(0.0, min(1.0, float(args.max_acceptable_failure_rate))),
            min_actionable_failures=max(1, int(args.min_actionable_failures)),
            recovery_max_candidates=max(1, int(args.recovery_max_candidates)),
            recovery_archive_top_k=max(0, int(args.recovery_archive_top_k)),
            publish_to_hf=bool(args.publish_to_hf),
            hf_token=args.hf_token,
            merge_recovered_rows=bool(args.merge_recovered_rows),
            output_dir=Path(args.output_dir),
            llm_generate_func=input_generate,
        )
    )

    if args.json:
        print(json.dumps(run.to_dict(), indent=2, sort_keys=True))
    else:
        summary = run.summary
        print(f"Executed {summary['sample_count_executed']} citation cases")
        print(f"Matched attempts: {summary['matched_attempt_count']} ({summary['matched_attempt_ratio']:.1%})")
        print(f"Unmatched citations: {summary['unmatched_citation_count']}")
        print(f"Recoveries: {summary['recovery_count']}")
        print(f"Merged recoveries: {summary['merged_recovery_count']}")
        coverage = summary.get("coverage_by_corpus") or {}
        actionable = list(coverage.get("actionable_corpora") or [])
        print(f"Actionable corpora: {', '.join(actionable) if actionable else 'none'}")
        patch_clusters = list(summary.get("failure_patch_clusters") or [])
        if patch_clusters:
            top = patch_clusters[0]
            print(
                "Top failure cluster: "
                f"{top.get('corpus_key')} @ {top.get('host') or 'unknown-host'} "
                f"-> {top.get('target_file') or 'no-target-file'} "
                f"({top.get('failure_count')} failures)"
            )
        backlog_path = str(summary.get("failure_patch_backlog_path") or "").strip()
        if backlog_path:
            print(f"Patch backlog: {backlog_path}")
        if run.output_path:
            print(f"Artifact: {run.output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
