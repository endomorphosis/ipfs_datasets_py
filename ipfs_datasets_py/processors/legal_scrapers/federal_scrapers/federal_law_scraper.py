"""Federal law scraper for federal procedural rules and local court rules.

This module expands federal legal scraping beyond US Code titles by collecting:
- Federal Rules of Civil Procedure (FRCP)
- Federal Rules of Criminal Procedure (FRCrP)
- Configurable local court rules landing pages

Outputs are emitted as JSON-LD JSONL records under:
    ~/.ipfs_datasets/federal_laws/federal_laws_jsonld/FEDERAL-RULES.jsonld
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import anyio

try:
    import requests
    from bs4 import BeautifulSoup

    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

logger = logging.getLogger(__name__)

DEFAULT_FEDERAL_LAWS_DIR = Path.home() / ".ipfs_datasets" / "federal_laws"
DEFAULT_FEDERAL_LAWS_INDEX_PATH = DEFAULT_FEDERAL_LAWS_DIR / "federal_laws_index_latest.jsonl"
DEFAULT_FEDERAL_LAWS_JSONLD_DIRNAME = "federal_laws_jsonld"
USER_AGENT = "ipfs-datasets-federal-law-scraper/1.0"

_RULE_NUMBER_RE = re.compile(r"\bRule\s+([0-9][\dA-Za-z\-.]*)", re.IGNORECASE)
_WS_RE = re.compile(r"\s+")

_DEFAULT_RULESET_CONFIGS: List[Dict[str, Any]] = [
    {
        "name": "frcp",
        "label": "Federal Rules of Civil Procedure",
        "type": "federal_procedural_rules",
        "index_url": "https://www.law.cornell.edu/rules/frcp",
        "rule_link_substring": "/rules/frcp/rule_",
        "court": "Federal Courts",
    },
    {
        "name": "frcrmp",
        "label": "Federal Rules of Criminal Procedure",
        "type": "federal_procedural_rules",
        "index_url": "https://www.law.cornell.edu/rules/frcrmp",
        "rule_link_substring": "/rules/frcrmp/rule_",
        "court": "Federal Courts",
    },
    {
        "name": "local_rules_dcd",
        "label": "U.S. District Court for D.C. Local Rules",
        "type": "local_rules",
        "index_url": "https://www.dcd.uscourts.gov/court-info/local-rules-and-orders/local-rules",
        "court": "D.D.C.",
    },
    {
        "name": "local_rules_cacd",
        "label": "U.S. District Court C.D. California Local Rules",
        "type": "local_rules",
        "index_url": "https://www.cacd.uscourts.gov/court-procedures/local-rules",
        "court": "C.D. Cal.",
    },
    {
        "name": "local_rules_nysd",
        "label": "U.S. District Court S.D. New York Rules and Orders",
        "type": "local_rules",
        "index_url": "https://www.nysd.uscourts.gov/rules",
        "court": "S.D.N.Y.",
    },
    {
        "name": "local_rules_ca9",
        "label": "Ninth Circuit Rules",
        "type": "local_rules",
        "index_url": "https://www.ca9.uscourts.gov/rules/",
        "court": "9th Cir.",
    },
]


class FederalLawScraper:
    """Registry-friendly class wrapper for federal law scraping."""

    async def scrape(self, **kwargs: Any) -> Dict[str, Any]:
        return await scrape_federal_laws(**kwargs)


def _normalize_space(value: str) -> str:
    return _WS_RE.sub(" ", str(value or "")).strip()


def _make_session() -> "requests.Session":
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
    )
    return session


def _resolve_output_dir(output_dir: Optional[str] = None) -> Path:
    if output_dir:
        return Path(output_dir).expanduser().resolve()
    return DEFAULT_FEDERAL_LAWS_DIR


def _safe_id_fragment(value: str) -> str:
    out = re.sub(r"[^a-zA-Z0-9._:-]+", "-", str(value or "").strip())
    return out.strip("-") or "unknown"


def _extract_rule_number(title: str, url: str) -> str:
    match = _RULE_NUMBER_RE.search(str(title or ""))
    if match:
        return str(match.group(1)).rstrip(".:-")
    url_tail = str(urlparse(str(url or "")).path).rsplit("/", 1)[-1]
    if url_tail.startswith("rule_"):
        return url_tail.removeprefix("rule_").replace("_", "-")
    return ""


def _jsonld_record(record: Dict[str, Any]) -> Dict[str, Any]:
    source_url = str(record.get("source_url") or "")
    ruleset = str(record.get("ruleset") or "federal-law")
    court = str(record.get("court") or "Federal Courts")
    rule_number = str(record.get("rule_number") or "")
    name = str(record.get("title") or "Federal Rule")

    return {
        "@context": {
            "@vocab": "https://schema.org/",
            "sourceUrl": "https://schema.org/url",
            "court": "https://schema.org/Organization",
            "ruleNumber": "https://schema.org/identifier",
            "jurisdiction": "https://schema.org/jurisdiction",
        },
        "@type": "Legislation",
        "@id": f"urn:federal-rules:{_safe_id_fragment(ruleset)}:{_safe_id_fragment(rule_number or name)}",
        "name": name,
        "legislationType": "rule",
        "jurisdiction": "US-FED",
        "court": court,
        "ruleSet": ruleset,
        "ruleNumber": rule_number,
        "dateModified": datetime.now().date().isoformat(),
        "sourceUrl": source_url,
        "text": str(record.get("text") or ""),
        "documentType": str(record.get("document_type") or "rule"),
    }


def _write_index_jsonl(rows: Iterable[Dict[str, Any]], *, index_path: Path) -> None:
    index_path.parent.mkdir(parents=True, exist_ok=True)
    with index_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _write_jsonld(records: List[Dict[str, Any]], *, output_root: Path) -> Path:
    out_dir = output_root / DEFAULT_FEDERAL_LAWS_JSONLD_DIRNAME
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "FEDERAL-RULES.jsonld"
    with out_path.open("w", encoding="utf-8") as handle:
        for row in records:
            handle.write(json.dumps(_jsonld_record(row), ensure_ascii=False) + "\n")
    return out_path


def _extract_rule_links(index_html: str, index_url: str, link_substring: str) -> List[str]:
    soup = BeautifulSoup(index_html, "html.parser")
    links: List[str] = []
    seen: set[str] = set()

    for anchor in soup.select("a[href]"):
        href = str(anchor.get("href") or "").strip()
        if not href:
            continue
        absolute = urljoin(index_url, href)
        if link_substring not in absolute:
            continue
        if absolute in seen:
            continue
        seen.add(absolute)
        links.append(absolute)

    return links


def _extract_title_and_text(html: str) -> Tuple[str, str]:
    soup = BeautifulSoup(html, "html.parser")

    # Prefer article content when available; fallback to body text.
    article = soup.select_one("article")
    heading = ""
    if article is not None:
        h = article.select_one("h1, h2")
        heading = _normalize_space(h.get_text(" ", strip=True)) if h else ""
        text = _normalize_space(article.get_text(" ", strip=True))
    else:
        h = soup.select_one("h1, h2")
        heading = _normalize_space(h.get_text(" ", strip=True)) if h else ""
        body = soup.select_one("main") or soup.body or soup
        text = _normalize_space(body.get_text(" ", strip=True))

    if not heading:
        heading = _normalize_space(soup.title.get_text(" ", strip=True) if soup.title else "")
    return heading, text


def _extract_local_rule_documents(index_html: str, index_url: str) -> List[Dict[str, str]]:
    soup = BeautifulSoup(index_html, "html.parser")
    rows: List[Dict[str, str]] = []
    seen: set[str] = set()

    for anchor in soup.select("a[href]"):
        href = str(anchor.get("href") or "").strip()
        title = _normalize_space(anchor.get_text(" ", strip=True))
        if not href or not title:
            continue
        absolute = urljoin(index_url, href)
        lower = absolute.lower()
        if lower in seen:
            continue

        if "rule" not in title.lower() and "rule" not in lower:
            continue

        seen.add(lower)
        rows.append({"title": title, "url": absolute})

    return rows


async def list_federal_law_sources() -> Dict[str, Any]:
    """List built-in source configs for federal law scraping."""
    return {
        "status": "success",
        "count": len(_DEFAULT_RULESET_CONFIGS),
        "sources": _DEFAULT_RULESET_CONFIGS,
    }


async def scrape_federal_laws(
    rulesets: Optional[List[str]] = None,
    include_local_rules: bool = True,
    output_format: str = "json",
    output_dir: Optional[str] = None,
    rate_limit_delay: float = 0.4,
    max_rules_per_ruleset: Optional[int] = None,
    custom_sources: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Scrape federal procedural rules and local court rules.

    Args:
        rulesets: Optional list of source names from list_federal_law_sources().
        include_local_rules: Include built-in local court rules sources.
        output_format: Response metadata field for compatibility.
        output_dir: Optional output root. Defaults to ~/.ipfs_datasets/federal_laws.
        rate_limit_delay: Delay between remote requests.
        max_rules_per_ruleset: Optional cap per source for debug runs.
        custom_sources: Optional additional source definitions.

    Returns:
        Standard scraper response shape with data + metadata.
    """
    if not REQUESTS_AVAILABLE:
        return {
            "status": "error",
            "error": "Required libraries unavailable: install requests and beautifulsoup4",
            "data": [],
            "metadata": {},
        }

    start = time.time()
    output_root = _resolve_output_dir(output_dir)
    output_root.mkdir(parents=True, exist_ok=True)

    selected_sources: List[Dict[str, Any]] = []
    requested = set(str(x).strip().lower() for x in (rulesets or []) if str(x).strip())

    for cfg in _DEFAULT_RULESET_CONFIGS:
        is_local = str(cfg.get("type")) == "local_rules"
        if is_local and not include_local_rules:
            continue
        if requested and str(cfg.get("name", "")).lower() not in requested:
            continue
        selected_sources.append(dict(cfg))

    for cfg in custom_sources or []:
        if not isinstance(cfg, dict):
            continue
        selected_sources.append(dict(cfg))

    if not selected_sources:
        return {
            "status": "error",
            "error": "No federal law sources selected",
            "data": [],
            "metadata": {},
        }

    records: List[Dict[str, Any]] = []
    source_summaries: List[Dict[str, Any]] = []
    errors: List[str] = []

    session = _make_session()

    for source in selected_sources:
        source_name = str(source.get("name") or "unknown")
        source_label = str(source.get("label") or source_name)
        source_url = str(source.get("index_url") or "").strip()
        source_type = str(source.get("type") or "federal_procedural_rules")
        source_court = str(source.get("court") or "Federal Courts")
        if not source_url:
            errors.append(f"{source_name}: missing index_url")
            continue

        try:
            resp = session.get(source_url, timeout=40)
            if int(resp.status_code) != 200:
                raise RuntimeError(f"HTTP {resp.status_code} for {source_url}")

            source_count = 0
            if source_type == "federal_procedural_rules":
                rule_link_substring = str(source.get("rule_link_substring") or "").strip()
                if not rule_link_substring:
                    raise RuntimeError(f"{source_name}: missing rule_link_substring")

                rule_urls = _extract_rule_links(resp.text or "", source_url, rule_link_substring)
                if max_rules_per_ruleset and max_rules_per_ruleset > 0:
                    rule_urls = rule_urls[: int(max_rules_per_ruleset)]

                for rule_url in rule_urls:
                    try:
                        page = session.get(rule_url, timeout=40)
                        if int(page.status_code) != 200:
                            continue
                        title, text = _extract_title_and_text(page.text or "")
                        if not text:
                            continue
                        rule_number = _extract_rule_number(title, rule_url)
                        records.append(
                            {
                                "ruleset": source_name,
                                "ruleset_label": source_label,
                                "court": source_court,
                                "title": title,
                                "rule_number": rule_number,
                                "text": text,
                                "source_url": rule_url,
                                "document_type": "federal_procedural_rule",
                            }
                        )
                        source_count += 1
                    finally:
                        await anyio.sleep(max(0.0, float(rate_limit_delay)))

            else:
                docs = _extract_local_rule_documents(resp.text or "", source_url)
                if max_rules_per_ruleset and max_rules_per_ruleset > 0:
                    docs = docs[: int(max_rules_per_ruleset)]

                for doc in docs:
                    records.append(
                        {
                            "ruleset": source_name,
                            "ruleset_label": source_label,
                            "court": source_court,
                            "title": str(doc.get("title") or "Local Rule"),
                            "rule_number": _extract_rule_number(str(doc.get("title") or ""), str(doc.get("url") or "")),
                            "text": str(doc.get("title") or ""),
                            "source_url": str(doc.get("url") or ""),
                            "document_type": "local_rule_reference",
                        }
                    )
                    source_count += 1

            source_summaries.append(
                {
                    "name": source_name,
                    "label": source_label,
                    "type": source_type,
                    "index_url": source_url,
                    "record_count": source_count,
                }
            )

        except Exception as exc:
            errors.append(f"{source_name}: {exc}")

    _write_index_jsonl(records, index_path=output_root / DEFAULT_FEDERAL_LAWS_INDEX_PATH.name)
    jsonld_path = _write_jsonld(records, output_root=output_root)

    elapsed = time.time() - start
    metadata = {
        "sources_requested": [str(s.get("name") or "") for s in selected_sources],
        "sources_count": len(selected_sources),
        "source_summaries": source_summaries,
        "records_count": len(records),
        "errors": errors,
        "error_count": len(errors),
        "elapsed_time_seconds": elapsed,
        "scraped_at": datetime.now().isoformat(),
        "output_dir": str(output_root),
        "index_path": str(output_root / DEFAULT_FEDERAL_LAWS_INDEX_PATH.name),
        "jsonld_dir": str(output_root / DEFAULT_FEDERAL_LAWS_JSONLD_DIRNAME),
        "jsonld_files": [str(jsonld_path)],
        "include_local_rules": bool(include_local_rules),
        "max_rules_per_ruleset": max_rules_per_ruleset,
    }

    if not records:
        return {
            "status": "error",
            "error": "No federal law records were scraped",
            "data": [],
            "metadata": metadata,
            "output_format": output_format,
        }

    return {
        "status": "success",
        "data": records,
        "metadata": metadata,
        "output_format": output_format,
        "note": "Federal rules corpus includes FRCP/FRCrP and configured local rules references.",
    }


__all__ = [
    "FederalLawScraper",
    "list_federal_law_sources",
    "scrape_federal_laws",
]
