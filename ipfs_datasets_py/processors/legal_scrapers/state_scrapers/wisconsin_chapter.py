"""Official Wisconsin statutes viewer parser.

Adapted from Vaquill-AI/open-us-law ``wi_bulk.parse`` (Apache-2.0).
``docs.legis.wisconsin.gov`` renders a section as the flat run of
``div.qsatxt_*`` blocks sharing ``data-section``. Case annotations in
``qsnote_*`` siblings (except history) are dropped.
"""

from __future__ import annotations

import copy
import re
from typing import Dict, List, Optional, Set, Tuple

from .base_scraper import NormalizedStatute, StatuteMetadata

BASE = "https://docs.legis.wisconsin.gov"
_WS_RE = re.compile(r"\s+")
_SEC_ANCHOR_RE = re.compile(r"/document/statutes/(\d+\.\d+\w*)(?:[/#?]|$)")
_HIST_LEAD_RE = re.compile(r"^\s*[\d.]+\w*\s+History\s+History:\s*", re.IGNORECASE)
_RESERVED_KEYWORDS = ("[repealed]", "[reserved]", "[expired]", "(repealed)", "(reserved)")


def chapter_of(section_number: str) -> str:
    token = str(section_number or "").strip()
    return token.split(".", 1)[0]


def section_url(section_number: str) -> str:
    return f"{BASE}/document/statutes/{section_number}"


def _clean(raw: str) -> str:
    text = (raw or "").replace("\xa0", " ").replace("\u2009", " ").replace("\u200b", "")
    return _WS_RE.sub(" ", text).strip()


def _is_qsatxt(cls_list) -> bool:
    return any(str(item).startswith("qsatxt_") for item in (cls_list or []))


def section_anchors(html: str, chapter: Optional[str] = None) -> Set[str]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return set()
    soup = BeautifulSoup(html or "", "html.parser")
    doc = soup.find(id="document") or soup
    out: Set[str] = set()
    for anchor in doc.find_all("a", href=True):
        match = _SEC_ANCHOR_RE.search(str(anchor.get("href") or ""))
        if not match:
            continue
        sec = match.group(1)
        if chapter is not None and chapter_of(sec) != str(chapter):
            continue
        out.add(sec)
    return out


def parse_page(html: str, chapter: str) -> Tuple[List[str], Dict[str, dict]]:
    """Harvest fully rendered ``qsatxt_*`` bodies for one chapter on a viewer page."""

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return [], {}
    soup = BeautifulSoup(html or "", "html.parser")
    doc = soup.find(id="document") or soup
    ordered: List[str] = []
    seen: Set[str] = set()
    paras_by_sec: Dict[str, List[str]] = {}
    title_by_sec: Dict[str, str] = {}
    chapter_token = str(chapter or "")

    for div in doc.find_all("div"):
        cls = div.get("class") or []
        if not _is_qsatxt(cls):
            continue
        sec = str(div.get("data-section") or "").strip()
        if not sec or chapter_of(sec) != chapter_token:
            continue
        if sec not in seen:
            seen.add(sec)
            ordered.append(sec)
        div_copy = copy.copy(div)
        title_span = div_copy.find("span", class_="qstitle_sect")
        if title_span is not None and sec not in title_by_sec:
            title_by_sec[sec] = _clean(title_span.get_text(" "))
        for span in div_copy.find_all("span", class_="qsnum_sect"):
            span.decompose()
        for span in div_copy.find_all("span", class_="qstitle_sect"):
            span.decompose()
        for anchor in div_copy.find_all("a", class_="reference"):
            anchor.decompose()
        text = _clean(div_copy.get_text(" "))
        if text:
            paras_by_sec.setdefault(sec, []).append(text)

    hist_by_sec: Dict[str, str] = {}
    for div in doc.find_all("div", class_="qsnote_history"):
        sec = str(div.get("data-section") or "").strip()
        if not sec or chapter_of(sec) != chapter_token:
            continue
        raw = _HIST_LEAD_RE.sub("", _clean(div.get_text(" "))).strip()
        if raw:
            hist_by_sec[sec] = (hist_by_sec.get(sec, "") + " " + raw).strip()

    sections: Dict[str, dict] = {}
    for sec in ordered:
        paras = paras_by_sec.get(sec, [])
        title = title_by_sec.get(sec, "")
        blob = f"{title} {' '.join(paras)}".lower()
        status = None
        for keyword in _RESERVED_KEYWORDS:
            if keyword in blob:
                status = "repealed" if "repeal" in keyword else "reserved"
                break
        sections[sec] = {
            "title": title,
            "paragraphs": paras,
            "history": hist_by_sec.get(sec, ""),
            "status": status,
        }
    return ordered, sections


def statutes_from_page(
    html: str,
    *,
    chapter: str,
    code_name: str = "Wisconsin Statutes",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    ordered, sections = parse_page(html, chapter)
    out: List[NormalizedStatute] = []
    for sec in ordered:
        if max_statutes is not None and len(out) >= int(max_statutes):
            break
        data = sections.get(sec) or {}
        if data.get("status"):
            continue
        body = " ".join(data.get("paragraphs") or []).strip()
        if len(body) < 40:
            continue
        out.append(
            NormalizedStatute(
                state_code="WI",
                state_name="Wisconsin",
                statute_id=f"{code_name} § {sec}",
                code_name=code_name,
                chapter_number=chapter,
                section_number=sec,
                section_name=(data.get("title") or f"Section {sec}")[:200],
                full_text=body[:14000],
                source_url=section_url(sec),
                official_cite=f"Wis. Stat. § {sec}",
                metadata=StatuteMetadata(),
                structured_data={
                    "source_kind": "official_wisconsin_qsatxt",
                    "source_authority_class": "official",
                    "discovery_method": "docs_legis_qsatxt_window",
                    "skip_hydrate": True,
                },
            )
        )
    return out
