"""Official ILGA ILCS FTP bulk parser.

Adapted from Vaquill-AI/open-us-law ``ilga_bulk`` (Apache-2.0). Illinois
publishes ``Section Sequence.txt`` plus per-section HTML under
``https://www.ilga.gov/ftp/ILCS/``. Does not auto-download the tree; operators
point ``ILLINOIS_BULK_ZIP`` at a local copy.
"""

from __future__ import annotations

import os
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from .base_scraper import NormalizedStatute, StatuteMetadata

FTP_BASE = "https://www.ilga.gov/ftp/ILCS"
SECTION_VIEW = "https://www.ilga.gov/legislation/ilcs/ilcs.asp"
_WS = re.compile(r"\s+")
_TYPES = frozenset({"A", "F", "H", "K"})
TYPE_SECTION = "K"


@dataclass(frozen=True)
class ManifestEntry:
    raw: str
    chapter: str
    act: str
    doc_type: str
    section: str

    @property
    def is_section(self) -> bool:
        return self.doc_type == TYPE_SECTION

    def citation(self) -> str:
        return f"{self.chapter} ILCS {self.act}/{self.section}"


def _act_from_code(aaaaa: str) -> str:
    first4 = int(aaaaa[:4])
    fifth = aaaaa[4]
    return str(first4) if fifth == "0" else f"{first4}.{fifth}"


def parse_line(line: str) -> Optional[ManifestEntry]:
    text = line.rstrip("\r\n")
    if len(text) < 10 or not text[:9].isdigit() or text[9] not in _TYPES:
        return None
    return ManifestEntry(
        raw=text,
        chapter=str(int(text[0:4])),
        act=_act_from_code(text[4:9]),
        doc_type=text[9],
        section=text[10:].strip(),
    )


def parse_manifest(text: str) -> List[ManifestEntry]:
    return [entry for line in text.splitlines() if (entry := parse_line(line)) is not None]


def section_url(manifest_code: str) -> str:
    code = str(manifest_code or "").strip()
    cccc = code[0:4]
    act4 = code[4:8]
    return f"{FTP_BASE}/Ch%20{cccc}/Act%20{act4}/{code}.html"


def html_to_text(html: str) -> str:
    if not html or not str(html).strip():
        return ""
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return _WS.sub(" ", html).strip()
    soup = BeautifulSoup(html, "html.parser")
    node = soup.find("div", align="justify") or soup
    return _WS.sub(" ", node.get_text(separator=" ")).strip()


def _iter_zip_html(archive: zipfile.ZipFile) -> dict:
    mapping = {}
    for name in archive.namelist():
        lower = name.lower()
        if lower.endswith(".html") or lower.endswith(".htm"):
            mapping[Path(name).name] = name
    return mapping


def parse_illinois_bulk_zip(
    zip_path: Path,
    *,
    code_name: str = "Illinois Compiled Statutes",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    """Parse a local ILCS FTP zip (manifest + section HTML) into statutes."""

    path = Path(zip_path)
    if not path.is_file():
        raise FileNotFoundError(f"Illinois bulk zip missing: {path}")
    statutes: List[NormalizedStatute] = []
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        manifest_name = next(
            (
                name
                for name in names
                if name.lower().endswith("section sequence.txt")
                or name.lower().endswith("section_sequence.txt")
            ),
            None,
        )
        if manifest_name is None:
            return []
        entries = [row for row in parse_manifest(archive.read(manifest_name).decode("utf-8", "replace")) if row.is_section]
        html_by_file = _iter_zip_html(archive)
        for entry in entries:
            if max_statutes is not None and len(statutes) >= int(max_statutes):
                break
            member = html_by_file.get(f"{entry.raw}.html") or html_by_file.get(f"{entry.raw}.htm")
            if member is None:
                continue
            text = html_to_text(archive.read(member).decode("utf-8", "replace"))
            if len(text) < 20:
                continue
            statutes.append(
                NormalizedStatute(
                    state_code="IL",
                    state_name="Illinois",
                    statute_id=f"{code_name} § {entry.citation()}",
                    code_name=code_name,
                    title_number=entry.chapter,
                    chapter_number=entry.act,
                    section_number=f"{entry.act}/{entry.section}",
                    section_name=f"Section {entry.section}",
                    full_text=text[:14000],
                    source_url=section_url(entry.raw),
                    official_cite=entry.citation(),
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "official_illinois_ilcs_ftp",
                        "source_authority_class": "official",
                        "discovery_method": "ilga_section_sequence_manifest",
                        "skip_hydrate": True,
                    },
                )
            )
    return statutes


