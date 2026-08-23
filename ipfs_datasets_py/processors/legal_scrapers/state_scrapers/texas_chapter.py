"""Official Texas chapter HTML parser (tcss resources / zip members).

Adapted from Vaquill-AI/open-us-law ``scrapeTX.py`` (Apache-2.0).
Body lives in ``p.left``: ``Sec.`` / ``Art.`` headings open a section,
indented paragraphs are statutory text, unindented history is dropped.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import List, Optional, Tuple

from .base_scraper import NormalizedStatute, StatuteMetadata

TCAS_RESOURCES = "https://tcss.legis.texas.gov/resources"
TCAS_API = "https://tcss.legis.texas.gov/api"
STATUTE_ORIGIN = "https://statutes.capitol.texas.gov"
# TLC codeIDs from statutes.capitol.texas.gov/assets/QuickCodes.json (Vaquill scrapeTX).
TX_CODE_IDS = {
    "AG": "1", "AL": "2", "BC": "4", "BO": "32", "CN": "5", "CP": "6",
    "CR": "7", "CV": "29", "ED": "9", "EL": "10", "ES": "35", "FA": "11",
    "FI": "12", "GV": "13", "HR": "15", "HS": "14", "I1": "37", "IN": "17",
    "LA": "18", "LG": "19", "NR": "20", "OC": "21", "PB": "23", "PE": "22",
    "PR": "25", "PW": "26", "SD": "33", "TN": "27", "TX": "28",
    "UT": "16", "WA": "30", "WL": "31",
}

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


def get_statute_array_url(code: str) -> str:
    token = str(code or "").strip().upper()
    return (
        f"{TCAS_API}/GetStatuteArray/GetStatuteArray/"
        f"{token}/{token}/null/null/null/null/null/null/null/null/htm"
    )


def populate_chapter_list_url(code: str) -> Optional[str]:
    code_id = TX_CODE_IDS.get(str(code or "").strip().upper())
    if not code_id:
        return None
    return f"{TCAS_API}/QuickSearch/PopulateChapterList/{code_id}/CH"


def _chapter_number_from_entry(entry: dict, code: str) -> str:
    url = str(entry.get("url") or "").strip()
    url_match = re.search(r"/" + re.escape(code) + r"\.([0-9A-Za-z._-]+?)\.htm", url, re.IGNORECASE)
    if url_match and url_match.group(1)[:1].isdigit():
        return url_match.group(1)
    rel = str(entry.get("url") or "").strip()
    rel_match = re.match(re.escape(code) + r"\.([0-9A-Za-z._-]+)$", rel, re.IGNORECASE)
    if rel_match and rel_match.group(1)[:1].isdigit():
        return rel_match.group(1)
    name = str(entry.get("name") or entry.get("text") or "")
    name_match = re.match(r"CHAPTER\s+([\w.]+)", name, re.IGNORECASE)
    if name_match and name_match.group(1)[:1].isdigit():
        return name_match.group(1).rstrip(".")
    return ""


def chapters_from_statute_array(payload, *, code: str) -> List[Tuple[str, str, str]]:
    """Normalize GetStatuteArray JSON to ``(chapter, name, html_url)``."""

    if not isinstance(payload, list):
        return []
    token = str(code or "").strip().upper()
    out: List[Tuple[str, str, str]] = []
    seen: set[str] = set()
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        number = _chapter_number_from_entry(entry, token)
        if not number or number in seen:
            continue
        seen.add(number)
        name = str(entry.get("name") or f"Chapter {number}").strip()
        out.append((number, name, chapter_html_url(token, number)))
    return out


def chapters_from_quicksearch(payload, *, code: str) -> List[Tuple[str, str, str]]:
    """Normalize PopulateChapterList JSON ``{text,value,url}`` rows."""

    if not isinstance(payload, list):
        return []
    token = str(code or "").strip().upper()
    out: List[Tuple[str, str, str]] = []
    seen: set[str] = set()
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        rel = str(entry.get("url") or "").strip()
        number = ""
        if rel:
            rel_match = re.match(
                re.escape(token) + r"\.([0-9A-Za-z._-]+)$", rel, re.IGNORECASE
            )
            if rel_match:
                number = rel_match.group(1)
        if not number:
            number = _chapter_number_from_entry(
                {"name": entry.get("text") or "", "url": rel}, token
            )
        if not number or number in seen:
            continue
        seen.add(number)
        name = str(entry.get("text") or f"Chapter {number}").strip()
        out.append((number, name, chapter_html_url(token, number)))
    return out


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


def configured_statute_array_path() -> Optional[Path]:
    raw = str(os.environ.get("TEXAS_STATUTE_ARRAY_JSON") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


def parse_configured_statute_array(*, code: str = "") -> List[Tuple[str, str, str]]:
    """Local GetStatuteArray dump. Does not call the tcss API."""

    path = configured_statute_array_path()
    if path is None:
        return []
    token = str(code or os.environ.get("TEXAS_STATUTE_ARRAY_CODE") or "PE").strip().upper()
    payload = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    return chapters_from_statute_array(payload, code=token)
