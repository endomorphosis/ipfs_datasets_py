"""Official Maryland Constitution StatuteText / GetNext parser.

Adapted from Vaquill-AI/open-us-law ``ingest_state_constitutions.scrape_md``
(Apache-2.0). mgaleg serves constitution codes (``c0``, ``c1``, ``c11a``)
through the same Articles dropdown and GetNext walk as the statutes; statute
``g*`` codes are filtered out. ``c0`` is the Declaration of Rights (article
id ``DR``), not ``art. c0, § N``.

Local dumps: ``MARYLAND_CONSTITUTION_HTML`` (StatuteText page and/or TOC)
and optional ``MARYLAND_CONSTITUTION_TOC_HTML``. No live GetNext walk.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from .base_scraper import NormalizedStatute, StatuteMetadata

MD_SECTION_URL = "https://mgaleg.maryland.gov/mgawebsite/Laws/StatuteText"
_MD_ARTICLES_SELECT_RE = re.compile(
    r'<select[^>]*id="Articles"[^>]*>(.*?)</select>', re.DOTALL | re.IGNORECASE
)
_MD_OPTION_RE = re.compile(r'<option[^>]+value="([^"]+)"[^>]*>([^<]+)</option>', re.IGNORECASE)
_MD_CONST_CODE_RE = re.compile(r"^c[a-z0-9]*$", re.IGNORECASE)
_MD_API_STRING_RE = re.compile(r"<string[^>]*>([^<]*)</string>", re.IGNORECASE)
_MD_ARTICLE_LABEL_RE = re.compile(r"^([IVXLC]+(?:-[A-Z])?)\s*-\s*(.+)$")
_RESERVED = re.compile(r"\b(repealed|expired|reserved|renumbered|transferred)\b", re.IGNORECASE)
_WS = re.compile(r"\s+")


def parse_get_next_envelope(body: str) -> Optional[str]:
    """Parse the .NET XML ``<string>`` envelope from GetNext/GetPrevious."""

    text = (body or "").strip()
    if not text:
        return None
    match = _MD_API_STRING_RE.search(text)
    value = match.group(1).strip() if match else text.strip('"').strip()
    if not value or value.lower() == "null":
        return None
    return value


def constitution_articles(html: str) -> List[Tuple[str, str, str]]:
    """Return ``(code, article_id, article_title)`` for ``c*`` dropdown rows."""

    match = _MD_ARTICLES_SELECT_RE.search(html or "")
    if not match:
        return []
    out: List[Tuple[str, str, str]] = []
    for code, display in _MD_OPTION_RE.findall(match.group(1)):
        code = code.strip()
        display = display.strip()
        if not code or not display or not _MD_CONST_CODE_RE.match(code):
            continue
        name = display.split(" - (")[0].strip()
        label_match = _MD_ARTICLE_LABEL_RE.match(name)
        if label_match:
            art_id, art_title = label_match.group(1), label_match.group(2)
        else:
            art_id, art_title = "DR", name
        out.append((code, art_id, art_title))
    return out


def _article_section_from_html(soup, source_url: str) -> Tuple[str, str]:
    query = parse_qs(urlparse(source_url or "").query)
    article = (query.get("article") or [""])[0].strip()
    section = (query.get("section") or [""])[0].strip()
    for name, bucket in (("article", "article"), ("section", "section")):
        node = soup.find("input", attrs={"name": name}) or soup.find("input", id=name)
        if node is not None:
            value = str(node.get("value") or "").strip()
            if value:
                if bucket == "article" and not article:
                    article = value
                if bucket == "section" and not section:
                    section = value
    return article, section


def parse_maryland_constitution_section_html(
    html: str,
    *,
    code_name: str = "Maryland Constitution",
    source_url: str = "",
    article_id: str = "",
    section_code: str = "",
) -> Optional[NormalizedStatute]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return None
    soup = BeautifulSoup(html or "", "html.parser")
    stat = soup.find(id="StatuteText")
    if stat is None:
        return None
    raw = stat.get_text("\n")
    if "File Not Found" in raw:
        return None
    if _RESERVED.search(raw) and len(raw.strip()) < 200:
        return None
    for tag in stat.find_all("div", class_="row"):
        tag.decompose()
    for tag in stat.find_all("div", style=re.compile(r"text-align\s*:\s*center", re.I)):
        tag.decompose()
    body = _WS.sub(" ", stat.get_text(" ")).strip()
    body = re.sub(r"^\s*§\s*[\w.\-]+\.\s*", "", body)
    if len(body) < 40:
        return None
    if _RESERVED.search(body[:160]):
        return None
    article, section = _article_section_from_html(soup, source_url)
    article = article or article_id
    section = section or section_code
    if not section:
        head = re.search(r"§\s*([\w.\-]+)\.", raw)
        if head:
            section = head.group(1)
    if not section:
        return None
    articles = constitution_articles(html)
    code = article.lower()
    resolved_id = "DR" if code in {"c0", "dr"} else (article_id or article or "I")
    for opt_code, opt_id, _title in articles:
        if opt_code.lower() == code:
            resolved_id = opt_id
            break
    if resolved_id == "DR" or code == "c0":
        cite = f"Md. Const., Decl. of Rights art. {section}"
        resolved_id = "DR"
    else:
        cite = f"Md. Const. art. {resolved_id}, § {section}"
    return NormalizedStatute(
        state_code="MD",
        state_name="Maryland",
        statute_id=cite,
        code_name=code_name,
        title_number=resolved_id,
        section_number=section,
        section_name=(body.split(".", 1)[0] or f"Section {section}")[:200],
        full_text=body,
        source_url=source_url
        or f"{MD_SECTION_URL}?article={article or 'c1'}&section={section}&enactments=false",
        official_cite=cite,
        metadata=StatuteMetadata(),
        structured_data={
            "source_kind": "official_maryland_constitution_html",
            "source_authority_class": "official",
            "discovery_method": "mgaleg_constitution_statute_text",
            "article_id": resolved_id,
            "article_code": article.lower() if article else None,
            "skip_hydrate": True,
        },
    )


def configured_constitution_html_path() -> Optional[Path]:
    raw = str(os.environ.get("MARYLAND_CONSTITUTION_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


def configured_constitution_toc_path() -> Optional[Path]:
    raw = str(os.environ.get("MARYLAND_CONSTITUTION_TOC_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


def parse_configured_maryland_constitution(
    *,
    code_name: str = "Maryland Constitution",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    path = configured_constitution_html_path()
    if path is None:
        return []
    html = path.read_text(encoding="utf-8", errors="replace")
    row = parse_maryland_constitution_section_html(html, code_name=code_name)
    if row is None:
        return []
    return [row] if max_statutes is None or int(max_statutes) >= 1 else []
