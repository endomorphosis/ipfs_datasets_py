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
from collections import defaultdict
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
DEFAULT_NETHERLANDS_LAWS_ARTICLE_INDEX_PATH = (
    DEFAULT_NETHERLANDS_LAWS_DIR / "netherlands_laws_articles_index_latest.jsonl"
)
DEFAULT_NETHERLANDS_LAWS_SEARCH_INDEX_PATH = (
    DEFAULT_NETHERLANDS_LAWS_DIR / "netherlands_laws_search_index_latest.jsonl"
)
DEFAULT_NETHERLANDS_LAWS_JSONLD_DIRNAME = "netherlands_laws_jsonld"
USER_AGENT = "ipfs-datasets-netherlands-law-scraper/1.0"

_WS_RE = re.compile(r"\s+")
_WETTEN_HOST_RE = re.compile(r"(^|\.)wetten\.overheid\.nl$", re.IGNORECASE)
_BWB_ID_RE = re.compile(r"/(BWBR[0-9A-Z]+)(?:/|$)", re.IGNORECASE)
_ARTICLE_HEADING_RE = re.compile(
    r"^artikel\s+([0-9]+(?:[.:][0-9]+)*(?:[a-z])?)\b(?:\s*[:.\-]\s*(.*))?$",
    re.IGNORECASE,
)
_STRUCTURE_KIND_PATTERNS: List[tuple[str, re.Pattern[str]]] = [
    ("boek", re.compile(r"^boek\s+([0-9ivxlcdm]+)\b", re.IGNORECASE)),
    ("titel", re.compile(r"^titel\s+([0-9a-zivxlcdm.\-]+)\b", re.IGNORECASE)),
    ("hoofdstuk", re.compile(r"^hoofdstuk\s+([0-9a-zivxlcdm.\-]+)\b", re.IGNORECASE)),
    ("afdeling", re.compile(r"^afdeling\s+([0-9a-zivxlcdm.\-]+)\b", re.IGNORECASE)),
    ("paragraaf", re.compile(r"^paragraaf\s+([0-9a-zivxlcdm.\-]+)\b", re.IGNORECASE)),
    ("artikel", _ARTICLE_HEADING_RE),
]
_STRUCTURE_LEVELS = ["boek", "titel", "hoofdstuk", "afdeling", "paragraaf", "artikel"]
_AUTHORITATIVE_HOST_PATTERNS = [
    re.compile(r"(^|\.)wetten\.overheid\.nl$", re.IGNORECASE),
    re.compile(r"(^|\.)overheid\.nl$", re.IGNORECASE),
    re.compile(r"(^|\.)koopoverheid\.nl$", re.IGNORECASE),
    re.compile(r"(^|\.)officielebekendmakingen\.nl$", re.IGNORECASE),
]
_INFO_LABEL_PATTERNS = {
    "regulation_type": [
        re.compile(r"soort regeling\s+(.+?)(?:\s{2,}|$)", re.IGNORECASE),
    ],
    "identifier": [
        re.compile(r"identificatienummer\s+(BWBR[0-9A-Z]+)", re.IGNORECASE),
    ],
    "cite_title": [
        re.compile(r"citeertitel\s+(.+?)(?:\s{2,}|$)", re.IGNORECASE),
    ],
    "official_title": [
        re.compile(r"(?:offici[eë]le titel|opschrift)\s+(.+?)(?:\s{2,}|$)", re.IGNORECASE),
    ],
    "effective_date": [
        re.compile(r"(?:datum inwerkingtreding|inwerkingtreding|geldig van)\s+(.+?)(?:\s{2,}|$)", re.IGNORECASE),
    ],
    "publication_date": [
        re.compile(r"(?:datum van uitgifte|publicatiedatum|datum publicatie)\s+(.+?)(?:\s{2,}|$)", re.IGNORECASE),
    ],
    "last_modified_date": [
        re.compile(r"(?:laatste wijziging|laatst gewijzigd)\s+(.+?)(?:\s{2,}|$)", re.IGNORECASE),
    ],
}
_DUTCH_MONTHS = {
    "januari": 1,
    "februari": 2,
    "maart": 3,
    "april": 4,
    "mei": 5,
    "juni": 6,
    "juli": 7,
    "augustus": 8,
    "september": 9,
    "oktober": 10,
    "november": 11,
    "december": 12,
}
_CONTENT_ROOT_SELECTORS = [
    "article",
    "main",
    "#content",
    ".wetgeving",
    ".regeling-tekst",
    ".regeling-onderdelen",
    ".wet-tekst",
    ".intitule",
]

