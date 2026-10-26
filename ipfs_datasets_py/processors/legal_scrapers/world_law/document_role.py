"""Label one row as a law, a metadata card, or an informative website page.

The label does not drop the row and does not rewrite the text. Two or more
title, chapter, part, article, or section headings stay a law. A short
operative sentence such as "Les lois" stays a law. Title-only cards and
site pages are labels a later query can read.
"""

from __future__ import annotations

import re
from typing import Mapping
from urllib.parse import urlsplit

ROLES = frozenset({"law", "metadata", "informative"})

_STRUCTURAL = frozenset({"title", "chapter", "part", "article", "section"})
_CATALOG_TYPES = frozenset({
    "catalog",
    "index",
    "metadata",
    "toc",
    "contents",
    "navigation",
})
_SITE_TYPES = frozenset({
    "website",
    "homepage",
    "search",
    "about",
    "contact",
    "blog",
    "newsletter",
})
_SITE_ENDPOINTS = frozenset({
    "search",
    "sitemap",
    "cookie",
    "cookies",
    "cookie-policy",
    "about",
    "contact",
    "faq",
    "login",
    "signin",
    "privacy-policy",
})
_CHROME_LINES = frozenset({
    "home",
    "search",
    "sitemap",
    "cookie policy",
    "cookies",
    "contact",
    "contact us",
    "about",
    "about us",
    "skip to content",
    "main menu",
    "sign in",
    "log in",
    "login",
    "newsletter",
    "privacy policy",
    "menu",
})
_STATUTORY = re.compile(
    r"(?i)\b(?:shall|hereby|s'applique|gilt|enacted|pursuant)\b|يجب|بموجب"
)
_WS = re.compile(r"\s+")
_SCAN_LIMIT = 200_000


def classify_document_role(row: Mapping[str, object]) -> tuple[str, str]:
    """Return ``(role, reason)`` for one source row or legal record.

    ``role`` is ``law``, ``metadata``, or ``informative``. The text is only
    read. Callers keep the original characters.
    """

    text = _text(row)
    if not text:
        return "metadata", "null_text"
    title = _first(row, "title", "title_native", "instrument_title", "html_title")
    if _title_shell(text, title):
        return "metadata", "title_shell"
    language = _first(row, "language")
    headings = _structural_headings(text, language)
    if headings >= 2:
        return "law", "legal_headings"
    doc_type = _doc_type(row)
    if doc_type in _CATALOG_TYPES and not _statutory(text):
        return "metadata", "catalog_type"
    if doc_type in _SITE_TYPES and not _statutory(text):
        return "informative", "site_type"
    url = _first(row, "source_url", "original_url", "url")
    if _chrome_lines(text) >= 3 and not _long_line(text):
        return "informative", "site_chrome"
    if _site_endpoint(url) and not _statutory(text) and not _long_line(text):
        return "informative", "site_page"
    return "law", "operative_text"


def _text(row: Mapping[str, object]) -> str:
    value = row.get("text")
    if value is None:
        value = row.get("body")
    if not isinstance(value, str):
        return ""
    return value.strip()


def _first(row: Mapping[str, object], *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _compact(value: str) -> str:
    return _WS.sub(" ", value).strip().casefold()


def _title_shell(text: str, title: str) -> bool:
    folded_title = _compact(title)
    folded_text = _compact(text)
    if len(folded_title) < 24 or not folded_text:
        return False
    return folded_text == folded_title or folded_text == f"{folded_title} {folded_title}"


def _structural_headings(text: str, language: str) -> int:
    from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.structure import (
        segment_exclusive,
    )

    sample = text if len(text) <= _SCAN_LIMIT else text[:_SCAN_LIMIT]
    count = 0
    for unit in segment_exclusive(sample, language=language):
        if unit.kind in _STRUCTURAL and (unit.number or "").strip():
            count += 1
            if count >= 2:
                return count
    return count


def _statutory(text: str) -> bool:
    return _STATUTORY.search(text) is not None


def _doc_type(row: Mapping[str, object]) -> str:
    found: list[str] = []
    for key in ("doc_type", "instrument_type"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            found.append(value.strip().casefold())
    for value in found:
        if value in _CATALOG_TYPES or value in _SITE_TYPES:
            return value
    return found[0] if found else ""


def _chrome_lines(text: str) -> int:
    count = 0
    for raw in text.splitlines():
        line = _compact(raw)
        if line in _CHROME_LINES or line.startswith("this website uses cookies"):
            count += 1
        elif line.startswith("this site uses cookies"):
            count += 1
    return count


def _long_line(text: str) -> bool:
    for raw in text.splitlines():
        line = raw.strip()
        folded = _compact(line)
        if len(line) > 160 and folded not in _CHROME_LINES:
            return True
    return False


def _site_endpoint(url: str) -> bool:
    if not url:
        return False
    path = urlsplit(url).path
    segments = [segment.casefold() for segment in path.split("/") if segment]
    if not segments:
        return False
    return segments[-1] in _SITE_ENDPOINTS
