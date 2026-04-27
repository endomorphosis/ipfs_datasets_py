"""Agentic daemon for iterative canonical legal-corpus scraping improvement.

This module runs a persistent scrape -> review -> criticize -> optimize loop.
It steers the existing state legal scrapers by changing web-archiving tactics
via environment-driven provider ordering, then scores each cycle using corpus-
specific coverage and ETL diagnostics.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.util
import json
import logging
import math
import os
import random
import re
import shlex
import shutil
import signal
import sys
import threading
import traceback
from contextlib import contextmanager, suppress
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional, Sequence
from urllib.parse import urlparse

from .canonical_legal_corpora import get_canonical_legal_corpus
from .state_admin_rules_scraper import scrape_state_admin_rules
from .state_laws_scraper import (
    US_STATES,
    _aggregate_fetch_analytics,
    _compute_etl_readiness_summary,
    _compute_state_quality_metrics,
    scrape_state_laws,
)
from .state_procedure_rules_scraper import scrape_state_procedure_rules
from .state_laws_verifier import _build_operational_diagnostics
from .url_archive_cache import URLArchiveCache

logger = logging.getLogger(__name__)


ScrapeFunction = Callable[..., Awaitable[Dict[str, Any]]]


def _normalize_fetch_analytics_by_state(
    fetch_analytics_by_state: Dict[str, Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    normalized: Dict[str, Dict[str, Any]] = {}
    for state_code, metrics in fetch_analytics_by_state.items():
        if not isinstance(metrics, dict):
            continue

        state_key = str(state_code or "").upper().strip()
        if not state_key:
            continue

        current = dict(metrics)
        attempted = max(0, int(current.get("attempted", 0) or 0))
        success = max(0, int(current.get("success", 0) or 0))
        fallback_count = max(0, int(current.get("fallback_count", 0) or 0))

        if success > attempted:
            attempted = success
        if attempted > 0 and fallback_count > attempted:
            fallback_count = attempted

        current["attempted"] = attempted
        current["success"] = success
        current["fallback_count"] = fallback_count
        current["providers"] = (
            dict(current.get("providers") or {})
            if isinstance(current.get("providers"), dict)
            else {}
        )
        normalized[state_key] = current

    return normalized


def _merge_admin_agentic_fetch_analytics(
    base_fetch_analytics_by_state: Dict[str, Dict[str, Any]],
    *,
    agentic_report: Dict[str, Any],
) -> Dict[str, Dict[str, Any]]:
    merged = _normalize_fetch_analytics_by_state(base_fetch_analytics_by_state)

    per_state = agentic_report.get("per_state") if isinstance(agentic_report, dict) else {}
    if not isinstance(per_state, dict):
        return merged

    for state_code, state_report in per_state.items():
        if not isinstance(state_report, dict):
            continue

        inspected_urls = int(state_report.get("inspected_urls", 0) or 0)
        fetched_rules = int(state_report.get("fetched_rules", 0) or 0)
        if inspected_urls <= 0 and fetched_rules <= 0:
            continue

        state_key = str(state_code or "").upper().strip()
        if not state_key:
            continue

        current = dict(merged.get(state_key) or {})
        attempted = int(current.get("attempted", 0) or 0)
        success = int(current.get("success", 0) or 0)
        fallback_count = int(current.get("fallback_count", 0) or 0)
        providers = dict(current.get("providers") or {}) if isinstance(current.get("providers"), dict) else {}

        if attempted <= 0:
            attempted = inspected_urls
            success = fetched_rules
        else:
            attempted = max(attempted, inspected_urls)
            success = max(success, fetched_rules)

        if inspected_urls > 0:
            providers["agentic_discovery"] = max(
                int(providers.get("agentic_discovery", 0) or 0),
                inspected_urls,
            )

        current["attempted"] = attempted
        current["success"] = success
        current["fallback_count"] = fallback_count
        current["providers"] = providers
        merged[state_key] = current

    return _normalize_fetch_analytics_by_state(merged)


@dataclass(frozen=True)
class AgenticCorpusDefinition:
    """Configuration for one supported canonical legal corpus."""

    key: str
    display_name: str
    default_output_subdir: str
    scrape_func: ScrapeFunction
    max_items_kwarg: str
    hydrate_kwarg: str
    retry_zero_kwarg: str


def _corpus_definitions() -> Dict[str, AgenticCorpusDefinition]:
    return {
        "state_laws": AgenticCorpusDefinition(
            key="state_laws",
            display_name="State Laws",
            default_output_subdir="state_laws",
            scrape_func=scrape_state_laws,
            max_items_kwarg="max_statutes",
            hydrate_kwarg="hydrate_statute_text",
            retry_zero_kwarg="retry_zero_statute_states",
        ),
        "state_admin_rules": AgenticCorpusDefinition(
            key="state_admin_rules",
            display_name="State Administrative Rules",
            default_output_subdir="state_admin_rules",
            scrape_func=scrape_state_admin_rules,
            max_items_kwarg="max_rules",
            hydrate_kwarg="hydrate_rule_text",
            retry_zero_kwarg="retry_zero_rule_states",
        ),
        "state_court_rules": AgenticCorpusDefinition(
            key="state_court_rules",
            display_name="State Court Rules",
            default_output_subdir="state_court_rules",
            scrape_func=scrape_state_procedure_rules,
            max_items_kwarg="max_rules",
            hydrate_kwarg="hydrate_rule_text",
            retry_zero_kwarg="retry_zero_rule_states",
        ),
    }


@dataclass(frozen=True)
class ScraperTacticProfile:
    """Configurable tactic profile for one daemon scrape cycle."""

    name: str
    description: str
    scraper_method_order: List[str]
    search_engines: List[str]
    rate_limit_delay: float = 1.0
    parallel_workers: int = 6
    per_state_retry_attempts: int = 1
    min_full_text_chars: int = 300
    hydrate_statute_text: bool = True
    strict_full_text: bool = True
    archive_is_submit_on_miss: bool = True
    search_parallel_enabled: bool = True
    search_fallback_enabled: bool = True
    llm_provider: Optional[str] = None
    embeddings_provider: Optional[str] = None
    ipfs_backend: Optional[str] = None
    enable_ipfs_accelerate: Optional[bool] = None
    cloudflare_timeout_seconds: Optional[int] = None
    cloudflare_poll_interval_seconds: Optional[float] = None
    cloudflare_max_rate_limit_wait_seconds: Optional[float] = None
    cloudflare_limit: Optional[int] = None
    cloudflare_depth: Optional[int] = None
    cloudflare_render: Optional[bool] = None
    cloudflare_source: Optional[str] = None
    cloudflare_formats: Optional[List[str]] = None
    cloudflare_include_external_links: Optional[bool] = None
    cloudflare_include_subdomains: Optional[bool] = None


def default_tactic_profiles() -> Dict[str, ScraperTacticProfile]:
    """Return built-in tactic profiles that map to web_archiving strategies."""
    profiles = [
        ScraperTacticProfile(
            name="archival_first",
            description="Bias toward Common Crawl, Wayback, Archive.is, and IPWB before live fetches.",
            scraper_method_order=[
                "common_crawl",
                "wayback_machine",
                "archive_is",
                "ipwb",
                "playwright",
                "beautifulsoup",
                "readability",
                "requests_only",
            ],
            search_engines=["brave", "duckduckgo", "google_cse"],
            archive_is_submit_on_miss=True,
        ),
        ScraperTacticProfile(
            name="render_first",
            description="Bias toward JS-rendered and readability extraction for dynamic state portals.",
            scraper_method_order=[
                "playwright",
                "beautifulsoup",
                "readability",
                "common_crawl",
                "wayback_machine",
                "archive_is",
                "requests_only",
            ],
            search_engines=["brave", "google_cse", "duckduckgo"],
            parallel_workers=4,
            min_full_text_chars=240,
        ),
        ScraperTacticProfile(
            name="discovery_first",
            description="Bias toward broader discovery and relocation search when official URLs have drifted.",
            scraper_method_order=[
                "common_crawl",
                "playwright",
                "beautifulsoup",
                "wayback_machine",
                "archive_is",
                "newspaper",
                "readability",
                "requests_only",
            ],
            search_engines=["google_cse", "brave", "duckduckgo"],
            per_state_retry_attempts=2,
            rate_limit_delay=0.75,
        ),
        ScraperTacticProfile(
            name="precision_first",
            description="Bias toward cleaner live fetches when archive-heavy tactics return scaffold or nav noise.",
            scraper_method_order=[
                "beautifulsoup",
                "requests_only",
                "playwright",
                "readability",
                "common_crawl",
                "wayback_machine",
                "archive_is",
            ],
            search_engines=["brave", "duckduckgo"],
            archive_is_submit_on_miss=False,
            min_full_text_chars=360,
        ),
        ScraperTacticProfile(
            name="document_first",
            description="Bias toward Playwright/live downloads and processor-backed PDF/RTF extraction on document-heavy portals.",
            scraper_method_order=[
                "playwright",
                "requests_only",
                "beautifulsoup",
                "readability",
                "common_crawl",
                "wayback_machine",
                "archive_is",
            ],
            search_engines=["google_cse", "brave", "duckduckgo"],
            parallel_workers=4,
            per_state_retry_attempts=2,
            min_full_text_chars=180,
            enable_ipfs_accelerate=True,
        ),
        ScraperTacticProfile(
            name="router_assisted",
            description="Bias toward router-assisted query recovery, embedding-ranked tactic selection, and IPFS-backed review persistence on weak cycles.",
            scraper_method_order=[
                "common_crawl",
                "playwright",
                "wayback_machine",
                "archive_is",
                "beautifulsoup",
                "readability",
                "requests_only",
            ],
            search_engines=["google_cse", "brave", "duckduckgo"],
            parallel_workers=5,
            per_state_retry_attempts=2,
            min_full_text_chars=220,
            enable_ipfs_accelerate=True,
        ),
        ScraperTacticProfile(
            name="cloudflare_explore",
            description="Bias toward Cloudflare Browser Rendering crawl, rendered document discovery, and subdomain exploration when official rule portals are challenge-heavy or JS-gated.",
            scraper_method_order=[
                "cloudflare_browser_rendering",
                "playwright",
                "beautifulsoup",
                "readability",
                "common_crawl",
                "wayback_machine",
                "archive_is",
                "requests_only",
            ],
            search_engines=["google_cse", "brave", "duckduckgo"],
            parallel_workers=4,
            per_state_retry_attempts=2,
            min_full_text_chars=160,
            enable_ipfs_accelerate=True,
            cloudflare_timeout_seconds=180,
            cloudflare_poll_interval_seconds=2.0,
            cloudflare_max_rate_limit_wait_seconds=60.0,
            cloudflare_limit=4,
            cloudflare_depth=1,
            cloudflare_render=True,
            cloudflare_source="all",
            cloudflare_formats=["markdown", "html"],
            cloudflare_include_external_links=False,
            cloudflare_include_subdomains=True,
        ),
    ]
    return {profile.name: profile for profile in profiles}


@dataclass
class StateLawsAgenticDaemonConfig:
    """Configuration for the persistent canonical legal-corpus agentic daemon."""

    corpus_key: str = "state_laws"
    states: List[str] = field(default_factory=lambda: list(US_STATES.keys()))
    output_dir: Optional[str] = None
    cycle_interval_seconds: float = 900.0
    max_cycles: int = 0
    max_statutes: int = 0
    top_n_diagnostics: int = 8
    target_score: float = 0.92
    stop_on_target_score: bool = False
    explore_probability: float = 0.30
    archive_warmup_urls: int = 25
    archive_warmup_concurrency: int = 8
    document_artifact_capture_enabled: bool = True
    document_artifact_state_limit: int = 4
    document_artifact_urls_per_state: int = 2
    document_artifact_max_total: int = 8
    per_state_timeout_seconds: float = 86400.0
    scrape_timeout_seconds: float = 0.0
    scrape_heartbeat_seconds: float = 60.0
    admin_agentic_max_candidates_per_state: Optional[int] = 1000
    admin_agentic_max_fetch_per_state: Optional[int] = 1000
    admin_agentic_max_results_per_domain: Optional[int] = 1000
    admin_agentic_max_hops: Optional[int] = 4
    admin_agentic_max_pages: Optional[int] = 1000
    admin_agentic_fetch_concurrency: Optional[int] = None
    admin_parallel_assist_enabled: bool = True
    admin_parallel_assist_state_limit: int = 6
    admin_parallel_assist_max_urls_per_domain: int = 20
    admin_parallel_assist_timeout_seconds: float = 86400.0
    stop_after_recovered_rows: bool = False
    search_engines_override: Optional[List[str]] = None
    forced_tactic_name: Optional[str] = None
    router_llm_timeout_seconds: float = 20.0
    router_embeddings_timeout_seconds: float = 10.0
    router_ipfs_timeout_seconds: float = 10.0
    min_document_recovery_ratio: float = 0.0
    tactic_profiles: Dict[str, ScraperTacticProfile] = field(default_factory=default_tactic_profiles)
    random_seed: Optional[int] = None
    post_cycle_release: "PostCycleReleaseConfig" = field(default_factory=lambda: PostCycleReleaseConfig())


@dataclass
class PostCycleReleaseConfig:
    """Configuration for optional post-cycle canonical release automation."""

    enabled: bool = False
    dry_run: bool = False
    min_score: Optional[float] = None
    require_passed: bool = True
    timeout_seconds: int = 7200
    workspace_root: Optional[str] = None
    python_bin: Optional[str] = None
    publish_command: Optional[str] = None


class StateLawsAgenticDaemon:
    """Persistent daemon for state legal-corpus scraping optimization."""

    def __init__(self, config: Optional[StateLawsAgenticDaemonConfig] = None) -> None:
        self.config = config or StateLawsAgenticDaemonConfig()
        self.corpus = _corpus_definitions()[str(self.config.corpus_key or "state_laws")]
        self.states = self._normalize_states(self.config.states)
        self.output_dir = self._resolve_output_dir(self.config.output_dir, self.corpus.default_output_subdir)
        self.cycles_dir = self.output_dir / "cycles"
        self.cycles_dir.mkdir(parents=True, exist_ok=True)
        self.document_artifacts_dir = self.output_dir / "document_artifacts"
        self.document_artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.recovered_rows_dir = self.output_dir / "recovered_rows"
        self.recovered_rows_dir.mkdir(parents=True, exist_ok=True)
        self.state_file = self.output_dir / "daemon_state.json"
        self.latest_file = self.output_dir / "latest_summary.json"
        self.pending_retry_file = self.output_dir / "latest_pending_retry.json"
        self.url_archive_cache = URLArchiveCache(
            metadata_dir=str(self.output_dir / "url_archive_cache"),
            persist_to_ipfs=True,
        )
        self._rand = random.Random(self.config.random_seed)
        self._state = self._load_state()

    def _effective_tactic_payload(self, tactic: ScraperTacticProfile) -> Dict[str, Any]:
        payload = asdict(tactic)
        if self.corpus.key == "state_admin_rules":
            payload["rate_limit_delay"] = 0.2
            payload["strict_full_text"] = False
            payload["min_full_text_chars"] = 200
            payload["parallel_workers"] = 1
        return payload

    async def run(self) -> Dict[str, Any]:
        """Run the daemon until it reaches max cycles or target score."""
        executed = 0
        summaries: List[Dict[str, Any]] = []

        while True:
            if self.config.max_cycles > 0 and executed >= int(self.config.max_cycles):
                break

            cycle = await self.run_cycle()
            summaries.append(cycle)
            executed += 1
            self._log_cycle_followup(cycle)

            if self.config.stop_on_target_score and bool(cycle.get("passed")):
                break

            if self.config.max_cycles > 0 and executed >= int(self.config.max_cycles):
                break

            await asyncio.sleep(self._next_cycle_delay_seconds(cycle))

        summary = {
            "status": "success",
            "corpus": self.corpus.key,
            "output_dir": str(self.output_dir),
            "cycles_executed": executed,
            "states": list(self.states),
            "latest_cycle": summaries[-1] if summaries else None,
            "pending_retry": self._state.get("pending_retry"),
            "best_tactic": self._state.get("best_tactic"),
            "recommended_tactics": list(self._state.get("recommended_tactics") or []),
        }
        self.latest_file.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        return summary

    def preview_post_cycle_release_plan(
        self,
        *,
        cycle_index: int = 1,
        critic_score: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Build a post-cycle release plan without running a scrape cycle."""
        score = float(critic_score if critic_score is not None else self.config.target_score)
        plan = self._build_post_cycle_release_plan(cycle_index=cycle_index, critic_score=score)
        return {
            "status": "planned",
            "preview": True,
            "corpus": self.corpus.key,
            "workspace_root": str(plan["workspace_root"]),
            "artifacts": plan["artifacts"],
            "commands": plan["commands"],
            "critic_score": score,
        }

    def preview_runtime_readiness(self) -> Dict[str, Any]:
        """Summarize whether this host is ready for a real daemon run."""
        cloudflare = self._cloudflare_browser_rendering_availability()
        router = self._router_availability_snapshot()
        tactic_profiles = list(self.config.tactic_profiles.keys())
        recommended = [
            name
            for name in ("cloudflare_explore", "router_assisted", "document_first", "archival_first")
            if name in self.config.tactic_profiles
        ]
        return {
            "status": "ready" if bool(router.get("llm_router")) and bool(router.get("embeddings_router")) else "partial",
            "preview": True,
            "corpus": self.corpus.key,
            "output_dir": str(self.output_dir),
            "states": list(self.states),
            "state_count": len(self.states),
            "cloudflare_browser_rendering": cloudflare,
            "router": router,
            "tactic_profiles": tactic_profiles,
            "recommended_boot_tactics": recommended,
        }

    async def probe_cloudflare_browser_rendering(
        self,
        *,
        url: str = "https://example.com",
        limit: int = 1,
        depth: int = 0,
        render: bool = False,
        timeout_seconds: int = 45,
    ) -> Dict[str, Any]:
        """Run a lightweight live Browser Rendering probe without a full daemon cycle."""
        availability = self._cloudflare_browser_rendering_availability()
        if not bool(availability.get("available")):
            return {
                "status": "missing_credentials",
                "provider": "cloudflare_browser_rendering",
                "availability": availability,
                "submitted_url": url,
            }

        try:
            import requests
            from ipfs_datasets_py.processors.web_archiving.cloudflare_browser_rendering_engine import (
                cancel_cloudflare_browser_rendering_crawl,
                start_cloudflare_browser_rendering_crawl,
                _resolve_credentials,
            )

            account_id, api_token = _resolve_credentials()
            headers = {
                "Authorization": f"Bearer {api_token}",
                "Content-Type": "application/json",
            }

            verify_response = requests.get(
                "https://api.cloudflare.com/client/v4/user/tokens/verify",
                headers=headers,
                timeout=max(5, int(timeout_seconds)),
            )
            verify_payload = verify_response.json()

            accounts_response = requests.get(
                "https://api.cloudflare.com/client/v4/accounts",
                headers=headers,
                timeout=max(5, int(timeout_seconds)),
            )
            accounts_payload = accounts_response.json()

            markdown_response = requests.post(
                f"https://api.cloudflare.com/client/v4/accounts/{account_id}/browser-rendering/markdown",
                headers=headers,
                json={"url": url},
                timeout=max(5, int(timeout_seconds)),
            )
            markdown_payload = markdown_response.json()

            started = await start_cloudflare_browser_rendering_crawl(
                url,
                account_id=account_id,
                api_token=api_token,
                limit=max(1, int(limit)),
                depth=max(0, int(depth)),
                formats=["markdown"],
                render=bool(render),
                request_timeout_seconds=max(5, int(timeout_seconds)),
                max_rate_limit_wait_seconds=max(5.0, float(timeout_seconds)),
            )
            result = {
                "provider": "cloudflare_browser_rendering",
                "availability": availability,
                "submitted_url": url,
                "probe_mode": "start_only",
                "token_verify": {
                    "http_status": int(verify_response.status_code),
                    "success": bool(verify_payload.get("success")),
                    "errors": list(verify_payload.get("errors") or []),
                },
                "accounts_probe": {
                    "http_status": int(accounts_response.status_code),
                    "success": bool(accounts_payload.get("success")),
                    "errors": list(accounts_payload.get("errors") or []),
                    "result_count": len(list(accounts_payload.get("result") or [])),
                },
                "markdown_probe": {
                    "http_status": int(markdown_response.status_code),
                    "success": bool(markdown_payload.get("success")),
                    "errors": list(markdown_payload.get("errors") or []),
                },
            }
            result.update(started)
            if started.get("status") == "success" and str(started.get("job_id") or "").strip():
                result["cancel_after_probe"] = await cancel_cloudflare_browser_rendering_crawl(
                    str(started.get("job_id")),
                    request_timeout_seconds=max(5, int(timeout_seconds)),
                )
            return result
        except Exception as exc:
            return {
                "status": "error",
                "provider": "cloudflare_browser_rendering",
                "availability": availability,
                "submitted_url": url,
                "error": str(exc),
            }

    async def run_cycle(self) -> Dict[str, Any]:
        """Run one scrape-review-criticize-optimize cycle."""
        cycle_index = int(self._state.get("cycle_count", 0) or 0) + 1
        tactic_selection = self._select_tactic_with_context()
        tactic = tactic_selection["profile"]
        cycle_states = self._ordered_states_for_cycle()
        checkpoint_payload: Dict[str, Any] = {
            "cycle": cycle_index,
            "timestamp": datetime.now().isoformat(),
            "corpus": self.corpus.key,
            "states": list(self.states),
            "cycle_state_order": cycle_states,
            "status": "running",
            "stage": "scrape",
            "tactic": self._effective_tactic_payload(tactic),
            "tactic_selection": tactic_selection["details"],
        }
        self._write_cycle_checkpoint(cycle_index=cycle_index, payload=checkpoint_payload)
        scrape_result = await self._run_scrape_with_tactic(
            tactic,
            states=cycle_states,
            cycle_index=cycle_index,
            checkpoint_payload=checkpoint_payload,
        )

        metadata = scrape_result.get("metadata") or {}
        recovered_row_artifacts = self._write_recovered_row_artifacts(
            cycle_index=cycle_index,
            scrape_result=scrape_result,
        )
        deferred_retry = self._build_deferred_retry_plan(scrape_result)
        if deferred_retry:
            cycle_payload = self._build_deferred_retry_cycle_payload(
                cycle_index=cycle_index,
                tactic=tactic,
                scrape_result=scrape_result,
                metadata=metadata,
                deferred_retry=deferred_retry,
            )
            checkpoint_payload.update(
                {
                    "status": str(scrape_result.get("status") or "unknown"),
                    "stage": "deferred_retry",
                    "diagnostics": cycle_payload["diagnostics"],
                    "critic_score": cycle_payload["critic_score"],
                    "passed": False,
                    "critic": cycle_payload["critic"],
                    "metadata": metadata,
                    "deferred_retry": deferred_retry,
                    "recovered_row_artifacts": recovered_row_artifacts,
                    "tactic_selection": tactic_selection["details"],
                }
            )
            self._write_cycle_checkpoint(cycle_index=cycle_index, payload=checkpoint_payload)
            cycle_payload["tactic_selection"] = tactic_selection["details"]
            cycle_payload["recovered_row_artifacts"] = recovered_row_artifacts
            self._update_state(tactic=tactic, cycle_payload=cycle_payload)
            cycle_path = self.cycles_dir / f"cycle_{cycle_index:04d}.json"
            cycle_path.write_text(json.dumps(cycle_payload, indent=2), encoding="utf-8")
            self.latest_file.write_text(json.dumps(cycle_payload, indent=2), encoding="utf-8")
            self._clear_cycle_checkpoint(cycle_index=cycle_index)
            return cycle_payload

        diagnostics = self._build_diagnostics(scrape_result)
        if isinstance(recovered_row_artifacts, dict) and isinstance(diagnostics.get("documents"), dict):
            diagnostics["documents"] = dict(diagnostics["documents"])
            diagnostics["documents"]["recovered_row_artifacts"] = recovered_row_artifacts
        diagnostics = self._annotate_document_recovery_gate(diagnostics)
        critic_score = self._critic_score(diagnostics)
        passed = self._is_success(diagnostics, critic_score)
        critic = self._criticize_cycle(diagnostics)
        checkpoint_payload.update(
            {
                "status": str(scrape_result.get("status") or "unknown"),
                "stage": "review",
                "diagnostics": diagnostics,
                "critic_score": critic_score,
                "passed": passed,
                "critic": critic,
                "metadata": metadata,
                "recovered_row_artifacts": recovered_row_artifacts,
                "tactic_selection": tactic_selection["details"],
            }
        )
        self._write_cycle_checkpoint(cycle_index=cycle_index, payload=checkpoint_payload)
        if bool(self.config.stop_after_recovered_rows):
            router_assist = {"status": "skipped", "reason": "stop-after-recovered-rows"}
            parallel_admin_assist = {"status": "skipped", "reason": "stop-after-recovered-rows"}
            archive_warmup = {"status": "skipped", "reason": "stop-after-recovered-rows"}
            document_gap_report = {"status": "skipped", "reason": "stop-after-recovered-rows"}
            document_gap_report_path = None
            document_artifacts = {"status": "skipped", "reason": "stop-after-recovered-rows"}
            post_cycle_release = {"status": "skipped", "reason": "stop-after-recovered-rows"}
            checkpoint_payload.update(
                {
                    "stage": "finalize_after_recovered_rows",
                    "router_assist": router_assist,
                    "parallel_admin_assist": parallel_admin_assist,
                    "archive_warmup": archive_warmup,
                    "document_gap_report": document_gap_report,
                    "document_artifacts": document_artifacts,
                    "post_cycle_release": post_cycle_release,
                }
            )
            self._write_cycle_checkpoint(cycle_index=cycle_index, payload=checkpoint_payload)
            cycle_payload = {
                "cycle": cycle_index,
                "timestamp": datetime.now().isoformat(),
                "corpus": self.corpus.key,
                "states": list(self.states),
                "cycle_state_order": cycle_states,
                "status": str(scrape_result.get("status") or "unknown"),
                "tactic": self._effective_tactic_payload(tactic),
                "tactic_selection": tactic_selection["details"],
                "critic_score": critic_score,
                "passed": passed,
                "diagnostics": diagnostics,
                "critic": critic,
                "router_assist": router_assist,
                "parallel_admin_assist": parallel_admin_assist,
                "archive_warmup": archive_warmup,
                "document_gap_report": document_gap_report,
                "document_gap_report_path": document_gap_report_path,
                "document_artifacts": document_artifacts,
                "recovered_row_artifacts": recovered_row_artifacts,
                "post_cycle_release": post_cycle_release,
                "metadata": metadata,
                "stop_after_recovered_rows": True,
            }
            self._update_state(tactic=tactic, cycle_payload=cycle_payload)
            cycle_path = self.cycles_dir / f"cycle_{cycle_index:04d}.json"
            cycle_path.write_text(json.dumps(cycle_payload, indent=2), encoding="utf-8")
            self.latest_file.write_text(json.dumps(cycle_payload, indent=2), encoding="utf-8")
            self._clear_cycle_checkpoint(cycle_index=cycle_index)
            return cycle_payload
        checkpoint_payload.update({"stage": "router_review"})
        self._write_cycle_checkpoint(cycle_index=cycle_index, payload=checkpoint_payload)
        router_assist = await self._build_router_assist_report(
            cycle_index=cycle_index,
            tactic=tactic,
            diagnostics=diagnostics,
            critic=critic,
        )
        critic = self._merge_router_assist_into_critic(critic=critic, router_assist=router_assist)
        checkpoint_payload.update(
            {
                "stage": "parallel_admin_assist",
                "critic": critic,
                "router_assist": router_assist,
            }
        )
        self._write_cycle_checkpoint(cycle_index=cycle_index, payload=checkpoint_payload)
        parallel_admin_assist = await self._run_parallel_admin_assist(
            cycle_index=cycle_index,
            tactic=tactic,
            diagnostics=diagnostics,
            critic=critic,
            metadata=metadata,
        )
        critic = self._merge_parallel_admin_assist_into_critic(critic=critic, parallel_admin_assist=parallel_admin_assist)
        checkpoint_payload.update(
            {
                "stage": "archive_warmup",
                "critic": critic,
                "parallel_admin_assist": parallel_admin_assist,
            }
        )
        self._write_cycle_checkpoint(cycle_index=cycle_index, payload=checkpoint_payload)
        archive_warmup = await self._archive_candidate_urls(scrape_result, diagnostics, critic=critic)
        checkpoint_payload.update(
            {
                "stage": "document_gap_report",
                "archive_warmup": archive_warmup,
            }
        )
        self._write_cycle_checkpoint(cycle_index=cycle_index, payload=checkpoint_payload)
        document_gap_report = self._build_document_gap_report(diagnostics=diagnostics, metadata=metadata)
        document_gap_report_path = self._write_document_gap_report(cycle_index=cycle_index, report=document_gap_report)
        checkpoint_payload.update(
            {
                "stage": "document_gap_report",
                "document_gap_report": document_gap_report,
                "document_gap_report_path": str(document_gap_report_path) if document_gap_report_path else None,
            }
        )
        self._write_cycle_checkpoint(cycle_index=cycle_index, payload=checkpoint_payload)
        document_artifacts = await self._capture_document_artifacts(
            cycle_index=cycle_index,
            tactic=tactic,
            document_gap_report=document_gap_report,
        )
        document_artifact_blocks = self._state_admin_blocks_from_document_artifacts(document_artifacts)
        if document_artifact_blocks:
            scrape_result = dict(scrape_result)
            scrape_result["data"] = self._merge_recovered_data_blocks(
                list(scrape_result.get("data") or []),
                document_artifact_blocks,
            )
            recovered_row_artifacts = self._write_recovered_row_artifacts(
                cycle_index=cycle_index,
                scrape_result=scrape_result,
            )
            diagnostics = self._build_diagnostics(scrape_result)
        diagnostics = self._merge_document_artifacts_into_diagnostics(
            diagnostics=diagnostics,
            document_artifacts=document_artifacts,
        )
        if isinstance(recovered_row_artifacts, dict) and isinstance(diagnostics.get("documents"), dict):
            diagnostics["documents"] = dict(diagnostics["documents"])
            diagnostics["documents"]["recovered_row_artifacts"] = recovered_row_artifacts
        diagnostics = self._annotate_document_recovery_gate(diagnostics)
        critic_score = self._critic_score(diagnostics)
        passed = self._is_success(diagnostics, score=critic_score)
        critic = self._criticize_cycle(diagnostics)
        critic = self._merge_router_assist_into_critic(critic=critic, router_assist=router_assist)
        critic = self._merge_parallel_admin_assist_into_critic(critic=critic, parallel_admin_assist=parallel_admin_assist)
        checkpoint_payload.update(
            {
                "stage": "post_cycle_release",
                "diagnostics": diagnostics,
                "critic_score": critic_score,
                "passed": passed,
                "critic": critic,
                "document_artifacts": document_artifacts,
                "recovered_row_artifacts": recovered_row_artifacts,
            }
        )
        self._write_cycle_checkpoint(cycle_index=cycle_index, payload=checkpoint_payload)
        post_cycle_release = await self._maybe_run_post_cycle_release(
            cycle_index=cycle_index,
            critic_score=critic_score,
            passed=passed,
        )
        checkpoint_payload.update(
            {
                "stage": "finalize",
                "post_cycle_release": post_cycle_release,
            }
        )
        self._write_cycle_checkpoint(cycle_index=cycle_index, payload=checkpoint_payload)

        cycle_payload = {
            "cycle": cycle_index,
            "timestamp": datetime.now().isoformat(),
            "corpus": self.corpus.key,
            "states": list(self.states),
            "cycle_state_order": cycle_states,
            "status": str(scrape_result.get("status") or "unknown"),
            "tactic": self._effective_tactic_payload(tactic),
            "tactic_selection": tactic_selection["details"],
            "critic_score": critic_score,
            "passed": passed,
            "diagnostics": diagnostics,
            "critic": critic,
            "router_assist": router_assist,
            "parallel_admin_assist": parallel_admin_assist,
            "archive_warmup": archive_warmup,
            "document_gap_report": document_gap_report,
            "document_gap_report_path": str(document_gap_report_path) if document_gap_report_path else None,
            "document_artifacts": document_artifacts,
            "recovered_row_artifacts": recovered_row_artifacts,
            "post_cycle_release": post_cycle_release,
            "metadata": metadata,
        }

        self._update_state(tactic=tactic, cycle_payload=cycle_payload)
        cycle_path = self.cycles_dir / f"cycle_{cycle_index:04d}.json"
        cycle_path.write_text(json.dumps(cycle_payload, indent=2), encoding="utf-8")
        self.latest_file.write_text(json.dumps(cycle_payload, indent=2), encoding="utf-8")
        self._clear_cycle_checkpoint(cycle_index=cycle_index)
        return cycle_payload

    def _annotate_document_recovery_gate(self, diagnostics: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(diagnostics, dict):
            return diagnostics

        documents = diagnostics.get("documents") or {}
        if not isinstance(documents, dict):
            return diagnostics

        candidate_document_urls = int(documents.get("candidate_document_urls", 0) or 0)
        processed_document_urls = int(documents.get("processed_document_urls", 0) or 0)
        ratio = (
            float(processed_document_urls) / float(max(1, candidate_document_urls))
            if candidate_document_urls > 0
            else 1.0
        )
        required_ratio = max(0.0, min(1.0, float(self.config.min_document_recovery_ratio or 0.0)))

        documents = dict(documents)
        documents["document_recovery_ratio"] = round(ratio, 3)
        documents["required_document_recovery_ratio"] = round(required_ratio, 3)
        documents["document_recovery_ratio_ok"] = bool(ratio >= required_ratio)
        diagnostics["documents"] = documents
        return diagnostics

    def _build_deferred_retry_plan(self, scrape_result: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        metadata = scrape_result.get("metadata") or {}
        candidate_metadata = self._rate_limit_metadata_candidates(scrape_result)
        scrape_status = str(scrape_result.get("status") or "").strip().lower()
        cloudflare_status = ""
        rate_limit_source: Dict[str, Any] = metadata
        for candidate in candidate_metadata:
            candidate_cloudflare_status = str(candidate.get("cloudflare_status") or "").strip().lower()
            if candidate_cloudflare_status == "rate_limited":
                cloudflare_status = candidate_cloudflare_status
                rate_limit_source = candidate
                break
        if scrape_status != "rate_limited" and cloudflare_status != "rate_limited":
            return None

        retry_after_seconds = self._coerce_optional_float(
            rate_limit_source.get("retry_after_seconds", scrape_result.get("retry_after_seconds"))
        )
        retry_at_utc = self._normalize_retry_at_utc(
            rate_limit_source.get("retry_at_utc", scrape_result.get("retry_at_utc"))
        )
        if retry_after_seconds is None and retry_at_utc:
            retry_after_seconds = self._seconds_until_utc(retry_at_utc)

        provider = "cloudflare_browser_rendering" if cloudflare_status == "rate_limited" else "unknown"
        rate_limit_diagnostics = dict(
            rate_limit_source.get("rate_limit_diagnostics") or scrape_result.get("rate_limit_diagnostics") or {}
        )
        return {
            "status": "scheduled",
            "reason": f"{provider}_rate_limited",
            "provider": provider,
            "retryable": bool(rate_limit_source.get("retryable", scrape_result.get("retryable", True))),
            "retry_after_seconds": retry_after_seconds,
            "retry_at_utc": retry_at_utc,
            "wait_budget_exhausted": bool(
                rate_limit_source.get("wait_budget_exhausted", scrape_result.get("wait_budget_exhausted", False))
            ),
            "source_status": scrape_status or cloudflare_status or "rate_limited",
            "rate_limit_diagnostics": rate_limit_diagnostics,
        }

    @staticmethod
    def _coalesce_router_llm_env(*names: str) -> str:
        for name in names:
            value = os.environ.get(name)
            if value is not None and str(value).strip():
                return str(value).strip()
        return ""

    @staticmethod
    def _truthy_env(name: str) -> Optional[bool]:
        value = os.environ.get(name)
        if value is None or not str(value).strip():
            return None
        return str(value).strip().lower() in {"1", "true", "yes", "on"}

    def _router_llm_kwargs(self, *, tactic: ScraperTacticProfile, timeout_seconds: float) -> Dict[str, Any]:
        provider_override = self._coalesce_router_llm_env(
            "LEGAL_DAEMON_ROUTER_LLM_PROVIDER",
            "IPFS_DATASETS_PY_ROUTER_REVIEW_LLM_PROVIDER",
        )
        model_override = self._coalesce_router_llm_env(
            "LEGAL_DAEMON_ROUTER_LLM_MODEL",
            "IPFS_DATASETS_PY_ROUTER_REVIEW_LLM_MODEL",
        )
        hf_provider_override = self._coalesce_router_llm_env(
            "LEGAL_DAEMON_ROUTER_LLM_HF_PROVIDER",
            "IPFS_DATASETS_PY_ROUTER_REVIEW_HF_PROVIDER",
        )
        hf_bill_to_override = self._coalesce_router_llm_env(
            "LEGAL_DAEMON_ROUTER_LLM_HF_BILL_TO",
            "IPFS_DATASETS_PY_ROUTER_REVIEW_HF_BILL_TO",
        )
        hf_use_chat_env = self._truthy_env("LEGAL_DAEMON_ROUTER_LLM_HF_USE_CHAT_COMPLETIONS")
        if hf_use_chat_env is None:
            hf_use_chat_env = self._truthy_env("IPFS_DATASETS_PY_ROUTER_REVIEW_HF_USE_CHAT_COMPLETIONS")

        selected_provider = provider_override or tactic.llm_provider
        kwargs: Dict[str, Any] = {
            "provider": selected_provider,
            "temperature": 0.2,
            "max_tokens": 350,
            "allow_local_fallback": timeout_seconds <= 0.0,
        }
        if model_override:
            kwargs["model_name"] = model_override
        if hf_provider_override:
            kwargs["hf_provider"] = hf_provider_override
        if hf_bill_to_override:
            kwargs["hf_bill_to"] = hf_bill_to_override
        if hf_use_chat_env is not None:
            kwargs["hf_use_chat_completions"] = hf_use_chat_env

        if kwargs.get("provider") == "hf_inference_api":
            if hf_use_chat_env is None and model_override and ":" in model_override:
                kwargs["hf_use_chat_completions"] = True

        return kwargs

    @staticmethod
    def _rate_limit_metadata_candidates(scrape_result: Dict[str, Any]) -> List[Dict[str, Any]]:
        metadata = scrape_result.get("metadata") or {}
        base_metadata = metadata.get("base_metadata") if isinstance(metadata, dict) else None
        candidates: List[Dict[str, Any]] = []
        if isinstance(metadata, dict):
            candidates.append(metadata)
        if isinstance(base_metadata, dict):
            candidates.append(base_metadata)
        return candidates

    def _build_deferred_retry_cycle_payload(
        self,
        *,
        cycle_index: int,
        tactic: ScraperTacticProfile,
        scrape_result: Dict[str, Any],
        metadata: Dict[str, Any],
        deferred_retry: Dict[str, Any],
    ) -> Dict[str, Any]:
        provider = str(deferred_retry.get("provider") or "unknown")
        diagnostics = {
            "rate_limit": dict(deferred_retry),
            "coverage": {
                "states_targeted": len(self.states),
                "states_returned": 0,
                "states_with_nonzero_statutes": 0,
                "coverage_gap_states": list(self.states),
            },
            "fetch": {
                "attempted": 0,
                "success": 0,
                "success_ratio": 0.0,
                "fallback_count": 0,
                "providers": {provider: 0} if provider != "unknown" else {},
                "no_attempt_states": list(self.states),
                "weak_states": [],
            },
            "etl_readiness": {
                "ready_for_kg_etl": False,
                "full_text_ratio": 0.0,
                "jsonld_ratio": 0.0,
                "jsonld_legislation_ratio": 0.0,
                "kg_payload_ratio": 0.0,
                "citation_ratio": 0.0,
                "statute_signal_ratio": 0.0,
                "non_scaffold_ratio": 0.0,
            },
            "quality": {
                "weak_states": [],
            },
            "documents": {
                "candidate_document_urls": 0,
                "processed_document_urls": 0,
                "states_with_candidate_document_gaps": [],
            },
        }
        critic = {
            "issues": [f"rate-limited-deferred-retry:{provider}"],
            "provider_summary": {provider: 0} if provider != "unknown" else {},
            "recommended_next_tactics": [tactic.name] if tactic.name in self.config.tactic_profiles else [],
            "priority_states": [],
            "state_action_plan": {},
            "query_hints": [],
            "summary": "Provider-directed cooldown detected; defer the next cycle until the advertised retry window instead of grading this scrape as a tactic failure.",
        }
        skipped = {"status": "skipped", "reason": "deferred-retry-scheduled"}
        return {
            "cycle": cycle_index,
            "timestamp": datetime.now().isoformat(),
            "corpus": self.corpus.key,
            "states": list(self.states),
            "status": str(scrape_result.get("status") or "unknown"),
            "tactic": self._effective_tactic_payload(tactic),
            "critic_score": 0.0,
            "passed": False,
            "diagnostics": diagnostics,
            "critic": critic,
            "router_assist": dict(skipped),
            "parallel_admin_assist": dict(skipped),
            "archive_warmup": dict(skipped),
            "document_gap_report": dict(skipped),
            "document_gap_report_path": None,
            "document_artifacts": dict(skipped),
            "post_cycle_release": dict(skipped),
            "metadata": metadata,
            "deferred_retry": deferred_retry,
        }

    @staticmethod
    def _safe_artifact_stem(value: Any, *, fallback: str) -> str:
        stem = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "").strip()).strip("._")
        return stem[:80] if stem else fallback

    @staticmethod
    def _content_type_extension(content_type: str) -> str:
        lowered = str(content_type or "").strip().lower()
        if "pdf" in lowered:
            return ".pdf"
        if "rtf" in lowered:
            return ".rtf"
        if "html" in lowered:
            return ".html"
        if "markdown" in lowered or "text/plain" in lowered:
            return ".txt"
        return ".bin"

    def _document_artifact_targets(self, document_gap_report: Dict[str, Any]) -> List[Dict[str, Any]]:
        states = document_gap_report.get("states") or {}
        if not isinstance(states, dict):
            return []

        state_order = [
            str(item).upper().strip()
            for item in list(document_gap_report.get("weak_states") or [])
            + list(document_gap_report.get("states_with_candidate_document_gaps") or [])
            + list(document_gap_report.get("states_with_artifact_candidates") or [])
            if str(item).strip()
        ]
        ordered_states = list(dict.fromkeys(state_order))[: max(1, int(self.config.document_artifact_state_limit or 1))]
        targets: List[Dict[str, Any]] = []
        max_total = max(1, int(self.config.document_artifact_max_total or 1))
        per_state_limit = max(1, int(self.config.document_artifact_urls_per_state or 1))
        per_state_attempt_limit = max(per_state_limit, per_state_limit * 4)
        total_attempt_limit = max(max_total, max_total * 4)

        for state_code in ordered_states:
            entry = states.get(state_code) or {}
            urls = [
                str(value).strip()
                for value in list(entry.get("top_candidate_document_urls") or [])
                if str(value).strip()
            ]
            if not urls:
                urls = [
                    str(value).strip()
                    for value in list(entry.get("top_candidate_urls") or [])
                    if str(value).strip()
                ]
            domains_seen = {
                str(value).strip().lower()
                for value in list(entry.get("domains_seen") or [])
                if str(value).strip()
            }
            deprioritized_hosts = {
                str(value).strip().lower()
                for value in list(entry.get("candidate_hosts_without_rules") or [])
                if str(value).strip()
            }
            if urls and (domains_seen or deprioritized_hosts):
                ranked_urls: List[str] = []
                for _, url in sorted(
                    enumerate(urls),
                    key=lambda item: (
                        0 if urlparse(item[1]).netloc.strip().lower() in domains_seen else 1,
                        1 if urlparse(item[1]).netloc.strip().lower() in deprioritized_hosts and urlparse(item[1]).netloc.strip().lower() not in domains_seen else 0,
                        item[0],
                    ),
                ):
                    ranked_urls.append(url)
                urls = ranked_urls
            urls = urls[:per_state_attempt_limit]
            directives = entry.get("recovery_directives") or {}
            for url in urls:
                if len(targets) >= total_attempt_limit:
                    return targets
                targets.append(
                    {
                        "state": state_code,
                        "url": url,
                        "directives": dict(directives) if isinstance(directives, dict) else {},
                    }
                )
        return targets

    def _preferred_methods_for_document_target(
        self,
        *,
        base_methods: Sequence[Any],
        directives: Dict[str, Any],
    ) -> List[Any]:
        ordered: List[Any] = []
        seen: set[Any] = set()

        def _append(method: Any) -> None:
            if method is None or method in seen:
                return
            seen.add(method)
            ordered.append(method)

        try:
            from ..web_archiving.unified_web_scraper import ScraperMethod
        except Exception:
            return list(base_methods)

        directive_map = {
            "playwright_download": [ScraperMethod.PLAYWRIGHT],
            "page_fetch": [ScraperMethod.REQUESTS_ONLY, ScraperMethod.BEAUTIFULSOUP],
            "direct_fetch": [ScraperMethod.REQUESTS_ONLY, ScraperMethod.BEAUTIFULSOUP],
            "cloudflare_browser_rendering": [ScraperMethod.CLOUDFLARE_BROWSER_RENDERING, ScraperMethod.PLAYWRIGHT],
            "archival_replay": [
                ScraperMethod.COMMON_CRAWL,
                ScraperMethod.WAYBACK_MACHINE,
                ScraperMethod.ARCHIVE_IS,
            ],
        }
        for name in list((directives or {}).get("download_methods") or []):
            for method in directive_map.get(str(name).strip(), []):
                _append(method)

        for method in list(base_methods or []):
            _append(method)
        return ordered

    async def _extract_document_text_from_raw_bytes(
        self,
        *,
        url: str,
        raw_bytes: bytes,
        content_type: str,
    ) -> Dict[str, Any]:
        lowered_url = str(url or "").strip().lower()
        normalized_content_type = str(content_type or "").strip().lower()
        if not raw_bytes:
            return {"text": "", "method": None}

        try:
            from ..web_archiving.unified_web_scraper import UnifiedWebScraper
        except Exception as exc:
            return {"text": "", "method": None, "error": str(exc)}

        if (
            lowered_url.endswith(".pdf")
            or ".pdf?" in lowered_url
            or "application/pdf" in normalized_content_type
        ):
            try:
                text = str(await UnifiedWebScraper._extract_pdf_text(raw_bytes) or "").strip()
            except Exception as exc:
                return {"text": "", "method": "pdf_processor", "error": str(exc)}
            return {"text": text, "method": "pdf_processor"}

        if (
            lowered_url.endswith(".rtf")
            or ".rtf?" in lowered_url
            or "application/rtf" in normalized_content_type
            or "text/rtf" in normalized_content_type
        ):
            try:
                text = str(await UnifiedWebScraper._extract_rtf_text(raw_bytes) or "").strip()
            except Exception as exc:
                return {"text": "", "method": "rtf_processor", "error": str(exc)}
            return {"text": text, "method": "rtf_processor"}

        return {"text": "", "method": None}

    async def _capture_document_artifacts(
        self,
        *,
        cycle_index: int,
        tactic: ScraperTacticProfile,
        document_gap_report: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        if self.corpus.key != "state_admin_rules":
            return {"status": "skipped", "reason": "corpus-not-state-admin-rules"}
        if not bool(self.config.document_artifact_capture_enabled):
            return {"status": "skipped", "reason": "document-artifact-capture-disabled"}
        if not isinstance(document_gap_report, dict) or not document_gap_report.get("states"):
            return {"status": "skipped", "reason": "no-document-gap-report"}

        targets = self._document_artifact_targets(document_gap_report)
        if not targets:
            return {"status": "skipped", "reason": "no-document-artifact-targets"}

        try:
            from ..web_archiving.unified_web_scraper import ScraperConfig, ScraperMethod, UnifiedWebScraper
        except Exception as exc:
            return {"status": "error", "reason": f"unified-web-scraper-unavailable:{exc}"}

        method_map = {method.value: method for method in ScraperMethod}
        preferred_methods = [
            method_map[name]
            for name in self._effective_scraper_method_order(tactic)
            if name in method_map
        ]
        if not preferred_methods:
            preferred_methods = [ScraperMethod.PLAYWRIGHT, ScraperMethod.REQUESTS_ONLY]

        config = ScraperConfig(
            timeout=max(30, int(self.config.per_state_timeout_seconds or 30)),
            preferred_methods=preferred_methods,
            fallback_enabled=True,
            archive_is_submit_on_miss=bool(tactic.archive_is_submit_on_miss),
            rate_limit_delay=max(0.0, float(tactic.rate_limit_delay or 0.0)),
        )
        cycle_dir = self.document_artifacts_dir / f"cycle_{cycle_index:04d}"
        cycle_dir.mkdir(parents=True, exist_ok=True)
        manifest_entries: List[Dict[str, Any]] = []
        max_success_total = max(1, int(self.config.document_artifact_max_total or 1))
        per_state_success_limit = max(1, int(self.config.document_artifact_urls_per_state or 1))
        successful_by_state: Dict[str, int] = {}

        for index, target in enumerate(targets, start=1):
            state_code = str(target.get("state") or "").upper().strip() or "UNK"
            if int(successful_by_state.get(state_code, 0) or 0) >= per_state_success_limit:
                continue
            if sum(1 for entry in manifest_entries if bool(entry.get("success"))) >= max_success_total:
                break
            url = str(target.get("url") or "").strip()
            if not url:
                continue
            directives = dict(target.get("directives") or {})
            target_methods = self._preferred_methods_for_document_target(
                base_methods=preferred_methods,
                directives=directives,
            )
            target_config = ScraperConfig(
                timeout=config.timeout,
                preferred_methods=target_methods,
                fallback_enabled=config.fallback_enabled,
                archive_is_submit_on_miss=config.archive_is_submit_on_miss,
                rate_limit_delay=config.rate_limit_delay,
            )
            scraper = UnifiedWebScraper(target_config)
            result = await scraper.scrape(url)
            metadata = dict(getattr(result, "metadata", {}) or {})
            raw_bytes = metadata.pop("raw_bytes", None)
            method_used = getattr(getattr(result, "method_used", None), "value", None) or str(metadata.get("method") or "")
            suggested_name = Path(urlparse(url).path).name or f"artifact_{index}"
            base_name = self._safe_artifact_stem(f"{state_code}_{index:02d}_{Path(suggested_name).stem}", fallback=f"{state_code}_{index:02d}")
            saved_files: List[str] = []
            sha256 = None
            content_type = str(metadata.get("content_type") or "").strip()
            document_processor_method = None
            document_processor_error = None

            if isinstance(raw_bytes, (bytes, bytearray)) and raw_bytes:
                extension = Path(suggested_name).suffix or self._content_type_extension(content_type)
                binary_path = cycle_dir / f"{base_name}{extension}"
                binary_path.write_bytes(bytes(raw_bytes))
                saved_files.append(str(binary_path))
                sha256 = hashlib.sha256(bytes(raw_bytes)).hexdigest()

            extracted_text = str(getattr(result, "text", "") or "").strip()
            if isinstance(raw_bytes, (bytes, bytearray)) and raw_bytes:
                processed_document = await self._extract_document_text_from_raw_bytes(
                    url=url,
                    raw_bytes=bytes(raw_bytes),
                    content_type=content_type,
                )
                recovered_text = str(processed_document.get("text") or "").strip()
                document_processor_method = processed_document.get("method")
                document_processor_error = processed_document.get("error")
                if recovered_text and len(recovered_text) > len(extracted_text):
                    extracted_text = recovered_text
            if extracted_text:
                text_path = cycle_dir / f"{base_name}.txt"
                text_path.write_text(extracted_text, encoding="utf-8")
                saved_files.append(str(text_path))

            html_text = str(getattr(result, "html", "") or "").strip()
            if html_text and not isinstance(raw_bytes, (bytes, bytearray)):
                html_path = cycle_dir / f"{base_name}.html"
                html_path.write_text(html_text, encoding="utf-8")
                saved_files.append(str(html_path))

            manifest_entries.append(
                {
                    "state": state_code,
                    "url": url,
                    "success": bool(getattr(result, "success", False)),
                    "method_used": method_used or None,
                    "content_type": content_type or None,
                    "content_length": int(metadata.get("content_length", 0) or 0),
                    "binary_document": bool(metadata.get("binary_document", False)),
                    "sha256": sha256,
                    "saved_files": saved_files,
                    "preferred_methods": [method.value for method in target_methods],
                    "title": str(getattr(result, "title", "") or "").strip() or None,
                    "error_count": len(list(getattr(result, "errors", []) or [])),
                    "errors": [str(item) for item in list(getattr(result, "errors", []) or []) if str(item).strip()][:4],
                    "document_processor_method": document_processor_method,
                    "document_processor_error": document_processor_error,
                    "metadata": {
                        key: value
                        for key, value in metadata.items()
                        if not isinstance(value, (bytes, bytearray))
                    },
                    "recovery_directives": directives,
                }
            )
            if bool(getattr(result, "success", False)):
                successful_by_state[state_code] = int(successful_by_state.get(state_code, 0) or 0) + 1

        successful_count = sum(1 for entry in manifest_entries if bool(entry.get("success")))
        manifest = {
            "cycle": int(cycle_index),
            "generated_at": datetime.now().isoformat(),
            "corpus": self.corpus.key,
            "preferred_methods": [method.value for method in preferred_methods],
            "target_count": len(manifest_entries),
            "successful_count": successful_count,
            "entries": manifest_entries,
            "artifact_dir": str(cycle_dir),
        }
        manifest_path = self.cycles_dir / f"cycle_{cycle_index:04d}_document_artifacts.json"
        latest_path = self.output_dir / "latest_document_artifacts.json"
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        latest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return {
            "status": "completed",
            "artifact_dir": str(cycle_dir),
            "artifact_path": str(manifest_path),
            "target_count": len(manifest_entries),
            "successful_count": int(successful_count or 0),
            "entries": manifest_entries,
        }

    def _document_artifact_summary(self, document_artifacts: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(document_artifacts, dict) or str(document_artifacts.get("status") or "") != "completed":
            return {
                "successful_document_urls": 0,
                "recovered_states": [],
                "by_state": {},
                "by_format": {"pdf": 0, "rtf": 0, "html": 0},
                "by_processor": {},
            }

        seen_document_urls: set[str] = set()
        recovered_states: set[str] = set()
        by_state: Dict[str, Dict[str, int]] = {}
        by_format: Dict[str, int] = {"pdf": 0, "rtf": 0, "html": 0}
        by_processor: Dict[str, int] = {}

        for entry in list(document_artifacts.get("entries") or []):
            if not isinstance(entry, dict) or not bool(entry.get("success")):
                continue
            state_code = str(entry.get("state") or "").upper().strip()
            url = str(entry.get("url") or "").strip()
            doc_format = self._document_format_from_url(url)
            if doc_format not in {"pdf", "rtf", "html"}:
                doc_format = "html"
            if url and doc_format in {"pdf", "rtf"}:
                seen_document_urls.add(url)
                if state_code:
                    recovered_states.add(state_code)
            by_format[doc_format] = int(by_format.get(doc_format, 0) or 0) + 1
            if state_code:
                state_counts = by_state.setdefault(state_code, {"pdf": 0, "rtf": 0, "html": 0, "successful": 0})
                state_counts[doc_format] = int(state_counts.get(doc_format, 0) or 0) + 1
                state_counts["successful"] = int(state_counts.get("successful", 0) or 0) + 1
            processor_method = str(entry.get("document_processor_method") or "").strip()
            if processor_method:
                by_processor[processor_method] = int(by_processor.get(processor_method, 0) or 0) + 1

        return {
            "successful_document_urls": len(seen_document_urls),
            "recovered_states": sorted(recovered_states),
            "by_state": by_state,
            "by_format": by_format,
            "by_processor": by_processor,
        }

    def _merge_document_artifacts_into_diagnostics(
        self,
        *,
        diagnostics: Dict[str, Any],
        document_artifacts: Dict[str, Any],
    ) -> Dict[str, Any]:
        if not isinstance(diagnostics, dict):
            return diagnostics
        documents = diagnostics.get("documents") or {}
        if not isinstance(documents, dict):
            return diagnostics

        artifact_summary = self._document_artifact_summary(document_artifacts)
        if int(artifact_summary.get("successful_document_urls", 0) or 0) <= 0:
            documents = dict(documents)
            documents["artifact_recovery"] = artifact_summary
            diagnostics["documents"] = documents
            return diagnostics

        updated_documents = dict(documents)
        per_state = {
            str(state).upper(): dict(counts or {})
            for state, counts in dict(updated_documents.get("per_state") or {}).items()
            if str(state).strip()
        }
        states_with_document_rules = {
            str(item).upper().strip()
            for item in list(updated_documents.get("states_with_document_rules") or [])
            if str(item).strip()
        }
        gap_states = {
            str(item).upper().strip()
            for item in list(updated_documents.get("states_with_candidate_document_gaps") or [])
            if str(item).strip()
        }
        per_state_recovery = {
            str(state).upper(): dict(payload or {})
            for state, payload in dict(updated_documents.get("per_state_recovery") or {}).items()
            if str(state).strip()
        }

        by_state = artifact_summary.get("by_state") or {}
        for state_code, counts in by_state.items():
            normalized_state = str(state_code).upper().strip()
            if not normalized_state:
                continue
            state_counts = dict(per_state.get(normalized_state) or {"html": 0, "pdf": 0, "rtf": 0})
            for name in ("html", "pdf", "rtf"):
                state_counts[name] = int(state_counts.get(name, 0) or 0) + int(counts.get(name, 0) or 0)
            per_state[normalized_state] = state_counts
            if int(state_counts.get("pdf", 0) or 0) + int(state_counts.get("rtf", 0) or 0) > 0:
                states_with_document_rules.add(normalized_state)
                gap_states.discard(normalized_state)

            recovery_entry = dict(per_state_recovery.get(normalized_state) or {})
            recovery_entry["artifact_recovery_successes"] = int(
                recovery_entry.get("artifact_recovery_successes", 0) or 0
            ) + int(counts.get("successful", 0) or 0)
            artifact_formats = {
                "pdf": int(counts.get("pdf", 0) or 0),
                "rtf": int(counts.get("rtf", 0) or 0),
                "html": int(counts.get("html", 0) or 0),
            }
            recovery_entry["artifact_recovery_formats"] = artifact_formats
            per_state_recovery[normalized_state] = recovery_entry

        updated_documents["per_state"] = per_state
        updated_documents["per_state_recovery"] = per_state_recovery
        updated_documents["processed_document_urls"] = int(updated_documents.get("processed_document_urls", 0) or 0) + int(
            artifact_summary.get("successful_document_urls", 0) or 0
        )
        updated_documents["states_with_document_rules"] = sorted(states_with_document_rules)
        updated_documents["states_with_candidate_document_gaps"] = sorted(gap_states)
        updated_documents["artifact_recovery"] = artifact_summary
        diagnostics["documents"] = updated_documents
        return diagnostics

    def _state_admin_blocks_from_document_artifacts(self, document_artifacts: Dict[str, Any]) -> List[Dict[str, Any]]:
        if self.corpus.key != "state_admin_rules":
            return []
        if not isinstance(document_artifacts, dict) or str(document_artifacts.get("status") or "") != "completed":
            return []

        by_state: Dict[str, List[Dict[str, Any]]] = {}
        counters: Dict[str, int] = {}
        for entry in list(document_artifacts.get("entries") or []):
            if not isinstance(entry, dict) or not bool(entry.get("success")):
                continue
            state_code = str(entry.get("state") or "").upper().strip()
            url = str(entry.get("url") or "").strip()
            if not state_code or not url:
                continue
            text = self._document_artifact_text(entry)
            if len(text) < 200:
                continue

            counters[state_code] = int(counters.get(state_code, 0) or 0) + 1
            section_number = f"A{counters[state_code]}"
            title = str(entry.get("title") or "").strip() or self._title_from_text(text)
            state_name = US_STATES.get(state_code, state_code)
            method_used = str(entry.get("document_processor_method") or entry.get("method_used") or "").strip()
            statute = {
                "state_code": state_code,
                "state_name": state_name,
                "statute_id": f"{state_code}-DOCUMENT-ARTIFACT-{counters[state_code]:04d}",
                "code_name": f"{state_name} Administrative Rules (Document Artifact Recovery)",
                "section_number": section_number,
                "section_name": title,
                "short_title": title,
                "full_text": text,
                "summary": text[:500],
                "legal_area": "administrative",
                "source_url": url,
                "official_cite": f"{state_code} Admin Rule {section_number}",
                "structured_data": {
                    "type": "regulation",
                    "agentic_discovery": True,
                    "document_artifact_recovery": True,
                    "method_used": method_used or None,
                    "content_type": entry.get("content_type"),
                    "sha256": entry.get("sha256"),
                },
            }
            by_state.setdefault(state_code, []).append(statute)

        blocks: List[Dict[str, Any]] = []
        for state_code, statutes in sorted(by_state.items()):
            state_name = US_STATES.get(state_code, state_code)
            blocks.append(
                {
                    "state_code": state_code,
                    "state_name": state_name,
                    "title": f"{state_name} Administrative Rules",
                    "source": "Document artifact recovery",
                    "source_url": statutes[0].get("source_url") if statutes else None,
                    "scraped_at": datetime.now(timezone.utc).isoformat(),
                    "statutes": statutes,
                    "rules_count": len(statutes),
                    "schema_version": "1.0",
                    "normalized": True,
                }
            )
        return blocks

    @staticmethod
    def _document_artifact_text(entry: Dict[str, Any]) -> str:
        for value in list(entry.get("saved_files") or []):
            path = Path(str(value or ""))
            if path.suffix.lower() != ".txt":
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace").strip()
            except Exception:
                continue
            if text:
                return text
        return ""

    @staticmethod
    def _title_from_text(text: str) -> str:
        for line in str(text or "").splitlines():
            candidate = line.strip()
            if candidate:
                return candidate[:180]
        return "Recovered Administrative Rule"

    @staticmethod
    def _merge_recovered_data_blocks(
        existing_blocks: Sequence[Dict[str, Any]],
        recovered_blocks: Sequence[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        merged: List[Dict[str, Any]] = []
        index_by_state: Dict[str, int] = {}
        for block in list(existing_blocks or []):
            if not isinstance(block, dict):
                continue
            copied = dict(block)
            statutes = copied.get("statutes")
            copied["statutes"] = list(statutes) if isinstance(statutes, list) else []
            state_code = str(copied.get("state_code") or copied.get("state") or "").upper().strip()
            if state_code and state_code not in index_by_state:
                index_by_state[state_code] = len(merged)
            merged.append(copied)

        for recovered in list(recovered_blocks or []):
            if not isinstance(recovered, dict):
                continue
            state_code = str(recovered.get("state_code") or recovered.get("state") or "").upper().strip()
            recovered_statutes = [
                dict(item)
                for item in list(recovered.get("statutes") or [])
                if isinstance(item, dict)
            ]
            if not state_code or not recovered_statutes:
                continue
            if state_code not in index_by_state:
                copied_recovered = dict(recovered)
                copied_recovered["statutes"] = recovered_statutes
                copied_recovered["rules_count"] = len(recovered_statutes)
                index_by_state[state_code] = len(merged)
                merged.append(copied_recovered)
                continue

            target = merged[index_by_state[state_code]]
            target_statutes = [
                item for item in list(target.get("statutes") or []) if isinstance(item, dict)
            ]
            seen_urls = {
                str(item.get("source_url") or item.get("url") or "").strip()
                for item in target_statutes
                if str(item.get("source_url") or item.get("url") or "").strip()
            }
            for statute in recovered_statutes:
                source_url = str(statute.get("source_url") or statute.get("url") or "").strip()
                if source_url and source_url in seen_urls:
                    continue
                target_statutes.append(statute)
                if source_url:
                    seen_urls.add(source_url)
            target["statutes"] = target_statutes
            target["rules_count"] = len(target_statutes)
        return merged

    def _write_cycle_checkpoint(self, *, cycle_index: int, payload: Dict[str, Any]) -> Optional[Path]:
        if not isinstance(payload, dict) or not payload:
            return None
        checkpoint_path = self.cycles_dir / f"cycle_{cycle_index:04d}.in_progress.json"
        latest_checkpoint_path = self.output_dir / "latest_in_progress.json"
        checkpoint_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        latest_checkpoint_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return checkpoint_path

    def _clear_cycle_checkpoint(self, *, cycle_index: int) -> None:
        checkpoint_path = self.cycles_dir / f"cycle_{cycle_index:04d}.in_progress.json"
        latest_checkpoint_path = self.output_dir / "latest_in_progress.json"
        for path in (checkpoint_path, latest_checkpoint_path):
            try:
                path.unlink(missing_ok=True)
            except Exception:
                pass

    def promote_latest_checkpoint_to_summary(self, *, reason: str) -> Optional[Path]:
        latest_checkpoint_path = self.output_dir / "latest_in_progress.json"
        if not latest_checkpoint_path.exists():
            return None

        try:
            payload = json.loads(latest_checkpoint_path.read_text(encoding="utf-8"))
        except Exception:
            return None

        if not isinstance(payload, dict) or not payload:
            return None

        payload = dict(payload)
        payload["checkpoint_promoted"] = True
        payload["checkpoint_promotion_reason"] = str(reason or "terminated")
        payload["checkpoint_promoted_at"] = datetime.now(timezone.utc).isoformat()

        cycle_index = int(payload.get("cycle", 0) or 0)
        cycle_path = self.cycles_dir / f"cycle_{cycle_index:04d}.recovered.json" if cycle_index > 0 else None
        try:
            self.latest_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            if cycle_path is not None:
                cycle_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception:
            return None
        return self.latest_file

    async def _run_scrape_with_tactic(
        self,
        tactic: ScraperTacticProfile,
        *,
        states: Optional[Sequence[str]] = None,
        cycle_index: Optional[int] = None,
        checkpoint_payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        cycle_states = self._normalize_cycle_states(states)
        kwargs: Dict[str, Any] = {
            "states": cycle_states,
            "output_format": "json",
            "include_metadata": True,
            "rate_limit_delay": max(0.0, float(tactic.rate_limit_delay)),
            "output_dir": None,
            "write_jsonld": True,
            "strict_full_text": bool(tactic.strict_full_text),
            "min_full_text_chars": max(0, int(tactic.min_full_text_chars or 0)),
            "parallel_workers": max(1, int(tactic.parallel_workers or 1)),
            "per_state_retry_attempts": max(0, int(tactic.per_state_retry_attempts or 0)),
            "per_state_timeout_seconds": max(0.0, float(self.config.per_state_timeout_seconds or 0.0)),
        }
        kwargs[self.corpus.hydrate_kwarg] = bool(tactic.hydrate_statute_text)
        kwargs[self.corpus.retry_zero_kwarg] = True
        if int(self.config.max_statutes or 0) > 0:
            kwargs[self.corpus.max_items_kwarg] = int(self.config.max_statutes)
        if self.corpus.key == "state_laws":
            kwargs["use_state_specific_scrapers"] = True
        elif self.corpus.key == "state_admin_rules":
            kwargs["rate_limit_delay"] = 0.2
            kwargs["strict_full_text"] = False
            kwargs["min_full_text_chars"] = 200
            kwargs["parallel_workers"] = 1
            kwargs["output_dir"] = str(self.output_dir)
            kwargs["agentic_checkpoint_interval"] = max(1, min(10, int(self.config.max_statutes or 10) or 10))
            admin_budget_kwargs = {
                "agentic_max_candidates_per_state": self.config.admin_agentic_max_candidates_per_state,
                "agentic_max_fetch_per_state": self.config.admin_agentic_max_fetch_per_state,
                "agentic_max_results_per_domain": self.config.admin_agentic_max_results_per_domain,
                "agentic_max_hops": self.config.admin_agentic_max_hops,
                "agentic_max_pages": self.config.admin_agentic_max_pages,
                "agentic_fetch_concurrency": self.config.admin_agentic_fetch_concurrency,
            }
            for key, value in admin_budget_kwargs.items():
                if value is None:
                    continue
                kwargs[key] = max(0, int(value)) if key != "agentic_fetch_concurrency" else max(1, int(value))

        with self._tactic_env(tactic):
            scrape_timeout_seconds = max(0.0, float(self.config.scrape_timeout_seconds or 0.0))
            heartbeat_seconds = max(0.0, float(self.config.scrape_heartbeat_seconds or 0.0))

            try:
                return await self._await_scrape_with_checkpoint_heartbeat(
                    lambda: self.corpus.scrape_func(**kwargs),
                    cycle_index=cycle_index,
                    checkpoint_payload=checkpoint_payload,
                    heartbeat_seconds=heartbeat_seconds,
                    scrape_timeout_seconds=scrape_timeout_seconds,
                )
            except asyncio.TimeoutError:
                timeout_metadata: Dict[str, Any] = {
                    "scrape_timeout_seconds": scrape_timeout_seconds,
                    "scrape_timed_out": True,
                }
                if self.corpus.key == "state_admin_rules":
                    timeout_metadata["cloudflare_browser_rendering"] = self._cloudflare_browser_rendering_availability()
                    salvaged_result = self._state_admin_scrape_result_from_agentic_checkpoints(
                        metadata=timeout_metadata,
                        error=f"Corpus scrape timed out after {scrape_timeout_seconds} seconds",
                    )
                    if salvaged_result is not None:
                        return salvaged_result
                return {
                    "status": "error",
                    "error": f"Corpus scrape timed out after {scrape_timeout_seconds} seconds",
                    "data": [],
                    "metadata": timeout_metadata,
                }

    async def _await_scrape_with_checkpoint_heartbeat(
        self,
        scrape_factory: Callable[[], Awaitable[Dict[str, Any]]],
        *,
        cycle_index: Optional[int],
        checkpoint_payload: Optional[Dict[str, Any]],
        heartbeat_seconds: float,
        scrape_timeout_seconds: float,
    ) -> Dict[str, Any]:
        heartbeat_task: Optional[asyncio.Task[None]] = None
        loop = asyncio.get_running_loop()
        result_future: asyncio.Future[Dict[str, Any]] = loop.create_future()

        def _publish_result(result: Dict[str, Any]) -> None:
            if not result_future.done():
                result_future.set_result(result)

        def _publish_exception(exc: BaseException) -> None:
            if not result_future.done():
                result_future.set_exception(exc)

        def _worker() -> None:
            try:
                result = asyncio.run(scrape_factory())
            except BaseException as exc:
                try:
                    loop.call_soon_threadsafe(_publish_exception, exc)
                except RuntimeError:
                    pass
                return
            try:
                loop.call_soon_threadsafe(_publish_result, result)
            except RuntimeError:
                pass

        worker = threading.Thread(
            target=_worker,
            name="agentic-daemon-scrape-worker",
            daemon=True,
        )
        worker.start()

        if (
            cycle_index is not None
            and checkpoint_payload is not None
            and heartbeat_seconds > 0
        ):
            started_at = asyncio.get_running_loop().time()

            async def _heartbeat_loop() -> None:
                heartbeat_count = 0
                while not result_future.done():
                    await asyncio.sleep(heartbeat_seconds)
                    if result_future.done():
                        break
                    heartbeat_count += 1
                    heartbeat_payload = dict(checkpoint_payload)
                    heartbeat_payload["timestamp"] = datetime.now().isoformat()
                    heartbeat_payload["stage"] = "scrape"
                    heartbeat_payload["scrape_heartbeat"] = {
                        "heartbeat_count": heartbeat_count,
                        "elapsed_seconds": round(asyncio.get_running_loop().time() - started_at, 3),
                    }
                    self._write_cycle_checkpoint(cycle_index=cycle_index, payload=heartbeat_payload)

            heartbeat_task = asyncio.create_task(_heartbeat_loop())

        try:
            if scrape_timeout_seconds > 0:
                return await asyncio.wait_for(asyncio.shield(result_future), timeout=scrape_timeout_seconds)
            return await result_future
        finally:
            if heartbeat_task is not None:
                heartbeat_task.cancel()
                with suppress(asyncio.CancelledError):
                    await heartbeat_task

    @staticmethod
    def _cloudflare_browser_rendering_availability() -> Dict[str, Any]:
        account_env_keys = [
            "IPFS_DATASETS_CLOUDFLARE_ACCOUNT_ID",
            "LEGAL_SCRAPER_CLOUDFLARE_ACCOUNT_ID",
            "CLOUDFLARE_ACCOUNT_ID",
            "CLOUDFLARE_AGENT_ACCOUNT_ID",
        ]
        token_env_keys = [
            "IPFS_DATASETS_CLOUDFLARE_API_TOKEN",
            "LEGAL_SCRAPER_CLOUDFLARE_API_TOKEN",
            "CLOUDFLARE_API_TOKEN",
            "CLOUDFLARE_AGENT_API_KEY",
        ]

        def _resolve_source(names: List[str], *, provider: str) -> Optional[str]:
            if provider == "env":
                return next((key for key in names if str(os.getenv(key) or "").strip()), None)
            if provider == "vault":
                try:
                    from ipfs_datasets_py.mcp_server.secrets_vault import get_secrets_vault

                    vault = get_secrets_vault()
                    return next((key for key in names if str(vault.get(key) or "").strip()), None)
                except Exception:
                    return None
            if provider == "keyring":
                try:
                    import keyring  # type: ignore

                    timeout_seconds = max(
                        0.1,
                        float(os.getenv("IPFS_DATASETS_KEYRING_LOOKUP_TIMEOUT_SECONDS", "1.5") or "1.5"),
                    )

                    class _KeyringLookupTimeout(TimeoutError):
                        pass

                    def _handle_timeout(_signum: int, _frame: Any) -> None:
                        raise _KeyringLookupTimeout()

                    for key in names:
                        if threading.current_thread() is not threading.main_thread():
                            return None
                        previous_handler = signal.getsignal(signal.SIGALRM)
                        try:
                            signal.signal(signal.SIGALRM, _handle_timeout)
                            signal.setitimer(signal.ITIMER_REAL, timeout_seconds)
                            value = str(keyring.get_password("ipfs_datasets_py", key) or "").strip()
                        except _KeyringLookupTimeout:
                            return None
                        finally:
                            signal.setitimer(signal.ITIMER_REAL, 0.0)
                            signal.signal(signal.SIGALRM, previous_handler)
                        if value:
                            return key
                    return None
                except Exception:
                    return None
            if provider == "shared_file":
                candidates = [
                    str(os.environ.get("IPFS_DATASETS_SECRETS_FILE") or "").strip(),
                    str(Path.home() / ".config" / "ipfs_datasets_py" / "secrets.json"),
                    "/etc/github-runner-secrets/secrets.json",
                    "/var/lib/github-runner/secrets.json",
                ]
                seen: set[str] = set()
                for candidate in candidates:
                    if not candidate or candidate in seen:
                        continue
                    seen.add(candidate)
                    try:
                        payload = json.loads(Path(candidate).expanduser().read_text(encoding="utf-8"))
                    except Exception:
                        continue
                    if not isinstance(payload, dict):
                        continue
                    for key in names:
                        if str(payload.get(key) or "").strip():
                            return key
                return None
            return None

        account_source = _resolve_source(account_env_keys, provider="env")
        account_source_kind = "env" if account_source else None
        if not account_source:
            account_source = _resolve_source(account_env_keys, provider="vault")
            account_source_kind = "vault" if account_source else None
        if not account_source:
            account_source = _resolve_source(account_env_keys, provider="shared_file")
            account_source_kind = "shared_file" if account_source else None
        if not account_source:
            account_source = _resolve_source(account_env_keys, provider="keyring")
            account_source_kind = "keyring" if account_source else None

        token_source = _resolve_source(token_env_keys, provider="env")
        token_source_kind = "env" if token_source else None
        if not token_source:
            token_source = _resolve_source(token_env_keys, provider="vault")
            token_source_kind = "vault" if token_source else None
        if not token_source:
            token_source = _resolve_source(token_env_keys, provider="shared_file")
            token_source_kind = "shared_file" if token_source else None
        if not token_source:
            token_source = _resolve_source(token_env_keys, provider="keyring")
            token_source_kind = "keyring" if token_source else None

        missing_credentials: List[str] = []
        if not account_source:
            missing_credentials.append("account_id")
        if not token_source:
            missing_credentials.append("api_token")

        configured = not missing_credentials
        return {
            "available": configured,
            "status": "configured" if configured else "missing_credentials",
            "provider": "cloudflare_browser_rendering",
            "account_id_env": account_source,
            "api_token_env": token_source,
            "account_id_source_kind": account_source_kind,
            "api_token_source_kind": token_source_kind,
            "missing_credentials": missing_credentials,
        }

    @staticmethod
    def _resolve_cloudflare_credential_values() -> Dict[str, Optional[str]]:
        account_names = [
            "IPFS_DATASETS_CLOUDFLARE_ACCOUNT_ID",
            "LEGAL_SCRAPER_CLOUDFLARE_ACCOUNT_ID",
            "CLOUDFLARE_ACCOUNT_ID",
            "CLOUDFLARE_AGENT_ACCOUNT_ID",
        ]
        token_names = [
            "IPFS_DATASETS_CLOUDFLARE_API_TOKEN",
            "LEGAL_SCRAPER_CLOUDFLARE_API_TOKEN",
            "CLOUDFLARE_API_TOKEN",
            "CLOUDFLARE_AGENT_API_KEY",
        ]

        def _resolve_value(names: List[str]) -> Optional[str]:
            for name in names:
                value = str(os.getenv(name) or "").strip()
                if value:
                    return value
            try:
                from ipfs_datasets_py.mcp_server.secrets_vault import get_secrets_vault

                vault = get_secrets_vault()
                for name in names:
                    value = str(vault.get(name) or "").strip()
                    if value:
                        return value
            except Exception:
                pass
            candidates = [
                str(os.environ.get("IPFS_DATASETS_SECRETS_FILE") or "").strip(),
                str(Path.home() / ".config" / "ipfs_datasets_py" / "secrets.json"),
                "/etc/github-runner-secrets/secrets.json",
                "/var/lib/github-runner/secrets.json",
            ]
            seen: set[str] = set()
            for candidate in candidates:
                if not candidate or candidate in seen:
                    continue
                seen.add(candidate)
                try:
                    payload = json.loads(Path(candidate).expanduser().read_text(encoding="utf-8"))
                except Exception:
                    continue
                if not isinstance(payload, dict):
                    continue
                for name in names:
                    value = str(payload.get(name) or "").strip()
                    if value:
                        return value
            try:
                import keyring  # type: ignore

                timeout_seconds = max(
                    0.1,
                    float(os.getenv("IPFS_DATASETS_KEYRING_LOOKUP_TIMEOUT_SECONDS", "1.5") or "1.5"),
                )

                class _KeyringLookupTimeout(TimeoutError):
                    pass

                def _handle_timeout(_signum: int, _frame: Any) -> None:
                    raise _KeyringLookupTimeout()

                for name in names:
                    if threading.current_thread() is not threading.main_thread():
                        return None
                    previous_handler = signal.getsignal(signal.SIGALRM)
                    try:
                        signal.signal(signal.SIGALRM, _handle_timeout)
                        signal.setitimer(signal.ITIMER_REAL, timeout_seconds)
                        value = str(keyring.get_password("ipfs_datasets_py", name) or "").strip()
                    except _KeyringLookupTimeout:
                        return None
                    finally:
                        signal.setitimer(signal.ITIMER_REAL, 0.0)
                        signal.signal(signal.SIGALRM, previous_handler)
                    if value:
                        return value
            except Exception:
                pass
            return None

        return {
            "account_id": _resolve_value(account_names),
            "api_token": _resolve_value(token_names),
        }

    def _build_diagnostics(self, scrape_result: Dict[str, Any]) -> Dict[str, Any]:
        metadata = scrape_result.get("metadata") or {}
        if self.corpus.key == "state_laws":
            return _build_operational_diagnostics(metadata, top_n=max(1, int(self.config.top_n_diagnostics or 1)))

        filtered_metadata = self._build_filtered_corpus_metadata(scrape_result)
        diagnostics = _build_operational_diagnostics(filtered_metadata, top_n=max(1, int(self.config.top_n_diagnostics or 1)))
        document_coverage = filtered_metadata.get("document_coverage")
        if isinstance(document_coverage, dict):
            diagnostics["documents"] = document_coverage
        corpus_gap_summary = filtered_metadata.get("corpus_gap_summary")
        if isinstance(corpus_gap_summary, dict):
            diagnostics["gap_analysis"] = corpus_gap_summary
        cloudflare_summary = filtered_metadata.get("cloudflare_browser_rendering")
        if isinstance(cloudflare_summary, dict):
            diagnostics["cloudflare"] = cloudflare_summary
        timing_summary = filtered_metadata.get("phase_timings")
        if isinstance(timing_summary, dict):
            diagnostics["timing"] = timing_summary
        return diagnostics

    def _build_filtered_corpus_metadata(self, scrape_result: Dict[str, Any]) -> Dict[str, Any]:
        metadata = scrape_result.get("metadata") or {}
        data = list(scrape_result.get("data") or [])
        base_metadata = metadata.get("base_metadata") or {}
        fetch_analytics_by_state = base_metadata.get("fetch_analytics_by_state") or metadata.get("fetch_analytics_by_state") or {}
        if isinstance(fetch_analytics_by_state, dict):
            fetch_analytics_by_state = _normalize_fetch_analytics_by_state(fetch_analytics_by_state)
        if self.corpus.key == "state_admin_rules" and isinstance(fetch_analytics_by_state, dict):
            fetch_analytics_by_state = _merge_admin_agentic_fetch_analytics(
                fetch_analytics_by_state,
                agentic_report=metadata.get("agentic_report") or {},
            )

        quality_by_state: Dict[str, Dict[str, Any]] = {}
        present_states: set[str] = set()
        nonzero_states: set[str] = set()
        zero_states: List[str] = []
        error_states: List[str] = []

        for block in data:
            if not isinstance(block, dict):
                continue
            state_code = str(block.get("state_code") or "").upper()
            if not state_code:
                continue
            present_states.add(state_code)
            statutes = [item for item in list(block.get("statutes") or []) if isinstance(item, dict)]
            quality_by_state[state_code] = _compute_state_quality_metrics(statutes)
            if statutes:
                nonzero_states.add(state_code)
            else:
                zero_states.append(state_code)
            if block.get("error"):
                error_states.append(state_code)

        missing_states = [code for code in self.states if code not in present_states]
        coverage_gap_states = sorted(set(zero_states + error_states + missing_states))
        coverage_summary = {
            "states_targeted": len(self.states),
            "states_returned": len(present_states),
            "states_with_nonzero_statutes": len(nonzero_states),
            "zero_statute_states": sorted(set(zero_states)),
            "error_states": sorted(set(error_states)),
            "missing_states": missing_states,
            "coverage_gap_states": coverage_gap_states,
            "full_coverage": len(coverage_gap_states) == 0,
        }

        filtered_metadata = {
            "coverage_summary": coverage_summary,
            "fetch_analytics": _aggregate_fetch_analytics(fetch_analytics_by_state if isinstance(fetch_analytics_by_state, dict) else {}),
            "fetch_analytics_by_state": fetch_analytics_by_state if isinstance(fetch_analytics_by_state, dict) else None,
            "etl_readiness": _compute_etl_readiness_summary(data),
            "quality_by_state": quality_by_state if quality_by_state else None,
        }
        timing_summary = self._build_phase_timing_summary(metadata)
        if timing_summary:
            filtered_metadata["phase_timings"] = timing_summary
        document_coverage = self._build_document_coverage(data=data, metadata=metadata)
        if document_coverage:
            filtered_metadata["document_coverage"] = document_coverage
        cloudflare_summary = metadata.get("cloudflare_browser_rendering")
        if isinstance(cloudflare_summary, dict):
            filtered_metadata["cloudflare_browser_rendering"] = dict(cloudflare_summary)
        else:
            derived_cloudflare_summary = {
                "cloudflare_status": metadata.get("cloudflare_status"),
                "cloudflare_http_status": metadata.get("cloudflare_http_status"),
                "cloudflare_browser_challenge_detected": metadata.get("cloudflare_browser_challenge_detected"),
                "cloudflare_error_excerpt": metadata.get("cloudflare_error_excerpt"),
                "cloudflare_record_status": metadata.get("cloudflare_record_status"),
                "cloudflare_job_status": metadata.get("cloudflare_job_status"),
                "browser_challenge_states": metadata.get("browser_challenge_states"),
                "rate_limited_states": metadata.get("rate_limited_states"),
            }
            derived_cloudflare_summary = {
                key: value for key, value in derived_cloudflare_summary.items() if value is not None
            }
            if derived_cloudflare_summary:
                filtered_metadata["cloudflare_browser_rendering"] = derived_cloudflare_summary
        corpus_gap_summary = self._build_corpus_gap_summary(data=data, metadata=metadata, document_coverage=document_coverage)
        if corpus_gap_summary:
            filtered_metadata["corpus_gap_summary"] = corpus_gap_summary
        return filtered_metadata

    @staticmethod
    def _build_phase_timing_summary(metadata: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        phase_timings = metadata.get("phase_timings")
        if not isinstance(phase_timings, dict):
            return None

        normalized: Dict[str, float] = {}
        for key, value in phase_timings.items():
            try:
                seconds = float(value)
            except (TypeError, ValueError):
                continue
            if seconds < 0.0:
                continue
            normalized[str(key)] = round(seconds, 4)

        if not normalized:
            return None

        total_seconds = float(normalized.get("total_seconds") or metadata.get("elapsed_time_seconds") or 0.0)
        phase_seconds = {key: value for key, value in normalized.items() if key != "total_seconds"}
        dominant_phase = None
        dominant_seconds = 0.0
        if phase_seconds:
            dominant_phase, dominant_seconds = max(phase_seconds.items(), key=lambda item: float(item[1] or 0.0))
        slow_phases = [
            key
            for key, value in phase_seconds.items()
            if total_seconds > 0.0 and float(value or 0.0) / float(total_seconds) >= 0.35
        ]
        return {
            "total_seconds": round(total_seconds, 4),
            "phase_seconds": phase_seconds,
            "dominant_phase": dominant_phase,
            "dominant_seconds": round(float(dominant_seconds or 0.0), 4),
            "slow_phases": slow_phases,
        }

    def _build_document_coverage(self, *, data: Sequence[Dict[str, Any]], metadata: Dict[str, Any]) -> Dict[str, Any]:
        per_state: Dict[str, Dict[str, int]] = {}
        total_by_format: Dict[str, int] = {"html": 0, "pdf": 0, "rtf": 0}
        candidate_document_urls = 0
        states_with_candidate_document_gaps: List[str] = []
        candidate_format_counts_by_state: Dict[str, Dict[str, int]] = {}
        candidate_urls_by_state: Dict[str, List[str]] = {}
        per_state_recovery: Dict[str, Dict[str, Any]] = {}

        agentic_report = metadata.get("agentic_report") or {}
        agentic_per_state = agentic_report.get("per_state") if isinstance(agentic_report, dict) else {}
        data_by_state = {
            str(block.get("state_code") or "").upper(): block
            for block in data
            if isinstance(block, dict) and str(block.get("state_code") or "").strip()
        }

        for state_code in list(self.states):
            state_counts = {"html": 0, "pdf": 0, "rtf": 0}
            processed_method_counts: Dict[str, int] = {}
            block = data_by_state.get(state_code)
            if isinstance(block, dict):
                for statute in list(block.get("statutes") or []):
                    if not isinstance(statute, dict):
                        continue
                    doc_format = self._document_format_from_url(statute.get("source_url") or statute.get("sourceUrl"))
                    state_counts[doc_format] = int(state_counts.get(doc_format, 0) or 0) + 1
                    method_name = self._document_method_from_row(statute)
                    if method_name:
                        processed_method_counts[method_name] = int(processed_method_counts.get(method_name, 0) or 0) + 1

            state_report = agentic_per_state.get(state_code) if isinstance(agentic_per_state, dict) else None
            if isinstance(state_report, dict):
                candidate_urls = [
                    str(value).strip()
                    for value in list(state_report.get("top_candidate_urls") or [])
                    if str(value).strip()
                ]
                candidate_urls_by_state[state_code] = candidate_urls
                report_format_counts = state_report.get("format_counts") or {}
                for name in ("pdf", "rtf"):
                    state_counts[name] = max(
                        int(state_counts.get(name, 0) or 0),
                        int(report_format_counts.get(name, 0) or 0),
                    )
                candidate_doc_count = sum(
                    1
                    for value in candidate_urls
                    if self._document_format_from_url(value) in {"pdf", "rtf"}
                )
                candidate_format_counts = {"pdf": 0, "rtf": 0}
                for value in candidate_urls:
                    doc_format = self._document_format_from_url(value)
                    if doc_format in {"pdf", "rtf"}:
                        candidate_format_counts[doc_format] = int(candidate_format_counts.get(doc_format, 0) or 0) + 1
                candidate_format_counts_by_state[state_code] = candidate_format_counts
                candidate_document_urls += candidate_doc_count
                if candidate_doc_count > 0 and (int(state_counts.get("pdf", 0) or 0) + int(state_counts.get("rtf", 0) or 0) <= 0):
                    states_with_candidate_document_gaps.append(state_code)

                cloudflare_status = str(state_report.get("cloudflare_status") or "").strip().lower()
                cloudflare_challenge = bool(state_report.get("cloudflare_browser_challenge_detected", False))
                cloudflare_http_status = state_report.get("cloudflare_http_status")
                try:
                    normalized_cloudflare_http_status = int(cloudflare_http_status) if cloudflare_http_status is not None and str(cloudflare_http_status).strip() else None
                except (TypeError, ValueError):
                    normalized_cloudflare_http_status = None
                cloudflare_record_status = str(state_report.get("cloudflare_record_status") or "").strip().lower()
                actionable_cloudflare = (
                    cloudflare_status in {"rate_limited", "browser_challenge", "record_errored", "error"}
                    or cloudflare_challenge
                    or normalized_cloudflare_http_status is not None and normalized_cloudflare_http_status >= 400
                    or cloudflare_record_status in {"errored", "failed", "timed_out"}
                )

                per_state_recovery[state_code] = {
                    "processed_method_counts": dict(processed_method_counts),
                    "source_breakdown": dict(state_report.get("source_breakdown") or {}),
                    "domains_seen": list(state_report.get("domains_seen") or []),
                    "parallel_prefetch": dict(state_report.get("parallel_prefetch") or {}),
                    "timed_out": bool(state_report.get("timed_out", False)),
                    "candidate_urls": int(state_report.get("candidate_urls", 0) or 0),
                    "inspected_urls": int(state_report.get("inspected_urls", 0) or 0),
                    "expanded_urls": int(state_report.get("expanded_urls", 0) or 0),
                    "cloudflare_status": cloudflare_status if actionable_cloudflare else None,
                    "cloudflare_http_status": cloudflare_http_status if actionable_cloudflare else None,
                    "cloudflare_browser_challenge_detected": cloudflare_challenge if actionable_cloudflare else False,
                    "cloudflare_error_excerpt": state_report.get("cloudflare_error_excerpt") if actionable_cloudflare else None,
                    "cloudflare_record_status": state_report.get("cloudflare_record_status") if actionable_cloudflare else None,
                    "cloudflare_job_status": state_report.get("cloudflare_job_status") if actionable_cloudflare else None,
                }
            else:
                candidate_urls_by_state[state_code] = []
                per_state_recovery[state_code] = {
                    "processed_method_counts": dict(processed_method_counts),
                    "source_breakdown": {},
                    "domains_seen": [],
                    "parallel_prefetch": {},
                    "timed_out": False,
                    "candidate_urls": 0,
                    "inspected_urls": 0,
                    "expanded_urls": 0,
                    "cloudflare_status": None,
                    "cloudflare_http_status": None,
                    "cloudflare_browser_challenge_detected": False,
                    "cloudflare_error_excerpt": None,
                    "cloudflare_record_status": None,
                    "cloudflare_job_status": None,
                }

            per_state[state_code] = state_counts
            for name, value in state_counts.items():
                total_by_format[name] = int(total_by_format.get(name, 0) or 0) + int(value or 0)

        processed_document_urls = int(total_by_format.get("pdf", 0) or 0) + int(total_by_format.get("rtf", 0) or 0)
        states_with_document_rules = sorted(
            state for state, counts in per_state.items() if int(counts.get("pdf", 0) or 0) + int(counts.get("rtf", 0) or 0) > 0
        )

        return {
            "total_by_format": total_by_format,
            "processed_document_urls": processed_document_urls,
            "candidate_document_urls": int(candidate_document_urls),
            "candidate_format_counts_by_state": candidate_format_counts_by_state,
            "candidate_urls_by_state": candidate_urls_by_state,
            "states_with_document_rules": states_with_document_rules,
            "states_with_candidate_document_gaps": sorted(set(states_with_candidate_document_gaps)),
            "per_state": per_state,
            "per_state_recovery": per_state_recovery,
            "cloudflare_browser_rendering": dict(metadata.get("cloudflare_browser_rendering") or {}),
        }

    def _write_recovered_row_artifacts(
        self,
        *,
        cycle_index: int,
        scrape_result: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Persist recovered rows outside cycle JSON so merge jobs can consume them."""
        data = [block for block in list(scrape_result.get("data") or []) if isinstance(block, dict)]
        cycle_dir = self.recovered_rows_dir / f"cycle_{cycle_index:04d}"
        cycle_dir.mkdir(parents=True, exist_ok=True)

        blocks_path = cycle_dir / f"{self.corpus.key}_blocks.json"
        rows_path = cycle_dir / f"{self.corpus.key}_statutes.jsonl"
        manifest_path = cycle_dir / f"{self.corpus.key}_manifest.json"
        parquet_path = cycle_dir / f"{self.corpus.key}_statutes.parquet"

        rows = self._flatten_recovered_statute_rows(data)
        state_counts: Dict[str, int] = {}
        for row in rows:
            state_code = str(row.get("state_code") or "").upper().strip()
            if not state_code:
                continue
            state_counts[state_code] = int(state_counts.get(state_code, 0) or 0) + 1

        target = self._recovered_row_hf_target_manifest(sorted(state_counts))
        summary: Dict[str, Any] = {
            "status": "success" if rows else "empty",
            "cycle": int(cycle_index),
            "corpus": self.corpus.key,
            "row_count": len(rows),
            "state_counts": state_counts,
            "blocks_json_path": str(blocks_path),
            "statutes_jsonl_path": str(rows_path),
            "statutes_parquet_path": None,
            "manifest_path": str(manifest_path),
            "target_hf_dataset_id": target.get("hf_dataset_id"),
            "target_combined_parquet_path": target.get("combined_parquet_path"),
            "target_parquet_paths_by_state": target.get("parquet_paths_by_state"),
        }

        try:
            blocks_path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
            with rows_path.open("w", encoding="utf-8") as handle:
                for row in rows:
                    handle.write(json.dumps(row, sort_keys=True) + "\n")
        except Exception as exc:
            summary["status"] = "error"
            summary["error"] = str(exc)
            with suppress(Exception):
                manifest_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
            return summary

        if self.corpus.key == "state_admin_rules":
            parquet_error = self._write_recovered_rows_parquet(rows=rows, parquet_path=parquet_path)
            if parquet_error is None and parquet_path.exists():
                summary["statutes_parquet_path"] = str(parquet_path)
            elif parquet_error:
                summary["parquet_error"] = parquet_error
        else:
            summary["parquet_status"] = "skipped"
            summary["parquet_skip_reason"] = "parquet row artifacts are currently emitted for state_admin_rules recovery"

        manifest_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
        return summary

    def _state_admin_scrape_result_from_agentic_checkpoints(
        self,
        *,
        metadata: Dict[str, Any],
        error: str,
    ) -> Optional[Dict[str, Any]]:
        """Build a scrape result from partial admin-rule checkpoints after timeout."""
        if self.corpus.key != "state_admin_rules":
            return None

        checkpoint_dir = self.output_dir / "agentic_checkpoints"
        if not checkpoint_dir.exists():
            return None

        blocks: List[Dict[str, Any]] = []
        total_rows = 0
        for statutes_path in sorted(checkpoint_dir.glob("STATE-*_statutes.jsonl")):
            match = re.match(r"STATE-([A-Z]{2})_statutes\.jsonl$", statutes_path.name)
            if not match:
                continue
            state_code = match.group(1)
            statutes: List[Dict[str, Any]] = []
            try:
                with statutes_path.open("r", encoding="utf-8", errors="ignore") as handle:
                    for line in handle:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            row = json.loads(line)
                        except Exception:
                            continue
                        if not isinstance(row, dict):
                            continue
                        row.setdefault("state_code", state_code)
                        statutes.append(self._json_safe_row(row))
            except Exception:
                continue
            if not statutes:
                continue

            total_rows += len(statutes)
            state_name = US_STATES.get(state_code, state_code)
            blocks.append(
                {
                    "state_code": state_code,
                    "state_name": state_name,
                    "title": f"{state_name} Administrative Rules",
                    "source": "Agentic checkpoint recovery",
                    "source_url": statutes[0].get("source_url"),
                    "scraped_at": datetime.now(timezone.utc).isoformat(),
                    "statutes": statutes,
                    "rules_count": len(statutes),
                    "schema_version": "1.0",
                    "normalized": True,
                    "checkpoint_recovered": True,
                    "checkpoint_path": str(statutes_path),
                }
            )

        if not blocks:
            return None

        checkpoint_metadata = dict(metadata)
        checkpoint_metadata.update(
            {
                "checkpoint_recovered": True,
                "checkpoint_recovered_rows": total_rows,
                "checkpoint_recovered_states": [block["state_code"] for block in blocks],
                "agentic_checkpoint_dir": str(checkpoint_dir),
                "rules_count": total_rows,
            }
        )
        return {
            "status": "partial_success",
            "error": error,
            "data": blocks,
            "metadata": checkpoint_metadata,
        }

    def _flatten_recovered_statute_rows(self, data: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        for block in data:
            state_code = str(block.get("state_code") or block.get("state") or "").upper().strip()
            statutes = block.get("statutes")
            if not isinstance(statutes, list):
                continue
            for index, statute in enumerate(statutes):
                if not isinstance(statute, dict):
                    continue
                row = dict(statute)
                row.setdefault("state_code", state_code)
                row.setdefault("corpus_key", self.corpus.key)
                row.setdefault("recovered_by", "state_laws_agentic_daemon")
                row.setdefault("recovered_at", datetime.now(timezone.utc).isoformat())
                row.setdefault("source_block_index", index)
                rows.append(self._json_safe_row(row))
        return rows

    @staticmethod
    def _json_safe_row(row: Dict[str, Any]) -> Dict[str, Any]:
        safe: Dict[str, Any] = {}
        for key, value in row.items():
            key_text = str(key)
            try:
                json.dumps(value)
                safe[key_text] = value
            except TypeError:
                safe[key_text] = str(value)
        return safe

    def _write_recovered_rows_parquet(self, *, rows: Sequence[Dict[str, Any]], parquet_path: Path) -> Optional[str]:
        if not rows:
            return "no rows to write"
        try:
            import pyarrow as pa  # type: ignore
            import pyarrow.parquet as pq  # type: ignore
        except Exception as exc:
            return f"pyarrow unavailable: {exc}"

        try:
            normalized_rows = [
                {
                    key: (json.dumps(value, sort_keys=True) if isinstance(value, (dict, list)) else value)
                    for key, value in row.items()
                }
                for row in rows
            ]
            table = pa.Table.from_pylist(normalized_rows)
            pq.write_table(table, parquet_path)
        except Exception as exc:
            return str(exc)
        return None

    def _recovered_row_hf_target_manifest(self, states: Sequence[str]) -> Dict[str, Any]:
        try:
            canonical = get_canonical_legal_corpus(self.corpus.key)
        except Exception:
            return {
                "hf_dataset_id": None,
                "combined_parquet_path": None,
                "parquet_paths_by_state": {},
            }

        prefix = canonical.parquet_dir_name.strip("/")
        parquet_paths_by_state = {
            str(state).upper(): f"{prefix}/{canonical.state_parquet_filename(str(state))}" if prefix else canonical.state_parquet_filename(str(state))
            for state in states
            if str(state).strip()
        }
        return {
            "hf_dataset_id": canonical.hf_dataset_id,
            "combined_parquet_path": canonical.combined_parquet_path(),
            "parquet_paths_by_state": parquet_paths_by_state,
        }

    @staticmethod
    def _document_method_from_row(row: Dict[str, Any]) -> Optional[str]:
        if not isinstance(row, dict):
            return None
        direct = str(row.get("method_used") or "").strip().lower()
        if direct:
            return direct
        structured = row.get("structured_data") or {}
        if isinstance(structured, dict):
            nested = str(structured.get("method_used") or "").strip().lower()
            if nested:
                return nested
        return None

    def _build_document_gap_report(
        self,
        *,
        diagnostics: Dict[str, Any],
        metadata: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        documents = diagnostics.get("documents") or {}
        gap_analysis = diagnostics.get("gap_analysis") or {}
        gap_states = [str(item).upper() for item in list(documents.get("states_with_candidate_document_gaps") or []) if str(item).strip()]
        weak_states_all = [str(item).upper() for item in list(gap_analysis.get("weak_states") or []) if str(item).strip()]

        agentic_report = metadata.get("agentic_report") or {}
        agentic_per_state = agentic_report.get("per_state") if isinstance(agentic_report, dict) else {}
        if not isinstance(agentic_per_state, dict):
            agentic_per_state = {}

        capture_states = list(gap_states)
        for state_code in weak_states_all:
            state_report = agentic_per_state.get(state_code)
            candidate_urls = list((state_report or {}).get("top_candidate_urls") or []) if isinstance(state_report, dict) else []
            if candidate_urls and state_code not in capture_states:
                capture_states.append(state_code)

        if not capture_states:
            return None

        document_per_state = documents.get("per_state") or {}
        document_recovery_per_state = documents.get("per_state_recovery") or {}
        gap_states_set = set(capture_states)
        weak_states = [
            str(item).upper()
            for item in weak_states_all
            if str(item).strip() and str(item).upper() in gap_states_set
        ]

        states: Dict[str, Dict[str, Any]] = {}
        for state_code in capture_states:
            processed_by_format = document_per_state.get(state_code) if isinstance(document_per_state, dict) else {}
            if not isinstance(processed_by_format, dict):
                processed_by_format = {}
            state_recovery = document_recovery_per_state.get(state_code) if isinstance(document_recovery_per_state, dict) else {}
            if not isinstance(state_recovery, dict):
                state_recovery = {}
            state_gap = gap_analysis.get("states", {}).get(state_code) if isinstance(gap_analysis.get("states"), dict) else {}
            if not isinstance(state_gap, dict):
                state_gap = {}
            state_report = agentic_per_state.get(state_code)
            if not isinstance(state_report, dict):
                state_report = {}

            top_candidate_document_urls = [
                str(value)
                for value in list(state_report.get("top_candidate_urls") or [])
                if self._document_format_from_url(value) in {"pdf", "rtf"}
            ]
            top_candidate_urls = [
                str(value)
                for value in list(state_report.get("top_candidate_urls") or [])
                if str(value).strip()
            ]
            candidate_document_format_counts = {"pdf": 0, "rtf": 0}
            for value in top_candidate_document_urls:
                doc_format = self._document_format_from_url(value)
                candidate_document_format_counts[doc_format] = int(candidate_document_format_counts.get(doc_format, 0) or 0) + 1
            recovery_directives = self._document_recovery_directives(
                state_code=state_code,
                state_recovery=state_recovery,
                candidate_document_format_counts=candidate_document_format_counts,
                top_candidate_urls=top_candidate_urls,
                top_candidate_document_urls=top_candidate_document_urls,
            )

            states[state_code] = {
                "candidate_urls": int(state_gap.get("candidate_urls", state_report.get("candidate_urls", 0)) or 0),
                "fetched_rules": int(state_gap.get("fetched_rules", state_report.get("fetched_rules", 0)) or 0),
                "processed_by_format": {
                    "html": int(processed_by_format.get("html", 0) or 0),
                    "pdf": int(processed_by_format.get("pdf", 0) or 0),
                    "rtf": int(processed_by_format.get("rtf", 0) or 0),
                },
                "candidate_artifact_urls": len(top_candidate_urls),
                "candidate_document_urls": len(top_candidate_document_urls),
                "candidate_document_format_counts": candidate_document_format_counts,
                "top_candidate_urls": top_candidate_urls[:12],
                "top_candidate_document_urls": top_candidate_document_urls[:12],
                "processed_method_counts": dict(state_recovery.get("processed_method_counts") or {}),
                "source_breakdown": dict(state_recovery.get("source_breakdown") or {}),
                "domains_seen": list(state_recovery.get("domains_seen") or []),
                "parallel_prefetch": dict(state_recovery.get("parallel_prefetch") or {}),
                "timed_out": bool(state_recovery.get("timed_out", False)),
                "inspected_urls": int(state_recovery.get("inspected_urls", 0) or 0),
                "expanded_urls": int(state_recovery.get("expanded_urls", 0) or 0),
                "missing_seed_hosts": [str(item) for item in list(state_gap.get("missing_seed_hosts") or []) if str(item).strip()],
                "candidate_hosts_without_rules": [
                    str(item) for item in list(state_gap.get("candidate_hosts_without_rules") or []) if str(item).strip()
                ],
                "recovery_directives": recovery_directives,
            }

        return {
            "generated_at": datetime.now().isoformat(),
            "corpus": self.corpus.key,
            "states_targeted": list(self.states),
            "states_with_candidate_document_gaps": gap_states,
            "states_with_artifact_candidates": capture_states,
            "weak_states": weak_states,
            "candidate_document_urls": int(documents.get("candidate_document_urls", 0) or 0),
            "processed_document_urls": int(documents.get("processed_document_urls", 0) or 0),
            "states": states,
        }

    def _document_recovery_directives(
        self,
        *,
        state_code: str,
        state_recovery: Dict[str, Any],
        candidate_document_format_counts: Dict[str, int],
        top_candidate_urls: Sequence[str],
        top_candidate_document_urls: Sequence[str],
    ) -> Dict[str, Any]:
        cloudflare_status = str(state_recovery.get("cloudflare_status") or "").strip().lower()
        challenge_detected = bool(state_recovery.get("cloudflare_browser_challenge_detected", False))
        download_methods: List[str] = []
        processor_modes: List[str] = []
        recommended_tactics: List[str] = []

        has_pdf = int(candidate_document_format_counts.get("pdf", 0) or 0) > 0
        has_rtf = int(candidate_document_format_counts.get("rtf", 0) or 0) > 0

        if has_pdf or has_rtf:
            download_methods.extend(["playwright_download", "page_fetch"])
            recommended_tactics.extend(["document_first", "render_first"])
        if has_pdf:
            processor_modes.append("pdf_processor")
        if has_rtf:
            processor_modes.append("rtf_processor")
        if challenge_detected or cloudflare_status == "browser_challenge":
            download_methods.extend(["cloudflare_browser_rendering", "archival_replay"])
            recommended_tactics.extend(["cloudflare_explore", "router_assisted"])
        if cloudflare_status == "rate_limited":
            recommended_tactics.extend(["archival_first", "router_assisted"])
        if not processor_modes:
            processor_modes.append("html_extraction")
        if not download_methods:
            download_methods.extend(["direct_fetch", "archival_replay"])
        if not recommended_tactics:
            recommended_tactics.append("router_assisted")
        if top_candidate_urls and not top_candidate_document_urls:
            recommended_tactics.extend(["discovery_first", "render_first"])

        return {
            "state": str(state_code).upper().strip(),
            "download_methods": list(dict.fromkeys(download_methods)),
            "processor_modes": list(dict.fromkeys(processor_modes)),
            "recommended_tactics": [
                name for name in list(dict.fromkeys(recommended_tactics)) if name in self.config.tactic_profiles
            ],
            "candidate_urls": list(top_candidate_urls)[:12],
            "candidate_document_urls": list(top_candidate_document_urls)[:12],
            "cloudflare_status": cloudflare_status or None,
            "cloudflare_browser_challenge_detected": challenge_detected,
        }

    def _write_document_gap_report(self, *, cycle_index: int, report: Optional[Dict[str, Any]]) -> Optional[Path]:
        if not isinstance(report, dict) or not report:
            return None
        cycle_path = self.cycles_dir / f"cycle_{cycle_index:04d}_document_gaps.json"
        latest_path = self.output_dir / "latest_document_gaps.json"
        payload = dict(report)
        payload["cycle"] = int(cycle_index)
        cycle_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        latest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return cycle_path

    def _build_state_action_plan(self, diagnostics: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        coverage = diagnostics.get("coverage") or {}
        fetch = diagnostics.get("fetch") or {}
        quality = diagnostics.get("quality") or {}
        documents = diagnostics.get("documents") or {}
        gap_analysis = diagnostics.get("gap_analysis") or {}

        plan: Dict[str, Dict[str, Any]] = {}
        document_per_state = documents.get("per_state") or {}
        document_recovery_per_state = documents.get("per_state_recovery") or {}
        candidate_format_counts_by_state = documents.get("candidate_format_counts_by_state") or {}
        gap_states = gap_analysis.get("states") or {}

        def _normalize_state_items(values: Sequence[Any]) -> set[str]:
            normalized: set[str] = set()
            for item in list(values or []):
                if isinstance(item, dict):
                    candidate = item.get("state") or item.get("state_code") or item.get("code")
                else:
                    candidate = item
                state_code = str(candidate or "").upper().strip()
                if state_code in self.states:
                    normalized.add(state_code)
            return normalized

        weak_quality_states = _normalize_state_items(list(quality.get("weak_states") or []))
        no_attempt_states = _normalize_state_items(list(fetch.get("no_attempt_states") or []))
        coverage_gap_states = _normalize_state_items(list(coverage.get("coverage_gap_states") or []))
        document_gap_states = _normalize_state_items(list(documents.get("states_with_candidate_document_gaps") or []))
        weak_gap_states = _normalize_state_items(list(gap_analysis.get("weak_states") or []))

        def _ensure_entry(state_code: str) -> Dict[str, Any]:
            state_key = str(state_code or "").upper().strip()
            entry = plan.setdefault(
                state_key,
                {
                    "priority_score": 0,
                    "reasons": [],
                    "recommended_tactics": [],
                    "query_hints": [],
                    "candidate_document_format_counts": {"pdf": 0, "rtf": 0},
                    "document_recovery_profile": {},
                    "hosts": [],
                },
            )
            return entry

        def _add_reason(state_code: str, reason: str, *, score: int, tactics: Sequence[str]) -> None:
            entry = _ensure_entry(state_code)
            if reason not in entry["reasons"]:
                entry["reasons"].append(reason)
            entry["priority_score"] = int(entry.get("priority_score", 0) or 0) + int(score)
            for tactic_name in tactics:
                if tactic_name in self.config.tactic_profiles and tactic_name not in entry["recommended_tactics"]:
                    entry["recommended_tactics"].append(tactic_name)

        for state_code in sorted(document_gap_states):
            _add_reason(state_code, "document_candidate_gap", score=4, tactics=["document_first", "render_first", "router_assisted"])
            entry = _ensure_entry(state_code)
            candidate_format_counts = candidate_format_counts_by_state.get(state_code) if isinstance(candidate_format_counts_by_state, dict) else {}
            if not isinstance(candidate_format_counts, dict):
                candidate_format_counts = {}
            state_recovery = document_recovery_per_state.get(state_code) if isinstance(document_recovery_per_state, dict) else {}
            if not isinstance(state_recovery, dict):
                state_recovery = {}
            domains_seen = [str(item).strip().lower() for item in list(state_recovery.get("domains_seen") or []) if str(item).strip()]
            processed_method_counts = dict(state_recovery.get("processed_method_counts") or {})
            source_breakdown = dict(state_recovery.get("source_breakdown") or {})
            parallel_prefetch = dict(state_recovery.get("parallel_prefetch") or {})
            entry["document_recovery_profile"] = {
                "processed_method_counts": processed_method_counts,
                "source_breakdown": source_breakdown,
                "domains_seen": domains_seen,
                "parallel_prefetch": parallel_prefetch,
                "candidate_urls": int(state_recovery.get("candidate_urls", 0) or 0),
                "inspected_urls": int(state_recovery.get("inspected_urls", 0) or 0),
                "expanded_urls": int(state_recovery.get("expanded_urls", 0) or 0),
                "timed_out": bool(state_recovery.get("timed_out", False)),
            }
            entry["candidate_document_format_counts"] = {
                "pdf": int(candidate_format_counts.get("pdf", 0) or 0),
                "rtf": int(candidate_format_counts.get("rtf", 0) or 0),
            }
            if domains_seen:
                entry["hosts"] = list(dict.fromkeys(list(entry.get("hosts") or []) + domains_seen))
            if not processed_method_counts and (source_breakdown or int(state_recovery.get("candidate_urls", 0) or 0) > 0):
                _add_reason(
                    state_code,
                    "document_recovery_stalled",
                    score=2,
                    tactics=["render_first", "router_assisted", "document_first"],
                )
            if int(parallel_prefetch.get("attempted", 0) or 0) > 0 and int(parallel_prefetch.get("successful", 0) or 0) <= 0:
                _add_reason(
                    state_code,
                    "document_prefetch_underperforming",
                    score=1,
                    tactics=["archival_first", "router_assisted", "discovery_first"],
                )
            cloudflare_status = str(state_recovery.get("cloudflare_status") or "").strip().lower()
            if bool(state_recovery.get("cloudflare_browser_challenge_detected", False)) or cloudflare_status == "browser_challenge":
                _add_reason(
                    state_code,
                    "cloudflare_browser_challenge",
                    score=3,
                    tactics=["cloudflare_explore", "router_assisted", "render_first", "document_first"],
                )
            if cloudflare_status == "rate_limited":
                _add_reason(
                    state_code,
                    "cloudflare_rate_limited",
                    score=1,
                    tactics=["archival_first", "router_assisted", "cloudflare_explore"],
                )

        for state_code in sorted(weak_gap_states):
            _add_reason(state_code, "coverage_gap", score=3, tactics=["discovery_first", "archival_first", "router_assisted"])
            gap_entry = gap_states.get(state_code) if isinstance(gap_states, dict) else {}
            if not isinstance(gap_entry, dict):
                gap_entry = {}
            hosts = [
                str(item).strip().lower()
                for item in list(gap_entry.get("missing_seed_hosts") or []) + list(gap_entry.get("candidate_hosts_without_rules") or [])
                if str(item).strip()
            ]
            if hosts:
                entry = _ensure_entry(state_code)
                entry["hosts"] = list(dict.fromkeys(entry.get("hosts") or [] + hosts))

        for state_code in sorted(no_attempt_states):
            _add_reason(state_code, "no_attempts", score=3, tactics=["archival_first", "discovery_first"])

        for state_code in sorted(coverage_gap_states):
            _add_reason(state_code, "missing_or_zero_coverage", score=2, tactics=["archival_first", "discovery_first"])

        for state_code in sorted(weak_quality_states):
            _add_reason(state_code, "weak_extraction_quality", score=2, tactics=["render_first", "precision_first"])

        for state_code, entry in plan.items():
            hosts = list(dict.fromkeys([str(item).strip().lower() for item in list(entry.get("hosts") or []) if str(item).strip()]))
            format_counts = entry.get("candidate_document_format_counts") or {}
            query_hints: List[str] = []
            if int(format_counts.get("pdf", 0) or 0) > 0:
                query_hints.append(f"{state_code} administrative code pdf")
            if int(format_counts.get("rtf", 0) or 0) > 0:
                query_hints.append(f"{state_code} administrative code rtf")
            for host in hosts[:2]:
                query_hints.append(f"{state_code} administrative rules site:{host}")
                if int(format_counts.get("pdf", 0) or 0) > 0:
                    query_hints.append(f"{state_code} site:{host} filetype:pdf")
                if int(format_counts.get("rtf", 0) or 0) > 0:
                    query_hints.append(f"{state_code} site:{host} filetype:rtf")
            entry["hosts"] = hosts
            entry["query_hints"] = list(dict.fromkeys([hint for hint in query_hints if hint.strip()]))[:6]

        ordered_plan: Dict[str, Dict[str, Any]] = {}
        for state_code, entry in sorted(
            plan.items(),
            key=lambda item: (-int((item[1] or {}).get("priority_score", 0) or 0), item[0]),
        ):
            normalized_entry = entry or {}
            if int(normalized_entry.get("priority_score", 0) or 0) <= 0:
                continue
            ordered_plan[state_code] = {
                "priority_score": int(normalized_entry.get("priority_score", 0) or 0),
                "reasons": list(normalized_entry.get("reasons") or []),
                "recommended_tactics": list(normalized_entry.get("recommended_tactics") or []),
                "query_hints": list(normalized_entry.get("query_hints") or []),
                "candidate_document_format_counts": dict(normalized_entry.get("candidate_document_format_counts") or {}),
                "document_recovery_profile": dict(normalized_entry.get("document_recovery_profile") or {}),
                "hosts": list(normalized_entry.get("hosts") or []),
            }
        return ordered_plan

    @staticmethod
    def _host_from_url(value: Any) -> str:
        url = str(value or "").strip()
        if not url:
            return ""
        try:
            return str(urlparse(url).netloc or "").strip().lower()
        except Exception:
            return ""

    @staticmethod
    def _priority_states_from_action_plan(state_action_plan: Dict[str, Dict[str, Any]], *, limit: int = 8) -> List[str]:
        ordered: List[str] = []
        for state_code, entry in state_action_plan.items():
            if int((entry or {}).get("priority_score", 0) or 0) <= 0:
                continue
            ordered.append(str(state_code).upper())
            if len(ordered) >= max(1, int(limit or 1)):
                break
        return ordered

    async def _build_router_assist_report(
        self,
        *,
        cycle_index: int,
        tactic: ScraperTacticProfile,
        diagnostics: Dict[str, Any],
        critic: Dict[str, Any],
    ) -> Dict[str, Any]:
        availability = self._router_availability_snapshot()
        report: Dict[str, Any] = {
            "status": "skipped",
            "availability": availability,
            "preferred": {
                "llm_provider": tactic.llm_provider,
                "embeddings_provider": tactic.embeddings_provider,
                "ipfs_backend": tactic.ipfs_backend,
                "enable_ipfs_accelerate": tactic.enable_ipfs_accelerate,
            },
        }
        issues = list(critic.get("issues") or [])
        if not issues:
            report["reason"] = "no-critic-issues"
            return report

        llm_review = await self._run_router_llm_review_with_timeout(tactic=tactic, diagnostics=diagnostics, critic=critic)
        embeddings_ranking = await self._run_router_embeddings_ranking_with_timeout(tactic=tactic, diagnostics=diagnostics, critic=critic)

        report.update(
            {
                "status": "completed",
                "issue_count": len(issues),
                "llm_review": llm_review,
                "embeddings_ranking": embeddings_ranking,
            }
        )

        cycle_path = self._write_router_assist_report(cycle_index=cycle_index, report=report)
        report["artifact_path"] = str(cycle_path) if cycle_path else None

        ipfs_preflight = self._router_ipfs_persist_preflight()
        if not bool(ipfs_preflight.get("available", False)):
            ipfs_persist = {
                "status": "skipped",
                "reason": str(ipfs_preflight.get("reason") or "ipfs-persist-unavailable"),
                "backend": ipfs_preflight.get("backend"),
                "command": ipfs_preflight.get("command"),
            }
            if ipfs_preflight.get("error"):
                ipfs_persist["error"] = ipfs_preflight.get("error")
        else:
            ipfs_persist = await self._run_router_ipfs_persist_with_timeout(
                cycle_index=cycle_index,
                report=report,
                corpus_key=self.corpus.key,
            )
        if ipfs_persist is not None:
            report["ipfs_persist"] = ipfs_persist
        return report

    def _router_availability_snapshot(self) -> Dict[str, Any]:
        availability: Dict[str, Any] = {
            "llm_router": importlib.util.find_spec("ipfs_datasets_py.llm_router") is not None,
            "embeddings_router": importlib.util.find_spec("ipfs_datasets_py.embeddings_router") is not None,
            "ipfs_backend_router": importlib.util.find_spec("ipfs_datasets_py.ipfs_backend_router") is not None,
        }
        try:
            from ipfs_datasets_py import llm_router

            availability["llm_accelerate"] = llm_router.get_accelerate_status()
        except Exception as exc:
            availability["llm_accelerate"] = {"available": False, "error": str(exc)}
        try:
            from ipfs_datasets_py import embeddings_router

            availability["embeddings_accelerate"] = embeddings_router.get_accelerate_status()
        except Exception as exc:
            availability["embeddings_accelerate"] = {"available": False, "error": str(exc)}
        try:
            from ipfs_datasets_py import ipfs_backend_router

            backend = ipfs_backend_router.get_ipfs_backend()
            availability["ipfs_backend"] = type(backend).__name__
        except Exception as exc:
            availability["ipfs_backend"] = None
            availability["ipfs_backend_error"] = str(exc)
        return availability

    def _router_ipfs_persist_preflight(self) -> Dict[str, Any]:
        try:
            from ipfs_datasets_py import ipfs_backend_router

            backend = ipfs_backend_router.get_ipfs_backend()
            backend_name = type(backend).__name__
            command = getattr(backend, "_cmd", None)
            if backend_name == "KuboCLIBackend":
                cmd_text = str(command or os.getenv("IPFS_DATASETS_PY_KUBO_CMD", "ipfs")).strip() or "ipfs"
                executable = shlex.split(cmd_text)[0] if cmd_text else "ipfs"
                if shutil.which(executable) is None:
                    auto_bootstrap = str(
                        os.getenv("LEGAL_DAEMON_ROUTER_IPFS_AUTO_BOOTSTRAP")
                        or os.getenv("IPFS_DATASETS_ROUTER_IPFS_AUTO_BOOTSTRAP")
                        or "0"
                    ).strip().lower() in {"1", "true", "yes", "on"}
                    if not auto_bootstrap:
                        return {
                            "available": False,
                            "reason": "ipfs-cli-missing",
                            "backend": backend_name,
                            "command": cmd_text,
                            "install_attempted": False,
                        }
                    install_attempt = self._attempt_router_ipfs_kit_bootstrap()
                    if bool(install_attempt.get("available", False)):
                        return install_attempt
                    return {
                        "available": False,
                        "reason": str(install_attempt.get("reason") or "ipfs-cli-missing"),
                        "backend": install_attempt.get("backend") or backend_name,
                        "command": install_attempt.get("command") or cmd_text,
                        "install_attempted": bool(install_attempt.get("install_attempted", False)),
                        "installer": install_attempt.get("installer"),
                        "error": install_attempt.get("error"),
                    }
            return {
                "available": True,
                "backend": backend_name,
                "command": str(command).strip() if command else None,
            }
        except Exception as exc:
            return {
                "available": False,
                "reason": "ipfs-backend-unavailable",
                "backend": None,
                "command": None,
                "error": str(exc),
            }

    def _attempt_router_ipfs_kit_bootstrap(self) -> Dict[str, Any]:
        repo_root = Path(__file__).resolve().parents[3]
        installer_path = repo_root / "scripts" / "setup" / "install.py"
        if not installer_path.exists():
            return {
                "available": False,
                "reason": "ipfs-kit-installer-missing",
                "backend": None,
                "command": None,
                "installer": str(installer_path),
            }

        try:
            spec = importlib.util.spec_from_file_location("ipfs_datasets_setup_install", installer_path)
            if spec is None or spec.loader is None:
                raise RuntimeError(f"unable to load installer module from {installer_path}")
            install_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(install_module)
            ensure_main_ipfs_kit_py = getattr(install_module, "ensure_main_ipfs_kit_py", None)
            if not callable(ensure_main_ipfs_kit_py):
                raise RuntimeError("ensure_main_ipfs_kit_py helper not available")
            os.environ.setdefault("IPFS_KIT_PY_USE_GIT", "true")
            os.environ["IPFS_DATASETS_PY_ENABLE_IPFS_KIT"] = "1"
            ensure_main_ipfs_kit_py()
        except Exception as exc:
            return {
                "available": False,
                "reason": "ipfs-kit-install-failed",
                "backend": None,
                "command": None,
                "installer": str(installer_path),
                "install_attempted": True,
                "error": str(exc),
            }

        backend_result = self._resolve_router_ipfs_backend_after_bootstrap(installer_path=installer_path)
        if bool(backend_result.get("available", False)):
            return backend_result

        quick_setup = getattr(install_module, "quick_setup", None)
        if callable(quick_setup):
            try:
                quick_setup_result = quick_setup()
            except Exception as exc:
                quick_setup_result = exc
            if not isinstance(quick_setup_result, BaseException):
                backend_result = self._resolve_router_ipfs_backend_after_bootstrap(installer_path=installer_path)
                backend_result["quick_setup_attempted"] = True
                backend_result["quick_setup_result"] = int(quick_setup_result or 0)
                if bool(backend_result.get("available", False)):
                    return backend_result
            else:
                backend_result = dict(backend_result)
                backend_result["quick_setup_attempted"] = True
                backend_result["quick_setup_error"] = str(quick_setup_result)

        return backend_result

    def _resolve_router_ipfs_backend_after_bootstrap(self, *, installer_path: Path) -> Dict[str, Any]:
        try:
            from ipfs_datasets_py import ipfs_backend_router, router_deps

            ipfs_backend_router.clear_ipfs_backend_router_caches()
            deps = router_deps.get_default_router_deps()
            deps.ipfs_backend = None
            backend = ipfs_backend_router.get_ipfs_backend(use_cache=False, deps=deps)
            backend_name = type(backend).__name__
            command = getattr(backend, "_cmd", None)
            if backend_name == "KuboCLIBackend":
                cmd_text = str(command or os.getenv("IPFS_DATASETS_PY_KUBO_CMD", "ipfs")).strip() or "ipfs"
                executable = shlex.split(cmd_text)[0] if cmd_text else "ipfs"
                if shutil.which(executable) is None:
                    return {
                        "available": False,
                        "reason": "ipfs-kit-install-did-not-change-backend",
                        "backend": backend_name,
                        "command": cmd_text,
                        "installer": str(installer_path),
                        "install_attempted": True,
                    }
            return {
                "available": True,
                "backend": backend_name,
                "command": str(command).strip() if command else None,
                "installer": str(installer_path),
                "install_attempted": True,
            }
        except Exception as exc:
            return {
                "available": False,
                "reason": "ipfs-kit-backend-unavailable-after-install",
                "backend": None,
                "command": None,
                "installer": str(installer_path),
                "install_attempted": True,
                "error": str(exc),
            }

    async def _run_llm_router_review(
        self,
        *,
        tactic: ScraperTacticProfile,
        diagnostics: Dict[str, Any],
        critic: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        try:
            from ipfs_datasets_py import llm_router
        except Exception as exc:
            return {"status": "unavailable", "error": str(exc)}

        prompt_payload = {
            "corpus": self.corpus.key,
            "states": list(self.states),
            "critic": {
                "summary": critic.get("summary"),
                "issues": list(critic.get("issues") or []),
                "provider_summary": critic.get("provider_summary") or {},
                "priority_states": list(critic.get("priority_states") or []),
                "state_action_plan": critic.get("state_action_plan") or {},
            },
            "diagnostics": {
                "coverage": diagnostics.get("coverage") or {},
                "fetch": diagnostics.get("fetch") or {},
                "etl_readiness": diagnostics.get("etl_readiness") or {},
                "documents": diagnostics.get("documents") or {},
                "gap_analysis": diagnostics.get("gap_analysis") or {},
            },
            "available_tactics": {
                name: profile.description for name, profile in self.config.tactic_profiles.items()
            },
        }
        prompt = (
            "You are reviewing an agentic legal scraping cycle. "
            "Return strict JSON with keys recommended_next_tactics, priority_states, query_hints, rationale. "
            "Only recommend tactics from the available_tactics keys. Keep query_hints short and state-specific.\n"
            + json.dumps(prompt_payload, ensure_ascii=False)
        )
        try:
            timeout_seconds = max(0.0, float(self.config.router_llm_timeout_seconds or 0.0))
            router_llm_kwargs = self._router_llm_kwargs(tactic=tactic, timeout_seconds=timeout_seconds)
            response = await self._run_blocking_on_daemon_thread(
                llm_router.generate_text,
                prompt,
                timeout_seconds=timeout_seconds,
                **router_llm_kwargs,
            )
        except Exception as exc:
            if router_llm_kwargs.get("provider") is None:
                exc_text = str(exc)
                if "ipfs_accelerate_py provider did not return generated text" in exc_text:
                    return {
                        "status": "unavailable",
                        "error": exc_text,
                        "reason": "accelerate-empty-response",
                    }
                if "Accelerate not available, using local fallback" in exc_text:
                    return {
                        "status": "unavailable",
                        "error": exc_text,
                        "reason": "accelerate-no-remote-fallback",
                    }
            return {"status": "error", "error": str(exc)}

        parsed = self._parse_router_llm_response(response)
        if parsed is None:
            return {"status": "error", "error": "invalid-json-response", "raw": str(response)[:1200]}
        parsed["status"] = "success"
        parsed["provider"] = router_llm_kwargs.get("provider")
        if router_llm_kwargs.get("model_name"):
            parsed["model_name"] = str(router_llm_kwargs.get("model_name"))
        if router_llm_kwargs.get("hf_provider"):
            parsed["hf_provider"] = str(router_llm_kwargs.get("hf_provider"))
        if router_llm_kwargs.get("hf_bill_to"):
            parsed["hf_bill_to"] = str(router_llm_kwargs.get("hf_bill_to"))
        return parsed

    async def _run_router_llm_review_with_timeout(
        self,
        *,
        tactic: ScraperTacticProfile,
        diagnostics: Dict[str, Any],
        critic: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        timeout_seconds = max(0.0, float(self.config.router_llm_timeout_seconds or 0.0))
        if timeout_seconds <= 0.0:
            return await self._run_llm_router_review(tactic=tactic, diagnostics=diagnostics, critic=critic)
        try:
            return await asyncio.wait_for(
                self._run_llm_router_review(tactic=tactic, diagnostics=diagnostics, critic=critic),
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError:
            return {
                "status": "unavailable",
                "error": f"timed out after {timeout_seconds:.1f} seconds",
                "reason": "timed-out",
            }

    @staticmethod
    def _parse_router_llm_response(response: Any) -> Optional[Dict[str, Any]]:
        text = str(response or "").strip()
        if not text:
            return None
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].strip()
        try:
            payload = json.loads(text)
        except Exception:
            return None
        if not isinstance(payload, dict):
            return None
        payload["recommended_next_tactics"] = [
            str(item) for item in list(payload.get("recommended_next_tactics") or []) if str(item).strip()
        ]
        payload["priority_states"] = [str(item).upper() for item in list(payload.get("priority_states") or []) if str(item).strip()]
        payload["query_hints"] = [str(item) for item in list(payload.get("query_hints") or []) if str(item).strip()]
        payload["rationale"] = str(payload.get("rationale") or "").strip()
        return payload

    def _rank_tactics_with_embeddings(
        self,
        tactic: ScraperTacticProfile,
        diagnostics: Dict[str, Any],
        critic: Dict[str, Any],
    ) -> Optional[List[Dict[str, Any]]]:
        try:
            from ipfs_datasets_py import embeddings_router
        except Exception:
            return None

        issue_summary = str(critic.get("summary") or "").strip()
        if not issue_summary:
            return None
        configured_provider = (
            str(tactic.embeddings_provider or "").strip()
            or str(os.getenv("LEGAL_DAEMON_ROUTER_EMBEDDINGS_PROVIDER") or "").strip()
            or str(os.getenv("IPFS_DATASETS_PY_EMBEDDINGS_PROVIDER") or "").strip()
        )
        allow_unpinned = str(
            os.getenv("LEGAL_DAEMON_ROUTER_EMBEDDINGS_ALLOW_UNPINNED")
            or "0"
        ).strip().lower() in {"1", "true", "yes", "on"}
        if not configured_provider and not allow_unpinned:
            return None
        tactic_names = list(self.config.tactic_profiles.keys())
        texts = [issue_summary] + [
            f"{name}: {self.config.tactic_profiles[name].description}" for name in tactic_names
        ]
        try:
            embeddings = embeddings_router.embed_texts_batched(
                texts,
                batch_size=max(2, len(texts)),
                provider=configured_provider or tactic.embeddings_provider,
            )
        except Exception:
            return None
        if len(embeddings) != len(texts):
            return None
        query_vector = embeddings[0]
        ranking: List[Dict[str, Any]] = []
        for name, vector in zip(tactic_names, embeddings[1:]):
            ranking.append(
                {
                    "tactic": name,
                    "score": round(self._cosine_similarity(query_vector, vector), 4),
                }
            )
        ranking.sort(key=lambda item: float(item.get("score", 0.0) or 0.0), reverse=True)
        return ranking

    async def _run_blocking_on_daemon_thread(
        self,
        func: Callable[..., Any],
        *args: Any,
        timeout_seconds: float = 0.0,
        **kwargs: Any,
    ) -> Any:
        loop = asyncio.get_running_loop()
        result_future: asyncio.Future[Any] = loop.create_future()

        def _publish_result(result: Any) -> None:
            if not result_future.done():
                result_future.set_result(result)

        def _publish_exception(exc: BaseException) -> None:
            if not result_future.done():
                result_future.set_exception(exc)

        def _worker() -> None:
            try:
                result = func(*args, **kwargs)
            except BaseException as exc:
                loop.call_soon_threadsafe(_publish_exception, exc)
                return

            loop.call_soon_threadsafe(_publish_result, result)

        worker = threading.Thread(target=_worker, name="agentic-daemon-blocking-call", daemon=True)
        worker.start()

        if float(timeout_seconds or 0.0) > 0.0:
            return await asyncio.wait_for(result_future, timeout=float(timeout_seconds))
        return await result_future

    async def _run_router_embeddings_ranking_with_timeout(
        self,
        *,
        tactic: ScraperTacticProfile,
        diagnostics: Dict[str, Any],
        critic: Dict[str, Any],
    ) -> Optional[List[Dict[str, Any]]]:
        timeout_seconds = max(0.0, float(self.config.router_embeddings_timeout_seconds or 0.0))
        ranking_task = asyncio.to_thread(self._rank_tactics_with_embeddings, tactic, diagnostics, critic)
        if timeout_seconds <= 0.0:
            return await ranking_task
        try:
            return await asyncio.wait_for(ranking_task, timeout=timeout_seconds)
        except asyncio.TimeoutError:
            return None

    @staticmethod
    def _cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
        if not left or not right or len(left) != len(right):
            return 0.0
        numerator = sum(float(a) * float(b) for a, b in zip(left, right))
        left_norm = math.sqrt(sum(float(a) * float(a) for a in left))
        right_norm = math.sqrt(sum(float(b) * float(b) for b in right))
        if left_norm <= 0.0 or right_norm <= 0.0:
            return 0.0
        return numerator / (left_norm * right_norm)

    async def _persist_router_assist_to_ipfs(
        self,
        *,
        cycle_index: int,
        report: Dict[str, Any],
        corpus_key: str,
    ) -> Optional[Dict[str, Any]]:
        try:
            from .ipfs_storage_integration import IPFSStorageManager
        except Exception as exc:
            return {"status": "unavailable", "error": str(exc)}
        try:
            storage = IPFSStorageManager(metadata_dir=str(self.output_dir / "ipfs_router_reviews"))
            result = await storage.add_dataset(
                name=f"{corpus_key}_agentic_router_review_cycle_{cycle_index:04d}",
                data=report,
                metadata={"cycle": cycle_index, "corpus": corpus_key, "states": list(self.states)},
                format="json",
                pin=False,
            )
            return result
        except Exception as exc:
            return {"status": "error", "error": str(exc)}

    async def _run_router_ipfs_persist_with_timeout(
        self,
        *,
        cycle_index: int,
        report: Dict[str, Any],
        corpus_key: str,
    ) -> Optional[Dict[str, Any]]:
        timeout_seconds = max(0.0, float(self.config.router_ipfs_timeout_seconds or 0.0))
        if timeout_seconds <= 0.0:
            return await self._persist_router_assist_to_ipfs(
                cycle_index=cycle_index,
                report=report,
                corpus_key=corpus_key,
            )

        loop = asyncio.get_running_loop()
        result_future: asyncio.Future[Optional[Dict[str, Any]]] = loop.create_future()

        def _publish_result(result: Optional[Dict[str, Any]]) -> None:
            if not result_future.done():
                result_future.set_result(result)

        def _publish_exception(exc: BaseException) -> None:
            if not result_future.done():
                result_future.set_exception(exc)

        def _worker() -> None:
            try:
                result = asyncio.run(
                    self._persist_router_assist_to_ipfs(
                        cycle_index=cycle_index,
                        report=report,
                        corpus_key=corpus_key,
                    )
                )
            except BaseException as exc:
                try:
                    loop.call_soon_threadsafe(_publish_exception, exc)
                except RuntimeError:
                    pass
                return
            try:
                loop.call_soon_threadsafe(_publish_result, result)
            except RuntimeError:
                pass

        threading.Thread(
            target=_worker,
            name="agentic-daemon-router-ipfs-worker",
            daemon=True,
        ).start()

        try:
            return await asyncio.wait_for(asyncio.shield(result_future), timeout=timeout_seconds)
        except asyncio.TimeoutError:
            return {"status": "error", "error": f"timed out after {timeout_seconds:.1f} seconds"}

    def _write_router_assist_report(self, *, cycle_index: int, report: Dict[str, Any]) -> Optional[Path]:
        if not isinstance(report, dict) or not report:
            return None
        cycle_path = self.cycles_dir / f"cycle_{cycle_index:04d}_router_assist.json"
        latest_path = self.output_dir / "latest_router_assist.json"
        payload = dict(report)
        payload["cycle"] = int(cycle_index)
        cycle_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        latest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return cycle_path

    def _merge_router_assist_into_critic(self, *, critic: Dict[str, Any], router_assist: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        if not isinstance(router_assist, dict) or str(router_assist.get("status") or "") != "completed":
            return critic
        updated = dict(critic)
        merged_tactics = list(updated.get("recommended_next_tactics") or [])
        llm_review = router_assist.get("llm_review") or {}
        if isinstance(llm_review, dict):
            for name in list(llm_review.get("recommended_next_tactics") or []):
                if name in self.config.tactic_profiles and name not in merged_tactics:
                    merged_tactics.insert(0, name)
        embeddings_ranking = list(router_assist.get("embeddings_ranking") or [])
        for row in embeddings_ranking[:2]:
            if not isinstance(row, dict):
                continue
            name = str(row.get("tactic") or "")
            if name in self.config.tactic_profiles and name not in merged_tactics:
                merged_tactics.append(name)
        updated["recommended_next_tactics"] = list(dict.fromkeys(merged_tactics))
        merged_priority_states = [
            str(item).upper().strip()
            for item in list(updated.get("priority_states") or [])
            if str(item).strip()
        ]
        if isinstance(llm_review, dict):
            for state_code in list(llm_review.get("priority_states") or []):
                normalized_state = str(state_code).upper().strip()
                if normalized_state and normalized_state in self.states and normalized_state not in merged_priority_states:
                    merged_priority_states.insert(0, normalized_state)
        if merged_priority_states:
            updated["priority_states"] = merged_priority_states
        llm_query_hints = list(llm_review.get("query_hints") or []) if isinstance(llm_review, dict) else []
        if llm_query_hints:
            updated["query_hints"] = llm_query_hints
        if isinstance(llm_review, dict) and str(llm_review.get("rationale") or "").strip():
            updated["router_rationale"] = str(llm_review.get("rationale") or "").strip()
        issues = list(updated.get("issues") or [])
        if "router-assisted-review" not in issues:
            issues.append("router-assisted-review")
        updated["issues"] = issues
        return updated

    async def _run_parallel_admin_assist(
        self,
        *,
        cycle_index: int,
        tactic: ScraperTacticProfile,
        diagnostics: Dict[str, Any],
        critic: Dict[str, Any],
        metadata: Dict[str, Any],
    ) -> Dict[str, Any]:
        if self.corpus.key != "state_admin_rules":
            return {"status": "skipped", "reason": "corpus-not-state-admin-rules"}
        if not bool(self.config.admin_parallel_assist_enabled):
            return {"status": "skipped", "reason": "parallel-assist-disabled"}

        target_states = self._parallel_admin_target_states(diagnostics=diagnostics, critic=critic)
        if not target_states:
            return {"status": "skipped", "reason": "no-priority-states"}

        try:
            from .enhanced_state_admin_orchestrator import (
                ParallelStateAdminOrchestrator,
                ParallelStateDiscoveryConfig,
            )
            from .state_admin_rules_scraper import US_STATES as _ADMIN_US_STATES
            from .state_admin_rules_scraper import _extract_seed_urls_for_state
        except Exception as exc:
            return {"status": "error", "error": str(exc)}

        seed_urls_by_state: Dict[str, List[str]] = {}
        candidate_domains: Dict[str, List[str]] = {}
        agentic_report = metadata.get("agentic_report") or {}
        agentic_per_state = agentic_report.get("per_state") if isinstance(agentic_report, dict) else {}
        if not isinstance(agentic_per_state, dict):
            agentic_per_state = {}

        for state_code in target_states:
            state_name = str(_ADMIN_US_STATES.get(state_code, state_code))
            seed_urls = list(_extract_seed_urls_for_state(state_code, state_name) or [])
            state_report = agentic_per_state.get(state_code) if isinstance(agentic_per_state, dict) else None
            if isinstance(state_report, dict):
                for candidate_url in list(state_report.get("top_candidate_urls") or []):
                    if self._document_format_from_url(candidate_url) not in {"pdf", "rtf"}:
                        continue
                    normalized_url = str(candidate_url or "").strip()
                    if normalized_url and normalized_url not in seed_urls:
                        seed_urls.append(normalized_url)
                candidate_domains[state_code] = [
                    str(item)
                    for item in list(state_report.get("top_candidate_urls") or [])
                    if str(item).strip()
                ]
            seed_urls_by_state[state_code] = seed_urls

        config = ParallelStateDiscoveryConfig(
            max_state_workers=max(1, min(len(target_states), int(self.config.admin_parallel_assist_state_limit or 1))),
            max_domain_workers_per_state=max(1, int(self.config.admin_agentic_fetch_concurrency or 4)),
            max_urls_per_domain=max(4, int(self.config.admin_parallel_assist_max_urls_per_domain or 4)),
            max_fetch_per_state=max(1, int(self.config.admin_agentic_max_fetch_per_state or 1000)),
            max_candidates_per_state=max(4, int(self.config.admin_agentic_max_candidates_per_state or 1000)),
            state_timeout=max(15.0, float(self.config.admin_parallel_assist_timeout_seconds or 86400.0)),
            url_fetch_timeout=min(300.0, max(5.0, float(self.config.admin_parallel_assist_timeout_seconds or 86400.0) / 6.0)),
            domain_timeout=min(600.0, max(10.0, float(self.config.admin_parallel_assist_timeout_seconds or 86400.0) / 3.0)),
            min_rule_text_chars=max(120, int(tactic.min_full_text_chars or 120)),
            enable_pdf_processing=True,
            enable_gap_analysis=True,
            cache_dir=str(self.output_dir / "url_archive_cache" / "parallel_admin_assist"),
            cache_read_enabled=True,
            cache_write_enabled=True,
            cache_to_ipfs=True,
        )

        orchestrator = ParallelStateAdminOrchestrator(config=config)
        try:
            results = await orchestrator.discover_state_rules_parallel(
                states=target_states,
                seed_urls_by_state=seed_urls_by_state,
                candidate_domains=candidate_domains,
            )
        except Exception as exc:
            return {"status": "error", "error": str(exc), "targeted_states": target_states}

        per_state: Dict[str, Dict[str, Any]] = {}
        recommended_tactics: List[str] = []
        query_hints: List[str] = []
        states_with_rules: List[str] = []
        states_without_rules: List[str] = []
        total_rules = 0

        for state_code in target_states:
            state_result = results.get(state_code)
            if state_result is None:
                states_without_rules.append(state_code)
                continue
            rules = list(getattr(state_result, "rules", []) or [])
            methods_used = dict(getattr(state_result, "methods_used", {}) or {})
            domains_visited = sorted(str(item) for item in list(getattr(state_result, "domains_visited", set()) or []))
            gap_analysis = dict(getattr(state_result, "gap_analysis", {}) or {})
            rules_found = len(rules)
            total_rules += rules_found
            if rules_found > 0:
                states_with_rules.append(state_code)
            else:
                states_without_rules.append(state_code)

            if any("playwright" in str(name).lower() or "pdf" in str(name).lower() or "rtf" in str(name).lower() for name in methods_used):
                recommended_tactics.extend(["document_first", "render_first"])
            if any(any(token in str(name).lower() for token in ("common_crawl", "wayback", "archive")) for name in methods_used):
                recommended_tactics.extend(["archival_first", "discovery_first"])
            if rules_found <= 0:
                recommended_tactics.extend(["router_assisted", "discovery_first"])

            for host in domains_visited[:2]:
                query_hints.append(f"{state_code} administrative rules site:{host}")
                query_hints.append(f"{state_code} site:{host} filetype:pdf")
                query_hints.append(f"{state_code} site:{host} filetype:rtf")

            per_state[state_code] = {
                "status": str(getattr(state_result, "status", "unknown") or "unknown"),
                "rules_found": rules_found,
                "urls_discovered": int(getattr(state_result, "urls_discovered", 0) or 0),
                "urls_fetched": int(getattr(state_result, "urls_fetched", 0) or 0),
                "fetch_errors": int(getattr(state_result, "fetch_errors", 0) or 0),
                "methods_used": methods_used,
                "domains_visited": domains_visited,
                "gap_analysis": gap_analysis,
                "top_rule_urls": [str((row or {}).get("url") or (row or {}).get("source_url") or "") for row in rules[:8]],
            }

        report: Dict[str, Any] = {
            "status": "completed",
            "targeted_states": target_states,
            "states_with_rules": states_with_rules,
            "states_without_rules": states_without_rules,
            "priority_states": states_without_rules or target_states,
            "discovered_rules_total": total_rules,
            "recommended_next_tactics": list(dict.fromkeys([name for name in recommended_tactics if name in self.config.tactic_profiles])),
            "query_hints": list(dict.fromkeys([hint for hint in query_hints if hint.strip()]))[:12],
            "per_state": per_state,
        }
        artifact_path = self._write_parallel_admin_assist_report(cycle_index=cycle_index, report=report)
        report["artifact_path"] = str(artifact_path) if artifact_path else None
        return report

    def _parallel_admin_target_states(self, *, diagnostics: Dict[str, Any], critic: Dict[str, Any]) -> List[str]:
        ordered: List[str] = []

        def _push(values: Sequence[Any]) -> None:
            for item in list(values or []):
                state_code = str(item or "").upper().strip()
                if state_code in self.states and state_code not in ordered:
                    ordered.append(state_code)
                    if len(ordered) >= max(1, int(self.config.admin_parallel_assist_state_limit or 1)):
                        return

        _push(list(critic.get("priority_states") or []))
        documents = diagnostics.get("documents") or {}
        coverage = diagnostics.get("coverage") or {}
        gap_analysis = diagnostics.get("gap_analysis") or {}
        _push(list(documents.get("states_with_candidate_document_gaps") or []))
        _push(list(gap_analysis.get("weak_states") or []))
        _push(list(coverage.get("coverage_gap_states") or []))
        _push(list((diagnostics.get("fetch") or {}).get("no_attempt_states") or []))
        return ordered[: max(1, int(self.config.admin_parallel_assist_state_limit or 1))]

    def _write_parallel_admin_assist_report(self, *, cycle_index: int, report: Dict[str, Any]) -> Optional[Path]:
        if not isinstance(report, dict) or not report:
            return None
        cycle_path = self.cycles_dir / f"cycle_{cycle_index:04d}_parallel_admin_assist.json"
        latest_path = self.output_dir / "latest_parallel_admin_assist.json"
        payload = dict(report)
        payload["cycle"] = int(cycle_index)
        cycle_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        latest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return cycle_path

    def _merge_parallel_admin_assist_into_critic(
        self,
        *,
        critic: Dict[str, Any],
        parallel_admin_assist: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        if not isinstance(parallel_admin_assist, dict) or str(parallel_admin_assist.get("status") or "") != "completed":
            return critic
        updated = dict(critic)
        merged_tactics = list(updated.get("recommended_next_tactics") or [])
        for name in list(parallel_admin_assist.get("recommended_next_tactics") or []):
            if name in self.config.tactic_profiles and name not in merged_tactics:
                merged_tactics.append(name)
        updated["recommended_next_tactics"] = merged_tactics

        merged_priority_states = [
            str(item).upper().strip()
            for item in list(updated.get("priority_states") or [])
            if str(item).strip()
        ]
        for state_code in list(parallel_admin_assist.get("priority_states") or []):
            normalized = str(state_code).upper().strip()
            if normalized in self.states and normalized not in merged_priority_states:
                merged_priority_states.insert(0, normalized)
        updated["priority_states"] = merged_priority_states

        query_hints = [str(item) for item in list(updated.get("query_hints") or []) if str(item).strip()]
        for hint in list(parallel_admin_assist.get("query_hints") or []):
            normalized_hint = str(hint).strip()
            if normalized_hint and normalized_hint not in query_hints:
                query_hints.append(normalized_hint)
        if query_hints:
            updated["query_hints"] = query_hints[:12]

        updated["parallel_admin_assist"] = {
            "targeted_states": list(parallel_admin_assist.get("targeted_states") or []),
            "states_with_rules": list(parallel_admin_assist.get("states_with_rules") or []),
            "states_without_rules": list(parallel_admin_assist.get("states_without_rules") or []),
            "discovered_rules_total": int(parallel_admin_assist.get("discovered_rules_total", 0) or 0),
        }
        return updated

    def _build_corpus_gap_summary(
        self,
        *,
        data: Sequence[Dict[str, Any]],
        metadata: Dict[str, Any],
        document_coverage: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        agentic_report = metadata.get("agentic_report") or {}
        agentic_per_state = agentic_report.get("per_state") if isinstance(agentic_report, dict) else {}
        if not isinstance(agentic_per_state, dict):
            agentic_per_state = {}

        weak_states: List[str] = []
        by_state: Dict[str, Dict[str, Any]] = {}
        document_gap_states = set(str(item).upper() for item in list((document_coverage or {}).get("states_with_candidate_document_gaps") or []))

        for state_code in list(self.states):
            state_report = agentic_per_state.get(state_code)
            if not isinstance(state_report, dict):
                continue
            gap_summary = state_report.get("gap_summary") or {}
            missing_seed_hosts = [str(item) for item in list(gap_summary.get("missing_seed_hosts") or []) if str(item).strip()]
            candidate_hosts_without_rules = [
                str(item) for item in list(gap_summary.get("candidate_hosts_without_rules") or []) if str(item).strip()
            ]
            fetched_rules = int(state_report.get("fetched_rules", 0) or 0)
            candidate_urls = int(state_report.get("candidate_urls", 0) or 0)
            entry = {
                "candidate_urls": candidate_urls,
                "fetched_rules": fetched_rules,
                "missing_seed_hosts": missing_seed_hosts,
                "candidate_hosts_without_rules": candidate_hosts_without_rules,
                "document_gap": state_code in document_gap_states,
            }
            if missing_seed_hosts or candidate_hosts_without_rules or state_code in document_gap_states:
                weak_states.append(state_code)
            by_state[state_code] = entry

        return {
            "weak_states": sorted(set(weak_states)),
            "states": by_state,
        }

    @staticmethod
    def _document_format_from_url(value: Any) -> str:
        url = str(value or "").strip().lower()
        if url.endswith(".pdf") or ".pdf?" in url:
            return "pdf"
        if url.endswith(".rtf") or ".rtf?" in url:
            return "rtf"
        return "html"

    async def _maybe_run_post_cycle_release(
        self,
        *,
        cycle_index: int,
        critic_score: float,
        passed: bool,
    ) -> Dict[str, Any]:
        cfg = self.config.post_cycle_release
        if not bool(cfg.enabled):
            return {"status": "skipped", "reason": "post-cycle-release-disabled"}

        required_score = float(cfg.min_score if cfg.min_score is not None else self.config.target_score)
        if bool(cfg.require_passed) and not passed:
            return {"status": "skipped", "reason": "cycle-did-not-pass", "required_score": required_score}
        if float(critic_score) < required_score:
            return {
                "status": "skipped",
                "reason": "score-below-threshold",
                "required_score": required_score,
                "critic_score": critic_score,
            }

        plan = self._build_post_cycle_release_plan(cycle_index=cycle_index, critic_score=critic_score)
        if bool(cfg.dry_run):
            return {
                "status": "planned",
                "dry_run": True,
                "workspace_root": str(plan["workspace_root"]),
                "commands": plan["commands"],
                "artifacts": plan["artifacts"],
            }

        stage_results: List[Dict[str, Any]] = []
        for stage in list(plan["commands"]):
            result = await self._run_release_command(
                command=str(stage["command"]),
                cwd=Path(str(plan["workspace_root"])),
                timeout_seconds=int(cfg.timeout_seconds or 7200),
            )
            stage_results.append({**stage, **result})
            if int(result.get("exit_code", 1) or 1) != 0:
                return {
                    "status": "error",
                    "workspace_root": str(plan["workspace_root"]),
                    "artifacts": plan["artifacts"],
                    "commands": stage_results,
                }

        return {
            "status": "success",
            "workspace_root": str(plan["workspace_root"]),
            "artifacts": plan["artifacts"],
            "commands": stage_results,
        }

    def _build_post_cycle_release_plan(self, *, cycle_index: int, critic_score: float) -> Dict[str, Any]:
        workspace_root = self._workspace_root()
        python_bin = self._python_bin()
        canonical = get_canonical_legal_corpus(self.corpus.key)
        cycle_stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        merge_output_dir = workspace_root / "artifacts" / self.corpus.key / f"canonical_merged_daemon_cycle_{cycle_index:04d}_{cycle_stamp}"
        clean_output_dir = merge_output_dir.parent / f"{merge_output_dir.name}_cleaned"
        if self.corpus.key == "state_admin_rules":
            jsonld_dir = clean_output_dir / canonical.jsonld_dir_name
            parquet_dir = clean_output_dir / canonical.parquet_dir_name
        else:
            jsonld_dir = merge_output_dir / canonical.jsonld_dir_name
            parquet_dir = merge_output_dir / canonical.parquet_dir_name

        context = {
            "workspace_root": str(workspace_root),
            "python_bin": shlex.quote(str(python_bin)),
            "merge_output_dir": str(merge_output_dir),
            "clean_output_dir": str(clean_output_dir),
            "jsonld_dir": str(jsonld_dir),
            "parquet_dir": str(parquet_dir),
            "daemon_output_dir": str(self.output_dir),
            "combined_parquet": str(parquet_dir / canonical.combined_parquet_filename),
            "combined_embeddings": str(parquet_dir / canonical.combined_embeddings_filename),
            "corpus_key": self.corpus.key,
            "critic_score": f"{critic_score:.4f}",
            "merge_state_args": " ".join(
                f'--state {shlex.quote(state)}' for state in list(self.states) if str(state).strip()
            ),
        }

        commands = self._release_command_templates()
        rendered_commands: List[Dict[str, Any]] = []
        for stage_name, template in commands:
            rendered_commands.append(
                {
                    "stage": stage_name,
                    "command": template.format(**context),
                }
            )

        publish_command = str(self.config.post_cycle_release.publish_command or "").strip()
        if publish_command:
            rendered_commands.append(
                {
                    "stage": "publish",
                    "command": publish_command.format(**context),
                }
            )

        return {
            "workspace_root": workspace_root,
            "artifacts": {
                "merge_output_dir": str(merge_output_dir),
                "clean_output_dir": str(clean_output_dir) if self.corpus.key == "state_admin_rules" else None,
                "daemon_output_dir": str(self.output_dir),
                "jsonld_dir": str(jsonld_dir),
                "parquet_dir": str(parquet_dir),
                "combined_parquet": str(parquet_dir / canonical.combined_parquet_filename),
                "combined_embeddings": str(parquet_dir / canonical.combined_embeddings_filename),
            },
            "commands": rendered_commands,
        }

    def _release_command_templates(self) -> List[tuple[str, str]]:
        base_prefix = "cd {workspace_root} && PYTHONPATH=src {python_bin}"
        canonical_local_root = str(get_canonical_legal_corpus(self.corpus.key).default_local_root())

        if self.corpus.key == "state_laws":
            return [
                (
                    "merge",
                    base_prefix
                    + " scripts/ops/legal_data/merge_state_laws_runs.py"
                    + f' --input-root {shlex.quote(canonical_local_root)} --input-root data/state_laws --input-root artifacts --input-root /tmp --output-dir "{{merge_output_dir}}" {{merge_state_args}}',
                ),
                (
                    "parquet",
                    base_prefix
                    + ' scripts/ops/legal_data/convert_state_admin_jsonld_to_parquet_with_cid.py --input-dir "{jsonld_dir}" --output-dir "{parquet_dir}" --combined-filename "state_laws_all_states.parquet"',
                ),
                (
                    "embeddings",
                    base_prefix
                    + ' scripts/ops/legal_data/build_state_laws_embeddings_parquet_with_cid.py --input-dir "{parquet_dir}" --include-combined --overwrite',
                ),
            ]

        if self.corpus.key == "state_admin_rules":
            return [
                (
                    "merge_recovered_rows",
                    base_prefix
                    + ' scripts/ops/legal_data/merge_state_admin_recovered_rows.py "{daemon_output_dir}" --output-dir "{clean_output_dir}" --parquet-dir "{parquet_dir}"',
                ),
                (
                    "embeddings",
                    base_prefix
                    + ' scripts/ops/legal_data/build_state_admin_embeddings_parquet_with_cid.py --input-dir "{parquet_dir}" --include-combined --overwrite',
                ),
            ]

        return [
            (
                "merge",
                base_prefix
                + " scripts/ops/legal_data/merge_state_court_rules_runs.py"
                + f' --input-root {shlex.quote(canonical_local_root)} --input-root . --input-root /tmp --output-dir "{{merge_output_dir}}" {{merge_state_args}}',
            ),
            (
                "parquet",
                base_prefix
                + ' scripts/ops/legal_data/convert_state_court_rules_jsonld_to_parquet_with_cid.py --input-dir "{jsonld_dir}" --output-dir "{parquet_dir}" --combined-filename "state_court_rules_all_states.parquet"',
            ),
            (
                "embeddings",
                base_prefix
                + ' scripts/ops/legal_data/build_state_court_rules_embeddings_parquet_with_cid.py --input-dir "{parquet_dir}" --include-combined --overwrite',
            ),
        ]

    async def _run_release_command(self, *, command: str, cwd: Path, timeout_seconds: int) -> Dict[str, Any]:
        process = await asyncio.create_subprocess_shell(
            command,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=max(1, int(timeout_seconds or 1)))
        except asyncio.TimeoutError:
            process.kill()
            await process.communicate()
            return {
                "exit_code": -1,
                "stdout": "",
                "stderr": f"timed out after {timeout_seconds} seconds",
            }

        return {
            "exit_code": int(process.returncode or 0),
            "stdout": stdout.decode("utf-8", errors="replace")[-4000:],
            "stderr": stderr.decode("utf-8", errors="replace")[-4000:],
        }

    def _select_tactic(self) -> ScraperTacticProfile:
        return self._select_tactic_with_context()["profile"]

    def _priority_recommended_tactics(self, profiles: Dict[str, ScraperTacticProfile]) -> List[str]:
        state_action_plan = self._state.get("state_action_plan") or {}
        if not isinstance(state_action_plan, dict) or not state_action_plan:
            return []

        ordered_entries: List[tuple[int, str, Dict[str, Any]]] = []
        for state_code in list(self._state.get("priority_states") or []):
            normalized_state = str(state_code or "").upper().strip()
            entry = state_action_plan.get(normalized_state)
            if not isinstance(entry, dict):
                continue
            priority_score = int(entry.get("priority_score", 0) or 0)
            ordered_entries.append((priority_score, normalized_state, entry))

        ordered_entries.sort(key=lambda item: (-item[0], item[1]))

        prioritized: List[str] = []
        for priority_score, _state_code, entry in ordered_entries:
            if priority_score <= 0:
                continue
            for tactic_name in list(entry.get("recommended_tactics") or []):
                normalized_tactic = str(tactic_name or "").strip()
                if normalized_tactic in profiles and normalized_tactic not in prioritized:
                    prioritized.append(normalized_tactic)
        return prioritized

    def _select_tactic_with_context(self) -> Dict[str, Any]:
        profiles = self.config.tactic_profiles
        forced_tactic_name = str(self.config.forced_tactic_name or "").strip()
        if forced_tactic_name and forced_tactic_name in profiles:
            recent_issue_counts = self._recent_issue_counts()
            return {
                "profile": profiles[forced_tactic_name],
                "details": {
                    "mode": "forced",
                    "selected_tactic": forced_tactic_name,
                    "priority_recommended_tactics": self._priority_recommended_tactics(profiles),
                    "recommended_tactics": [
                        name for name in list(self._state.get("recommended_tactics") or []) if name in profiles
                    ],
                    "priority_states": list(self._state.get("priority_states") or []),
                    "recent_issue_counts": recent_issue_counts,
                    "score_breakdown": {
                        forced_tactic_name: {
                            "forced": True,
                        }
                    },
                },
            }
        recommended = [name for name in list(self._state.get("recommended_tactics") or []) if name in profiles]
        priority_recommended = self._priority_recommended_tactics(profiles)
        ordered_names = priority_recommended + recommended + [name for name in profiles if name not in priority_recommended and name not in recommended]
        recent_issue_counts = self._recent_issue_counts()

        stats = self._state.get("tactics") or {}
        untried = [name for name in ordered_names if int((stats.get(name) or {}).get("trials", 0) or 0) <= 0]
        if untried:
            selected_name = untried[0]
            mode = "priority_untried" if selected_name in priority_recommended else "untried"
            return {
                "profile": profiles[selected_name],
                "details": {
                    "mode": mode,
                    "selected_tactic": selected_name,
                    "priority_recommended_tactics": priority_recommended,
                    "recommended_tactics": recommended,
                    "priority_states": list(self._state.get("priority_states") or []),
                    "recent_issue_counts": recent_issue_counts,
                    "score_breakdown": {
                        selected_name: {
                            "untried_bonus": 1.0,
                        }
                    },
                },
            }

        if self._rand.random() < max(0.0, min(1.0, float(self.config.explore_probability or 0.0))):
            selected_name = min(
                ordered_names,
                key=lambda name: (
                    int((stats.get(name) or {}).get("trials", 0) or 0),
                    -float((stats.get(name) or {}).get("best_score", 0.0) or 0.0),
                ),
            )
            return {
                "profile": profiles[selected_name],
                "details": {
                    "mode": "explore",
                    "selected_tactic": selected_name,
                    "priority_recommended_tactics": priority_recommended,
                    "recommended_tactics": recommended,
                    "priority_states": list(self._state.get("priority_states") or []),
                    "recent_issue_counts": recent_issue_counts,
                    "score_breakdown": {
                        name: {
                            "trials": int((stats.get(name) or {}).get("trials", 0) or 0),
                            "best_score": float((stats.get(name) or {}).get("best_score", 0.0) or 0.0),
                        }
                        for name in ordered_names
                    },
                },
            }

        score_breakdown: Dict[str, Dict[str, Any]] = {}
        def _rank(name: str) -> float:
            entry = stats.get(name) or {}
            trials = max(1, int(entry.get("trials", 0) or 0))
            avg_score = float(entry.get("total_score", 0.0) or 0.0) / float(trials)
            best_score = float(entry.get("best_score", 0.0) or 0.0)
            recommendation_bonus = 0.03 if name in recommended else 0.0
            priority_bonus = self._tactic_priority_bonus(name)
            issue_pressure_bonus = self._tactic_issue_pressure_bonus(name)
            exploration_bonus = 0.04 / float(trials)
            stagnation_penalty = self._tactic_stagnation_penalty(name)
            score = (
                avg_score
                + (0.20 * best_score)
                + recommendation_bonus
                + priority_bonus
                + issue_pressure_bonus
                + exploration_bonus
                - stagnation_penalty
            )
            score_breakdown[name] = {
                "trials": trials,
                "avg_score": round(avg_score, 4),
                "best_score": round(best_score, 4),
                "recommendation_bonus": round(recommendation_bonus, 4),
                "priority_bonus": round(priority_bonus, 4),
                "issue_pressure_bonus": round(issue_pressure_bonus, 4),
                "exploration_bonus": round(exploration_bonus, 4),
                "stagnation_penalty": round(stagnation_penalty, 4),
                "rank_score": round(score, 4),
            }
            return score

        selected_name = max(ordered_names, key=_rank)
        return {
            "profile": profiles[selected_name],
            "details": {
                "mode": "exploit",
                "selected_tactic": selected_name,
                "priority_recommended_tactics": priority_recommended,
                "recommended_tactics": recommended,
                "priority_states": list(self._state.get("priority_states") or []),
                "recent_issue_counts": recent_issue_counts,
                "score_breakdown": score_breakdown,
            },
        }

    def _ordered_states_for_cycle(self) -> List[str]:
        priority_states = [
            str(item).upper().strip()
            for item in list(self._state.get("priority_states") or [])
            if str(item).strip()
        ]
        ordered: List[str] = []
        for state_code in priority_states + list(self.states):
            if state_code in self.states and state_code not in ordered:
                ordered.append(state_code)
        return ordered or list(self.states)

    def _normalize_cycle_states(self, states: Optional[Sequence[str]]) -> List[str]:
        normalized = [
            str(item).upper().strip()
            for item in list(states or [])
            if str(item).strip() and str(item).upper().strip() in self.states
        ]
        if normalized:
            return list(dict.fromkeys(normalized))
        return list(self.states)

    def _tactic_priority_bonus(self, tactic_name: str) -> float:
        state_action_plan = self._state.get("state_action_plan") or {}
        if not isinstance(state_action_plan, dict):
            return 0.0

        bonus = 0.0
        for state_code in list(self._state.get("priority_states") or []):
            entry = state_action_plan.get(str(state_code).upper().strip())
            if not isinstance(entry, dict):
                continue
            if tactic_name not in list(entry.get("recommended_tactics") or []):
                continue
            priority_score = int(entry.get("priority_score", 0) or 0)
            bonus += 0.03 * float(min(priority_score, 5))
        return min(0.18, bonus)

    @staticmethod
    def _issue_pressure_tactics(issue: str) -> List[str]:
        normalized = str(issue or "").strip().lower()
        if not normalized:
            return []
        if normalized.startswith("cloudflare-browser-challenge"):
            return ["cloudflare_explore", "router_assisted", "render_first", "document_first"]
        if normalized.startswith("cloudflare-rate-limited"):
            return ["archival_first", "router_assisted", "cloudflare_explore"]
        if normalized.startswith("document-recovery-stalled"):
            return ["render_first", "router_assisted", "document_first"]
        if normalized.startswith("document-recovery-ratio-low"):
            return ["document_first", "render_first", "router_assisted"]
        if normalized.startswith("document-prefetch-underperforming"):
            return ["archival_first", "router_assisted", "discovery_first"]
        if normalized.startswith(("document-candidate-gaps", "state-gap-analysis")) or normalized == "agentic-discovery-dominant":
            return ["document_first", "router_assisted", "render_first"]
        if normalized.startswith(("coverage-gaps", "no-attempt-states")) or normalized in {
            "common-crawl-unused-on-gap-cycle",
            "fallback-retry-dominant",
            "base-scrape-dominant",
        }:
            return ["archival_first", "discovery_first", "router_assisted"]
        if normalized in {"quality-weak", "kg-payload-low", "jsonld-legislation-low"}:
            return ["render_first", "precision_first", "router_assisted"]
        if normalized == "fetch-success-low":
            return ["render_first", "archival_first", "router_assisted"]
        return []

    def _tactic_issue_pressure_bonus(self, tactic_name: str) -> float:
        recent_cycles = list(self._state.get("recent_cycles") or [])
        if not recent_cycles:
            return 0.0

        bonus = 0.0
        for index, row in enumerate(recent_cycles[-4:], start=1):
            if not isinstance(row, dict):
                continue
            issues = [str(item).strip() for item in list(row.get("issues") or []) if str(item).strip()]
            if not issues:
                continue
            weight = 0.02 * float(index)
            for issue in issues:
                normalized_issue = str(issue or "").strip().lower()
                if tactic_name in self._issue_pressure_tactics(issue):
                    bonus += weight
                if normalized_issue.startswith("cloudflare-browser-challenge") and tactic_name == "cloudflare_explore":
                    bonus += 0.025 * float(index)
                if normalized_issue.startswith("cloudflare-rate-limited") and tactic_name == "archival_first":
                    bonus += 0.01 * float(index)
        return min(0.24, bonus)

    def _tactic_stagnation_penalty(self, tactic_name: str) -> float:
        recent_cycles = [
            row
            for row in list(self._state.get("recent_cycles") or [])
            if isinstance(row, dict) and str(row.get("tactic") or "") == tactic_name
        ]
        if len(recent_cycles) < 2:
            return 0.0

        window = recent_cycles[-2:]
        if any(bool(row.get("passed")) for row in window):
            return 0.0

        scores = [float(row.get("score", 0.0) or 0.0) for row in window]
        if max(scores) - min(scores) > 0.025:
            return 0.0

        issue_count = sum(len(list(row.get("issues") or [])) for row in window)
        if issue_count <= 0:
            return 0.0

        recommended = set(str(name).strip() for name in list(self._state.get("recommended_tactics") or []) if str(name).strip())
        return 0.05 if tactic_name in recommended else 0.08

    def _recent_issue_counts(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for row in list(self._state.get("recent_cycles") or [])[-6:]:
            if not isinstance(row, dict):
                continue
            for issue in list(row.get("issues") or []):
                normalized = str(issue).strip()
                if not normalized:
                    continue
                counts[normalized] = int(counts.get(normalized, 0) or 0) + 1
        return counts

    def _criticize_cycle(self, diagnostics: Dict[str, Any]) -> Dict[str, Any]:
        coverage = diagnostics.get("coverage") or {}
        fetch = diagnostics.get("fetch") or {}
        etl = diagnostics.get("etl_readiness") or {}
        quality = diagnostics.get("quality") or {}
        documents = diagnostics.get("documents") or {}
        gap_analysis = diagnostics.get("gap_analysis") or {}
        timing = diagnostics.get("timing") or {}
        state_action_plan = self._build_state_action_plan(diagnostics)

        issues: List[str] = []
        next_tactics: List[str] = []
        provider_summary = dict(fetch.get("providers") or {})

        coverage_gaps = list(coverage.get("coverage_gap_states") or [])
        if coverage_gaps:
            issues.append(f"coverage-gaps:{','.join(coverage_gaps[:8])}")
            next_tactics.extend(["archival_first", "discovery_first"])

        no_attempt_states = list(fetch.get("no_attempt_states") or [])
        if no_attempt_states:
            issues.append(f"no-attempt-states:{','.join(no_attempt_states[:8])}")
            next_tactics.extend(["archival_first", "discovery_first"])

        if float(fetch.get("success_ratio", 0.0) or 0.0) < 0.55:
            issues.append("fetch-success-low")
            next_tactics.extend(["render_first", "archival_first"])

        weak_quality = list(quality.get("weak_states") or [])
        if weak_quality:
            issues.append("quality-weak")
            next_tactics.extend(["render_first", "precision_first"])

        if float(etl.get("kg_payload_ratio", 0.0) or 0.0) < 0.70:
            issues.append("kg-payload-low")
            next_tactics.extend(["precision_first", "render_first"])

        if float(etl.get("jsonld_legislation_ratio", 0.0) or 0.0) < 0.70:
            issues.append("jsonld-legislation-low")
            next_tactics.extend(["precision_first", "discovery_first"])

        document_gap_states = list(documents.get("states_with_candidate_document_gaps") or [])
        if document_gap_states:
            issues.append(f"document-candidate-gaps:{','.join(document_gap_states[:8])}")
            next_tactics.extend(["document_first", "render_first", "discovery_first"])

        candidate_document_urls = int(documents.get("candidate_document_urls", 0) or 0)
        processed_document_urls = int(documents.get("processed_document_urls", 0) or 0)
        required_document_recovery_ratio = max(0.0, min(1.0, float(self.config.min_document_recovery_ratio or 0.0)))
        if candidate_document_urls > 0:
            document_recovery_ratio = float(processed_document_urls) / float(max(1, candidate_document_urls))
            if document_recovery_ratio < required_document_recovery_ratio:
                issues.append(
                    "document-recovery-ratio-low:"
                    f"{round(document_recovery_ratio, 3)}<{round(required_document_recovery_ratio, 3)}"
                )
                next_tactics.extend(["document_first", "render_first", "router_assisted"])

        stalled_recovery_states = [
            state_code
            for state_code, entry in state_action_plan.items()
            if "document_recovery_stalled" in list((entry or {}).get("reasons") or [])
        ]
        if stalled_recovery_states:
            issues.append(f"document-recovery-stalled:{','.join(stalled_recovery_states[:8])}")
            next_tactics.extend(["render_first", "router_assisted", "document_first"])

        weak_prefetch_states = [
            state_code
            for state_code, entry in state_action_plan.items()
            if "document_prefetch_underperforming" in list((entry or {}).get("reasons") or [])
        ]
        if weak_prefetch_states:
            issues.append(f"document-prefetch-underperforming:{','.join(weak_prefetch_states[:8])}")
            next_tactics.extend(["archival_first", "router_assisted", "discovery_first"])

        browser_challenge_states = [
            state_code
            for state_code, entry in state_action_plan.items()
            if "cloudflare_browser_challenge" in list((entry or {}).get("reasons") or [])
        ]
        if browser_challenge_states:
            issues.append(f"cloudflare-browser-challenge:{','.join(browser_challenge_states[:8])}")
            next_tactics.extend(["cloudflare_explore", "router_assisted", "render_first", "document_first"])

        cloudflare_rate_limited_states = [
            state_code
            for state_code, entry in state_action_plan.items()
            if "cloudflare_rate_limited" in list((entry or {}).get("reasons") or [])
        ]
        if cloudflare_rate_limited_states:
            issues.append(f"cloudflare-rate-limited:{','.join(cloudflare_rate_limited_states[:8])}")
            next_tactics.extend(["archival_first", "router_assisted", "cloudflare_explore"])

        weak_gap_states = list(gap_analysis.get("weak_states") or [])
        if weak_gap_states:
            issues.append(f"state-gap-analysis:{','.join(weak_gap_states[:8])}")
            next_tactics.extend(["discovery_first", "document_first", "router_assisted"])

        dominant_phase = str(timing.get("dominant_phase") or "").strip()
        if dominant_phase == "agentic_discovery_seconds":
            issues.append("agentic-discovery-dominant")
            next_tactics.extend(["document_first", "precision_first", "router_assisted"])
        elif dominant_phase == "fallback_retry_seconds":
            issues.append("fallback-retry-dominant")
            next_tactics.extend(["archival_first", "render_first", "router_assisted"])
        elif dominant_phase == "base_scrape_seconds" and no_attempt_states:
            issues.append("base-scrape-dominant")
            next_tactics.extend(["render_first", "discovery_first", "router_assisted"])

        if provider_summary and "common_crawl" not in provider_summary and coverage_gaps:
            issues.append("common-crawl-unused-on-gap-cycle")
            next_tactics.extend(["archival_first", "router_assisted"])

        if len(issues) >= 2:
            next_tactics.append("router_assisted")

        if not next_tactics:
            next_tactics.append("archival_first")

        deduped_tactics = list(dict.fromkeys([name for name in next_tactics if name in self.config.tactic_profiles]))
        priority_states = self._priority_states_from_action_plan(state_action_plan)
        query_hints: List[str] = []
        for state_code in priority_states:
            for hint in list((state_action_plan.get(state_code) or {}).get("query_hints") or []):
                normalized_hint = str(hint).strip()
                if normalized_hint and normalized_hint not in query_hints:
                    query_hints.append(normalized_hint)
        return {
            "issues": issues,
            "provider_summary": provider_summary,
            "recommended_next_tactics": deduped_tactics,
            "priority_states": priority_states,
            "state_action_plan": state_action_plan,
            "query_hints": query_hints,
            "summary": self._summarize_critic_issues(issues),
        }

    @staticmethod
    def _summarize_critic_issues(issues: List[str]) -> str:
        if not issues:
            return "Coverage and ETL signals are stable; continue exploiting the best-known tactic."
        if any(item.startswith("coverage-gaps") for item in issues):
            return "Coverage gaps remain, so the next cycle should bias toward broader archival and search discovery."
        if any(item.startswith("cloudflare-browser-challenge") for item in issues):
            return "Browser challenges are blocking weak states, so the next cycle should bias toward Cloudflare rendering, Playwright downloads, and router-guided fallback selection."
        if any(item.startswith("document-recovery-stalled") for item in issues):
            return "Document candidates are being found but recovery is stalling, so the next cycle should bias toward renderer-backed downloads and router-guided troubleshooting."
        if any(item.startswith("document-recovery-ratio-low") for item in issues):
            return "Document extraction throughput is below the configured threshold, so the next cycle should bias toward document-first tactics and renderer-backed recovery."
        if any(item.startswith("document-candidate-gaps") for item in issues):
            return "Document-heavy gaps remain, so the next cycle should bias toward Playwright downloads and processor-backed PDF/RTF extraction."
        if "quality-weak" in issues:
            return "Coverage exists, but extraction quality is weak; bias toward render and precision tactics next."
        if "fetch-success-low" in issues:
            return "Fetch reliability is weak; bias toward alternative archival providers and relocation search."
        return "Cycle surfaced mixed issues; continue exploring alternate tactics with provider diversity."

    async def _archive_candidate_urls(
        self,
        scrape_result: Dict[str, Any],
        diagnostics: Dict[str, Any],
        *,
        critic: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        max_urls = max(0, int(self.config.archive_warmup_urls or 0))
        if max_urls <= 0:
            return {"status": "skipped", "reason": "archive-warmup-disabled", "attempted": 0}

        urls = self._collect_candidate_urls(scrape_result, diagnostics, critic=critic, limit=max_urls)
        if not urls:
            return {"status": "skipped", "reason": "no-candidate-urls", "attempted": 0}

        try:
            from .parallel_web_archiver import ParallelWebArchiver
        except Exception as exc:
            return {"status": "skipped", "reason": f"parallel-archiver-unavailable:{exc}", "attempted": 0}

        try:
            archiver = ParallelWebArchiver(max_concurrent=max(1, int(self.config.archive_warmup_concurrency or 1)))
            cached_hits = []
            uncached_urls = []
            for url in urls:
                cached = self.url_archive_cache.get(url)
                if cached and cached.content:
                    cached_hits.append(
                        {
                            "url": cached.url,
                            "success": True,
                            "source": f"{cached.source}:cache",
                        }
                    )
                else:
                    uncached_urls.append(url)
            fetched_results = await archiver.archive_urls_parallel(uncached_urls) if uncached_urls else []
            for result in fetched_results:
                if bool(getattr(result, "success", False)) and str(getattr(result, "content", "") or "").strip():
                    await self.url_archive_cache.put(
                        url=str(getattr(result, "url", "") or ""),
                        content=str(getattr(result, "content", "") or ""),
                        source=str(getattr(result, "source", "") or "archive_warmup"),
                        metadata={"corpus": self.corpus.key, "warmup": True},
                    )
            results = cached_hits + fetched_results
        except Exception as exc:
            return {
                "status": "error",
                "reason": str(exc),
                "attempted": len(urls),
            }

        successful = [result for result in results if bool(getattr(result, "success", False))]
        by_source: Dict[str, int] = {}
        for result in successful:
            source = str(getattr(result, "source", "unknown") or "unknown")
            by_source[source] = int(by_source.get(source, 0) or 0) + 1

        return {
            "status": "success",
            "attempted": len(urls),
            "successful": len(successful),
            "failed": max(0, len(urls) - len(successful)),
            "sources": by_source,
        }

    def _collect_candidate_urls(
        self,
        scrape_result: Dict[str, Any],
        diagnostics: Dict[str, Any],
        *,
        critic: Optional[Dict[str, Any]] = None,
        limit: int,
    ) -> List[str]:
        coverage = diagnostics.get("coverage") or {}
        fetch = diagnostics.get("fetch") or {}
        weak_states = set(str(item).upper() for item in list(coverage.get("coverage_gap_states") or []))
        weak_states.update(str(item).upper() for item in list(fetch.get("no_attempt_states") or []))
        for row in list(fetch.get("weak_states") or []):
            if isinstance(row, dict):
                state = str(row.get("state") or "").upper()
                if state:
                    weak_states.add(state)

        urls: List[str] = []
        metadata = scrape_result.get("metadata") or {}
        agentic_report = metadata.get("agentic_report") or {}
        agentic_per_state = agentic_report.get("per_state") if isinstance(agentic_report, dict) else {}
        documents = diagnostics.get("documents") or {}
        document_gap_states = [
            str(item).upper().strip()
            for item in list(documents.get("states_with_candidate_document_gaps") or [])
            if str(item).strip()
        ]
        priority_states = [
            str(item).upper().strip()
            for item in list((critic or {}).get("priority_states") or [])
            if str(item).strip()
        ]
        state_order = list(dict.fromkeys(priority_states + document_gap_states + sorted(weak_states)))

        def _remember_url(value: Any) -> bool:
            url = str(value or "").strip()
            if not url or url in urls:
                return False
            urls.append(url)
            return len(urls) >= limit

        def _remember_state_report_urls(state_code: str) -> bool:
            if not isinstance(agentic_per_state, dict):
                return False
            state_report = agentic_per_state.get(state_code)
            if not isinstance(state_report, dict):
                return False
            candidate_urls = [str(item).strip() for item in list(state_report.get("top_candidate_urls") or []) if str(item).strip()]
            candidate_urls.sort(
                key=lambda value: (
                    0 if self._document_format_from_url(value) in {"pdf", "rtf"} else 1,
                    0 if self._document_format_from_url(value) == "pdf" else 1,
                    value,
                )
            )
            for value in candidate_urls:
                if _remember_url(value):
                    return True
            for value in list(state_report.get("seed_urls") or []):
                if _remember_url(value):
                    return True
            return False

        for state_code in state_order:
            if _remember_state_report_urls(state_code):
                return urls

        for block in list(scrape_result.get("data") or []):
            if not isinstance(block, dict):
                continue
            state_code = str(block.get("state_code") or "").upper()
            if state_order and state_code not in state_order:
                continue
            for statute in list(block.get("statutes") or []):
                if not isinstance(statute, dict):
                    continue
                if _remember_url(statute.get("source_url") or statute.get("sourceUrl")):
                    return urls

        if isinstance(agentic_per_state, dict):
            for state_code in sorted(set(agentic_per_state) - set(state_order)):
                if _remember_state_report_urls(state_code):
                    return urls
        return urls[:limit]

    def _update_state(self, *, tactic: ScraperTacticProfile, cycle_payload: Dict[str, Any]) -> None:
        self._state["cycle_count"] = int(self._state.get("cycle_count", 0) or 0) + 1
        self._state["last_cycle_at"] = cycle_payload.get("timestamp")
        self._state["corpus"] = self.corpus.key
        self._state["recommended_tactics"] = list((cycle_payload.get("critic") or {}).get("recommended_next_tactics") or [])
        self._state["priority_states"] = list((cycle_payload.get("critic") or {}).get("priority_states") or [])
        self._state["state_action_plan"] = dict((cycle_payload.get("critic") or {}).get("state_action_plan") or {})
        self._state["state_query_hints"] = self._next_state_query_hints(cycle_payload)
        self._state["last_tactic_selection"] = dict(cycle_payload.get("tactic_selection") or {})
        deferred_retry = cycle_payload.get("deferred_retry") or {}
        if isinstance(deferred_retry, dict) and str(deferred_retry.get("status") or "") == "scheduled":
            self._state["pending_retry"] = dict(deferred_retry)
            self._record_recent_cycle(tactic=tactic, cycle_payload=cycle_payload)
            self._write_pending_retry_artifact(cycle_payload)
            self.state_file.write_text(json.dumps(self._state, indent=2), encoding="utf-8")
            return
        self._state.pop("pending_retry", None)
        self._clear_pending_retry_artifact()

        tactics = self._state.setdefault("tactics", {})
        entry = tactics.setdefault(
            tactic.name,
            {"trials": 0, "total_score": 0.0, "best_score": 0.0, "last_score": 0.0, "passed_cycles": 0},
        )
        entry["trials"] = int(entry.get("trials", 0) or 0) + 1
        entry["total_score"] = float(entry.get("total_score", 0.0) or 0.0) + float(cycle_payload.get("critic_score", 0.0) or 0.0)
        entry["best_score"] = max(float(entry.get("best_score", 0.0) or 0.0), float(cycle_payload.get("critic_score", 0.0) or 0.0))
        entry["last_score"] = float(cycle_payload.get("critic_score", 0.0) or 0.0)
        if bool(cycle_payload.get("passed")):
            entry["passed_cycles"] = int(entry.get("passed_cycles", 0) or 0) + 1

        current_best = self._state.get("best_tactic") or {}
        if float(cycle_payload.get("critic_score", 0.0) or 0.0) >= float(current_best.get("score", 0.0) or 0.0):
            self._state["best_tactic"] = {
                "name": tactic.name,
                "score": float(cycle_payload.get("critic_score", 0.0) or 0.0),
                "cycle": int(cycle_payload.get("cycle", 0) or 0),
            }

        self._record_recent_cycle(tactic=tactic, cycle_payload=cycle_payload)
        self.state_file.write_text(json.dumps(self._state, indent=2), encoding="utf-8")

    def _record_recent_cycle(self, *, tactic: ScraperTacticProfile, cycle_payload: Dict[str, Any]) -> None:
        recent_cycles = list(self._state.get("recent_cycles") or [])
        critic = cycle_payload.get("critic") or {}
        diagnostics = cycle_payload.get("diagnostics") or {}
        documents = diagnostics.get("documents") or {}
        coverage = diagnostics.get("coverage") or {}
        recent_cycles.append(
            {
                "cycle": int(cycle_payload.get("cycle", 0) or 0),
                "tactic": tactic.name,
                "score": float(cycle_payload.get("critic_score", 0.0) or 0.0),
                "passed": bool(cycle_payload.get("passed")),
                "issues": [str(item) for item in list(critic.get("issues") or []) if str(item).strip()],
                "priority_states": [
                    str(item).upper().strip()
                    for item in list(critic.get("priority_states") or [])
                    if str(item).strip()
                ],
                "document_gap_states": [
                    str(item).upper().strip()
                    for item in list(documents.get("states_with_candidate_document_gaps") or [])
                    if str(item).strip()
                ],
                "coverage_gap_states": [
                    str(item).upper().strip()
                    for item in list(coverage.get("coverage_gap_states") or [])
                    if str(item).strip()
                ],
            }
        )
        self._state["recent_cycles"] = recent_cycles[-6:]

    def _write_pending_retry_artifact(self, cycle_payload: Dict[str, Any]) -> Optional[Path]:
        deferred_retry = cycle_payload.get("deferred_retry") or {}
        if not isinstance(deferred_retry, dict) or str(deferred_retry.get("status") or "") != "scheduled":
            return None
        cycle_index = int(cycle_payload.get("cycle", 0) or 0)
        cycle_path = self.cycles_dir / f"cycle_{cycle_index:04d}_pending_retry.json"
        payload = {
            "cycle": cycle_index,
            "timestamp": cycle_payload.get("timestamp"),
            "corpus": self.corpus.key,
            "states": list(cycle_payload.get("states") or self.states),
            "status": cycle_payload.get("status"),
            "pending_retry": dict(deferred_retry),
        }
        cycle_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        self.pending_retry_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return cycle_path

    def _clear_pending_retry_artifact(self) -> None:
        try:
            self.pending_retry_file.unlink(missing_ok=True)
        except Exception:
            pass

    def _next_cycle_delay_seconds(self, cycle: Dict[str, Any]) -> float:
        deferred_retry = cycle.get("deferred_retry") or {}
        if isinstance(deferred_retry, dict) and str(deferred_retry.get("status") or "") == "scheduled":
            retry_after_seconds = self._coerce_optional_float(deferred_retry.get("retry_after_seconds"))
            if retry_after_seconds is not None:
                return max(0.0, retry_after_seconds)
            retry_at_utc = self._normalize_retry_at_utc(deferred_retry.get("retry_at_utc"))
            if retry_at_utc:
                return self._seconds_until_utc(retry_at_utc)
        return max(0.0, float(self.config.cycle_interval_seconds or 0.0))

    def _log_cycle_followup(self, cycle: Dict[str, Any]) -> None:
        deferred_retry = cycle.get("deferred_retry") or {}
        if not isinstance(deferred_retry, dict) or str(deferred_retry.get("status") or "") != "scheduled":
            return
        provider = str(deferred_retry.get("provider") or "unknown")
        retry_at_utc = self._normalize_retry_at_utc(deferred_retry.get("retry_at_utc"))
        retry_after_seconds = self._coerce_optional_float(deferred_retry.get("retry_after_seconds"))
        logger.warning(
            "Deferred retry scheduled for %s: retry_after_seconds=%s retry_at_utc=%s reason=%s",
            provider,
            f"{retry_after_seconds:.1f}" if retry_after_seconds is not None else "unknown",
            retry_at_utc or "unknown",
            str(deferred_retry.get("reason") or "rate_limited"),
        )

    @staticmethod
    def _coerce_optional_float(value: Any) -> Optional[float]:
        if value is None or value == "":
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _normalize_retry_at_utc(value: Any) -> Optional[str]:
        text = str(value or "").strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat()

    @staticmethod
    def _seconds_until_utc(timestamp: str) -> float:
        normalized = StateLawsAgenticDaemon._normalize_retry_at_utc(timestamp)
        if not normalized:
            return 0.0
        parsed = datetime.fromisoformat(normalized)
        return max(0.0, (parsed - datetime.now(timezone.utc)).total_seconds())

    @staticmethod
    def _resolve_output_dir(output_dir: Optional[str], default_output_subdir: str) -> Path:
        if output_dir:
            return Path(output_dir).expanduser().resolve()
        return (Path.home() / ".ipfs_datasets" / default_output_subdir / "agentic_daemon").resolve()

    def _workspace_root(self) -> Path:
        configured = str(self.config.post_cycle_release.workspace_root or "").strip()
        if configured:
            return Path(configured).expanduser().resolve()
        return Path(__file__).resolve().parents[4]

    def _python_bin(self) -> Path:
        configured = str(self.config.post_cycle_release.python_bin or "").strip()
        if configured:
            return Path(configured).expanduser().resolve()

        workspace_root = self._workspace_root()
        venv_python = workspace_root / ".venv" / "bin" / "python"
        if venv_python.exists():
            return venv_python.resolve()
        return Path(sys.executable).resolve()

    def _load_state(self) -> Dict[str, Any]:
        if self.state_file.exists():
            try:
                payload = json.loads(self.state_file.read_text(encoding="utf-8"))
                if isinstance(payload, dict):
                    return payload
            except Exception:
                logger.warning("Failed to load daemon state from %s", self.state_file)
        return {
            "created_at": datetime.now().isoformat(),
            "cycle_count": 0,
            "recommended_tactics": [],
            "priority_states": [],
            "state_action_plan": {},
            "state_query_hints": {},
            "recent_cycles": [],
            "tactics": {},
            "best_tactic": {},
        }

    def _next_state_query_hints(self, cycle_payload: Dict[str, Any]) -> Dict[str, List[str]]:
        router_assist = cycle_payload.get("router_assist") or {}
        llm_review = router_assist.get("llm_review") if isinstance(router_assist, dict) else {}
        critic = cycle_payload.get("critic") or {}

        if isinstance(llm_review, dict):
            query_hints = [str(item).strip() for item in list(llm_review.get("query_hints") or []) if str(item).strip()]
            priority_states = [
                str(item).upper().strip()
                for item in list(llm_review.get("priority_states") or [])
                if str(item).strip()
            ]
            target_states = [state for state in priority_states if state in self.states] or list(self.states)
            if query_hints and target_states:
                return {state: list(query_hints) for state in target_states}

        state_action_plan = critic.get("state_action_plan") or {}
        if not isinstance(state_action_plan, dict) or not state_action_plan:
            return {}

        mapped: Dict[str, List[str]] = {}
        for state_code in list(critic.get("priority_states") or []):
            normalized_state = str(state_code).upper().strip()
            if normalized_state not in self.states:
                continue
            state_entry = state_action_plan.get(normalized_state) or {}
            state_hints = [str(item).strip() for item in list(state_entry.get("query_hints") or []) if str(item).strip()]
            if state_hints:
                mapped[normalized_state] = state_hints
        return mapped

    @staticmethod
    def _normalize_states(states: Sequence[str]) -> List[str]:
        normalized = [str(item).upper() for item in states if str(item).upper() in US_STATES]
        return normalized if normalized else list(US_STATES.keys())

    @staticmethod
    def _critic_score(diagnostics: Dict[str, Any]) -> float:
        coverage = diagnostics.get("coverage") or {}
        fetch = diagnostics.get("fetch") or {}
        etl = diagnostics.get("etl_readiness") or {}
        quality = diagnostics.get("quality") or {}
        documents = diagnostics.get("documents") or {}

        targeted = int(coverage.get("states_targeted", 0) or 0)
        nonzero = int(coverage.get("states_with_nonzero_statutes", 0) or 0)
        coverage_score = (float(nonzero) / float(targeted)) if targeted > 0 else 0.0

        full_text_ratio = float(etl.get("full_text_ratio", 0.0) or 0.0)
        jsonld_ratio = float(etl.get("jsonld_ratio", 0.0) or 0.0)
        jsonld_legislation_ratio = float(etl.get("jsonld_legislation_ratio", 0.0) or 0.0)
        kg_payload_ratio = float(etl.get("kg_payload_ratio", 0.0) or 0.0)
        citation_ratio = float(etl.get("citation_ratio", 0.0) or 0.0)
        statute_signal_ratio = float(etl.get("statute_signal_ratio", 0.0) or 0.0)
        non_scaffold_ratio = float(etl.get("non_scaffold_ratio", 0.0) or 0.0)
        etl_score = (
            (0.20 * full_text_ratio)
            + (0.20 * jsonld_ratio)
            + (0.15 * jsonld_legislation_ratio)
            + (0.15 * kg_payload_ratio)
            + (0.15 * statute_signal_ratio)
            + (0.10 * non_scaffold_ratio)
            + (0.05 * citation_ratio)
        )

        fetch_success_ratio = float(fetch.get("success_ratio", 0.0) or 0.0)
        fetch_attempted = int(fetch.get("attempted", 0) or 0)
        no_attempt_states = list(fetch.get("no_attempt_states") or [])
        no_attempt_penalty = (len(no_attempt_states) / max(1, targeted)) * 0.25
        fetch_score = max(0.0, fetch_success_ratio - no_attempt_penalty)

        if targeted > 0 and fetch_attempted <= 0:
            fetch_score = max(0.0, fetch_score - 0.35)

        weak_quality = list(quality.get("weak_states") or [])
        if weak_quality:
            risk_values: List[float] = []
            for row in weak_quality:
                if not isinstance(row, dict):
                    continue
                scaffold = float(row.get("scaffold_ratio", 0.0) or 0.0)
                nav_like = float(row.get("nav_like_ratio", 0.0) or 0.0)
                fallback = float(row.get("fallback_section_ratio", 0.0) or 0.0)
                risk_values.append((0.6 * scaffold) + (0.3 * nav_like) + (0.1 * fallback))
            quality_score = max(0.0, 1.0 - (sum(risk_values) / max(1, len(risk_values))))
        else:
            quality_score = 1.0

        score = (0.35 * coverage_score) + (0.40 * etl_score) + (0.15 * fetch_score) + (0.10 * quality_score)
        if bool(etl.get("ready_for_kg_etl")):
            score += 0.05

        candidate_document_urls = int(documents.get("candidate_document_urls", 0) or 0)
        processed_document_urls = int(documents.get("processed_document_urls", 0) or 0)
        if candidate_document_urls > 0:
            document_processing_ratio = min(1.0, float(processed_document_urls) / float(max(1, candidate_document_urls)))
            document_gap_ratio = float(len(list(documents.get("states_with_candidate_document_gaps") or []))) / float(max(1, targeted or 1))
            score = (0.94 * score) + (0.06 * document_processing_ratio)
            score -= 0.05 * document_gap_ratio

        if statute_signal_ratio > 0.0 and statute_signal_ratio < 0.65:
            score -= 0.08
        if non_scaffold_ratio > 0.0 and non_scaffold_ratio < 0.80:
            score -= 0.08
        if kg_payload_ratio > 0.0 and kg_payload_ratio < 0.65:
            score -= 0.06

        return round(max(0.0, min(1.0, score)), 4)

    def _is_success(self, diagnostics: Dict[str, Any], score: float) -> bool:
        coverage = diagnostics.get("coverage") or {}
        etl = diagnostics.get("etl_readiness") or {}
        fetch = diagnostics.get("fetch") or {}
        documents = diagnostics.get("documents") or {}

        coverage_gaps = list(coverage.get("coverage_gap_states") or [])
        no_attempt_states = list(fetch.get("no_attempt_states") or [])
        document_gap_states = list(documents.get("states_with_candidate_document_gaps") or [])

        full_text_ratio = float(etl.get("full_text_ratio", 0.0) or 0.0)
        jsonld_ratio = float(etl.get("jsonld_ratio", 0.0) or 0.0)
        jsonld_legislation_ratio = float(etl.get("jsonld_legislation_ratio", 0.0) or 0.0)
        kg_payload_ratio = float(etl.get("kg_payload_ratio", 0.0) or 0.0)
        statute_signal_ratio = float(etl.get("statute_signal_ratio", 0.0) or 0.0)
        non_scaffold_ratio = float(etl.get("non_scaffold_ratio", 0.0) or 0.0)

        candidate_document_urls = int(documents.get("candidate_document_urls", 0) or 0)
        processed_document_urls = int(documents.get("processed_document_urls", 0) or 0)
        required_document_recovery_ratio = max(0.0, min(1.0, float(self.config.min_document_recovery_ratio or 0.0)))
        document_recovery_ratio = (
            float(processed_document_urls) / float(max(1, candidate_document_urls))
            if candidate_document_urls > 0
            else 1.0
        )

        return bool(
            score >= float(self.config.target_score)
            and bool(etl.get("ready_for_kg_etl"))
            and full_text_ratio >= 0.85
            and jsonld_ratio >= 0.75
            and jsonld_legislation_ratio >= 0.70
            and kg_payload_ratio >= 0.70
            and statute_signal_ratio >= 0.70
            and non_scaffold_ratio >= 0.85
            and len(coverage_gaps) == 0
            and len(no_attempt_states) == 0
            and len(document_gap_states) == 0
            and document_recovery_ratio >= required_document_recovery_ratio
        )

    def _effective_scraper_method_order(self, tactic: ScraperTacticProfile) -> List[str]:
        method_order = list(tactic.scraper_method_order)
        if self.corpus.key == "state_admin_rules":
            return method_order

        cloudflare_summary = self._cloudflare_browser_rendering_availability()
        if not bool(cloudflare_summary.get("available")):
            return method_order

        cloudflare_method = "cloudflare_browser_rendering"
        if cloudflare_method in method_order:
            return method_order

        try:
            playwright_index = method_order.index("playwright")
        except ValueError:
            method_order.append(cloudflare_method)
        else:
            method_order.insert(playwright_index, cloudflare_method)
        return method_order

    @contextmanager
    def _tactic_env(self, tactic: ScraperTacticProfile) -> Iterable[None]:
        method_order_keys = [
            "IPFS_DATASETS_SCRAPER_METHOD_ORDER",
            "LEGAL_SCRAPER_METHOD_ORDER",
        ]
        search_engines = list(self.config.search_engines_override or tactic.search_engines)
        overrides = {
            "IPFS_DATASETS_SEARCH_ENGINES": ",".join(search_engines),
            "LEGAL_SCRAPER_SEARCH_ENGINES": ",".join(search_engines),
            "IPFS_DATASETS_SCRAPER_FALLBACK_ENABLED": "1",
            "LEGAL_SCRAPER_FALLBACK_ENABLED": "1",
            "IPFS_DATASETS_SEARCH_PARALLEL_ENABLED": "1" if tactic.search_parallel_enabled else "0",
            "IPFS_DATASETS_SEARCH_FALLBACK_ENABLED": "1" if tactic.search_fallback_enabled else "0",
            "IPFS_DATASETS_ARCHIVE_IS_SUBMIT_ON_MISS": "1" if tactic.archive_is_submit_on_miss else "0",
        }
        if self.corpus.key != "state_admin_rules":
            effective_method_order = self._effective_scraper_method_order(tactic)
            overrides.update(
                {
                    "IPFS_DATASETS_SCRAPER_METHOD_ORDER": ",".join(effective_method_order),
                    "LEGAL_SCRAPER_METHOD_ORDER": ",".join(effective_method_order),
                }
            )
        if tactic.llm_provider:
            overrides["IPFS_DATASETS_PY_LLM_PROVIDER"] = str(tactic.llm_provider)
        if tactic.embeddings_provider:
            overrides["IPFS_DATASETS_PY_EMBEDDINGS_PROVIDER"] = str(tactic.embeddings_provider)
        if tactic.ipfs_backend:
            overrides["IPFS_DATASETS_PY_IPFS_BACKEND"] = str(tactic.ipfs_backend)
        if tactic.enable_ipfs_accelerate is not None:
            overrides["IPFS_DATASETS_PY_ENABLE_IPFS_ACCELERATE"] = "1" if tactic.enable_ipfs_accelerate else "0"
        cloudflare_numeric_overrides = {
            "IPFS_DATASETS_CLOUDFLARE_CRAWL_TIMEOUT_SECONDS": tactic.cloudflare_timeout_seconds,
            "LEGAL_SCRAPER_CLOUDFLARE_CRAWL_TIMEOUT_SECONDS": tactic.cloudflare_timeout_seconds,
            "IPFS_DATASETS_CLOUDFLARE_CRAWL_POLL_INTERVAL_SECONDS": tactic.cloudflare_poll_interval_seconds,
            "LEGAL_SCRAPER_CLOUDFLARE_CRAWL_POLL_INTERVAL_SECONDS": tactic.cloudflare_poll_interval_seconds,
            "IPFS_DATASETS_CLOUDFLARE_CRAWL_MAX_RATE_LIMIT_WAIT_SECONDS": tactic.cloudflare_max_rate_limit_wait_seconds,
            "LEGAL_SCRAPER_CLOUDFLARE_CRAWL_MAX_RATE_LIMIT_WAIT_SECONDS": tactic.cloudflare_max_rate_limit_wait_seconds,
            "IPFS_DATASETS_CLOUDFLARE_CRAWL_LIMIT": tactic.cloudflare_limit,
            "LEGAL_SCRAPER_CLOUDFLARE_CRAWL_LIMIT": tactic.cloudflare_limit,
            "IPFS_DATASETS_CLOUDFLARE_CRAWL_DEPTH": tactic.cloudflare_depth,
            "LEGAL_SCRAPER_CLOUDFLARE_CRAWL_DEPTH": tactic.cloudflare_depth,
        }
        for key, value in cloudflare_numeric_overrides.items():
            if value is not None:
                overrides[key] = str(value)
        cloudflare_bool_overrides = {
            "IPFS_DATASETS_CLOUDFLARE_CRAWL_RENDER": tactic.cloudflare_render,
            "LEGAL_SCRAPER_CLOUDFLARE_CRAWL_RENDER": tactic.cloudflare_render,
            "IPFS_DATASETS_CLOUDFLARE_CRAWL_INCLUDE_EXTERNAL_LINKS": tactic.cloudflare_include_external_links,
            "LEGAL_SCRAPER_CLOUDFLARE_CRAWL_INCLUDE_EXTERNAL_LINKS": tactic.cloudflare_include_external_links,
            "IPFS_DATASETS_CLOUDFLARE_CRAWL_INCLUDE_SUBDOMAINS": tactic.cloudflare_include_subdomains,
            "LEGAL_SCRAPER_CLOUDFLARE_CRAWL_INCLUDE_SUBDOMAINS": tactic.cloudflare_include_subdomains,
        }
        for key, value in cloudflare_bool_overrides.items():
            if value is not None:
                overrides[key] = "1" if value else "0"
        if tactic.cloudflare_source:
            overrides["IPFS_DATASETS_CLOUDFLARE_CRAWL_SOURCE"] = str(tactic.cloudflare_source)
            overrides["LEGAL_SCRAPER_CLOUDFLARE_CRAWL_SOURCE"] = str(tactic.cloudflare_source)
        if tactic.cloudflare_formats:
            serialized_formats = ",".join(str(item).strip() for item in tactic.cloudflare_formats if str(item).strip())
            if serialized_formats:
                overrides["IPFS_DATASETS_CLOUDFLARE_CRAWL_FORMATS"] = serialized_formats
                overrides["LEGAL_SCRAPER_CLOUDFLARE_CRAWL_FORMATS"] = serialized_formats
        cloudflare_credentials = self._resolve_cloudflare_credential_values()
        if cloudflare_credentials.get("account_id"):
            overrides["IPFS_DATASETS_CLOUDFLARE_ACCOUNT_ID"] = str(cloudflare_credentials["account_id"])
            overrides["LEGAL_SCRAPER_CLOUDFLARE_ACCOUNT_ID"] = str(cloudflare_credentials["account_id"])
            overrides["CLOUDFLARE_ACCOUNT_ID"] = str(cloudflare_credentials["account_id"])
        if cloudflare_credentials.get("api_token"):
            overrides["IPFS_DATASETS_CLOUDFLARE_API_TOKEN"] = str(cloudflare_credentials["api_token"])
            overrides["LEGAL_SCRAPER_CLOUDFLARE_API_TOKEN"] = str(cloudflare_credentials["api_token"])
            overrides["CLOUDFLARE_API_TOKEN"] = str(cloudflare_credentials["api_token"])
        state_query_hints = self._state.get("state_query_hints") or {}
        if isinstance(state_query_hints, dict) and state_query_hints:
            try:
                overrides["LEGAL_SCRAPER_QUERY_HINTS_JSON"] = json.dumps(state_query_hints, ensure_ascii=False, sort_keys=True)
            except Exception:
                pass
        managed_keys = set(overrides)
        if self.corpus.key == "state_admin_rules":
            managed_keys.update(method_order_keys)
        previous = {key: os.environ.get(key) for key in managed_keys}
        try:
            if self.corpus.key == "state_admin_rules":
                for key in method_order_keys:
                    os.environ.pop(key, None)
            for key, value in overrides.items():
                os.environ[key] = value
            yield
        finally:
            for key, old_value in previous.items():
                if old_value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = old_value


async def run_state_laws_agentic_daemon(
    *,
    states: Optional[Sequence[str]] = None,
    output_dir: Optional[str] = None,
    cycle_interval_seconds: float = 900.0,
    max_cycles: int = 0,
    max_statutes: int = 0,
    explore_probability: float = 0.30,
    archive_warmup_urls: int = 25,
    per_state_timeout_seconds: float = 86400.0,
    router_llm_timeout_seconds: float = 20.0,
    router_embeddings_timeout_seconds: float = 10.0,
    router_ipfs_timeout_seconds: float = 10.0,
    min_document_recovery_ratio: float = 0.0,
    stop_after_recovered_rows: bool = False,
    target_score: float = 0.92,
    stop_on_target_score: bool = False,
    random_seed: Optional[int] = None,
    post_cycle_release_enabled: bool = False,
    post_cycle_release_dry_run: bool = False,
    post_cycle_release_min_score: Optional[float] = None,
    post_cycle_release_require_passed: bool = True,
    post_cycle_release_timeout_seconds: int = 7200,
    post_cycle_release_workspace_root: Optional[str] = None,
    post_cycle_release_python_bin: Optional[str] = None,
    post_cycle_release_publish_command: Optional[str] = None,
) -> Dict[str, Any]:
    """Convenience entrypoint for the state-law agentic daemon."""
    daemon = StateLawsAgenticDaemon(
        StateLawsAgenticDaemonConfig(
            corpus_key="state_laws",
            states=list(states or list(US_STATES.keys())),
            output_dir=output_dir,
            cycle_interval_seconds=cycle_interval_seconds,
            max_cycles=max_cycles,
            max_statutes=max_statutes,
            explore_probability=explore_probability,
            archive_warmup_urls=archive_warmup_urls,
            per_state_timeout_seconds=per_state_timeout_seconds,
            router_llm_timeout_seconds=router_llm_timeout_seconds,
            router_embeddings_timeout_seconds=router_embeddings_timeout_seconds,
            router_ipfs_timeout_seconds=router_ipfs_timeout_seconds,
            min_document_recovery_ratio=min_document_recovery_ratio,
            stop_after_recovered_rows=stop_after_recovered_rows,
            target_score=target_score,
            stop_on_target_score=stop_on_target_score,
            random_seed=random_seed,
            post_cycle_release=PostCycleReleaseConfig(
                enabled=post_cycle_release_enabled,
                dry_run=post_cycle_release_dry_run,
                min_score=post_cycle_release_min_score,
                require_passed=post_cycle_release_require_passed,
                timeout_seconds=post_cycle_release_timeout_seconds,
                workspace_root=post_cycle_release_workspace_root,
                python_bin=post_cycle_release_python_bin,
                publish_command=post_cycle_release_publish_command,
            ),
        )
    )
    return await daemon.run()


async def run_state_admin_rules_agentic_daemon(
    *,
    states: Optional[Sequence[str]] = None,
    output_dir: Optional[str] = None,
    cycle_interval_seconds: float = 900.0,
    max_cycles: int = 0,
    max_statutes: int = 0,
    explore_probability: float = 0.30,
    archive_warmup_urls: int = 25,
    per_state_timeout_seconds: float = 86400.0,
    router_llm_timeout_seconds: float = 20.0,
    router_embeddings_timeout_seconds: float = 10.0,
    router_ipfs_timeout_seconds: float = 10.0,
    min_document_recovery_ratio: float = 0.0,
    admin_agentic_max_candidates_per_state: Optional[int] = 1000,
    admin_agentic_max_fetch_per_state: Optional[int] = 1000,
    admin_agentic_max_results_per_domain: Optional[int] = 1000,
    admin_agentic_max_hops: Optional[int] = 4,
    admin_agentic_max_pages: Optional[int] = 1000,
    admin_agentic_fetch_concurrency: Optional[int] = None,
    admin_parallel_assist_enabled: bool = True,
    admin_parallel_assist_state_limit: int = 6,
    admin_parallel_assist_max_urls_per_domain: int = 20,
    admin_parallel_assist_timeout_seconds: float = 86400.0,
    stop_after_recovered_rows: bool = False,
    target_score: float = 0.92,
    stop_on_target_score: bool = False,
    random_seed: Optional[int] = None,
    post_cycle_release_enabled: bool = False,
    post_cycle_release_dry_run: bool = False,
    post_cycle_release_min_score: Optional[float] = None,
    post_cycle_release_require_passed: bool = True,
    post_cycle_release_timeout_seconds: int = 7200,
    post_cycle_release_workspace_root: Optional[str] = None,
    post_cycle_release_python_bin: Optional[str] = None,
    post_cycle_release_publish_command: Optional[str] = None,
) -> Dict[str, Any]:
    daemon = StateLawsAgenticDaemon(
        StateLawsAgenticDaemonConfig(
            corpus_key="state_admin_rules",
            states=list(states or list(US_STATES.keys())),
            output_dir=output_dir,
            cycle_interval_seconds=cycle_interval_seconds,
            max_cycles=max_cycles,
            max_statutes=max_statutes,
            explore_probability=explore_probability,
            archive_warmup_urls=archive_warmup_urls,
            per_state_timeout_seconds=per_state_timeout_seconds,
            router_llm_timeout_seconds=router_llm_timeout_seconds,
            router_embeddings_timeout_seconds=router_embeddings_timeout_seconds,
            router_ipfs_timeout_seconds=router_ipfs_timeout_seconds,
            min_document_recovery_ratio=min_document_recovery_ratio,
            admin_agentic_max_candidates_per_state=admin_agentic_max_candidates_per_state,
            admin_agentic_max_fetch_per_state=admin_agentic_max_fetch_per_state,
            admin_agentic_max_results_per_domain=admin_agentic_max_results_per_domain,
            admin_agentic_max_hops=admin_agentic_max_hops,
            admin_agentic_max_pages=admin_agentic_max_pages,
            admin_agentic_fetch_concurrency=admin_agentic_fetch_concurrency,
            admin_parallel_assist_enabled=admin_parallel_assist_enabled,
            admin_parallel_assist_state_limit=admin_parallel_assist_state_limit,
            admin_parallel_assist_max_urls_per_domain=admin_parallel_assist_max_urls_per_domain,
            admin_parallel_assist_timeout_seconds=admin_parallel_assist_timeout_seconds,
            stop_after_recovered_rows=stop_after_recovered_rows,
            target_score=target_score,
            stop_on_target_score=stop_on_target_score,
            random_seed=random_seed,
            post_cycle_release=PostCycleReleaseConfig(
                enabled=post_cycle_release_enabled,
                dry_run=post_cycle_release_dry_run,
                min_score=post_cycle_release_min_score,
                require_passed=post_cycle_release_require_passed,
                timeout_seconds=post_cycle_release_timeout_seconds,
                workspace_root=post_cycle_release_workspace_root,
                python_bin=post_cycle_release_python_bin,
                publish_command=post_cycle_release_publish_command,
            ),
        )
    )
    return await daemon.run()


async def run_state_court_rules_agentic_daemon(
    *,
    states: Optional[Sequence[str]] = None,
    output_dir: Optional[str] = None,
    cycle_interval_seconds: float = 900.0,
    max_cycles: int = 0,
    max_statutes: int = 0,
    explore_probability: float = 0.30,
    archive_warmup_urls: int = 25,
    per_state_timeout_seconds: float = 86400.0,
    router_llm_timeout_seconds: float = 20.0,
    router_embeddings_timeout_seconds: float = 10.0,
    router_ipfs_timeout_seconds: float = 10.0,
    min_document_recovery_ratio: float = 0.0,
    stop_after_recovered_rows: bool = False,
    target_score: float = 0.92,
    stop_on_target_score: bool = False,
    random_seed: Optional[int] = None,
    post_cycle_release_enabled: bool = False,
    post_cycle_release_dry_run: bool = False,
    post_cycle_release_min_score: Optional[float] = None,
    post_cycle_release_require_passed: bool = True,
    post_cycle_release_timeout_seconds: int = 7200,
    post_cycle_release_workspace_root: Optional[str] = None,
    post_cycle_release_python_bin: Optional[str] = None,
    post_cycle_release_publish_command: Optional[str] = None,
) -> Dict[str, Any]:
    daemon = StateLawsAgenticDaemon(
        StateLawsAgenticDaemonConfig(
            corpus_key="state_court_rules",
            states=list(states or list(US_STATES.keys())),
            output_dir=output_dir,
            cycle_interval_seconds=cycle_interval_seconds,
            max_cycles=max_cycles,
            max_statutes=max_statutes,
            explore_probability=explore_probability,
            archive_warmup_urls=archive_warmup_urls,
            per_state_timeout_seconds=per_state_timeout_seconds,
            router_llm_timeout_seconds=router_llm_timeout_seconds,
            router_embeddings_timeout_seconds=router_embeddings_timeout_seconds,
            router_ipfs_timeout_seconds=router_ipfs_timeout_seconds,
            min_document_recovery_ratio=min_document_recovery_ratio,
            stop_after_recovered_rows=stop_after_recovered_rows,
            target_score=target_score,
            stop_on_target_score=stop_on_target_score,
            random_seed=random_seed,
            post_cycle_release=PostCycleReleaseConfig(
                enabled=post_cycle_release_enabled,
                dry_run=post_cycle_release_dry_run,
                min_score=post_cycle_release_min_score,
                require_passed=post_cycle_release_require_passed,
                timeout_seconds=post_cycle_release_timeout_seconds,
                workspace_root=post_cycle_release_workspace_root,
                python_bin=post_cycle_release_python_bin,
                publish_command=post_cycle_release_publish_command,
            ),
        )
    )
    return await daemon.run()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the canonical legal-corpus agentic scraper daemon.")
    parser.add_argument(
        "--corpus",
        default="state_laws",
        choices=sorted(_corpus_definitions().keys()),
        help="Canonical corpus to optimize.",
    )
    parser.add_argument("--states", default="all", help="Comma-separated state codes, or 'all'.")
    parser.add_argument("--output-dir", default=None, help="Directory for daemon cycle artifacts.")
    parser.add_argument("--cycle-interval-seconds", type=float, default=900.0, help="Sleep interval between daemon cycles.")
    parser.add_argument("--max-cycles", type=int, default=0, help="Maximum number of cycles to run. 0 means forever.")
    parser.add_argument("--max-statutes", type=int, default=0, help="Optional per-run statute cap for debug cycles.")
    parser.add_argument("--explore-probability", type=float, default=0.30, help="Exploration probability for tactic selection.")
    parser.add_argument("--archive-warmup-urls", type=int, default=25, help="Number of weak-state URLs to archive after each cycle.")
    parser.add_argument("--per-state-timeout-seconds", type=float, default=86400.0, help="Timeout budget for each individual state scrape.")
    parser.add_argument("--scrape-timeout-seconds", type=float, default=0.0, help="Optional timeout budget for the full corpus scrape stage. 0 disables the outer scrape timeout.")
    parser.add_argument("--router-llm-timeout-seconds", type=float, default=20.0, help="Timeout budget for router-backed LLM review during each cycle.")
    parser.add_argument("--router-embeddings-timeout-seconds", type=float, default=10.0, help="Timeout budget for router-backed embeddings ranking during each cycle.")
    parser.add_argument("--router-ipfs-timeout-seconds", type=float, default=10.0, help="Timeout budget for persisting router-assist artifacts to IPFS.")
    parser.add_argument("--min-document-recovery-ratio", type=float, default=0.0, help="Optional minimum processed/(candidate PDF+RTF URLs) ratio required for pass criteria when candidate document URLs are present.")
    parser.add_argument("--admin-agentic-max-candidates-per-state", type=int, default=1000, help="Optional state-admin-rules candidate cap passed through to the agentic fallback.")
    parser.add_argument("--admin-agentic-max-fetch-per-state", type=int, default=1000, help="Optional state-admin-rules fetch cap passed through to the agentic fallback.")
    parser.add_argument("--admin-agentic-max-results-per-domain", type=int, default=1000, help="Optional state-admin-rules per-domain result cap passed through to the agentic fallback.")
    parser.add_argument("--admin-agentic-max-hops", type=int, default=4, help="Optional state-admin-rules traversal hop limit passed through to the agentic fallback.")
    parser.add_argument("--admin-agentic-max-pages", type=int, default=1000, help="Optional state-admin-rules page limit passed through to the agentic fallback.")
    parser.add_argument("--admin-agentic-fetch-concurrency", type=int, default=None, help="Optional state-admin-rules fetch concurrency passed through to the agentic fallback.")
    parser.add_argument("--admin-parallel-assist-enabled", action=argparse.BooleanOptionalAction, default=True, help="Enable the state-admin parallel supplemental discovery pass for weak states during each daemon cycle.")
    parser.add_argument("--admin-parallel-assist-state-limit", type=int, default=6, help="Maximum number of weak state-admin targets to send through the parallel assist pass each cycle.")
    parser.add_argument("--admin-parallel-assist-max-urls-per-domain", type=int, default=20, help="Maximum URLs per domain evaluated by the parallel state-admin assist pass.")
    parser.add_argument("--admin-parallel-assist-timeout-seconds", type=float, default=86400.0, help="Per-state timeout budget for the parallel state-admin assist pass.")
    parser.add_argument("--stop-after-recovered-rows", action="store_true", help="Finalize the daemon cycle immediately after recovered row artifacts are written.")
    parser.add_argument("--search-engines", default=None, help="Optional comma-separated search engine override for daemon tactics, e.g. duckduckgo.")
    parser.add_argument("--tactic", default=None, help="Force one tactic profile for every daemon cycle, e.g. document_first.")
    parser.add_argument("--target-score", type=float, default=0.92, help="Critic score threshold for convergence.")
    parser.add_argument("--stop-on-target-score", action="store_true", help="Stop once the daemon reaches the target critic score.")
    parser.add_argument("--random-seed", type=int, default=None, help="Optional deterministic seed for tactic selection.")
    parser.add_argument("--post-cycle-release", action="store_true", help="Run canonical merge/parquet/embed automation after a qualifying cycle.")
    parser.add_argument("--print-post-cycle-release-plan", action="store_true", help="Print the post-cycle release command plan without running a scrape cycle.")
    parser.add_argument("--post-cycle-release-dry-run", action="store_true", help="Plan post-cycle release commands without executing them.")
    parser.add_argument("--post-cycle-release-min-score", type=float, default=None, help="Optional minimum critic score required before running post-cycle release.")
    parser.add_argument("--post-cycle-release-ignore-pass", action="store_true", help="Allow post-cycle release even if the cycle does not meet the pass criteria.")
    parser.add_argument("--post-cycle-release-timeout-seconds", type=int, default=7200, help="Per-stage timeout for live post-cycle release commands.")
    parser.add_argument("--post-cycle-release-workspace-root", default=None, help="Workspace root used when resolving legal-data ops scripts.")
    parser.add_argument("--post-cycle-release-python-bin", default=None, help="Python interpreter used for post-cycle release commands.")
    parser.add_argument("--post-cycle-release-publish-command", default=None, help="Optional publish command template appended after merge/parquet/embed.")
    parser.add_argument("--post-cycle-release-preview-score", type=float, default=None, help="Critic score to stamp into a scrape-free release plan preview.")
    parser.add_argument("--post-cycle-release-preview-cycle", type=int, default=1, help="Cycle number to stamp into a scrape-free release plan preview.")
    parser.add_argument("--print-runtime-readiness", action="store_true", help="Print Cloudflare/router/IPFS readiness without running a scrape cycle.")
    parser.add_argument("--probe-cloudflare-browser-rendering", action="store_true", help="Run a live Cloudflare Browser Rendering auth probe without starting the daemon.")
    parser.add_argument("--probe-cloudflare-url", default="https://example.com", help="URL submitted during the live Cloudflare Browser Rendering probe.")
    return parser


def _parse_states_arg(value: str) -> List[str]:
    raw = str(value or "all").strip()
    if not raw or raw.lower() == "all":
        return list(US_STATES.keys())
    return [item.strip().upper() for item in raw.split(",") if item.strip()]


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    daemon: Optional[StateLawsAgenticDaemon] = None
    previous_handlers: Dict[int, Any] = {}

    def _restore_signal_handlers() -> None:
        for sig, previous in previous_handlers.items():
            try:
                signal.signal(sig, previous)
            except Exception:
                pass

    try:
        states = _parse_states_arg(args.states)
        daemon = StateLawsAgenticDaemon(
            StateLawsAgenticDaemonConfig(
                corpus_key=str(args.corpus),
                states=states,
                output_dir=args.output_dir,
                cycle_interval_seconds=float(args.cycle_interval_seconds),
                max_cycles=int(args.max_cycles),
                max_statutes=int(args.max_statutes),
                explore_probability=float(args.explore_probability),
                archive_warmup_urls=int(args.archive_warmup_urls),
                per_state_timeout_seconds=float(args.per_state_timeout_seconds),
                scrape_timeout_seconds=float(args.scrape_timeout_seconds),
                router_llm_timeout_seconds=float(args.router_llm_timeout_seconds),
                router_embeddings_timeout_seconds=float(args.router_embeddings_timeout_seconds),
                router_ipfs_timeout_seconds=float(args.router_ipfs_timeout_seconds),
                min_document_recovery_ratio=float(args.min_document_recovery_ratio),
                admin_agentic_max_candidates_per_state=args.admin_agentic_max_candidates_per_state,
                admin_agentic_max_fetch_per_state=args.admin_agentic_max_fetch_per_state,
                admin_agentic_max_results_per_domain=args.admin_agentic_max_results_per_domain,
                admin_agentic_max_hops=args.admin_agentic_max_hops,
                admin_agentic_max_pages=args.admin_agentic_max_pages,
                admin_agentic_fetch_concurrency=args.admin_agentic_fetch_concurrency,
                admin_parallel_assist_enabled=bool(args.admin_parallel_assist_enabled),
                admin_parallel_assist_state_limit=int(args.admin_parallel_assist_state_limit),
                admin_parallel_assist_max_urls_per_domain=int(args.admin_parallel_assist_max_urls_per_domain),
                admin_parallel_assist_timeout_seconds=float(args.admin_parallel_assist_timeout_seconds),
                stop_after_recovered_rows=bool(args.stop_after_recovered_rows),
                search_engines_override=[
                    item.strip()
                    for item in str(args.search_engines or "").split(",")
                    if item.strip()
                ]
                or None,
                forced_tactic_name=args.tactic,
                target_score=float(args.target_score),
                stop_on_target_score=bool(args.stop_on_target_score),
                random_seed=args.random_seed,
                post_cycle_release=PostCycleReleaseConfig(
                    enabled=bool(args.post_cycle_release),
                    dry_run=bool(args.post_cycle_release_dry_run),
                    min_score=args.post_cycle_release_min_score,
                    require_passed=not bool(args.post_cycle_release_ignore_pass),
                    timeout_seconds=int(args.post_cycle_release_timeout_seconds),
                    workspace_root=args.post_cycle_release_workspace_root,
                    python_bin=args.post_cycle_release_python_bin,
                    publish_command=args.post_cycle_release_publish_command,
                ),
            )
        )

        def _handle_termination(signum: int, _frame: Any) -> None:
            signal_name = getattr(signal.Signals(signum), "name", str(signum))
            if daemon is not None:
                daemon.promote_latest_checkpoint_to_summary(reason=f"signal:{signal_name}")
            raise SystemExit(128 + int(signum))

        for sig in (signal.SIGTERM, signal.SIGINT):
            previous_handlers[sig] = signal.getsignal(sig)
            signal.signal(sig, _handle_termination)

        if bool(args.print_runtime_readiness):
            result = daemon.preview_runtime_readiness()
        elif bool(args.probe_cloudflare_browser_rendering):
            result = asyncio.run(
                daemon.probe_cloudflare_browser_rendering(
                    url=str(args.probe_cloudflare_url or "https://example.com").strip() or "https://example.com"
                )
            )
        elif bool(args.print_post_cycle_release_plan):
            result = daemon.preview_post_cycle_release_plan(
                cycle_index=max(1, int(args.post_cycle_release_preview_cycle)),
                critic_score=args.post_cycle_release_preview_score,
            )
        else:
            result = asyncio.run(daemon.run())
        _restore_signal_handlers()
    except KeyboardInterrupt:
        if daemon is not None:
            daemon.promote_latest_checkpoint_to_summary(reason="keyboard_interrupt")
        _restore_signal_handlers()
        return 130
    except SystemExit as exc:
        if daemon is not None:
            code = exc.code if isinstance(exc.code, int) else 1
            if code not in (0, None):
                daemon.promote_latest_checkpoint_to_summary(reason=f"system_exit:{code}")
        _restore_signal_handlers()
        raise
    except Exception as exc:
        _restore_signal_handlers()
        result = {
            "status": "error",
            "error": str(exc),
            "exception_type": type(exc).__name__,
            "traceback": traceback.format_exc(),
        }
        print(json.dumps(result, indent=2), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
