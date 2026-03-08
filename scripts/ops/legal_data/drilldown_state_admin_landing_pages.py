#!/usr/bin/env python3
"""Fetch landing-page admin candidates and rank likely child rule links."""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Any, Dict, Iterable, List, Tuple
from urllib.parse import urlparse

from ipfs_datasets_py.processors.web_archiving.contracts import OperationMode, UnifiedFetchRequest
from ipfs_datasets_py.processors.web_archiving.unified_api import UnifiedWebArchivingAPI

ADMIN_LINK_RE = re.compile(
    r"administrative|admin\.?\s*code|rules?|regulations?|register|code\s+of\s+regulations|"
    r"bulletin|notice|adoption|proposed|chapter|title|agency|board|commission|part|subpart|pdf",
    re.IGNORECASE,
)

RULE_BODY_RE = re.compile(
    r"§\s*\d|\barm\s+\d|\b\d{1,3}\.\d{1,3}\.\d{1,4}\b|authority\s*:|history\s*:|implementing\s*:|"
    r"notice\s+of\s+(?:adoption|proposed\s+adoption|proposed\s+amendment|repeal)|purpose\s+of\s+regulations",
    re.IGNORECASE,
)

BAD_LINK_RE = re.compile(
    r"notary|apostille|contact|about-us|about$|help$|faq|login|log\s*in|directory|staff|calendar|events|"
    r"meeting|agenda|minutes|news|home$|homepage|search$|sitemap|rss|subscribe|privacy|accessibility|"
    r"cdn-cgi|email-protection|twitter\.com|x\.com|facebook\.com|instagram\.com|youtube\.com|"
    r"feedback-survey|accessgov|contact\.php|subscribe\.php",
    re.IGNORECASE,
)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Drill down candidate admin landing pages and rank likely child links")
    p.add_argument("--report-json", help="Page-gap report JSON")
    p.add_argument("--input-json", help="Prior drilldown/probe JSON with `pages` or `rows`")
    p.add_argument("--states", nargs="*", default=[], help="Optional state filter")
    p.add_argument(
        "--page-categories",
        nargs="*",
        default=["candidate_landing_page", "candidate_substantive"],
        help="Page categories from the page-gap report to drill down",
    )
    p.add_argument(
        "--only-no-rule-body",
        action="store_true",
        help="When reading --input-json, only keep rows whose prior probe lacked rule body signals",
    )
    p.add_argument(
        "--expand-child-links",
        action="store_true",
        help="When reading --input-json, expand ranked child_links into the next probe set",
    )
    p.add_argument(
        "--child-link-limit-per-page",
        type=int,
        default=6,
        help="Maximum child links to take from each input page when --expand-child-links is set",
    )
    p.add_argument("--top-pages", type=int, default=12)
    p.add_argument("--top-links", type=int, default=12)
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--timeout-seconds", type=int, default=40)
    p.add_argument("--output-json", required=True)
    p.add_argument("--output-md", required=True)
    args = p.parse_args()
    if not args.report_json and not args.input_json:
        p.error("one of --report-json or --input-json is required")
    return args


