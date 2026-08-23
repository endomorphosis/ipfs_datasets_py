"""Official South Dakota whole-title HTML parser.

Adapted from Vaquill-AI/open-us-law ``sd_bulk.parse`` (Apache-2.0).
``sdlegislature.gov/api/Statutes/{title}.html?all=true`` carries every section
heading (SENU span) plus body. Local paths: ``SOUTH_DAKOTA_TITLE_HTML``,
``SOUTH_DAKOTA_CHAPTER_HTML``. Title/chapter ``?all=true`` responses may be
UTF-16 LE without a BOM (Vaquill ``scrapeSD._decode``).
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from .base_scraper import NormalizedStatute, StatuteMetadata

SECTION_NUM_RE = re.compile(r"^(\d+[A-Za-z]*-\d+[A-Za-z]*-\d+[A-Za-z0-9]*(?:\.\d+)*)")
_CLASS_HEADING_RE = re.compile(r"Normal$")
_CLASS_TOC_RE = re.compile(r"B$")
_SOURCE_RE = re.compile(r"^Source:", re.IGNORECASE)
_HASH_RE = re.compile(r"^(s[0-9a-f]+)")
_WS = re.compile(r"\s+")


def title_html_url(title: str) -> str:
    return f"https://sdlegislature.gov/api/Statutes/{title}.html?all=true"


def chapter_html_url(title: str, chapter: str) -> str:
    return f"https://sdlegislature.gov/api/Statutes/{title}-{chapter}.html?all=true"


def decode_sdlegislature_bytes(raw: bytes) -> str:
    """Decode SDLRC ``?all=true`` payloads (UTF-16 LE without BOM, else UTF-8)."""

    data = raw or b""
    if len(data) >= 2 and data[1] == 0x00:
        try:
            return data.decode("utf-16-le")
        except UnicodeDecodeError:
            pass
    for encoding in ("utf-8", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


_CHAPTER_ENTRY_RE = re.compile(r"^(\d+(?:[A-Z](?=[A-Z]))?)(.+)$")
_LEADING_ZEROS_RE = re.compile(r"^0+(\d+[A-Za-z]*)$")


def normalize_chapter_number(display: str) -> str:
    match = _LEADING_ZEROS_RE.match(str(display or ""))
    return match.group(1) if match else str(display or "")


def title_chapter_entries(html: str) -> List[Tuple[str, str]]:
    """Chapter numbers/names from a title ``?all=true`` TOC (class suffix ``B``)."""

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    out: List[Tuple[str, str]] = []
    seen = set()
    for para in soup.find_all("p"):
        cls_list = para.get("class") or []
        if not cls_list or not str(cls_list[0]).endswith("B"):
            continue
        raw = _clean(para.get_text(strip=True))
        if not raw:
            continue
        match = _CHAPTER_ENTRY_RE.match(raw)
        if not match:
            continue
        number = normalize_chapter_number(match.group(1))
        if not number or number in seen:
            continue
        seen.add(number)
        name = match.group(2).strip() or f"Chapter {number}"
        out.append((number, name))
    return out


def _clean(raw: str) -> str:
    return _WS.sub(" ", (raw or "").replace("\xa0", " ")).strip()


def parse_south_dakota_title_html(
    html: str,
    *,
    title_label: str,
    code_name: str = "South Dakota Codified Laws",
    max_statutes: Optional[int] = None,
    source_url: str = "",
) -> List[NormalizedStatute]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    statutes: List[NormalizedStatute] = []
    cur_hash = cur_num = cur_name = None
    cur_body: List[str] = []

    def _flush() -> None:
        if not cur_num or (max_statutes is not None and len(statutes) >= int(max_statutes)):
            return
        if cur_name and re.search(r"\b(repealed|reserved|expired|transferred)\b", cur_name, re.I):
            return
        body = " ".join(cur_body).strip()
        if len(body) < 20:
            return
        parts = cur_num.split("-")
        statutes.append(
            NormalizedStatute(
                state_code="SD",
                state_name="South Dakota",
                statute_id=f"{code_name} § {cur_num}",
                code_name=code_name,
                title_number=parts[0] if parts else title_label,
                chapter_number=parts[1] if len(parts) > 1 else None,
                section_number=cur_num,
                section_name=(cur_name or f"Section {cur_num}")[:200],
                full_text=body[:14000],
                source_url=source_url or title_html_url(title_label),
                official_cite=f"S.D. Codified Laws § {cur_num}",
                metadata=StatuteMetadata(),
                structured_data={
                    "source_kind": "official_south_dakota_title_html",
                    "source_authority_class": "official",
                    "discovery_method": "sdlegislature_statutes_all_true",
                    "skip_hydrate": True,
                },
            )
        )

    for para in soup.find_all("p"):
        cls_list = para.get("class", []) or []
        if not cls_list:
            continue
        cls = cls_list[0]
        if _CLASS_TOC_RE.search(cls):
            continue
        cls_hash = _HASH_RE.match(cls)
        cls_hash = cls_hash.group(1) if cls_hash else None
        if cls_hash is None:
            continue
        if _CLASS_HEADING_RE.search(cls):
            plain = _clean(para.get_text(strip=True))
            if _SOURCE_RE.match(plain):
                continue
            sec_num = None
            for span in para.find_all("span"):
                if "SENU" in " ".join(span.get("class", []) or []):
                    match = SECTION_NUM_RE.match(span.get_text(strip=True) or "")
                    if match:
                        sec_num = match.group(1)
                        break
            if sec_num is None:
                for anchor in para.find_all("a", href=True):
                    num = (parse_qs(urlparse(anchor["href"]).query).get("Statute") or [""])[0]
                    match = SECTION_NUM_RE.match(num)
                    if match:
                        sec_num = match.group(1)
                        break
            if sec_num and SECTION_NUM_RE.match(plain) and sec_num.split("-")[0] == str(title_label):
                _flush()
                cur_hash = cls_hash
                cur_num = sec_num
                cur_name = re.sub(r"^[\d\.\-A-Za-z]*?" + re.escape(sec_num) + r"\.?\s*", "", plain).strip()
                cur_body = []
            continue
        if cls_hash != cur_hash or cur_num is None:
            continue
        txt = _clean(para.get_text(" "))
        if txt and not _SOURCE_RE.match(txt):
            cur_body.append(txt)
    _flush()
    return statutes


def configured_title_html_path() -> Optional[Path]:
    for key in ("SOUTH_DAKOTA_TITLE_HTML", "SOUTH_DAKOTA_CHAPTER_HTML"):
        raw = str(os.environ.get(key) or "").strip()
        if not raw:
            continue
        path = Path(raw).expanduser()
        if path.is_file():
            return path
    return None


def parse_configured_south_dakota_title(
    *,
    code_name: str = "South Dakota Codified Laws",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    path = configured_title_html_path()
    if path is None:
        return []
    html = decode_sdlegislature_bytes(path.read_bytes())
    stem = path.stem.split(".")[0]
    title_label = stem.split("-")[0] if stem else "22"
    source = (
        chapter_html_url(title_label, stem.split("-", 1)[1])
        if "-" in stem
        else title_html_url(title_label)
    )
    return parse_south_dakota_title_html(
        html,
        title_label=title_label,
        code_name=code_name,
        max_statutes=max_statutes,
        source_url=source,
    )