_DEFAULT_SOURCE_CONFIGS: List[Dict[str, Any]] = [
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


def _classify_structure_heading(text: str) -> tuple[Optional[str], Optional[str]]:
    label = _normalize_space(text)
    for kind, pattern in _STRUCTURE_KIND_PATTERNS:
        match = pattern.match(label)
        if match:
            return kind, _normalize_space(match.group(1))
    return None, None


def _clear_lower_hierarchy_levels(hierarchy: Dict[str, str], kind: str) -> None:
    if kind not in _STRUCTURE_LEVELS:
        return
    current_index = _STRUCTURE_LEVELS.index(kind)
    for lower_kind in _STRUCTURE_LEVELS[current_index + 1 :]:
        hierarchy.pop(lower_kind, None)


def _parse_dutch_date(value: Any) -> str:
    text = _normalize_space(value)
    if not text:
        return ""

    iso_match = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", text)
    if iso_match:
        return iso_match.group(1)

    numeric_match = re.search(r"\b(\d{1,2})-(\d{1,2})-(\d{4})\b", text)
    if numeric_match:
        day, month, year = numeric_match.groups()
        return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"

    month_name_match = re.search(
        r"\b(\d{1,2})\s+([a-z\u00e4\u00eb\u00ef\u00f6\u00fc]+)\s+(\d{4})\b",
        text,
        re.IGNORECASE,
    )
    if month_name_match:
        day, month_name, year = month_name_match.groups()
        month = _DUTCH_MONTHS.get(month_name.lower())
        if month:
            return f"{int(year):04d}-{month:02d}-{int(day):02d}"

    return ""


def _append_text(target: Dict[str, Any], text: str) -> None:
    normalized = _normalize_space(text)
    if not normalized:
        return
    parts = target.setdefault("_text_parts", [])
    if not isinstance(parts, list):
        parts = []
        target["_text_parts"] = parts
    parts.append(normalized)


def _finalize_parts(parts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    finalized: List[Dict[str, Any]] = []
    for part in parts:
        row = dict(part)
        text = _normalize_space(" ".join(str(item) for item in row.pop("_text_parts", [])))
        row["text"] = text
        if row.get("heading"):
            row["heading"] = _normalize_space(row["heading"])
        finalized.append(row)
    return finalized


def _hierarchy_path_items(hierarchy: Dict[str, Any], *, article_number: str = "", article_label: str = "") -> List[Dict[str, str]]:
    path: List[Dict[str, str]] = []
    for kind in _STRUCTURE_LEVELS:
        if kind == "artikel":
            if article_number or article_label:
                path.append(
                    {
                        "kind": "artikel",
                        "label": article_label or f"Artikel {article_number}".strip(),
                        "number": article_number,
                    }
                )
            continue
        label = _normalize_space(hierarchy.get(kind) or "")
        if label:
            _, number = _classify_structure_heading(label)
            path.append({"kind": kind, "label": label, "number": number or ""})
    return path


def _hierarchy_path_string(path_items: List[Dict[str, str]]) -> str:
    return " > ".join(_normalize_space(item.get("label") or "") for item in path_items if item.get("label"))


def _hierarchy_field_map(path_items: List[Dict[str, str]]) -> Dict[str, str]:
    out: Dict[str, str] = {
        "book_label": "",
        "title_label": "",
        "chapter_label": "",
        "division_label": "",
        "paragraph_label": "",
        "article_label": "",
        "book_number": "",
        "title_number": "",
        "chapter_number": "",
        "division_number": "",
        "paragraph_number": "",
        "article_number": "",
    }
    mapping = {
        "boek": ("book_label", "book_number"),
        "titel": ("title_label", "title_number"),
        "hoofdstuk": ("chapter_label", "chapter_number"),
        "afdeling": ("division_label", "division_number"),
        "paragraaf": ("paragraph_label", "paragraph_number"),
        "artikel": ("article_label", "article_number"),
    }
    for item in path_items:
        fields = mapping.get(str(item.get("kind") or ""))
        if not fields:
            continue
        out[fields[0]] = _normalize_space(item.get("label") or "")
        out[fields[1]] = _normalize_space(item.get("number") or "")
    return out


def _build_document_citation(title: str, identifier: str, aliases: List[str]) -> str:
    short_title = _normalize_space(aliases[0]) if aliases else ""
    if short_title:
        return short_title
    if title:
        return _normalize_space(title)
    return _normalize_space(identifier)


def _build_article_citation(document_citation: str, path_items: List[Dict[str, str]]) -> str:
    segments = [document_citation] if document_citation else []
    for item in path_items:
        label = _normalize_space(item.get("label") or "")
        if not label:
            continue
        if item.get("kind") == "artikel":
            segments.append(label)
        elif item.get("kind") in {"boek", "titel", "hoofdstuk", "afdeling", "paragraaf"}:
            segments.append(label)
    return ", ".join(dict.fromkeys(segment for segment in segments if segment))


def _normalize_historical_versions(
    identifier: str,
    versions: List[Dict[str, str]],
    *,
    current_document_url: str,
    current_info_url: str,
    current_effective_date: str,
) -> List[Dict[str, str]]:
    normalized: List[Dict[str, str]] = []
    seen: Set[str] = set()

    for version in versions:
        effective_date = _normalize_space(version.get("effective_date") or "")
        document_url = _normalize_space(version.get("source_url") or "")
        info_url = document_url if document_url.endswith("/informatie") else f"{document_url.rstrip('/')}/informatie" if document_url else ""
        key = f"{effective_date}|{document_url}|{info_url}"
        if key in seen:
            continue
        seen.add(key)
        normalized.append(
            {
                "identifier": identifier,
                "effective_date": effective_date,
                "label": _normalize_space(version.get("label") or ""),
                "document_url": document_url[:-11] if document_url.endswith("/informatie") else document_url,
                "information_url": info_url,
                "is_current": effective_date == current_effective_date,
            }
        )

    current_key = f"{current_effective_date}|{current_document_url}|{current_info_url}"
    if current_effective_date and current_key not in seen:
        normalized.append(
            {
                "identifier": identifier,
                "effective_date": current_effective_date,
                "label": "Huidige versie",
                "document_url": current_document_url,
                "information_url": current_info_url,
                "is_current": True,
            }
        )

    normalized.sort(key=lambda item: item.get("effective_date", ""))
    return normalized


def _extract_document_structure(content_root: Any) -> Dict[str, Any]:
    parts: List[Dict[str, Any]] = []
    current_part: Optional[Dict[str, Any]] = None
    hierarchy: Dict[str, str] = {}

    for node in content_root.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "li"], recursive=True):
        text = _normalize_space(node.get_text(" ", strip=True))
        if not text:
            continue

        kind, number = _classify_structure_heading(text)
        if kind is not None and (node.name.startswith("h") or kind == "artikel"):
            _clear_lower_hierarchy_levels(hierarchy, kind)
            if kind != "artikel":
                hierarchy[kind] = text
                path_items = _hierarchy_path_items(hierarchy)
                current_part = {
                    "kind": kind,
                    "label": text,
                    "number": number,
                    "hierarchy": dict(hierarchy),
                    "hierarchy_path": path_items,
                    "hierarchy_path_text": _hierarchy_path_string(path_items),
                }
                parts.append(current_part)
            else:
                article_match = _ARTICLE_HEADING_RE.match(text)
                path_items = _hierarchy_path_items(dict(hierarchy), article_number=number or "", article_label=text)
                current_part = {
                    "kind": kind,
                    "label": text,
                    "number": number,
                    "citation": f"Artikel {number}" if number else "Artikel",
                    "heading": _normalize_space(article_match.group(2)) if article_match and article_match.group(2) else "",
                    "hierarchy": dict(hierarchy),
                    "hierarchy_path": path_items,
                    "hierarchy_path_text": _hierarchy_path_string(path_items),
                }
                parts.append(current_part)
            continue

        if current_part is not None:
            _append_text(current_part, text)

    finalized_parts = _finalize_parts(parts)
    articles = [part for part in finalized_parts if str(part.get("kind")) == "artikel"]
    chapters = [
        part
        for part in finalized_parts
        if str(part.get("kind")) in {"boek", "titel", "hoofdstuk", "afdeling", "paragraaf"}
    ]
    return {"parts": finalized_parts, "articles": articles, "chapters": chapters}


