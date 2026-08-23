"""Official Texas chapter HTML parser (tcss resources / zip members).

Adapted from Vaquill-AI/open-us-law ``scrapeTX.py`` (Apache-2.0).
Body lives in ``p.left``: ``Sec.`` / ``Art.`` headings open a section,
indented paragraphs are statutory text, unindented history is dropped.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional

from .base_scraper import NormalizedStatute, StatuteMetadata

TCAS_RESOURCES = "https://tcss.legis.texas.gov/resources"
STATUTE_ORIGIN = "https://statutes.capitol.texas.gov"

_SEC_RE = re.compile(r"^(Sec\.|Art\.)\s+(\d[\d.A-Z-]*)\.", re.IGNORECASE)
_TITLE_RE = re.compile(
    r"^(?:Sec\.|Art\.)\s+[\d.\w-]+\.\s+((?:[A-Z][A-Z\s;,\-\(\)'\"&.]+\.)+)\s*(.*)",
)
_RESERVED = re.compile(
    r"\[(?:repealed|expired|reserved|renumbered|transferred)\b|\brepealed\b",
    re.IGNORECASE,
)
_HISTORY_PREFIXES = (
    "Acts ",
    "Added by",
    "Amended by",
    "Redesignated",
    "Transferred",
    "Expired ",
    "Renumbered",
    "Reenacted",
)
_WS = re.compile(r"\s+")


def chapter_html_url(code: str, chapter_num: str) -> str:
    return f"{TCAS_RESOURCES}/{code}/htm/{code}.{chapter_num}.htm"


def _clean(text: str) -> str:
    return _WS.sub(" ", (text or "").replace("\xa0", " ").replace("\u2002", " ")).strip()


def _is_history(text: str) -> bool:
    return text.startswith(_HISTORY_PREFIXES)


def parse_texas_chapter_html(
    html: str,
    *,
    code_name: str = "Penal Code",
    code_abbrev: str = "PE",
    chapter_number: str = "",
    member_name: str = "",
    source_url: str = "",
    zip_url: str = "",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    """Parse ``p.left`` Sec./Art. blocks from one tcss chapter HTML page."""

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []

    soup = BeautifulSoup(html or "", "html.parser")
    paras = [p for p in soup.find_all("p") if "left" in (p.get("class") or [])]
    if not paras:
        return []

    chapter = chapter_number or _chapter_from_member(member_name)
    official_url = source_url or (
        chapter_html_url(code_abbrev, chapter) if chapter else STATUTE_ORIGIN
    )
    statutes: List[NormalizedStatute] = []
    current_number = ""
    current_name = ""
    current_anchor = ""
    body_parts: List[str] = []

    def flush() -> None:
        nonlocal current_number, current_name, current_anchor, body_parts
        if not current_number:
            return
        if _RESERVED.search(current_name or ""):
            current_number = ""
            current_name = ""
            current_anchor = ""
            body_parts = []
            return
        body = _clean(" ".join(body_parts))
        if len(body) < 40:
            current_number = ""
            current_name = ""
            current_anchor = ""
            body_parts = []
            return
        if max_statutes is not None and len(statutes) >= int(max_statutes):
            current_number = ""
            return
        heading = current_name or f"§ {current_number}"
        link = official_url
        if current_anchor:
            link = f"{official_url}#{current_anchor}"
        structured = {
            "source_kind": (
                "official_texas_statutes_html_zip" if zip_url else "official_texas_chapter_html"
            ),
            "source_authority_class": "official",
            "discovery_method": "tcss_p_left_sec",
            "skip_hydrate": True,
        }
        if zip_url:
            structured["zip_url"] = zip_url
        if member_name:
            structured["zip_member"] = member_name
        statutes.append(
            NormalizedStatute(
                state_code="TX",
                state_name="Texas",
                statute_id=f"{code_name} § {current_number}",
                code_name=code_name,
                chapter_number=chapter or None,
                section_number=current_number,
                section_name=heading[:200],
                full_text=body[:14000],
                source_url=link,
                official_cite=f"Tex. {code_name} § {current_number}",
                metadata=StatuteMetadata(),
                structured_data=structured,
            )
        )
        current_number = ""
        current_name = ""
        current_anchor = ""
        body_parts = []

    for para in paras:
        text = _clean(para.get_text(" "))
        if not text:
            continue
        match = _SEC_RE.match(text)
        if match:
            flush()
            if max_statutes is not None and len(statutes) >= int(max_statutes):
                break
            if _RESERVED.search(text):
                current_number = ""
                current_name = ""
                current_anchor = ""
                body_parts = []
                continue
            current_number = match.group(2).rstrip(".")
            current_anchor = str(para.get("id") or current_number)
            title_match = _TITLE_RE.match(text)
            if title_match:
                current_name = f"§ {current_number}. {title_match.group(1).strip()}"
                rest = _clean(title_match.group(2))
            else:
                current_name = f"§ {current_number}."
                rest = _clean(_SEC_RE.sub("", text, count=1))
            if rest and not _is_history(rest) and not _RESERVED.search(current_name):
                body_parts.append(rest)
            continue
        if not current_number:
            continue
        style = str(para.get("style") or "")
        if "text-indent" not in style or _is_history(text):
            continue
        body_parts.append(text)
    flush()
    return statutes


def _chapter_from_member(member_name: str) -> str:
    match = re.search(r"\.([0-9A-Za-z.-]+)\.html?$", str(member_name or ""), re.IGNORECASE)
    return match.group(1) if match else ""


def configured_chapter_html_path() -> Optional[Path]:
    raw = str(os.environ.get("TEXAS_CHAPTER_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None
