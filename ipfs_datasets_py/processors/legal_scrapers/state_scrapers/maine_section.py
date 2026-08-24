"""Official Maine MRS section HTML parser.

Adapted from Vaquill-AI/open-us-law ``scrapeME.py`` (Apache-2.0).
Body lives in ``div.MRSSection``; ``heading_section`` is skipped and
``qhistory`` is dropped.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional, Tuple

from .base_scraper import NormalizedStatute, StatuteMetadata

BASE = "https://legislature.maine.gov/legis/statutes"
_RESERVED = re.compile(r"\((?:repealed|expired|reserved|renumbered)\)", re.IGNORECASE)
_SEC_RE = re.compile(r"§\s*(?P<num>[\w\-]+)\.\s*(?P<head>.*)$")
_TITLE_RE = re.compile(r"/title(?P<title>[\w\-]+)sec(?P<section>[\w\-]+)\.html$", re.IGNORECASE)
_WS = re.compile(r"\s+")
_MOJIBAKE = ("\xc2", "\xe2\x80", "â€")


def _fix_encoding(text: str) -> str:
    if not text or not any(marker in text for marker in _MOJIBAKE):
        return text
    try:
        fixed = text.encode("latin-1", errors="ignore").decode("utf-8", errors="ignore")
    except Exception:
        return text
    return fixed if sum(m in fixed for m in _MOJIBAKE) < sum(m in text for m in _MOJIBAKE) else text


def _clean(text: str) -> str:
    return _WS.sub(" ", _fix_encoding((text or "").replace("\xa0", " "))).strip()


def parse_maine_section_html(
    html: str,
    *,
    source_url: str = "",
    code_name: str = "Maine Revised Statutes",
) -> Optional[NormalizedStatute]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return None
    soup = BeautifulSoup(html or "", "html.parser")
    sec = soup.find("div", class_=re.compile(r"MRSSection"))
    if sec is None:
        return None
    heading = ""
    paras: list[str] = []
    for element in sec.find_all(recursive=False):
        classes = " ".join(element.get("class") or [])
        text = _clean(element.get_text(" "))
        if not text:
            continue
        if "heading_section" in classes:
            heading = text
            continue
        if "qhistory" in classes:
            continue
        paras.append(text)
    body = _clean(" ".join(paras))
    if len(body) < 40:
        return None
    if _RESERVED.search(heading) or _RESERVED.search(body[:160]):
        return None
    url_match = _TITLE_RE.search(source_url or "")
    title = url_match.group("title") if url_match else ""
    number = url_match.group("section") if url_match else ""
    head_match = _SEC_RE.search(heading)
    if head_match:
        number = number or head_match.group("num")
        name = head_match.group("head").strip()
    else:
        name = heading or f"Section {number}"
    if not number:
        return None
    return NormalizedStatute(
        state_code="ME",
        state_name="Maine",
        statute_id=f"{code_name} § {number}",
        code_name=code_name,
        title_number=title or None,
        section_number=number,
        section_name=name[:200],
        full_text=body[:14000],
        source_url=source_url or f"{BASE}/",
        official_cite=(
            f"Me. Rev. Stat. tit. {title}, § {number}" if title else f"Me. Rev. Stat. § {number}"
        ),
        metadata=StatuteMetadata(),
        structured_data={
            "source_kind": "official_maine_mrs_section",
            "source_authority_class": "official",
            "discovery_method": "legislature_mrssection",
            "skip_hydrate": True,
        },
    )


def configured_section_html_path() -> Optional[Path]:
    raw = str(os.environ.get("MAINE_SECTION_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


def title_toc_chapter_links(html: str, *, base_url: str = BASE) -> List[Tuple[str, str]]:
    """Chapter index URLs from a title TOC (``MRSChapter_toclist``).

    Adapted from Vaquill-AI/open-us-law ``scrape_me2`` nested title listing.
    """

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    from urllib.parse import urljoin

    soup = BeautifulSoup(html or "", "html.parser")
    out: List[Tuple[str, str]] = []
    seen = set()
    containers = soup.find_all("div", class_=re.compile(r"MRSChapter_toclist"))
    anchors = []
    for container in containers:
        anchors.extend(container.find_all("a", href=True))
    if not anchors:
        anchors = soup.find_all("a", href=True)
    for anchor in anchors:
        href = str(anchor.get("href") or "").strip()
        if not re.search(r"title[0-9A-Za-z\-]+ch[0-9A-Za-z\-]+sec0\.html$", href, re.IGNORECASE):
            continue
        if href.lower().endswith("ch0sec0.html"):
            continue
        url = urljoin(base_url.rstrip("/") + "/", href)
        if url in seen:
            continue
        seen.add(url)
        name = _clean(anchor.get_text(" ")) or url
        out.append((url, name))
    return out


def configured_title_toc_html_path() -> Optional[Path]:
    raw = str(os.environ.get("MAINE_TITLE_TOC_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None
