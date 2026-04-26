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
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict, deque
from typing import Any, Dict, Iterable, List, Optional, Set
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse

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
DEFAULT_NETHERLANDS_LAWS_RUN_METADATA_PATH = (
    DEFAULT_NETHERLANDS_LAWS_DIR / "netherlands_laws_run_metadata_latest.json"
)
USER_AGENT = "ipfs-datasets-netherlands-law-scraper/1.0"

_WS_RE = re.compile(r"\s+")
_WETTEN_HOST_RE = re.compile(r"(^|\.)wetten\.overheid\.nl$", re.IGNORECASE)
_ZOEK_SERVICE_HOST_RE = re.compile(r"(^|\.)zoekservice\.overheid\.nl$", re.IGNORECASE)
_BWB_ID_RE = re.compile(r"/(BWBR[0-9A-Z]+)(?:/|$)", re.IGNORECASE)
_BWB_IDENTIFIER_RE = re.compile(r"\b(BWBR[0-9A-Z]+)\b", re.IGNORECASE)
_ARTICLE_HEADING_RE = re.compile(
    r"^artikel\s+([0-9]+(?:[.:][0-9]+)*(?:[a-z])?)\b(?:\s*(?:(?:[:.\-])\s*|\s+)(.*))?$",
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
_SRU_BWB_ENDPOINT = "https://zoekservice.overheid.nl/sru/Search"
_DEFAULT_SRU_MAXIMUM_RECORDS = 100
_MAX_METADATA_TITLE_CHARS = 300
_MAX_AUTHORITY_SOURCES = 50


def _build_sru_seed_url(query: str, *, start_record: int = 1, maximum_records: int = _DEFAULT_SRU_MAXIMUM_RECORDS) -> str:
    params = {
        "operation": "searchRetrieve",
        "version": "2.0",
        "x-connection": "BWB",
        "query": query,
        "startRecord": str(max(1, int(start_record))),
        "maximumRecords": str(max(1, int(maximum_records))),
    }
    return f"{_SRU_BWB_ENDPOINT}?{urlencode(params)}"


_DEFAULT_DISCOVERY_SEED_URLS: List[str] = [
    _build_sru_seed_url("dcterms.type==wet"),
    _build_sru_seed_url("dcterms.type==rijkswet"),
    _build_sru_seed_url("dcterms.type==AMvB"),
    _build_sru_seed_url("dcterms.type==ministeriele-regeling"),
    "https://wetten.overheid.nl/zoeken",
    "https://wetten.overheid.nl/uitgebreid_zoeken",
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
            "Accept": "application/xml,text/html,application/xhtml+xml,*/*;q=0.8",
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


def _normalize_official_url(url: str) -> str:
    normalized = str(url or "").strip().split("#", 1)[0]
    if not normalized:
        return ""
    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"}:
        return ""
    path = parsed.path or "/"
    if path != "/" and normalized.endswith("/"):
        return normalized
    if "." not in path.rsplit("/", 1)[-1] and not parsed.query and not normalized.endswith("/"):
        return f"{normalized}/"
    return normalized


def _is_supported_law_url(url: str) -> bool:
    parsed = urlparse(str(url or "").strip())
    if parsed.scheme not in {"http", "https"}:
        return False
    if not _WETTEN_HOST_RE.search(parsed.netloc or ""):
        return False
    return bool(_extract_bwb_id(url))


def _is_supported_seed_url(url: str) -> bool:
    parsed = urlparse(str(url or "").strip())
    if parsed.scheme not in {"http", "https"}:
        return False
    if _extract_bwb_id(url):
        return False
    if _WETTEN_HOST_RE.search(parsed.netloc or ""):
        return True
    if _is_sru_bwb_seed_url(url):
        return True
    return False


def _is_sru_bwb_seed_url(url: str) -> bool:
    parsed = urlparse(str(url or "").strip())
    if parsed.scheme not in {"http", "https"}:
        return False
    if not _ZOEK_SERVICE_HOST_RE.search(parsed.netloc or ""):
        return False
    if parsed.path.rstrip("/") != "/sru/Search":
        return False
    qs = parse_qs(parsed.query)
    operation = str((qs.get("operation") or [""])[0]).lower()
    connection = str((qs.get("x-connection") or [""])[0]).upper()
    return operation == "searchretrieve" and connection == "BWB"


def _canonical_law_url_from_identifier(identifier: str) -> str:
    bwb_id = _normalize_space(identifier).upper()
    if not _BWB_IDENTIFIER_RE.fullmatch(bwb_id):
        return ""
    return f"https://wetten.overheid.nl/{bwb_id}/"


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
        normalized = _normalize_official_url(absolute)
        if normalized in seen:
            continue
        seen.add(normalized)
        links.append(normalized)

    return links


def _extract_discovery_links(index_html: str, index_url: str) -> List[str]:
    soup = BeautifulSoup(index_html, "html.parser")
    links: List[str] = []
    seen: Set[str] = set()

    for anchor in soup.select("a[href]"):
        href = str(anchor.get("href") or "").strip()
        if not href:
            continue
        absolute = _normalize_official_url(urljoin(index_url, href))
        if not absolute or not _is_supported_seed_url(absolute):
            continue
        if absolute in seen:
            continue
        seen.add(absolute)
        links.append(absolute)

    return links


def _xml_local_name(tag: str) -> str:
    return str(tag or "").rsplit("}", 1)[-1]


def _seed_response_is_usable(response: Any, seed_url: str) -> bool:
    status = int(getattr(response, "status_code", 0) or 0)
    if status == 200:
        return True
    content_type = str(getattr(response, "headers", {}).get("content-type") or "").lower()
    text = str(getattr(response, "text", "") or "").lstrip()
    return _is_sru_bwb_seed_url(seed_url) and status == 406 and ("xml" in content_type or text.startswith("<?xml"))


def _sru_next_page_url(seed_url: str, next_record_position: int) -> str:
    parsed = urlparse(seed_url)
    pairs = parse_qs(parsed.query)
    pairs["startRecord"] = [str(max(1, int(next_record_position)))]
    if "maximumRecords" not in pairs:
        pairs["maximumRecords"] = [str(_DEFAULT_SRU_MAXIMUM_RECORDS)]
    query = urlencode({key: values[-1] for key, values in pairs.items()})
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, query, ""))


