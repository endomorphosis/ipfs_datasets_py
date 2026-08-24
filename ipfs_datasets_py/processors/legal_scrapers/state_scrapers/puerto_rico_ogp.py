"""Official Puerto Rico OGP Biblioteca Virtual statute parser.

Adapted from Vaquill-AI/open-us-law ``pr_bulk.parse`` (Apache-2.0).
OGP publishes amendment-consolidated PDFs at ``bvirtualogp.pr.gov``.
Spanish is the enacted language. LPRA cites are secondary, never the
primary key. No auto-download of bulk PDFs.

Local dumps: ``PUERTO_RICO_OGP_TEXT`` or ``PUERTO_RICO_OGP_PDF``.
This module is outside LCR-084 exact-51 (50 states + DC).
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .base_scraper import NormalizedStatute, StatuteMetadata

OGP_BASE = "https://bvirtualogp.pr.gov/ogp/Bvirtual/leyesreferencia/PDF"
OGP_BASE_ORG = "https://bvirtualogp.pr.gov/ogp/Bvirtual/LeyesOrganicas/PDF"
OGP_BASES = (OGP_BASE, OGP_BASE_ORG)


def ogp_candidate_pdf_urls(stem: str) -> Tuple[str, str]:
    """A stem lives in leyesreferencia or LeyesOrganicas; try both."""

    token = str(stem or "").strip().lstrip("/")
    return (f"{OGP_BASE}/{token}.pdf", f"{OGP_BASE_ORG}/{token}.pdf")

# Hyphen must be followed by whitespace so "Seccion 1400Z-2(f)" is not a header.
_SEP = r"(?:[–—]|-\s)\s*"
_SEC_HDR = re.compile(r"(?m)^Secci[óo]n\s+(\d+(?:\.\d+){0,2}[A-Za-z]?)\s*\.?\s*" + _SEP)
_ART_HDR = re.compile(r"(?m)^Art[íi]culo\s+(\d+(?:\.\d+)?[A-Za-z]?)\s*\.?\s*" + _SEP)
_LPRA_TERM = re.compile(
    r"[-–—]?\s*\(\s*(\d+[A-Za-z]?)\s*L\.?\s*P\.?\s*R\.?\s*A\.?\s*§\s*([^)]+?)\s*\)"
)
_BODY_CUE = re.compile(
    r"\n\s*(?:\([a-z0-9]+\)|\(\d+\)|Este |Esta |Los |Las |El |La |Un |Una )"
)
_RESERVED = re.compile(r"\b(derogad[oa]|repealed|reservad[oa]|expirad[oa])\b", re.IGNORECASE)
_WS = re.compile(r"\s+")

OGP_CODES: Dict[str, Dict[str, str]] = {
    "incentivos": {
        "name": "Código de Incentivos de Puerto Rico (2019)",
        "citation": "Cód. Inc. P.R.",
        "pdf_url": f"{OGP_BASE}/60-2019.pdf",
        "marker": "seccion",
    },
    "civil": {
        "name": "Código Civil de Puerto Rico (2020)",
        "citation": "Cód. Civ. P.R.",
        "pdf_url": f"{OGP_BASE}/55-2020.pdf",
        "marker": "articulo",
    },
    "electoral": {
        "name": "Código Electoral de Puerto Rico (2020)",
        "citation": "Cód. Elect. P.R.",
        "pdf_url": f"{OGP_BASE}/58-2020.pdf",
        "marker": "articulo",
    },
}


def official_ogp_frontier() -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    for slug, meta in OGP_CODES.items():
        stem = str(meta["pdf_url"]).rsplit("/", 1)[-1].removesuffix(".pdf")
        primary, organic = ogp_candidate_pdf_urls(stem)
        rows.append(
            {
                "slug": slug,
                "code_name": meta["name"],
                "official_url": meta["pdf_url"],
                "organic_url": organic,
                "leyesreferencia_url": primary,
                "citation_prefix": meta["citation"],
                "source_authority_class": "official",
            }
        )
    return rows


def _clean(text: str) -> str:
    return _WS.sub(" ", (text or "").replace("\xa0", " ")).strip()


def _is_toc(heading: str, body: str) -> bool:
    blob = f"{heading} {(body or '')[:80]}"
    return (
        "…" in blob
        or "Tabla de Contenido" in blob
        or bool(re.search(r"\.{4,}", heading or ""))
    )


def _split_heading_body(span: str) -> Tuple[str, str, str]:
    term = _LPRA_TERM.search(span[:700])
    if term:
        return (
            span[: term.start()],
            f"{term.group(1)} L.P.R.A. § {term.group(2)}",
            span[term.end() :],
        )
    cuts = [200]
    for pattern in (r"\.\s", r"\[Nota"):
        match = re.search(pattern, span[:200])
        if match:
            cuts.append(match.start())
    cue = _BODY_CUE.search(span[:200])
    if cue:
        cuts.append(cue.start())
    cut = min(cuts)
    return span[:cut], "", span[cut:]


def parse_ogp_text(
    text: str,
    *,
    source_url: str = "",
    code_name: str = "Códigos de Puerto Rico",
    citation_prefix: str = "P.R.",
    marker: str = "mixed",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    """Parse OGP consolidated PDF text into official statute rows."""

    raw = text or ""
    toc = raw.rfind("Tabla de Contenido")
    if toc > len(raw) * 0.85 and re.search(r"…{5,}", raw[toc:]):
        raw = raw[:toc]
    if marker == "seccion":
        specs = [(_SEC_HDR, "Sección")]
    elif marker == "articulo":
        specs = [(_ART_HDR, "Artículo")]
    else:
        specs = [(_ART_HDR, "Artículo"), (_SEC_HDR, "Sección")]
    headers: List[Tuple[int, int, str, str]] = []
    for pattern, unit in specs:
        for match in pattern.finditer(raw):
            headers.append((match.start(), match.end(), match.group(1).strip(), unit))
    headers.sort()
    collected: List[Tuple[str, str, str, str, str]] = []
    for index, (start, hend, number, unit) in enumerate(headers):
        end = headers[index + 1][0] if index + 1 < len(headers) else len(raw)
        heading_raw, cite, body_raw = _split_heading_body(raw[hend:end])
        heading = _clean(heading_raw).rstrip(". ")
        body = _clean(body_raw).lstrip(".—–- );")
        if len(body) < 40:
            continue
        if _RESERVED.search(heading) or _RESERVED.search(body[:160]):
            continue
        collected.append((unit, number, heading, cite, body))

    best: Dict[Tuple[str, str], Tuple[str, str, str, str, str]] = {}
    for unit, number, heading, cite, body in collected:
        key = (unit, number)
        current = best.get(key)
        if current is None:
            best[key] = (unit, number, heading, cite, body)
            continue
        a_toc = _is_toc(heading, body)
        c_toc = _is_toc(current[2], current[4])
        if a_toc != c_toc:
            if not a_toc:
                best[key] = (unit, number, heading, cite, body)
        elif len(body) > len(current[4]):
            best[key] = (unit, number, heading, cite, body)

    statutes: List[NormalizedStatute] = []
    for unit, number, heading, cite, body in best.values():
        if _is_toc(heading, body):
            continue
        if max_statutes is not None and len(statutes) >= int(max_statutes):
            break
        official = source_url or OGP_BASE
        if "justia" in official.lower():
            official = OGP_BASE
        statutes.append(
            NormalizedStatute(
                state_code="PR",
                state_name="Puerto Rico",
                statute_id=f"{code_name} {unit} {number}",
                code_name=code_name,
                section_number=number,
                section_name=heading[:200] or f"{unit} {number}",
                full_text=body[:14000],
                source_url=official,
                official_cite=f"{citation_prefix} {unit} {number}",
                metadata=StatuteMetadata(),
                structured_data={
                    "source_kind": "official_puerto_rico_ogp_pdf",
                    "source_authority_class": "official",
                    "discovery_method": "ogp_bvirtual_consolidated_pdf",
                    "citation_lpra": cite or None,
                    "unit": unit,
                    "skip_hydrate": True,
                },
            )
        )
    return statutes


def _pdf_to_text(path: Path) -> str:
    try:
        import subprocess

        proc = subprocess.run(
            ["pdftotext", "-layout", "-q", str(path), "-"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if proc.returncode == 0 and proc.stdout:
            return proc.stdout.decode("utf-8", errors="replace")
    except Exception:
        pass
    return ""


def parse_configured_puerto_rico_ogp(
    *,
    code_name: str = "Códigos de Puerto Rico",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    raw_text = str(os.environ.get("PUERTO_RICO_OGP_TEXT") or "").strip()
    if raw_text:
        path = Path(raw_text).expanduser()
        if path.is_file():
            return parse_ogp_text(
                path.read_text(encoding="utf-8", errors="replace"),
                source_url=OGP_CODES["incentivos"]["pdf_url"],
                code_name=code_name,
                citation_prefix="Cód. Inc. P.R.",
                marker="seccion",
                max_statutes=max_statutes,
            )
    raw_pdf = str(os.environ.get("PUERTO_RICO_OGP_PDF") or "").strip()
    if raw_pdf:
        path = Path(raw_pdf).expanduser()
        if path.is_file():
            text = _pdf_to_text(path)
            if text:
                return parse_ogp_text(
                    text,
                    source_url=str(path),
                    code_name=code_name,
                    max_statutes=max_statutes,
                )
    return []
