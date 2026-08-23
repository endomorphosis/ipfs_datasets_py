"""Official Georgia OCGA title-text dump parser.

Georgia's live HTML tree is an Angular SPA with no free official bulk zip.
An operator-supplied local dump of official title text (PDF extract or
saved statute bodies) can be admitted as official: no nav/footer SPA chrome,
no archive transport. This does not auto-download the commercial OCGA.

Local dumps: ``GEORGIA_TITLE_TEXT``, ``GEORGIA_TITLE_TEXT_DIR``.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional

from .georgia_archive import (
    NAV_MARKERS,
    official_section_url,
    official_title_url,
)
from .base_scraper import NormalizedStatute, StatuteMetadata

_SECTION_RE = re.compile(
    r"(?m)^(?:§|&sect;)\s*(?P<num>\d+[A-Za-z]?-\d+[A-Za-z0-9.-]*)\.\s*(?P<head>[^\n]+)"
)
_RESERVED = re.compile(r"\b(repealed|reserved|expired|renumbered)\b", re.IGNORECASE)
_WS = re.compile(r"\s+")


def _clean(text: str) -> str:
    return _WS.sub(" ", (text or "").replace("\xa0", " ")).strip()


def parse_georgia_title_text(
    text: str,
    *,
    source_url: str = "",
    code_name: str = "Official Code of Georgia Annotated",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    body = text or ""
    lines = []
    for line in body.splitlines():
        lowered = line.lower()
        if any(marker in lowered for marker in NAV_MARKERS):
            continue
        lines.append(line)
    cleaned = "\n".join(lines)
    matches = list(_SECTION_RE.finditer(cleaned))
    statutes: List[NormalizedStatute] = []
    for index, match in enumerate(matches):
        if max_statutes is not None and len(statutes) >= int(max_statutes):
            break
        number = match.group("num")
        heading = match.group("head").strip()
        if _RESERVED.search(heading):
            continue
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(cleaned)
        section_body = _clean(cleaned[start:end])
        if any(marker in section_body.lower() for marker in NAV_MARKERS):
            continue
        if len(section_body) < 40:
            continue
        parts = number.split("-")
        official = official_section_url(number)
        statutes.append(
            NormalizedStatute(
                state_code="GA",
                state_name="Georgia",
                statute_id=f"{code_name} § {number}",
                code_name=code_name,
                title_number=parts[0] if parts else None,
                chapter_number=parts[1] if len(parts) > 1 else None,
                section_number=number,
                section_name=heading[:200],
                full_text=section_body[:14000],
                source_url=source_url or official,
                official_cite=f"Ga. Code Ann. § {number}",
                metadata=StatuteMetadata(),
                structured_data={
                    "source_kind": "official_georgia_title_text",
                    "source_authority_class": "official",
                    "discovery_method": "georgia_title_text_dump",
                    "official_title_url": official_title_url(parts[0]) if parts else None,
                    "skip_hydrate": True,
                },
            )
        )
    return statutes


def configured_title_text_paths() -> List[Path]:
    paths: List[Path] = []
    raw = str(os.environ.get("GEORGIA_TITLE_TEXT") or "").strip()
    if raw:
        path = Path(raw).expanduser()
        if path.is_file():
            paths.append(path)
    raw_dir = str(os.environ.get("GEORGIA_TITLE_TEXT_DIR") or "").strip()
    if raw_dir:
        directory = Path(raw_dir).expanduser()
        if directory.is_dir():
            paths.extend(
                sorted(
                    child
                    for child in directory.iterdir()
                    if child.is_file() and child.suffix.lower() in {".txt", ".text"}
                )
            )
    return paths


def configured_title_text_path() -> Optional[Path]:
    paths = configured_title_text_paths()
    return paths[0] if paths else None


def parse_configured_georgia_title(
    *,
    code_name: str = "Official Code of Georgia Annotated",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    statutes: List[NormalizedStatute] = []
    seen: set[str] = set()
    for path in configured_title_text_paths():
        if max_statutes is not None and len(statutes) >= int(max_statutes):
            break
        remaining = None if max_statutes is None else max(0, int(max_statutes) - len(statutes))
        rows = parse_georgia_title_text(
            path.read_text(encoding="utf-8", errors="replace"),
            source_url=official_title_url(path.stem.split("-")[-1] if "-" in path.stem else "16"),
            code_name=code_name,
            max_statutes=remaining,
        )
        for row in rows:
            key = str(row.section_number or "")
            if key in seen:
                continue
            seen.add(key)
            statutes.append(row)
    return statutes
