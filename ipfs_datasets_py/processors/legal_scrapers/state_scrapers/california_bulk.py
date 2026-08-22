"""Official California bulk CAML export (downloads.leginfo.legislature.ca.gov).

Adapted from Vaquill-AI/open-us-law ``ca_bulk`` (Apache-2.0). The HTML
LegInfo app publishes ``Disallow: /``; the downloads host is the sanctioned
database dump and is official, not a secondary mirror.
"""

from __future__ import annotations

import os
import re
import zipfile
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from .base_scraper import NormalizedStatute

OFFICIAL_DOWNLOADS_HOST = "downloads.leginfo.legislature.ca.gov"
OFFICIAL_SECTION_URL = (
    "https://leginfo.legislature.ca.gov/faces/codes_displaySection.xhtml"
    "?lawCode={code}&sectionNum={section}"
)

# LAW_SECTION_TBL columns (Vaquill ca_bulk/tables.py).
S_CODE, S_SECT, S_LOB = 1, 2, 14

_WS = re.compile(r"\s+")
_BLANKS = re.compile(r"\n{3,}")
_KNOWN_CAML = {
    "[document]",
    "caml:content",
    "content",
    "p",
    "h1",
    "br",
    "span",
    "table",
    "thead",
    "tbody",
    "tr",
    "td",
    "th",
    "col",
    "colgroup",
    "caml:fraction",
    "caml:numerator",
    "caml:denominator",
    "b",
    "i",
    "u",
    "sub",
    "sup",
    "em",
    "strong",
    "caml:tipin",
    "caml:labelledfield",
}
_PARA = {"p", "h1", "table"}
_ROW = {"tr"}
_CELL = {"td", "th"}


def session_zip_url(session: str) -> str:
    """Official pubinfo zip for one two-year legislative session."""

    year = str(session or "").strip() or "2025"
    return f"https://{OFFICIAL_DOWNLOADS_HOST}/pubinfo_{year}.zip"


def unquote_field(value: str) -> Optional[str]:
    text = str(value or "").strip()
    if text.startswith("`") and text.endswith("`") and len(text) >= 2:
        text = text[1:-1]
    if text in {"", "NULL"}:
        return None
    return text


def caml_to_text(xml: str) -> Tuple[str, Set[str]]:
    """Convert one CAML section body to plain text.

    Fractions become ``4/5`` (not ``45``). Tables keep row/cell text. Unknown
    tags keep inner text and are reported.
    """

    if not xml or not str(xml).strip():
        return "", set()
    try:
        from bs4 import BeautifulSoup
        from bs4.element import NavigableString, Tag
    except ImportError:
        return str(xml), set()

    soup = BeautifulSoup(xml, "html.parser")
    unknown = {
        tag.name.lower()
        for tag in soup.find_all(True)
        if tag.name and tag.name.lower() not in _KNOWN_CAML
    }

    def _walk(node: Any) -> str:
        if isinstance(node, NavigableString):
            return _WS.sub(" ", str(node))
        if not isinstance(node, Tag):
            return ""
        name = str(node.name or "").lower()
        if name == "br":
            return "\n"
        if name == "span":
            classes = node.get("class") or []
            if any("enspace" in str(item).lower() for item in classes) or not node.get_text(
                strip=True
            ):
                return " "
            return "".join(_walk(child) for child in node.children)
        if name == "caml:fraction":
            num = node.find("caml:numerator")
            den = node.find("caml:denominator")
            if num is not None and den is not None:
                frac = f"{num.get_text(strip=True)}/{den.get_text(strip=True)}"
                prev = node.previous_sibling
                if isinstance(prev, NavigableString) and prev.rstrip()[-1:].isdigit():
                    frac = " " + frac
                return frac
            return "".join(_walk(child) for child in node.children)
        inner = "".join(_walk(child) for child in node.children)
        if name in _CELL:
            return inner.strip() + " "
        if name in _ROW:
            return "\n" + inner.strip()
        if name in _PARA:
            return "\n\n" + inner + "\n\n"
        return inner

    text = _walk(soup)
    lines = [line.strip() for line in text.split("\n")]
    text = _BLANKS.sub("\n\n", "\n".join(lines)).strip()
    return text, unknown


def _iter_section_rows(table_text: str) -> Iterable[List[str]]:
    for line in table_text.splitlines():
        if not line.strip():
            continue
        yield line.split("\t")


def parse_california_bulk_zip(
    zip_path: Path,
    *,
    code_type: str,
    max_statutes: Optional[int] = None,
    code_name: str = "California Code",
) -> List[NormalizedStatute]:
    """Parse official pubinfo ZIP into NormalizedStatute rows for one code family."""

    wanted = str(code_type or "").strip().upper()
    if not wanted:
        return []
    path = Path(zip_path)
    if not path.is_file():
        raise FileNotFoundError(f"California bulk zip missing: {path}")
    statutes: List[NormalizedStatute] = []
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        table_name = next(
            (name for name in names if name.endswith("LAW_SECTION_TBL.dat")),
            None,
        )
        if table_name is None:
            return []
        table_text = archive.read(table_name).decode("utf-8", errors="replace")
        for row in _iter_section_rows(table_text):
            if max_statutes is not None and len(statutes) >= int(max_statutes):
                break
            if len(row) <= S_LOB:
                continue
            code = (unquote_field(row[S_CODE]) or "").upper()
            if code != wanted or code == "CONS":
                continue
            section = (unquote_field(row[S_SECT]) or "").rstrip(".")
            lob = unquote_field(row[S_LOB]) or ""
            if not section or not lob or lob not in names:
                continue
            try:
                caml = archive.read(lob).decode("utf-8", errors="replace")
            except Exception:
                continue
            text, _unknown = caml_to_text(caml)
            if len(text.strip()) < 20:
                continue
            source_url = OFFICIAL_SECTION_URL.format(code=code, section=f"{section}.")
            statutes.append(
                NormalizedStatute(
                    state_code="CA",
                    state_name="California",
                    statute_id=f"{code_name} § {section}",
                    code_name=code_name,
                    section_number=section,
                    section_name=f"Section {section}",
                    full_text=text[:14000],
                    source_url=source_url,
                    official_cite=f"Cal. {code} § {section}",
                    structured_data={
                        "source_kind": "official_california_bulk_caml",
                        "source_authority_class": "official",
                        "discovery_method": "leginfo_pubinfo_zip",
                        "bulk_host": OFFICIAL_DOWNLOADS_HOST,
                        "skip_hydrate": True,
                    },
                )
            )
    return statutes


def configured_bulk_zip_path() -> Optional[Path]:
    raw = str(os.environ.get("CALIFORNIA_BULK_ZIP") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None
