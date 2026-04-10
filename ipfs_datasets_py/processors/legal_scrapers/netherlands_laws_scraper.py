"""Scraper for Netherlands laws hosted on official Dutch government sources.

This scraper is intentionally modest and configurable:
- it can crawl official index/seed pages for ``wetten.overheid.nl`` links
- it can scrape explicit document URLs directly
- it normalizes results into a repo-consistent JSON/JSON-LD shape

The first version is designed to be reliable as an extension point for EU law
support without forcing the existing US-specific state/federal abstractions to
change.
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set
from urllib.parse import urljoin, urlparse

try:
    import requests
    from bs4 import BeautifulSoup

    REQUESTS_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised via error return path
    REQUESTS_AVAILABLE = False

logger = logging.getLogger(__name__)

DEFAULT_NETHERLANDS_LAWS_DIR = Path.home() / ".ipfs_datasets" / "netherlands_laws"
DEFAULT_NETHERLANDS_LAWS_INDEX_PATH = DEFAULT_NETHERLANDS_LAWS_DIR / "netherlands_laws_index_latest.jsonl"
DEFAULT_NETHERLANDS_LAWS_JSONLD_DIRNAME = "netherlands_laws_jsonld"
USER_AGENT = "ipfs-datasets-netherlands-law-scraper/1.0"

_WS_RE = re.compile(r"\s+")
_WETTEN_HOST_RE = re.compile(r"(^|\.)wetten\.overheid\.nl$", re.IGNORECASE)
_BWB_ID_RE = re.compile(r"/(BWBR[0-9A-Z]+)(?:/|$)", re.IGNORECASE)

_DEFAULT_SOURCE_CONFIGS: List[Dict[str, Any]] = [
    {
        "name": "wetten_overheid_search",
        "label": "Wetten.overheid.nl Search",
        "type": "index",
        "url": "https://wetten.overheid.nl/zoeken",
        "jurisdiction": "NL",
    },
    {
        "name": "wetten_overheid_burgerlijk_wetboek_boek_1",
        "label": "Burgerlijk Wetboek Boek 1",
        "type": "document",
        "url": "https://wetten.overheid.nl/BWBR0002656/",
        "jurisdiction": "NL",
    },
    {
        "name": "wetten_overheid_strafrecht",
        "label": "Wetboek van Strafrecht",
        "type": "document",
        "url": "https://wetten.overheid.nl/BWBR0001854/",
        "jurisdiction": "NL",
    },
]


def _normalize_space(value: Any) -> str:
    return _WS_RE.sub(" ", str(value or "")).strip()


def _resolve_output_dir(output_dir: Optional[str] = None) -> Path:
    if output_dir:
        return Path(output_dir).expanduser().resolve()
    return DEFAULT_NETHERLANDS_LAWS_DIR


def _make_session() -> "requests.Session":
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
    )
    return session


def _safe_id_fragment(value: str) -> str:
    out = re.sub(r"[^a-zA-Z0-9._:-]+", "-", str(value or "").strip())
    return out.strip("-") or "unknown"


def _extract_bwb_id(url: str) -> str:
    match = _BWB_ID_RE.search(str(url or ""))
    if match:
        return str(match.group(1)).upper()
    return ""


def _is_supported_law_url(url: str) -> bool:
    parsed = urlparse(str(url or "").strip())
    if parsed.scheme not in {"http", "https"}:
        return False
    if not _WETTEN_HOST_RE.search(parsed.netloc or ""):
        return False
    return bool(_extract_bwb_id(url))


def _extract_document_links(index_html: str, index_url: str) -> List[str]:
    soup = BeautifulSoup(index_html, "html.parser")
    links: List[str] = []
    seen: Set[str] = set()

    for anchor in soup.select("a[href]"):
        href = str(anchor.get("href") or "").strip()
        if not href:
            continue
        absolute = urljoin(index_url, href)
        if not _is_supported_law_url(absolute):
            continue
        normalized = absolute.split("#", 1)[0]
        if normalized in seen:
            continue
        seen.add(normalized)
        links.append(normalized)

    return links


def _extract_title_and_text(html: str) -> Dict[str, str]:
    soup = BeautifulSoup(html, "html.parser")

    heading = ""
    heading_node = soup.select_one("h1") or soup.select_one("title")
    if heading_node is not None:
        heading = _normalize_space(heading_node.get_text(" ", strip=True))

    content_root = (
        soup.select_one("article")
        or soup.select_one("main")
        or soup.select_one("#content")
        or soup.body
        or soup
    )
    text = _normalize_space(content_root.get_text(" ", strip=True))

    return {"title": heading, "text": text}


def _jsonld_record(record: Dict[str, Any]) -> Dict[str, Any]:
    source_url = str(record.get("source_url") or "")
    identifier = str(record.get("identifier") or "")
    title = str(record.get("title") or "Netherlands Law")

    return {
        "@context": {
            "@vocab": "https://schema.org/",
            "sourceUrl": "https://schema.org/url",
            "jurisdiction": "https://schema.org/jurisdiction",
            "identifier": "https://schema.org/identifier",
            "legislationType": "https://schema.org/legislationType",
            "inLanguage": "https://schema.org/inLanguage",
        },
        "@type": "Legislation",
        "@id": f"urn:nl-law:{_safe_id_fragment(identifier or title)}",
        "name": title,
        "identifier": identifier,
        "legislationType": str(record.get("document_type") or "statute"),
        "jurisdiction": "NL",
        "inLanguage": str(record.get("language") or "nl"),
        "dateModified": datetime.now().date().isoformat(),
        "sourceUrl": source_url,
        "text": str(record.get("text") or ""),
    }


def _write_index_jsonl(rows: Iterable[Dict[str, Any]], *, index_path: Path) -> None:
    index_path.parent.mkdir(parents=True, exist_ok=True)
    with index_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _write_jsonld(records: List[Dict[str, Any]], *, output_root: Path) -> Path:
    out_dir = output_root / DEFAULT_NETHERLANDS_LAWS_JSONLD_DIRNAME
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "NETHERLANDS-LAWS.jsonld"
    with out_path.open("w", encoding="utf-8") as handle:
        for row in records:
            handle.write(json.dumps(_jsonld_record(row), ensure_ascii=False) + "\n")
    return out_path


async def list_netherlands_law_sources() -> Dict[str, Any]:
    """List built-in Netherlands law source configs."""
    return {
        "status": "success",
        "count": len(_DEFAULT_SOURCE_CONFIGS),
        "sources": list(_DEFAULT_SOURCE_CONFIGS),
    }


async def scrape_netherlands_laws(
    document_urls: Optional[List[str]] = None,
    seed_urls: Optional[List[str]] = None,
    output_format: str = "json",
    output_dir: Optional[str] = None,
    rate_limit_delay: float = 0.4,
    max_documents: Optional[int] = None,
    include_metadata: bool = True,
    custom_sources: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Scrape Netherlands laws from official Dutch government sources.

    Args:
        document_urls: Explicit law document URLs to fetch directly.
        seed_urls: Index/search pages to crawl for ``wetten.overheid.nl/BWBR...`` links.
        output_format: Compatibility field for downstream tool callers.
        output_dir: Optional output root. Defaults to ``~/.ipfs_datasets/netherlands_laws``.
        rate_limit_delay: Delay between requests.
        max_documents: Optional cap on scraped law documents.
        include_metadata: Include source metadata fields in result rows.
        custom_sources: Optional additional ``{"type": "index"|"document", "url": ...}`` configs.
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

    selected_seed_urls: List[str] = []
    selected_document_urls: List[str] = []

    for item in _DEFAULT_SOURCE_CONFIGS + list(custom_sources or []):
        if not isinstance(item, dict):
            continue
        source_type = str(item.get("type") or "").strip().lower()
        url = str(item.get("url") or "").strip()
        if not url:
            continue
        if source_type == "index":
            selected_seed_urls.append(url)
        elif source_type == "document":
            selected_document_urls.append(url)

    if seed_urls:
        selected_seed_urls.extend(str(url).strip() for url in seed_urls if str(url).strip())
    if document_urls:
        selected_document_urls.extend(str(url).strip() for url in document_urls if str(url).strip())

    if not selected_seed_urls and not selected_document_urls:
        return {
            "status": "error",
            "error": "No Netherlands law sources selected",
            "data": [],
            "metadata": {},
        }

    records: List[Dict[str, Any]] = []
    errors: List[str] = []
    crawled_index_pages: List[str] = []
    discovered_document_urls: Set[str] = set()
    session = _make_session()

    for index_url in selected_seed_urls:
        try:
            response = session.get(index_url, timeout=40)
            if int(response.status_code) != 200:
                raise RuntimeError(f"HTTP {response.status_code} for {index_url}")
            crawled_index_pages.append(index_url)
            for discovered in _extract_document_links(response.text or "", index_url):
                discovered_document_urls.add(discovered)
        except Exception as exc:
            errors.append(f"{index_url}: {exc}")
        time.sleep(max(0.0, float(rate_limit_delay)))

    for url in selected_document_urls:
        if _is_supported_law_url(url):
            discovered_document_urls.add(url)
        else:
            errors.append(f"{url}: unsupported Netherlands law URL")

    ordered_document_urls = sorted(discovered_document_urls)
    if max_documents and max_documents > 0:
        ordered_document_urls = ordered_document_urls[: int(max_documents)]

    for law_url in ordered_document_urls:
        try:
            response = session.get(law_url, timeout=40)
            if int(response.status_code) != 200:
                raise RuntimeError(f"HTTP {response.status_code} for {law_url}")

            parsed = _extract_title_and_text(response.text or "")
            title = str(parsed.get("title") or "").strip()
            text = str(parsed.get("text") or "").strip()
            if not text:
                raise RuntimeError("No law text extracted")

            identifier = _extract_bwb_id(law_url)
            row: Dict[str, Any] = {
                "jurisdiction": "NL",
                "country": "Netherlands",
                "language": "nl",
                "identifier": identifier,
                "title": title or identifier or "Netherlands Law",
                "text": text,
                "source_url": law_url,
                "document_type": "statute",
                "scraped_at": datetime.now().isoformat(),
            }
            if include_metadata:
                row["metadata"] = {
                    "host": urlparse(law_url).netloc,
                    "source_system": "wetten.overheid.nl",
                }
            records.append(row)
        except Exception as exc:
            errors.append(f"{law_url}: {exc}")
        time.sleep(max(0.0, float(rate_limit_delay)))

    _write_index_jsonl(records, index_path=output_root / DEFAULT_NETHERLANDS_LAWS_INDEX_PATH.name)
    jsonld_path = _write_jsonld(records, output_root=output_root)

    elapsed = time.time() - start
    metadata = {
        "seed_urls": selected_seed_urls,
        "seed_url_count": len(selected_seed_urls),
        "crawled_index_pages": crawled_index_pages,
        "explicit_document_urls": selected_document_urls,
        "discovered_document_count": len(ordered_document_urls),
        "records_count": len(records),
        "errors": errors,
        "error_count": len(errors),
        "elapsed_time_seconds": elapsed,
        "scraped_at": datetime.now().isoformat(),
        "output_dir": str(output_root),
        "index_path": str(output_root / DEFAULT_NETHERLANDS_LAWS_INDEX_PATH.name),
        "jsonld_dir": str(output_root / DEFAULT_NETHERLANDS_LAWS_JSONLD_DIRNAME),
        "jsonld_files": [str(jsonld_path)],
        "max_documents": max_documents,
        "include_metadata": bool(include_metadata),
    }

    if not records:
        return {
            "status": "error",
            "error": "No Netherlands law records were scraped",
            "data": [],
            "metadata": metadata,
            "output_format": output_format,
        }

    return {
        "status": "success",
        "data": records,
        "metadata": metadata,
        "output_format": output_format,
        "note": "Netherlands laws scraper targets official Dutch government law pages on wetten.overheid.nl.",
    }


__all__ = [
    "list_netherlands_law_sources",
    "scrape_netherlands_laws",
    "_extract_document_links",
    "_extract_title_and_text",
]