def _is_authoritative_url(url: str) -> bool:
    parsed = urlparse(str(url or "").strip())
    return any(pattern.search(parsed.netloc or "") for pattern in _AUTHORITATIVE_HOST_PATTERNS)


def _collect_labeled_values(soup: Any) -> Dict[str, List[str]]:
    values: Dict[str, List[str]] = defaultdict(list)

    for term in soup.select("dt"):
        definition = term.find_next_sibling("dd")
        if definition is None:
            continue
        key = _normalize_space(term.get_text(" ", strip=True)).lower()
        value = _normalize_space(definition.get_text(" ", strip=True))
        if key and value:
            values[key].append(value)

    for row in soup.select("tr"):
        header = row.find(["th", "td"])
        if header is None:
            continue
        cells = row.find_all(["th", "td"])
        if len(cells) < 2:
            continue
        key = _normalize_space(cells[0].get_text(" ", strip=True)).lower()
        value = _normalize_space(" ".join(cell.get_text(" ", strip=True) for cell in cells[1:]))
        if key and value:
            values[key].append(value)

    return dict(values)


def _match_info_label(text: str, key: str) -> str:
    for pattern in _INFO_LABEL_PATTERNS.get(key, []):
        match = pattern.search(text)
        if match:
            return _normalize_space(match.group(1))
    return ""


