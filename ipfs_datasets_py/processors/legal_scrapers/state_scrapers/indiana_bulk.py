"""Official Indiana Code HTML zip parser.

Adapted from Vaquill-AI/open-us-law ``in_bulk`` (Apache-2.0). iga.in.gov
publishes a year-templated HTML zip:

    https://iga.in.gov/ic/{year}/{year}-Indiana-Code-html.zip

The live site geo-fences the zip; this adapter never auto-downloads. Operators
point ``INDIANA_BULK_ZIP`` at a local copy.
"""

from __future__ import annotations

import html as html_lib
import os
import re
import zipfile
from pathlib import Path
from typing import Iterator, List, Optional, Tuple

from .base_scraper import NormalizedStatute, StatuteMetadata

_STRUCT_DIV = re.compile(r'<div class="(title|article|chapter|section)" id="([^"]+)"')
_SHORTDESC = re.compile(r'<span id="shortdescription"[^>]*>(.*?)</span>', re.DOTALL)
_P_BLOCK = re.compile(r"<p\b[^>]*>(.*?)</p>", re.DOTALL)
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")
_RESERVED = ("repealed", "expired", "renumbered", "transferred", "reserved", "vacated")


def zip_url(year: int | str) -> str:
    token = str(int(year))
    return f"https://iga.in.gov/ic/{token}/{token}-Indiana-Code-html.zip"


def _text(fragment: str) -> str:
    text = _TAG.sub("", fragment)
    text = html_lib.unescape(text)
    text = text.replace("\xa0", " ").replace("\u2005", " ").replace("\u202f", " ")
    return _WS.sub(" ", text).strip()


def iter_section_blocks(html: str) -> Iterator[Tuple[str, str, List[str], Optional[str]]]:
    """Yield ``(section_id, heading, paragraphs, status)`` from one title HTML file."""

    matches = list(_STRUCT_DIV.finditer(html or ""))
    for index, match in enumerate(matches):
        cls, node_id = match.group(1), match.group(2)
        if cls != "section":
            continue
        end = matches[index + 1].start() if index + 1 < len(matches) else len(html)
        block = html[match.start() : end]
        short = _SHORTDESC.search(block)
        heading = _text(short.group(1)) if short else ""
        paragraphs = [_text(item.group(1)) for item in _P_BLOCK.finditer(block) if _text(item.group(1))]
        blob = f"{heading} {paragraphs[0] if paragraphs else ''}".lower()
        status = None
        for keyword in _RESERVED:
            if keyword in blob:
                status = "repealed" if keyword in ("repealed", "expired", "vacated") else "reserved"
                break
        yield node_id, heading, paragraphs, status


def parse_indiana_bulk_zip(
    zip_path: Path,
    *,
    code_name: str = "Indiana Code",
    max_statutes: Optional[int] = None,
    code_year: str = "2026",
) -> List[NormalizedStatute]:
    """Parse official Indiana Code HTML zip into NormalizedStatute rows."""

    path = Path(zip_path)
    if not path.is_file():
        raise FileNotFoundError(f"Indiana bulk zip missing: {path}")
    statutes: List[NormalizedStatute] = []
    with zipfile.ZipFile(path) as archive:
        names = sorted(name for name in archive.namelist() if name.lower().endswith(".html"))
        for name in names:
            if max_statutes is not None and len(statutes) >= int(max_statutes):
                break
            html = archive.read(name).decode("utf-8", errors="replace")
            for node_id, heading, paragraphs, status in iter_section_blocks(html):
                if max_statutes is not None and len(statutes) >= int(max_statutes):
                    break
                if status:
                    continue
                body = " ".join(paragraphs).strip()
                if len(body) < 20:
                    continue
                title_num = node_id.split("-", 1)[0]
                source_url = (
                    f"https://iga.in.gov/legislative/laws/{code_year}/ic/titles/{title_num}"
                    f"#{node_id}"
                )
                statutes.append(
                    NormalizedStatute(
                        state_code="IN",
                        state_name="Indiana",
                        statute_id=f"{code_name} § {node_id}",
                        code_name=code_name,
                        title_number=title_num,
                        section_number=node_id,
                        section_name=(heading[:200] if heading else f"Section {node_id}"),
                        full_text=body[:14000],
                        source_url=source_url,
                        official_cite=f"Ind. Code § {node_id}",
                        metadata=StatuteMetadata(),
                        structured_data={
                            "source_kind": "official_indiana_code_html_zip",
                            "source_authority_class": "official",
                            "discovery_method": "iga_indiana_code_html_zip",
                            "code_year": str(code_year),
                            "skip_hydrate": True,
                        },
                    )
                )
    return statutes


def configured_bulk_zip_path() -> Optional[Path]:
    raw = str(os.environ.get("INDIANA_BULK_ZIP") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


API_BASE = "https://api.iga.in.gov"
SITE_BASE = "https://iga.in.gov"


def titles_api_url(year: int | str = 2024) -> str:
    return f"{API_BASE}/{int(year)}/ic/titles"


def _payload_list(data, *keys: str) -> list:
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return []
    for key in keys:
        value = data.get(key)
        if isinstance(value, list):
            return value
    return []


def _number(obj: dict, *keys: str) -> str:
    for key in keys:
        value = obj.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def titles_from_payload(data) -> List[Tuple[str, str]]:
    """``GET /{year}/ic/titles`` rows. No live API call."""

    out: List[Tuple[str, str]] = []
    seen: set[str] = set()
    for item in _payload_list(data, "titles", "items", "data", "results"):
        if not isinstance(item, dict):
            continue
        number = _number(item, "titleNumber", "number", "title", "id")
        if not number or number in seen:
            continue
        seen.add(number)
        name = str(item.get("name") or item.get("titleName") or item.get("title") or f"Title {number}")
        out.append((number, name))
    return out


def nested_from_payload(data, *, kind: str) -> List[Tuple[str, str]]:
    """Articles/chapters/sections lists from an IGA JSON object."""

    key_map = {
        "article": ("articles", "articleNumber", "article", "articleName"),
        "chapter": ("chapters", "chapterNumber", "chapter", "chapterName"),
        "section": ("sections", "sectionNumber", "section", "sectionName"),
    }
    list_key, number_key, alt_key, name_key = key_map[kind]
    out: List[Tuple[str, str]] = []
    seen: set[str] = set()
    for item in _payload_list(data, list_key, "items", "data"):
        if not isinstance(item, dict):
            continue
        number = _number(item, number_key, "number", alt_key, "id")
        if not number or number in seen:
            continue
        seen.add(number)
        name = str(item.get(name_key) or item.get("name") or item.get(alt_key) or number)
        out.append((number, name))
    return out


def normalize_section(raw: str, title: str, article: str, chapter: str) -> str:
    parts = re.split(r"[-.]", str(raw or "").strip())
    if len(parts) == 4:
        return "-".join(str(int(part)) if part.isdigit() else part for part in parts)
    t = str(int(title)) if str(title).isdigit() else title
    a = str(int(article)) if str(article).isdigit() else article
    c = str(int(chapter)) if str(chapter).isdigit() else chapter
    s = str(int(raw)) if str(raw).isdigit() else str(raw or "").strip()
    return f"{t}-{a}-{c}-{s}"
