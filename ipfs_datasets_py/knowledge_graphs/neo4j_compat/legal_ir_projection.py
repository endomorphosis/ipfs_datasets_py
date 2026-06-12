"""Legal IR helpers for Neo4j-compatible graph projections."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Mapping, Sequence, Tuple


_USCODE_CITATION_RE = re.compile(
    r"(?P<title>\d+[A-Za-z]*)\s+U\.?S\.?C\.?\s+"
    r"(?P<section>\d+[A-Za-z0-9]*(?:-[A-Za-z0-9]+)*(?:\.)?)",
    re.IGNORECASE,
)
_USCODE_SOURCE_ID_RE = re.compile(
    r"^us-code-(?P<title>\d+[A-Za-z]*)-(?P<section>[A-Za-z0-9][A-Za-z0-9.-]*?)"
    r"(?:-[0-9a-f]{8,})?$",
    re.IGNORECASE,
)
_TRAILING_SECTION_PUNCT_RE = re.compile(r"[.;:]+$")
_SECTION_PART_RE = re.compile(r"(?P<number>\d+)(?P<suffix>[A-Za-z]+)?")


def augment_legal_ir_projection_triples(
    triples: Sequence[Mapping[str, Any]],
) -> List[Dict[str, str]]:
    """Add canonical U.S. Code title/section triples for sparse graph inputs.

    The modal compiler usually emits these facts itself.  This fallback lives in
    the Neo4j compatibility lane so direct graph callers still get stable legal
    view coverage from a bare ``source_id`` or ``citation`` triple.
    """

    normalized = _normalize_triples(triples)
    if len(normalized) > 16:
        return normalized
    seen = {
        (triple["subject"], triple["predicate"], triple["object"])
        for triple in normalized
    }
    predicates_by_subject: Dict[str, set[str]] = {}
    for triple in normalized:
        predicates_by_subject.setdefault(triple["subject"], set()).add(
            triple["predicate"]
        )

    augmented = list(normalized)
    for triple in normalized:
        subject = triple["subject"]
        predicate = triple["predicate"]
        obj = triple["object"]
        components: List[Tuple[str, str]] = []
        existing_predicates = predicates_by_subject.setdefault(subject, set())
        if predicate == "source_id" and not _has_family(
            existing_predicates,
            "source_id_",
        ):
            components = _source_id_components(obj)
        elif predicate == "citation" and not _has_family(
            existing_predicates,
            "citation_",
        ):
            components = _citation_components(obj)
        if not components:
            continue

        for component_predicate, component_value in components:
            if component_predicate in existing_predicates:
                continue
            key = (subject, component_predicate, component_value)
            if key in seen:
                continue
            seen.add(key)
            existing_predicates.add(component_predicate)
            augmented.append(
                {
                    "subject": subject,
                    "predicate": component_predicate,
                    "object": component_value,
                }
            )
    return augmented


def _has_family(predicates: set[str], prefix: str) -> bool:
    return any(predicate.startswith(prefix) for predicate in predicates)


def _normalize_triples(triples: Sequence[Mapping[str, Any]]) -> List[Dict[str, str]]:
    normalized: List[Dict[str, str]] = []
    for triple in triples:
        subject = str(triple.get("subject", "")).strip()
        predicate = str(triple.get("predicate", "")).strip()
        obj = str(triple.get("object", "")).strip()
        if not subject or not predicate or not obj:
            continue
        normalized.append({"subject": subject, "predicate": predicate, "object": obj})
    return normalized


def _source_id_components(source_id: str) -> List[Tuple[str, str]]:
    match = _USCODE_SOURCE_ID_RE.match(source_id.strip())
    if not match:
        return []
    title = match.group("title")
    raw_section = match.group("section")
    section = _normalize_section(raw_section)
    components: List[Tuple[str, str]] = [
        ("source_id_scheme", "us-code"),
        ("source_id_title", title),
        ("source_id_title_number", _leading_number(title)),
        ("source_id_section", raw_section),
        ("source_id_section_raw", raw_section),
        ("source_id_section_normalized", section),
        ("source_id_citation_canonical", _canonical_usc_citation(title, section)),
        ("source_id_title_section_key", f"{title}:{section}"),
        ("source_id_section_component_profile", _section_profile(section)),
    ]
    if raw_section != section:
        components.append(("source_id_section_has_trailing_punct", "true"))
    else:
        components.append(("source_id_section_has_trailing_punct", "false"))
    return _clean_components(components)


def _citation_components(citation: str) -> List[Tuple[str, str]]:
    match = _USCODE_CITATION_RE.search(citation.strip())
    if not match:
        return []
    title = match.group("title")
    raw_section = match.group("section")
    section = _normalize_section(raw_section)
    components: List[Tuple[str, str]] = [
        ("citation_code", "U.S.C."),
        ("citation_title", title),
        ("citation_title_number", _leading_number(title)),
        ("citation_section", raw_section),
        ("citation_section_raw", raw_section),
        ("citation_section_normalized", section),
        ("citation_canonical", _canonical_usc_citation(title, section)),
        ("citation_title_section_key", f"{title}:{section}"),
        ("citation_section_component_profile", _section_profile(section)),
    ]
    if raw_section != section:
        components.append(("citation_section_has_trailing_punct", "true"))
    else:
        components.append(("citation_section_has_trailing_punct", "false"))
    return _clean_components(components)


def _normalize_section(section: str) -> str:
    return _TRAILING_SECTION_PUNCT_RE.sub("", section.strip())


def _canonical_usc_citation(title: str, section: str) -> str:
    if not title or not section:
        return ""
    return f"{title} U.S.C. {section}"


def _leading_number(value: str) -> str:
    match = _SECTION_PART_RE.match(value.strip())
    return match.group("number") if match else ""


def _section_profile(section: str) -> str:
    parts = _SECTION_PART_RE.fullmatch(section.strip())
    if not parts:
        return "mixed"
    return "numeric_alpha" if parts.group("suffix") else "numeric"


def _clean_components(components: Sequence[Tuple[str, str]]) -> List[Tuple[str, str]]:
    cleaned: List[Tuple[str, str]] = []
    seen: set[Tuple[str, str]] = set()
    for predicate, value in components:
        predicate = str(predicate or "").strip()
        value = str(value or "").strip()
        key = (predicate, value)
        if not predicate or not value or key in seen:
            continue
        seen.add(key)
        cleaned.append(key)
    return cleaned


__all__ = ["augment_legal_ir_projection_triples"]
