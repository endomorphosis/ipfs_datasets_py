"""Official Georgia OCGA title-text dump parser.

Georgia's live HTML tree is an Angular SPA with no free official bulk zip.
An operator-supplied local dump of official title text (PDF extract or
saved statute bodies) can be admitted as official: no nav/footer SPA chrome,
no archive transport. Even exact Title 1-53 filename coverage is only a local
inventory check; it cannot certify freshness or an exhaustive live section
frontier. This does not auto-download the commercial OCGA.

Local dumps: ``GEORGIA_TITLE_TEXT``, ``GEORGIA_TITLE_TEXT_DIR``,
``GEORGIA_TITLE_PDF``, ``GEORGIA_TITLE_PDF_DIR``. PDFs are never auto-downloaded.
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from .georgia_archive import (
    NAV_MARKERS,
    TITLE_NUMBERS,
    official_section_url,
    official_title_url,
)
from .base_scraper import NormalizedStatute, StatuteMetadata

_SECTION_RE = re.compile(
    r"(?m)^(?:(?:O\.C\.G\.A\.|OCGA)\s+)?"
    r"(?:§|&sect;|&#167;)?\s*"
    r"(?P<num>\d{1,2}[A-Za-z]?-\d+[A-Za-z0-9.-]*)\.\s+"
    r"(?P<head>[^\n]+)"
)
_RESERVED = re.compile(r"\b(repealed|reserved|expired|renumbered)\b", re.IGNORECASE)
_WS = re.compile(r"\s+")
_TITLE_DUMP_STEM_RE = re.compile(
    r"^(?:title|ocga)[-_ ]?(?P<number>\d{1,3})$",
    re.IGNORECASE,
)


class GeorgiaTitleCoverageError(RuntimeError):
    """Configured OCGA title dumps do not cover the complete 1-53 inventory."""

    def __init__(self, coverage: Dict[str, Any]):
        self.coverage = dict(coverage)
        details: List[str] = []
        for key in (
            "missing",
            "extra",
            "duplicates",
            "unparseable",
            "unreadable",
            "empty",
            "mismatched",
        ):
            value = self.coverage.get(key)
            if value:
                details.append(f"{key}={value}")
        suffix = "; ".join(details) or "unknown coverage defect"
        super().__init__(f"Georgia configured title inventory is incomplete: {suffix}")


def _clean(text: str) -> str:
    return _WS.sub(" ", (text or "").replace("\xa0", " ")).strip()


def parse_georgia_title_text(
    text: str,
    *,
    source_url: str = "",
    code_name: str = "Official Code of Georgia Annotated",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    body = text or ""
    lines = []
    for line in body.splitlines():
        lowered = line.lower()
        if any(marker in lowered for marker in NAV_MARKERS):
            continue
        lines.append(line)
    cleaned = "\n".join(lines)
    matches = list(_SECTION_RE.finditer(cleaned))
    statutes: List[NormalizedStatute] = []
    for index, match in enumerate(matches):
        if max_statutes is not None and len(statutes) >= int(max_statutes):
            break
        number = match.group("num")
        heading = match.group("head").strip()
        if _RESERVED.search(heading):
            continue
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(cleaned)
        section_body = _clean(cleaned[start:end])
        if any(marker in section_body.lower() for marker in NAV_MARKERS):
            continue
        if len(section_body) < 40:
            continue
        parts = number.split("-")
        official = official_section_url(number)
        statutes.append(
            NormalizedStatute(
                state_code="GA",
                state_name="Georgia",
                statute_id=f"{code_name} § {number}",
                code_name=code_name,
                title_number=parts[0] if parts else None,
                chapter_number=parts[1] if len(parts) > 1 else None,
                section_number=number,
                section_name=heading[:200],
                full_text=section_body[:14000],
                source_url=source_url or official,
                official_cite=f"Ga. Code Ann. § {number}",
                metadata=StatuteMetadata(),
                structured_data={
                    "source_kind": "official_georgia_title_text",
                    "source_authority_class": "official",
                    "discovery_method": "georgia_title_text_dump",
                    "official_title_url": official_title_url(parts[0]) if parts else None,
                    "skip_hydrate": True,
                },
            )
        )
    return statutes


def _title_number_from_path(path: Path) -> Optional[str]:
    """Return a canonical title number only for an explicit dump filename.

    Inventory coverage must never infer a title from trailing digits or fall
    back to Title 16.  ``title-16.txt`` and ``ocga_16.pdf`` are accepted;
    unrelated names remain usable by bounded parsers but are not inventory
    evidence.
    """

    match = _TITLE_DUMP_STEM_RE.fullmatch(path.stem.strip())
    if match is None:
        return None
    return str(int(match.group("number")))


def _extract_pdf_text(pdf_path: Path) -> str:
    try:
        import pdfplumber
    except ImportError:
        pdfplumber = None
    if pdfplumber is not None:
        try:
            lines: List[str] = []
            with pdfplumber.open(str(pdf_path)) as pdf:
                for page in pdf.pages:
                    lines.append(page.extract_text() or "")
            return "\n".join(lines)
        except Exception:
            pass
    try:
        from pypdf import PdfReader
    except ImportError:
        return ""
    try:
        reader = PdfReader(str(pdf_path))
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception:
        return ""


def parse_georgia_title_pdf(
    pdf_path: Path,
    *,
    source_url: str = "",
    code_name: str = "Official Code of Georgia Annotated",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    text = _extract_pdf_text(pdf_path)
    if not text.strip():
        return []
    title = _title_number_from_path(pdf_path)
    return parse_georgia_title_text(
        text,
        source_url=source_url or (official_title_url(title) if title else ""),
        code_name=code_name,
        max_statutes=max_statutes,
    )


def configured_title_text_paths() -> List[Path]:
    paths: List[Path] = []
    for key in ("GEORGIA_TITLE_TEXT", "GEORGIA_TITLE_PDF"):
        raw = str(os.environ.get(key) or "").strip()
        if raw:
            path = Path(raw).expanduser()
            if path.is_file():
                paths.append(path)
    for key, suffixes in (
        ("GEORGIA_TITLE_TEXT_DIR", {".txt", ".text"}),
        ("GEORGIA_TITLE_PDF_DIR", {".pdf"}),
    ):
        raw_dir = str(os.environ.get(key) or "").strip()
        if not raw_dir:
            continue
        directory = Path(raw_dir).expanduser()
        if directory.is_dir():
            paths.extend(
                sorted(
                    child
                    for child in directory.iterdir()
                    if child.is_file() and child.suffix.lower() in suffixes
                )
            )
    return paths


def configured_title_text_path() -> Optional[Path]:
    paths = configured_title_text_paths()
    return paths[0] if paths else None


def _title_sort_key(number: str) -> tuple[int, str]:
    match = re.match(r"(\d+)", str(number or ""))
    return (int(match.group(1)) if match else 999, str(number or ""))


def configured_title_coverage(
    paths: Optional[Sequence[Path]] = None,
) -> Dict[str, Any]:
    """Inspect strict filename coverage for the OCGA Title 1-53 inventory."""

    selected = list(paths) if paths is not None else configured_title_text_paths()
    expected = set(TITLE_NUMBERS)
    by_title: Dict[str, List[str]] = {}
    unparseable: List[str] = []
    for path in selected:
        number = _title_number_from_path(path)
        if number is None:
            unparseable.append(path.as_posix())
            continue
        by_title.setdefault(number, []).append(path.as_posix())

    present = set(by_title)
    duplicates = {
        number: sorted(names)
        for number, names in sorted(
            by_title.items(), key=lambda item: _title_sort_key(item[0])
        )
        if len(names) != 1
    }
    missing = sorted(expected - present, key=_title_sort_key)
    extra = sorted(present - expected, key=_title_sort_key)
    result: Dict[str, Any] = {
        "expected": sorted(expected, key=_title_sort_key),
        "present": sorted(present, key=_title_sort_key),
        "missing": missing,
        "extra": extra,
        "duplicates": duplicates,
        "unparseable": sorted(unparseable),
        "unreadable": [],
        "empty": [],
        "mismatched": {},
        "path_count": len(selected),
    }
    result["complete"] = not any(
        result[key] for key in ("missing", "extra", "duplicates", "unparseable")
    )
    return result


def require_complete_configured_title_coverage(
    paths: Optional[Sequence[Path]] = None,
) -> Dict[str, Any]:
    """Require exactly one strictly named configured dump for every Title 1-53."""

    coverage = configured_title_coverage(paths)
    if not coverage["complete"]:
        raise GeorgiaTitleCoverageError(coverage)
    return coverage


def covered_title_numbers(paths: Optional[Sequence[Path]] = None) -> List[str]:
    """Title numbers present in operator ``GEORGIA_TITLE_TEXT`` / ``_PDF`` dumps."""

    out: List[str] = []
    seen: set[str] = set()
    for path in paths if paths is not None else configured_title_text_paths():
        number = _title_number_from_path(path)
        if not number or number in seen:
            continue
        seen.add(number)
        out.append(number)

    return sorted(out, key=_title_sort_key)


def parse_configured_georgia_title(
    *,
    code_name: str = "Official Code of Georgia Annotated",
    max_statutes: Optional[int] = None,
    paths: Optional[Sequence[Path]] = None,
    require_complete_inventory: bool = False,
) -> List[NormalizedStatute]:
    selected = list(paths) if paths is not None else configured_title_text_paths()
    if require_complete_inventory and max_statutes is not None:
        raise ValueError(
            "complete Georgia title coverage cannot be parsed with max_statutes"
        )
    coverage = (
        require_complete_configured_title_coverage(selected)
        if require_complete_inventory
        else {}
    )
    statutes: List[NormalizedStatute] = []
    seen: set[str] = set()
    empty: List[str] = []
    unreadable: List[str] = []
    mismatched: Dict[str, List[str]] = {}
    for path in selected:
        if max_statutes is not None and len(statutes) >= int(max_statutes):
            break
        remaining = (
            None if max_statutes is None else max(0, int(max_statutes) - len(statutes))
        )
        title = _title_number_from_path(path)
        source = official_title_url(title) if title else ""
        try:
            payload = path.read_bytes()
        except OSError:
            if require_complete_inventory:
                unreadable.append(path.as_posix())
                continue
            raise
        dump_sha256 = hashlib.sha256(payload).hexdigest()
        if path.suffix.lower() == ".pdf":
            rows = parse_georgia_title_pdf(
                path,
                source_url=source,
                code_name=code_name,
                max_statutes=remaining,
            )
        else:
            rows = parse_georgia_title_text(
                payload.decode("utf-8", errors="replace"),
                source_url=source,
                code_name=code_name,
                max_statutes=remaining,
            )
        if require_complete_inventory:
            if not rows:
                empty.append(str(title))
            wrong_titles = sorted(
                {
                    str(row.title_number or "")
                    for row in rows
                    if str(row.title_number or "") != str(title)
                },
                key=_title_sort_key,
            )
            if wrong_titles:
                mismatched[str(title)] = wrong_titles
        for row in rows:
            key = str(row.section_number or "")
            if key in seen:
                continue
            seen.add(key)
            structured = dict(row.structured_data or {})
            structured.update(
                {
                    "configured_title_number": title,
                    "configured_title_dump_sha256": dump_sha256,
                    "configured_title_dump_size_bytes": len(payload),
                }
            )
            row.structured_data = structured
            statutes.append(row)
    if require_complete_inventory and (empty or unreadable or mismatched):
        coverage.update(
            {
                "complete": False,
                "empty": sorted(set(empty), key=_title_sort_key),
                "unreadable": sorted(set(unreadable)),
                "mismatched": dict(
                    sorted(
                        mismatched.items(), key=lambda item: _title_sort_key(item[0])
                    )
                ),
            }
        )
        raise GeorgiaTitleCoverageError(coverage)
    if require_complete_inventory:
        for row in statutes:
            structured = dict(row.structured_data or {})
            structured.update(
                {
                    "configured_title_inventory_complete": True,
                    "configured_title_inventory_count": len(TITLE_NUMBERS),
                    "fresh_live_frontier_verified": False,
                    "full_corpus_admissible": False,
                }
            )
            row.structured_data = structured
    return statutes
