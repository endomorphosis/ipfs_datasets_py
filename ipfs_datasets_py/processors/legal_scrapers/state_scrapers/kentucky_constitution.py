"""Official Kentucky Constitution section parser.

Adapted from Vaquill-AI/open-us-law ``ingest_state_constitutions.scrape_ky``
(Apache-2.0). apps.legislature.ky.gov lists sections on a TOC and serves
each at ViewConstitution. Flat Bill of Rights numbering (no articles).

Local dump: ``KENTUCKY_CONSTITUTION_HTML``.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import urljoin

from .base_scraper import NormalizedStatute, StatuteMetadata

KY_CONST_TOC = "https://apps.legislature.ky.gov/law/constitution"
KY_BASE = "https://apps.legislature.ky.gov"
_TOC_LINK_RE = re.compile(r"Section\s+(\d+[A-Za-z]?)\s*[.\-…]\s*(.*)", re.IGNORECASE)
_RESERVED = re.compile(r"\b(repealed|reserved|expired|renumbered)\b", re.IGNORECASE)
_WS = re.compile(r"\s+")


def constitution_toc_links(html: str) -> List[Tuple[str, str, str]]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    out: List[Tuple[str, str, str]] = []
    seen = set()
    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href") or "")
        if "ViewConstitution" not in href and "/constitution" not in href.lower():
            continue
        text = _WS.sub(" ", anchor.get_text(" ")).strip()
        match = _TOC_LINK_RE.match(text)
        if not match:
            continue
        number = match.group(1)
        if number in seen:
            continue
        seen.add(number)
        title = match.group(2).strip().rstrip(".")
        full = href if href.startswith("http") else urljoin(KY_BASE + "/", href)
        out.append((number, title, full))
    return out


def parse_kentucky_constitution_section_html(
    html: str,
    *,
    section_number: str = "1",
    section_title: str = "",
    source_url: str = "",
    code_name: str = "Kentucky Constitution",
) -> Optional[NormalizedStatute]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return None
    soup = BeautifulSoup(html or "", "html.parser")
    main = (
        soup.find("main")
        or soup.find("div", id="MainContent")
        or soup.find("div", class_=re.compile("content", re.I))
        or soup.find("body")
        or soup
    )
    text = main.get_text("\n", strip=True)
    number = str(section_number or "1")
    anchor = re.search(rf"Section\s+{re.escape(number)}\s*[.\-…]", text, flags=re.IGNORECASE)
    if anchor:
        text = text[anchor.start() :]
    for trail in ("\n© ", "\nPrint this page", "\nReturn to top", "\nText as Ratified"):
        idx = text.find(trail)
        if idx > 0:
            text = text[:idx]
            break
    body = _WS.sub(" ", text).strip()
    if len(body) < 40:
        return None
    if _RESERVED.search(section_title) or _RESERVED.search(body[:160]):
        return None
    heading = (section_title or body.split(".", 1)[0])[:200]
    return NormalizedStatute(
        state_code="KY",
        state_name="Kentucky",
        statute_id=f"Ky. Const. § {number}",
        code_name=code_name,
        title_number="I",
        section_number=number,
        section_name=heading or f"Section {number}",
        full_text=body[:14000],
        source_url=source_url or KY_CONST_TOC,
        official_cite=f"Ky. Const. § {number}",
        metadata=StatuteMetadata(),
        structured_data={
            "source_kind": "official_kentucky_constitution_html",
            "source_authority_class": "official",
            "discovery_method": "apps_legislature_ky_viewconstitution",
            "skip_hydrate": True,
        },
    )


def parse_configured_kentucky_constitution(
    *,
    code_name: str = "Kentucky Constitution",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    raw = str(os.environ.get("KENTUCKY_CONSTITUTION_HTML") or "").strip()
    if not raw:
        return []
    path = Path(raw).expanduser()
    if not path.is_file():
        return []
    html = path.read_text(encoding="utf-8", errors="replace")
    links = constitution_toc_links(html)
    if links:
        out: List[NormalizedStatute] = []
        for number, title, url in links:
            if max_statutes is not None and len(out) >= int(max_statutes):
                break
            row = parse_kentucky_constitution_section_html(
                html,
                section_number=number,
                section_title=title,
                source_url=url,
                code_name=code_name,
            )
            if row is not None:
                out.append(row)
        if out:
            return out
    row = parse_kentucky_constitution_section_html(
        html,
        section_number="1",
        code_name=code_name,
        source_url=KY_CONST_TOC,
    )
    return [row] if row is not None else []
