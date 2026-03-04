#!/usr/bin/env python3
"""Scrape civil/criminal procedure rules across states + territories.

This script performs a focused scrape for rule/code families matching:
- Rules of Civil Procedure
- Rules of Criminal Procedure
- Code of Civil Procedure
- Code of Criminal Procedure

It uses registered state-specific scrapers when available and falls back to
generic discovery from jurisdiction landing pages.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ipfs_datasets_py.processors.legal_scrapers.state_laws_scraper import US_STATES
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers import (
    GenericStateScraper,
    get_scraper_for_state,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.base_scraper import (
    BaseStateScraper,
    NormalizedStatute,
)

PROCEDURE_RE = re.compile(
    r"(rules?\s+of\s+(civil|criminal)\s+procedure|"
    r"(civil|criminal)\s+rules?\s+of\s+procedure|"
    r"code\s+of\s+(civil|criminal)\s+procedure|"
    r"(civil|criminal)\s+procedure)",
    re.IGNORECASE,
)

TERRITORIES: Dict[str, Dict[str, str]] = {
    "PR": {"name": "Puerto Rico", "base_url": "https://law.justia.com/codes/puerto-rico/"},
    "GU": {"name": "Guam", "base_url": "https://law.justia.com/codes/guam/"},
    "VI": {"name": "U.S. Virgin Islands", "base_url": "https://law.justia.com/codes/virgin-islands/"},
    "AS": {"name": "American Samoa", "base_url": "https://law.justia.com/codes/american-samoa/"},
    "MP": {"name": "Northern Mariana Islands", "base_url": "https://law.justia.com/codes/northern-mariana-islands/"},
}


def _output_root(output_dir: str | None) -> Path:
    if output_dir:
        return Path(output_dir).expanduser().resolve()
    return (Path.home() / ".ipfs_datasets" / "state_laws" / "procedural_rules").resolve()


def _canonical_entry(name: str, url: str) -> Tuple[str, str]:
    return (" ".join((name or "").split()).strip(), (url or "").strip())


async def _discover_procedure_links(scraper: BaseStateScraper, base_url: str, max_links: int = 30) -> List[Dict[str, str]]:
    raw = await scraper._fetch_page_content_with_archival_fallback(base_url, timeout_seconds=35)
    if not raw:
        return []

    html = raw.decode("utf-8", errors="replace")
    soup = BeautifulSoup(html, "html.parser")

    out: List[Dict[str, str]] = []
    seen: set[Tuple[str, str]] = set()

    for a in soup.find_all("a", href=True):
        text = " ".join(a.get_text(" ", strip=True).split())
        href = str(a.get("href") or "").strip()
        if not text and not href:
            continue
        signal = f"{text} {href}"
        if not PROCEDURE_RE.search(signal):
            continue

        full_url = href if href.startswith("http") else urljoin(base_url, href)
        key = _canonical_entry(text, full_url)
        if key in seen:
            continue
        seen.add(key)
        out.append({"name": text or "Procedural Rules", "url": full_url})

        if len(out) >= max_links:
            break

    return out


async def _scrape_code_candidates(
    scraper: BaseStateScraper,
    state_code: str,
    state_name: str,
    candidates: List[Dict[str, str]],
    rate_limit_delay: float,
    max_per_jurisdiction: int,
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    seen_ids: set[str] = set()

    for cand in candidates:
        code_name = str(cand.get("name") or "").strip() or "Procedural Rules"
        code_url = str(cand.get("url") or "").strip()
        if not code_url:
            continue

        if not PROCEDURE_RE.search(f"{code_name} {code_url}"):
            continue

        try:
            statutes: List[NormalizedStatute] = await scraper.scrape_code(code_name, code_url)
        except Exception:
            statutes = []

        for st in statutes:
            st_dict = st.to_dict() if hasattr(st, "to_dict") else dict(st)
            if not PROCEDURE_RE.search(
                " ".join(
                    [
                        str(st_dict.get("code_name") or ""),
                        str(st_dict.get("title_name") or st_dict.get("titleName") or ""),
                        str(st_dict.get("section_name") or st_dict.get("sectionName") or ""),
                        str(st_dict.get("statute_id") or ""),
                    ]
                )
            ):
                # Keep records from known procedure candidate pages even if section titles omit keywords.
                if not PROCEDURE_RE.search(f"{code_name} {code_url}"):
                    continue

            uid = f"{state_code}|{st_dict.get('statute_id') or ''}|{st_dict.get('source_url') or st_dict.get('sourceUrl') or ''}"
            if uid in seen_ids:
                continue
            seen_ids.add(uid)

            st_dict["state_code"] = state_code
            st_dict["state_name"] = state_name
            st_dict["jurisdiction_type"] = "state" if state_code in US_STATES else "territory"
            rows.append(st_dict)

            if max_per_jurisdiction > 0 and len(rows) >= max_per_jurisdiction:
                return rows

        if rate_limit_delay > 0:
            await asyncio.sleep(rate_limit_delay)

    return rows


async def _run_jurisdiction(
    *,
    state_code: str,
    state_name: str,
    base_url_override: str | None,
    rate_limit_delay: float,
    max_per_jurisdiction: int,
) -> Dict[str, Any]:
    scraper = get_scraper_for_state(state_code, state_name)
    if scraper is None:
        scraper = GenericStateScraper(state_code, state_name)

    if base_url_override:
        try:
            scraper.sources = [
                {"name": "Justia", "base_url": base_url_override, "priority": 1}
            ]
        except Exception:
            pass

    candidates: List[Dict[str, str]] = []
    candidate_seen: set[Tuple[str, str]] = set()

    try:
        for item in scraper.get_code_list() or []:
            name = str(item.get("name") or "").strip()
            url = str(item.get("url") or "").strip()
            if not url:
                continue
            if not PROCEDURE_RE.search(f"{name} {url}"):
                continue
            key = _canonical_entry(name, url)
            if key in candidate_seen:
                continue
            candidate_seen.add(key)
            candidates.append({"name": name or "Procedural Rules", "url": url})
    except Exception:
        pass

    base_url = base_url_override or scraper.get_base_url()
    if base_url:
        discovered = await _discover_procedure_links(scraper, base_url)
        for item in discovered:
            key = _canonical_entry(item.get("name") or "", item.get("url") or "")
            if key in candidate_seen:
                continue
            candidate_seen.add(key)
            candidates.append(item)

    rows = await _scrape_code_candidates(
        scraper=scraper,
        state_code=state_code,
        state_name=state_name,
        candidates=candidates,
        rate_limit_delay=rate_limit_delay,
        max_per_jurisdiction=max_per_jurisdiction,
    )

    return {
        "state_code": state_code,
        "state_name": state_name,
        "candidates": len(candidates),
        "records": len(rows),
        "rows": rows,
    }


async def run(
    output_dir: str | None,
    rate_limit_delay: float,
    parallel_workers: int,
    max_per_jurisdiction: int,
) -> Dict[str, Any]:
    jurisdictions: List[Tuple[str, str, str | None]] = []
    for code, name in sorted(US_STATES.items()):
        jurisdictions.append((code, name, None))
    for code, info in sorted(TERRITORIES.items()):
        jurisdictions.append((code, info["name"], info["base_url"]))

    sem = asyncio.Semaphore(max(1, int(parallel_workers or 1)))

    async def _worker(code: str, name: str, base: str | None) -> Dict[str, Any]:
        async with sem:
            return await _run_jurisdiction(
                state_code=code,
                state_name=name,
                base_url_override=base,
                rate_limit_delay=rate_limit_delay,
                max_per_jurisdiction=max_per_jurisdiction,
            )

    results = await asyncio.gather(*[_worker(code, name, base) for code, name, base in jurisdictions])

    out_dir = _output_root(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = out_dir / "state_and_territory_procedural_rules.jsonl"
    summary_path = out_dir / "state_and_territory_procedural_rules_summary.json"

    total_records = 0
    with jsonl_path.open("w", encoding="utf-8") as handle:
        for item in results:
            for row in item.get("rows", []):
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                total_records += 1

    by_jurisdiction = {
        item["state_code"]: {
            "state_name": item["state_name"],
            "candidates": int(item.get("candidates") or 0),
            "records": int(item.get("records") or 0),
        }
        for item in results
    }

    summary = {
        "status": "success",
        "jurisdictions_targeted": len(jurisdictions),
        "records_total": total_records,
        "output_jsonl": str(jsonl_path),
        "by_jurisdiction": by_jurisdiction,
        "states_with_records": sorted([k for k, v in by_jurisdiction.items() if int(v.get("records") or 0) > 0]),
        "states_without_records": sorted([k for k, v in by_jurisdiction.items() if int(v.get("records") or 0) == 0]),
    }

    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scrape state + territory civil/criminal procedure rules")
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--rate-limit-delay", type=float, default=0.25)
    parser.add_argument("--parallel-workers", type=int, default=8)
    parser.add_argument("--max-per-jurisdiction", type=int, default=0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = asyncio.run(
        run(
            output_dir=args.output_dir,
            rate_limit_delay=float(args.rate_limit_delay),
            parallel_workers=int(args.parallel_workers),
            max_per_jurisdiction=int(args.max_per_jurisdiction),
        )
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
