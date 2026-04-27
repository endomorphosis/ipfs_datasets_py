#!/usr/bin/env python3
"""Run the agentic legal-corpus daemon across state laws, court rules, and admin rules.

This wrapper standardizes three things for full-state runs:
1. Shared cache configuration so repeated fetches reuse archived/live results.
2. Stable output layout under a single root directory.
3. Failure handoff artifacts that summarize likely scraper patch targets.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional

from ipfs_datasets_py.processors.legal_scrapers.state_laws_agentic_daemon import (
    PostCycleReleaseConfig,
    StateLawsAgenticDaemon,
    StateLawsAgenticDaemonConfig,
)
from ipfs_datasets_py.processors.legal_scrapers.state_laws_scraper import US_STATES


CorpusRunner = Callable[..., Awaitable[Dict[str, Any]]]


CORPUS_RUNNERS: Dict[str, str] = {
    "state_laws": "state_laws",
    "state_court_rules": "state_court_rules",
    "state_admin_rules": "state_admin_rules",
}

CORE_PATCH_TARGETS: Dict[str, List[str]] = {
    "state_laws": [
        "ipfs_datasets_py/processors/legal_scrapers/state_laws_scraper.py",
        "ipfs_datasets_py/processors/legal_scrapers/state_laws_verifier.py",
        "ipfs_datasets_py/processors/legal_scrapers/state_scrapers/base_scraper.py",
    ],
    "state_court_rules": [
        "ipfs_datasets_py/processors/legal_scrapers/state_procedure_rules_scraper.py",
        "ipfs_datasets_py/processors/legal_scrapers/state_scrapers/base_scraper.py",
    ],
    "state_admin_rules": [
        "ipfs_datasets_py/processors/legal_scrapers/state_admin_rules_scraper.py",
        "ipfs_datasets_py/processors/legal_scrapers/state_scrapers/base_scraper.py",
    ],
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_states(value: str) -> List[str]:
    raw = str(value or "all").strip()
    if not raw or raw.lower() == "all":
        return list(US_STATES.keys())
    return [item.strip().upper() for item in raw.split(",") if item.strip().upper() in US_STATES]


def _parse_corpora(value: str) -> List[str]:
    raw = str(value or "all").strip().lower()
    if raw == "all":
        return list(CORPUS_RUNNERS.keys())
    requested = []
    for item in raw.split(","):
        key = item.strip().lower()
        if not key:
            continue
        if key in {"laws", "state_laws"}:
            requested.append("state_laws")
        elif key in {"court", "courts", "court_rules", "state_court_rules"}:
            requested.append("state_court_rules")
        elif key in {"admin", "admin_rules", "state_admin_rules"}:
            requested.append("state_admin_rules")
    seen = set()
    ordered: List[str] = []
    for item in requested:
        if item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered


def _parse_csv(value: Optional[str]) -> Optional[List[str]]:
    raw = str(value or "").strip()
    if not raw:
        return None
    items = [item.strip() for item in raw.split(",") if item.strip()]
    return items or None


def _state_code_to_scraper_file(state_code: str) -> Optional[str]:
    state_name = US_STATES.get(str(state_code or "").upper())
    if not state_name:
        return None

    slug = state_name.lower().replace(" ", "_").replace("-", "_")
    if str(state_code).upper() == "DC":
        slug = "district_of_columbia"

    rel = Path("ipfs_datasets_py/processors/legal_scrapers/state_scrapers") / f"{slug}.py"
    abs_path = (
        Path(__file__).resolve().parents[3]
        / "ipfs_datasets_py"
        / "processors"
        / "legal_scrapers"
        / "state_scrapers"
        / f"{slug}.py"
    )
    return str(rel) if abs_path.exists() else None


def _default_cache_env(output_root: Path, *, cache_to_ipfs: bool, pin_ipfs_pages: bool) -> Dict[str, str]:
    return {
        "IPFS_DATASETS_LEGAL_FETCH_CACHE_ENABLED": "1",
        "IPFS_DATASETS_LEGAL_FETCH_CACHE_IPFS_MIRROR": "1" if cache_to_ipfs else "0",
        "IPFS_DATASETS_LEGAL_FETCH_CACHE_DIR": str(output_root / "_shared_fetch_cache"),
        "LEGAL_SCRAPER_IPFS_PAGE_CACHE_ENABLED": "1",
        "LEGAL_SCRAPER_IPFS_PAGE_CACHE_PIN": "1" if pin_ipfs_pages else "0",
        "LEGAL_SCRAPER_IPFS_PAGE_CACHE_DIR": str(output_root / "_shared_ipfs_page_cache"),
    }


def _apply_env_overrides(env_overrides: Dict[str, str]) -> None:
    for key, value in env_overrides.items():
        os.environ[str(key)] = str(value)


def _load_existing_summary(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _build_patch_backlog_entry(corpus: str, summary: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    latest_cycle = dict(summary.get("latest_cycle") or {})
    if not latest_cycle:
        return None
    if bool(latest_cycle.get("passed")):
        return None

    critic = dict(latest_cycle.get("critic") or {})
    diagnostics = dict(latest_cycle.get("diagnostics") or {})
    router_assist = dict(latest_cycle.get("router_assist") or {})
    llm_review = dict(router_assist.get("llm_review") or {})
    state_action_plan = dict(critic.get("state_action_plan") or {})

    patch_targets: List[str] = []
    for path in CORE_PATCH_TARGETS.get(corpus, []):
        if path not in patch_targets:
            patch_targets.append(path)

    priority_states = [str(item).upper() for item in (critic.get("priority_states") or []) if str(item).strip()]
    if not priority_states:
        priority_states = [str(item).upper() for item in (llm_review.get("priority_states") or []) if str(item).strip()]

    for state_code in priority_states:
        scraper_file = _state_code_to_scraper_file(state_code)
        if scraper_file and scraper_file not in patch_targets:
            patch_targets.append(scraper_file)

    weak_states = []
    for row in diagnostics.get("fetch", {}).get("weak_states", []) or []:
        if isinstance(row, dict) and row.get("state"):
            weak_states.append(str(row.get("state")).upper())
    for state_code in weak_states:
        scraper_file = _state_code_to_scraper_file(state_code)
        if scraper_file and scraper_file not in patch_targets:
            patch_targets.append(scraper_file)

    state_reasons = {
        state_code: list((payload or {}).get("reasons") or [])
        for state_code, payload in state_action_plan.items()
        if isinstance(payload, dict)
    }

    return {
        "corpus": corpus,
        "status": latest_cycle.get("status"),
        "critic_score": latest_cycle.get("critic_score"),
        "issues": list(critic.get("issues") or []),
        "recommended_tactics": list(critic.get("recommended_next_tactics") or []),
        "priority_states": priority_states,
        "query_hints": list(critic.get("query_hints") or llm_review.get("query_hints") or []),
        "router_rationale": critic.get("router_rationale") or llm_review.get("rationale"),
        "patch_targets": patch_targets,
        "state_reasons": state_reasons,
    }


async def _run_corpus(
    *,
    corpus: str,
    states: List[str],
    output_root: Path,
    max_cycles: int,
    max_statutes: int,
    cycle_interval_seconds: float,
    explore_probability: float,
    archive_warmup_urls: int,
    per_state_timeout_seconds: float,
    scrape_timeout_seconds: float,
    target_score: float,
    stop_on_target_score: bool,
    min_document_recovery_ratio: float,
    stop_after_recovered_rows: bool,
    search_engines: Optional[List[str]],
    tactic: Optional[str],
    skip_passed: bool,
) -> Dict[str, Any]:
    corpus_output_dir = output_root / corpus
    corpus_output_dir.mkdir(parents=True, exist_ok=True)

    latest_summary_path = corpus_output_dir / "latest_summary.json"
    existing_summary = _load_existing_summary(latest_summary_path)
    if skip_passed and existing_summary and bool((existing_summary.get("latest_cycle") or {}).get("passed")):
        return {
            "status": "skipped",
            "reason": "already-passed",
            "summary": existing_summary,
            "output_dir": str(corpus_output_dir),
        }

    config = StateLawsAgenticDaemonConfig(
        corpus_key=CORPUS_RUNNERS[corpus],
        states=list(states),
        output_dir=str(corpus_output_dir),
        cycle_interval_seconds=cycle_interval_seconds,
        max_cycles=max_cycles,
        max_statutes=max_statutes,
        explore_probability=explore_probability,
        archive_warmup_urls=archive_warmup_urls,
        per_state_timeout_seconds=per_state_timeout_seconds,
        scrape_timeout_seconds=max(0.0, float(scrape_timeout_seconds or 0.0)),
        router_llm_timeout_seconds=20.0,
        router_embeddings_timeout_seconds=10.0,
        router_ipfs_timeout_seconds=10.0,
        min_document_recovery_ratio=min_document_recovery_ratio,
        stop_after_recovered_rows=stop_after_recovered_rows,
        search_engines_override=search_engines,
        forced_tactic_name=tactic,
        target_score=target_score,
        stop_on_target_score=stop_on_target_score,
        admin_agentic_max_candidates_per_state=1000,
        admin_agentic_max_fetch_per_state=1000,
        admin_agentic_max_results_per_domain=1000,
        admin_agentic_max_hops=4,
        admin_agentic_max_pages=1000,
        admin_parallel_assist_enabled=True,
        admin_parallel_assist_state_limit=6,
        admin_parallel_assist_max_urls_per_domain=20,
        admin_parallel_assist_timeout_seconds=per_state_timeout_seconds,
        post_cycle_release=PostCycleReleaseConfig(enabled=False),
    )
    daemon = StateLawsAgenticDaemon(config)

    started_at = _utc_now()
    summary = await daemon.run()
    finished_at = _utc_now()
    return {
        "status": "completed",
        "started_at": started_at,
        "finished_at": finished_at,
        "summary": summary,
        "output_dir": str(corpus_output_dir),
    }


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the agentic scraper daemon across all state legal corpora.")
    parser.add_argument("--states", default="all", help="Comma-separated state codes, or 'all'.")
    parser.add_argument(
        "--corpora",
        default="all",
        help="Comma-separated corpora: state_laws,state_court_rules,state_admin_rules or aliases laws,court,admin.",
    )
    parser.add_argument(
        "--output-root",
        default=str(Path.cwd() / "tmp" / "all_state_legal_corpora_agentic"),
        help="Directory containing per-corpus daemon outputs plus the aggregated summary.",
    )
    parser.add_argument("--max-cycles", type=int, default=1, help="Maximum daemon cycles per corpus.")
    parser.add_argument("--max-statutes", type=int, default=0, help="Optional per-run cap for debug/smoke runs. 0 means unlimited.")
    parser.add_argument("--cycle-interval-seconds", type=float, default=900.0, help="Sleep interval between daemon cycles when max-cycles > 1.")
    parser.add_argument("--explore-probability", type=float, default=0.30, help="Exploration probability for tactic selection.")
    parser.add_argument("--archive-warmup-urls", type=int, default=25, help="How many weak-state URLs to archive/warm after each cycle.")
    parser.add_argument("--per-state-timeout-seconds", type=float, default=86400.0, help="Per-state scrape timeout budget.")
    parser.add_argument("--scrape-timeout-seconds", type=float, default=0.0, help="Optional whole-corpus scrape timeout budget; 0 disables it.")
    parser.add_argument("--target-score", type=float, default=0.92, help="Critic score threshold used by each daemon.")
    parser.add_argument("--stop-on-target-score", action="store_true", help="Stop a corpus daemon early when it passes.")
    parser.add_argument("--min-document-recovery-ratio", type=float, default=0.0, help="Optional minimum processed-document recovery ratio gate.")
    parser.add_argument("--stop-after-recovered-rows", action="store_true", help="Finalize each daemon cycle immediately after recovered row artifacts are written.")
    parser.add_argument("--search-engines", default=None, help="Optional comma-separated search engine override for daemon tactics, e.g. duckduckgo.")
    parser.add_argument("--tactic", default=None, help="Force one tactic profile for each corpus daemon, e.g. document_first.")
    parser.add_argument("--skip-passed", action="store_true", help="Skip corpora whose existing latest summary already passed.")
    parser.add_argument("--cache-to-ipfs", action=argparse.BooleanOptionalAction, default=True, help="Mirror the shared fetch cache to IPFS.")
    parser.add_argument("--pin-ipfs-pages", action=argparse.BooleanOptionalAction, default=False, help="Pin per-page IPFS cache entries.")
    return parser


async def _main_async(args: argparse.Namespace) -> int:
    states = _parse_states(args.states)
    corpora = _parse_corpora(args.corpora)
    if not states:
        raise SystemExit("No valid states selected.")
    if not corpora:
        raise SystemExit("No valid corpora selected.")

    output_root = Path(args.output_root).expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    env_overrides = _default_cache_env(
        output_root,
        cache_to_ipfs=bool(args.cache_to_ipfs),
        pin_ipfs_pages=bool(args.pin_ipfs_pages),
    )
    _apply_env_overrides(env_overrides)

    aggregated: Dict[str, Any] = {
        "status": "running",
        "started_at": _utc_now(),
        "output_root": str(output_root),
        "states": states,
        "corpora": corpora,
        "cache_env": env_overrides,
        "runs": {},
        "patch_backlog": [],
    }
    aggregated_path = output_root / "aggregated_summary.json"
    aggregated_path.write_text(json.dumps(aggregated, indent=2), encoding="utf-8")

    for corpus in corpora:
        result = await _run_corpus(
            corpus=corpus,
            states=states,
            output_root=output_root,
            max_cycles=int(args.max_cycles),
            max_statutes=int(args.max_statutes),
            cycle_interval_seconds=float(args.cycle_interval_seconds),
            explore_probability=float(args.explore_probability),
            archive_warmup_urls=int(args.archive_warmup_urls),
            per_state_timeout_seconds=float(args.per_state_timeout_seconds),
            scrape_timeout_seconds=float(args.scrape_timeout_seconds),
            target_score=float(args.target_score),
            stop_on_target_score=bool(args.stop_on_target_score),
            min_document_recovery_ratio=float(args.min_document_recovery_ratio),
            stop_after_recovered_rows=bool(args.stop_after_recovered_rows),
            search_engines=_parse_csv(args.search_engines),
            tactic=args.tactic,
            skip_passed=bool(args.skip_passed),
        )
        aggregated["runs"][corpus] = result

        summary = result.get("summary")
        if isinstance(summary, dict):
            patch_entry = _build_patch_backlog_entry(corpus, summary)
            if patch_entry is not None:
                aggregated["patch_backlog"].append(patch_entry)

        aggregated_path.write_text(json.dumps(aggregated, indent=2), encoding="utf-8")

    pass_count = 0
    fail_count = 0
    skipped_count = 0
    for corpus in corpora:
        run_payload = dict(aggregated["runs"].get(corpus) or {})
        if run_payload.get("status") == "skipped":
            skipped_count += 1
            continue
        latest_cycle = dict((run_payload.get("summary") or {}).get("latest_cycle") or {})
        if bool(latest_cycle.get("passed")):
            pass_count += 1
        else:
            fail_count += 1

    aggregated.update(
        {
            "status": "success",
            "finished_at": _utc_now(),
            "pass_count": pass_count,
            "fail_count": fail_count,
            "skipped_count": skipped_count,
            "all_passed": fail_count == 0,
        }
    )
    aggregated_path.write_text(json.dumps(aggregated, indent=2), encoding="utf-8")

    print(json.dumps(aggregated, indent=2))
    return 0


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    return asyncio.run(_main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
