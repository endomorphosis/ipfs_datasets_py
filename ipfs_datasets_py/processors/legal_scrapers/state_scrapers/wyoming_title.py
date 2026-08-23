"""Official Wyoming title PDF/text parser.

Wyoming publishes deterministic title PDFs at
``https://www.wyoleg.gov/statutes/compress/titleN.pdf``. This parser splits
``N-N-N. heading`` blocks and drops History/Source trailers.

Local dump: ``WYOMING_TITLE_TEXT``.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional

from .base_scraper import NormalizedStatute, StatuteMetadata

COMPRESS = "https://www.wyoleg.gov/statutes/compress"
_SECTION_HEADER_RE = re.compile(
    r"(?m)^\s*(?P<num>\d{1,2}-\d{1,2}-\d{2,4}(?:\.[0-9A-Za-z]+)?)\.\s+(?P<head>.+)$"
)
_HISTORY_RE = re.compile(r"^\s*(History|Source|Laws|Cross references)\b", re.IGNORECASE)
_RESERVED = re.compile(r"\b(repealed|reserved|expired|renumbered)\b", re.IGNORECASE)
_WS = re.compile(r"\s+")


def _clean(text: str) -> str:
    return _WS.sub(" ", (text or "").replace("\xa0", " ")).strip()


def parse_wyoming_title_text(
    text: str,
    *,
    source_url: str = "",
    code_name: str = "Wyoming Statutes",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    matches = list(_SECTION_HEADER_RE.finditer(text or ""))
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
                state_code="WY",
                state_name="Wyoming",
                statute_id=f"{code_name} § {number}",
                code_name=code_name,
                title_number=parts[0] if parts else None,
                chapter_number=parts[1] if len(parts) > 1 else None,
                section_number=number,
                section_name=heading[:200],
                full_text=body[:14000],
                source_url=source_url or f"{COMPRESS}/title{parts[0] if parts else '1'}.pdf",
                official_cite=f"Wyo. Stat. § {number}",
                metadata=StatuteMetadata(),
                structured_data={
                    "source_kind": "official_wyoming_title_pdf",
                    "source_authority_class": "official",
                    "discovery_method": "wyoleg_compress_title_text",
                    "skip_hydrate": True,
                },
            )
        )
    return statutes


def configured_title_text_path() -> Optional[Path]:
    raw = str(os.environ.get("WYOMING_TITLE_TEXT") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None
