"""Legal IR helpers for Neo4j-compatible graph projections."""

from __future__ import annotations

import json
import math
import re
from typing import Any, Dict, List, Mapping, Sequence, Tuple


_USCODE_CITATION_RE = re.compile(
    r"(?P<title>\d+[A-Za-z]*)\s+U\.?S\.?C\.?\s+"
    r"(?:§{1,2}\s*|secs?\.?\s*|sections?\s+)?"
    r"(?P<section>\d+[A-Za-z0-9]*(?:[.-][A-Za-z0-9]+)*(?:\s+"
    r"(?:to|through|thru)\s+\d+[A-Za-z0-9]*(?:[.-][A-Za-z0-9]+)*)?(?:\.)?)",
    re.IGNORECASE,
)
_USCODE_SOURCE_ID_RE = re.compile(
    r"^us-code-(?P<title>\d+[A-Za-z]*)-(?P<section>[A-Za-z0-9][A-Za-z0-9 .-]*?)"
    r"(?:-[0-9a-f]{8,})?$",
    re.IGNORECASE,
)
_SECTION_MARKER_RE = re.compile(
    r"(?:§{1,2}|secs?\.?|sections?)\s*"
    r"(?P<section>\d+[A-Za-z0-9]*(?:[.-][A-Za-z0-9]+)*(?:\s+"
    r"(?:to|through|thru)\s+\d+[A-Za-z0-9]*(?:[.-][A-Za-z0-9]+)*|"
    r"\s*,\s*\d+[A-Za-z0-9]*(?:[.-][A-Za-z0-9]+)*)*(?:\.)?)",
    re.IGNORECASE,
)
_SECTION_HEADING_MARKER_RE = re.compile(
    r"(?:§{1,2}|secs?\.?|sections?)\s*"
    r"(?P<section>\d+[A-Za-z0-9]*(?:[.-][A-Za-z0-9]+)*(?:\s+"
    r"(?:to|through|thru)\s+\d+[A-Za-z0-9]*(?:[.-][A-Za-z0-9]+)*|"
    r"\s*,\s*\d+[A-Za-z0-9]*(?:[.-][A-Za-z0-9]+)*)*(?:\.)?)"
    r"\s*(?:[-.]|\])\s*(?P<heading>[^§]+?)(?="
    r"\s+From the U\.S\. Government Publishing Office\b|"
    r"\s+Editorial Notes\b|"
    r"\s+Statutory Notes\b|"
    r"\s+Pub\. L\.|"
    r"\s+\([a-z]\)(?:\([0-9A-Za-z]+\))?(?:\s|$)|"
    r"\s+\(Pub\.|\s+\(Added|\s+\(June|\s+\(Sept\.|"
    r"$)",
    re.IGNORECASE,
)
_CODE_TITLE_HEADING_RE = re.compile(
    r"\bTitle\s+(?P<label>\d+[A-Za-z]*)\s+-\s+"
    r"(?P<heading>.+?)(?="
    r"\s+\d+[A-Za-z]*\s+U\.?S\.?C\.?\b|"
    r"\s+United States Code\b|"
    r"\s+Subtitle\s+[A-Z0-9]+\s+-\s+|"
    r"\s+CHAPTER\s+[0-9A-Za-z-]+\s+-\s+|"
    r"\s+SUBCHAPTER\s+[IVXLCDM0-9A-Z-]+\s+-\s+|"
    r"\s+Secs?\.?\s+\d|$)",
    re.IGNORECASE,
)
_SUBTITLE_HEADING_RE = re.compile(
    r"\bSubtitle\s+(?P<label>[A-Z0-9]+)\s+-\s+"
    r"(?P<heading>.+?)(?="
    r"\s+PART\s+[IVXLCDM0-9A-Z-]+\s+-\s+|"
    r"\s+Part\s+[IVXLCDM0-9A-Z-]+\s+-\s+|"
    r"\s+CHAPTER\s+[0-9A-Za-z-]+\s+-\s+|"
    r"\s+SUBCHAPTER\s+[IVXLCDM0-9A-Z-]+\s+-\s+|"
    r"\s+Subchapter\s+[IVXLCDM0-9A-Z-]+\s+-\s+|"
    r"\s+Secs?\.?\s+\d|$)",
    re.IGNORECASE,
)
_CHAPTER_HEADING_RE = re.compile(
    r"\bCHAPTER\s+(?P<label>[0-9A-Za-z-]+)\s+-\s+"
    r"(?P<heading>.+?)(?="
    r"\s+SUBCHAPTER\s+[IVXLCDM0-9A-Z-]+\s+-\s+|"
    r"\s+Subchapter\s+[IVXLCDM0-9A-Z-]+\s+-\s+|"
    r"\s+PART\s+[IVXLCDM0-9A-Z-]+\s+-\s+|"
    r"\s+Part\s+[IVXLCDM0-9A-Z-]+\s+-\s+|"
    r"\s+subpart\s+[IVXLCDM0-9A-Z-]+\s+-\s+|"
    r"\s+Secs?\.?\s+\d|$)",
    re.IGNORECASE,
)
_SUBCHAPTER_HEADING_RE = re.compile(
    r"\bSubchapter\s+(?P<label>[IVXLCDM0-9A-Z-]+)\s+-\s+"
    r"(?P<heading>.+?)(?="
    r"\s+PART\s+[IVXLCDM0-9A-Z-]+\s+-\s+|"
    r"\s+Part\s+[IVXLCDM0-9A-Z-]+\s+-\s+|"
    r"\s+subpart\s+[IVXLCDM0-9A-Z-]+\s+-\s+|"
    r"\s+Secs?\.?\s+\d|$)",
    re.IGNORECASE,
)
_PART_HEADING_RE = re.compile(
    r"\bPart\s+(?P<label>[IVXLCDM0-9A-Z-]+)\s+-\s+"
    r"(?P<heading>.+?)(?="
    r"\s+CHAPTER\s+[0-9A-Za-z-]+\s+-\s+|"
    r"\s+SUBCHAPTER\s+[IVXLCDM0-9A-Z-]+\s+-\s+|"
    r"\s+Subchapter\s+[IVXLCDM0-9A-Z-]+\s+-\s+|"
    r"\s+subpart\s+[IVXLCDM0-9A-Z-]+\s+-\s+|"
    r"\s+Secs?\.?\s+\d|$)",
    re.IGNORECASE,
)
_SUBPART_HEADING_RE = re.compile(
    r"\bsubpart\s+(?P<label>[IVXLCDM0-9A-Z-]+)\s+-\s+"
    r"(?P<heading>.+?)(?=\s+Secs?\.?\s+\d|$)",
    re.IGNORECASE,
)
_SUBSECTION_HEADING_RE = re.compile(
    r"(?:^|\s)\((?P<label>[a-z])\)\s+"
    r"(?P<heading>[A-Z][A-Za-z0-9 ,'\-/&]{1,96}?)(?="
    r"\s+(?:A|An|Each|For|In|No|Nothing|Not|The|There|Whoever)\b|"
    r"\s+\([0-9A-Za-z]+\)|$)",
)
_PARAGRAPH_MARKER_RE = re.compile(r"(?:^|\s)\((?P<label>[0-9]+)\)\s+")
_DEFINITION_TERM_RE = re.compile(
    r"\([0-9]+\)\s+\"(?P<term>[^\"]{2,96})\"\s+means\b",
    re.IGNORECASE,
)
_USCODE_TITLE_RE = re.compile(
    r"(?P<title>\d+[A-Za-z]*)\s+U\.?S\.?C\.?",
    re.IGNORECASE,
)
_TRAILING_SECTION_PUNCT_RE = re.compile(r"[.;:]+$")
_SECTION_PART_RE = re.compile(r"(?P<number>\d+)(?P<suffix>[A-Za-z]+)?")
_SECTION_RANGE_RE = re.compile(
    r"^(?P<start>\d+[A-Za-z0-9]*(?:[.-][A-Za-z0-9]+)*)\s+"
    r"(?P<connector>to|through|thru)\s+"
    r"(?P<end>\d+[A-Za-z0-9]*(?:[.-][A-Za-z0-9]+)*)$",
    re.IGNORECASE,
)
_SECTION_LIST_RE = re.compile(
    r"^(?P<items>\d+[A-Za-z0-9]*(?:[.-][A-Za-z0-9]+)*(?:\s*,\s*"
    r"\d+[A-Za-z0-9]*(?:[.-][A-Za-z0-9]+)*)+)$",
    re.IGNORECASE,
)
_TEXT_PREDICATES = {
    "document_text",
    "sample_text",
    "source_text",
    "text",
}
_SOURCE_ID_ALIAS_PREDICATES = {
    "sample_id",
}
_LEGAL_IR_VIEW_GUIDANCE_PREDICATES = {
    "compiler_guidance_predicted_view",
    "compiler_guidance_target_component",
    "compiler_guidance_target_view",
    "predicted_component",
    "predicted_view",
    "target_component",
    "target_view",
}
_LEGAL_IR_GRAPH_REPAIR_ACTIONS = {
    "repair_multiview_legal_ir_graph_projection",
}
_NEO4J_COMPAT_TARGET_COMPONENT = "knowledge_graphs.neo4j_compat"
_RAW_LEGAL_IR_GUIDANCE_PAYLOAD_PREDICATES = {
    "attribution",
    "bridge_failure_name",
    "bundle",
    "compiler_guidance",
    "compiler_guidance_attribution",
    "compiler_guidance_bundle",
    "compiler_guidance_evidence",
    "compiler_guidance_legal_ir_view_gaps",
    "evidence",
    "guidance",
    "legal_ir_view_gaps",
    "metadata",
    "semantic_bundle",
    "semantic_bundle_key",
    "target_metrics",
    "vector_bundle",
}
_LEGAL_IR_VIEW_ALIASES = {
    "knowledge_graph": "knowledge_graphs.neo4j_compat",
    "knowledge_graphs_neo4j_compat": "knowledge_graphs.neo4j_compat",
    "knowledge_graphs.neo4j_compat": "knowledge_graphs.neo4j_compat",
    "neo4j_compat": "knowledge_graphs.neo4j_compat",
    "modal_frame_logic": "modal.frame_logic",
    "modal.frame_logic": "modal.frame_logic",
}
_MULTI_VALUE_COMPONENT_PREDICATES = {
    "section_definition_term",
    "section_paragraph_label",
    "section_subsection_label",
    "learned_legal_ir_predicted_view",
    "learned_legal_ir_predicted_view_weight",
    "learned_legal_ir_target_view",
    "learned_legal_ir_target_view_weight",
    "learned_legal_ir_view_gap",
    "learned_legal_ir_view_rank",
}
_MAX_AUGMENT_TRIGGER_TRIPLES_PER_SUBJECT = 8
_EDITORIAL_STATUS_KEYWORDS = (
    ("repealed", re.compile(r"\brepealed\b", re.IGNORECASE)),
    ("transferred", re.compile(r"\btransferred\b", re.IGNORECASE)),
    ("omitted", re.compile(r"\bomitted\b", re.IGNORECASE)),
)
_EDITORIAL_NOTES_START_RE = re.compile(
    r"\b(?:Editorial Notes?|Statutory Notes?|Historical and Revision Notes?)\b",
    re.IGNORECASE,
)
_CATCHLINE_BODY_START_RE = re.compile(
    r"\s+(?:A|An|Each|For|In|It|No|Nothing|Not|The|There|This|Whoever|"
    r"Pub\. L\.)\b.*$"
)
_SECTION_HEADING_SOURCE_TAIL_RE = re.compile(
    r"\s+(?:From the U\.S\. Government(?:\s+Publishing\s+Office)?|"
    r"Editorial\s+Notes?|Statutory\s+Notes?)\b.*$",
    re.IGNORECASE,
)
_DASH_TRANSLATION = str.maketrans(
    {
        "\u2010": "-",
        "\u2011": "-",
        "\u2012": "-",
        "\u2013": "-",
        "\u2014": "-",
        "\u2212": "-",
    }
)