def _discover_authoritative_source_urls(soup: Any, info_url: str) -> List[str]:
    discovered: List[str] = []
    seen: Set[str] = set()

    for url in [info_url]:
        normalized = str(url or "").strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            discovered.append(normalized)

    for anchor in soup.select("a[href]"):
        href = str(anchor.get("href") or "").strip()
        if not href:
            continue
        absolute = urljoin(info_url or "https://wetten.overheid.nl/", href)
        absolute = absolute.split("#", 1)[0]
        if not _is_authoritative_url(absolute):
            continue
        if absolute in seen:
            continue
        seen.add(absolute)
        discovered.append(absolute)

    return discovered


def _extract_version_history(soup: Any, *, identifier: str, base_url: str) -> List[Dict[str, str]]:
    versions: List[Dict[str, str]] = []
    seen: Set[str] = set()

    for anchor in soup.select("a[href]"):
        href = str(anchor.get("href") or "").strip()
        if not href:
            continue
        absolute = urljoin(base_url or "https://wetten.overheid.nl/", href)
        if identifier and identifier.upper() not in absolute.upper():
            continue
        date_match = re.search(r"/(\d{4}-\d{2}-\d{2})(?:/|$)", absolute)
        if not date_match:
            continue
        normalized = absolute.split("#", 1)[0]
        if normalized in seen:
            continue
        seen.add(normalized)
        label = _normalize_space(anchor.get_text(" ", strip=True))
        versions.append(
            {
                "effective_date": date_match.group(1),
                "label": label,
                "source_url": normalized,
            }
        )

    versions.sort(key=lambda item: item.get("effective_date", ""))
    return versions


