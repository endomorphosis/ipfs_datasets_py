#!/usr/bin/env python3
"""Discover state admin-rule source URLs and emit KG-ready ETL corpus.

This script uses the legal web-archive search stack to discover likely
state administrative rule/code sources for selected states, then fetches a
small text snapshot for each candidate URL and writes a corpus JSONL suitable
for downstream knowledge-graph ETL.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence
from urllib.parse import urljoin, urlparse

from ipfs_datasets_py.processors.legal_scrapers.legal_web_archive_search import (
    LegalWebArchiveSearch,
)
from ipfs_datasets_py.processors.legal_scrapers.state_admin_rules_scraper import (
    _STATE_ADMIN_SOURCE_MAP,
    _is_non_admin_seed_url,
    US_50_STATE_CODES,
)
from ipfs_datasets_py.processors.legal_scrapers.state_laws_scraper import (
    US_STATES,
    _get_official_state_url,
)
from ipfs_datasets_py.processors.web_archiving.unified_web_scraper import (
    ScraperConfig,
    ScraperMethod,
    UnifiedWebScraper,
)

ADMIN_URL_HINT_RE = re.compile(
    r"administrative|admin[-_/ ]?code|code[-_/ ]of[-_/ ]regulations|regulations?|rules?",
    re.IGNORECASE,
)


@dataclass
class Candidate:
    state_code: str
    query: str
    url: str
    source: str
    score: int


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Discover state admin-rule sources and emit ETL corpus")
    p.add_argument("--states", nargs="*", default=["auto-zero"], help="State codes or auto-zero")
    p.add_argument(
        "--summary-json",
        default="/tmp/state_admin_rules_all_20260305_131935_fixed/final_summary.json",
        help="Summary JSON used when --states auto-zero",
    )
    p.add_argument("--max-results-per-domain", type=int, default=30)
    p.add_argument("--max-candidates-per-state", type=int, default=20)
    p.add_argument("--max-fetch-per-state", type=int, default=5)
    p.add_argument(
        "--output-dir",
        default=str(Path.home() / ".ipfs_datasets" / "state_admin_rules" / "discovery"),
    )
    return p.parse_args()


def _select_states(args: argparse.Namespace) -> List[str]:
    states = [s.upper() for s in args.states]
    if states and states != ["AUTO-ZERO"]:
        return [s for s in states if s in set(US_50_STATE_CODES)]

    summary_path = Path(args.summary_json)
    if summary_path.exists():
        data = json.loads(summary_path.read_text(encoding="utf-8"))
        meta = data.get("metadata") or {}
        zero_states = [str(s).upper() for s in (meta.get("zero_rule_states") or [])]
        if zero_states:
            return [s for s in zero_states if s in set(US_50_STATE_CODES)]

    return list(US_50_STATE_CODES)


def _domains_for_state(state_code: str) -> List[str]:
    low = state_code.lower()
    # Domain patterns that frequently host state administrative code content.
    return [
        f"{low}.gov",
        f"state.{low}.us",
        f"admincode.{low}.gov",
        "legis.state.us",
        "rules.state.us",
    ]


def _query_for_state(state_code: str) -> str:
    state_name = US_STATES.get(state_code, state_code)
    return f"{state_name} administrative code regulations rules"


def _score_url(url: str) -> int:
    if _is_non_admin_seed_url(url):
        return -100
    score = 0
    u = url.lower()
    if ADMIN_URL_HINT_RE.search(u):
        score += 3
    if ".gov" in u or ".us" in u:
        score += 2
    if "/rules" in u or "/reg" in u:
        score += 2
    return score


def _template_candidates_for_state(state_code: str, query: str) -> List[Candidate]:
    curated = list(_STATE_ADMIN_SOURCE_MAP.get(state_code) or [])
    if curated:
        return [
            Candidate(
                state_code=state_code,
                query=query,
                url=url,
                source="curated_seed",
                score=_score_url(url) + 3,
            )
            for url in curated
            if str(url or "").strip()
        ]

    base_url = str(_get_official_state_url(state_code) or "").strip()
    if not base_url:
        return []

    paths = [
        "",
        "/rules",
        "/regulations",
        "/administrative-code",
        "/code-of-regulations",
        "/agency-rules",
        "/policies",
    ]

    out: List[Candidate] = []
    for path in paths:
        url = urljoin(base_url if base_url.endswith("/") else base_url + "/", path.lstrip("/"))
        out.append(
            Candidate(
                state_code=state_code,
                query=query,
                url=url,
                source="official_template",
                score=_score_url(url),
            )
        )
    return out


def _dedupe_candidates(candidates: Sequence[Candidate]) -> List[Candidate]:
    seen = set()
    out: List[Candidate] = []
    for c in sorted(candidates, key=lambda x: x.score, reverse=True):
        key = c.url.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out


async def _discover_for_state(
    searcher: LegalWebArchiveSearch,
    state_code: str,
    max_results_per_domain: int,
    max_candidates_per_state: int,
) -> List[Candidate]:
    query = _query_for_state(state_code)
    domains = _domains_for_state(state_code)
    candidates: List[Candidate] = []

    raw = await searcher._search_archives_multi_domain(
        query=query,
        domains=domains,
        max_results_per_domain=max_results_per_domain,
    )

    for row in raw.get("results", []) if isinstance(raw, dict) else []:
        url = str((row or {}).get("url") or "").strip()
        if not url:
            continue
        if _is_non_admin_seed_url(url):
            continue
        score = _score_url(url)
        if score <= 0:
            continue
        candidates.append(
            Candidate(
                state_code=state_code,
                query=query,
                url=url,
                source=str((row or {}).get("source") or "common_crawl"),
                score=score,
            )
        )

    candidates.extend(_template_candidates_for_state(state_code, query))

    return _dedupe_candidates(candidates)[:max_candidates_per_state]


async def _fetch_documents(candidates: Sequence[Candidate], max_fetch: int) -> List[Dict[str, Any]]:
    cfg = ScraperConfig(
        timeout=35,
        max_retries=2,
        extract_links=True,
        extract_text=True,
        preferred_methods=[
            ScraperMethod.BEAUTIFULSOUP,
            ScraperMethod.WAYBACK_MACHINE,
            ScraperMethod.COMMON_CRAWL,
            ScraperMethod.REQUESTS_ONLY,
        ],
        fallback_enabled=True,
        rate_limit_delay=0.2,
    )
    scraper = UnifiedWebScraper(cfg)

    docs: List[Dict[str, Any]] = []
    for cand in list(candidates)[:max_fetch]:
        res = await scraper.scrape(cand.url)
        text = str(res.text or "").strip()
        if len(text) < 120:
            link_hints: List[str] = []
            for link in list(res.links or [])[:6]:
                if not isinstance(link, dict):
                    continue
                label = str(link.get("text") or "").strip()
                href = str(link.get("url") or "").strip()
                if label:
                    link_hints.append(label)
                elif href:
                    link_hints.append(href)

            fallback_parts = [
                str(res.title or "").strip(),
                cand.query,
                cand.url,
                " ".join(link_hints),
            ]
            text = "\n".join([p for p in fallback_parts if p]).strip()
            if len(text) < 20:
                continue

        docs.append(
            {
                "state_code": cand.state_code,
                "url": cand.url,
                "domain": urlparse(cand.url).netloc,
                "title": str(res.title or "").strip(),
                "text": text,
                "method_used": res.method_used.value if res.method_used else None,
                "fetch_success": bool(res.success),
                "fetch_errors": list(res.errors or []),
                "discovery_source": cand.source,
                "query": cand.query,
                "fetched_at": datetime.now().isoformat(),
            }
        )

    return docs


def _write_jsonl(path: Path, rows: Iterable[Dict[str, Any]]) -> int:
    count = 0
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            count += 1
    return count


async def main() -> None:
    args = parse_args()
    states = _select_states(args)
    out_dir = Path(args.output_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    searcher = LegalWebArchiveSearch(auto_archive=False, use_hf_indexes=True)

    all_candidates: List[Candidate] = []
    all_docs: List[Dict[str, Any]] = []
    per_state_counts: Dict[str, Dict[str, int]] = {}

    for state_code in states:
        candidates = await _discover_for_state(
            searcher,
            state_code=state_code,
            max_results_per_domain=args.max_results_per_domain,
            max_candidates_per_state=args.max_candidates_per_state,
        )
        docs = await _fetch_documents(candidates, max_fetch=args.max_fetch_per_state)

        all_candidates.extend(candidates)
        all_docs.extend(docs)
        per_state_counts[state_code] = {
            "candidate_urls": len(candidates),
            "fetched_documents": len(docs),
        }

    candidates_jsonl = out_dir / "state_admin_rule_discovered_sources.jsonl"
    etl_jsonl = out_dir / "state_admin_rule_kg_corpus.jsonl"
    summary_json = out_dir / "state_admin_rule_discovery_summary.json"

    candidate_rows = [
        {
            "state_code": c.state_code,
            "query": c.query,
            "url": c.url,
            "source": c.source,
            "score": c.score,
        }
        for c in all_candidates
    ]

    n_candidates = _write_jsonl(candidates_jsonl, candidate_rows)
    n_docs = _write_jsonl(etl_jsonl, all_docs)

    summary = {
        "timestamp": datetime.now().isoformat(),
        "states": states,
        "states_count": len(states),
        "candidate_url_count": n_candidates,
        "etl_document_count": n_docs,
        "per_state": per_state_counts,
        "outputs": {
            "discovered_sources_jsonl": str(candidates_jsonl),
            "kg_corpus_jsonl": str(etl_jsonl),
        },
        "next_step": (
            "Run convert_legal_corpus_to_formal_logic.py on kg_corpus_jsonl "
            "to produce formal-logic/KG-ready artifacts."
        ),
    }
    summary_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
