"""Official West Virginia full-code HTML dump parser.

Vaquill notes ``wvcodeentire.htm`` as the full-code dump. Local path:
``WEST_VIRGINIA_CODE_HTML``.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional

from .base_scraper import NormalizedStatute, StatuteMetadata

_SECTION_RE = re.compile(
    r"(?m)^(?:§|&sect;)\s*(?P<num>\d+[A-Za-z]?-\d+[A-Za-z]?-\d+[A-Za-z0-9.]*)\.\s*(?P<head>[^\n]+)"
)
_WS = re.compile(r"\s+")
_RESERVED = re.compile(r"\b(repealed|reserved|expired|omitted)\b", re.IGNORECASE)


def section_url(section_number: str) -> str:
    return f"https://code.wvlegislature.gov/{section_number}/"


def parse_west_virginia_code_html(
    html: str,
    *,
    code_name: str = "West Virginia Code",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        text = html
    else:
        soup = BeautifulSoup(html or "", "html.parser")
        for tag in soup(["script", "style", "nav", "header", "footer"]):
            tag.decompose()
        text = soup.get_text("\n", strip=True)
    matches = list(_SECTION_RE.finditer(text))
    statutes: List[NormalizedStatute] = []
    for index, match in enumerate(matches):
        if max_statutes is not None and len(statutes) >= int(max_statutes):
            break
        number = match.group("num")
        heading = match.group("head").strip()
        if _RESERVED.search(heading):
            continue
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = _WS.sub(" ", text[start:end]).strip()
        if len(body) < 40:
            continue
        parts = number.split("-")
        statutes.append(
            NormalizedStatute(
                state_code="WV",
                state_name="West Virginia",
                statute_id=f"{code_name} § {number}",
                code_name=code_name,
                chapter_number=parts[0] if parts else None,
                section_number=number,
                section_name=heading[:200],
                full_text=body[:14000],
                source_url=section_url(number),
                official_cite=f"W. Va. Code § {number}",
                metadata=StatuteMetadata(),
                structured_data={
                    "source_kind": "official_west_virginia_code_dump",
                    "source_authority_class": "official",
                    "discovery_method": "wvcodeentire_html",
                    "skip_hydrate": True,
                },
            )
        )
    return statutes


def configured_code_html_path() -> Optional[Path]:
    raw = str(os.environ.get("WEST_VIRGINIA_CODE_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None