def _extract_info_metadata(html: str, *, info_url: str = "") -> Dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    text = _normalize_space(soup.get_text(" ", strip=True))
    labeled_values = _collect_labeled_values(soup)

    title = ""
    title_node = soup.select_one("h1") or soup.select_one("title")
    if title_node is not None:
        title = _normalize_space(title_node.get_text(" ", strip=True))

    regulation_type = (
        next(iter(labeled_values.get("soort regeling", [])), "")
        or _match_info_label(text, "regulation_type")
    )
    identifier = (
        next(iter(labeled_values.get("identificatienummer", [])), "")
        or _match_info_label(text, "identifier")
    ).upper()
    official_title = (
        next(iter(labeled_values.get("officiële titel", [])), "")
        or next(iter(labeled_values.get("officiele titel", [])), "")
        or next(iter(labeled_values.get("opschrift", [])), "")
        or _match_info_label(text, "official_title")
        or title
    )
    cite_title = (
        next(iter(labeled_values.get("citeertitel", [])), "")
        or _match_info_label(text, "cite_title")
    )
    aliases = [_normalize_space(value) for value in [cite_title, title] if _normalize_space(value)]
    aliases = list(dict.fromkeys(alias for alias in aliases if alias and alias != official_title))

    effective_date = _parse_dutch_date(
        next(iter(labeled_values.get("datum inwerkingtreding", [])), "")
        or next(iter(labeled_values.get("inwerkingtreding", [])), "")
        or next(iter(labeled_values.get("geldig van", [])), "")
        or _match_info_label(text, "effective_date")
    )
    publication_date = _parse_dutch_date(
        next(iter(labeled_values.get("datum van uitgifte", [])), "")
        or next(iter(labeled_values.get("publicatiedatum", [])), "")
        or next(iter(labeled_values.get("datum publicatie", [])), "")
        or _match_info_label(text, "publication_date")
    )
    last_modified_date = _parse_dutch_date(
        next(iter(labeled_values.get("laatste wijziging", [])), "")
        or next(iter(labeled_values.get("laatst gewijzigd", [])), "")
        or _match_info_label(text, "last_modified_date")
    )
    authority_sources = _discover_authoritative_source_urls(soup, info_url)
    historical_versions = _extract_version_history(soup, identifier=identifier, base_url=info_url)

    return {
        "title": title,
        "canonical_title": official_title,
        "regulation_type": regulation_type,
        "identifier": identifier,
        "aliases": aliases,
        "effective_date": effective_date,
        "publication_date": publication_date,
        "last_modified_date": last_modified_date,
        "historical_versions": historical_versions,
        "authority_sources": authority_sources,
    }


def _select_content_root(soup: Any) -> Any:
    for selector in _CONTENT_ROOT_SELECTORS:
        node = soup.select_one(selector)
        if node is not None:
            return node
    return soup.body or soup


def _extract_title_and_text(html: str) -> Dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")

    heading = ""
    heading_node = soup.select_one("h1") or soup.select_one("title")
    if heading_node is not None:
        heading = _normalize_space(heading_node.get_text(" ", strip=True))

    content_root = _select_content_root(soup)
    text = _normalize_space(content_root.get_text(" ", strip=True))
    structure = _extract_document_structure(content_root)

    return {
        "title": heading,
        "text": text,
        "structure": structure,
    }


def _build_article_records(document_row: Dict[str, Any]) -> List[Dict[str, Any]]:
    article_records: List[Dict[str, Any]] = []
    canonical_title = str(document_row.get("canonical_title") or document_row.get("title") or "")
    identifier = str(document_row.get("identifier") or "")
    aliases = list(document_row.get("aliases") or [])
    document_citation = _build_document_citation(canonical_title, identifier, aliases)

    for article in document_row.get("articles") or []:
        article_text = _normalize_space(article.get("text") or "")
        article_number = _normalize_space(article.get("number") or "")
        hierarchy_path = list(article.get("hierarchy_path") or [])
        hierarchy_path_text = _hierarchy_path_string(hierarchy_path)
        hierarchy_fields = _hierarchy_field_map(hierarchy_path)
        article_citation = _build_article_citation(document_citation, hierarchy_path)
        if not article_text:
            continue

        article_records.append(
            {
                "record_type": "article",
                "jurisdiction": document_row.get("jurisdiction", "NL"),
                "jurisdiction_name": document_row.get("jurisdiction_name", "Netherlands"),
                "country": document_row.get("country", "Netherlands"),
                "language": document_row.get("language", "nl"),
                "identifier": identifier,
                "official_identifier": document_row.get("official_identifier", identifier),
                "document_identifier": identifier,
                "article_identifier": f"{identifier}:artikel:{article_number or _safe_id_fragment(article.get('label') or '')}",
                "title": canonical_title,
                "canonical_title": canonical_title,
                "aliases": aliases,
                "document_type": document_row.get("document_type", "statute"),
                "text": article_text,
                "source_url": document_row.get("source_url"),
                "information_url": document_row.get("information_url"),
                "effective_date": document_row.get("effective_date", ""),
                "publication_date": document_row.get("publication_date", ""),
                "last_modified_date": document_row.get("last_modified_date", ""),
                "historical_versions": list(document_row.get("historical_versions") or []),
                "article_number": article_number,
                "article_heading": article.get("heading") or "",
                "citation": article_citation,
                "document_citation": document_citation,
                "hierarchy_path": hierarchy_path,
                "hierarchy_path_text": hierarchy_path_text,
                "hierarchy_labels": [item.get("label") for item in hierarchy_path if item.get("label")],
                **hierarchy_fields,
                "scraped_at": document_row.get("scraped_at"),
            }
        )

    return article_records


