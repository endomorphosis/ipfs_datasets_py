"""Official New Jersey Permanent Statutes RTF zip parser.

Adapted from Vaquill-AI/open-us-law ``nj_bulk.parse`` / ``ingest_nj_bulk.py``
(Apache-2.0). The daily dump is:

    https://pub.njleg.state.nj.us/Statutes/STATUTES-TEXT.zip  -> STATUTES.RTF

Does not download the archive by default. Operators point ``NEW_JERSEY_BULK_ZIP``
at a local copy.
"""

from __future__ import annotations

import os
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, List, Optional

from .base_scraper import NormalizedStatute, StatuteMetadata

OFFICIAL_ZIP_URL = "https://pub.njleg.state.nj.us/Statutes/STATUTES-TEXT.zip"
RTF_MEMBER = "STATUTES.RTF"
SECTION_VIEW = "https://www.njleg.state.nj.us/legislative-activity/statutes"

_CIT_RE = re.compile(r"^\s*(\d+[A-Za-z]?):([0-9][0-9A-Za-z.\-]*?)\.?\s")
_CIT_RE2 = re.compile(r"^\s*(\d+[A-Za-z]?):([0-9][0-9A-Za-z.\-]*)")
_CTRL_RE = re.compile(r"\\([a-zA-Z]+)(-?\d+)? ?")


@dataclass(frozen=True)
class NjSection:
    title: str
    section: str
    catchline: str
    body: str

    @property
    def chapter(self) -> str:
        return self.section.split("-", 1)[0]

    def citation(self) -> str:
        return f"N.J. Stat. § {self.title}:{self.section}"


def _rtf_to_text(chunk: str) -> str:
    """Extract plain text from one ``\\pard``-delimited RTF chunk."""

    out: List[str] = []
    index = 0
    n = len(chunk)
    skip_depth = 0
    depth = 0
    while index < n:
        ch = chunk[index]
        if ch == "\\":
            match = _CTRL_RE.match(chunk, index)
            if match:
                word = match.group(1)
                index = match.end()
                if skip_depth:
                    continue
                if word in ("par", "line", "tab", "cell", "row"):
                    out.append(" ")
                elif word == "u":
                    try:
                        cp = int(match.group(2))
                        if cp < 0:
                            cp += 65536
                        out.append(chr(cp))
                    except (TypeError, ValueError):
                        pass
                    if index < n and chunk[index] not in "\\{}":
                        index += 1
                continue
            if chunk[index : index + 2] == "\\'":
                hexs = chunk[index + 2 : index + 4]
                index += 4
                if not skip_depth:
                    try:
                        out.append(bytes([int(hexs, 16)]).decode("cp1252", "replace"))
                    except ValueError:
                        pass
                continue
            nxt = chunk[index + 1] if index + 1 < n else ""
            index += 2
            if not skip_depth and nxt in "{}\\":
                out.append(nxt)
            continue
        if ch == "{":
            depth += 1
            if chunk[index + 1 : index + 3] == "\\*":
                skip_depth = depth
            index += 1
            continue
        if ch == "}":
            if skip_depth and depth == skip_depth:
                skip_depth = 0
            depth -= 1
            index += 1
            continue
        if ch in "\r\n":
            index += 1
            continue
        if not skip_depth:
            out.append(ch)
        index += 1
    return re.sub(r"[ \t]+", " ", "".join(out)).strip()


def _style_of(chunk: str) -> int:
    match = re.match(r"\s*(?:\\plain)?\s*\\s(\d+)\b", chunk)
    return int(match.group(1)) if match else 0


def iter_sections(rtf: str) -> Iterator[NjSection]:
    """Yield sections from STATUTES.RTF style tags (``\\s2`` title, ``\\s3`` headnote)."""

    chunks = rtf.split("\\pard")
    cur_title: Optional[str] = None
    sec_title = sec_num = catchline = None
    body: List[str] = []

    def _flush() -> Optional[NjSection]:
        if sec_title and sec_num:
            return NjSection(sec_title, sec_num, catchline or "", "\n".join(body).strip())
        return None

    for chunk in chunks:
        style = _style_of(chunk)
        if style == 1:
            continue
        if style == 2:
            flushed = _flush()
            if flushed:
                yield flushed
            sec_title = sec_num = catchline = None
            body = []
            text = _rtf_to_text(chunk)
            heading = re.search(r"TITLE\s+(\w+)", text)
            cur_title = heading.group(1) if heading else cur_title
            continue
        if style == 3:
            flushed = _flush()
            if flushed:
                yield flushed
            body = []
            text = _rtf_to_text(chunk)
            match = _CIT_RE.match(text) or _CIT_RE2.match(text)
            if match:
                sec_title, sec_num = match.group(1), match.group(2)
                catchline = text[match.end() :].strip()
            else:
                sec_title = sec_num = catchline = None
            continue
        if sec_title:
            text = _rtf_to_text(chunk)
            if text:
                body.append(text)
    flushed = _flush()
    if flushed:
        yield flushed


def parse_new_jersey_bulk_zip(
    zip_path: Path,
    *,
    code_name: str = "New Jersey Statutes",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    """Parse official STATUTES-TEXT.zip into NormalizedStatute rows."""

    path = Path(zip_path)
    if not path.is_file():
        raise FileNotFoundError(f"New Jersey bulk zip missing: {path}")
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        member = next(
            (name for name in names if name.upper().endswith(RTF_MEMBER)),
            next((name for name in names if name.upper().endswith(".RTF")), None),
        )
        if member is None:
            return []
        rtf = archive.read(member).decode("cp1252", errors="replace")

    statutes: List[NormalizedStatute] = []
    for section in iter_sections(rtf):
        if max_statutes is not None and len(statutes) >= int(max_statutes):
            break
        if not section.body or len(section.body) < 5:
            continue
        cite = f"{section.title}:{section.section}"
        statutes.append(
            NormalizedStatute(
                state_code="NJ",
                state_name="New Jersey",
                statute_id=f"{code_name} § {cite}",
                code_name=code_name,
                title_number=section.title,
                chapter_number=section.chapter,
                section_number=cite,
                section_name=(section.catchline[:200] if section.catchline else f"Section {cite}"),
                full_text=section.body[:14000],
                source_url=SECTION_VIEW,
                official_cite=section.citation(),
                metadata=StatuteMetadata(),
                structured_data={
                    "source_kind": "official_new_jersey_statutes_rtf",
                    "source_authority_class": "official",
                    "discovery_method": "njleg_statutes_text_zip",
                    "bulk_host": "pub.njleg.state.nj.us",
                    "skip_hydrate": True,
                },
            )
        )
    return statutes


def configured_bulk_zip_path() -> Optional[Path]:
    raw = str(os.environ.get("NEW_JERSEY_BULK_ZIP") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None
