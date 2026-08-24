"""Official Connecticut chapter HTML parser (inline #sec_* siblings).

Adapted from Vaquill-AI/open-us-law ``scrapeCT.py`` (Apache-2.0).
Walk siblings from each ``#sec_*`` heading until ``nav_tbl``, the next
``toc_catchln`` / ``span.catchln``, or the next ``sec_*`` anchor.
``source-first`` / ``history-first`` paragraphs are dropped.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional, Tuple

from .base_scraper import NormalizedStatute, StatuteMetadata

BASE_PUB = "https://www.cga.ct.gov/current/pub"
_RESERVED = re.compile(
    r"\((?:repealed|expired|reserved|renumbered|transferred)\)",
    re.IGNORECASE,
)
_ANCHOR_RE = re.compile(r"^sec_([A-Za-z0-9][A-Za-z0-9._\-]*)$")
_SEC_ID_RE = re.compile(r"^sec_")
_WS = re.compile(r"\s+")
_HEADING_RE = re.compile(
    r"Sec\.\s*(?P<num>[A-Za-z0-9][A-Za-z0-9._\-]*)\.\s*(?P<head>.*)$",
    re.IGNORECASE,
)


_TITLE_HREF_RE = re.compile(r"title_([0-9a-z]+)\.htm$", re.IGNORECASE)
_CHAPTER_HREF_RE = re.compile(r"chap_([0-9a-z]+)\.htm$", re.IGNORECASE)


def titles_from_index(html: str, *, base_url: str = BASE_PUB) -> List[Tuple[str, str]]:
    """Title numbers and URLs from ``titles.htm`` (``toc_ttl_desig`` / title_N.htm)."""

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    from urllib.parse import urljoin

    soup = BeautifulSoup(html or "", "html.parser")
    out: List[Tuple[str, str]] = []
    seen = set()
    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href") or "").strip()
        match = _TITLE_HREF_RE.search(href)
        if not match:
            continue
        number = match.group(1).lstrip("0") or match.group(1)
        if number in seen:
            continue
        seen.add(number)
        out.append((urljoin(base_url.rstrip("/") + "/", href), number))
    return out


def chapters_from_title(html: str, *, base_url: str = BASE_PUB) -> List[Tuple[str, str]]:
    """Chapter URLs from a title page (``toc_ch_link`` / chap_NNN.htm)."""

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    from urllib.parse import urljoin

    soup = BeautifulSoup(html or "", "html.parser")
    out: List[Tuple[str, str]] = []
    seen = set()
    anchors = soup.find_all("a", class_="toc_ch_link") or soup.find_all("a", href=True)
    for anchor in anchors:
        href = str(anchor.get("href") or "").strip()
        match = _CHAPTER_HREF_RE.search(href)
        if not match:
            continue
        number = match.group(1).lstrip("0") or match.group(1)
        if number in seen:
            continue
        seen.add(number)
        out.append((urljoin(base_url.rstrip("/") + "/", href), number))
    return out


def chapter_url(chapter: str) -> str:
    token = str(chapter or "").strip().lower().zfill(3)
    if token.isdigit():
        token = token.zfill(3)
    return f"{BASE_PUB}/chap_{token}.htm"


def _clean(text: str) -> str:
    return _WS.sub(" ", (text or "").replace("\xa0", " ")).strip()


def _anchor_number(anchor_id: str) -> Optional[str]:
    match = _ANCHOR_RE.match(str(anchor_id or "").strip())
    return match.group(1) if match else None


def _is_section_boundary(tag, current_id: str) -> bool:
    if tag.name == "table":
        return True
    classes = tag.get("class") or []
    if tag.name == "p" and "toc_catchln" in classes:
        return True
    if tag.find("span", class_="catchln"):
        nxt = tag.find(id=_SEC_ID_RE)
        if nxt is None or str(nxt.get("id") or "") != current_id:
            return True
    nxt = tag.find(id=_SEC_ID_RE) if tag.name == "p" else None
    return bool(nxt is not None and str(nxt.get("id") or "") != current_id)


def _heading_and_rest(text: str, section_number: str) -> Tuple[str, str]:
    match = _HEADING_RE.match(text)
    if match:
        return match.group("head").strip(" ."), ""
    prefix = f"Sec. {section_number}."
    if text.lower().startswith(prefix.lower()):
        rest = text[len(prefix) :].strip()
        return rest[:200], ""
    return text[:200], ""


def parse_connecticut_chapter_html(
    html: str,
    *,
    chapter_url: str = "",
    code_name: str = "Connecticut General Statutes",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    """Parse inline CGA chapter sections from one ``chap_NNN.htm`` page."""

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []

    soup = BeautifulSoup(html or "", "html.parser")
    source = chapter_url or BASE_PUB
    statutes: List[NormalizedStatute] = []
    seen: set[str] = set()

    anchors = []
    for para in soup.find_all("p", class_="toc_catchln"):
        link = para.find("a", href=True)
        href = str(link.get("href") or "") if link else ""
        if href.startswith("#"):
            anchors.append(href.lstrip("#"))
    if not anchors:
        for span in soup.select("span.catchln[id^='sec_'], span[id^='sec_']"):
            anchors.append(str(span.get("id") or ""))

    for anchor_id in anchors:
        if max_statutes is not None and len(statutes) >= int(max_statutes):
            break
        number = _anchor_number(anchor_id)
        if not number or number in seen:
            continue
        anchor = soup.find(id=anchor_id)
        if anchor is None:
            continue
        heading_tag = anchor.parent
        heading_text = _clean(anchor.get_text(" "))
        if _RESERVED.search(heading_text):
            continue
        toc = soup.find("a", href=f"#{anchor_id}")
        toc_text = _clean(toc.get_text(" ")) if toc else ""
        if _RESERVED.search(toc_text):
            continue
        if toc is not None and toc.find("b") is not None and not heading_text:
            continue
        name, _ = _heading_and_rest(heading_text or toc_text, number)
        if _RESERVED.search(name):
            continue

        body_parts: List[str] = []
        heading_full = _clean(heading_tag.get_text(" ")) if heading_tag is not None else heading_text
        leftover = heading_full
        for prefix in (heading_text, f"Sec. {number}. {name}", f"Sec. {number}."):
            if leftover.lower().startswith(prefix.lower()):
                leftover = leftover[len(prefix) :].strip(" .")
                break
        if leftover and not _RESERVED.search(leftover):
            body_parts.append(leftover)

        sibling = heading_tag.next_sibling if heading_tag is not None else None
        while sibling is not None:
            if getattr(sibling, "name", None):
                if _is_section_boundary(sibling, anchor_id):
                    break
                classes = sibling.get("class") or []
                raw = _clean(sibling.get_text(" "))
                if raw and not any(cls in ("source-first", "history-first") for cls in classes):
                    body_parts.append(raw)
            sibling = sibling.next_sibling

        body = _clean(" ".join(body_parts))
        if len(body) < 20:
            continue
        seen.add(number)
        statutes.append(
            NormalizedStatute(
                state_code="CT",
                state_name="Connecticut",
                statute_id=f"{code_name} § {number}",
                code_name=code_name,
                section_number=number,
                section_name=(name or f"Section {number}")[:200],
                full_text=body[:14000],
                source_url=f"{source}#{anchor_id}",
                official_cite=f"Conn. Gen. Stat. § {number}",
                metadata=StatuteMetadata(),
                structured_data={
                    "source_kind": "official_connecticut_chapter_html",
                    "source_authority_class": "official",
                    "discovery_method": "cga_sec_sibling_walk",
                    "chapter_url": source,
                    "skip_hydrate": True,
                },
            )
        )
    return statutes


def configured_chapter_html_path() -> Optional[Path]:
    raw = str(os.environ.get("CONNECTICUT_CHAPTER_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


def configured_titles_html_path() -> Optional[Path]:
    raw = str(os.environ.get("CONNECTICUT_TITLES_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


def parse_configured_titles_html() -> List[Tuple[str, str]]:
    path = configured_titles_html_path()
    if path is None:
        return []
    return titles_from_index(path.read_text(encoding="utf-8", errors="replace"))