def _verify_cross_sources(
    session: "requests.Session",
    *,
    law_url: str,
    identifier: str,
    title: str,
    info_metadata: Dict[str, Any],
) -> Dict[str, Any]:
    source_urls = [law_url]
    source_urls.extend(info_metadata.get("authority_sources") or [])
    deduped_urls = list(dict.fromkeys(url for url in source_urls if str(url).strip()))
    verified_sources: List[Dict[str, Any]] = []

    for url in deduped_urls[:3]:
        try:
            response = session.get(url, timeout=40)
            if int(response.status_code) != 200:
                verified_sources.append({"url": url, "status": int(response.status_code), "matched_identifier": False})
                continue
            page_text = _normalize_space(BeautifulSoup(response.text or "", "html.parser").get_text(" ", strip=True))
            title_match = bool(title) and title.lower() in page_text.lower()
            identifier_match = bool(identifier) and identifier.upper() in page_text.upper()
            verified_sources.append(
                {
                    "url": url,
                    "status": int(response.status_code),
                    "matched_identifier": identifier_match,
                    "matched_title": title_match,
                }
            )
        except Exception as exc:
            verified_sources.append({"url": url, "status": "error", "error": str(exc)})

    identifier_matches = [item for item in verified_sources if item.get("matched_identifier") is True]
    return {
        "authoritative_sources_checked": len(verified_sources),
        "authoritative_sources": verified_sources,
        "identifier_consistent": bool(identifier_matches) or not identifier,
        "title_consistent": any(item.get("matched_title") is True for item in verified_sources) or not title,
    }


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
        "dateModified": str(record.get("last_modified_date") or datetime.now().date().isoformat()),
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


def _write_optional_index(rows: Iterable[Dict[str, Any]], *, index_path: Path) -> None:
    _write_index_jsonl(rows, index_path=index_path)