def augment_legal_ir_projection_triples(
    triples: Sequence[Mapping[str, Any]],
) -> List[Dict[str, str]]:
    """Add canonical U.S. Code title/section triples for sparse graph inputs.

    The modal compiler usually emits these facts itself.  This fallback lives in
    the Neo4j compatibility lane so direct graph callers still get stable legal
    view coverage from a bare ``source_id`` or ``citation`` triple.
    """

    normalized = _normalize_triples(triples)
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
    augment_triggers_by_subject: Dict[str, int] = {}
    for triple in normalized:
        subject = triple["subject"]
        predicate = triple["predicate"]
        obj = triple["object"]
        components: List[Tuple[str, str]] = []
        existing_predicates = predicates_by_subject.setdefault(subject, set())
        is_augment_trigger = (
            predicate in {"source_id", "citation", *_SOURCE_ID_ALIAS_PREDICATES}
            or predicate in _TEXT_PREDICATES
        )
        if is_augment_trigger:
            trigger_count = augment_triggers_by_subject.get(subject, 0)
            if trigger_count >= _MAX_AUGMENT_TRIGGER_TRIPLES_PER_SUBJECT:
                continue
            augment_triggers_by_subject[subject] = trigger_count + 1
        if (
            predicate in {"source_id", *_SOURCE_ID_ALIAS_PREDICATES}
            and not _has_family(existing_predicates, "source_id_")
        ):
            components = _source_id_components(obj)
        elif predicate == "citation" and not _has_family(
            existing_predicates,
            "citation_",
        ):
            components = _citation_components(obj)
        elif predicate in _TEXT_PREDICATES:
            if not _has_family(existing_predicates, "citation_"):
                components.extend(_citation_components(obj))
                components.extend(_citation_from_text_components(obj))
            if not _has_family(existing_predicates, "source_id_"):
                components.extend(_source_id_from_text_components(obj))
            if not _has_family(existing_predicates, "section_marker"):
                components.extend(_section_text_components(obj))
            if "status_keyword" not in existing_predicates:
                components.extend(_editorial_status_components(obj))
            if not _has_family(existing_predicates, "usc_hierarchy_"):
                components.extend(_uscode_hierarchy_components(obj))
        if not components:
            continue

        for component_predicate, component_value in components:
            if (
                component_predicate in existing_predicates
                and component_predicate not in _MULTI_VALUE_COMPONENT_PREDICATES
            ):
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
    _append_source_citation_alignment_triples(
        augmented,
        predicates_by_subject=predicates_by_subject,
        seen=seen,
    )
    _append_structural_graph_view_alignment_triples(
        augmented,
        predicates_by_subject=predicates_by_subject,
        seen=seen,
    )
    _append_legal_ir_guidance_alignment_triples(
        augmented,
        predicates_by_subject=predicates_by_subject,
        seen=seen,
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
    normalized_source_id = _normalize_dashes(source_id).strip()
    match = _USCODE_SOURCE_ID_RE.match(normalized_source_id)
    if not match:
        return []
    title = match.group("title")
    raw_section = match.group("section")
    section = _normalize_section(raw_section)
    components: List[Tuple[str, str]] = [
        ("source_id", normalized_source_id),
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
    components.extend(_section_range_components("source_id_section", section))
    if raw_section != section:
        components.append(("source_id_section_has_trailing_punct", "true"))
    else:
        components.append(("source_id_section_has_trailing_punct", "false"))
    return _clean_components(components)


def _citation_components(citation: str) -> List[Tuple[str, str]]:
    match = _USCODE_CITATION_RE.search(_normalize_dashes(citation).strip())
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
    components.extend(_section_range_components("citation_section", section))
    if raw_section != section:
        components.append(("citation_section_has_trailing_punct", "true"))
    else:
        components.append(("citation_section_has_trailing_punct", "false"))
    return _clean_components(components)


def _normalize_section(section: str) -> str:
    return _TRAILING_SECTION_PUNCT_RE.sub("", _normalize_dashes(section).strip())


def _normalize_dashes(value: str) -> str:
    return str(value or "").translate(_DASH_TRANSLATION)


def _source_id_from_text_components(text: str) -> List[Tuple[str, str]]:
    normalized = _normalize_dashes(text)
    citation_match = _USCODE_CITATION_RE.search(normalized)
    if not citation_match:
        citation_match = _USCODE_TITLE_RE.search(normalized)
    section_match = _SECTION_MARKER_RE.search(normalized)
    if not citation_match or not section_match:
        return []
    title = citation_match.group("title")
    section = _lead_section(_normalize_section(section_match.group("section")))
    if not title or not section:
        return []
    source_id = f"us-code-{title}-{section}"
    return _source_id_components(source_id)


def _citation_from_text_components(text: str) -> List[Tuple[str, str]]:
    normalized = _normalize_dashes(text)
    title_match = _USCODE_TITLE_RE.search(normalized)
    section_match = _SECTION_MARKER_RE.search(normalized)
    if not title_match or not section_match:
        return []
    citation = (
        f"{title_match.group('title')} U.S.C. "
        f"{_normalize_section(section_match.group('section'))}"
    )
    return _citation_components(citation)


def _section_text_components(text: str) -> List[Tuple[str, str]]:
    normalized = _normalize_dashes(text)
    section_match = _SECTION_MARKER_RE.search(normalized)
    if not section_match:
        return []
    raw_section = section_match.group("section")
    section = _normalize_section(raw_section)
    components: List[Tuple[str, str]] = [
        ("section_marker", raw_section),
        ("section_marker_normalized", section),
        ("section_marker_component_profile", _section_profile(section)),
    ]
    components.extend(_section_range_components("section_marker", section))
    components.extend(_section_list_components("section_marker", section))

    heading_match = _SECTION_HEADING_MARKER_RE.search(normalized)
    if heading_match:
        heading = _clean_heading_text(heading_match.group("heading"))
        if heading:
            components.append(("section_heading_tail", heading))
            components.append(("section_catchline", heading))
            parts = _section_heading_parts(heading)
            if len(parts) > 1:
                components.append(("section_heading_part_count", str(len(parts))))
                for index, part in enumerate(parts, start=1):
                    components.append((f"section_heading_part_{index}", part))
    components.extend(_section_body_structure_components(normalized))
    return _clean_components(components)


def _uscode_hierarchy_components(text: str) -> List[Tuple[str, str]]:
    normalized = _normalize_dashes(text)
    components: List[Tuple[str, str]] = []
    components.extend(
        _hierarchy_heading_components(
            normalized,
            pattern=_CODE_TITLE_HEADING_RE,
            prefix="usc_hierarchy_title",
        )
    )
    components.extend(
        _hierarchy_heading_components(
            normalized,
            pattern=_SUBTITLE_HEADING_RE,
            prefix="usc_hierarchy_subtitle",
        )
    )
    components.extend(
        _hierarchy_heading_components(
            normalized,
            pattern=_CHAPTER_HEADING_RE,
            prefix="usc_hierarchy_chapter",
        )
    )
    components.extend(
        _hierarchy_heading_components(
            normalized,
            pattern=_SUBCHAPTER_HEADING_RE,
            prefix="usc_hierarchy_subchapter",
        )
    )
    components.extend(
        _hierarchy_heading_components(
            normalized,
            pattern=_PART_HEADING_RE,
            prefix="usc_hierarchy_part",
        )
    )
    components.extend(
        _hierarchy_heading_components(
            normalized,
            pattern=_SUBPART_HEADING_RE,
            prefix="usc_hierarchy_subpart",
        )
    )
    if components:
        levels = {
            predicate.rsplit("_", 1)[0]
            for predicate, _value in components
            if predicate.endswith("_label")
        }
        components.append(("usc_hierarchy_level_count", str(len(levels))))
        components.append(("usc_hierarchy_projection", "true"))
    return _clean_components(components)


def _hierarchy_heading_components(
    text: str,
    *,
    pattern: re.Pattern[str],
    prefix: str,
) -> List[Tuple[str, str]]:
    components: List[Tuple[str, str]] = []
    for match in pattern.finditer(text):
        label = _clean_hierarchy_label(match.group("label"))
        heading = _clean_hierarchy_heading_text(match.group("heading"))
        if not label or not heading:
            continue
        components.append((f"{prefix}_label", label))
        components.append((f"{prefix}_heading", heading))
        components.append((f"{prefix}_key", f"{label}:{_identifier_token(heading)}"))
    return components[:12]


def _clean_hierarchy_label(text: str) -> str:
    return re.sub(r"\s+", " ", _normalize_dashes(text)).strip(" -.;:").upper()


def _clean_hierarchy_heading_text(text: str) -> str:
    heading = re.sub(r"\s+", " ", _normalize_dashes(text)).strip(" -.;:")
    heading = re.sub(
        r"\s+(?:From the U\.S\. Government Publishing Office|Editorial Notes|"
        r"Statutory Notes|Secs?\.?\s+\d).*$",
        "",
        heading,
        flags=re.IGNORECASE,
    ).strip(" -.;:")
    return heading


def _editorial_status_components(text: str) -> List[Tuple[str, str]]:
    normalized = _normalize_dashes(text)
    components: List[Tuple[str, str]] = []
    primary_keywords = _primary_editorial_status_keywords(normalized)
    for keyword in primary_keywords:
        components.append(("status_keyword", keyword))
        components.append((f"status_keyword_{keyword}", "true"))
        components.append(("status_scope", "section_heading"))
    for keyword in _editorial_reference_status_keywords(normalized, primary_keywords):
        components.append(("editorial_reference_status_keyword", keyword))
        components.append((f"editorial_reference_status_keyword_{keyword}", "true"))
    return components


def _primary_editorial_status_keywords(text: str) -> List[str]:
    heading = ""
    heading_match = _SECTION_HEADING_MARKER_RE.search(text)
    if heading_match:
        heading = _clean_heading_text(heading_match.group("heading"))
    else:
        marker_match = _SECTION_MARKER_RE.search(text)
        if marker_match:
            heading = _clean_heading_text(
                text[marker_match.end() : marker_match.end() + 160]
            )
    if not heading:
        return []
    return [
        keyword
        for keyword, pattern in _EDITORIAL_STATUS_KEYWORDS
        if pattern.search(heading)
    ]


def _editorial_reference_status_keywords(
    text: str,
    primary_keywords: Sequence[str],
) -> List[str]:
    note_match = _EDITORIAL_NOTES_START_RE.search(text)
    notes_text = text[note_match.start() :] if note_match else ""
    if not notes_text:
        return []
    primary = set(primary_keywords)
    return [
        keyword
        for keyword, pattern in _EDITORIAL_STATUS_KEYWORDS
        if keyword not in primary and pattern.search(notes_text)
    ]


def _clean_heading_text(text: str) -> str:
    heading = re.sub(r"\s+", " ", _normalize_dashes(text)).strip(" -.;")
    heading = _SECTION_HEADING_SOURCE_TAIL_RE.sub("", heading).strip(" -.;")
    # Some sparse samples continue directly into text after a short catchline.
    # Keep the canonical heading span conservative and deterministic.
    heading = _CATCHLINE_BODY_START_RE.sub("", heading).strip(" -.;")
    return heading


def _section_heading_parts(heading: str) -> List[str]:
    return [
        part.strip(" -.;")
        for part in heading.split(";")
        if part.strip(" -.;")
    ]


def _section_body_structure_components(text: str) -> List[Tuple[str, str]]:
    components: List[Tuple[str, str]] = []
    subsection_headings = _subsection_heading_components(text)
    paragraph_components = _paragraph_marker_components(text)
    definition_components = _definition_term_components(text)

    components.extend(subsection_headings)
    components.extend(paragraph_components)
    components.extend(definition_components)
    if subsection_headings:
        components.append(("section_style_has_subsections", "true"))
        components.append(
            (
                "section_subsection_count",
                str(
                    len(
                        {
                            value
                            for predicate, value in subsection_headings
                            if predicate == "section_subsection_label"
                        }
                    )
                ),
            )
        )
    if paragraph_components:
        components.append(("section_style_has_paragraphs", "true"))
        components.append(
            (
                "section_paragraph_count",
                str(
                    len(
                        {
                            value
                            for predicate, value in paragraph_components
                            if predicate == "section_paragraph_label"
                        }
                    )
                ),
            )
        )
    if definition_components:
        components.append(("section_style_definition_list", "true"))
        components.append(
            (
                "section_definition_term_count",
                str(
                    len(
                        {
                            value
                            for predicate, value in definition_components
                            if predicate == "section_definition_term"
                        }
                    )
                ),
            )
        )
    return components


def _subsection_heading_components(text: str) -> List[Tuple[str, str]]:
    components: List[Tuple[str, str]] = []
    for match in _SUBSECTION_HEADING_RE.finditer(text):
        label = match.group("label").lower()
        heading = _clean_body_heading_text(match.group("heading"))
        if not label or not heading:
            continue
        components.append(("section_subsection_label", label))
        components.append((f"section_subsection_{label}_heading", heading))
    return components[:24]


def _paragraph_marker_components(text: str) -> List[Tuple[str, str]]:
    components: List[Tuple[str, str]] = []
    for match in _PARAGRAPH_MARKER_RE.finditer(text):
        label = match.group("label")
        if not label:
            continue
        components.append(("section_paragraph_label", label))
        components.append((f"section_paragraph_{label}_marker", f"({label})"))
    return components[:32]


def _definition_term_components(text: str) -> List[Tuple[str, str]]:
    components: List[Tuple[str, str]] = []
    for index, match in enumerate(_DEFINITION_TERM_RE.finditer(text), start=1):
        term = _clean_definition_term(match.group("term"))
        if not term:
            continue
        components.append(("section_definition_term", term))
        components.append((f"section_definition_term_{index}", term))
        components.append(
            (
                f"section_definition_term_{index}_normalized",
                _identifier_token(term),
            )
        )
    return components[:36]


def _clean_body_heading_text(text: str) -> str:
    heading = re.sub(r"\s+", " ", _normalize_dashes(text)).strip(" -.;:")
    heading = re.sub(
        r"\s+(?:A|An|Each|For|In|No|Nothing|Not|The|There|Whoever)\b.*$",
        "",
        heading,
    ).strip(" -.;:")
    return heading


def _clean_definition_term(text: str) -> str:
    return re.sub(r"\s+", " ", _normalize_dashes(text)).strip(" -.;:")


def _identifier_token(text: str) -> str:
    token = re.sub(r"[^A-Za-z0-9]+", "_", text.lower()).strip("_")
    return token or "term"


def _canonical_usc_citation(title: str, section: str) -> str:
    if not title or not section:
        return ""
    return f"{title} U.S.C. {section}"


def _leading_number(value: str) -> str:
    match = _SECTION_PART_RE.match(value.strip())
    return match.group("number") if match else ""


def _section_profile(section: str) -> str:
    if _SECTION_RANGE_RE.fullmatch(section.strip()):
        return "range"
    if _SECTION_LIST_RE.fullmatch(section.strip()):
        return "list"
    parts = _SECTION_PART_RE.fullmatch(section.strip())
    if not parts:
        return "mixed"
    return "numeric_alpha" if parts.group("suffix") else "numeric"


def _section_range_components(prefix: str, section: str) -> List[Tuple[str, str]]:
    match = _SECTION_RANGE_RE.fullmatch(section.strip())
    if not match:
        return []
    start = match.group("start")
    connector = match.group("connector").lower()
    end = match.group("end")
    components: List[Tuple[str, str]] = [
        (f"{prefix}_range", f"{start} {connector} {end}"),
        (f"{prefix}_range_start", start),
        (f"{prefix}_range_end", end),
        (f"{prefix}_range_connector", connector),
    ]
    start_number = _leading_number(start)
    end_number = _leading_number(end)
    if start_number and end_number:
        components.append((f"{prefix}_range_number_pair", f"{start_number}|{end_number}"))
        try:
            span = int(end_number) - int(start_number)
        except ValueError:
            span = 0
        relation = "ascending" if span > 0 else "same" if span == 0 else "descending"
        components.append((f"{prefix}_range_number_relation", relation))
        components.append((f"{prefix}_range_number_span", str(abs(span))))
    return components


def _section_list_components(prefix: str, section: str) -> List[Tuple[str, str]]:
    match = _SECTION_LIST_RE.fullmatch(section.strip())
    if not match:
        return []
    items = [
        _normalize_section(item)
        for item in re.split(r"\s*,\s*", match.group("items"))
        if _normalize_section(item)
    ]
    if len(items) < 2:
        return []
    components: List[Tuple[str, str]] = [
        (f"{prefix}_list", ", ".join(items)),
        (f"{prefix}_list_count", str(len(items))),
        (f"{prefix}_list_first", items[0]),
        (f"{prefix}_list_last", items[-1]),
    ]
    components.extend(
        (f"{prefix}_list_item_{index}", item)
        for index, item in enumerate(items, start=1)
    )
    return components


def _lead_section(section: str) -> str:
    normalized = _normalize_section(section)
    list_match = _SECTION_LIST_RE.fullmatch(normalized)
    if list_match:
        return _normalize_section(re.split(r"\s*,\s*", list_match.group("items"))[0])
    range_match = _SECTION_RANGE_RE.fullmatch(normalized)
    if range_match:
        return _normalize_section(range_match.group("start"))
    return normalized


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


def _append_source_citation_alignment_triples(
    triples: List[Dict[str, str]],
    *,
    predicates_by_subject: Dict[str, set[str]],
    seen: set[Tuple[str, str, str]],
) -> None:
    component_maps: Dict[str, Dict[str, str]] = {}
    for triple in triples:
        component_maps.setdefault(triple["subject"], {})[
            triple["predicate"]
        ] = triple["object"]

    for subject, components in sorted(component_maps.items()):
        alignment_components = _source_citation_alignment_components(components)
        if not alignment_components:
            continue
        existing_predicates = predicates_by_subject.setdefault(subject, set())
        for predicate, value in alignment_components:
            if predicate in existing_predicates:
                continue
            key = (subject, predicate, value)
            if key in seen:
                continue
            seen.add(key)
            existing_predicates.add(predicate)
            triples.append(
                {
                    "subject": subject,
                    "predicate": predicate,
                    "object": value,
                }
            )


def _source_citation_alignment_components(
    components: Mapping[str, str],
) -> List[Tuple[str, str]]:
    source_title = components.get("source_id_title", "")
    citation_title = components.get("citation_title", "")
    source_section = components.get("source_id_section_normalized", "")
    citation_section = components.get("citation_section_normalized", "")
    source_canonical = components.get("source_id_citation_canonical", "")
    citation_canonical = components.get("citation_canonical", "")
    source_key = components.get("source_id_title_section_key", "")
    citation_key = components.get("citation_title_section_key", "")
    if not (
        (source_title or source_section or source_canonical or source_key)
        and (citation_title or citation_section or citation_canonical or citation_key)
    ):
        return []

    title_match = bool(source_title and citation_title and source_title == citation_title)
    section_match = bool(
        source_section and citation_section and source_section == citation_section
    )
    canonical_match = bool(
        source_canonical and citation_canonical and source_canonical == citation_canonical
    )
    key_match = bool(source_key and citation_key and source_key == citation_key)
    alignment = (
        "canonical_match"
        if canonical_match
        else "title_section_match"
        if title_match and section_match
        else "title_match"
        if title_match
        else "section_match"
        if section_match
        else "mismatch"
    )
    components_out: List[Tuple[str, str]] = [
        ("citation_source_id_alignment", alignment),
        ("citation_source_id_title_match", "true" if title_match else "false"),
        ("citation_source_id_section_match", "true" if section_match else "false"),
        (
            "citation_source_id_title_section_key_match",
            "true" if key_match else "false",
        ),
        ("citation_source_id_canonical_match", "true" if canonical_match else "false"),
    ]
    if source_key and citation_key:
        components_out.append(
            ("citation_source_id_title_section_key_pair", f"{citation_key}|{source_key}")
        )
    if source_canonical and citation_canonical:
        components_out.append(
            (
                "citation_source_id_canonical_pair",
                f"{citation_canonical}|{source_canonical}",
            )
        )
    return _clean_components(components_out)


def _append_legal_ir_guidance_alignment_triples(
    triples: List[Dict[str, str]],
    *,
    predicates_by_subject: Dict[str, set[str]],
    seen: set[Tuple[str, str, str]],
) -> None:
    guidance_by_subject: Dict[str, Dict[str, set[str]]] = {}
    for triple in triples:
        subject = triple["subject"]
        predicate = triple["predicate"]
        obj = triple["object"]
        guidance = guidance_by_subject.setdefault(
            subject,
            {
                "predicted": set(),
                "target": set(),
                "actions": set(),
                "features": set(),
                "gaps": {},
            },
        )
        normalized_predicate = predicate.strip().lower()
        normalized_view = _canonical_legal_ir_view_name(obj)
        if normalized_predicate in _LEGAL_IR_VIEW_GUIDANCE_PREDICATES:
            if "predicted" in normalized_predicate:
                if normalized_view:
                    guidance["predicted"].add(normalized_view)
            elif normalized_view:
                guidance["target"].add(normalized_view)
        elif normalized_predicate in {
            "action",
            "compiler_guidance_action",
            "compiler_guidance_route",
            "route",
        }:
            guidance["actions"].add(obj.strip())
        if normalized_predicate in _RAW_LEGAL_IR_GUIDANCE_PAYLOAD_PREDICATES:
            _collect_legal_ir_guidance_features(
                obj,
                guidance=guidance,
                predicate_hint=normalized_predicate,
            )

    for subject, guidance in sorted(guidance_by_subject.items()):
        target_views = set(guidance["target"])
        predicted_views = set(guidance["predicted"])
        feature_text = "\n".join(sorted(guidance["features"] | guidance["actions"]))
        has_graph_route = any(
            action in feature_text for action in _LEGAL_IR_GRAPH_REPAIR_ACTIONS
        )
        has_neo4j_target = _NEO4J_COMPAT_TARGET_COMPONENT in feature_text
        has_graph_failure_metric = (
            "legal_ir_multiview_graph_failure_penalty" in feature_text
        )
        has_knowledge_graph_scope = "knowledge_graphs" in feature_text
        if (
            guidance["actions"] & _LEGAL_IR_GRAPH_REPAIR_ACTIONS
            or has_graph_route
            or has_neo4j_target
            or (has_graph_failure_metric and has_knowledge_graph_scope)
        ):
            target_views.add(_NEO4J_COMPAT_TARGET_COMPONENT)
        if not target_views and not predicted_views:
            continue
        facts: List[Tuple[str, str]] = []
        ranked_views = sorted(target_views | predicted_views)
        gap_values = guidance.get("gaps", {})
        if not isinstance(gap_values, Mapping):
            gap_values = {}
        for rank, view in enumerate(ranked_views, start=1):
            if view in predicted_views:
                facts.append(("learned_legal_ir_predicted_view", view))
                facts.append(
                    ("learned_legal_ir_predicted_view_weight", f"{view}:1.000000")
                )
            if view in target_views:
                facts.append(("learned_legal_ir_target_view", view))
                facts.append(("learned_legal_ir_target_view_weight", f"{view}:1.000000"))
            gap = 0.0
            if view in gap_values:
                gap = _safe_float(gap_values.get(view), 0.0)
            elif view in target_views and view not in predicted_views:
                gap = 1.0
            elif view in predicted_views and view not in target_views:
                gap = -1.0
            facts.append(("learned_legal_ir_view_rank", f"{rank}:{view}"))
            facts.append(("learned_legal_ir_view_gap", f"{view}:{gap:.6f}"))
        _append_component_triples(
            triples,
            subject=subject,
            components=facts,
            predicates_by_subject=predicates_by_subject,
            seen=seen,
        )


def _collect_legal_ir_guidance_features(
    value: Any,
    *,
    guidance: Dict[str, Any],
    predicate_hint: str = "",
) -> None:
    """Extract graph-view guidance from raw packet-shaped triple values."""

    if isinstance(value, Mapping):
        for raw_key, raw_value in value.items():
            key = str(raw_key or "").strip().lower()
            guidance["features"].add(key)
            if key in _LEGAL_IR_VIEW_GUIDANCE_PREDICATES:
                view = _canonical_legal_ir_view_name(str(raw_value or ""))
                if view:
                    bucket = "predicted" if "predicted" in key else "target"
                    guidance[bucket].add(view)
            elif key in {
                "action",
                "compiler_guidance_action",
                "compiler_guidance_route",
                "route",
                "semantic_bundle_key",
            }:
                text = str(raw_value or "").strip()
                if text:
                    guidance["actions"].add(text)
            elif key in {
                "compiler_guidance_legal_ir_view_gaps",
                "legal_ir_view_gaps",
            } and isinstance(raw_value, Mapping):
                _collect_legal_ir_view_gap_features(raw_value, guidance=guidance)
            elif key == "legal_ir_component_gaps" and isinstance(raw_value, Mapping):
                _collect_legal_ir_component_gap_features(raw_value, guidance=guidance)
            elif key == "legal_ir_underrepresented_components":
                _collect_underrepresented_component_features(
                    raw_value,
                    guidance=guidance,
                )
            _collect_legal_ir_guidance_features(
                raw_value,
                guidance=guidance,
                predicate_hint=key,
            )
        return

    if isinstance(value, (list, tuple, set)):
        for item in value:
            _collect_legal_ir_guidance_features(
                item,
                guidance=guidance,
                predicate_hint=predicate_hint,
            )
        return

    text = str(value or "").strip()
    if not text:
        return
    guidance["features"].add(text)
    if _graph_repair_text_match(text):
        guidance["actions"].add("repair_multiview_legal_ir_graph_projection")
    if _NEO4J_COMPAT_TARGET_COMPONENT in text:
        if "predicted" in predicate_hint:
            guidance["predicted"].add(_NEO4J_COMPAT_TARGET_COMPONENT)
        else:
            guidance["target"].add(_NEO4J_COMPAT_TARGET_COMPONENT)
    if "knowledge_graphs_neo4j_compat:underrepresented" in text.lower():
        guidance["target"].add(_NEO4J_COMPAT_TARGET_COMPONENT)

    parsed = _json_guidance_value(text)
    if parsed is not None:
        _collect_legal_ir_guidance_features(
            parsed,
            guidance=guidance,
            predicate_hint=predicate_hint,
        )


def _collect_legal_ir_view_gap_features(
    gaps: Mapping[Any, Any],
    *,
    guidance: Dict[str, Any],
) -> None:
    for raw_key, raw_value in gaps.items():
        key = str(raw_key or "").strip()
        value = str(raw_value or "").strip()
        guidance["features"].add(key)
        if value:
            guidance["features"].add(value)
        view_key, _, bucket = key.partition(":")
        view = _canonical_legal_ir_view_name(view_key)
        if view == _NEO4J_COMPAT_TARGET_COMPONENT and bucket.lower() in {
            "missing",
            "underrepresented",
        }:
            guidance["target"].add(_NEO4J_COMPAT_TARGET_COMPONENT)
            gaps = guidance.setdefault("gaps", {})
            if isinstance(gaps, dict):
                gaps[_NEO4J_COMPAT_TARGET_COMPONENT] = max(
                    _safe_float(gaps.get(_NEO4J_COMPAT_TARGET_COMPONENT), 0.0),
                    _safe_float(value, 1.0),
                )


def _collect_legal_ir_component_gap_features(
    gaps: Mapping[Any, Any],
    *,
    guidance: Dict[str, Any],
) -> None:
    gap_bucket = guidance.setdefault("gaps", {})
    for raw_key, raw_value in gaps.items():
        view = _canonical_legal_ir_view_name(str(raw_key or ""))
        if not view:
            continue
        number = _safe_float(raw_value, 0.0)
        guidance["features"].add(view)
        if isinstance(gap_bucket, dict):
            existing = _safe_float(gap_bucket.get(view), 0.0)
            gap_bucket[view] = (
                number if existing == 1.0 and number else existing + number
            )
        if view == _NEO4J_COMPAT_TARGET_COMPONENT and number > 0.0:
            guidance["target"].add(_NEO4J_COMPAT_TARGET_COMPONENT)


def _collect_underrepresented_component_features(
    value: Any,
    *,
    guidance: Dict[str, Any],
) -> None:
    gap_bucket = guidance.setdefault("gaps", {})
    for item in _iter_feature_values(value):
        view = _canonical_legal_ir_view_name(item)
        if not view:
            continue
        guidance["features"].add(view)
        if view == _NEO4J_COMPAT_TARGET_COMPONENT:
            guidance["target"].add(_NEO4J_COMPAT_TARGET_COMPONENT)
            if isinstance(gap_bucket, dict):
                existing = _safe_float(gap_bucket.get(view), 0.0)
                gap_bucket[view] = existing if existing != 0.0 else 1.0


def _json_guidance_value(text: str) -> Any:
    if not text or text[0] not in "{[":
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _iter_feature_values(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, Mapping):
        direct = str(value.get("feature") or value.get("name") or "").strip()
        if direct:
            return [direct]
        values = value.values()
    elif isinstance(value, (str, bytes)):
        text = value.decode("utf-8", errors="ignore") if isinstance(value, bytes) else value
        return [text.strip()] if text.strip() else []
    else:
        try:
            values = list(value)
        except TypeError:
            values = [value]
    features: List[str] = []
    for item in values:
        text = str(item or "").strip()
        if text:
            features.append(text)
    return features


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(number):
        return default
    return number


def _graph_repair_text_match(text: str) -> bool:
    return "repair_multiview_legal_ir_graph_projection" in text


def _append_structural_graph_view_alignment_triples(
    triples: List[Dict[str, str]],
    *,
    predicates_by_subject: Dict[str, set[str]],
    seen: set[Tuple[str, str, str]],
) -> None:
    component_maps: Dict[str, Dict[str, str]] = {}
    for triple in triples:
        component_maps.setdefault(triple["subject"], {})[
            triple["predicate"]
        ] = triple["object"]

    for subject, components in sorted(component_maps.items()):
        if not _components_imply_neo4j_projection_view(components):
            continue
        _append_component_triples(
            triples,
            subject=subject,
            components=[
                (
                    "learned_legal_ir_target_view",
                    "knowledge_graphs.neo4j_compat",
                ),
                (
                    "learned_legal_ir_target_view_weight",
                    "knowledge_graphs.neo4j_compat:1.000000",
                ),
                (
                    "learned_legal_ir_view_rank",
                    "1:knowledge_graphs.neo4j_compat",
                ),
                (
                    "learned_legal_ir_view_gap",
                    "knowledge_graphs.neo4j_compat:1.000000",
                ),
            ],
            predicates_by_subject=predicates_by_subject,
            seen=seen,
        )


def _components_imply_neo4j_projection_view(components: Mapping[str, str]) -> bool:
    if components.get("learned_legal_ir_target_view") or components.get(
        "learned_legal_ir_predicted_view"
    ):
        return False
    has_canonical_citation = bool(
        components.get("citation_canonical")
        or components.get("source_id_citation_canonical")
    )
    has_section_structure = bool(
        components.get("section_marker_normalized")
        or components.get("source_id_section_normalized")
        or components.get("citation_section_normalized")
    )
    has_graph_structure = bool(
        components.get("usc_hierarchy_projection") == "true"
        or components.get("status_keyword")
    )
    return has_canonical_citation and has_section_structure and has_graph_structure


def _append_component_triples(
    triples: List[Dict[str, str]],
    *,
    subject: str,
    components: Sequence[Tuple[str, str]],
    predicates_by_subject: Dict[str, set[str]],
    seen: set[Tuple[str, str, str]],
) -> None:
    existing_predicates = predicates_by_subject.setdefault(subject, set())
    for predicate, value in _clean_components(components):
        if (
            predicate in existing_predicates
            and predicate not in _MULTI_VALUE_COMPONENT_PREDICATES
        ):
            continue
        key = (subject, predicate, value)
        if key in seen:
            continue
        seen.add(key)
        existing_predicates.add(predicate)
        triples.append({"subject": subject, "predicate": predicate, "object": value})


def _canonical_legal_ir_view_name(value: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return ""
    return _LEGAL_IR_VIEW_ALIASES.get(normalized.lower(), normalized)


__all__ = ["augment_legal_ir_projection_triples"]
