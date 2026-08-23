"""Official New Mexico Statutes Annotated chapter PDF/text parser.

Adapted from the ``N-N-N. heading`` walk in ``new_mexico.py``. Vaquill
lists New Mexico as in-progress; this is the official chapter-text
parser, env-gated to a local dump.

Local dump: ``NEW_MEXICO_CHAPTER_TEXT``.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional

from .base_scraper import NormalizedStatute, StatuteMetadata

BASE = "https://nmonesource.com/nmos/nmsa/en/nav_date.do"
_SECTION_HEADER_RE = re.compile(
    r"(?m)^\s*(?P<section>[0-9]+(?:-[0-9A-Za-z]+)+(?:\.[0-9A-Za-z]+)*)\.\s+(?P<title>.+)$"
)
_HISTORY_RE = re.compile(r"^\s*(History|Source|Cross references|Annotation)\b", re.IGNORECASE)
_RESERVED = re.compile(r"\b(repealed|reserved|expired|renumbered)\b", re.IGNORECASE)
_WS = re.compile(r"\s+")


def _clean(text: str) -> str:
    return _WS.sub(" ", (text or "").replace("\xa0", " ")).strip()


def parse_new_mexico_chapter_text(
    text: str,
    *,
    source_url: str = "",
    code_name: str = "New Mexico Statutes Annotated",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    matches = list(_SECTION_HEADER_RE.finditer(text or ""))
    statutes: List[NormalizedStatute] = []
    for index, match in enumerate(matches):
        if max_statutes is not None and len(statutes) >= int(max_statutes):
            break
        number = match.group("section")
        heading = match.group("title").strip()
        if _RESERVED.search(heading):
            continue
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        paras = []
        for line in text[start:end].splitlines():
            line = line.strip()
            if not line or _HISTORY_RE.match(line):
                continue
            paras.append(line)
        body = _clean(" ".join(paras))
        if len(body) < 40:
            continue
        parts = number.split("-")
        statutes.append(
            NormalizedStatute(
                state_code="NM",
                state_name="New Mexico",
                statute_id=f"{code_name} § {number}",
                code_name=code_name,
                chapter_number=parts[0] if parts else None,
                section_number=number,
                section_name=heading[:200],
                full_text=body[:14000],
                source_url=source_url or BASE,
                official_cite=f"N.M. Stat. Ann. § {number}",
                metadata=StatuteMetadata(),
                structured_data={
                    "source_kind": "official_nmonesource_chapter_pdf",
                    "source_authority_class": "official",
                    "discovery_method": "official_nav_date_chapter_pdf_sections",
                    "skip_hydrate": True,
                },
            )
        )
    return statutes


def configured_chapter_text_path() -> Optional[Path]:
    raw = str(os.environ.get("NEW_MEXICO_CHAPTER_TEXT") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None
