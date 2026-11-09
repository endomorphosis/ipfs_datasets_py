"""Decide which municipal rows are laws, and cite the ones that are.

The national admit path refuses a municipal slug. This module is the
municipal sibling. It does not download or upload. It does not invent a
section number or rewrite the words of an ordinance. A line break is put
back before a printed CJK article mark that the scrape joined to the
previous sentence. A Bluebook string is the existing US formatter. Any
other printed citation is an analog built from fields already on the row.
"""

from __future__ import annotations

import hashlib
import re
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
from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.heading_assignment import (
    assign_heading,
)
from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.placement import (
    classify_placement,
)
from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.structure import (
    _cjk_numeral_value,
    normalize_legal_text,
    segment_exclusive,
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
# A recital that names another provision is an enabling clause, not that provision.
_RECITAL = re.compile(
    r"(?i)\b(?:considerando|whereas|pursuant\s+to|nos\s+termos|disposto\s+n[oa]|having\s+regard)\b"
)
_NAMES_PROVISION = re.compile(r"(?i)\b(?:artigo|art\.?|article|section|sec\.?|§)\s*[0-9]")
# A cookie or privacy page is not a provision, even when its title is long enough
# for the instrument fallback. A privacy ordinance keeps a path that is not one of these.
_POLICY_URL = re.compile(
    r"(?i)(?:cookie|privacy-policy|privacypolicy|datenschutz|"
    r"politique-de-confidentialite|/privacy(?:/|$))"
)
# A press-release path is not the ordinance it mentions.
_NEWS_URL = re.compile(
    r"(?i)/(?:news|media-center|media-centre|blog|actualites|actualit%C3%A9s)(?:/|$)"
)
_ERROR_TITLE = re.compile(
    r"(?i)^(?:request rejected|access denied|403 forbidden|404(?: not found)?|"
    r"page not found|forbidden)$"
)
# The instrument word is printed. A CMS id, "Request Rejected", and a welcome
# title are not instrument names.
_MUNICIPAL_INSTRUMENT = re.compile(
    r"(?i)(?:\b(?:lei|leyes?|ordinances?|ordenanzas?|odluk[ae]|odluke|bylaws?|"
    r"by-laws?|besluit(?:en)?|verordeningen|règlements?|reglements?|arrêtés?|"
    r"arretes?|decretos?|decrees?|décrets?|decrets?|deliberaç(?:ão|oes|ões)|"
    r"portarias?|resoluções|resolucione?s|acuerdos?|рішення|токтом)\b)"
    r"|条例|條例|規則|規程|要項|要點|辦法|細則|自治條例"
)
_LABELED_LOCATOR = re.compile(
    r"(?i)(?:\b(?:articles?|arts?\.?|sections?|secs?\.?|chapters?|anexa)\b|§)"
    r"|第\s*[0-9一二三四五六七八九十百]+\s*[条條]"
)
_ANNEX_LINE = re.compile(r"(?i)^anexa(?:\s+nr\.?)?\s*([0-9]{1,4})\b")
_CJK_PRESENT = re.compile(r"[\u4e00-\u9fff]")
# The scrape joined the next printed article onto the previous sentence.
_CJK_ARTICLE_BREAK = re.compile(r"([。！？])\s*(第\s*[0-9]{1,4}\s*[条條])")
_CJK_ENUM_BREAK = re.compile(r"([。！？])\s*([一二三四五六七八九十百]+、)")
_CJK_HAS_ARTICLE = re.compile(r"第\s*[0-9一二三四五六七八九十百]+\s*[条條]")
_BARE_CJK_ITEM = re.compile(
    r"(?:^|[。！？\n])\s*([一二三四五六七八九十百]{1,3})[ \t]+"
)
_STRUCTURAL_EVIDENCE = frozenset({
    "title",
    "source_url",
    "source_field",
    "hierarchy_path",
    "source_hierarchy",
})


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
    if _policy_url(_first(row, "source_url", "url")):
        return CollectDecision(False, "site_page")
    if _ERROR_TITLE.match(_first(row, "title", "title_native", "html_title")):
        return CollectDecision(False, "site_page")
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
    if _news_url(_first(row, "source_url", "url")):
        return CollectDecision(False, "site_page")
    return CollectDecision(True, raw_reason)


def admit_municipal_row(row: Mapping[str, object]) -> MunicipalAdmission:
    """Project one row into cited law atoms, or refuse it with no text."""

    decision = collect_municipal_row(row)
    if not decision.accept:
        return MunicipalAdmission((), decision.reason)
    original = _text(row)
    restored = _restore_cjk_breaks(original)
    record = {
        "entry_cid": _first(row, "entry_cid", "cid"),
        "authority": _first(row, "authority", "place_name"),
        "jurisdiction": _first(row, "jurisdiction", "country_code"),
        "instrument_type": _instrument(row),
        "title": _first(row, "title", "title_native", "html_title"),
        "text": restored,
        "language": _first(row, "language") or "en",
        "source_url": _first(row, "source_url", "url") or None,
        "citation": None,
        "bluebook_citation": None,
        "provenance": {"citation_year": _year(row)},
    }
    atoms: list[dict[str, object]] = []
    unplaced: list[dict[str, object]] = []
    for atom in expand_legal_record(record):
        provenance = atom.get("provenance")
        if not isinstance(provenance, dict):
            continue
        if provenance.get("document_role") != "law":
            continue
        if _specific_locator(provenance):
            if restored != original:
                provenance["locator_recovery"] = "cjk_line"
            atoms.append(assign_municipal_citation(atom))
        else:
            unplaced.append(atom)
    if not atoms:
        bare = _bare_cjk_atoms(record)
        if bare:
            atoms.extend(bare)
            unplaced = []
    for atom in unplaced:
        placed = _place_instrument_atom(atom)
        if placed is not None:
            atoms.append(placed)
    preamble = _leading_preamble(record)
    if preamble is not None and not _text_already_kept(str(preamble.get("text") or ""), atoms):
        placed = _place_instrument_atom(preamble)
        if placed is not None:
            atoms.insert(0, placed)
    if not atoms:
        return MunicipalAdmission((), "not_queryable")
    return MunicipalAdmission(tuple(atoms), "law")


def _place_instrument_atom(atom: Mapping[str, object]) -> dict[str, object] | None:
    """Keep a law atom that has an instrument name and no provision number.

    The name comes from the source title. A page id, a CMS path, and the
    preposition "o" are not stored as a section.
    """

    copied = dict(atom)
    raw = copied.get("provenance")
    provenance = dict(raw) if isinstance(raw, dict) else {}
    copied["provenance"] = provenance
    if provenance.get("document_role") != "law":
        role, reason = classify_document_role(copied)
        if role != "law":
            return None
        provenance["document_role"] = role
        provenance["document_role_reason"] = reason
    if _specific_locator(provenance):
        return None
    title = copied.get("title") if isinstance(copied.get("title"), str) else ""
    text = copied.get("text") if isinstance(copied.get("text"), str) else ""
    url = copied.get("source_url") if isinstance(copied.get("source_url"), str) else ""
    if _is_homepage(url) and not _municipal_instrument_name(title):
        return None
    context = {
        "title": title,
        "text": text,
        "source_url": url,
        "source_type": copied.get("instrument_type") or "",
    }
    if _municipal_instrument_name(title):
        context["instrument_title"] = title
    assigned = assign_heading(context)
    if _safe_structural(assigned, title):
        for key, value in assigned.locators:
            if key not in _LOCATORS or (key == "section" and value.casefold() == "o"):
                continue
            provenance[key] = value
        if _specific_locator(provenance):
            provenance["heading_status"] = "structural"
            provenance["heading_evidence"] = assigned.evidence
            if assigned.instrument:
                provenance["heading_instrument"] = assigned.instrument
            provenance["locator_recovery"] = assigned.evidence
            cited = assign_municipal_citation(copied)
            return cited
    annex = _annex_section(title, text)
    if annex:
        provenance["section"] = annex
        provenance["heading_status"] = "structural"
        provenance["heading_evidence"] = "annex"
        provenance["locator_recovery"] = "annex"
        return assign_municipal_citation(copied)
    instrument = assigned.instrument.strip()
    if assigned.status == "unresolved" or not instrument or instrument.isdigit():
        if _municipal_instrument_name(title):
            instrument = title.strip()
            assigned_status = "instrument_only"
        else:
            return None
    else:
        assigned_status = assigned.status
    if assigned_status != "instrument_only":
        return None
    language = copied.get("language") if isinstance(copied.get("language"), str) else ""
    placement = classify_placement(
        text,
        language,
        status="instrument_only",
        instrument=instrument,
    )
    if placement == "whole_instrument" and _RECITAL.search(text) and _NAMES_PROVISION.search(text):
        placement = "enabling_instrument"
    provenance["heading_status"] = "instrument_only"
    provenance["heading_instrument"] = instrument
    provenance["heading_placement"] = placement
    provenance.pop("section", None)
    authority = _string(copied.get("authority"))
    country = _country_name(_string(copied.get("jurisdiction")))
    copied["citation"] = ", ".join(piece for piece in (authority, country, instrument) if piece)
    copied["bluebook_citation"] = None
    provenance["citation_form"] = "analog"
    provenance["locator_recovery"] = "instrument"
    return copied


def _leading_preamble(record: Mapping[str, object]) -> dict[str, object] | None:
    """Return the text that sits before the first real provision, if it is one."""

    text = record.get("text")
    if not isinstance(text, str) or not text.strip():
        return None
    language = record.get("language") if isinstance(record.get("language"), str) else ""
    cleaned = normalize_legal_text(text)
    units = segment_exclusive(cleaned, language=language)
    if len(units) < 2 or units[0].kind != "preamble":
        return None
    body = units[0].body.strip()
    if len(body) < 40:
        return None
    parent = record.get("entry_cid") if isinstance(record.get("entry_cid"), str) else ""
    atom = dict(record)
    atom["text"] = body
    raw = record.get("provenance")
    atom["provenance"] = dict(raw) if isinstance(raw, dict) else {}
    atom["entry_cid"] = hashlib.sha256(f"preamble\n{parent}\n{body}".encode()).hexdigest()
    return atom


def _text_already_kept(body: str, atoms: list[dict[str, object]]) -> bool:
    folded = body.casefold()
    for atom in atoms:
        text = atom.get("text")
        if isinstance(text, str) and folded in text.casefold():
            return True
    return False


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


def _restore_cjk_breaks(text: str) -> str:
    """Put a line break back before a printed article the scrape joined on.

    ``第 2 條`` after ``。`` is the next provision. ``第二十九條`` inside the
    sentence is a citation and is left where it is. The words are unchanged.
    """

    if not _CJK_PRESENT.search(text):
        return text
    text = _CJK_ARTICLE_BREAK.sub(r"\1\n\2", text)
    return _CJK_ENUM_BREAK.sub(r"\1\n\2", text)


def _bare_cjk_atoms(record: Mapping[str, object]) -> list[dict[str, object]]:
    """Split ``一`` / ``二`` provisions when the scrape omitted the enumeration comma.

    A document that already prints ``第 N 條`` keeps those articles. The list
    has to start at 一 and increase. A later sentence that merely contains a
    numeral is not a provision.
    """

    text = record.get("text")
    if not isinstance(text, str) or not text or _CJK_HAS_ARTICLE.search(text):
        return []
    numbered: list[tuple[int, int]] = []
    for match in _BARE_CJK_ITEM.finditer(text):
        raw = _cjk_numeral_value(match.group(1))
        if not raw or not raw.isdigit():
            continue
        number = int(raw)
        if number < 1 or number > 200:
            continue
        numbered.append((number, match.start(1)))
    if len(numbered) < 2 or numbered[0][0] != 1:
        return []
    if any(numbered[index][0] >= numbered[index + 1][0] for index in range(len(numbered) - 1)):
        return []
    parent = record.get("entry_cid") if isinstance(record.get("entry_cid"), str) else ""
    atoms: list[dict[str, object]] = []
    for index, (number, start) in enumerate(numbered):
        end = numbered[index + 1][1] if index + 1 < len(numbered) else len(text)
        body = text[start:end].strip()
        if len(body) < 16:
            continue
        atom = dict(record)
        raw = record.get("provenance")
        provenance = dict(raw) if isinstance(raw, dict) else {}
        provenance["article"] = str(number)
        provenance["section"] = str(number)
        provenance["heading_status"] = "structural"
        provenance["heading_evidence"] = "cjk_enum"
        provenance["locator_recovery"] = "cjk_enum"
        provenance["document_role"] = "law"
        atom["provenance"] = provenance
        atom["text"] = body
        atom["entry_cid"] = hashlib.sha256(f"cjk\n{parent}\n{number}\n{body}".encode()).hexdigest()
        atoms.append(assign_municipal_citation(atom))
    if len(atoms) < 2:
        return []
    return atoms


def _safe_structural(assigned: object, title: str) -> bool:
    status = getattr(assigned, "status", "")
    evidence = getattr(assigned, "evidence", "")
    if status != "structural" or evidence not in _STRUCTURAL_EVIDENCE:
        return False
    if evidence == "title" and _LABELED_LOCATOR.search(title) is None:
        return False
    return True


def _annex_section(title: str, text: str) -> str:
    """Use ``Anexa nr. N`` from the title or the first line. Ignore the parent act number."""

    for source in (title, _first_line(text)):
        match = _ANNEX_LINE.match(source.strip())
        if match is None:
            continue
        number = int(match.group(1))
        if 1 <= number <= 400:
            return f"Anexa {match.group(1)}"
    return ""


def _first_line(text: str) -> str:
    for line in text.splitlines():
        if line.strip():
            return line.strip()
    return ""


def _municipal_instrument_name(title: str) -> bool:
    text = " ".join(title.split())
    if len(text) < 8 or len(text) > 300 or text.isdigit():
        return False
    if _ERROR_TITLE.match(text):
        return False
    return _MUNICIPAL_INSTRUMENT.search(text) is not None


def _policy_url(url: str) -> bool:
    return _POLICY_URL.search(url) is not None


def _news_url(url: str) -> bool:
    return _NEWS_URL.search(urlsplit(url).path) is not None


def _is_homepage(url: str) -> bool:
    return urlsplit(url).path in {"", "/"}


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
        if not value or (key == "section" and value.casefold() == "o"):
            continue
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