def _extract_sru_document_links(sru_xml: str, seed_url: str) -> tuple[List[str], Optional[str], Dict[str, Any]]:
    """Extract canonical wetten.nl document URLs from official SRU BWB XML."""
    links: List[str] = []
    seen: Set[str] = set()
    metadata: Dict[str, Any] = {
        "number_of_records": None,
        "next_record_position": None,
        "record_positions_seen": 0,
        "identifiers_seen": 0,
    }

    root = ET.fromstring(sru_xml.encode("utf-8") if isinstance(sru_xml, str) else sru_xml)
    for elem in root.iter():
        local_name = _xml_local_name(elem.tag)
        text = _normalize_space(elem.text or "")
        if local_name == "numberOfRecords" and text.isdigit():
            metadata["number_of_records"] = int(text)
            continue
        if local_name == "nextRecordPosition" and text.isdigit():
            metadata["next_record_position"] = int(text)
            continue
        if local_name == "recordPosition":
            metadata["record_positions_seen"] += 1
            continue
        if local_name != "identifier":
            continue
        match = _BWB_IDENTIFIER_RE.search(text)
        if not match:
            continue
        metadata["identifiers_seen"] += 1
        law_url = _canonical_law_url_from_identifier(match.group(1))
        if not law_url or law_url in seen:
            continue
        seen.add(law_url)
        links.append(law_url)

    next_url = None
    next_position = metadata.get("next_record_position")
    total_records = metadata.get("number_of_records")
    if isinstance(next_position, int) and (not isinstance(total_records, int) or next_position <= total_records):
        next_url = _sru_next_page_url(seed_url, next_position)

    return links, next_url, metadata


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


def _build_canonical_law_url(identifier: str) -> str:
    normalized = _normalize_space(identifier).upper()
    return f"https://wetten.overheid.nl/{normalized}/" if normalized else ""


