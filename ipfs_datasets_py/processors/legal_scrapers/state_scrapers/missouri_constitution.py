"""Official Missouri Constitution OneSection parser.

Adapted from Vaquill-AI/open-us-law ``ingest_state_constitutions.scrape_mo``
(Apache-2.0). revisor.mo.gov ``OneSection.aspx?constit=y`` puts the body in
the ``div.norm`` sibling of ``span#effdt``. Direct ``p.norm`` children exclude
the predecessor-document ``div.foot`` Source note. A catchline prefixed
``SCHEDULE—`` is rerouted off Article XII.

Local dump: ``MISSOURI_CONSTITUTION_HTML``.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional

from .base_scraper import NormalizedStatute, StatuteMetadata

MO_CONST_INDEX = "https://revisor.mo.gov/main/Home.aspx?constit=y"
_MO_HEADING_RE = re.compile(
    r"^([IVXLC]+)\s+Section\s+([\w().]+)\.\s*(.*?)\s*—?\s*$"
)
_RESERVED = re.compile(r"\b(repealed|reserved|expired|renumbered)\b", re.IGNORECASE)
_WS = re.compile(r"\s+")


def parse_missouri_constitution_html(
    html: str,
    *,
    code_name: str = "Missouri Constitution",
    source_url: str = "",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    effdt = soup.find("span", id="effdt")
    wrap = effdt
    while wrap is not None and getattr(wrap, "name", None) != "div":
        wrap = wrap.parent
    container = wrap.find_next_sibling("div", class_="norm") if wrap is not None else None
    if container is None:
        container = soup.find("div", class_="norm")
    if container is None:
        return []
    catchline = ""
    art_id = "I"
    number = "1"
    body_parts: List[str] = []
    for para in container.find_all("p", class_="norm", recursive=False):
        bold = para.find("span", class_="bold")
        if bold is not None:
            heading_text = _WS.sub(" ", bold.get_text(" ", strip=True)).strip()
            match = _MO_HEADING_RE.match(heading_text)
            if match:
                art_id, number, catchline = (
                    match.group(1),
                    match.group(2),
                    match.group(3).strip().rstrip("."),
                )
            bold.decompose()
        text = _WS.sub(" ", para.get_text(" ", strip=True)).strip()
        if text:
            body_parts.append(text)
    body = " ".join(body_parts).strip()
    effdt_text = _WS.sub(" ", effdt.get_text(" ", strip=True)).strip() if effdt is not None else ""
    if effdt_text:
        body = f"{body} [{effdt_text}]".strip()
    if catchline.startswith("SCHEDULE"):
        art_id = "SCHEDULE"
        catchline = re.sub(r"^SCHEDULE\s*[—-]\s*", "", catchline).strip()
    if len(body) < 40:
        return []
    if _RESERVED.search(catchline) or _RESERVED.search(body[:160]):
        return []
    if max_statutes is not None and int(max_statutes) < 1:
        return []
    cite = (
        f"Mo. Const. Schedule § {number}"
        if art_id == "SCHEDULE"
        else f"Mo. Const. art. {art_id}, § {number}"
    )
    return [
        NormalizedStatute(
            state_code="MO",
            state_name="Missouri",
            statute_id=cite,
            code_name=code_name,
            title_number=art_id,
            section_number=number,
            section_name=(catchline or f"Section {number}")[:200],
            full_text=body,
            source_url=source_url or MO_CONST_INDEX,
            official_cite=cite,
            metadata=StatuteMetadata(),
            structured_data={
                "source_kind": "official_missouri_constitution_html",
                "source_authority_class": "official",
                "discovery_method": "revisor_mo_gov_constit",
                "article_id": art_id,
                "skip_hydrate": True,
            },
        )
    ]


def configured_constitution_html_path() -> Optional[Path]:
    raw = str(os.environ.get("MISSOURI_CONSTITUTION_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None
