"""Official Pennsylvania consolidated title text parser.

Adapted from Vaquill-AI/open-us-law ``pa_bulk.parse`` (Apache-2.0).
Uses last alone-on-a-line ``§ N.`` as the body header so TOC entries are
ignored. Local extracted text: ``PENNSYLVANIA_TITLE_TEXT``. Does not require
PyMuPDF for the text path.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional

from .base_scraper import NormalizedStatute, StatuteMetadata

_HDR_RE = re.compile(r"(?m)^[ \t\xa0]*§[ \t\xa0]*([0-9][0-9A-Za-z.]*?)\.[ \t\xa0]*$")
_STRUCT_RE = re.compile(
    r"(?m)^[ \t\xa0]*(CHAPTER\b|Chapter [0-9A-Z]|SUBCHAPTER\b|Subchapter [A-Z]"
    r"|PART\b|Part [0-9A-Z]|ARTICLE\b|Article [0-9A-Z]|Sec\.[ \t\xa0]*$"
    r"|TABLE OF CONTENTS)"
)
_PAGENUM_RE = re.compile(r"(?m)^[ \t\xa0]*\d{1,4}[ \t\xa0]*$")
_NEWPARA_RE = re.compile(
    r'^(\((?:[0-9]+|[0-9]+\.[0-9]+|[a-z]|[a-z]\.[0-9]+|[A-Z]|[ivxlcdm]+)\)|"[^"]+\.")'
)
_WS = re.compile(r"\s+")
_RESERVED_KEYWORDS = ("(reserved)", "(repealed)", "(expired)", "(renumbered)", "(deleted)")


def title_html_url(ttl: str) -> str:
    token = str(ttl).zfill(2)
    return f"https://www.palegis.us/statutes/consolidated/view-statute?txtType=HTM&ttl={token}"


def dewrap(text: str) -> List[str]:
    paras: List[str] = []
    buf = ""
    for raw in text.split("\n"):
        line = raw.strip()
        if not line:
            if buf:
                paras.append(buf)
                buf = ""
            continue
        if _NEWPARA_RE.match(line):
            if buf:
                paras.append(buf)
            buf = line
        else:
            buf = f"{buf} {line}".strip() if buf else line
    if buf:
        paras.append(buf)
    return paras


def parse_pennsylvania_title_text(
    full: str,
    *,
    title_number: str,
    code_name: str = "Pennsylvania Consolidated Statutes",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    heads = list(_HDR_RE.finditer(full or ""))
    if not heads:
        return []
    last = {match.group(1): match for match in heads}
    body = sorted(last.values(), key=lambda match: match.start())
    starts = [match.start() for match in body]
    statutes: List[NormalizedStatute] = []
    for index, match in enumerate(body):
        if max_statutes is not None and len(statutes) >= int(max_statutes):
            break
        num = match.group(1)
        seg_end = starts[index + 1] if index + 1 < len(starts) else len(full)
        seg = full[match.end() : seg_end]
        struct = _STRUCT_RE.search(seg)
        if struct:
            seg = seg[: struct.start()]
        seg = _PAGENUM_RE.sub("", seg)
        lines = seg.split("\n")
        idx = 0
        while idx < len(lines) and not lines[idx].strip():
            idx += 1
        heading_lines: List[str] = []
        while idx < len(lines):
            line = lines[idx].strip()
            if not line:
                idx += 1
                continue
            if _NEWPARA_RE.match(line):
                break
            heading_lines.append(line)
            idx += 1
            if line.endswith(".") or len(heading_lines) >= 8:
                break
        heading = _WS.sub(" ", " ".join(heading_lines)).strip()
        paras = dewrap("\n".join(lines[idx:]))
        blob = f"{heading} {' '.join(paras[:1])}".lower()
        if any(keyword in blob for keyword in _RESERVED_KEYWORDS):
            continue
        text = " ".join(paras).strip()
        if len(text) < 20:
            continue
        statutes.append(
            NormalizedStatute(
                state_code="PA",
                state_name="Pennsylvania",
                statute_id=f"{code_name} § {num}",
                code_name=code_name,
                title_number=str(title_number),
                section_number=num,
                section_name=(heading or f"Section {num}")[:200],
                full_text=text[:14000],
                source_url=title_html_url(title_number),
                official_cite=f"{title_number} Pa.C.S. § {num}",
                metadata=StatuteMetadata(),
                structured_data={
                    "source_kind": "official_pennsylvania_title_text",
                    "source_authority_class": "official",
                    "discovery_method": "palegis_consolidated_title_pdf_text",
                    "skip_hydrate": True,
                },
            )
        )
    return statutes


def configured_title_text_path() -> Optional[Path]:
    raw = str(os.environ.get("PENNSYLVANIA_TITLE_TEXT") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None
