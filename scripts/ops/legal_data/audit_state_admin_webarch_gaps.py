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
    _is_relaxed_recovery_text,
    _is_substantive_rule_text,
)
from ipfs_datasets_py.processors.legal_scrapers.state_laws_scraper import _get_official_state_url
from ipfs_datasets_py.processors.web_archiving.unified_api import UnifiedWebArchivingAPI

_ERROR_BLOCK_RE = re.compile(
    r"403|404|forbidden|page not found|cert|certificate|ssl|timeout|timed out|connection refused|dns|name mismatch",
    re.IGNORECASE,
)


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
    substantive = _is_substantive_rule_text(text=text, title=title, url=url, min_chars=160)
    relaxed = _is_relaxed_recovery_text(text=text, title=title, url=url)
    blocked, blocked_messages = _classify_error_messages(error_messages)
    return {
        "state_code": state_code,
        "url": url,
        "success": bool(page.get("success")),
        "title": title[:240],
        "text_len": len(text),
        "substantive_admin": substantive,
        "relaxed_admin": relaxed,
        "error_codes": error_codes,
        "error_messages": error_messages[:5],
        "blocked_or_transport_error": blocked,
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
    api = UnifiedWebArchivingAPI()
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
    substantive_hits = [row for row in page_rows if row["substantive_admin"]]
    blocked_count = sum(1 for row in page_rows if row["blocked_or_transport_error"])
    new_substantive_urls = [row["url"] for row in substantive_hits if row["url"] and not row["in_existing_corpus"]]
    thin_successes = [row for row in page_rows if row["success"] and row["text_len"] < 160 and not row["substantive_admin"]]

    if corpus["corpus_substantive_rows"] <= 0 and substantive_hits:
        gap_category = "corpus_gap_probe_found_substantive"
    elif success_count <= 0 and blocked_count > 0:
        gap_category = "blocked_or_transport_failures"
    elif success_count > 0 and not substantive_hits:
        gap_category = "fetchable_but_non_substantive"
    elif corpus["corpus_substantive_rows"] > 0 or substantive_hits:
        gap_category = "has_substantive_signal"
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
        "probe_substantive_hits": len(substantive_hits),
        "probe_blocked_count": blocked_count,
        "probe_thin_success_count": len(thin_successes),
        "new_substantive_urls": new_substantive_urls[:10],
        "best_substantive_urls": [row["url"] for row in substantive_hits[:10]],
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
    lines.append(f"- States blocked mainly by transport/access failures: **{summary['states_blocked_or_transport']}**")
    lines.append(f"- States fetchable but still non-substantive: **{summary['states_fetchable_but_non_substantive']}**")
    lines.append("")
    lines.append("## Per-State")
    lines.append("")
    lines.append("| State | Corpus Rows | Corpus Substantive | Probe Success | Probe Substantive | New Substantive URLs | Gap Category |")
    lines.append("|---|---:|---:|---:|---:|---:|---|")
    for row in state_rows:
        lines.append(
            f"| {row['state_code']} | {row['corpus_rows']} | {row['corpus_substantive_rows']} | {row['probe_success_count']} | {row['probe_substantive_hits']} | {len(row['new_substantive_urls'])} | {row['gap_category']} |"
        )
    lines.append("")
    lines.append("## Priority Gaps")
    lines.append("")
    for row in state_rows:
        if row["gap_category"] not in {
            "corpus_gap_probe_found_substantive",
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
        if row["blocked_examples"]:
            lines.append(f"- Blocked examples: {', '.join('`' + msg[:120] + '`' for msg in row['blocked_examples'][:3])}")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def main() -> int:
    args = parse_args()
    states = [str(s).upper().strip() for s in args.states if str(s).upper().strip() in set(US_50_STATE_CODES)]
    aggregate_path = Path(args.aggregate_jsonl).expanduser().resolve()
    local_jsonld_dir = Path(args.local_jsonld_dir).expanduser().resolve()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.output_dir).expanduser().resolve() if args.output_dir else (
        Path("artifacts/state_admin_rules") / f"webarch_gap_audit_{timestamp}"
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
