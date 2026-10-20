"""Admit one citable legal unit per export row.

The deterministic hierarchy parser in ``country_laws_ir.structure`` decides
the split. This module does not call a language model and does not invent
statute text. A parenthesized ``(a)`` or ``(1)`` marker stays on the parent
section. Chrome that normalizes to empty text is not a legal unit.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import replace
from typing import Mapping

from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.structure import (
    StructureUnit,
    normalize_legal_text,
    split_structured_units,
)
from ipfs_datasets_py.processors.legal_scrapers.world_law.document_role import (
    ROLES,
    classify_document_role,
)
from ipfs_datasets_py.processors.legal_scrapers.world_law.textutil import sha256_text

_JSONLD_TYPE = {
    "law": "Legislation",
    "metadata": "DigitalDocument",
    "informative": "WebPage",
}

_REPRESENTATIONS = frozenset({"record", "jsonld", "text"})
_SUBSECTION_UNIT = re.compile(r"^\(([0-9A-Za-z]{1,6})\)\s+\S")
# A subsection marker is a line-start "(a)" or "(1)". A mid-line "(this)" is not.
_SUBSECTION_TOKEN = re.compile(r"(?m)^[ \t]*\(([0-9A-Za-z]{1,6})\)")
# ``article`` and ``division`` are inherited from the parent record. Expand does
# not invent them, and a bluebook citation overwrites ``statute`` only.
_LOCATOR_KEYS = (
    "title",
    "chapter",
    "article",
    "division",
    "part",
    "statute",
    "section",
    "subsection",
    "hierarchy_path",
)


def expand_legal_record(record: Mapping[str, object]) -> list[dict[str, object]]:
    """Return atomic copies of one legal record.

    An empty list means the text was chrome only. A null ``text`` stays one
    row with ``provenance.atomic`` false. One unsplittable instrument stays
    one row and keeps its ``entry_cid``. Two or more article or section units
    become one row each, with a new ``entry_cid``.
    """

    base = _copy_record(record)
    text = base.get("text")
    if text is None:
        _ensure_role(base)
        _stamp(base, atomic=False, locator={})
        return [base]
    original = text if isinstance(text, str) else str(text)
    cleaned = normalize_legal_text(original)
    if not cleaned:
        return []
    base["text"] = cleaned
    _ensure_role(base)
    language = base.get("language")
    units = _coalesce_subsections(
        split_structured_units(cleaned, language=language if isinstance(language, str) else "")
    )
    citation = base.get("citation")
    citation_text = citation.strip() if isinstance(citation, str) else ""
    if len(units) < 2:
        if cleaned != original:
            base["content_sha256"] = sha256_text(cleaned)
        locator = _locator(units[0], citation_text) if units else {}
        if citation_text and "statute" not in locator:
            locator["statute"] = citation_text
        if "subsection" not in locator:
            tokens = _subsection_tokens(cleaned)
            if tokens:
                locator["subsection"] = ", ".join(tokens)
        _stamp(base, atomic=True, locator=locator)
        return [base]
    parent = base.get("entry_cid")
    parent_cid = parent if isinstance(parent, str) else ""
    atoms: list[dict[str, object]] = []
    for index, unit in enumerate(units):
        atom = _copy_record(base)
        body = unit.body.strip()
        atom["text"] = body
        atom["content_sha256"] = sha256_text(body)
        locator = _locator(unit, citation_text)
        _stamp(atom, atomic=True, locator=locator)
        atom["entry_cid"] = _atom_cid(parent_cid, index, unit, body)
        atoms.append(atom)
    return atoms


def render_atomic(record: Mapping[str, object], representation: str) -> dict[str, object]:
    """Render one already-atomic record as JSON-LD or pure text."""

    if representation == "jsonld":
        return _render_jsonld(record)
    if representation == "text":
        return _render_text(record)
    raise ValueError(representation)


def representation_names() -> frozenset[str]:
    return _REPRESENTATIONS


def _copy_record(record: Mapping[str, object]) -> dict[str, object]:
    copied = dict(record)
    raw = copied.get("provenance")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            raw = {}
    copied["provenance"] = dict(raw) if isinstance(raw, dict) else {}
    return copied


def _stamp(record: dict[str, object], *, atomic: bool, locator: Mapping[str, str]) -> None:
    provenance = record["provenance"]
    assert isinstance(provenance, dict)
    provenance["atomic"] = atomic
    for key in _LOCATOR_KEYS:
        value = locator.get(key)
        if isinstance(value, str) and value:
            provenance[key] = value


def _locator(unit: StructureUnit, citation: str) -> dict[str, str]:
    article = (unit.article_number or "").strip()
    section = (unit.section_number or "").strip()
    if unit.kind == "article" and not article:
        article = unit.number.strip()
    if unit.kind == "section" and not section:
        section = unit.number.strip()
    statute = citation or article
    provision = section
    if not provision and article and statute != article:
        provision = article
    locator: dict[str, str] = {}
    if unit.title_number:
        locator["title"] = unit.title_number
    if unit.chapter_number:
        locator["chapter"] = unit.chapter_number
    if unit.part_number:
        locator["part"] = unit.part_number
    if statute:
        locator["statute"] = statute
    if provision:
        locator["section"] = provision
    if unit.kind == "article" and article:
        locator["article"] = article
    if unit.subsections:
        locator["subsection"] = ", ".join(unit.subsections)
    if unit.hierarchy_path:
        locator["hierarchy_path"] = unit.hierarchy_path
    return locator


def _atom_cid(parent: str, index: int, unit: StructureUnit, body: str) -> str:
    raw = "\n".join((parent, str(index), unit.kind, unit.number, unit.hierarchy_path, body))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _is_subsection_unit(unit: StructureUnit) -> bool:
    return _SUBSECTION_UNIT.match(unit.body.lstrip()) is not None


def _merge_subsection(parent: StructureUnit, child: StructureUnit) -> StructureUnit:
    if child.char_start == parent.char_end:
        body = parent.body + child.body
        end = child.char_end
    else:
        body = parent.body.rstrip("\n") + "\n" + child.body.lstrip("\n")
        end = parent.char_end
    return replace(parent, body=body, char_end=end, subsections=_subsection_tokens(body))


def _subsection_tokens(text: str) -> tuple[str, ...]:
    seen: list[str] = []
    for match in _SUBSECTION_TOKEN.finditer(text):
        token = match.group(1)
        if token not in seen:
            seen.append(token)
        if len(seen) >= 40:
            break
    return tuple(seen)


def _coalesce_subsections(units: list[StructureUnit]) -> list[StructureUnit]:
    """Fold ``(a)`` / ``(1)`` bodies into the surrounding section.

    A document made only of those markers is one instrument. Returning an
    empty list tells the caller to keep the whole text.
    """

    if not units or all(_is_subsection_unit(unit) for unit in units):
        return []
    pending: list[StructureUnit] = []
    kept: list[StructureUnit] = []
    for unit in units:
        if _is_subsection_unit(unit):
            if kept:
                kept[-1] = _merge_subsection(kept[-1], unit)
            else:
                pending.append(unit)
            continue
        kept.append(_attach_leading(pending, unit))
        pending = []
    for leftover in pending:
        if kept:
            kept[-1] = _merge_subsection(kept[-1], leftover)
    return kept


def _attach_leading(pending: list[StructureUnit], unit: StructureUnit) -> StructureUnit:
    if not pending:
        return unit
    body = unit.body
    start = unit.char_start
    for earlier in reversed(pending):
        body = earlier.body.rstrip("\n") + "\n" + body.lstrip("\n")
        start = earlier.char_start
    return replace(unit, body=body, char_start=start, subsections=_subsection_tokens(body))


def _provenance(record: Mapping[str, object]) -> dict[str, object]:
    raw = record.get("provenance")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return {}
    return dict(raw) if isinstance(raw, dict) else {}


def _locator_from_provenance(provenance: Mapping[str, object]) -> dict[str, str]:
    locator: dict[str, str] = {}
    for key in _LOCATOR_KEYS:
        value = provenance.get(key)
        if isinstance(value, str) and value:
            locator[key] = value
    return locator


def _render_text(record: Mapping[str, object]) -> dict[str, object]:
    provenance = _provenance(record)
    text = record.get("text")
    atomic = provenance.get("atomic")
    return {
        "text": text if isinstance(text, str) else None,
        "entry_cid": _string_or_none(record.get("entry_cid")),
        "jurisdiction": _string_or_none(record.get("jurisdiction")),
        "citation": _string_or_none(record.get("citation")),
        "instrument_title": _string_or_none(record.get("title")),
        "language": _string_or_none(record.get("language")),
        "locator": _locator_from_provenance(provenance),
        "atomic": atomic if isinstance(atomic, bool) else False,
        "document_role": _role(provenance),
    }


def _render_jsonld(record: Mapping[str, object]) -> dict[str, object]:
    provenance = _provenance(record)
    role = _role(provenance)
    document: dict[str, object] = {
        "@context": "https://schema.org",
        "@type": _JSONLD_TYPE[role],
        "encodingFormat": "text/plain",
    }
    text = record.get("text")
    if isinstance(text, str) and text:
        document["text"] = text
    _put(document, "identifier", record.get("entry_cid"))
    _put(document, "legislationIdentifier", record.get("citation"))
    _put(document, "name", record.get("title"))
    _put(document, "legislationJurisdiction", record.get("jurisdiction"))
    _put(document, "inLanguage", record.get("language"))
    _put(document, "datePublished", record.get("published_date"))
    _put(document, "legislationDate", record.get("effective_date"))
    _put(document, "url", record.get("source_url"))
    _put(document, "legislationType", record.get("instrument_type"))
    properties: list[dict[str, str]] = []
    for key, value in _locator_from_provenance(provenance).items():
        properties.append({"@type": "PropertyValue", "propertyID": key, "value": value})
    properties.append({"@type": "PropertyValue", "propertyID": "document_role", "value": role})
    reason = provenance.get("document_role_reason")
    if isinstance(reason, str) and reason:
        properties.append(
            {"@type": "PropertyValue", "propertyID": "document_role_reason", "value": reason}
        )
    for key in ("bluebook_citation", "authority"):
        value = record.get(key)
        if isinstance(value, str) and value:
            properties.append({"@type": "PropertyValue", "propertyID": key, "value": value})
    atomic = provenance.get("atomic")
    if isinstance(atomic, bool):
        properties.append(
            {
                "@type": "PropertyValue",
                "propertyID": "atomic",
                "value": "true" if atomic else "false",
            }
        )
    if properties:
        document["additionalProperty"] = properties
    return document


def _put(document: dict[str, object], key: str, value: object) -> None:
    if isinstance(value, str) and value:
        document[key] = value


def _ensure_role(record: dict[str, object]) -> None:
    provenance = record["provenance"]
    assert isinstance(provenance, dict)
    current = provenance.get("document_role")
    if current in ROLES and isinstance(provenance.get("document_role_reason"), str):
        return
    role, reason = classify_document_role(record)
    provenance["document_role"] = role
    provenance["document_role_reason"] = reason


def _role(provenance: Mapping[str, object]) -> str:
    current = provenance.get("document_role")
    if current in ROLES:
        return str(current)
    return "law"


def _string_or_none(value: object) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None
