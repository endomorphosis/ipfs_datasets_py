"""Official Delaware Code chapter HTML parser.

Adapted from Vaquill-AI/open-us-law ``scrapeDE.py`` (Apache-2.0).
Sections are ``div.Section``; body is direct ``<p>`` children; leftover
non-paragraph nodes are history and are dropped. Mojibake is undone.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional

from .base_scraper import NormalizedStatute, StatuteMetadata

BASE = "https://delcode.delaware.gov"
_HEAD_RE = re.compile(r"§\s*(?P<num>[0-9A-Za-z\-]+)\.\s*(?P<head>.+)", re.IGNORECASE)
_RESERVED = re.compile(r"\[(?:repealed|expired|reserved)\b", re.IGNORECASE)
_WS = re.compile(r"\s+")
_MOJIBAKE = ("\xc2", "\xe2\x80", "â€", "Â")


def _fix_encoding(text: str) -> str:
    if not text or not any(marker in text for marker in _MOJIBAKE):
        return text
    try:
        fixed = text.encode("latin-1", errors="ignore").decode("utf-8", errors="ignore")
    except Exception:
        return text
    return fixed if sum(m in fixed for m in _MOJIBAKE) < sum(m in text for m in _MOJIBAKE) else text


def _clean(text: str) -> str:
    value = _fix_encoding((text or "").replace("\xa0", " ").replace("\u2002", " "))
    return _WS.sub(" ", value).strip()


def parse_delaware_chapter_html(
    html: str,
    *,
    source_url: str = "",
    code_name: str = "Delaware Code",
    title_number: str = "",
    chapter_number: str = "",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    title_match = re.search(r"/title(\d+)/", source_url, re.IGNORECASE)
    chapter_match = re.search(r"/c(\d+)/", source_url, re.IGNORECASE)
    title_number = title_number or (title_match.group(1) if title_match else "")
    chapter_number = chapter_number or (
        (chapter_match.group(1).lstrip("0") or "0") if chapter_match else ""
    )
    statutes: List[NormalizedStatute] = []
    for div in soup.find_all("div", class_="Section"):
        if max_statutes is not None and len(statutes) >= int(max_statutes):
            break
        head = div.find("div", class_="SectionHead")
        if head is None:
            continue
        heading = _clean(head.get_text(" "))
        if _RESERVED.search(heading):
            continue
        match = _HEAD_RE.search(heading)
        number = str(head.get("id") or (match.group("num") if match else "")).replace(",", "-").rstrip(".")
        name = match.group("head").strip() if match else heading
        paras: List[str] = []
        for child in div.find_all(recursive=False):
            classes = child.get("class") or []
            if "SectionHead" in classes:
                continue
            text = _clean(child.get_text(" "))
            if not text:
                continue
            if child.name == "p":
                paras.append(text)
        body = _clean(" ".join(paras))
        if not number or len(body) < 40:
            continue
        link = source_url or BASE
        if number:
            link = f"{link.split('#')[0]}#{number}"
        statutes.append(
            NormalizedStatute(
                state_code="DE",
                state_name="Delaware",
                statute_id=f"{code_name} § {number}",
                code_name=code_name,
                title_number=title_number or None,
                chapter_number=chapter_number or None,
                section_number=number,
                section_name=name[:200],
                full_text=body[:14000],
                source_url=link,
                official_cite=f"{title_number} Del. C. § {number}".strip(),
                metadata=StatuteMetadata(),
                structured_data={
                    "source_kind": "official_delaware_section_html",
                    "source_authority_class": "official",
                    "discovery_method": "delcode_section_div",
                    "skip_hydrate": True,
                },
            )
        )
    return statutes


def configured_chapter_html_path() -> Optional[Path]:
    raw = str(os.environ.get("DELAWARE_CHAPTER_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None