def _load_report(path: Path) -> List[Dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows: List[Dict[str, Any]] = []
    for state_row in payload.get("states") or []:
        state = str(state_row.get("state") or "").upper().strip()
        for page in state_row.get("problem_pages") or []:
            if not isinstance(page, dict):
                continue
            row = dict(page)
            row["state"] = state
            rows.append(row)
    return rows


def _load_input_rows(path: Path, expand_child_links: bool, child_link_limit_per_page: int) -> List[Dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_rows = payload.get("pages")
    if not isinstance(raw_rows, list):
        raw_rows = payload.get("rows")
    if not isinstance(raw_rows, list):
        raise ValueError(f"Unsupported input JSON shape in {path}")

    rows: List[Dict[str, Any]] = []
    for item in raw_rows:
        if not isinstance(item, dict):
            continue
        state = str(item.get("state") or "").upper().strip()
        page_category = str(item.get("page_category") or "probe_input").strip() or "probe_input"
        if expand_child_links:
            child_links = item.get("child_links") or []
            added = 0
            for link in child_links:
                if not isinstance(link, dict):
                    continue
                url = str(link.get("url") or "").strip()
                if not url:
                    continue
                rows.append(
                    {
                        "state": state,
                        "url": url,
                        "page_category": f"{page_category}_child",
                        "rule_body_signals": bool(link.get("rule_body_signal")),
                        "text_len": 0,
                    }
                )
                added += 1
                if added >= max(1, int(child_link_limit_per_page)):
                    break
            continue
        rows.append(
            {
                "state": state,
                "url": str(item.get("url") or "").strip(),
                "page_category": page_category,
                "rule_body_signals": bool(item.get("rule_body_signals")),
                "text_len": int(item.get("text_len") or 0),
            }
        )
    return rows


def _dedupe_target_rows(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    deduped: List[Dict[str, Any]] = []
    seen = set()
    for row in rows:
        state = str(row.get("state") or "").upper().strip()
        url = str(row.get("url") or "").strip().rstrip("/")
        if not url:
            continue
        key = (state, url.lower())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def _link_score(base_host: str, link: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
    url = str(link.get("url") or "").strip()
    text = str(link.get("text") or "").strip()
    host = urlparse(url).netloc
    hay = f"{url} {text}"
    score = 0
    if ADMIN_LINK_RE.search(hay):
        score += 4
    if RULE_BODY_RE.search(hay):
        score += 4
    if host and base_host and host == base_host:
        score += 2
    if url.lower().endswith(".pdf") or ".pdf?" in url.lower():
        score += 2
    if BAD_LINK_RE.search(hay):
        score -= 5
    if re.search(r"/cdn-cgi/|email-protection|feedback-survey|accessgov", url, re.IGNORECASE):
        score -= 6
    if re.search(r"/search(?:/|$)|/login(?:/|$)|/help(?:/|$)", url, re.IGNORECASE):
        score -= 4
    payload = {
        "url": url,
        "text": text[:240],
        "domain": host,
        "score": score,
        "admin_signal": bool(ADMIN_LINK_RE.search(hay)),
        "rule_body_signal": bool(RULE_BODY_RE.search(hay)),
        "same_domain": bool(host and base_host and host == base_host),
    }
    return score, payload


def _dedupe_links(links: Iterable[Dict[str, Any]], base_host: str, limit: int) -> List[Dict[str, Any]]:
    seen = set()
    scored: List[Tuple[int, Dict[str, Any]]] = []
    for link in links:
        if not isinstance(link, dict):
            continue
        url = str(link.get("url") or "").strip()
        if not url.startswith(("http://", "https://")):
            continue
        key = url.rstrip("/").lower()
        if key in seen:
            continue
        seen.add(key)
        scored.append(_link_score(base_host, link))
    scored.sort(key=lambda item: (item[0], item[1]["same_domain"], item[1]["rule_body_signal"], item[1]["admin_signal"]), reverse=True)
    return [payload for score, payload in scored if score > 0][: max(1, int(limit))]


def _fetch_page(row: Dict[str, Any], timeout_seconds: int, top_links: int) -> Dict[str, Any]:
    url = str(row.get("url") or "").strip()
    state = str(row.get("state") or "").strip()
    api = UnifiedWebArchivingAPI()
    request = UnifiedFetchRequest(
        url=url,
        timeout_seconds=max(5, int(timeout_seconds)),
        mode=OperationMode.BALANCED,
        fallback_enabled=True,
        domain="legal",
        min_quality=0.0,
    )
    try:
        response = api.fetch(request)
        document = response.document
        text = str(document.text or "") if document else ""
        title = str(document.title or "") if document else ""
        links = []
        if document:
            raw_links = document.metadata.get("links") or document.extraction_provenance.get("links") or []
            if isinstance(raw_links, list):
                links = raw_links
        errors = [str(err.message or "") for err in (response.errors or []) if getattr(err, "message", None)]
        child_links = _dedupe_links(links, urlparse(url).netloc, top_links)
        return {
            "state": state,
            "url": url,
            "page_category": row.get("page_category"),
            "success": bool(response.success),
            "quality_score": float(response.quality_score or 0.0),
            "provider": str(response.trace.provider_selected) if response.trace and response.trace.provider_selected else "",
            "title": title[:240],
            "text_len": len(text.strip()),
            "rule_body_signals": bool(RULE_BODY_RE.search(text)),
            "child_links": child_links,
            "child_link_count": len(child_links),
            "errors": errors[:5],
        }
    except BaseException as exc:
        return {
            "state": state,
            "url": url,
            "page_category": row.get("page_category"),
            "success": False,
            "quality_score": 0.0,
            "provider": "",
            "title": "",
            "text_len": 0,
            "rule_body_signals": False,
            "child_links": [],
            "child_link_count": 0,
            "errors": [f"{type(exc).__name__}: {exc}"],
        }


def _markdown(payload: Dict[str, Any]) -> str:
    lines: List[str] = []
    summary = payload["summary"]
    lines.append("# State Admin Landing Page Drilldown")
    lines.append("")
    lines.append(f"- Generated: `{summary['generated_at']}`")
    lines.append(f"- Pages fetched: **{summary['pages_fetched']}**")
    lines.append(f"- Successful fetches: **{summary['successful_fetches']}**")
    lines.append(f"- Pages with ranked child links: **{summary['pages_with_child_links']}**")
    lines.append("")
    for row in payload["pages"]:
        lines.append(f"## {row['state']} {row['page_category']}")
        lines.append("")
        lines.append(f"- URL: `{row['url']}`")
        lines.append(f"- Success: **{'Yes' if row['success'] else 'No'}**")
        lines.append(f"- Provider: `{row['provider'] or 'n/a'}`")
        lines.append(f"- Quality score: **{row['quality_score']:.2f}**")
        lines.append(f"- Text length: **{row['text_len']}**")
        lines.append(f"- Rule body signals: **{'Yes' if row['rule_body_signals'] else 'No'}**")
        if row.get("errors"):
            lines.append(f"- Errors: `{'; '.join(row['errors'][:2])}`")
        lines.append("")
        lines.append("| Score | Same Domain | Rule Body | URL | Link Text |")
        lines.append("|---:|:---:|:---:|---|---|")
        for link in row.get("child_links") or []:
            lines.append(
                f"| {link['score']} | {'Yes' if link['same_domain'] else 'No'} | {'Yes' if link['rule_body_signal'] else 'No'} | {link['url']} | {str(link.get('text') or '').replace('|', ' ')} |"
            )
        if not (row.get("child_links") or []):
            lines.append("| 0 | No | No |  |  |")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    source_path = Path(args.input_json or args.report_json).expanduser().resolve()
    if args.input_json:
        rows = _load_input_rows(source_path, bool(args.expand_child_links), int(args.child_link_limit_per_page))
    else:
        rows = _load_report(source_path)
    states_filter = {str(s).upper().strip() for s in args.states if str(s).strip()}
    categories = {str(c).strip() for c in args.page_categories if str(c).strip()}
    if args.input_json:
        target_rows = [
            row
            for row in rows
            if row.get("url")
            and (not states_filter or str(row.get("state") or "") in states_filter)
            and (not args.only_no_rule_body or not bool(row.get("rule_body_signals")))
        ]
    else:
        target_rows = [
            row
            for row in rows
            if str(row.get("page_category") or "") in categories and (not states_filter or str(row.get("state") or "") in states_filter)
        ]
    target_rows = _dedupe_target_rows(target_rows)
    target_rows.sort(key=lambda row: (str(row.get("state") or ""), str(row.get("page_category") or ""), -int(row.get("text_len") or 0), str(row.get("url") or "")))
    target_rows = target_rows[: max(1, int(args.top_pages))]

    pages: List[Dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max(1, int(args.workers))) as executor:
        futures = [executor.submit(_fetch_page, row, int(args.timeout_seconds), int(args.top_links)) for row in target_rows]
        for future in as_completed(futures):
            pages.append(future.result())

    pages.sort(key=lambda row: (row["state"], row["page_category"], row["url"]))
    payload = {
        "summary": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "pages_fetched": len(pages),
            "successful_fetches": sum(1 for row in pages if row["success"]),
            "pages_with_child_links": sum(1 for row in pages if row.get("child_links")),
            "source_json": str(source_path),
        },
        "pages": pages,
    }

    out_json = Path(args.output_json).expanduser().resolve()
    out_md = Path(args.output_md).expanduser().resolve()
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    out_md.write_text(_markdown(payload), encoding="utf-8")
    print(json.dumps({"output_json": str(out_json), "output_md": str(out_md), "summary": payload["summary"]}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
