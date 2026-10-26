"""Decide which municipal rows are laws, and cite the ones that are.

The national admit path refuses a municipal slug. This module is the
municipal sibling. It does not download, upload, or rewrite ordinance text.
A Bluebook string is the existing US formatter. Any other printed citation
is an analog built from fields already on the row.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping
from urllib.parse import urlsplit

from ipfs_datasets_py.processors.legal_data.iso_slug_crosswalk import _DEFAULT_NAMES
from ipfs_datasets_py.processors.legal_scrapers.bluebook_citation_validator.constants import (
    BLUEBOOK_STATE_ABBREVS,
    MAX_CITATION_YEAR,
    MIN_CITATION_YEAR,
)
from ipfs_datasets_py.processors.legal_scrapers.municipal_law_database_scrapers.hub.parquet_writer import (
    BLUEBOOK_STATE,
    format_bluebook,
)
from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.structure import (
    normalize_legal_text,
)
from ipfs_datasets_py.processors.legal_scrapers.world_law.atomic_corpus import (
    expand_legal_record,
)
from ipfs_datasets_py.processors.legal_scrapers.world_law.document_role import (
    classify_document_role,
)
from ipfs_datasets_py.processors.legal_scrapers.world_law.textutil import null_text

_SITE_TYPES = frozenset({
    "website",
    "homepage",
    "search",
    "about",
    "contact",
    "blog",
    "newsletter",
})
# A parenthetical such as "(a)" stays on its section. The printed citation
# uses that section number. A subsection-only atom is still queryable.
_LOCATORS = ("section", "article", "part", "chapter", "title", "subsection")
# Host words that are a different government or a non-law site.
_HOST_BLOCKS = (
    "k12",
    "school",
    "schools",
    "court",
    "courts",
    "chamber",
    "tourism",
    "visit",
    "citydirectory",
    "directory",
    "census",
    "wikipedia",
    "facebook",
    "blogspot",
)
_CODE_SUFFIXES = ("ecode360.com", "codepublishing.com", "municipalcodeonline.com")


@dataclass(frozen=True)
class CollectDecision:
    """Whether one raw row may be appended to the municipal card."""

    accept: bool
    reason: str


@dataclass(frozen=True)
class MunicipalAdmission:
    """Atoms kept for one row, or a refusal with no text."""

    atoms: tuple[dict[str, object], ...]
    reason: str


def collect_municipal_row(row: Mapping[str, object]) -> CollectDecision:
    """Return the drop decision for one HTML row.

    An accepted row is a law on the municipality's own host or on a code
    host. Breadcrumbs, blogs, and title shells are refused. The text is
    only read.
    """

    if row.get("source_official") is False:
        return CollectDecision(False, "unofficial")
    text = _text(row)
    if not text:
        return CollectDecision(False, "empty")
    host_reason = _host_reason(row)
    if host_reason:
        return CollectDecision(False, host_reason)
    labeled = {
        "title": _first(row, "title", "title_native", "html_title"),
        "language": _first(row, "language"),
        "source_url": _first(row, "source_url", "url"),
        "doc_type": _first(row, "doc_type", "instrument_type"),
    }
    raw_role, raw_reason = classify_document_role({**labeled, "text": text})
    if raw_role != "law":
        return CollectDecision(False, raw_reason)
    cleaned = normalize_legal_text(text)
    if not cleaned:
        return CollectDecision(False, "empty")
    cleaned_role, cleaned_reason = classify_document_role({**labeled, "text": cleaned})
    if cleaned_role != "law":
        return CollectDecision(False, cleaned_reason)
    doc_type = labeled["doc_type"].casefold()
    if raw_reason == "operative_text" and doc_type in _SITE_TYPES:
        return CollectDecision(False, "site_type")
    return CollectDecision(True, raw_reason)


def admit_municipal_row(row: Mapping[str, object]) -> MunicipalAdmission:
    """Project one row into cited law atoms, or refuse it with no text."""

    decision = collect_municipal_row(row)
    if not decision.accept:
        return MunicipalAdmission((), decision.reason)
    record = {
        "entry_cid": _first(row, "entry_cid", "cid"),
        "authority": _first(row, "authority", "place_name"),
        "jurisdiction": _first(row, "jurisdiction", "country_code"),
        "instrument_type": _instrument(row),
        "text": _text(row),
        "language": _first(row, "language") or "en",
        "source_url": _first(row, "source_url", "url") or None,
        "citation": None,
        "bluebook_citation": None,
        "provenance": {"citation_year": _year(row)},
    }
    atoms: list[dict[str, object]] = []
    for atom in expand_legal_record(record):
        provenance = atom.get("provenance")
        if not isinstance(provenance, dict):
            continue
        if provenance.get("document_role") != "law":
            continue
        if not _specific_locator(provenance):
            continue
        atoms.append(assign_municipal_citation(atom))
    if not atoms:
        return MunicipalAdmission((), "not_queryable")
    return MunicipalAdmission(tuple(atoms), "law")


def assign_municipal_citation(record: Mapping[str, object]) -> dict[str, object]:
    """Fill ``citation`` and ``citation_form`` from stored locators.

    ``bluebook_citation`` is set only for a US place whose state abbreviation,
    section, and source year are all stored and inside the checker range.
    A missing year omits the parentheses and is an analog. The formatter's
    ``§ {section}`` spacing is kept. The Rule 12.9 checker requires ``§``
    with no space, so it is not used to demote a string this formatter wrote.
    """

    copied = dict(record)
    raw = copied.get("provenance")
    provenance = dict(raw) if isinstance(raw, dict) else {}
    copied["provenance"] = provenance
    authority = _string(copied.get("authority"))
    section = _string(provenance.get("section"))
    year = _string(provenance.get("citation_year"))
    state = _us_state(_string(copied.get("jurisdiction")))
    kind = _code_kind(authority)
    if state in BLUEBOOK_STATE and authority and section and _year_in_range(year):
        abbrev = BLUEBOOK_STATE[state]
        cite = format_bluebook(authority, abbrev, section, year, kind)
        if abbrev in BLUEBOOK_STATE_ABBREVS:
            copied["citation"] = cite
            copied["bluebook_citation"] = cite
            provenance["citation_form"] = "bluebook"
            return copied
    if state in BLUEBOOK_STATE and authority and section:
        cite = format_bluebook(authority, BLUEBOOK_STATE[state], section, "", kind)
        copied["citation"] = cite
        copied["bluebook_citation"] = None
        provenance["citation_form"] = "analog"
        return copied
    copied["citation"] = _analog(copied, provenance)
    copied["bluebook_citation"] = None
    provenance["citation_form"] = "analog"
    return copied


def municipal_place_status(*, resolved: bool, admitted: int, refused: int) -> str:
    """Name a place as a law, a non-law scrape, a coverage gap, or unknown."""

    if admitted > 0:
        return "law"
    if refused > 0:
        return "not_a_law"
    if resolved:
        return "coverage_gap"
    return "unknown_place"


def _host_reason(row: Mapping[str, object]) -> str:
    url = _first(row, "source_url", "url")
    if not url:
        return "no_host"
    host = urlsplit(url).netloc.casefold().split(":", 1)[0]
    if host.startswith("www."):
        host = host[4:]
    if host.endswith("municipal.codes"):
        return "no_collector"
    if _code_host(host, url):
        return ""
    place = _letters(_first(row, "authority", "place_name", "name"))
    folded = _letters(host)
    if "county" in folded and "county" not in place:
        return "unrelated_host"
    if any(mark in folded for mark in _HOST_BLOCKS) and (not place or place not in folded):
        return "unrelated_host"
    return ""


def _code_host(host: str, url: str) -> bool:
    if host == "library.municode.com" or host.endswith(".library.municode.com"):
        return True
    if "amlegal.com" in host and "/codes/" in url.casefold():
        return True
    return host.endswith(_CODE_SUFFIXES)


def _code_kind(authority: str) -> str:
    folded = authority.casefold()
    if "county" in folded and "city" not in folded:
        return "County Code"
    return "Municipal Code"


def _analog(record: Mapping[str, object], provenance: Mapping[str, object]) -> str:
    authority = _string(record.get("authority"))
    country = _country_name(_string(record.get("jurisdiction")))
    instrument = _string(record.get("instrument_type")) or "ordinance"
    locator = _specific_locator(provenance)
    pieces = [piece for piece in (authority, country, f"{instrument} {locator}".strip()) if piece]
    return ", ".join(pieces)


def _specific_locator(provenance: Mapping[str, object]) -> str:
    for key in _LOCATORS:
        value = _string(provenance.get(key))
        if value:
            return value
    return ""


def _country_name(jurisdiction: str) -> str:
    code = jurisdiction.upper()
    if code == "US" or code.startswith("US-"):
        return "United States"
    return _DEFAULT_NAMES.get(code, jurisdiction)


def _us_state(jurisdiction: str) -> str:
    code = jurisdiction.upper()
    if code.startswith("US-") and len(code) == 5:
        return code[3:]
    return ""


def _year_in_range(year: str) -> bool:
    if len(year) != 4 or not year.isdigit():
        return False
    value = int(year)
    return MIN_CITATION_YEAR <= value <= MAX_CITATION_YEAR


def _year(row: Mapping[str, object]) -> str:
    value = row.get("citation_year")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return ""


def _instrument(row: Mapping[str, object]) -> str:
    value = _first(row, "instrument_type", "tipo")
    return value or "ordinance"


def _text(row: Mapping[str, object]) -> str:
    value = row.get("text")
    if isinstance(value, str) and value.strip():
        return value
    body = row.get("body")
    if isinstance(body, str):
        return body.strip()
    return ""


def _first(row: Mapping[str, object], *keys: str) -> str:
    for key in keys:
        found = null_text(row.get(key))
        if found:
            return found
    return ""


def _string(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    return ""


def _letters(value: str) -> str:
    return "".join(char for char in value.casefold() if char.isalnum())
