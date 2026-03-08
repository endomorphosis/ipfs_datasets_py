#!/usr/bin/env python3
"""Parallel audit of state admin-rule corpus gaps using unified web archiving.

This script compares the current aggregate admin corpus against a bounded
agentic fetch crawl per state. It uses existing corpus URLs, curated admin-rule
seed URLs, and simple official-site templates, then classifies what the crawl
finds as substantive, thin, blocked, or placeholder content.
"""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Any, Dict, Iterable, List, Tuple
from urllib.parse import urlparse

from ipfs_datasets_py.processors.legal_scrapers.state_admin_rules_scraper import (
    US_50_STATE_CODES,
    US_STATES,
    _STATE_ADMIN_SOURCE_MAP,
    _looks_like_non_rule_admin_page,
    _is_relaxed_recovery_text,
    _is_substantive_rule_text,
)
from ipfs_datasets_py.processors.legal_scrapers.state_laws_scraper import _get_official_state_url
from ipfs_datasets_py.processors.web_archiving.unified_api import UnifiedWebArchivingAPI
from ipfs_datasets_py.processors.web_archiving.unified_web_scraper import (
    ScraperConfig,
    ScraperMethod,
    UnifiedWebScraper,
)

_ERROR_BLOCK_RE = re.compile(
    r"403|404|forbidden|page not found|cert|certificate|ssl|timeout|timed out|connection refused|dns|name mismatch",
    re.IGNORECASE,
)

_ADMIN_PAGE_ANCHOR_RE = re.compile(
    r"administrative|admin\.?\s+code|rules?|regulations?|register|code\s+of\s+regulations|tac\b|nmac\b|nycrr\b|arm\b|ricr\b|iar\b",
    re.IGNORECASE,
)

_NON_ADMIN_PAGE_RE = re.compile(
    r"notary|invite|directory|roster|find my legislator|legislator|budget document|fee schedule|map|about$|contact|opt-out preferences",
    re.IGNORECASE,
)

_RULE_BODY_SIGNAL_RE = re.compile(
    r"§\s*\d|\barm\s+\d|\b\d{1,3}\.\d{1,3}\.\d{1,4}\b|authority\s*:|history\s*:|implementing\s*:|"
    r"purpose\s+of\s+regulations|notice\s+of\s+adoption|notice\s+of\s+proposed\s+(?:amendment|adoption|repeal)",
    re.IGNORECASE,
)

_BLOCKED_CHALLENGE_RE = re.compile(
    r"just a moment|attention required|cloudflare|request rejected|access denied|access is denied|"
    r"captcha|security check|checking your browser|temporarily unavailable|forbidden",
    re.IGNORECASE,
)

_LOGIN_GATE_RE = re.compile(
    r"sign in|log in|username|password|single sign-on|sso|forgot password|request account|account login",
    re.IGNORECASE,
)

_BLOCKED_TITLE_RE = re.compile(
    r"^(attention required|just a moment|request rejected|403\b|404\b|access denied|forbidden)",
    re.IGNORECASE,
)


def _build_live_audit_api() -> UnifiedWebArchivingAPI:
    """Use the same live-aware routing as targeted weak-state recovery."""
    live_cfg = ScraperConfig(
        timeout=40,
        max_retries=2,
        extract_links=True,
        extract_text=True,
        fallback_enabled=True,
        rate_limit_delay=0.2,
        common_crawl_hf_remote_meta=False,
        preferred_methods=[
            ScraperMethod.PLAYWRIGHT,
            ScraperMethod.BEAUTIFULSOUP,
            ScraperMethod.REQUESTS_ONLY,
            ScraperMethod.WAYBACK_MACHINE,
            ScraperMethod.COMMON_CRAWL,
        ],
    )
    return UnifiedWebArchivingAPI(scraper=UnifiedWebScraper(live_cfg))


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Audit state admin-rule corpus gaps with agentic web archiving")
    p.add_argument(
        "--aggregate-jsonl",
        default=(
            "artifacts/state_admin_rules/full_parallel_run_20260306_073445/output/aggregates/"
            "state_admin_rule_kg_corpus_all_states_complete_20260307.jsonl"
        ),
        help="Admin aggregate JSONL to compare against",
    )
    p.add_argument(
        "--local-jsonld-dir",
        default=str(Path.home() / ".ipfs_datasets" / "state_admin_rules" / "state_admin_rules_jsonld"),
        help="Canonical local admin JSON-LD directory",
    )
    p.add_argument("--states", nargs="*", default=list(US_50_STATE_CODES), help="State codes to audit")
    p.add_argument("--max-seeds-per-state", type=int, default=4)
    p.add_argument("--max-pages", type=int, default=6)
    p.add_argument("--max-hops", type=int, default=1)
    p.add_argument("--workers", type=int, default=8)
    p.add_argument(
        "--output-dir",
        default=None,
        help="Output directory (default: artifacts/state_admin_rules/webarch_gap_audit_<timestamp>)",
    )
    return p.parse_args()


