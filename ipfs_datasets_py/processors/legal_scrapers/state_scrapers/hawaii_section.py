"""Official Hawaii HRS section HTML parser.

Adapted from Vaquill-AI/open-us-law ``scrapeHI.py`` (Apache-2.0).
First ``<p>`` carries ``§ N-N. heading`` plus body; later paragraphs stop
at notes headings or ``[L 1892`` history.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional, Tuple

from .base_scraper import NormalizedStatute, StatuteMetadata

BASE = "https://www.capitol.hawaii.gov"
_NOTES_HEADINGS = {
    "attorney general opinions",
    "law journals and reviews",
    "case notes",
    "rules of court",
    "cross references",
    "revision notes",
    "compiler's notes",
    "note",
    "notes",
    "history",
    "history of section",
    "editor's note",
    "source",
    "annotations",
}
_HISTORY_RE = re.compile(r"\[?[Ll]\s+\d{4}")
_RESERVED = re.compile(r"\(repealed\)|\(expired\)|\(reserved\)|--repealed", re.IGNORECASE)
_SEC_RE = re.compile(r"§\s*([\d][\w\-.]*)")
_FILE_RE = re.compile(r"HRS_(\d{4})-(\d{4}(?:_\d{4})?)\.HTM$", re.IGNORECASE)
_WS = re.compile(r"\s+")
_NEXT_TEXT_RE = re.compile(r"^\s*next\s*(?:>+|»|&gt;)?\s*$", re.IGNORECASE)
_CHAPTER_PREFIX_RE = re.compile(r"^(.*/HRS\d+[A-Z]*/)", re.IGNORECASE)
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


def chapter_prefix(chapter_url: str) -> Optional[str]:
    match = _CHAPTER_PREFIX_RE.match(str(chapter_url or ""))
    return match.group(1) if match else None


def find_next_link(html: str, *, current_url: str) -> Optional[str]:
    """Absolute URL of the chapter/section ``Next`` link, if present."""

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return None
    from urllib.parse import urljoin

    soup = BeautifulSoup(html or "", "html.parser")
    for anchor in soup.find_all("a", href=True):
        if not _NEXT_TEXT_RE.match(_clean(anchor.get_text(" "))):
            continue
        href = str(anchor.get("href") or "").strip()
        if not href:
            continue
        return urljoin(current_url, href)
    return None


def _strip_heading(text: str) -> str:
    text = re.sub(r"(\w)\s+-\s+(\w)", r"\1-\2", text)
    match = re.match(r"^\s*\[?§\s*[\d][\w\-.]*\]?\s+[^.]{1,200}\.\s+(.*)", text, re.DOTALL)
    return match.group(1).strip() if match else text


def parse_hawaii_section_html(
    html: str,
    *,
    source_url: str = "",
    code_name: str = "Hawaii Revised Statutes",
) -> Optional[NormalizedStatute]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return None
    soup = BeautifulSoup(html or "", "html.parser")
    paragraphs = soup.find_all("p")
    if not paragraphs:
        return None
    first = _clean(paragraphs[0].get_text(" "))
    if _RESERVED.search(first):
        return None
    number = ""
    file_match = _FILE_RE.search(source_url or "")
    if file_match:
        chapter = str(int(file_match.group(1)))
        section = file_match.group(2).lstrip("0") or "0"
        number = f"{chapter}-{section.replace('_', '.')}"
    sec_match = _SEC_RE.search(re.sub(r"(\w)\s+-\s+(\w)", r"\1-\2", first))
    if sec_match:
        number = sec_match.group(1).rstrip(".")
    if not number:
        return None
    name_match = re.match(
        r"^\s*\[?§\s*[\d][\w\-.]*\]?\s+([^.]{1,150})\.",
        re.sub(r"(\w)\s+-\s+(\w)", r"\1-\2", first),
    )
    name = name_match.group(1).strip() if name_match else f"Section {number}"
    hist_split = re.split(r"\s+(?=\[(?:Am\s+)?L\s+\d{4})", first, maxsplit=1)
    body_parts = [_strip_heading(hist_split[0])]
    for para in paragraphs[1:]:
        text = _clean(para.get_text(" "))
        if not text:
            continue
        lower = text.lower().rstrip(":").rstrip(".")
        if lower in _NOTES_HEADINGS or any(lower.startswith(head) for head in _NOTES_HEADINGS):
            break
        if _HISTORY_RE.match(text) or text.startswith("[L ") or text.startswith("[Am"):
            break
        body_parts.append(text)
    body = _clean(" ".join(part for part in body_parts if part))
    if len(body) < 40:
        return None
    return NormalizedStatute(
        state_code="HI",
        state_name="Hawaii",
        statute_id=f"{code_name} § {number}",
        code_name=code_name,
        chapter_number=number.split("-", 1)[0],
        section_number=number,
        section_name=name[:200],
        full_text=body[:14000],
        source_url=source_url or f"{BASE}/docs/hrs.htm",
        official_cite=f"Haw. Rev. Stat. § {number}",
        metadata=StatuteMetadata(),
        structured_data={
            "source_kind": "official_hawaii_hrs_html",
            "source_authority_class": "official",
            "discovery_method": "capitol_hrs_section_p",
            "skip_hydrate": True,
        },
    )


def configured_section_html_path() -> Optional[Path]:
    raw = str(os.environ.get("HAWAII_SECTION_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


def configured_chapter_html_path() -> Optional[Path]:
    raw = str(os.environ.get("HAWAII_CHAPTER_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


def parse_configured_next_link(*, current_url: str = "") -> Optional[str]:
    path = configured_chapter_html_path()
    if path is None:
        return None
    url = str(current_url or os.environ.get("HAWAII_CHAPTER_URL") or "").strip() or BASE
    return find_next_link(
        path.read_text(encoding="utf-8", errors="replace"),
        current_url=url,
    )