async def list_netherlands_law_sources() -> Dict[str, Any]:
    """List built-in Netherlands law source configs."""
    return {
        "status": "success",
        "count": len(_DEFAULT_SOURCE_CONFIGS),
        "sources": list(_DEFAULT_SOURCE_CONFIGS),
        "verification_sources": [
            {
                "name": "koop_overheid_rijksoverheid_page",
                "url": "https://www.koopoverheid.nl/voor-overheden/rijksoverheid",
                "note": "KOOP describes Overheid.nl as the publication channel for laws and regulations.",
            },
            {
                "name": "wetten_overheid_information_pages",
                "url_template": "https://wetten.overheid.nl/<BWBR-ID>/informatie",
                "note": "Per-document metadata and identifier verification page.",
            },
        ],
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
    article_records: List[Dict[str, Any]] = []
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
            structure = parsed.get("structure") or {}
            info_metadata: Dict[str, Any] = {}
            info_url = ""
            if identifier:
                info_url = f"https://wetten.overheid.nl/{identifier}/informatie"
                try:
                    info_response = session.get(info_url, timeout=40)
                    if int(info_response.status_code) == 200:
                        info_metadata = _extract_info_metadata(info_response.text or "", info_url=info_url)
                except Exception as exc:
                    errors.append(f"{law_url} [informatie]: {exc}")

            canonical_title = str(info_metadata.get("canonical_title") or info_metadata.get("title") or title or identifier)
            resolved_identifier = str(info_metadata.get("identifier") or identifier)
            aliases = list(info_metadata.get("aliases") or [])
            document_citation = _build_document_citation(canonical_title, resolved_identifier, aliases)
            source_verification = _verify_cross_sources(
                session,
                law_url=law_url,
                identifier=resolved_identifier,
                title=canonical_title,
                info_metadata=info_metadata,
            )
            structure_parts = structure.get("parts") or []
            structure_articles = structure.get("articles") or []
            structure_chapters = structure.get("chapters") or []
            normalized_versions = _normalize_historical_versions(
                resolved_identifier,
                list(info_metadata.get("historical_versions") or []),
                current_document_url=law_url,
                current_info_url=info_url,
                current_effective_date=str(info_metadata.get("effective_date") or ""),
            )

            row: Dict[str, Any] = {
                "record_type": "document",
                "jurisdiction": "NL",
                "jurisdiction_name": "Netherlands",
                "country": "Netherlands",
                "language": "nl",
                "identifier": resolved_identifier,
                "official_identifier": resolved_identifier,
                "title": canonical_title or "Netherlands Law",
                "canonical_title": canonical_title or "Netherlands Law",
                "aliases": aliases,
                "text": text,
                "source_url": law_url,
                "information_url": info_url or None,
                "document_type": str(info_metadata.get("regulation_type") or "statute").lower().replace(" ", "_"),
                "citation": document_citation,
                "official_metadata": {
                    "effective_date": info_metadata.get("effective_date") or "",
                    "publication_date": info_metadata.get("publication_date") or "",
                    "last_modified_date": info_metadata.get("last_modified_date") or "",
                },
                "effective_date": str(info_metadata.get("effective_date") or ""),
                "publication_date": str(info_metadata.get("publication_date") or ""),
                "last_modified_date": str(info_metadata.get("last_modified_date") or ""),
                "historical_versions": normalized_versions,
                "article_count": len(structure_articles),
                "chapter_count": len(structure_chapters),
                "articles": structure_articles,
                "chapters": structure_chapters,
                "parts": structure_parts,
                "headings": [part.get("label") for part in structure_parts if str(part.get("kind")) != "artikel"],
                "citations": [part.get("citation") for part in structure_articles if part.get("citation")],
                "scraped_at": datetime.now().isoformat(),
            }
            if include_metadata:
                row["metadata"] = {
                    "host": urlparse(law_url).netloc,
                    "source_system": "wetten.overheid.nl",
                    "info_url": info_url or None,
                    "authority_sources": list(info_metadata.get("authority_sources") or []),
                    "verification": dict(
                        {
                            "document_page_verified": True,
                            "information_page_verified": bool(info_metadata),
                        },
                        **source_verification,
                    ),
                }
            row["article_records"] = _build_article_records(row)
            article_records.extend(row["article_records"])
            records.append(row)
        except Exception as exc:
            errors.append(f"{law_url}: {exc}")
        time.sleep(max(0.0, float(rate_limit_delay)))

    _write_index_jsonl(records, index_path=output_root / DEFAULT_NETHERLANDS_LAWS_INDEX_PATH.name)
    _write_optional_index(
        article_records,
        index_path=output_root / DEFAULT_NETHERLANDS_LAWS_ARTICLE_INDEX_PATH.name,
    )
    _write_optional_index(
        [*records, *article_records],
        index_path=output_root / DEFAULT_NETHERLANDS_LAWS_SEARCH_INDEX_PATH.name,
    )
    jsonld_path = _write_jsonld(records, output_root=output_root)

    elapsed = time.time() - start
    metadata = {
        "seed_urls": selected_seed_urls,
        "seed_url_count": len(selected_seed_urls),
        "crawled_index_pages": crawled_index_pages,
        "explicit_document_urls": selected_document_urls,
        "discovered_document_count": len(ordered_document_urls),
        "records_count": len(records),
        "article_records_count": len(article_records),
        "search_records_count": len(records) + len(article_records),
        "errors": errors,
        "error_count": len(errors),
        "elapsed_time_seconds": elapsed,
        "scraped_at": datetime.now().isoformat(),
        "output_dir": str(output_root),
        "index_path": str(output_root / DEFAULT_NETHERLANDS_LAWS_INDEX_PATH.name),
        "article_index_path": str(output_root / DEFAULT_NETHERLANDS_LAWS_ARTICLE_INDEX_PATH.name),
        "search_index_path": str(output_root / DEFAULT_NETHERLANDS_LAWS_SEARCH_INDEX_PATH.name),
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
            "article_data": [],
            "search_data": [],
            "metadata": metadata,
            "output_format": output_format,
        }

    return {
        "status": "success",
        "data": records,
        "article_data": article_records,
        "search_data": [*records, *article_records],
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