def _norm_url(value: Any) -> str:
    url = str(value or "").strip()
    if not url:
        return ""
    return url.rstrip("/")


def _resolve_input_path(value: str) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path.resolve()

    candidates = [
        Path.cwd() / path,
        Path(__file__).resolve().parents[4] / path,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return candidates[0].resolve()


def _official_template_urls(state_code: str) -> List[str]:
    base_url = str(_get_official_state_url(state_code) or "").strip()
    if not base_url:
        return []
    generic_fallback = f"https://legislature.{state_code.lower()}.gov/"
    if base_url.rstrip("/") == generic_fallback.rstrip("/"):
        return []
    if not base_url.endswith("/"):
        base_url += "/"
    tails = [
        "",
        "rules",
        "regulations",
        "administrative-code",
        "code-of-regulations",
        "agency-rules",
        "policies",
    ]
    urls: List[str] = []
    for tail in tails:
        if not tail:
            urls.append(base_url.rstrip("/"))
        else:
            urls.append(base_url.rstrip("/") + "/" + tail)
    return urls


def _load_jsonl_rows(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            if isinstance(row, dict):
                rows.append(row)
    return rows


def _load_aggregate_by_state(path: Path) -> Dict[str, List[Dict[str, Any]]]:
    grouped = {code: [] for code in US_50_STATE_CODES}
    for row in _load_jsonl_rows(path):
        state_code = str(row.get("state_code") or "").upper().strip()
        if state_code in grouped:
            grouped[state_code].append(row)
    return grouped


def _count_local_jsonld_rows(local_dir: Path) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for state_code in US_50_STATE_CODES:
        path = local_dir / f"STATE-{state_code}.jsonld"
        if not path.exists():
            out[state_code] = 0
            continue
        count = 0
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                count += 1
        out[state_code] = count
    return out


def _classify_error_messages(messages: Iterable[str]) -> Tuple[bool, List[str]]:
    blocked = False
    hits: List[str] = []
    for msg in messages:
        text = str(msg or "").strip()
        if not text:
            continue
        if _ERROR_BLOCK_RE.search(text):
            blocked = True
            hits.append(text[:240])
    return blocked, hits[:3]


def _document_text(doc: Dict[str, Any]) -> str:
    return str(doc.get("text") or "").strip()


def _document_title(doc: Dict[str, Any]) -> str:
    return str(doc.get("title") or "").strip()


def _document_html(doc: Dict[str, Any]) -> str:
    return str(doc.get("html") or "")


def _looks_like_blocked_page(*, title: str, text: str, html: str, error_messages: Iterable[str]) -> bool:
    title_text = str(title or "").strip()
    body_text = str(text or "")
    body_html = str(html or "")
    errors = "\n".join(str(msg or "") for msg in error_messages)
    combined = "\n".join([title_text, body_text[:2500], body_html[:2500], errors[:1000]])
    if _BLOCKED_TITLE_RE.search(title_text):
        return True
    if not _BLOCKED_CHALLENGE_RE.search(combined):
        return False
    return len(body_text.strip()) < 1200


def _looks_like_login_gate(*, title: str, text: str, html: str) -> bool:
    title_text = str(title or "").strip()
    body_text = str(text or "")
    hay = "\n".join([title_text, body_text[:2500], str(html or "")[:2500]])
    if not _LOGIN_GATE_RE.search(hay):
        return False
    return len(body_text.strip()) < 1200 or bool(re.search(r"^(sign in|log in|account)", title_text, re.IGNORECASE))


def _is_confident_substantive_page(*, text: str, title: str, url: str) -> bool:
    if not _is_substantive_rule_text(text=text, title=title, url=url, min_chars=160):
        return False
    title_url_hay = " ".join([str(title or ""), str(url or "")]).strip()
    if not title_url_hay:
        return False
    if _NON_ADMIN_PAGE_RE.search(title_url_hay):
        return False
    return bool(_ADMIN_PAGE_ANCHOR_RE.search(title_url_hay))


def _has_rule_body_signals(*, text: str, title: str, url: str) -> bool:
    hay = " ".join([str(title or ""), str(url or ""), str(text or "")])
    return bool(_RULE_BODY_SIGNAL_RE.search(hay))


def _page_row(*, state_code: str, page: Dict[str, Any], corpus_urls: set[str]) -> Dict[str, Any]:
    url = _norm_url(page.get("url"))
    document = page.get("document") or {}
    if not isinstance(document, dict):
        document = {}
    errors = page.get("errors") or []
    error_messages: List[str] = []
    error_codes: List[str] = []
    for item in errors:
        if isinstance(item, dict):
            code = str(item.get("code") or "").strip()
            msg = str(item.get("message") or "").strip()
            if code:
                error_codes.append(code)
            if msg:
                error_messages.append(msg)
        else:
            text = str(item or "").strip()
            if text:
                error_messages.append(text)
    title = _document_title(document)
    text = _document_text(document)
    html = _document_html(document)
    substantive = _is_confident_substantive_page(text=text, title=title, url=url)
    relaxed = _is_relaxed_recovery_text(text=text, title=title, url=url)
    rule_body = _has_rule_body_signals(text=text, title=title, url=url)
    landing_like = _looks_like_non_rule_admin_page(text=text, title=title, url=url)
    blocked_from_errors, blocked_messages = _classify_error_messages(error_messages)
    blocked_from_page = _looks_like_blocked_page(title=title, text=text, html=html, error_messages=error_messages)
    login_gate = _looks_like_login_gate(title=title, text=text, html=html)
    blocked = blocked_from_errors or blocked_from_page or login_gate
    return {
        "state_code": state_code,
        "url": url,
        "success": bool(page.get("success")),
        "usable_success": bool(page.get("success")) and not blocked,
        "title": title[:240],
        "text_len": len(text),
        "substantive_admin": substantive,
        "relaxed_admin": relaxed,
        "rule_body_signals": rule_body,
        "landing_like_admin_page": landing_like,
        "error_codes": error_codes,
        "error_messages": error_messages[:5],
        "blocked_or_transport_error": blocked,
        "blocked_by_challenge_page": blocked_from_page,
        "blocked_by_login_gate": login_gate,
        "blocked_examples": blocked_messages,
        "in_existing_corpus": url in corpus_urls,
        "domain": urlparse(url).netloc if url else "",
    }


def _corpus_summary(state_code: str, rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    urls = {_norm_url(row.get("url")) for row in rows if _norm_url(row.get("url"))}
    substantive_rows = 0
    for row in rows:
        if _is_substantive_rule_text(
            text=str(row.get("text") or ""),
            title=str(row.get("title") or ""),
            url=str(row.get("url") or ""),
            min_chars=160,
        ):
            substantive_rows += 1
    return {
        "state_code": state_code,
        "corpus_rows": len(rows),
        "corpus_substantive_rows": substantive_rows,
        "corpus_urls": urls,
    }


def _prioritize_seeds(state_code: str, corpus_rows: List[Dict[str, Any]], max_seeds: int) -> List[str]:
    ordered: List[str] = []
    seen = set()
    for url in _STATE_ADMIN_SOURCE_MAP.get(state_code, []):
        norm = _norm_url(url)
        if norm and norm not in seen:
            ordered.append(norm)
            seen.add(norm)
    for row in corpus_rows:
        norm = _norm_url(row.get("url"))
        if norm and norm not in seen:
            ordered.append(norm)
            seen.add(norm)
    for url in _official_template_urls(state_code):
        norm = _norm_url(url)
        if norm and norm not in seen:
            ordered.append(norm)
            seen.add(norm)
    return ordered[: max(1, int(max_seeds))]


def _audit_state(
    *,
    state_code: str,
    corpus_rows: List[Dict[str, Any]],
    local_jsonld_rows: int,
    max_seeds: int,
    max_pages: int,
    max_hops: int,
) -> Dict[str, Any]:
    state_name = US_STATES.get(state_code, state_code)
    corpus = _corpus_summary(state_code, corpus_rows)
    seeds = _prioritize_seeds(state_code, corpus_rows, max_seeds)
    api = _build_live_audit_api()
    target_terms = [
        state_name,
        f"{state_name} administrative code",
        f"{state_name} administrative rules",
        f"{state_name} regulations",
    ]
    probe = api.agentic_discover_and_fetch(
        seed_urls=seeds,
        target_terms=target_terms,
        max_hops=max_hops,
        max_pages=max_pages,
    )
    results = probe.get("results") or []
    page_rows = [_page_row(state_code=state_code, page=page, corpus_urls=corpus["corpus_urls"]) for page in results if isinstance(page, dict)]

    success_count = sum(1 for row in page_rows if row["success"])
    usable_success_count = sum(1 for row in page_rows if row["usable_success"])
    substantive_hits = [row for row in page_rows if row["substantive_admin"] and row["rule_body_signals"]]
    landing_candidate_hits = [row for row in page_rows if row["substantive_admin"] and not row["rule_body_signals"]]
    blocked_count = sum(1 for row in page_rows if row["blocked_or_transport_error"])
    new_substantive_urls = [row["url"] for row in substantive_hits if row["url"] and not row["in_existing_corpus"]]
    new_landing_candidate_urls = [row["url"] for row in landing_candidate_hits if row["url"] and not row["in_existing_corpus"]]
    thin_successes = [
        row for row in page_rows
        if row["usable_success"] and row["text_len"] < 160 and not row["substantive_admin"]
    ]

    if corpus["corpus_substantive_rows"] <= 0 and substantive_hits:
        gap_category = "corpus_gap_probe_found_substantive"
    elif corpus["corpus_substantive_rows"] <= 0 and landing_candidate_hits:
        gap_category = "corpus_gap_with_landing_candidates"
    elif corpus["corpus_substantive_rows"] > 0 or substantive_hits:
        gap_category = "has_substantive_signal"
    elif usable_success_count <= 0 and blocked_count > 0:
        gap_category = "blocked_or_transport_failures"
    elif usable_success_count > 0 and not substantive_hits:
        gap_category = "fetchable_but_non_substantive"
    else:
        gap_category = "unclear"

    return {
        "state_code": state_code,
        "state_name": state_name,
        "seed_urls": seeds,
        "seed_count": len(seeds),
        "has_curated_seeds": state_code in _STATE_ADMIN_SOURCE_MAP,
        "local_jsonld_rows": int(local_jsonld_rows),
        "corpus_rows": corpus["corpus_rows"],
        "corpus_substantive_rows": corpus["corpus_substantive_rows"],
        "probe_visited_count": int(probe.get("visited_count") or 0),
        "probe_result_count": len(page_rows),
        "probe_success_count": success_count,
        "probe_usable_success_count": usable_success_count,
        "probe_substantive_hits": len(substantive_hits),
        "probe_landing_candidate_hits": len(landing_candidate_hits),
        "probe_blocked_count": blocked_count,
        "probe_thin_success_count": len(thin_successes),
        "new_substantive_urls": new_substantive_urls[:10],
        "best_substantive_urls": [row["url"] for row in substantive_hits[:10]],
        "new_landing_candidate_urls": new_landing_candidate_urls[:10],
        "best_landing_candidate_urls": [row["url"] for row in landing_candidate_hits[:10]],
        "blocked_examples": [msg for row in page_rows for msg in row["blocked_examples"]][:5],
        "gap_category": gap_category,
        "pages": page_rows,
    }


def _write_jsonl(path: Path, rows: Iterable[Dict[str, Any]]) -> int:
    count = 0
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            count += 1
    return count


def _build_markdown(summary: Dict[str, Any], state_rows: List[Dict[str, Any]]) -> str:
    lines: List[str] = []
    lines.append("# State Admin WebArch Gap Audit")
    lines.append("")
    lines.append(f"- Generated: `{summary['generated_at']}`")
    lines.append(f"- States audited: **{summary['states_audited']}**")
    lines.append(f"- Per-state workers: **{summary['workers']}**")
    lines.append(f"- Max seeds/state: **{summary['max_seeds_per_state']}**")
    lines.append(f"- Max pages/state: **{summary['max_pages']}**")
    lines.append(f"- Max hops: **{summary['max_hops']}**")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- States with substantive corpus signal: **{summary['states_with_corpus_substantive']}**")
    lines.append(f"- States where probe found substantive pages: **{summary['states_with_probe_substantive']}**")
    lines.append(f"- States where probe found new substantive URLs outside corpus: **{summary['states_with_new_substantive_urls']}**")
    lines.append(f"- States where probe found only landing-page candidates: **{summary['states_with_landing_candidates']}**")
    lines.append(f"- States blocked mainly by transport/access failures: **{summary['states_blocked_or_transport']}**")
    lines.append(f"- States fetchable but still non-substantive: **{summary['states_fetchable_but_non_substantive']}**")
    lines.append("")
    lines.append("## Per-State")
    lines.append("")
    lines.append("| State | Corpus Rows | Corpus Substantive | Probe Success | Usable Success | Probe Substantive | Probe Landing Candidates | New Substantive URLs | Gap Category |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---|")
    for row in state_rows:
        lines.append(
            f"| {row['state_code']} | {row['corpus_rows']} | {row['corpus_substantive_rows']} | {row['probe_success_count']} | {row['probe_usable_success_count']} | {row['probe_substantive_hits']} | {row['probe_landing_candidate_hits']} | {len(row['new_substantive_urls'])} | {row['gap_category']} |"
        )
    lines.append("")
    lines.append("## Priority Gaps")
    lines.append("")
    for row in state_rows:
        if row["gap_category"] not in {
            "corpus_gap_probe_found_substantive",
            "corpus_gap_with_landing_candidates",
            "blocked_or_transport_failures",
            "fetchable_but_non_substantive",
        }:
            continue
        lines.append(f"### {row['state_code']}")
        lines.append("")
        lines.append(f"- Gap category: `{row['gap_category']}`")
        lines.append(f"- Seed URLs: {', '.join('`' + url + '`' for url in row['seed_urls'][:4]) or 'None'}")
        if row["new_substantive_urls"]:
            lines.append(f"- New substantive URLs: {', '.join('`' + url + '`' for url in row['new_substantive_urls'][:5])}")
        if row["best_landing_candidate_urls"]:
            lines.append(f"- Landing-page candidates: {', '.join('`' + url + '`' for url in row['best_landing_candidate_urls'][:5])}")
        if row["blocked_examples"]:
            lines.append(f"- Blocked examples: {', '.join('`' + msg[:120] + '`' for msg in row['blocked_examples'][:3])}")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def main() -> int:
    args = parse_args()
    states = [str(s).upper().strip() for s in args.states if str(s).upper().strip() in set(US_50_STATE_CODES)]
    aggregate_path = _resolve_input_path(args.aggregate_jsonl)
    local_jsonld_dir = _resolve_input_path(args.local_jsonld_dir)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_dir = _resolve_input_path(args.output_dir) if args.output_dir else (
        Path.cwd() / "artifacts/state_admin_rules" / f"webarch_gap_audit_{timestamp}"
    ).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    by_state = _load_aggregate_by_state(aggregate_path)
    local_counts = _count_local_jsonld_rows(local_jsonld_dir)

    state_rows: List[Dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max(1, int(args.workers))) as executor:
        futures = {
            executor.submit(
                _audit_state,
                state_code=state_code,
                corpus_rows=by_state.get(state_code, []),
                local_jsonld_rows=local_counts.get(state_code, 0),
                max_seeds=int(args.max_seeds_per_state),
                max_pages=int(args.max_pages),
                max_hops=int(args.max_hops),
            ): state_code
            for state_code in states
        }
        for future in as_completed(futures):
            state_rows.append(future.result())

    state_rows.sort(key=lambda row: row["state_code"])
    page_rows = [page for row in state_rows for page in row["pages"]]

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "aggregate_jsonl": str(aggregate_path),
        "local_jsonld_dir": str(local_jsonld_dir),
        "states_audited": len(state_rows),
        "workers": int(args.workers),
        "max_seeds_per_state": int(args.max_seeds_per_state),
        "max_pages": int(args.max_pages),
        "max_hops": int(args.max_hops),
        "states_with_corpus_substantive": sum(1 for row in state_rows if row["corpus_substantive_rows"] > 0),
        "states_with_probe_substantive": sum(1 for row in state_rows if row["probe_substantive_hits"] > 0),
        "states_with_new_substantive_urls": sum(1 for row in state_rows if row["new_substantive_urls"]),
        "states_with_landing_candidates": sum(1 for row in state_rows if row["probe_landing_candidate_hits"] > 0 and row["probe_substantive_hits"] == 0),
        "states_blocked_or_transport": sum(1 for row in state_rows if row["gap_category"] == "blocked_or_transport_failures"),
        "states_fetchable_but_non_substantive": sum(1 for row in state_rows if row["gap_category"] == "fetchable_but_non_substantive"),
    }

    (out_dir / "summary.json").write_text(
        json.dumps({"summary": summary, "states": state_rows}, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    _write_jsonl(out_dir / "per_page.jsonl", page_rows)
    _write_jsonl(out_dir / "per_state.jsonl", state_rows)
    (out_dir / "summary.md").write_text(_build_markdown(summary, state_rows), encoding="utf-8")

    print(json.dumps({"output_dir": str(out_dir), **summary}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