def _extract_version_date_from_url(url: str) -> str:
    match = re.search(r"/(\d{4}-\d{2}-\d{2})(?:/|$)", str(url or ""))
    return match.group(1) if match else ""


def _build_versioned_law_url(identifier: str, effective_date: str, fallback_url: str = "") -> str:
    parsed_date = _parse_dutch_date(effective_date)
    if identifier and parsed_date:
        return f"https://wetten.overheid.nl/{identifier.upper()}/{parsed_date}/0/"
    return _normalize_space(fallback_url)


def _version_identifier(identifier: str, effective_date: str) -> str:
    parsed_date = _parse_dutch_date(effective_date)
    if identifier and parsed_date:
        return f"{identifier.upper()}@{parsed_date}"
    return _normalize_space(identifier).upper()


def _infer_version_end_date(current_start: str, next_start: str) -> str:
    current_date = _parse_dutch_date(current_start)
    next_date = _parse_dutch_date(next_start)
    if not current_date or not next_date:
        return ""
    try:
        return (datetime.strptime(next_date, "%Y-%m-%d").date() - timedelta(days=1)).isoformat()
    except ValueError:
        return ""


def _normalize_historical_versions(
    identifier: str,
    versions: List[Dict[str, str]],
    *,
    current_document_url: str,
    current_info_url: str,
    current_effective_date: str,
) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    canonical_law_url = _build_canonical_law_url(identifier)

    for version in versions:
        effective_date = _normalize_space(version.get("effective_date") or "")
        document_url = _normalize_space(version.get("source_url") or "")
        versioned_document_url = document_url[:-11] if document_url.endswith("/informatie") else document_url
        info_url = document_url if document_url.endswith("/informatie") else f"{versioned_document_url.rstrip('/')}/informatie" if versioned_document_url else ""
        key = f"{effective_date}|{document_url}|{info_url}"
        if key in seen:
            continue
        seen.add(key)
        normalized.append(
            {
                "identifier": identifier,
                "law_identifier": identifier,
                "law_version_identifier": _version_identifier(identifier, effective_date),
                "version_specific_identifier": _version_identifier(identifier, effective_date),
                "effective_date": effective_date,
                "version_start_date": effective_date,
                "version_end_date": "",
                "label": _normalize_space(version.get("label") or ""),
                "canonical_law_url": canonical_law_url,
                "document_url": versioned_document_url,
                "canonical_document_url": canonical_law_url,
                "versioned_law_url": versioned_document_url or _build_versioned_law_url(identifier, effective_date),
                "information_url": info_url,
                "is_current": effective_date == current_effective_date,
            }
        )

    current_key = f"{current_effective_date}|{current_document_url}|{current_info_url}"
    if current_effective_date and current_key not in seen:
        normalized.append(
            {
                "identifier": identifier,
                "law_identifier": identifier,
                "law_version_identifier": _version_identifier(identifier, current_effective_date),
                "version_specific_identifier": _version_identifier(identifier, current_effective_date),
                "effective_date": current_effective_date,
                "version_start_date": current_effective_date,
                "version_end_date": "",
                "label": "Huidige versie",
                "canonical_law_url": canonical_law_url,
                "document_url": current_document_url,
                "canonical_document_url": canonical_law_url,
                "versioned_law_url": _build_versioned_law_url(identifier, current_effective_date, current_document_url),
                "information_url": current_info_url,
                "is_current": True,
            }
        )

    normalized.sort(key=lambda item: item.get("effective_date", ""))
    for index, version in enumerate(normalized):
        next_effective_date = normalized[index + 1]["effective_date"] if index + 1 < len(normalized) else ""
        version["version_end_date"] = _infer_version_end_date(version.get("version_start_date", ""), next_effective_date)
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
    if not any(str(part.get("kind")) == "artikel" for part in finalized_parts):
        fallback_text = _normalize_space(content_root.get_text(" ", strip=True))
        fallback_match = re.search(
            r"\b(artikel\s+([0-9]+(?:[.:][0-9]+)*(?:[a-z])?))\b(.*)$",
            fallback_text,
            re.IGNORECASE,
        )
        if fallback_match:
            article_label = _normalize_space(fallback_match.group(1))
            article_number = _normalize_space(fallback_match.group(2))
            article_body = _normalize_space(fallback_match.group(3))
            path_items = _hierarchy_path_items({}, article_number=article_number, article_label=article_label)
            finalized_parts.append(
                {
                    "kind": "artikel",
                    "label": article_label,
                    "number": article_number,
                    "citation": f"Artikel {article_number}" if article_number else "Artikel",
                    "heading": "",
                    "hierarchy": {},
                    "hierarchy_path": path_items,
                    "hierarchy_path_text": _hierarchy_path_string(path_items),
                    "text": article_body,
                }
            )
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