def configured_bulk_zip_path() -> Optional[Path]:
    raw = str(os.environ.get("ILLINOIS_BULK_ZIP") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


_ILCS_ACT_RE = re.compile(r"(\d+)\s+ILCS\s+(\d+[A-Za-z]?)/")
_SEC_CITE_RE = re.compile(r"^\((\d+)\s+ILCS\s+(\d+[A-Za-z]?)/([^)]+)\)\s*$")


def chapter_links(html: str, *, base_url: str = "https://www.ilga.gov") -> List[Tuple[str, str, str]]:
    """TOC ``Acts?ChapterID=&ChapterNumber=`` rows."""

    from urllib.parse import parse_qsl, urljoin, urlparse

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    out: List[Tuple[str, str, str]] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href") or "")
        if "Acts?" not in href or "ChapterID=" not in href or "ChapterNumber=" not in href:
            continue
        params = dict(parse_qsl(urlparse(href).query))
        number = (params.get("ChapterNumber") or "").strip()
        if not number or number in seen:
            continue
        seen.add(number)
        name = _WS.sub(" ", (anchor.get_text(" ") or "").replace("\xa0", " ")).strip()
        out.append((number, name or f"Chapter {number}", urljoin(base_url, href)))
    return out


def act_links(html: str, *, base_url: str = "https://www.ilga.gov") -> List[Tuple[str, str, str, str]]:
    """Chapter page ``Articles?ActID=`` rows: ``(act, chapter, name, url)``."""

    from urllib.parse import parse_qsl, urljoin, urlparse

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    out: List[Tuple[str, str, str, str]] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href") or "")
        if "Articles?" not in href or "ActID=" not in href:
            continue
        params = dict(parse_qsl(urlparse(href).query))
        act_id = (params.get("ActID") or "").strip()
        if not act_id or act_id in seen:
            continue
        raw = _WS.sub(" ", (anchor.get_text(" ") or "").replace("\xa0", " ")).strip()
        match = _ILCS_ACT_RE.match(raw)
        if not match:
            continue
        seen.add(act_id)
        out.append((match.group(2), match.group(1), raw, urljoin(base_url, href)))
    return out


def section_cites(html: str) -> List[Tuple[str, str, str]]:
    """FullText ``(5 ILCS 70/0.01)`` cites; skip ``Art. N heading``."""

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    out: List[Tuple[str, str, str]] = []
    seen: set[str] = set()
    for code in soup.find_all("code"):
        text = _WS.sub(" ", (code.get_text(" ") or "").replace("\xa0", " ")).strip()
        match = _SEC_CITE_RE.match(text)
        if not match:
            continue
        chapter, act, path = match.group(1), match.group(2), match.group(3).strip()
        if "heading" in path.lower() or "art." in path.lower():
            continue
        key = f"{chapter}/{act}/{path}"
        if key in seen:
            continue
        seen.add(key)
        out.append((chapter, act, path))
    return out


def full_text_url(act_id: str, chapter_id: str) -> str:
    return (
        "https://www.ilga.gov/legislation/ILCS/details"
        f"?ActID={act_id}&ChapterID={chapter_id}&SeqStart=&ChapAct=FullText"
    )
