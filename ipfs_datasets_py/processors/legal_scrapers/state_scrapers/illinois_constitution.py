"""Official Illinois Constitution article-page parser.

Adapted from Vaquill-AI/open-us-law ``ingest_state_constitutions.scrape_il``
(Apache-2.0). ilga.gov/commission/lrb/con{1-14}.htm is one article per page.
Section numbers may be decimal inserts (``8.1``). There is no con15.htm;
the 1970 transition schedule is not current official text.

Local dumps: ``ILLINOIS_CONSTITUTION_HTML`` or ``ILLINOIS_CONSTITUTION_HTML_DIR``.
No auto-download of ILGA pages.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional

from .base_scraper import NormalizedStatute, StatuteMetadata

IL_CONST_URL_TMPL = "https://www.ilga.gov/commission/lrb/con{n}.htm"
_IL_ARTICLE_HEAD_RE = re.compile(r"ARTICLE\s+([IVXLC]+)\s*\n\s*([^\n]+)")
_IL_SECTION_RE = re.compile(r"\n\s*SECTION\s+(\d+(?:\.\d+)?[A-Za-z]?)\.?\s*([^\n]*)\n")
_RESERVED = re.compile(r"\b(repealed|reserved|expired|renumbered)\b", re.IGNORECASE)
_WS = re.compile(r"\s+")


def parse_illinois_constitution_html(
    html: str,
    *,
    code_name: str = "Illinois Constitution",
    source_url: str = "",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    body_text = "\n" + BeautifulSoup(html or "", "html.parser").get_text("\n", strip=True)
    art_match = _IL_ARTICLE_HEAD_RE.search(body_text)
    art_id = art_match.group(1) if art_match else "I"
    matches = list(_IL_SECTION_RE.finditer(body_text))
    statutes: List[NormalizedStatute] = []
    url = source_url or IL_CONST_URL_TMPL.format(n=1)
    for index, match in enumerate(matches):
        if max_statutes is not None and len(statutes) >= int(max_statutes):
            break
        number = match.group(1)
        heading = (match.group(2) or "").strip()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body_text)
        raw = _WS.sub(" ", body_text[match.end() : end].replace("\xa0", " ")).strip()
        if len(raw) < 40:
            continue
        if _RESERVED.search(heading) or _RESERVED.search(raw[:160]):
            continue
        cite = f"Ill. Const. art. {art_id}, § {number}"
        statutes.append(
            NormalizedStatute(
                state_code="IL",
                state_name="Illinois",
                statute_id=cite,
                code_name=code_name,
                title_number=art_id,
                section_number=number,
                section_name=(heading or raw.split(".", 1)[0])[:200],
                full_text=raw,
                source_url=url,
                official_cite=cite,
                metadata=StatuteMetadata(),
                structured_data={
                    "source_kind": "official_illinois_constitution_html",
                    "source_authority_class": "official",
                    "discovery_method": "ilga_lrb_constitution_html",
                    "article_id": art_id,
                    "skip_hydrate": True,
                },
            )
        )
    return statutes


def configured_constitution_html_path() -> Optional[Path]:
    raw = str(os.environ.get("ILLINOIS_CONSTITUTION_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


def configured_constitution_html_dir() -> Optional[Path]:
    raw = str(os.environ.get("ILLINOIS_CONSTITUTION_HTML_DIR") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_dir() else None


def parse_configured_illinois_constitution(
    *,
    code_name: str = "Illinois Constitution",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    dir_path = configured_constitution_html_dir()
    if dir_path is not None:
        out: List[NormalizedStatute] = []
        files = sorted(dir_path.glob("con*.htm")) + sorted(dir_path.glob("con*.html"))
        seen = set()
        for path in files:
            if path in seen or not path.is_file():
                continue
            seen.add(path)
            if max_statutes is not None and len(out) >= int(max_statutes):
                break
            remaining = None if max_statutes is None else max(0, int(max_statutes) - len(out))
            out.extend(
                parse_illinois_constitution_html(
                    path.read_text(encoding="utf-8", errors="replace"),
                    code_name=code_name,
                    source_url=IL_CONST_URL_TMPL.format(n=path.stem.replace("con", "") or 1),
                    max_statutes=remaining,
                )
            )
        return out
    path = configured_constitution_html_path()
    if path is None:
        return []
    return parse_illinois_constitution_html(
        path.read_text(encoding="utf-8", errors="replace"),
        code_name=code_name,
        source_url=IL_CONST_URL_TMPL.format(n=1),
        max_statutes=max_statutes,
    )