def _metadata_value_is_reasonable(value: str, *, max_chars: int = _MAX_METADATA_TITLE_CHARS) -> bool:
    normalized = _normalize_space(value)
    if not normalized or len(normalized) > max_chars:
        return False
    lowered = normalized.lower()
    if lowered.startswith("de citeertitel is"):
        return False
    repeated_labels = [
        "soort regeling",
        "identificatienummer",
        "rechtsgebied",
        "overheidsthema",
        "wetsfamilie",
        "wetstechnische informatie",
    ]
    return sum(1 for label in repeated_labels if label in lowered) <= 1


def _first_reasonable_metadata_value(*values: str, max_chars: int = _MAX_METADATA_TITLE_CHARS) -> str:
    for value in values:
        normalized = _normalize_space(value)
        if _metadata_value_is_reasonable(normalized, max_chars=max_chars):
            return normalized
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
        if len(discovered) >= _MAX_AUTHORITY_SOURCES:
            break

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
    official_title = _first_reasonable_metadata_value(
        next(iter(labeled_values.get("officiële titel", [])), ""),
        next(iter(labeled_values.get("officiele titel", [])), ""),
        next(iter(labeled_values.get("opschrift", [])), ""),
        next(iter(labeled_values.get("niet officiële titel", [])), ""),
        next(iter(labeled_values.get("niet officiele titel", [])), ""),
        _match_info_label(text, "official_title"),
        title,
    )
    cite_title = _first_reasonable_metadata_value(
        next(iter(labeled_values.get("citeertitel", [])), ""),
        _match_info_label(text, "cite_title"),
        max_chars=200,
    )
    aliases = [_normalize_space(value) for value in [cite_title, title] if _normalize_space(value)]
    aliases = list(dict.fromkeys(alias for alias in aliases if alias and alias != official_title))

    effective_date = _parse_dutch_date(
        next(iter(labeled_values.get("datum inwerkingtreding", [])), "")
        or next(iter(labeled_values.get("datum van inwerkingtreding", [])), "")
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
    law_identifier = str(document_row.get("law_identifier") or identifier)
    version_date = str(document_row.get("version_start_date") or document_row.get("effective_date") or "")
    law_version_identifier = str(
        document_row.get("law_version_identifier") or _version_identifier(law_identifier, version_date)
    )

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
                "law_identifier": law_identifier,
                "law_version_identifier": law_version_identifier,
                "version_specific_identifier": law_version_identifier,
                "document_identifier": law_identifier,
                "document_version_identifier": law_version_identifier,
                "article_identifier": (
                    f"{law_version_identifier}:artikel:{article_number or _safe_id_fragment(article.get('label') or '')}"
                ),
                "title": canonical_title,
                "canonical_title": canonical_title,
                "aliases": aliases,
                "document_type": document_row.get("document_type", "statute"),
                "text": article_text,
                "source_url": document_row.get("source_url"),
                "canonical_law_url": document_row.get("canonical_law_url"),
                "canonical_document_url": document_row.get("canonical_document_url"),
                "versioned_law_url": document_row.get("versioned_law_url"),
                "information_url": document_row.get("information_url"),
                "effective_date": document_row.get("effective_date", ""),
                "version_start_date": document_row.get("version_start_date", ""),
                "version_end_date": document_row.get("version_end_date", ""),
                "is_current": bool(document_row.get("is_current", False)),
                "publication_date": document_row.get("publication_date", ""),
                "last_modified_date": document_row.get("last_modified_date", ""),
                "historical_version_count": len(list(document_row.get("historical_versions") or [])),
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


def _write_run_metadata(metadata: Dict[str, Any], *, output_root: Path) -> Path:
    out_path = output_root / DEFAULT_NETHERLANDS_LAWS_RUN_METADATA_PATH.name
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as handle:
        json.dump(metadata, handle, ensure_ascii=False, indent=2)
    return out_path


def _load_existing_record_map(index_path: Path) -> Dict[str, Dict[str, Any]]:
    existing: Dict[str, Dict[str, Any]] = {}
    if not index_path.exists():
        return existing

    try:
        with index_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                text = line.strip()
                if not text:
                    continue
                try:
                    row = json.loads(text)
                except json.JSONDecodeError:
                    continue
                identifier = _normalize_space(row.get("identifier") or "")
                if identifier:
                    existing[identifier] = row
                    continue
                source_url = _normalize_space(row.get("source_url") or "")
                if source_url:
                    existing[source_url] = row
    except OSError:
        return {}

    return existing


async def list_netherlands_law_sources() -> Dict[str, Any]:
    """List built-in Netherlands law source configs."""
    return {
        "status": "success",
        "count": len(_DEFAULT_SOURCE_CONFIGS),
        "sources": list(_DEFAULT_SOURCE_CONFIGS),
        "verification_sources": [
            {
                "name": "koop_overheid_sru_bwb",
                "url": "https://zoekservice.overheid.nl/sru/Search?operation=searchRetrieve&version=2.0&x-connection=BWB&query=dcterms.type==wet",
                "note": "Official KOOP/Overheid SRU endpoint for the Basiswettenbestand; supports pagination with startRecord and maximumRecords.",
            },
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
    max_seed_pages: int = 25,
    crawl_depth: int = 2,
    use_default_seeds: bool = False,
    skip_existing: bool = False,
    resume: bool = False,
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
        max_seed_pages: Bounded count of official discovery pages to visit.
        crawl_depth: Maximum discovery-link depth from the provided seed pages.
        use_default_seeds: Add built-in official discovery pages when explicit seeds are not provided.
        skip_existing: Skip laws already present in the on-disk document index.
        resume: Alias for ``skip_existing`` with run metadata preserved across reruns.
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
    skip_existing = bool(skip_existing or resume)

    selected_seed_urls: List[str] = []
    selected_document_urls: List[str] = []

    for item in list(custom_sources or []):
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
    if use_default_seeds or (not selected_seed_urls and not selected_document_urls):
        selected_seed_urls.extend(_DEFAULT_DISCOVERY_SEED_URLS)

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
    skipped_documents: List[str] = []
    discovered_document_urls: Set[str] = set()
    candidate_document_links: Set[str] = set()
    candidate_link_total = 0
    seed_page_details: List[Dict[str, Any]] = []
    session = _make_session()
    seed_visit_count = 0
    successful_document_fetches = 0
    successful_parses = 0
    failed_documents = 0
    failed_seed_pages = 0
    existing_record_map = _load_existing_record_map(output_root / DEFAULT_NETHERLANDS_LAWS_INDEX_PATH.name)

    normalized_seed_urls = list(
        dict.fromkeys(
            _normalize_official_url(url)
            for url in selected_seed_urls
            if _normalize_official_url(url) and _is_supported_seed_url(_normalize_official_url(url))
        )
    )
    seed_queue: deque[tuple[str, int]] = deque((url, 0) for url in normalized_seed_urls)
    seen_seed_urls: Set[str] = set()

    while seed_queue and seed_visit_count < max(0, int(max_seed_pages or 0)):
        index_url, depth = seed_queue.popleft()
        if index_url in seen_seed_urls:
            continue
        seen_seed_urls.add(index_url)
        try:
            response = session.get(index_url, timeout=40)
            if not _seed_response_is_usable(response, index_url):
                raise RuntimeError(f"HTTP {response.status_code} for {index_url}")
            crawled_index_pages.append(index_url)
            seed_visit_count += 1

            document_links: List[str] = []
            discovery_links: List[str] = []
            seed_detail: Dict[str, Any] = {
                "url": index_url,
                "depth": depth,
                "status_code": int(response.status_code),
                "source_type": "sru_bwb" if _is_sru_bwb_seed_url(index_url) else "html",
            }
            if _is_sru_bwb_seed_url(index_url):
                document_links, next_sru_url, sru_metadata = _extract_sru_document_links(response.text or "", index_url)
                seed_detail.update(sru_metadata)
                if next_sru_url and next_sru_url not in seen_seed_urls:
                    seed_queue.append((next_sru_url, depth))
            else:
                document_links = _extract_document_links(response.text or "", index_url)
                if depth < max(0, int(crawl_depth or 0)):
                    discovery_links = _extract_discovery_links(response.text or "", index_url)

            seed_detail["document_links_found"] = len(document_links)
            seed_detail["discovery_links_found"] = len(discovery_links)
            seed_page_details.append(seed_detail)
            for discovered in document_links:
                candidate_link_total += 1
                candidate_document_links.add(discovered)
                discovered_document_urls.add(discovered)
            for linked_seed_url in discovery_links:
                if linked_seed_url not in seen_seed_urls:
                    seed_queue.append((linked_seed_url, depth + 1))
        except Exception as exc:
            failed_seed_pages += 1
            errors.append(f"{index_url}: {exc}")
        time.sleep(max(0.0, float(rate_limit_delay)))

    for url in selected_document_urls:
        if _is_supported_law_url(url):
            normalized_url = _normalize_official_url(url)
            candidate_link_total += 1
            candidate_document_links.add(normalized_url)
            discovered_document_urls.add(normalized_url)
        else:
            errors.append(f"{url}: unsupported Netherlands law URL")

    all_discovered_document_urls = sorted(discovered_document_urls, key=lambda value: (_extract_bwb_id(value), value))
    discovered_law_identifiers = sorted({_extract_bwb_id(url) for url in all_discovered_document_urls if _extract_bwb_id(url)})
    ordered_document_urls = list(all_discovered_document_urls)
    if max_documents and max_documents > 0:
        ordered_document_urls = ordered_document_urls[: int(max_documents)]

    for law_url in ordered_document_urls:
        identifier = _extract_bwb_id(law_url)
        if skip_existing and (
            identifier in existing_record_map
            or law_url in existing_record_map
        ):
            skipped_documents.append(law_url)
            continue
        try:
            response = session.get(law_url, timeout=40)
            if int(response.status_code) != 200:
                raise RuntimeError(f"HTTP {response.status_code} for {law_url}")
            successful_document_fetches += 1

            parsed = _extract_title_and_text(response.text or "")
            title = str(parsed.get("title") or "").strip()
            text = str(parsed.get("text") or "").strip()
            if not text:
                raise RuntimeError("No law text extracted")

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
                "law_identifier": resolved_identifier,
                "official_identifier": resolved_identifier,
                "law_version_identifier": _version_identifier(resolved_identifier, str(info_metadata.get("effective_date") or "")),
                "version_specific_identifier": _version_identifier(resolved_identifier, str(info_metadata.get("effective_date") or "")),
                "title": canonical_title or "Netherlands Law",
                "canonical_title": canonical_title or "Netherlands Law",
                "aliases": aliases,
                "text": text,
                "source_url": law_url,
                "canonical_law_url": _build_canonical_law_url(resolved_identifier),
                "canonical_document_url": _build_canonical_law_url(resolved_identifier),
                "versioned_law_url": _build_versioned_law_url(
                    resolved_identifier,
                    str(info_metadata.get("effective_date") or ""),
                    law_url,
                ),
                "information_url": info_url or None,
                "document_type": str(info_metadata.get("regulation_type") or "statute").lower().replace(" ", "_"),
                "citation": document_citation,
                "official_metadata": {
                    "effective_date": info_metadata.get("effective_date") or "",
                    "publication_date": info_metadata.get("publication_date") or "",
                    "last_modified_date": info_metadata.get("last_modified_date") or "",
                },
                "effective_date": str(info_metadata.get("effective_date") or ""),
                "version_start_date": str(info_metadata.get("effective_date") or ""),
                "version_end_date": "",
                "is_current": True,
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
            article_records.extend(_build_article_records(row))
            records.append(row)
            successful_parses += 1
        except Exception as exc:
            failed_documents += 1
            errors.append(f"{law_url}: {exc}")
        time.sleep(max(0.0, float(rate_limit_delay)))

    persisted_records = list(existing_record_map.values()) if skip_existing else []
    if records:
        replacement_keys = {
            _normalize_space(row.get("identifier") or row.get("source_url") or "")
            for row in records
            if _normalize_space(row.get("identifier") or row.get("source_url") or "")
        }
        if persisted_records and replacement_keys:
            persisted_records = [
                row
                for row in persisted_records
                if _normalize_space(row.get("identifier") or row.get("source_url") or "") not in replacement_keys
            ]
    persisted_records.extend(records)
    persisted_article_records: List[Dict[str, Any]] = []
    for row in persisted_records:
        if str(row.get("record_type") or "") != "document":
            continue
        persisted_article_records.extend(list(row.get("article_records") or _build_article_records(row)))

    _write_index_jsonl(persisted_records, index_path=output_root / DEFAULT_NETHERLANDS_LAWS_INDEX_PATH.name)
    _write_optional_index(
        persisted_article_records,
        index_path=output_root / DEFAULT_NETHERLANDS_LAWS_ARTICLE_INDEX_PATH.name,
    )
    _write_optional_index(
        [*persisted_records, *persisted_article_records],
        index_path=output_root / DEFAULT_NETHERLANDS_LAWS_SEARCH_INDEX_PATH.name,
    )
    jsonld_path = _write_jsonld(persisted_records, output_root=output_root)

    elapsed = time.time() - start
    metadata = {
        "seed_urls": normalized_seed_urls,
        "seed_url_count": len(normalized_seed_urls),
        "crawled_index_pages": crawled_index_pages,
        "seed_page_details": seed_page_details,
        "seed_pages_visited": seed_visit_count,
        "seed_pages_failed": failed_seed_pages,
        "explicit_document_urls": selected_document_urls,
        "candidate_links_found": candidate_link_total,
        "candidate_links_unique": len(candidate_document_links),
        "official_law_documents_accepted": len(all_discovered_document_urls),
        "unique_laws_discovered": len(discovered_law_identifiers),
        "discovered_law_identifiers": discovered_law_identifiers,
        "discovered_document_count": len(all_discovered_document_urls),
        "documents_selected_for_fetch": len(ordered_document_urls),
        "documents_fetched": successful_document_fetches,
        "documents_parsed": successful_parses,
        "documents_skipped": len(skipped_documents),
        "documents_failed": failed_documents,
        "skipped_document_urls": skipped_documents,
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
        "max_seed_pages": max_seed_pages,
        "crawl_depth": crawl_depth,
        "rate_limit_delay": rate_limit_delay,
        "skip_existing": skip_existing,
        "resume": bool(resume),
        "persisted_records_count": len(persisted_records),
        "persisted_article_records_count": len(persisted_article_records),
    }
    metadata_path = _write_run_metadata(metadata, output_root=output_root)
    metadata["run_metadata_path"] = str(metadata_path)

    if not records and not persisted_records:
        return {
            "status": "error",
            "error": "No Netherlands law records were scraped",
            "data": [],
            "article_data": [],
            "search_data": [],
            "metadata": metadata,
            "output_format": output_format,
        }

    if not records and persisted_records:
        return {
            "status": "success",
            "data": [],
            "article_data": [],
            "search_data": [],
            "metadata": metadata,
            "output_format": output_format,
            "note": "No new Netherlands laws were scraped; existing on-disk corpus was preserved.",
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
    "_extract_sru_document_links",
    "_extract_title_and_text",
]
