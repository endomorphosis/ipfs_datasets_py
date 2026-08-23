"""Official Arkansas Constitution PDF-text parser.

Adapted from Vaquill-AI/open-us-law ``ingest_state_constitutions.scrape_ar``
(Apache-2.0). Start at the real ``PREAMBLE``. Units are ``Article N``,
``SCHEDULE``, then ``AMEND. N.``. Sections use ``§ N.``.

Local dump: ``ARKANSAS_CONSTITUTION_TEXT``. No auto-download of the PDF.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional, Tuple

from .base_scraper import NormalizedStatute, StatuteMetadata

AR_CONST_PDF = "https://www.jonesboroar.gov/DocumentCenter/View/290/Arkansas-Constitution-PDF"
_AR_ARTICLE_RE = re.compile(r"\n\s*Article\s+(\d+)\s*\n\s*([^\n]+)\n")
_AR_SCHEDULE_RE = re.compile(r"\n\s*SCHEDULE\s*\n")
_AR_AMEND_RE = re.compile(r"\n\s*AMEND\.\s+(\d+)\.\s*\n\s*([^\n]+)\n")
_AR_SECTION_RE = re.compile(r"\n\s*§\s*(\d+[A-Za-z]?(?:\.\d+)?)\.\s*")
_AR_PAGE_NUM_RE = re.compile(r"\n[ \t]*\d{1,3}[ \t]*\n(?=\s*\n)")
_RESERVED = re.compile(r"\b(repealed|reserved|expired|renumbered)\b", re.IGNORECASE)
_WS = re.compile(r"\s+")


def _split_units(body_text: str) -> List[Tuple[str, str]]:
    art_matches = list(_AR_ARTICLE_RE.finditer(body_text))
    sched = _AR_SCHEDULE_RE.search(body_text)
    amend_matches = list(_AR_AMEND_RE.finditer(body_text))
    boundary = len(body_text)
    if sched is not None:
        boundary = min(boundary, sched.start())
    if amend_matches:
        boundary = min(boundary, amend_matches[0].start())
    units: List[Tuple[str, str]] = []
    for index, match in enumerate(art_matches):
        start = match.end()
        end = art_matches[index + 1].start() if index + 1 < len(art_matches) else boundary
        units.append((match.group(1), body_text[start:end]))
    if sched is not None:
        sched_end = amend_matches[0].start() if amend_matches else len(body_text)
        units.append(("SCHED", body_text[sched.end() : sched_end]))
    for index, match in enumerate(amend_matches):
        start = match.end()
        end = amend_matches[index + 1].start() if index + 1 < len(amend_matches) else len(body_text)
        units.append((f"AMEND{match.group(1)}", body_text[start:end]))
    return units


def parse_arkansas_constitution_text(
    text: str,
    *,
    code_name: str = "Arkansas Constitution",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    raw_text = _AR_PAGE_NUM_RE.sub("\n", "\n" + (text or ""))
    pre = re.search(r"\n\s*PREAMBLE\s*\n", raw_text)
    body = raw_text[pre.start() :] if pre else raw_text
    statutes: List[NormalizedStatute] = []
    for art_id, span in _split_units(body):
        if max_statutes is not None and len(statutes) >= int(max_statutes):
            break
        sec_matches = list(_AR_SECTION_RE.finditer("\n" + span))
        for index, match in enumerate(sec_matches):
            if max_statutes is not None and len(statutes) >= int(max_statutes):
                break
            number = match.group(1)
            end = sec_matches[index + 1].start() if index + 1 < len(sec_matches) else len(span) + 1
            raw = _WS.sub(" ", ("\n" + span)[match.end() : end]).strip()
            if len(raw) < 40 or _RESERVED.search(raw[:160]):
                continue
            cite = f"Ark. Const. art. {art_id}, § {number}"
            statutes.append(
                NormalizedStatute(
                    state_code="AR",
                    state_name="Arkansas",
                    statute_id=cite,
                    code_name=code_name,
                    title_number=art_id,
                    section_number=number,
                    section_name=(raw.split(".", 1)[0] or f"Section {number}")[:200],
                    full_text=raw[:14000],
                    source_url=AR_CONST_PDF,
                    official_cite=cite,
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "official_arkansas_constitution_pdf",
                        "source_authority_class": "official",
                        "discovery_method": "arkansas_constitution_pdf",
                        "article_id": art_id,
                        "skip_hydrate": True,
                    },
                )
            )
    return statutes


def configured_constitution_text_path() -> Optional[Path]:
    raw = str(os.environ.get("ARKANSAS_CONSTITUTION_TEXT") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None
