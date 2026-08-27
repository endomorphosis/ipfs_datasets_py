"""Official Pennsylvania Constitution article parser.

Adapted from Vaquill-AI/open-us-law ``ingest_state_constitutions.scrape_pa``
(Apache-2.0). Each article is ``00.{N:03d}..HTM`` with inline ``§ N.`` sections.

Local dump: ``PENNSYLVANIA_CONSTITUTION_HTML``.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional

from .base_scraper import NormalizedStatute, StatuteMetadata

PA_ARTICLE_URL_TMPL = "https://www.legis.state.pa.us/WU01/LI/LI/CT/HTM/00/00.{n:03d}..HTM"
_PA_ROMAN = ("I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI")
_RESERVED = re.compile(r"\b(repealed|reserved|expired|renumbered)\b", re.IGNORECASE)
_WS = re.compile(r"\s+")


def pa_article_url(article_index: int) -> str:
    return PA_ARTICLE_URL_TMPL.format(n=max(1, int(article_index)))


def official_article_frontier() -> List[dict]:
    return [
        {
            "article_id": roman,
            "article_index": str(index),
            "official_url": pa_article_url(index),
            "source_authority_class": "official",
        }
        for index, roman in enumerate(_PA_ROMAN, start=1)
    ]


def _clean_pa_section_body(raw: str) -> str:
    text = re.sub(r"\n\s*00[a-zA-Z0-9]+s?\s*\n", "\n", raw or "")
    text = re.sub(r"\n\s*00[a-zA-Z0-9]+s?\s*$", "", text)
    return _WS.sub(" ", text).strip()


def parse_pennsylvania_constitution_html(
    html: str,
    *,
    article_id: str = "I",
    article_index: int = 1,
    code_name: str = "Pennsylvania Constitution",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    body_text = soup.get_text("\n", strip=True)
    article = str(article_id or "I")
    source = pa_article_url(article_index)
    statutes: List[NormalizedStatute] = []
    markers = list(re.finditer(r"§\s*(\d+(?:\.\d+)?[A-Za-z]?)\.\s*", body_text))
    for index, match in enumerate(markers):
        if max_statutes is not None and len(statutes) >= int(max_statutes):
            break
        number = match.group(1).strip()
        end = markers[index + 1].start() if index + 1 < len(markers) else len(body_text)
        span = body_text[match.end() : end]
        heading_match = re.match(r"([^\n]+)", span.strip())
        heading = _WS.sub(" ", heading_match.group(1) if heading_match else "").strip().rstrip(".")
        if _RESERVED.search(heading):
            continue
        body = _clean_pa_section_body(span)
        if heading and body.startswith(heading):
            body = _clean_pa_section_body(body[len(heading) :].lstrip(". "))
        if len(body) < 40:
            continue
        statutes.append(
            NormalizedStatute(
                state_code="PA",
                state_name="Pennsylvania",
                statute_id=f"Pa. Const. art. {article}, § {number}",
                code_name=code_name,
                title_number=article,
                section_number=number,
                section_name=(heading or f"Section {number}")[:200],
                full_text=body,
                source_url=source,
                official_cite=f"Pa. Const. art. {article}, § {number}",
                metadata=StatuteMetadata(),
                structured_data={
                    "source_kind": "official_pennsylvania_constitution_html",
                    "source_authority_class": "official",
                    "discovery_method": "legis_state_pa_us_ct_htm",
                    "article_id": article,
                    "skip_hydrate": True,
                },
            )
        )
    return statutes


def configured_constitution_html_path() -> Optional[Path]:
    raw = str(os.environ.get("PENNSYLVANIA_CONSTITUTION_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None
