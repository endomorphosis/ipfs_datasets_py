"""Deontic logic parsing and formula generation utilities.

This module is intentionally conservative.  It is a deterministic scaffold for
indexing, triage, and LLM prompting, not a substitute for an LLM/legal review
formalization pass.
"""

import re
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional


PARSER_SCHEMA_VERSION = "deterministic_deontic_v12"
PARSER_REQUIRED_FIELDS = [
    "schema_version",
    "source_id",
    "canonical_citation",
    "text",
    "support_text",
    "support_span",
    "field_spans",
    "norm_type",
    "deontic_operator",
    "modal",
    "subject",
    "actor_type",
    "entity_type",
    "action",
    "action_verb",
    "action_object",
    "action_recipient",
    "conditions",
    "condition_details",
    "temporal_constraints",
    "temporal_constraint_details",
    "exceptions",
    "exception_details",
    "override_clauses",
    "override_clause_details",
    "cross_references",
    "cross_reference_details",
    "resolved_cross_references",
    "enforcement_links",
    "conflict_links",
    "enumerated_items",
    "defined_term_refs",
    "definition_scope",
    "ontology_terms",
    "formal_terms",
    "llm_repair",
    "export_readiness",
    "logic_frame",
    "legal_frame",
    "kg_relationship_hints",
    "monetary_amounts",
    "monetary_amount_details",
    "penalty",
    "procedure",
    "section_context",
    "hierarchy_path",
    "hierarchy_details",
    "document_type",
    "extraction_method",
    "confidence_floor",
    "slot_coverage",
    "scaffold_quality",
    "quality_label",
    "parser_warnings",
    "promotable_to_theorem",
]
LEGACY_SCHEMA_DEFAULTS: Dict[str, Any] = {
    "source_id": "",
    "canonical_citation": "",
    "field_spans": {},
    "condition_details": [],
    "temporal_constraint_details": [],
    "exception_details": [],
    "override_clause_details": [],
    "cross_reference_details": [],
    "resolved_cross_references": [],
    "enforcement_links": [],
    "conflict_links": [],
    "defined_term_refs": [],
    "definition_scope": {},
    "ontology_terms": [],
    "formal_terms": {},
    "llm_repair": {},
    "export_readiness": {},
    "logic_frame": {},
    "legal_frame": {},
    "kg_relationship_hints": [],
    "monetary_amounts": [],
    "monetary_amount_details": [],
    "penalty": {},
    "procedure": {},
    "section_context": {},
    "hierarchy_path": [],
    "hierarchy_details": [],
}
EXPORT_TABLE_SPECS: Dict[str, Dict[str, Any]] = {
    "canonical": {"primary_key": "source_id", "requires_source_id": True},
    "formal_logic": {"primary_key": "formula_id", "requires_source_id": True},
    "proof_obligations": {"primary_key": "proof_obligation_id", "requires_source_id": True},
    "knowledge_graph_triples": {"primary_key": "triple_id", "requires_source_id": True},
    "clause_records": {"primary_key": "clause_id", "requires_source_id": True},
    "reference_records": {"primary_key": "reference_id", "requires_source_id": True},
    "procedure_event_records": {"primary_key": "event_id", "requires_source_id": True},
    "sanction_records": {"primary_key": "sanction_id", "requires_source_id": True},
    "ontology_entities": {"primary_key": "entity_id", "requires_source_id": True},
    "repair_queue": {"primary_key": "repair_id", "requires_source_id": True},
}
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9(])")
_SECTION_HEADER_RE = re.compile(
    r"^\s*(?:(?:sec(?:tion)?\.?|§)\s*)?([0-9]+(?:\.[0-9]+)*(?:[A-Za-z])?)\.?\s*(.*)$",
    re.IGNORECASE,
)
_HIERARCHY_HEADER_RE = re.compile(
    r"^\s*(title|chapter|article|part|division)\s+([0-9A-Za-z][0-9A-Za-z.\-]*)\.?\s*(.*)$",
    re.IGNORECASE,
)
_ENUM_LABEL_RE = re.compile(r"\(([A-Za-z0-9]+)\)")
_MODAL_RE = re.compile(
    r"""
    (?P<subject>
        (?:the\s+)?
        [A-Za-z][A-Za-z0-9'’\-]*
        (?:\s+(?!shall\b|must\b|may\b|cannot\b|can\b|is\b|are\b|will\b|should\b)
            [A-Za-z][A-Za-z0-9'’\-]*){0,10}
    )
    \s+
    (?P<modal>
        shall\s+not|must\s+not|may\s+not|cannot|can\s+not|
        is\s+prohibited\s+from|are\s+prohibited\s+from|
        is\s+forbidden\s+to|are\s+forbidden\s+to|
        shall|must|required\s+to|is\s+required\s+to|are\s+required\s+to|
        has\s+a\s+duty\s+to|have\s+a\s+duty\s+to|
        may|is\s+authorized\s+to|are\s+authorized\s+to|
        is\s+permitted\s+to|are\s+permitted\s+to|
        is\s+entitled\s+to|are\s+entitled\s+to
    )
    \s+
    (?P<action>.+?)
    (?=(?:\s+(?:and|or)\s+(?:shall|must|may|cannot|can\s+not|is\s+required|are\s+required|is\s+authorized|are\s+authorized|is\s+permitted|are\s+permitted)\b)|(?:\s+(?:if|when|where|provided\s+that|unless|except|except\s+that|without|absent|before|after|within|not\s+later\s+than)\b)|[.;:]|$)
    """,
    re.IGNORECASE | re.VERBOSE,
)
_IMPLICIT_MODAL_RE = re.compile(
    r"""
    \b(?:and|or)\s+
    (?P<modal>
        shall\s+not|must\s+not|may\s+not|cannot|can\s+not|
        shall|must|required\s+to|may|
        is\s+authorized\s+to|are\s+authorized\s+to|
        is\s+permitted\s+to|are\s+permitted\s+to
    )
    \s+
    (?P<action>.+?)
    (?=(?:\s+(?:and|or)\s+(?:shall|must|may|cannot|can\s+not)\b)|(?:\s+(?:if|when|where|provided\s+that|unless|except|except\s+that|without|absent|before|after|within|not\s+later\s+than)\b)|[.;:]|$)
    """,
    re.IGNORECASE | re.VERBOSE,
)
_IMPERSONAL_NORM_RE = re.compile(
    r"""
    (?:
        (?P<unlawful>it\s+is\s+(?:unlawful|illegal|prohibited)\s+(?:for\s+(?P<unlawful_subject>.+?)\s+)?to\s+(?P<unlawful_action>.+?))
        |
        (?P<license>(?:a|an|the)\s+(?P<license_subject>license|permit|certificate|registration|approval)\s+is\s+required\s+to\s+(?P<license_action>.+?))
        |
        (?P<duty>(?:a|an|the)\s+duty\s+is\s+imposed\s+on\s+(?P<duty_subject>.+?)\s+to\s+(?P<duty_action>.+?))
    )
    (?=(?:\s+(?:if|when|where|provided\s+that|unless|except|without|absent|before|after|within|not\s+later\s+than)\b)|[.;:]|$)
    """,
    re.IGNORECASE | re.VERBOSE,
)
_VIOLATION_RE = re.compile(
    r"\bfailure\s+to\s+(.+?)\s+is\s+(?:a\s+)?(?:violation|offense|infraction)\b",
    re.IGNORECASE,
)
_PENALTY_RE = re.compile(
    r"\b(?:a\s+)?(?:violation|offense|infraction)(?:\s+of\s+(?:this\s+section|section\s+[0-9][0-9A-Za-z.\-]*(?:\([a-z0-9]+\))*))?\s+(?:is|shall\s+be)\s+"
    r"(?:punishable\s+by|subject\s+to)\s+(.+?)(?:[.;:]|$)",
    re.IGNORECASE,
)
_APPLICABILITY_RE = re.compile(
    r"\b(?P<scope>this|the)\s+(?P<scope_type>section|chapter|title|article|part)\s+"
    r"(?:applies|shall\s+apply|is\s+applicable)\s+to\s+(?P<target>.+?)(?:[.;:]|$)",
    re.IGNORECASE,
)
_NON_APPLICABILITY_RE = re.compile(
    r"\b(?P<scope>this|the)\s+(?P<scope_type>section|chapter|title|article|part)\s+"
    r"(?:does\s+not\s+apply|shall\s+not\s+apply|is\s+not\s+applicable)\s+to\s+(?P<target>.+?)(?:[.;:]|$)",
    re.IGNORECASE,
)
_EXEMPTION_RE = re.compile(
    r"\b(?P<target>.+?)\s+(?:is|are)\s+exempt\s+from\s+(?P<requirement>.+?)(?:[.;:]|$)",
    re.IGNORECASE,
)
_NOT_REQUIRED_EXEMPTION_RE = re.compile(
    r"\b(?:no\s+|(?:a|an|the|any)\s+)?"
    r"(?P<instrument>permit|license|certificate|registration|approval)\s+"
    r"(?:(?:is|are|shall\s+be)\s+not\s+required|(?:is|are)\s+unnecessary)\s+"
    r"(?P<preposition>for|to)\s+(?P<target>.+?)(?:[.;:]|$)",
    re.IGNORECASE,
)
_INSTRUMENT_VALIDITY_RE = re.compile(
    r"\b(?P<instrument>(?:the|a|an)\s+)?(?P<instrument_type>permit|license|certificate|registration|approval|variance)\s+"
    r"(?:is|shall\s+be)\s+valid\s+for\s+(?P<duration>.+?)(?:[.;:]|$)",
    re.IGNORECASE,
)
_INSTRUMENT_EXPIRATION_RE = re.compile(
    r"\b(?P<instrument>(?:the|a|an)\s+)?(?P<instrument_type>permit|license|certificate|registration|approval|variance)\s+"
    r"(?:expires|shall\s+expire|terminates|shall\s+terminate)\s+(?P<anchor>.+?)(?:[.;:]|$)",
    re.IGNORECASE,
)
_MONEY_RE = re.compile(
    r"(?:\$\s?\d[\d,]*(?:\.\d{2})?|\b\d[\d,]*\s+dollars?\b)",
    re.IGNORECASE,
)
_CLAUSE_END_RE = r"(?:,|[.]\s|[.]$|$)"
_CONDITION_PATTERNS = [
    ("if", rf"\bif\s+(.+?)(?:,|\s+then|[.]$|$)"),
    ("when", rf"\bwhen\s+(.+?){_CLAUSE_END_RE}"),
    ("where", rf"\bwhere\s+(.+?){_CLAUSE_END_RE}"),
    ("provided_that", rf"\bprovided that\s+(.+?){_CLAUSE_END_RE}"),
    ("subject_to", rf"\bsubject to\s+(.+?){_CLAUSE_END_RE}"),
    ("in_case", rf"\bin case\s+(.+?){_CLAUSE_END_RE}"),
]
_EXCEPTION_PATTERNS = [
    ("unless", rf"\bunless\s+(.+?){_CLAUSE_END_RE}"),
    ("except", rf"\bexcept\s+(?:for\s+)?(.+?){_CLAUSE_END_RE}"),
    ("without", rf"\bwithout\s+(.+?){_CLAUSE_END_RE}"),
    ("absent", rf"\babsent\s+(.+?){_CLAUSE_END_RE}"),
    ("with_exception_of", rf"\bwith the exception of\s+(.+?){_CLAUSE_END_RE}"),
    ("other_than", rf"\bother than\s+(.+?){_CLAUSE_END_RE}"),
    ("excluding", rf"\bexcluding\s+(.+?){_CLAUSE_END_RE}"),
]
_OVERRIDE_PATTERNS = [
    ("notwithstanding", rf"\bnotwithstanding\s+(.+?)(?:,|[.]$|$)"),
    ("without_regard_to", rf"\bwithout regard to\s+(.+?)(?:,|[.]$|$)"),
]
_TEMPORAL_PATTERNS = [
    ("deadline", "by_date", r"\bby\s+((?:january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{1,2}(?:st|nd|rd|th)?(?:,?\s+\d{4})?)"),
    ("deadline", "by_numeric_date", r"\bby\s+(\d{1,2}/\d{1,2}/\d{2,4})"),
    ("deadline", "by_numeric_date", r"\bby\s+(\d{1,2}-\d{1,2}-\d{2,4})"),
    ("deadline", "within_duration", r"\bwithin\s+(\d+\s+(?:(?:business|calendar)\s+)?(?:days?|weeks?|months?|years?)(?:\s+after\s+.+?)?)(?=\s+(?:unless|except|without|absent|if|when|where|provided that|subject to)\b|[,.;]|$)"),
    ("deadline", "not_later_than", r"\bnot\s+later\s+than\s+(\d+\s+(?:(?:business|calendar)\s+)?(?:days?|weeks?|months?|years?)(?:\s+after\s+.+?)?)(?=\s+(?:unless|except|without|absent|if|when|where|provided that|subject to)\b|[,.;]|$)"),
    ("deadline", "before_date", r"\bbefore\s+((?:january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{1,2})"),
    ("deadline", "after_date", r"\bafter\s+((?:january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{1,2})"),
    ("period", "annually", r"\b(annually)\b"),
    ("period", "monthly", r"\b(monthly)\b"),
    ("period", "weekly", r"\b(weekly)\b"),
    ("period", "daily", r"\b(daily)\b"),
    ("duration", "for_duration", r"\bfor\s+(\d+\s+(?:(?:business|calendar)\s+)?(?:days?|weeks?|months?|years?))"),
]
_DEFINITION_RE = re.compile(
    r"\b(?:means|includes?|defined\s+as|has\s+the\s+meaning\s+given|refers\s+to)\b",
    re.IGNORECASE,
)
_DEFINED_TERM_RE = re.compile(
    r"\b(?:the\s+)?(?:term|terms|word|words)\s+['\"“”]?([A-Za-z][A-Za-z0-9'’\-\s]{0,80}?)[\"'“”]?\s+"
    r"(?:means|includes?|defined\s+as|has\s+the\s+meaning\s+given|refers\s+to)\b",
    re.IGNORECASE,
)
_UNQUOTED_DEFINED_TERM_RE = re.compile(
    r"^\s*(?:(?:(?:in|as\s+used\s+in)\s+this\s+(?:section|chapter|title)|for\s+purposes\s+of\s+this\s+(?:section|chapter|title)),?\s+)?"
    r"(?:the\s+)?([A-Za-z][A-Za-z0-9'’\-]*(?:\s+[A-Za-z][A-Za-z0-9'’\-]*){0,8}?)\s+"
    r"(?:means|includes?|defined\s+as|has\s+the\s+meaning\s+given|refers\s+to)\b",
    re.IGNORECASE,
)
_LEADING_DETERMINERS_RE = re.compile(r"^(?:the|a|an|any|each|every|such|no)\s+", re.IGNORECASE)
_TRAILING_NOISE_RE = re.compile(
    r"\s+(?:in accordance with|pursuant to|under|as provided in|except as provided in)\s+.+$",
    re.IGNORECASE,
)
_PASSIVE_BY_RE = re.compile(r"^be\s+([A-Za-z][A-Za-z0-9'’\-]*)\s+by\s+(.+)$", re.IGNORECASE)
_PAST_PARTICIPLE_BASE = {
    "adopted": "adopt",
    "awarded": "award",
    "filed": "file",
    "issued": "issue",
    "maintained": "maintain",
    "prepared": "prepare",
    "provided": "provide",
    "submitted": "submit",
}
_MENTAL_STATE_TERMS = {
    "intentionally",
    "knowingly",
    "negligently",
    "recklessly",
    "willfully",
    "wilfully",
}
_RECIPIENT_RE = re.compile(
    r"\b(?:to|for|with|of)\s+((?:the\s+)?[A-Za-z][A-Za-z0-9'’\-]*(?:\s+[A-Za-z][A-Za-z0-9'’\-]*){0,6})$",
    re.IGNORECASE,
)
_DEFINITION_BODY_RE = re.compile(
    r"\b(?:means|includes?|defined\s+as|has\s+the\s+meaning\s+given|refers\s+to)\b\s+(.+)$",
    re.IGNORECASE,
)
_GOVERNMENT_ACTORS = {
    "administrator",
    "agency",
    "bureau",
    "city",
    "commission",
    "commissioner",
    "council",
    "department",
    "director",
    "engineer",
    "examiner",
    "hearings",
    "mayor",
    "officer",
    "secretary",
    "state",
    "auditor",
}
_LEGAL_PERSON_ACTORS = {
    "applicant",
    "borrower",
    "contractor",
    "defendant",
    "employee",
    "employer",
    "individual",
    "landlord",
    "lessee",
    "licensee",
    "owner",
    "party",
    "permittee",
    "person",
    "plaintiff",
    "resident",
    "tenant",
    "worker",
}
_ORGANIZATION_ACTORS = {
    "business",
    "company",
    "corporation",
    "entity",
    "institution",
    "organization",
    "provider",
}
_LEGAL_INSTRUMENT_ENTITIES = {
    "approval",
    "certificate",
    "easement",
    "franchise",
    "license",
    "permit",
    "registration",
    "variance",
}
_LEGAL_EVENT_ENTITIES = {
    "appeal",
    "citation",
    "complaint",
    "fee",
    "hearing",
    "inspection",
    "notice",
    "offense",
    "order",
    "penalty",
    "review",
    "violation",
}
_PROPERTY_ENTITIES = {
    "building",
    "facility",
    "park",
    "premises",
    "property",
    "right-of-way",
    "sewer",
    "sidewalk",
    "street",
    "tree",
    "vehicle",
}
_PROCEDURE_EVENT_ORDER = [
    "application",
    "receipt",
    "inspection",
    "review",
    "notice",
    "hearing",
    "decision",
    "issuance",
    "renewal",
    "suspension",
    "revocation",
    "appeal",
]
_PROCEDURE_EVENT_PATTERNS = {
    "application": r"\b(?:apply|applies|application|applicant)\b",
    "receipt": r"\b(?:receipt|receive|received)\b",
    "inspection": r"\b(?:inspect|inspection)\b",
    "review": r"\b(?:review|investigate|investigation)\b",
    "notice": r"\b(?:notice|notify|notification)\b",
    "hearing": r"\b(?:hearing)\b",
    "decision": r"\b(?:decision|decide|determination|order)\b",
    "issuance": r"\b(?:issue|issued|issuance|grant|approve|approval)\b",
    "renewal": r"\b(?:renew|renewal)\b",
    "suspension": r"\b(?:suspend|suspension)\b",
    "revocation": r"\b(?:revoke|revocation)\b",
    "appeal": r"\b(?:appeal\w*)\b",
}


def extract_normative_elements(
    text: str,
    document_type: str = "statute",
    *,
    expand_enumerations: bool = False,
) -> List[Dict[str, Any]]:
    elements: List[Dict[str, Any]] = []
    segments = segment_legal_text(text)
    for segment in segments:
        segment_text = segment["text"].strip()
        if not segment_text:
            continue
        for element in analyze_normative_sentence(segment_text, document_type):
            element["source_span"] = segment["span"]
            element["section_context"] = segment["section_context"]
            element["hierarchy_path"] = segment["hierarchy_path"]
            element["hierarchy_details"] = segment.get("hierarchy_details", [])
            _finalize_element(element)
            elements.append(element)
    if expand_enumerations:
        elements = expand_enumerated_norms(elements)
    _apply_definition_context(elements)
    _apply_cross_reference_context(elements)
    _apply_document_penalty_context(elements, str(text or ""))
    _apply_enforcement_context(elements)
    _apply_conflict_context(elements)
    return elements


def expand_enumerated_norms(elements: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Expand modal-governed enumerated lists into item-level norm elements.

    The default parser keeps enumerated clauses as one parent scaffold for
    backward compatibility. Formal logic exporters often need one formula per
    list item, so this helper creates deterministic child elements that inherit
    the parent actor, modality, conditions, references, and hierarchy context.
    """

    expanded: List[Dict[str, Any]] = []
    for element in elements or []:
        items = element.get("enumerated_items") or []
        if not items:
            expanded.append(element)
            continue
        parent_source_id = element.get("source_id") or build_source_id(element)
        child_elements = [
            _build_enumerated_child_element(element, item, parent_source_id)
            for item in items
            if isinstance(item, dict) and item.get("text")
        ]
        if child_elements:
            expanded.extend(child_elements)
        else:
            expanded.append(element)
    return expanded


def _build_enumerated_child_element(
    parent: Dict[str, Any],
    item: Dict[str, Any],
    parent_source_id: str,
) -> Dict[str, Any]:
    action_text = _clean_action(str(item.get("text") or ""))
    sentence = str(parent.get("text") or "")
    action_span = _find_span(sentence, action_text)
    support_span = action_span or list(parent.get("support_span") or [])
    child = dict(parent)
    child.update(
        {
            "parent_source_id": parent_source_id,
            "enumeration_label": str(item.get("label") or ""),
            "support_text": action_text,
            "support_span": support_span,
            "action": [action_text],
            "action_verb": _first_verb(action_text),
            "action_object": _action_object(action_text),
            "action_recipient": extract_action_recipient(action_text),
            "enumerated_items": [],
            "extraction_method": "deterministic_enumerated_item_v1",
        }
    )
    field_spans = dict(parent.get("field_spans") or {})
    field_spans["action"] = action_span
    action_start = action_span[0] if len(action_span) == 2 else 0
    field_spans["action_verb"] = _find_span(sentence, child["action_verb"], start=action_start)
    field_spans["action_object"] = _find_span(sentence, child["action_object"], start=action_start)
    field_spans["action_recipient"] = _find_span(sentence, child["action_recipient"], start=action_start)
    child["field_spans"] = field_spans
    return _finalize_element(child)


def _split_legal_sentences(text: str) -> List[str]:
    normalized = re.sub(r"\s+", " ", str(text or "")).strip()
    if not normalized:
        return []
    # Avoid splitting common legal abbreviations such as U.S.C. and Pub. L.
    protected = (
        normalized.replace("U.S.C.", "USC")
        .replace("U.S.", "US")
        .replace("Pub. L.", "Pub L")
        .replace("Sec.", "Sec")
    )
    return [part.strip(" .") for part in _SENTENCE_SPLIT_RE.split(protected) if part.strip(" .")]


def segment_legal_text(text: str) -> List[Dict[str, Any]]:
    """Split legal text into statute-aware segments with hierarchy metadata."""
    source = str(text or "")
    if not source.strip():
        return []

    segments: List[Dict[str, Any]] = []
    section_context: Dict[str, str] = {}
    hierarchy: List[str] = []
    hierarchy_details: List[Dict[str, Any]] = []
    cursor = 0

    for raw_line in source.splitlines() or [source]:
        line_start = cursor
        cursor += len(raw_line) + 1
        line = raw_line.strip()
        if not line:
            continue

        hierarchy_header = _HIERARCHY_HEADER_RE.match(line)
        if hierarchy_header:
            level = hierarchy_header.group(1).lower()
            value = hierarchy_header.group(2)
            heading = hierarchy_header.group(3).strip(" .")
            hierarchy = [item for item in hierarchy if not _hierarchy_path_replaced_by(level, item)]
            hierarchy.append(f"{level}:{value}")
            detail_start = line_start + raw_line.find(line)
            hierarchy_details = [
                item for item in hierarchy_details if not _hierarchy_detail_replaced_by(level, item)
            ]
            hierarchy_details.append(
                {
                    "level": level,
                    "value": value,
                    "heading": heading,
                    "span": [detail_start + hierarchy_header.start(), detail_start + hierarchy_header.end()],
                }
            )
            continue

        header = _SECTION_HEADER_RE.match(line)
        if header and _looks_like_section_header(line, header):
            section_context = {
                "section": header.group(1),
                "heading": header.group(2).strip(" ."),
            }
            hierarchy = [
                item
                for item in hierarchy
                if not item.startswith(("section:", "heading:", "paragraph:", "subsection:"))
            ]
            hierarchy.append(f"section:{section_context['section']}")
            if section_context["heading"]:
                hierarchy.append(f"heading:{section_context['heading']}")
            detail_start = line_start + raw_line.find(line)
            hierarchy_details = [
                item
                for item in hierarchy_details
                if item.get("level") not in {"section", "paragraph", "subsection"}
            ]
            hierarchy_details.append(
                {
                    "level": "section",
                    "value": section_context["section"],
                    "heading": section_context["heading"],
                    "span": [detail_start + header.start(), detail_start + header.end()],
                }
            )
            continue

        for start, end, segment_text, label_path in _split_segment_fragments(line):
            absolute_start = line_start + raw_line.find(line) + start
            segment_hierarchy = [*hierarchy, *label_path]
            segment_hierarchy_details = [
                *hierarchy_details,
                *[
                    {
                        "level": "paragraph",
                        "value": label.split(":", 1)[1],
                        "heading": "",
                        "span": [absolute_start, absolute_start + len(label.split(":", 1)[1]) + 2],
                    }
                    for label in label_path
                    if label.startswith("paragraph:")
                ],
            ]
            for sentence in _split_legal_sentences(segment_text):
                sentence_offset = segment_text.find(sentence)
                if sentence_offset < 0:
                    sentence_offset = 0
                sentence_start = absolute_start + sentence_offset
                segments.append(
                    {
                        "text": sentence,
                        "span": [sentence_start, sentence_start + len(sentence)],
                        "section_context": dict(section_context),
                        "hierarchy_path": segment_hierarchy,
                        "hierarchy_details": segment_hierarchy_details,
                    }
                )

    if not segments:
        normalized = re.sub(r"\s+", " ", source).strip()
        return [
            {
                "text": normalized,
                "span": [0, len(normalized)],
                "section_context": {},
                "hierarchy_path": [],
                "hierarchy_details": [],
            }
        ]
    return segments


def _hierarchy_path_replaced_by(level: str, item: str) -> bool:
    order = ["title", "division", "chapter", "article", "part"]
    if ":" not in item or level not in order:
        return False
    item_level = item.split(":", 1)[0]
    return item_level in order and order.index(item_level) >= order.index(level)


def _hierarchy_detail_replaced_by(level: str, item: Dict[str, Any]) -> bool:
    order = ["title", "division", "chapter", "article", "part"]
    item_level = item.get("level")
    return bool(item_level in order and level in order and order.index(item_level) >= order.index(level))


def _looks_like_section_header(line: str, match: re.Match[str]) -> bool:
    marker = match.group(0)
    if re.match(r"^\s*(?:sec(?:tion)?\.?|§)\b", line, re.IGNORECASE):
        return True
    heading = match.group(2).strip()
    return bool(heading and len(line) < 140 and not re.search(r"\b(?:shall|must|may|means|includes?)\b", line, re.IGNORECASE))


def _split_segment_fragments(line: str) -> List[tuple[int, int, str, List[str]]]:
    matches = list(_ENUM_LABEL_RE.finditer(line))
    if not matches:
        return [(0, len(line), line, [])]

    prefix = line[: matches[0].start()].strip()
    if prefix:
        return [(0, len(line), line, [])]
    fragments: List[tuple[int, int, str, List[str]]] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(line)
        body = line[start:end].strip(" ;,.")
        if not body:
            continue
        fragments.append((match.start(), end, body, [f"paragraph:{match.group(1)}"]))
    return fragments


def analyze_normative_sentence(sentence: str, document_type: str) -> List[Dict[str, Any]]:
    sentence = sentence.strip()
    sentence_lower = sentence.lower()
    elements: List[Dict[str, Any]] = []

    for match in _MODAL_RE.finditer(sentence):
        modal = re.sub(r"\s+", " ", match.group("modal").lower()).strip()
        norm_type, deontic_operator = classify_modal(modal)
        raw_subject = match.group("subject")
        if deontic_operator in {"O", "P"} and re.match(r"\s*(?:no|none)\b", raw_subject or "", flags=re.IGNORECASE):
            norm_type, deontic_operator = "prohibition", "F"
        subject_text = _clean_phrase(raw_subject)
        if subject_text.lower() in {"and", "or"}:
            continue
        action_text = _clean_action(match.group("action"))
        subject_text, action_text = _normalize_passive_clause(subject_text, action_text)
        if not action_text:
            continue
        elements.append(
            _finalize_element(
                _build_element(
                    sentence=sentence,
                    document_type=document_type,
                    norm_type=norm_type,
                    deontic_operator=deontic_operator,
                    modal=modal,
                    subject_text=subject_text,
                    action_text=action_text,
                    support_span=match.span(),
                    field_spans={
                        "subject": list(match.span("subject")),
                        "modal": list(match.span("modal")),
                        "action": list(match.span("action")),
                    },
                    extraction_method="deterministic_modal_clause_v2",
                )
            )
        )

    if elements:
        first_subject = (elements[0].get("subject") or [""])[0]
        occupied_spans = [tuple(item.get("support_span") or []) for item in elements]
        for match in _IMPLICIT_MODAL_RE.finditer(sentence):
            if any(len(span) == 2 and match.start() >= span[0] and match.end() <= span[1] for span in occupied_spans):
                continue
            modal = re.sub(r"\s+", " ", match.group("modal").lower()).strip()
            norm_type, deontic_operator = classify_modal(modal)
            action_text = _clean_action(match.group("action"))
            subject_text, action_text = _normalize_passive_clause(first_subject, action_text)
            if not action_text:
                continue
            elements.append(
                _finalize_element(
                    _build_element(
                        sentence=sentence,
                        document_type=document_type,
                        norm_type=norm_type,
                        deontic_operator=deontic_operator,
                        modal=modal,
                        subject_text=subject_text or first_subject,
                        action_text=action_text,
                        support_span=match.span(),
                        field_spans={
                            "subject": [],
                            "modal": list(match.span("modal")),
                            "action": list(match.span("action")),
                        },
                        extraction_method="deterministic_implicit_modal_clause_v2",
                    )
                )
            )
        return elements

    for match in _IMPERSONAL_NORM_RE.finditer(sentence):
        if match.group("unlawful"):
            subject_text = _clean_phrase(match.group("unlawful_subject") or "person")
            action_text = _clean_action(match.group("unlawful_action"))
            norm_type, deontic_operator = "prohibition", "F"
            modal = "unlawful"
        elif match.group("license"):
            subject_text = _clean_phrase(match.group("license_subject"))
            action_text = f"authorize {match.group('license_action')}"
            norm_type, deontic_operator = "obligation", "O"
            modal = "is required to"
        else:
            subject_text = _clean_phrase(match.group("duty_subject"))
            action_text = _clean_action(match.group("duty_action"))
            norm_type, deontic_operator = "obligation", "O"
            modal = "duty is imposed"
        if not action_text:
            continue
        elements.append(
            _finalize_element(
                _build_element(
                    sentence=sentence,
                    document_type=document_type,
                    norm_type=norm_type,
                    deontic_operator=deontic_operator,
                    modal=modal,
                    subject_text=subject_text,
                    action_text=action_text,
                    support_span=match.span(),
                    field_spans=_impersonal_field_spans(match),
                    extraction_method="deterministic_impersonal_norm_v3",
                )
            )
        )
    if elements:
        return elements

    validity_match = _INSTRUMENT_VALIDITY_RE.search(sentence)
    if validity_match:
        instrument_text = _clean_phrase(validity_match.group("instrument_type"))
        duration_text = _clean_phrase(validity_match.group("duration"))
        return [
            _finalize_element(
                _build_element(
                    sentence=sentence,
                    document_type=document_type,
                    norm_type="instrument_lifecycle",
                    deontic_operator="LIFE",
                    modal="valid for",
                    subject_text=instrument_text,
                    action_text=f"valid for {duration_text}",
                    support_span=validity_match.span(),
                    field_spans={
                        "subject": list(validity_match.span("instrument_type")),
                        "modal": [validity_match.end("instrument_type"), validity_match.start("duration")],
                        "action": list(validity_match.span("duration")),
                    },
                    extraction_method="deterministic_instrument_validity_clause_v1",
                )
            )
        ]

    expiration_match = _INSTRUMENT_EXPIRATION_RE.search(sentence)
    if expiration_match:
        instrument_text = _clean_phrase(expiration_match.group("instrument_type"))
        anchor_text = _clean_phrase(expiration_match.group("anchor"))
        return [
            _finalize_element(
                _build_element(
                    sentence=sentence,
                    document_type=document_type,
                    norm_type="instrument_lifecycle",
                    deontic_operator="LIFE",
                    modal="expires",
                    subject_text=instrument_text,
                    action_text=f"expires {anchor_text}",
                    support_span=expiration_match.span(),
                    field_spans={
                        "subject": list(expiration_match.span("instrument_type")),
                        "modal": [expiration_match.end("instrument_type"), expiration_match.start("anchor")],
                        "action": list(expiration_match.span("anchor")),
                    },
                    extraction_method="deterministic_instrument_expiration_clause_v1",
                )
            )
        ]

    not_required_match = _NOT_REQUIRED_EXEMPTION_RE.search(sentence)
    if not_required_match:
        instrument_text = _clean_phrase(not_required_match.group("instrument"))
        target_text = _clean_phrase(not_required_match.group("target"))
        preposition = not_required_match.group("preposition").lower()
        if preposition == "to":
            target_text = _clean_action(target_text)
        return [
            _finalize_element(
                _build_element(
                    sentence=sentence,
                    document_type=document_type,
                    norm_type="exemption",
                    deontic_operator="EXEMPT",
                    modal="not required",
                    subject_text=target_text,
                    action_text=f"exempt from {instrument_text}",
                    support_span=not_required_match.span(),
                    field_spans={
                        "subject": list(not_required_match.span("target")),
                        "modal": [not_required_match.start("instrument"), not_required_match.start("target")],
                        "action": list(not_required_match.span("instrument")),
                    },
                    extraction_method="deterministic_not_required_exemption_clause_v1",
                )
            )
        ]

    violation_match = _VIOLATION_RE.search(sentence)
    if violation_match:
        action_text = f"fail to {violation_match.group(1).strip()}"
        return [
            _finalize_element(
                _build_element(
                    sentence=sentence,
                    document_type=document_type,
                    norm_type="violation",
                    deontic_operator="F",
                    modal="violation",
                    subject_text="person",
                    action_text=action_text,
                    support_span=violation_match.span(),
                    field_spans={
                        "subject": [],
                        "modal": list(violation_match.span()),
                        "action": list(violation_match.span(1)),
                    },
                    extraction_method="deterministic_violation_clause_v4",
                )
            )
        ]

    penalty_match = _PENALTY_RE.search(sentence)
    if penalty_match:
        penalty_text = penalty_match.group(1).strip()
        return [
            _finalize_element(
                _build_element(
                    sentence=sentence,
                    document_type=document_type,
                    norm_type="penalty",
                    deontic_operator="O",
                    modal="penalty",
                    subject_text="violation",
                    action_text=f"incur {penalty_text}",
                    support_span=penalty_match.span(),
                    field_spans={
                        "subject": list(penalty_match.span()),
                        "modal": list(penalty_match.span()),
                        "action": list(penalty_match.span(1)),
                    },
                    extraction_method="deterministic_penalty_clause_v4",
                )
            )
        ]

    non_applicability_match = _NON_APPLICABILITY_RE.search(sentence)
    if non_applicability_match:
        scope_subject = f"{non_applicability_match.group('scope')} {non_applicability_match.group('scope_type')}".lower()
        target_text = _clean_phrase(non_applicability_match.group("target"))
        return [
            _finalize_element(
                _build_element(
                    sentence=sentence,
                    document_type=document_type,
                    norm_type="exemption",
                    deontic_operator="EXEMPT",
                    modal="does not apply to",
                    subject_text=scope_subject,
                    action_text=f"not apply to {target_text}",
                    support_span=non_applicability_match.span(),
                    field_spans={
                        "subject": list(non_applicability_match.span("scope_type")),
                        "modal": [non_applicability_match.start(), non_applicability_match.start("target")],
                        "action": list(non_applicability_match.span("target")),
                    },
                    extraction_method="deterministic_non_applicability_clause_v1",
                )
            )
        ]

    applicability_match = _APPLICABILITY_RE.search(sentence)
    if applicability_match:
        scope_subject = f"{applicability_match.group('scope')} {applicability_match.group('scope_type')}".lower()
        target_text = _clean_phrase(applicability_match.group("target"))
        return [
            _finalize_element(
                _build_element(
                    sentence=sentence,
                    document_type=document_type,
                    norm_type="applicability",
                    deontic_operator="APP",
                    modal="applies to",
                    subject_text=scope_subject,
                    action_text=f"apply to {target_text}",
                    support_span=applicability_match.span(),
                    field_spans={
                        "subject": list(applicability_match.span("scope_type")),
                        "modal": [applicability_match.start(), applicability_match.start("target")],
                        "action": list(applicability_match.span("target")),
                    },
                    extraction_method="deterministic_applicability_clause_v1",
                )
            )
        ]

    exemption_match = _EXEMPTION_RE.search(sentence)
    if exemption_match:
        target_text = _clean_phrase(exemption_match.group("target"))
        requirement_text = _clean_action(exemption_match.group("requirement"))
        return [
            _finalize_element(
                _build_element(
                    sentence=sentence,
                    document_type=document_type,
                    norm_type="exemption",
                    deontic_operator="EXEMPT",
                    modal="exempt from",
                    subject_text=target_text,
                    action_text=f"exempt from {requirement_text}",
                    support_span=exemption_match.span(),
                    field_spans={
                        "subject": list(exemption_match.span("target")),
                        "modal": [exemption_match.end("target"), exemption_match.start("requirement")],
                        "action": list(exemption_match.span("requirement")),
                    },
                    extraction_method="deterministic_exemption_clause_v1",
                )
            )
        ]

    if _DEFINITION_RE.search(sentence_lower):
        defined_term_match = _DEFINED_TERM_RE.search(sentence) or _UNQUOTED_DEFINED_TERM_RE.search(sentence)
        defined_terms = [_clean_phrase(defined_term_match.group(1))] if defined_term_match else extract_legal_subject(sentence)
        return [
            _finalize_element(
                {
                "schema_version": PARSER_SCHEMA_VERSION,
                "source_id": "",
                "canonical_citation": "",
                "text": sentence,
                "support_text": sentence,
                "support_span": [0, len(sentence)],
                "field_spans": {
                    "defined_term": list(defined_term_match.span(1)) if defined_term_match else [],
                    "definition_body": _definition_body_span(sentence),
                    "subject": list(defined_term_match.span(1)) if defined_term_match else [],
                    "modal": [],
                    "action": [0, len(sentence)],
                    "action_verb": [],
                    "action_object": [],
                    "action_recipient": [],
                },
                "norm_type": "definition",
                "deontic_operator": "DEF",
                "modal": "definition",
                "subject": defined_terms,
                "action": [sentence],
                "defined_term": defined_terms[0] if defined_terms else "",
                "definition_body": extract_definition_body(sentence),
                "conditions": extract_conditions(sentence),
                "condition_details": extract_condition_details(sentence),
                "temporal_constraints": extract_temporal_constraints(sentence),
                "temporal_constraint_details": extract_temporal_constraint_details(sentence),
                "exceptions": extract_exceptions(sentence),
                "exception_details": extract_exception_details(sentence),
                "override_clauses": extract_override_clauses(sentence),
                "override_clause_details": extract_override_clause_details(sentence),
                "cross_references": extract_cross_references(sentence),
                "cross_reference_details": extract_cross_reference_details(sentence),
                "resolved_cross_references": [],
                "enforcement_links": [],
                "conflict_links": [],
                "enumerated_items": extract_enumerated_items(sentence),
                "defined_term_refs": [],
                "definition_scope": infer_definition_scope(sentence),
                "ontology_terms": extract_ontology_terms(sentence),
                "formal_terms": {},
                "llm_repair": {},
                "export_readiness": {},
                "logic_frame": {},
                "legal_frame": {},
                "kg_relationship_hints": [],
                "monetary_amounts": extract_monetary_amounts(sentence),
                "monetary_amount_details": extract_monetary_amount_details(sentence),
                "penalty": {},
                "procedure": {},
                "actor_type": classify_legal_entity(defined_terms[0] if defined_terms else ""),
                "entity_type": classify_legal_entity(defined_terms[0] if defined_terms else ""),
                "action_verb": "",
                "action_object": "",
                "action_recipient": "",
                "section_context": {},
                "hierarchy_path": [],
                "hierarchy_details": [],
                "document_type": document_type,
                "extraction_method": "deterministic_definition_v2",
                "confidence_floor": 0.25,
                }
            )
        ]

    return []


def _build_element(
    *,
    sentence: str,
    document_type: str,
    norm_type: str,
    deontic_operator: str,
    modal: str,
    subject_text: str,
    action_text: str,
    support_span: tuple[int, int],
    extraction_method: str,
    field_spans: Optional[Dict[str, List[int]]] = None,
) -> Dict[str, Any]:
    enumerated_items = extract_enumerated_items(sentence)
    if enumerated_items and re.match(r"^\([A-Za-z0-9]+\)\s+", action_text or ""):
        action_text = enumerated_items[0]["text"]
    subject = [subject_text] if subject_text else extract_legal_subject(sentence)
    action = [action_text]
    spans = _complete_field_spans(sentence, subject_text, action_text, field_spans or {})
    return {
        "schema_version": PARSER_SCHEMA_VERSION,
        "source_id": "",
        "canonical_citation": "",
        "text": sentence,
        "support_text": sentence[support_span[0] : support_span[1]].strip(),
        "support_span": list(support_span),
        "field_spans": spans,
        "norm_type": norm_type,
        "deontic_operator": deontic_operator,
        "modal": modal,
        "subject": subject,
        "actor_type": classify_legal_entity(subject[0] if subject else ""),
        "entity_type": classify_legal_entity(subject[0] if subject else ""),
        "action": action,
        "mental_state": _mental_state(action_text),
        "action_verb": _first_verb(action_text),
        "action_object": _action_object(action_text),
        "action_recipient": extract_action_recipient(action_text),
        "conditions": extract_conditions(sentence),
        "condition_details": extract_condition_details(sentence),
        "temporal_constraints": extract_temporal_constraints(sentence),
        "temporal_constraint_details": extract_temporal_constraint_details(sentence),
        "exceptions": extract_exceptions(sentence),
        "exception_details": extract_exception_details(sentence),
        "override_clauses": extract_override_clauses(sentence),
        "override_clause_details": extract_override_clause_details(sentence),
        "cross_references": extract_cross_references(sentence),
        "cross_reference_details": extract_cross_reference_details(sentence),
        "resolved_cross_references": [],
        "enforcement_links": [],
        "conflict_links": [],
        "enumerated_items": enumerated_items,
        "defined_term_refs": [],
        "definition_scope": {},
        "ontology_terms": extract_ontology_terms(sentence),
        "formal_terms": {},
        "llm_repair": {},
        "export_readiness": {},
        "logic_frame": {},
        "legal_frame": {},
        "kg_relationship_hints": [],
        "monetary_amounts": extract_monetary_amounts(sentence),
        "monetary_amount_details": extract_monetary_amount_details(sentence),
        "penalty": {},
        "procedure": {},
        "section_context": {},
        "hierarchy_path": [],
        "hierarchy_details": [],
        "document_type": document_type,
        "extraction_method": extraction_method,
        "confidence_floor": 0.35,
    }


def _complete_field_spans(
    sentence: str,
    subject_text: str,
    action_text: str,
    field_spans: Dict[str, List[int]],
) -> Dict[str, List[int]]:
    raw_subject_span = list(field_spans.get("subject") or [])
    if len(raw_subject_span) == 2:
        raw_subject = sentence[raw_subject_span[0] : raw_subject_span[1]]
        subject_span = raw_subject_span if raw_subject.strip().lower() == subject_text.lower() else _find_span(sentence, subject_text, start=raw_subject_span[0])
    else:
        subject_span = _find_span(sentence, subject_text)
    spans = {
        "subject": subject_span,
        "modal": list(field_spans.get("modal") or []),
        "action": list(field_spans.get("action") or _find_span(sentence, action_text)),
        "action_verb": [],
        "action_object": [],
        "action_recipient": [],
        "defined_term": [],
        "definition_body": [],
    }
    action_start = spans["action"][0] if len(spans["action"]) == 2 else 0
    action_verb = _first_verb(action_text)
    action_object = _action_object(action_text)
    action_recipient = extract_action_recipient(action_text)
    spans["action_verb"] = _find_span(sentence, action_verb, start=action_start)
    spans["action_object"] = _find_span(sentence, action_object, start=action_start)
    spans["action_recipient"] = _find_span(sentence, action_recipient, start=action_start)
    return spans


def _find_span(text: str, value: str, start: int = 0) -> List[int]:
    if not value:
        return []
    match = re.search(re.escape(str(value)), str(text or "")[start:], flags=re.IGNORECASE)
    if not match:
        return []
    return [start + match.start(), start + match.end()]


def _definition_body_span(sentence: str) -> List[int]:
    match = _DEFINITION_BODY_RE.search(str(sentence or ""))
    if not match:
        return []
    return [match.start(1), match.end(1)]


def _impersonal_field_spans(match: re.Match[str]) -> Dict[str, List[int]]:
    if match.group("unlawful"):
        return {
            "subject": list(match.span("unlawful_subject")) if match.group("unlawful_subject") else [],
            "modal": list(match.span("unlawful")),
            "action": list(match.span("unlawful_action")),
        }
    if match.group("license"):
        return {
            "subject": list(match.span("license_subject")),
            "modal": list(match.span("license")),
            "action": list(match.span("license_action")),
        }
    return {
        "subject": list(match.span("duty_subject")),
        "modal": list(match.span("duty")),
        "action": list(match.span("duty_action")),
    }


def _finalize_element(element: Dict[str, Any]) -> Dict[str, Any]:
    element.setdefault("schema_version", PARSER_SCHEMA_VERSION)
    element.setdefault("section_context", {})
    element.setdefault("hierarchy_path", [])
    element.setdefault("hierarchy_details", [])
    element.setdefault("defined_term_refs", [])
    element.setdefault("resolved_cross_references", [])
    element.setdefault("enforcement_links", [])
    element.setdefault("conflict_links", [])
    element.setdefault("definition_scope", {})
    element.setdefault("ontology_terms", extract_ontology_terms(element.get("text", "")))
    element["canonical_citation"] = build_canonical_citation(element)
    element["source_id"] = build_source_id(element)
    element.setdefault("llm_repair", {})
    element.setdefault("export_readiness", {})
    element.setdefault("logic_frame", {})
    _enrich_legal_frame(element)
    element["formal_terms"] = build_formal_terms(element)
    quality = score_scaffold_quality(element)
    element["slot_coverage"] = quality["slot_coverage"]
    element["scaffold_quality"] = quality["score"]
    element["quality_label"] = quality["label"]
    element["parser_warnings"] = quality["warnings"]
    element["promotable_to_theorem"] = quality["promotable_to_theorem"]
    schema_validation = validate_parser_element(element)
    element["schema_valid"] = schema_validation["valid"]
    if not schema_validation["valid"]:
        element["parser_warnings"] = [
            *element["parser_warnings"],
            *[f"schema_{field}_missing" for field in schema_validation["missing_fields"]],
        ]
        element["promotable_to_theorem"] = False
    element["logic_frame"] = build_logic_frame(element)
    element["llm_repair"] = build_llm_repair_payload(element)
    element["export_readiness"] = build_export_readiness(element)
    return element


def _apply_definition_context(elements: List[Dict[str, Any]]) -> None:
    definitions = [
        element
        for element in elements
        if element.get("norm_type") == "definition" and element.get("defined_term")
    ]
    if not definitions:
        return
    for element in elements:
        if element.get("norm_type") == "definition":
            continue
        refs: List[Dict[str, Any]] = []
        text = str(element.get("text") or "")
        for definition in definitions:
            if not _definition_applies_to_element(definition, element):
                continue
            term = str(definition.get("defined_term") or "").strip()
            if not term:
                continue
            for match in re.finditer(rf"\b{re.escape(term)}s?\b", text, flags=re.IGNORECASE):
                refs.append(
                    {
                        "term": term,
                        "definition_body": definition.get("definition_body", ""),
                        "definition_text": definition.get("text", ""),
                        "definition_scope": definition.get("definition_scope", {}),
                        "span": [match.start(), match.end()],
                    }
                )
        element["defined_term_refs"] = refs
        if refs:
            existing = element.get("kg_relationship_hints", [])
            for ref in refs:
                existing.append(
                    {
                        "subject": ref["term"],
                        "predicate": "definedBy",
                        "object": ref["definition_body"] or ref["definition_text"],
                    }
                )
            element["kg_relationship_hints"] = existing
            element["ontology_terms"] = merge_ontology_terms(element.get("ontology_terms", []), refs)
            _finalize_element(element)


def build_canonical_citation(element: Dict[str, Any]) -> str:
    """Build a deterministic citation-like label from available hierarchy metadata."""
    parts: List[str] = []
    for level in ["title", "division", "chapter", "article", "part"]:
        value = _hierarchy_value(element, level)
        if value:
            parts.append(f"{level} {value}")
    section = (element.get("section_context") or {}).get("section")
    if section:
        parts.append(f"section {section}")
    paragraph = _hierarchy_value(element, "paragraph")
    if paragraph:
        parts.append(f"paragraph ({paragraph})")
    return " / ".join(parts)


def build_source_id(element: Dict[str, Any]) -> str:
    """Create a stable deterministic ID for joins across parquet/KG/proof exports."""
    identity = {
        "citation": element.get("canonical_citation") or build_canonical_citation(element),
        "source_span": element.get("source_span", []),
        "support_span": element.get("support_span", []),
        "norm_type": element.get("norm_type", ""),
        "operator": element.get("deontic_operator", ""),
        "text": element.get("text", ""),
    }
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    return f"deontic:{digest[:24]}"


def build_formal_terms(element: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize parser slots into symbols shared by KG and formal exporters."""
    action_text = (element.get("action") or [""])[0]
    actor = (element.get("subject") or [""])[0]
    section = (element.get("section_context") or {}).get("section", "")
    return {
        "source_id": element.get("source_id", ""),
        "citation_id": normalize_symbol(element.get("canonical_citation", "")),
        "section_id": normalize_symbol(section),
        "actor_id": normalize_symbol(actor),
        "actor_predicate": normalize_predicate_name(actor),
        "action_predicate": normalize_predicate_name(_action_without_mental_state(action_text)),
        "object_predicate": normalize_predicate_name(element.get("action_object", "")),
        "recipient_id": normalize_symbol(element.get("action_recipient", "")),
        "norm_predicate": normalize_predicate_name(element.get("norm_type", "")),
        "category_predicate": normalize_predicate_name((element.get("legal_frame") or {}).get("category", "")),
        "defined_term_id": normalize_symbol(element.get("defined_term", "")),
    }


def normalize_symbol(value: str) -> str:
    normalized = re.sub(r"[^0-9A-Za-z]+", "_", str(value or "").strip().lower()).strip("_")
    return normalized or "unknown"


def _definition_applies_to_element(definition: Dict[str, Any], element: Dict[str, Any]) -> bool:
    scope = definition.get("definition_scope") or {}
    scope_type = scope.get("scope_type", "document")
    if scope_type == "section":
        definition_section = (definition.get("section_context") or {}).get("section")
        element_section = (element.get("section_context") or {}).get("section")
        return bool(definition_section and definition_section == element_section) or not definition_section
    if scope_type in {"title", "chapter"}:
        return _same_hierarchy_scope(definition, element, scope_type)
    return True


def _same_hierarchy_scope(definition: Dict[str, Any], element: Dict[str, Any], level: str) -> bool:
    definition_value = _hierarchy_value(definition, level)
    element_value = _hierarchy_value(element, level)
    return bool(definition_value and definition_value == element_value) or not definition_value


def _hierarchy_value(element: Dict[str, Any], level: str) -> str:
    for detail in element.get("hierarchy_details") or []:
        if detail.get("level") == level:
            return str(detail.get("value") or "")
    prefix = f"{level}:"
    for item in element.get("hierarchy_path") or []:
        if str(item).startswith(prefix):
            return str(item).split(":", 1)[1]
    return ""


def _apply_cross_reference_context(elements: List[Dict[str, Any]]) -> None:
    section_index = _build_section_index(elements)
    for element in elements:
        resolved_refs = resolve_cross_references(element, section_index)
        element["resolved_cross_references"] = resolved_refs
        if resolved_refs:
            _finalize_element(element)


def _build_section_index(elements: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    index: Dict[str, Dict[str, Any]] = {}
    for element in elements:
        section = (element.get("section_context") or {}).get("section")
        if not section:
            continue
        index.setdefault(
            _normalize_section_ref(section),
            {
                "section": section,
                "heading": (element.get("section_context") or {}).get("heading", ""),
                "hierarchy_path": list(element.get("hierarchy_path") or []),
                "hierarchy_details": list(element.get("hierarchy_details") or []),
                "source_span": list(element.get("source_span") or []),
            },
        )
    return index


def resolve_cross_references(
    element: Dict[str, Any],
    section_index: Optional[Dict[str, Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Resolve extracted cross references against known in-document sections."""
    section_index = section_index or {}
    resolved: List[Dict[str, Any]] = []
    for ref in element.get("cross_reference_details") or []:
        detail = dict(ref)
        ref_type = str(detail.get("type") or "")
        value = str(detail.get("value") or "")
        detail["resolution_status"] = "external"
        detail["target_exists"] = False
        detail["target_section"] = ""
        detail["target_heading"] = ""
        detail["target_hierarchy_path"] = []
        if ref_type == "section_range":
            targets = _resolve_section_range(detail, section_index)
            detail["resolution_status"] = "resolved" if targets else "unresolved"
            detail["target_exists"] = bool(targets)
            detail["target_sections"] = targets
            resolved.append(detail)
            continue
        if ref_type == "section":
            target = (
                _relative_reference_target(element, "section")
                if _is_relative_reference(value)
                else section_index.get(_normalize_section_ref(value))
            )
        elif ref_type in {"subsection", "paragraph", "chapter", "title"}:
            target = _hierarchy_reference_target(element, ref_type, value)
        else:
            target = {}
        if ref_type in {"section", "subsection", "paragraph", "chapter", "title"}:
            detail["resolution_status"] = "resolved" if target else "unresolved"
            detail["target_exists"] = bool(target)
            if target:
                detail["target_section"] = target.get("section", "")
                detail["target_heading"] = target.get("heading", "")
                detail["target_hierarchy_path"] = list(target.get("hierarchy_path") or [])
        resolved.append(detail)
    return resolved


def _hierarchy_reference_target(element: Dict[str, Any], ref_type: str, value: str) -> Dict[str, Any]:
    if _is_relative_reference(value):
        return _relative_reference_target(element, ref_type)
    if ref_type in {"chapter", "title"}:
        current_value = _hierarchy_value(element, ref_type)
        return _relative_reference_target(element, ref_type) if current_value and current_value.lower() == value.lower() else {}
    normalized_value = str(value or "").strip().lower()
    candidates = [f"{ref_type}:{normalized_value}"]
    if ref_type == "subsection":
        candidates.append(f"paragraph:{normalized_value}")
    matched_path = [
        item for item in element.get("hierarchy_path") or [] if str(item).lower() in candidates
    ]
    if not matched_path:
        return {}
    section_context = element.get("section_context") or {}
    return {
        "section": section_context.get("section", ""),
        "heading": section_context.get("heading", ""),
        "hierarchy_path": matched_path,
        "hierarchy_details": [
            item
            for item in element.get("hierarchy_details") or []
            if item.get("level") in {ref_type, "paragraph"} and str(item.get("value") or "").lower() == normalized_value
        ],
        "source_span": list(element.get("source_span") or []),
    }


def _resolve_section_range(
    ref: Dict[str, Any],
    section_index: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    start = _section_sort_key(ref.get("start_section", ""))
    end = _section_sort_key(ref.get("end_section", ""))
    if not start or not end:
        return []
    if start > end:
        start, end = end, start
    targets: List[Dict[str, Any]] = []
    for target in section_index.values():
        key = _section_sort_key(target.get("section", ""))
        if key and start <= key <= end:
            targets.append(
                {
                    "section": target.get("section", ""),
                    "heading": target.get("heading", ""),
                    "hierarchy_path": list(target.get("hierarchy_path") or []),
                }
            )
    return sorted(targets, key=lambda item: _section_sort_key(item.get("section", "")))


def _section_sort_key(value: str) -> tuple[int, ...]:
    parts = re.findall(r"\d+", str(value or ""))
    return tuple(int(part) for part in parts)


def _relative_reference_target(element: Dict[str, Any], ref_type: str) -> Dict[str, Any]:
    if ref_type == "section":
        section_context = element.get("section_context") or {}
        section = section_context.get("section", "")
        if not section:
            return {}
        return {
            "section": section,
            "heading": section_context.get("heading", ""),
            "hierarchy_path": list(element.get("hierarchy_path") or []),
            "hierarchy_details": list(element.get("hierarchy_details") or []),
            "source_span": list(element.get("source_span") or []),
        }
    if ref_type in {"subsection", "paragraph"}:
        prefix = f"{ref_type}:"
        path = [item for item in element.get("hierarchy_path") or [] if str(item).startswith(prefix)]
        if ref_type == "subsection" and not path:
            path = [item for item in element.get("hierarchy_path") or [] if str(item).startswith("paragraph:")]
        if not path:
            return {}
        section_context = element.get("section_context") or {}
        return {
            "section": section_context.get("section", ""),
            "heading": section_context.get("heading", ""),
            "hierarchy_path": path,
            "hierarchy_details": [
                item
                for item in element.get("hierarchy_details") or []
                if item.get("level") in {ref_type, "paragraph"}
            ],
            "source_span": list(element.get("source_span") or []),
        }
    value = _hierarchy_value(element, ref_type)
    if not value:
        return {}
    detail = next(
        (item for item in element.get("hierarchy_details") or [] if item.get("level") == ref_type),
        {},
    )
    prefix = f"{ref_type}:{value}"
    return {
        "section": "",
        "heading": detail.get("heading", ""),
        "hierarchy_path": [item for item in element.get("hierarchy_path") or [] if str(item).startswith(prefix)],
        "hierarchy_details": [detail] if detail else [],
        "source_span": list(detail.get("span") or []),
    }


def _is_relative_reference(value: str) -> bool:
    return bool(re.match(r"^this\s+(?:section|subsection|paragraph|chapter|title)$", str(value or ""), flags=re.IGNORECASE))


def _normalize_section_ref(value: str) -> str:
    return re.sub(r"[^0-9a-z]+", ".", str(value or "").lower()).strip(".")


def _unresolved_cross_references(element: Dict[str, Any]) -> List[Dict[str, Any]]:
    internal_ref_types = {"section", "section_range", "subsection", "paragraph", "chapter", "title"}
    resolved = element.get("resolved_cross_references") or []
    if resolved:
        return [
            ref
            for ref in resolved
            if ref.get("type") in internal_ref_types and ref.get("resolution_status") == "unresolved"
        ]
    return [ref for ref in element.get("cross_reference_details") or [] if ref.get("type") in internal_ref_types]


def _apply_document_penalty_context(elements: List[Dict[str, Any]], source_text: str) -> None:
    recurrence = extract_penalty_recurrence(source_text)
    if not recurrence:
        return
    for element in elements:
        if (element.get("legal_frame") or {}).get("category") != "penalty":
            continue
        penalty = dict(element.get("penalty") or {})
        if not penalty.get("recurrence"):
            penalty["recurrence"] = recurrence
            element["penalty"] = penalty
            _finalize_element(element)


def _apply_enforcement_context(elements: List[Dict[str, Any]]) -> None:
    section_violation_index = _build_section_violation_index(elements)
    for element in elements:
        links = extract_enforcement_links(element, section_violation_index)
        element["enforcement_links"] = links
        if links:
            _finalize_element(element)


def _apply_conflict_context(elements: List[Dict[str, Any]]) -> None:
    conflicts = detect_normative_conflicts(elements)
    if not conflicts:
        return
    for conflict in conflicts:
        indices = conflict.get("element_indices") or []
        for index in indices:
            if not isinstance(index, int) or index >= len(elements):
                continue
            other_indices = [item for item in indices if item != index]
            link = {
                "type": conflict.get("type", ""),
                "severity": conflict.get("severity", ""),
                "description": conflict.get("description", ""),
                "element_indices": indices,
                "other_element_indices": other_indices,
                "resolution_strategies": conflict.get("resolution_strategies", []),
            }
            existing = elements[index].setdefault("conflict_links", [])
            if link not in existing:
                existing.append(link)
            _finalize_element(elements[index])


def _build_section_violation_index(elements: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    index: Dict[str, Dict[str, Any]] = {}
    for element in elements:
        if (element.get("legal_frame") or {}).get("category") != "violation":
            continue
        section = (element.get("section_context") or {}).get("section")
        if not section:
            continue
        index.setdefault(
            _normalize_section_ref(section),
            {
                "section": section,
                "heading": (element.get("section_context") or {}).get("heading", ""),
                "source_span": list(element.get("source_span") or []),
                "text": element.get("text", ""),
            },
        )
    return index


def extract_enforcement_links(
    element: Dict[str, Any],
    section_violation_index: Optional[Dict[str, Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Infer enforcement targets for violation and penalty formalization."""
    category = (element.get("legal_frame") or {}).get("category", "")
    if category not in {"violation", "penalty"}:
        return []
    section_violation_index = section_violation_index or {}
    targets = _enforcement_target_sections(element)
    links: List[Dict[str, Any]] = []
    link_type = "defines_violation_of" if category == "violation" else "penalizes_violation_of"
    if not targets and category == "penalty":
        section = (element.get("section_context") or {}).get("section", "")
        if section and _normalize_section_ref(section) in section_violation_index:
            targets.append(
                {
                    "target_type": "section",
                    "target_section": section,
                    "target_heading": (element.get("section_context") or {}).get("heading", ""),
                    "target_hierarchy_path": list(element.get("hierarchy_path") or []),
                    "resolution_status": "inferred",
                    "source": "same_section_violation",
                }
            )
    for target in targets:
        link = {
            "type": link_type,
            "target_type": target.get("target_type", "section"),
            "target_section": target.get("target_section", ""),
            "target_heading": target.get("target_heading", ""),
            "target_hierarchy_path": target.get("target_hierarchy_path", []),
            "resolution_status": target.get("resolution_status", "unresolved"),
            "source": target.get("source", "cross_reference"),
        }
        violation = section_violation_index.get(_normalize_section_ref(link["target_section"]))
        if category == "penalty" and violation:
            link["target_violation_text"] = violation.get("text", "")
            link["target_violation_span"] = violation.get("source_span", [])
        links.append(link)
    return links


def _enforcement_target_sections(element: Dict[str, Any]) -> List[Dict[str, Any]]:
    targets: List[Dict[str, Any]] = []
    for ref in element.get("resolved_cross_references") or []:
        if ref.get("type") != "section":
            continue
        target_section = ref.get("target_section") or ""
        if not target_section and _is_relative_reference(ref.get("value", "")):
            target_section = (element.get("section_context") or {}).get("section", "")
        targets.append(
            {
                "target_type": "section",
                "target_section": target_section,
                "target_heading": ref.get("target_heading", ""),
                "target_hierarchy_path": list(ref.get("target_hierarchy_path") or []),
                "resolution_status": ref.get("resolution_status", "unresolved"),
                "source": "cross_reference",
            }
        )
    if targets:
        return targets
    text = str(element.get("text") or "").lower()
    if re.search(r"\b(?:this|the)\s+section\b", text):
        section_context = element.get("section_context") or {}
        section = section_context.get("section", "")
        if section:
            targets.append(
                {
                    "target_type": "section",
                    "target_section": section,
                    "target_heading": section_context.get("heading", ""),
                    "target_hierarchy_path": list(element.get("hierarchy_path") or []),
                    "resolution_status": "resolved",
                    "source": "local_section_phrase",
                }
            )
    return targets


def validate_parser_element(element: Dict[str, Any]) -> Dict[str, Any]:
    """Validate the stable deterministic parser element contract."""
    missing = [field for field in PARSER_REQUIRED_FIELDS if field not in element]
    type_errors: List[str] = []
    list_fields = [
        "support_span",
        "subject",
        "action",
        "conditions",
        "condition_details",
        "temporal_constraints",
        "temporal_constraint_details",
        "exceptions",
        "exception_details",
        "override_clauses",
        "override_clause_details",
        "cross_references",
        "cross_reference_details",
        "resolved_cross_references",
        "enforcement_links",
        "conflict_links",
        "enumerated_items",
        "defined_term_refs",
        "ontology_terms",
        "kg_relationship_hints",
        "monetary_amounts",
        "monetary_amount_details",
        "hierarchy_path",
        "hierarchy_details",
        "parser_warnings",
    ]
    for field in list_fields:
        if field in element and not isinstance(element[field], list):
            type_errors.append(field)
    if "section_context" in element and not isinstance(element["section_context"], dict):
        type_errors.append("section_context")
    for field in ["definition_scope", "export_readiness", "field_spans", "formal_terms", "legal_frame", "logic_frame", "llm_repair", "penalty", "procedure"]:
        if field in element and not isinstance(element[field], dict):
            type_errors.append(field)
    if "support_span" in element and len(element["support_span"]) != 2:
        type_errors.append("support_span")
    return {
        "valid": not missing and not type_errors,
        "missing_fields": missing,
        "type_errors": type_errors,
        "schema_version": element.get("schema_version", PARSER_SCHEMA_VERSION),
    }


def migrate_parser_element(element: Dict[str, Any]) -> Dict[str, Any]:
    """Upgrade an older deterministic parser element to the current schema."""
    migrated = dict(element or {})
    migrated["previous_schema_version"] = migrated.get("schema_version", "unknown")
    migrated["schema_version"] = PARSER_SCHEMA_VERSION
    text = str(migrated.get("text") or migrated.get("source_text") or "")
    support_text = str(migrated.get("support_text") or text)
    migrated.setdefault("text", text)
    migrated.setdefault("support_text", support_text)
    migrated.setdefault("support_span", [0, len(support_text)])
    migrated.setdefault("subject", [])
    migrated.setdefault("action", [])
    migrated.setdefault("modal", "")
    migrated.setdefault("norm_type", "unknown")
    migrated.setdefault("deontic_operator", "")
    migrated.setdefault("document_type", "statute")
    migrated.setdefault("extraction_method", "migrated_legacy_parser_element")
    migrated.setdefault("confidence_floor", 0.1)
    migrated.setdefault("conditions", [])
    migrated.setdefault("exceptions", [])
    migrated.setdefault("override_clauses", [])
    migrated.setdefault("cross_references", [])
    migrated.setdefault("enumerated_items", [])
    for field, default in LEGACY_SCHEMA_DEFAULTS.items():
        migrated.setdefault(field, list(default) if isinstance(default, list) else dict(default))
    migrated["condition_details"] = migrated["condition_details"] or _legacy_clause_details(migrated.get("conditions", []), "condition")
    migrated["exception_details"] = migrated["exception_details"] or _legacy_clause_details(migrated.get("exceptions", []), "exception")
    migrated["override_clause_details"] = migrated["override_clause_details"] or _legacy_clause_details(migrated.get("override_clauses", []), "override")
    migrated["cross_reference_details"] = migrated["cross_reference_details"] or _legacy_cross_reference_details(migrated.get("cross_references", []))
    migrated["temporal_constraint_details"] = migrated["temporal_constraint_details"] or _legacy_temporal_details(migrated.get("temporal_constraints", []))
    migrated.setdefault("temporal_constraints", [])
    migrated["actor_type"] = migrated.get("actor_type") or classify_legal_entity((migrated.get("subject") or [""])[0] if migrated.get("subject") else "")
    migrated["entity_type"] = migrated.get("entity_type") or migrated["actor_type"]
    action_text = (migrated.get("action") or [""])[0] if migrated.get("action") else ""
    migrated["action_verb"] = migrated.get("action_verb") or _first_verb(action_text)
    migrated["action_object"] = migrated.get("action_object") or _action_object(action_text)
    migrated["action_recipient"] = migrated.get("action_recipient") or extract_action_recipient(action_text)
    if not migrated.get("field_spans"):
        migrated["field_spans"] = _complete_field_spans(text, (migrated.get("subject") or [""])[0] if migrated.get("subject") else "", action_text, {})
    return _finalize_element(migrated)


def _legacy_clause_details(values: List[str], slot_type: str) -> List[Dict[str, Any]]:
    return [
        {
            "type": slot_type,
            "clause_type": "legacy",
            "raw_text": str(value),
            "normalized_text": str(value).lower(),
            "span": [],
            "clause_span": [],
        }
        for value in values or []
    ]


def _legacy_cross_reference_details(refs: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    return [
        {
            "type": ref.get("type", "reference"),
            "value": ref.get("value", ""),
            "raw_text": f"{ref.get('type', 'reference')} {ref.get('value', '')}".strip(),
            "normalized_text": f"{ref.get('type', 'reference')} {ref.get('value', '')}".strip().lower(),
            "span": [],
        }
        for ref in refs or []
        if isinstance(ref, dict)
    ]


def _legacy_temporal_details(items: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    return [
        {
            "type": item.get("type", "temporal"),
            "temporal_kind": "legacy",
            "value": item.get("value", ""),
            "anchor": "",
            "raw_text": item.get("value", ""),
            "normalized_text": item.get("value", "").lower(),
            "span": [],
        }
        for item in items or []
        if isinstance(item, dict)
    ]


def _deterministic_ir_repair_resolution(element: Dict[str, Any]) -> Dict[str, Any]:
    """Return formula-layer repair clearance when it is explicitly deterministic."""

    try:
        from ipfs_datasets_py.logic.deontic.formula_builder import parser_element_to_formula_record
    except Exception:
        return {}

    try:
        formula_record = parser_element_to_formula_record(element)
    except Exception:
        return {}

    deterministic_resolution = formula_record.get("deterministic_resolution") or {}
    if not deterministic_resolution:
        return {}
    if formula_record.get("proof_ready") is not True:
        return {}
    if formula_record.get("requires_validation") is True:
        return {}
    if formula_record.get("repair_required") is True:
        return {}
    return deterministic_resolution


def build_llm_repair_payload(element: Dict[str, Any]) -> Dict[str, Any]:
    """Build a deterministic handoff payload for optional llm_router repair."""
    reasons = list(element.get("parser_warnings", []))
    if element.get("schema_valid") is False:
        reasons.append("schema_validation_failed")
    if element.get("quality_label") == "low":
        reasons.append("low_scaffold_quality")
    if element.get("promotable_to_theorem") is False and not reasons:
        reasons.append("not_promotable_to_theorem")

    deterministic_resolution = _deterministic_ir_repair_resolution(element)
    if deterministic_resolution:
        reasons = []
    required = bool(reasons)
    prompt_context = {
        "source_text": element.get("text", ""),
        "source_id": element.get("source_id", ""),
        "canonical_citation": element.get("canonical_citation", ""),
        "support_text": element.get("support_text", ""),
        "support_span": element.get("support_span", []),
        "source_span": element.get("source_span", []),
        "section_context": element.get("section_context", {}),
        "hierarchy_path": element.get("hierarchy_path", []),
        "hierarchy_details": element.get("hierarchy_details", []),
        "legal_frame": element.get("legal_frame", {}),
        "formal_terms": element.get("formal_terms", {}),
        "deontic_operator": element.get("deontic_operator", ""),
        "norm_type": element.get("norm_type", ""),
        "subject": element.get("subject", []),
        "action": element.get("action", []),
        "conditions": element.get("condition_details", []),
        "exceptions": element.get("exception_details", []),
        "temporal_constraints": element.get("temporal_constraint_details", []),
        "cross_references": element.get("cross_reference_details", []),
        "resolved_cross_references": element.get("resolved_cross_references", []),
        "enforcement_links": element.get("enforcement_links", []),
        "conflict_links": element.get("conflict_links", []),
        "defined_term_refs": element.get("defined_term_refs", []),
        "kg_relationship_hints": element.get("kg_relationship_hints", []),
        "ontology_terms": element.get("ontology_terms", []),
        "parser_warnings": reasons,
        "deterministically_resolved": bool(deterministic_resolution),
        "deterministic_resolution": deterministic_resolution,
    }
    prompt_hash = hashlib.sha256(
        json.dumps(prompt_context, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    return {
        "required": required,
        "reasons": reasons,
        "target_schema_version": PARSER_SCHEMA_VERSION,
        "suggested_router": "llm_router",
        "allow_llm_repair": required,
        "deterministically_resolved": bool(deterministic_resolution),
        "deterministic_resolution": deterministic_resolution,
        "prompt_template": "legal_deontic_parser_repair_v1",
        "prompt_hash": prompt_hash,
        "prompt_context": prompt_context,
    }


def build_logic_frame(element: Dict[str, Any]) -> Dict[str, Any]:
    """Build an intermediate representation for formal-logic exporters."""
    action_text = (element.get("action") or [""])[0]
    return {
        "schema_version": PARSER_SCHEMA_VERSION,
        "source_id": element.get("source_id", ""),
        "canonical_citation": element.get("canonical_citation", ""),
        "actor": (element.get("subject") or [""])[0],
        "actor_type": element.get("actor_type", "unknown"),
        "modality": element.get("deontic_operator", ""),
        "norm_type": element.get("norm_type", ""),
        "action_text": action_text,
        "action_predicate": normalize_predicate_name(_action_without_mental_state(action_text)),
        "object": element.get("action_object", ""),
        "recipient": element.get("action_recipient", ""),
        "conditions": element.get("condition_details", []),
        "exceptions": element.get("exception_details", []),
        "temporal_constraints": element.get("temporal_constraint_details", []),
        "cross_references": element.get("cross_reference_details", []),
        "resolved_cross_references": element.get("resolved_cross_references", []),
        "enforcement_links": element.get("enforcement_links", []),
        "conflict_links": element.get("conflict_links", []),
        "defined_terms": element.get("defined_term_refs", []),
        "violation": element.get("legal_frame", {}).get("category") == "violation",
        "penalty": element.get("penalty", {}),
        "procedure": element.get("procedure", {}),
        "formal_terms": element.get("formal_terms", {}),
        "field_spans": element.get("field_spans", {}),
        "source_text": element.get("text", ""),
        "readiness": {
            "schema_valid": element.get("schema_valid"),
            "parser_warnings": element.get("parser_warnings", []),
            "promotable_to_theorem": element.get("promotable_to_theorem", False),
        },
    }


def build_export_readiness(element: Dict[str, Any]) -> Dict[str, Any]:
    """Declare which downstream artifacts are safe from this parser element."""
    blockers = list(element.get("parser_warnings", []))
    if element.get("schema_valid") is False:
        blockers.append("schema_validation_failed")
    if element.get("llm_repair", {}).get("required"):
        blockers.append("llm_repair_required")
    blockers = list(dict.fromkeys(blockers))

    allowed_exports = ["canonical_parquet", "bm25", "embeddings", "knowledge_graph"]
    formal_logic_targets: List[str] = []
    requires_validation: List[str] = []
    has_temporal_or_procedure = bool(element.get("temporal_constraint_details") or element.get("procedure"))

    if element.get("schema_valid") is False:
        allowed_exports = []
        requires_validation.append("schema_repair")
    elif blockers:
        if has_temporal_or_procedure:
            formal_logic_targets = ["deontic", "fol", "frame_logic", "temporal_logic", "event_calculus"]
        allowed_exports.append("llm_repair_queue")
        requires_validation.extend(["llm_router_repair", "human_or_llm_semantic_review"])
    else:
        formal_logic_targets = ["deontic", "fol", "frame_logic"]
        if has_temporal_or_procedure:
            formal_logic_targets.append("temporal_logic")
            formal_logic_targets.append("event_calculus")
        allowed_exports.extend(["formal_logic_scaffold", "proof_candidate"])

    theorem_promotable = bool(
        element.get("promotable_to_theorem")
        and not blockers
        and element.get("schema_valid") is True
    )
    if not theorem_promotable and "human_or_llm_semantic_review" not in requires_validation:
        requires_validation.append("human_or_llm_semantic_review")

    return {
        "kg_ready": element.get("schema_valid") is True,
        "logic_ready": bool(formal_logic_targets),
        "proof_ready": theorem_promotable,
        "theorem_promotable": theorem_promotable,
        "allowed_exports": allowed_exports,
        "formal_logic_targets": formal_logic_targets,
        "blockers": blockers,
        "requires_validation": requires_validation,
        "source": "deterministic_parser",
    }


def infer_definition_scope(sentence: str) -> Dict[str, str]:
    text = str(sentence or "")
    lowered = text.lower()
    if re.search(r"\bas used in this (section|chapter|title)\b", lowered):
        match = re.search(r"\bas used in this (section|chapter|title)\b", lowered)
        return {"scope_type": match.group(1), "raw_text": match.group(0)}
    if re.search(r"\bin this section\b", lowered):
        return {"scope_type": "section", "raw_text": "in this section"}
    if re.search(r"\bin this chapter\b", lowered):
        return {"scope_type": "chapter", "raw_text": "in this chapter"}
    if re.search(r"\bin this title\b", lowered):
        return {"scope_type": "title", "raw_text": "in this title"}
    if re.search(r"\bfor purposes of this (section|chapter|title)\b", lowered):
        match = re.search(r"\bfor purposes of this (section|chapter|title)\b", lowered)
        return {"scope_type": match.group(1), "raw_text": match.group(0)}
    return {"scope_type": "unknown", "raw_text": ""}


def extract_ontology_terms(text: str) -> List[Dict[str, str]]:
    raw = str(text or "")
    terms: List[Dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    patterns = [
        (
            "government_actor",
            r"\b(?:Director|Bureau|City|Administrator|Commission|Council|Mayor|Department|Auditor|City\s+Attorney|City\s+Engineer|Code\s+Hearings\s+Officer|Hearings\s+Officer)\b",
        ),
        (
            "legal_person",
            r"\b(?:applicant|person|owner|tenant|employee|contractor|resident|permittee|licensee|operator|vendor)\b",
        ),
        (
            "legal_instrument",
            r"\b(?:permit|license|certificate|registration|approval|variance|franchise|easement|order)\b",
        ),
        (
            "legal_event",
            r"\b(?:notice|hearing|decision|appeal|inspection|violation|penalty|fee|citation|complaint|review|revocation|suspension)\b",
        ),
        (
            "regulated_property",
            r"\b(?:premises|sidewalk|street|vehicle|building|facility|property|right-of-way|right\s+of\s+way|sewer|tree|park)\b",
        ),
        (
            "regulated_activity",
            r"\b(?:operate|file|submit|inspect|revoke|suspend|issue|appeal|maintain|remove|install|construct)\b",
        ),
    ]
    for term_type, pattern in patterns:
        for match in re.finditer(pattern, raw, flags=re.IGNORECASE):
            value = match.group(0)
            key = (term_type, value.lower())
            if key in seen:
                continue
            seen.add(key)
            terms.append({"term": value, "type": term_type, "span": [match.start(), match.end()]})
    return terms


def merge_ontology_terms(
    existing_terms: List[Dict[str, Any]],
    defined_refs: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    merged = list(existing_terms or [])
    seen = {(str(item.get("term", "")).lower(), str(item.get("type", ""))) for item in merged}
    for ref in defined_refs:
        key = (str(ref.get("term", "")).lower(), "defined_term")
        if key in seen:
            continue
        seen.add(key)
        merged.append(
            {
                "term": ref.get("term", ""),
                "type": "defined_term",
                "definition_body": ref.get("definition_body", ""),
                "span": ref.get("span", []),
            }
        )
    return merged


def _enrich_legal_frame(element: Dict[str, Any]) -> None:
    text = str(element.get("text") or "")
    action = (element.get("action") or [""])[0]
    subject = (element.get("subject") or [""])[0]
    category = classify_legal_frame(element)
    element["legal_frame"] = {
        "source_id": element.get("source_id", ""),
        "canonical_citation": element.get("canonical_citation", ""),
        "category": category,
        "actor": subject,
        "actor_id": normalize_symbol(subject),
        "actor_type": element.get("actor_type", "unknown"),
        "action": action,
        "action_predicate": normalize_predicate_name(_action_without_mental_state(action)),
        "object": element.get("action_object", ""),
        "recipient": element.get("action_recipient", ""),
        "norm_type": element.get("norm_type", ""),
        "deontic_operator": element.get("deontic_operator", ""),
    }
    element["monetary_amounts"] = extract_monetary_amounts(text)
    element["monetary_amount_details"] = extract_monetary_amount_details(text)
    existing_penalty = element.get("penalty") or {}
    penalty = extract_penalty_details(text, action)
    if existing_penalty.get("recurrence") and not penalty.get("recurrence"):
        penalty["recurrence"] = existing_penalty["recurrence"]
    element["penalty"] = penalty
    element["procedure"] = extract_procedure_details(text, action)
    element["kg_relationship_hints"] = build_kg_relationship_hints(element)


def classify_legal_frame(element: Dict[str, Any]) -> str:
    text = str(element.get("text") or "").lower()
    action = " ".join(element.get("action", [])).lower()
    norm_type = element.get("norm_type")
    subject = " ".join(element.get("subject", [])).lower()
    if norm_type == "applicability":
        return "applicability"
    if norm_type == "exemption":
        return "exemption"
    if norm_type == "instrument_lifecycle":
        return "instrument_lifecycle"
    if norm_type == "definition":
        return "definition"
    if norm_type == "penalty" or "punishable" in text or "fine" in text or "penalty" in text:
        return "penalty"
    if norm_type == "violation" or "violation" in text or "offense" in text or "infraction" in text:
        return "violation"
    if element.get("entity_type") == "legal_event" and subject in _LEGAL_EVENT_ENTITIES:
        return "procedure"
    if re.search(r"\b(?:appeal|appealed|hearing|notice|decision|inspect|inspection|revoke|revocation|suspend|suspension)\b", action):
        return "procedure"
    if subject in _LEGAL_INSTRUMENT_ENTITIES or any(term in text for term in ["permit", "license", "certificate", "registration"]):
        return "permit_or_license"
    if extract_legal_instrument_target(action):
        return "permit_or_license"
    if "fee" in text or element.get("monetary_amounts"):
        return "fee"
    if action.startswith(("file", "submit", "apply", "provide")):
        return "filing_requirement"
    return "norm"


def extract_monetary_amounts(text: str) -> List[Dict[str, str]]:
    amounts: List[Dict[str, str]] = []
    for match in _MONEY_RE.finditer(str(text or "")):
        amounts.append({"raw_text": match.group(0).strip(), "span": [match.start(), match.end()]})
    return amounts


def extract_monetary_amount_details(text: str) -> List[Dict[str, Any]]:
    details: List[Dict[str, Any]] = []
    for match in _MONEY_RE.finditer(str(text or "")):
        raw_text = match.group(0).strip()
        numeric = re.sub(r"[^\d.]", "", raw_text)
        details.append(
            {
                "type": "money",
                "raw_text": raw_text,
                "normalized_text": raw_text.lower(),
                "numeric_value": numeric,
                "currency": "USD" if "$" in raw_text or "dollar" in raw_text.lower() else "",
                "span": [match.start(), match.end()],
            }
        )
    return details


def extract_penalty_details(text: str, action: str = "") -> Dict[str, Any]:
    combined = f"{text} {action}".strip()
    lower = combined.lower()
    if not any(term in lower for term in ["fine", "penalty", "punishable", "imprison", "violation", "offense", "infraction"]):
        return {}
    amounts = extract_monetary_amount_details(combined)
    minimum_amount = _penalty_bound(combined, "minimum")
    maximum_amount = _penalty_bound(combined, "maximum")
    return {
        "raw_text": combined,
        "sanction_class": classify_sanction_class(combined),
        "sanction_modality": classify_sanction_modality(combined),
        "monetary_amounts": extract_monetary_amounts(combined),
        "monetary_amount_details": amounts,
        "minimum_amount": minimum_amount,
        "maximum_amount": maximum_amount,
        "has_range": bool(minimum_amount and maximum_amount),
        "recurrence": extract_penalty_recurrence(combined),
        "imprisonment_duration": extract_imprisonment_duration(combined),
        "has_imprisonment": bool(re.search(r"\b(?:jail|imprison|imprisonment|custody)\b", lower)),
        "has_fine": "fine" in lower or bool(amounts),
    }


def classify_sanction_class(text: str) -> str:
    lower = str(text or "").lower()
    if re.search(r"\bcriminal\s+(?:fine|penalty|offense|violation|sanction)\b", lower):
        return "criminal"
    if re.search(r"\bcivil\s+(?:fine|penalty|violation|infraction|sanction)\b", lower):
        return "civil"
    if re.search(r"\badministrative\s+(?:fine|penalty|sanction|citation)\b", lower):
        return "administrative"
    if re.search(r"\bimprison|jail|custody\b", lower):
        return "criminal"
    return ""


def classify_sanction_modality(text: str) -> str:
    lower = str(text or "").lower()
    if re.search(r"\bmay\s+(?:be\s+)?(?:impose|imposed|punish|punished|fine|fined|assess|assessed)\b", lower):
        return "discretionary"
    if re.search(r"\b(?:is|shall\s+be)\s+(?:punishable\s+by|subject\s+to)\b", lower):
        return "mandatory"
    if re.search(r"\bmust\s+(?:pay|serve)\b", lower):
        return "mandatory"
    return ""


def _penalty_bound(text: str, bound: str) -> Dict[str, Any]:
    if bound == "minimum":
        pattern = r"\b(?:not\s+less\s+than|minimum(?:\s+of)?)\s+(\$\s?\d[\d,]*(?:\.\d{2})?|\d[\d,]*\s+dollars?)"
    else:
        pattern = r"\b(?:not\s+more\s+than|maximum(?:\s+of)?|up\s+to)\s+(\$\s?\d[\d,]*(?:\.\d{2})?|\d[\d,]*\s+dollars?)"
    match = re.search(pattern, text, flags=re.IGNORECASE)
    if not match:
        return {}
    raw_text = match.group(1).strip()
    return {
        "raw_text": raw_text,
        "numeric_value": re.sub(r"[^\d.]", "", raw_text),
        "currency": "USD" if "$" in raw_text or "dollar" in raw_text.lower() else "",
        "span": [match.start(1), match.end(1)],
    }


def extract_penalty_recurrence(text: str) -> Dict[str, Any]:
    patterns = [
        ("per_day", r"\b(?:each|every)\s+day\s+(?:constitutes|is)\s+(?:a\s+)?separate\s+violation\b"),
        ("per_violation", r"\b(?:per|for each)\s+violation\b"),
        ("per_offense", r"\b(?:per|for each)\s+offense\b"),
    ]
    for recurrence_type, pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return {
                "type": recurrence_type,
                "raw_text": match.group(0),
                "span": [match.start(), match.end()],
            }
    return {}


def extract_imprisonment_duration(text: str) -> Dict[str, Any]:
    pattern = r"\b(?:imprisonment|jail|custody)\s+(?:for\s+)?(?:a\s+term\s+of\s+)?(?:not\s+more\s+than|up\s+to|for)?\s*(\d+)\s+(days?|months?|years?)\b"
    match = re.search(pattern, str(text or ""), flags=re.IGNORECASE)
    if not match:
        return {}
    return {
        "raw_text": match.group(0).strip(),
        "quantity": int(match.group(1)),
        "unit": match.group(2).lower().rstrip("s"),
        "span": [match.start(), match.end()],
    }


def extract_procedure_details(text: str, action: str = "") -> Dict[str, Any]:
    combined = f"{text} {action}".strip()
    lower = combined.lower()
    events = [
        event
        for event in _PROCEDURE_EVENT_ORDER
        if re.search(_PROCEDURE_EVENT_PATTERNS[event], lower)
    ]
    if not events:
        return {}
    event_mentions = extract_procedure_event_mentions(combined)
    event_relations = extract_procedure_event_relations(combined, action, events)
    return {
        "events": events,
        "event_chain": [
            {
                "event": event,
                "order": index + 1,
                "mentions": [mention for mention in event_mentions if mention.get("event") == event],
                "relations": [
                    relation
                    for relation in event_relations
                    if relation.get("event") == event or relation.get("anchor_event") == event
                ],
            }
            for index, event in enumerate(events)
        ],
        "event_mentions": event_mentions,
        "event_relations": event_relations,
        "trigger_event": _infer_trigger_event(events, event_relations),
        "terminal_event": _infer_terminal_event(events, event_relations),
        "raw_text": combined,
    }


def extract_procedure_event_mentions(text: str) -> List[Dict[str, Any]]:
    mentions: List[Dict[str, Any]] = []
    seen: set[tuple[str, int, int]] = set()
    for event in _PROCEDURE_EVENT_ORDER:
        pattern = _PROCEDURE_EVENT_PATTERNS[event]
        for match in re.finditer(pattern, str(text or ""), flags=re.IGNORECASE):
            key = (event, match.start(), match.end())
            if key in seen:
                continue
            seen.add(key)
            mentions.append(
                {
                    "event": event,
                    "raw_text": match.group(0),
                    "span": [match.start(), match.end()],
                }
            )
    return sorted(mentions, key=lambda item: (item["span"][0], _PROCEDURE_EVENT_ORDER.index(item["event"])))


def extract_procedure_event_relations(text: str, action: str = "", events: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """Extract deterministic event ordering relations from procedural connectors."""
    combined = str(text or "")
    known_events = events or [
        event
        for event in _PROCEDURE_EVENT_ORDER
        if re.search(_PROCEDURE_EVENT_PATTERNS[event], combined, flags=re.IGNORECASE)
    ]
    action_event = _infer_event_from_phrase(action) or (known_events[-1] if known_events else "")
    relations: List[Dict[str, Any]] = []

    def add_relation(event: str, relation: str, anchor_event: str, match: re.Match[str], raw_text: str = "") -> None:
        if not event and not anchor_event:
            return
        relation_record = {
            "event": event,
            "relation": relation,
            "anchor_event": anchor_event,
            "raw_text": (raw_text or match.group(0)).strip(),
            "span": [match.start(), match.end()],
        }
        if relation_record not in relations:
            relations.append(relation_record)

    for match in re.finditer(r"\bupon\s+receipt\s+of\s+(?P<object>[^,.;]+)", combined, flags=re.IGNORECASE):
        anchor_event = _infer_event_from_phrase(match.group("object")) or "receipt"
        add_relation(action_event, "triggered_by_receipt_of", anchor_event, match)
        add_relation("receipt", "receives", anchor_event, match)

    for match in re.finditer(r"\bafter\s+(?P<events>[^,.;]+?)(?=\s+(?:and\s+)?(?:shall|must|may|before|within)\b|[,.;]|$)", combined, flags=re.IGNORECASE):
        for anchor_event in _events_from_phrase(match.group("events")):
            add_relation(action_event, "after", anchor_event, match)

    for match in re.finditer(r"\bbefore\s+(?P<events>[^,.;]+?)(?=\s+(?:and\s+)?(?:shall|must|may|after|within)\b|[,.;]|$)", combined, flags=re.IGNORECASE):
        for anchor_event in _events_from_phrase(match.group("events")):
            add_relation(action_event, "before", anchor_event, match)

    return relations


def _infer_trigger_event(events: List[str], relations: List[Dict[str, Any]]) -> str:
    for relation in relations:
        if relation.get("relation") in {"triggered_by_receipt_of", "after"} and relation.get("anchor_event") in events:
            return relation["anchor_event"]
    return events[0] if events else ""


def _infer_terminal_event(events: List[str], relations: List[Dict[str, Any]]) -> str:
    before_events = [relation.get("anchor_event") for relation in relations if relation.get("relation") == "before"]
    for event in reversed(events):
        if event not in before_events:
            return event
    return events[-1] if events else ""


def _events_from_phrase(phrase: str) -> List[str]:
    events = []
    for part in re.split(r"\s*(?:,|and|or)\s*", str(phrase or "")):
        event = _infer_event_from_phrase(part)
        if event and event not in events:
            events.append(event)
    return events


def _infer_event_from_phrase(phrase: str) -> str:
    normalized = str(phrase or "").lower()
    aliases = {
        "approval": "issuance",
        "approve": "issuance",
        "grant": "issuance",
        "receipt": "receipt",
        "receive": "receipt",
        "received": "receipt",
    }
    for token, event in aliases.items():
        if re.search(rf"\b{re.escape(token)}\b", normalized):
            return event
    for event in _PROCEDURE_EVENT_ORDER:
        if re.search(_PROCEDURE_EVENT_PATTERNS[event], normalized):
            return event
    return ""


def build_kg_relationship_hints(element: Dict[str, Any]) -> List[Dict[str, str]]:
    subject = (element.get("subject") or [""])[0]
    action = (element.get("action") or [""])[0]
    category = (element.get("legal_frame") or {}).get("category", "")
    instrument_target = extract_legal_instrument_target(action)
    relationships: List[Dict[str, str]] = []
    if subject and action:
        predicate = {
            "obligation": "imposesDutyOn",
            "permission": "authorizes",
            "prohibition": "prohibits",
            "violation": "definesViolationFor",
            "penalty": "createsPenaltyFor",
            "definition": "definesTerm",
            "applicability": "appliesTo",
            "exemption": "exemptsFrom",
            "instrument_lifecycle": "setsLifecycleFor",
        }.get(element.get("norm_type"), "regulates")
        relationships.append({"subject": "law", "predicate": predicate, "object": subject})
        relationships.append({"subject": subject, "predicate": "performsAction", "object": action})
    if category == "instrument_lifecycle" and subject:
        relationships.append({"subject": "law", "predicate": "setsLifecycleFor", "object": subject})
    if category == "permit_or_license" and action:
        relationships.append(
            {
                "subject": action,
                "predicate": "requiresLegalInstrument",
                "object": instrument_target or subject,
            }
        )
    if element.get("action_recipient"):
        relationships.append({"subject": subject, "predicate": "directedTo", "object": element["action_recipient"]})
    procedure = element.get("procedure") or {}
    events = set(procedure.get("events") or [])
    if "notice" in events:
        relationships.append({"subject": subject, "predicate": "providesNoticeTo", "object": element.get("action_recipient") or action})
    if "hearing" in events:
        relationships.append({"subject": subject, "predicate": "holdsHearingFor", "object": element.get("action_recipient") or action})
    if "decision" in events:
        relationships.append({"subject": subject, "predicate": "issuesDecision", "object": action})
    if "appeal" in events:
        relationships.append({"subject": action or subject, "predicate": "mayAppealDecision", "object": subject})
    if "inspection" in events:
        relationships.append({"subject": subject, "predicate": "mayInspect", "object": element.get("action_object") or action})
    if "revocation" in events:
        relationships.append({"subject": subject, "predicate": "mayRevokeInstrument", "object": instrument_target or element.get("action_object") or action})
    if "suspension" in events:
        relationships.append({"subject": subject, "predicate": "maySuspendInstrument", "object": instrument_target or element.get("action_object") or action})
    for link in element.get("enforcement_links", []):
        if link.get("type") == "defines_violation_of":
            relationships.append(
                {
                    "subject": "violation",
                    "predicate": "violatesSection",
                    "object": link.get("target_section", ""),
                }
            )
        if link.get("type") == "penalizes_violation_of":
            relationships.append(
                {
                    "subject": "penalty",
                    "predicate": "penalizesViolationOf",
                    "object": link.get("target_section", ""),
                }
            )
    for ref in element.get("defined_term_refs", []):
        relationships.append(
            {
                "subject": ref.get("term", ""),
                "predicate": "definedBy",
                "object": ref.get("definition_body") or ref.get("definition_text", ""),
            }
        )
    resolved_refs = element.get("resolved_cross_references") or []
    if resolved_refs:
        for ref in resolved_refs:
            if ref.get("type") == "section_range":
                predicate = "referencesResolvedSectionRange" if ref.get("resolution_status") == "resolved" else "referencesUnresolvedSectionRange"
                relationships.append({"subject": "law", "predicate": predicate, "object": ref.get("value", "")})
                continue
            target = ref.get("target_section") or ref.get("value", "")
            predicate = "referencesResolvedSection" if ref.get("resolution_status") == "resolved" else "referencesUnresolvedSection"
            relationships.append({"subject": "law", "predicate": predicate, "object": f"{ref.get('type')}:{target}"})
    else:
        for ref in element.get("cross_references", []):
            relationships.append({"subject": "law", "predicate": "references", "object": f"{ref.get('type')}:{ref.get('value')}"})
    for amount in element.get("monetary_amounts", []):
        relationships.append({"subject": "law", "predicate": "mentionsAmount", "object": amount.get("raw_text", "")})
    return relationships


def build_kg_triples(element: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Convert KG relationship hints into parquet-friendly triple rows."""
    triples: List[Dict[str, Any]] = []
    source_id = element.get("source_id") or build_source_id(element)
    citation = element.get("canonical_citation") or build_canonical_citation(element)
    for index, relationship in enumerate(element.get("kg_relationship_hints") or []):
        subject = relationship.get("subject", "")
        predicate = relationship.get("predicate", "")
        object_value = relationship.get("object", "")
        triple_identity = {
            "source_id": source_id,
            "index": index,
            "subject": subject,
            "predicate": predicate,
            "object": object_value,
        }
        triple_hash = hashlib.sha256(
            json.dumps(triple_identity, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        triples.append(
            {
                "triple_id": f"kg:{triple_hash[:24]}",
                "source_id": source_id,
                "canonical_citation": citation,
                "subject": subject,
                "subject_id": normalize_symbol(subject),
                "predicate": predicate,
                "predicate_id": normalize_symbol(predicate),
                "object": object_value,
                "object_id": normalize_symbol(object_value),
                "norm_type": element.get("norm_type", ""),
                "legal_category": (element.get("legal_frame") or {}).get("category", ""),
                "confidence_floor": element.get("confidence_floor", 0.0),
                "provenance": {
                    "text": element.get("text", ""),
                    "source_span": element.get("source_span", []),
                    "support_span": element.get("support_span", []),
                    "field_spans": element.get("field_spans", {}),
                },
            }
        )
    return triples


def extract_legal_instrument_target(action: str) -> str:
    match = re.search(
        r"\b(?:permit|license|certificate|registration|approval|variance|franchise|easement|order)\b",
        str(action or ""),
        flags=re.IGNORECASE,
    )
    return match.group(0).lower() if match else ""


def classify_modal(modal: str) -> tuple[str, str]:
    modal = re.sub(r"\s+", " ", str(modal or "").lower()).strip()
    # Prohibitions must be checked before bare "shall"/"must"/"may".
    if modal in {
        "shall not",
        "must not",
        "may not",
        "cannot",
        "can not",
        "is prohibited from",
        "are prohibited from",
        "is forbidden to",
        "are forbidden to",
    }:
        return "prohibition", "F"
    if modal in {
        "may",
        "is authorized to",
        "are authorized to",
        "is permitted to",
        "are permitted to",
        "is entitled to",
        "are entitled to",
    }:
        return "permission", "P"
    return "obligation", "O"


def _clean_phrase(value: str) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip(" ,;:")
    text = _LEADING_DETERMINERS_RE.sub("", text).strip()
    return text


def _clean_action(value: str) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip(" ,;:")
    text = _TRAILING_NOISE_RE.sub("", text).strip()
    return text


def _first_verb(action: str) -> str:
    words = re.findall(r"[A-Za-z][A-Za-z0-9'’\-]*", action or "")
    while words and words[0].lower() in _MENTAL_STATE_TERMS:
        words = words[1:]
    return words[0].lower() if words else ""


def _action_object(action: str) -> str:
    words = re.findall(r"[A-Za-z][A-Za-z0-9'’\-]*", action or "")
    while words and words[0].lower() in _MENTAL_STATE_TERMS:
        words = words[1:]
    return " ".join(words[1:]).strip() if len(words) > 1 else ""


def _mental_state(action: str) -> str:
    words = re.findall(r"[A-Za-z][A-Za-z0-9'’\-]*", action or "")
    if words and words[0].lower() in _MENTAL_STATE_TERMS:
        return words[0].lower()
    return ""


def _action_without_mental_state(action: str) -> str:
    words = re.findall(r"[A-Za-z][A-Za-z0-9'’\-]*", action or "")
    if words and words[0].lower() in _MENTAL_STATE_TERMS:
        return " ".join(words[1:]).strip()
    return action


def _normalize_passive_clause(subject_text: str, action_text: str) -> tuple[str, str]:
    match = _PASSIVE_BY_RE.match(action_text or "")
    if not match:
        return subject_text, action_text
    participle = match.group(1).lower()
    agent = _clean_phrase(match.group(2))
    verb = _PAST_PARTICIPLE_BASE.get(participle)
    if not verb:
        verb = re.sub(r"ied$", "y", participle)
        verb = re.sub(r"ed$", "", verb)
    object_text = _clean_phrase(subject_text)
    normalized_action = f"{verb} {object_text}".strip()
    return agent or subject_text, normalized_action


def classify_legal_entity(text: str) -> str:
    """Return a coarse actor/entity type for KG and frame-logic scaffolds."""
    normalized = re.sub(r"[^A-Za-z0-9\s]", " ", str(text or "").lower())
    tokens = set(normalized.split())
    if not tokens:
        return "unknown"
    if tokens & _GOVERNMENT_ACTORS:
        return "government_actor"
    if tokens & _ORGANIZATION_ACTORS:
        return "organization"
    if tokens & _LEGAL_PERSON_ACTORS:
        return "legal_person"
    if tokens & _LEGAL_INSTRUMENT_ENTITIES:
        return "legal_instrument"
    if tokens & _LEGAL_EVENT_ENTITIES:
        return "legal_event"
    if tokens & _PROPERTY_ENTITIES:
        return "regulated_property"
    if any(token.endswith("office") or token.endswith("board") for token in tokens):
        return "government_actor"
    return "legal_entity"


def extract_action_recipient(action: str) -> str:
    """Extract a likely beneficiary/recipient from an action phrase."""
    match = _RECIPIENT_RE.search(str(action or "").strip())
    if not match:
        return ""
    recipient = _clean_phrase(match.group(1))
    if recipient.lower() in {
        "law",
        "regulation",
        "section",
        "chapter",
        "title",
        "this section",
        "this chapter",
        "this title",
    }:
        return ""
    return recipient


def extract_definition_body(sentence: str) -> str:
    match = _DEFINITION_BODY_RE.search(str(sentence or "").strip())
    if not match:
        return ""
    return match.group(1).strip(" .;:")


def score_scaffold_quality(element: Dict[str, Any]) -> Dict[str, Any]:
    """Score whether a deterministic parse is safe to promote without LLM repair."""
    warnings: List[str] = []
    norm_type = element.get("norm_type")
    subjects = [item for item in element.get("subject", []) if item]
    actions = [item for item in element.get("action", []) if item]
    action_text = actions[0] if actions else ""

    required_slots = ["deontic_operator", "subject", "action"]
    if norm_type == "definition":
        required_slots = ["defined_term", "definition_body"]

    filled_slots = 0
    for slot in required_slots:
        value = element.get(slot)
        if slot == "subject":
            value = subjects
        elif slot == "action":
            value = actions
        if value:
            filled_slots += 1
        else:
            warnings.append(f"missing_{slot}")

    slot_coverage = filled_slots / len(required_slots) if required_slots else 0.0
    score = 0.25 + (0.55 * slot_coverage)

    if element.get("conditions"):
        score += 0.04
    if element.get("temporal_constraints"):
        score += 0.04
    if element.get("action_recipient"):
        score += 0.03
    if element.get("actor_type") in {"government_actor", "legal_person", "organization"}:
        score += 0.03

    if element.get("enumerated_items"):
        warnings.append("enumerated_clause_requires_item_level_review")
        score -= 0.10
    if _unresolved_cross_references(element):
        warnings.append("cross_reference_requires_resolution")
        score -= 0.04
    if element.get("conflict_links"):
        warnings.append("normative_conflict_requires_resolution")
        score -= 0.12
    if element.get("exceptions"):
        warnings.append("exception_requires_scope_review")
        score -= 0.05
    if element.get("override_clauses"):
        warnings.append("override_clause_requires_precedence_review")
        score -= 0.05
    if (element.get("legal_frame") or {}).get("category") == "penalty" and not element.get("penalty"):
        warnings.append("penalty_requires_amount_or_sanction_review")
        score -= 0.05
    if (element.get("legal_frame") or {}).get("category") == "procedure" and element.get("temporal_constraints"):
        warnings.append("procedure_timeline_requires_event_order_review")
        score -= 0.04
    if len(re.findall(r"[A-Za-z][A-Za-z0-9'’\-]*", action_text)) > 18:
        warnings.append("overlong_action_span")
        score -= 0.10
    if norm_type == "definition" and not element.get("defined_term"):
        warnings.append("definition_term_uncertain")
        score -= 0.10

    score = max(0.0, min(score, 0.95))
    # Promotion here means "safe to use as a deterministic theorem scaffold
    # without LLM repair"; any warning should keep it in the review lane.
    promotable = score >= 0.70 and not warnings
    if score >= 0.75:
        label = "high"
    elif score >= 0.50:
        label = "medium"
    else:
        label = "low"

    return {
        "score": round(score, 3),
        "label": label,
        "slot_coverage": round(slot_coverage, 3),
        "warnings": warnings,
        "promotable_to_theorem": promotable,
    }


def extract_legal_subject(sentence: str) -> List[str]:
    subjects: List[str] = []

    subject_patterns = [
        r"\b(?:citizens?|residents?|persons?|individuals?|people)\b",
        r"\b(?:companies?|corporations?|businesses?|entities?)\b",
        r"\b(?:developers?|operators?|providers?|controllers?|processors?)\b",
        r"\b(?:systems?|services?|platforms?|applications?|software)\b",
        r"\b(?:employees?|workers?|staff)\b",
        r"\b(?:drivers?|operators?|users?)\b",
        r"\b(?:owners?|lessees?|tenants?)\b",
        r"\b(?:students?|minors?|adults?)\b",
        r"\b(?:patients?|clients?|customers?)\b",
    ]

    for pattern in subject_patterns:
        subjects.extend(re.findall(pattern, sentence.lower()))

    capitalized_words = re.findall(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b", sentence)
    subjects.extend(capitalized_words[:2])

    acronyms = re.findall(r"\b[A-Z]{2,}\b", sentence)
    subjects.extend(acronyms[:2])
    acronym_phrases = re.findall(r"\b[A-Z]{2,}\s+[a-z]+(?:\s+[a-z]+)*\b", sentence)
    subjects.extend(acronym_phrases[:2])

    return list(set(subjects))


def extract_legal_action(sentence: str) -> List[str]:
    actions: List[str] = []

    modal_verb_pattern = (
        r"(?:must|shall|may|can|cannot|must not|shall not)\s+(?:not\s+)?(\w+(?:\s+\w+)*?)(?:\s+(?:by|before|after|until|unless|except)|\.|$)"
    )
    actions.extend([m.strip() for m in re.findall(modal_verb_pattern, sentence.lower())])

    prohibited_pattern = (
        r"(?:prohibited from|prohibited to|forbidden to)\s+([^.]+?)(?:\s+(?:by|before|after|until|unless|except)|\.|$)"
    )
    actions.extend([m.strip() for m in re.findall(prohibited_pattern, sentence.lower())])

    legal_action_patterns = [
        r"\b(?:pay|file|submit|provide|deliver|execute|perform)\s+([^.]+?)(?:\s+(?:by|before|after)|\.|$)",
        r"\b(?:comply with|adhere to|follow|observe)\s+([^.]+?)(?:\s+(?:by|before|after)|\.|$)",
        r"\b(?:obtain|acquire|secure|maintain)\s+([^.]+?)(?:\s+(?:by|before|after)|\.|$)",
    ]
    for pattern in legal_action_patterns:
        actions.extend([m.strip() for m in re.findall(pattern, sentence.lower())])

    return list(set(actions))


def extract_conditions(sentence: str) -> List[str]:
    return [item["normalized_text"] for item in extract_condition_details(sentence)]


def extract_condition_details(sentence: str) -> List[Dict[str, Any]]:
    return _extract_clause_details(sentence, _CONDITION_PATTERNS, "condition")


def extract_override_clauses(sentence: str) -> List[str]:
    return [item["normalized_text"] for item in extract_override_clause_details(sentence)]


def extract_override_clause_details(sentence: str) -> List[Dict[str, Any]]:
    return _extract_clause_details(sentence, _OVERRIDE_PATTERNS, "override")


def extract_cross_references(sentence: str) -> List[Dict[str, str]]:
    return [{"type": item["type"], "value": item["value"]} for item in extract_cross_reference_details(sentence)]


def extract_cross_reference_details(sentence: str) -> List[Dict[str, Any]]:
    refs: List[Dict[str, Any]] = []
    patterns = [
        ("section_range", r"\bsections?\s+([0-9][0-9A-Za-z.\-]*(?:\([a-z0-9]+\))*)\s+(?:through|thru|to|-)\s+([0-9][0-9A-Za-z.\-]*(?:\([a-z0-9]+\))*)"),
        ("section", r"\bsection\s+([0-9][0-9A-Za-z.\-]*(?:\([a-z0-9]+\))*)"),
        ("section", r"§\s*([0-9][0-9A-Za-z.\-]*(?:\([a-z0-9]+\))*)"),
        ("section", r"\b(this\s+section)\b"),
        ("subsection", r"\bsubsection\s+\(([a-z0-9]+)\)"),
        ("subsection", r"\b(this\s+subsection)\b"),
        ("paragraph", r"\bparagraph\s+\(([a-z0-9]+)\)"),
        ("paragraph", r"\b(this\s+paragraph)\b"),
        ("chapter", r"\bchapter\s+([0-9A-Za-z][0-9A-Za-z.\-]*)"),
        ("chapter", r"\b(this\s+chapter)\b"),
        ("title", r"\btitle\s+([0-9A-Za-z]+)"),
        ("title", r"\b(this\s+title)\b"),
        ("usc", r"\b(\d+)\s+u\.?s\.?c\.?\s+(?:§|sec(?:tion)?\.?)?\s*([0-9A-Za-z.\-]+)"),
    ]
    seen: set[tuple[str, str]] = set()
    for ref_type, pattern in patterns:
        for match in re.finditer(pattern, sentence, flags=re.IGNORECASE):
            if _is_definition_scope_marker(sentence, match):
                continue
            if ref_type == "section_range":
                start_section = str(match.group(1) or "").strip().lower()
                end_section = str(match.group(2) or "").strip().lower()
                value = f"{start_section}-{end_section}"
            elif len(match.groups()) > 1:
                value = " ".join(part for part in match.groups() if part).strip().lower()
            else:
                value = str(match.group(1) or "").strip().lower()
            if not value:
                continue
            key = (ref_type, value)
            if key in seen:
                continue
            seen.add(key)
            refs.append(
                {
                    "type": ref_type,
                    "value": value,
                    "raw_text": match.group(0).strip(),
                    "normalized_text": f"{ref_type} {value}",
                    "span": [match.start(), match.end()],
                }
            )
            if ref_type == "section_range":
                refs[-1]["start_section"] = start_section
                refs[-1]["end_section"] = end_section
    return refs


def _is_definition_scope_marker(sentence: str, match: re.Match[str]) -> bool:
    raw = match.group(0).lower()
    if not raw.startswith("this "):
        return False
    prefix = str(sentence or "")[: match.start()].lower()
    return bool(re.search(r"(?:\bin\s+|\bfor\s+purposes\s+of\s+)$", prefix))


def extract_enumerated_items(sentence: str) -> List[Dict[str, str]]:
    items: List[Dict[str, str]] = []
    matches = list(re.finditer(r"(?:^|\s)\(([A-Za-z0-9]+)\)\s+", sentence))
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(sentence)
        text = sentence[start:end].strip(" ;,.")
        text = re.sub(r"\s+(?:and|or)$", "", text, flags=re.IGNORECASE).strip(" ;,.")
        if text:
            items.append({"label": match.group(1), "text": text})
    return items


def extract_temporal_constraints(sentence: str) -> List[Dict[str, str]]:
    return [
        {"type": item["type"], "value": item["value"]}
        for item in extract_temporal_constraint_details(sentence)
    ]


def extract_temporal_constraint_details(sentence: str) -> List[Dict[str, Any]]:
    details: List[Dict[str, Any]] = []
    seen: set[tuple[str, str, int, int]] = set()
    for constraint_type, temporal_kind, pattern in _TEMPORAL_PATTERNS:
        for match in re.finditer(pattern, sentence, flags=re.IGNORECASE):
            value = match.group(1).strip().lower()
            anchor = ""
            if " after " in value:
                value_part, anchor_part = value.split(" after ", 1)
                anchor = anchor_part.strip()
                value = f"{value_part.strip()} after {anchor}"
            key = (constraint_type, value, match.start(), match.end())
            if key in seen:
                continue
            seen.add(key)
            details.append(
                {
                    "type": constraint_type,
                    "temporal_kind": temporal_kind,
                    "value": value,
                    "anchor": anchor,
                    **normalize_temporal_value(value),
                    "raw_text": match.group(0).strip(),
                    "normalized_text": value,
                    "span": [match.start(), match.end()],
                }
            )
    return details


def normalize_temporal_value(value: str) -> Dict[str, Any]:
    """Normalize a temporal phrase into atoms useful for temporal logic export."""
    normalized = str(value or "").strip().lower()
    duration = normalized.split(" after ", 1)[0].split(" before ", 1)[0].strip()
    match = re.match(r"(?P<quantity>\d+)\s+(?:(?P<calendar>business|calendar)\s+)?(?P<unit>days?|weeks?|months?|years?)\b", duration)
    anchor_event = ""
    direction = ""
    if " after " in normalized:
        anchor_event = normalized.split(" after ", 1)[1].strip()
        direction = "after"
    elif " before " in normalized:
        anchor_event = normalized.split(" before ", 1)[1].strip()
        direction = "before"
    if not match:
        return {
            "quantity": None,
            "unit": "",
            "calendar": "",
            "anchor_event": anchor_event,
            "direction": direction,
        }
    return {
        "quantity": int(match.group("quantity")),
        "unit": match.group("unit").rstrip("s"),
        "calendar": match.group("calendar") or "calendar",
        "anchor_event": anchor_event,
        "direction": direction,
    }


def extract_exceptions(sentence: str) -> List[str]:
    return [item["normalized_text"] for item in extract_exception_details(sentence)]


def extract_exception_details(sentence: str) -> List[Dict[str, Any]]:
    return _extract_clause_details(sentence, _EXCEPTION_PATTERNS, "exception")


def _extract_clause_details(
    sentence: str,
    patterns: List[tuple[str, str]],
    slot_type: str,
) -> List[Dict[str, Any]]:
    details: List[Dict[str, Any]] = []
    seen: set[tuple[str, str, int, int]] = set()
    for clause_type, pattern in patterns:
        for match in re.finditer(pattern, sentence, flags=re.IGNORECASE):
            value = match.group(1).strip()
            normalized = value.lower()
            key = (clause_type, normalized, match.start(1), match.end(1))
            if key in seen:
                continue
            seen.add(key)
            details.append(
                {
                    "type": slot_type,
                    "clause_type": clause_type,
                    "raw_text": value,
                    "normalized_text": normalized,
                    "span": [match.start(1), match.end(1)],
                    "clause_span": [match.start(), match.end()],
                }
            )
    return details


def build_formal_logic_record(element: Dict[str, Any]) -> Dict[str, Any]:
    """Build a single parquet-friendly row for formal-logic/proof pipelines."""
    source_id = element.get("source_id") or build_source_id(element)
    formula = build_deontic_formula(element)
    identity = {
        "source_id": source_id,
        "formula": formula,
        "schema": PARSER_SCHEMA_VERSION,
    }
    formula_hash = hashlib.sha256(
        json.dumps(identity, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    readiness = element.get("export_readiness") or build_export_readiness(element)
    return {
        "formula_id": f"formula:{formula_hash[:24]}",
        "source_id": source_id,
        "canonical_citation": element.get("canonical_citation", ""),
        "schema_version": PARSER_SCHEMA_VERSION,
        "logic_family": "deontic",
        "formula": formula,
        "formal_terms": element.get("formal_terms", {}),
        "logic_frame": element.get("logic_frame", {}),
        "legal_frame": element.get("legal_frame", {}),
        "proof_candidate": bool(readiness.get("proof_ready")),
        "formal_logic_targets": readiness.get("formal_logic_targets", []),
        "requires_validation": readiness.get("requires_validation", []),
        "parser_warnings": element.get("parser_warnings", []),
        "conflict_links": element.get("conflict_links", []),
        "enforcement_links": element.get("enforcement_links", []),
        "provenance": {
            "text": element.get("text", ""),
            "source_span": element.get("source_span", []),
            "support_text": element.get("support_text", ""),
            "support_span": element.get("support_span", []),
        },
    }


def build_procedure_event_records(element: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Flatten procedure event chains into event-calculus friendly rows."""
    procedure = element.get("procedure") or {}
    event_chain = procedure.get("event_chain") or []
    records: List[Dict[str, Any]] = []
    source_id = element.get("source_id") or build_source_id(element)
    temporal_details = element.get("temporal_constraint_details") or []
    for item in event_chain:
        event = item.get("event", "")
        order = item.get("order", 0)
        relations = item.get("relations") or []
        identity = {
            "source_id": source_id,
            "event": event,
            "order": order,
        }
        event_hash = hashlib.sha256(
            json.dumps(identity, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        anchors = [
            detail
            for detail in temporal_details
            if detail.get("anchor_event") == event or detail.get("anchor") == event
        ]
        records.append(
            {
                "event_id": f"event:{event_hash[:24]}",
                "source_id": source_id,
                "canonical_citation": element.get("canonical_citation", ""),
                "event": event,
                "event_symbol": normalize_predicate_name(event),
                "event_order": order,
                "is_trigger": event == procedure.get("trigger_event"),
                "is_terminal": event == procedure.get("terminal_event"),
                "event_mentions": item.get("mentions", []),
                "event_relations": relations,
                "relation_types": [relation.get("relation", "") for relation in relations],
                "anchor_events": [relation.get("anchor_event", "") for relation in relations if relation.get("anchor_event")],
                "temporal_anchors": anchors,
                "actor_id": (element.get("formal_terms") or {}).get("actor_id", ""),
                "action_predicate": (element.get("formal_terms") or {}).get("action_predicate", ""),
                "provenance": {
                    "text": element.get("text", ""),
                    "source_span": element.get("source_span", []),
                },
            }
        )
    return records


def build_proof_obligation_record(element: Dict[str, Any]) -> Dict[str, Any]:
    """Build a deterministic proof-queue row for theorem/proof backends."""
    formal_record = build_formal_logic_record(element)
    readiness = element.get("export_readiness") or build_export_readiness(element)
    identity = {
        "source_id": formal_record["source_id"],
        "formula_id": formal_record["formula_id"],
        "schema": PARSER_SCHEMA_VERSION,
    }
    proof_hash = hashlib.sha256(
        json.dumps(identity, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    proof_systems = ["deontic_tableau", "fol_resolution", "frame_logic"]
    if "temporal_logic" in readiness.get("formal_logic_targets", []):
        proof_systems.extend(["temporal_logic", "event_calculus"])
    return {
        "proof_obligation_id": f"proof:{proof_hash[:24]}",
        "source_id": formal_record["source_id"],
        "formula_id": formal_record["formula_id"],
        "canonical_citation": formal_record["canonical_citation"],
        "formula": formal_record["formula"],
        "proof_candidate": formal_record["proof_candidate"],
        "proof_systems": proof_systems,
        "blocked": not formal_record["proof_candidate"],
        "blockers": readiness.get("blockers", []),
        "requires_validation": readiness.get("requires_validation", []),
        "conflict_links": element.get("conflict_links", []),
        "enforcement_links": element.get("enforcement_links", []),
        "provenance": formal_record["provenance"],
    }


def build_clause_records(element: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Flatten conditions/exceptions/overrides into parquet-friendly clause rows."""
    records: List[Dict[str, Any]] = []
    source_id = element.get("source_id") or build_source_id(element)
    clause_groups = [
        ("condition", element.get("condition_details") or []),
        ("exception", element.get("exception_details") or []),
        ("override", element.get("override_clause_details") or []),
    ]
    for slot_type, clauses in clause_groups:
        for index, clause in enumerate(clauses):
            text = clause.get("normalized_text") or clause.get("raw_text", "")
            identity = {
                "source_id": source_id,
                "slot_type": slot_type,
                "index": index,
                "text": text,
                "span": clause.get("span", []),
            }
            clause_hash = hashlib.sha256(
                json.dumps(identity, sort_keys=True, default=str).encode("utf-8")
            ).hexdigest()
            records.append(
                {
                    "clause_id": f"clause:{clause_hash[:24]}",
                    "source_id": source_id,
                    "canonical_citation": element.get("canonical_citation", ""),
                    "slot_type": slot_type,
                    "clause_type": clause.get("clause_type", ""),
                    "raw_text": clause.get("raw_text", ""),
                    "normalized_text": text,
                    "predicate": normalize_predicate_name(text),
                    "span": clause.get("span", []),
                    "clause_span": clause.get("clause_span", []),
                    "effect": {
                        "condition": "antecedent",
                        "exception": "negated_antecedent",
                        "override": "precedence_modifier",
                    }.get(slot_type, "modifier"),
                    "provenance": {
                        "text": element.get("text", ""),
                        "source_span": element.get("source_span", []),
                    },
                }
            )
    return records


def build_reference_records(element: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Flatten cross-reference resolution into citation graph rows."""
    records: List[Dict[str, Any]] = []
    source_id = element.get("source_id") or build_source_id(element)
    refs = element.get("resolved_cross_references") or element.get("cross_reference_details") or []
    for index, ref in enumerate(refs):
        target_sections = ref.get("target_sections") or []
        if target_sections:
            targets = target_sections
        else:
            targets = [
                {
                    "section": ref.get("target_section", ""),
                    "heading": ref.get("target_heading", ""),
                    "hierarchy_path": ref.get("target_hierarchy_path", []),
                }
            ]
        for target_index, target in enumerate(targets):
            target_section = target.get("section", "") if isinstance(target, dict) else ""
            identity = {
                "source_id": source_id,
                "index": index,
                "target_index": target_index,
                "type": ref.get("type", ""),
                "value": ref.get("value", ""),
                "target_section": target_section,
            }
            ref_hash = hashlib.sha256(
                json.dumps(identity, sort_keys=True, default=str).encode("utf-8")
            ).hexdigest()
            records.append(
                {
                    "reference_id": f"ref:{ref_hash[:24]}",
                    "source_id": source_id,
                    "canonical_citation": element.get("canonical_citation", ""),
                    "reference_type": ref.get("type", ""),
                    "reference_value": ref.get("value", ""),
                    "raw_text": ref.get("raw_text", ""),
                    "normalized_text": ref.get("normalized_text", ""),
                    "resolution_status": ref.get("resolution_status", "unresolved"),
                    "target_exists": bool(ref.get("target_exists")),
                    "target_section": target_section,
                    "target_heading": target.get("heading", "") if isinstance(target, dict) else "",
                    "target_hierarchy_path": target.get("hierarchy_path", []) if isinstance(target, dict) else [],
                    "span": ref.get("span", []),
                    "provenance": {
                        "text": element.get("text", ""),
                        "source_span": element.get("source_span", []),
                    },
                }
            )
    return records


def build_sanction_records(element: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Flatten penalty details into sanction rows for proof/certificate layers."""
    penalty = element.get("penalty") or {}
    if not penalty:
        return []
    source_id = element.get("source_id") or build_source_id(element)
    records: List[Dict[str, Any]] = []

    def add_record(sanction_type: str, detail: Dict[str, Any], role: str = "") -> None:
        identity = {
            "source_id": source_id,
            "sanction_type": sanction_type,
            "role": role,
            "detail": detail,
        }
        sanction_hash = hashlib.sha256(
            json.dumps(identity, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        records.append(
            {
                "sanction_id": f"sanction:{sanction_hash[:24]}",
                "source_id": source_id,
                "canonical_citation": element.get("canonical_citation", ""),
                "sanction_type": sanction_type,
                "role": role,
                "detail": detail,
                "sanction_class": penalty.get("sanction_class", ""),
                "sanction_modality": penalty.get("sanction_modality", ""),
                "recurrence": penalty.get("recurrence", {}),
                "has_range": bool(penalty.get("has_range")),
                "enforcement_links": element.get("enforcement_links", []),
                "provenance": {
                    "text": element.get("text", ""),
                    "source_span": element.get("source_span", []),
                },
            }
        )

    seen_amounts: set[tuple[str, str, str]] = set()
    for amount in penalty.get("monetary_amount_details") or []:
        amount_key = (
            str(amount.get("raw_text", "")),
            str(amount.get("numeric_value", "")),
            str(amount.get("currency", "")),
        )
        if amount_key in seen_amounts:
            continue
        seen_amounts.add(amount_key)
        add_record("fine", amount, "amount")
    if penalty.get("minimum_amount"):
        add_record("fine", penalty["minimum_amount"], "minimum")
    if penalty.get("maximum_amount"):
        add_record("fine", penalty["maximum_amount"], "maximum")
    if penalty.get("imprisonment_duration"):
        add_record("imprisonment", penalty["imprisonment_duration"], "duration")
    if penalty.get("recurrence"):
        add_record("recurrence", penalty["recurrence"], "recurrence")
    return records


def build_ontology_entity_records(element: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Flatten ontology terms into entity rows for KG/entity parquet tables."""
    source_id = element.get("source_id") or build_source_id(element)
    records: List[Dict[str, Any]] = []
    seen: set[tuple[str, str, tuple[int, ...]]] = set()
    for term in element.get("ontology_terms") or []:
        value = str(term.get("term", ""))
        entity_type = str(term.get("type", ""))
        span = tuple(term.get("span") or [])
        key = (value.lower(), entity_type, span)
        if key in seen:
            continue
        seen.add(key)
        identity = {
            "source_id": source_id,
            "entity": value,
            "type": entity_type,
            "span": list(span),
        }
        entity_hash = hashlib.sha256(
            json.dumps(identity, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        records.append(
            {
                "entity_id": f"entity:{entity_hash[:24]}",
                "source_id": source_id,
                "canonical_citation": element.get("canonical_citation", ""),
                "term": value,
                "term_id": normalize_symbol(value),
                "entity_type": entity_type,
                "definition_body": term.get("definition_body", ""),
                "span": list(span),
                "provenance": {
                    "text": element.get("text", ""),
                    "source_span": element.get("source_span", []),
                },
            }
        )
    return records


def build_repair_queue_record(element: Dict[str, Any]) -> Dict[str, Any]:
    """Build a deterministic llm_router repair queue row when repair is needed."""
    repair = element.get("llm_repair") or build_llm_repair_payload(element)
    source_id = element.get("source_id") or build_source_id(element)
    identity = {
        "source_id": source_id,
        "prompt_hash": repair.get("prompt_hash", ""),
        "reasons": repair.get("reasons", []),
    }
    repair_hash = hashlib.sha256(
        json.dumps(identity, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    return {
        "repair_id": f"repair:{repair_hash[:24]}",
        "source_id": source_id,
        "canonical_citation": element.get("canonical_citation", ""),
        "required": bool(repair.get("required")),
        "reasons": repair.get("reasons", []),
        "suggested_router": repair.get("suggested_router", "llm_router"),
        "prompt_template": repair.get("prompt_template", ""),
        "prompt_hash": repair.get("prompt_hash", ""),
        "prompt_context": repair.get("prompt_context", {}),
        "schema_version": element.get("schema_version", PARSER_SCHEMA_VERSION),
        "quality_label": element.get("quality_label", ""),
        "scaffold_quality": element.get("scaffold_quality", 0.0),
    }


def build_export_record_bundle(element: Dict[str, Any]) -> Dict[str, Any]:
    """Build all deterministic parquet-oriented export rows for one element."""
    return {
        "source_id": element.get("source_id") or build_source_id(element),
        "canonical": dict(element),
        "formal_logic": [build_formal_logic_record(element)],
        "proof_obligations": [build_proof_obligation_record(element)],
        "knowledge_graph_triples": build_kg_triples(element),
        "clause_records": build_clause_records(element),
        "reference_records": build_reference_records(element),
        "procedure_event_records": build_procedure_event_records(element),
        "sanction_records": build_sanction_records(element),
        "ontology_entities": build_ontology_entity_records(element),
        "repair_queue": [build_repair_queue_record(element)] if (element.get("llm_repair") or {}).get("required") else [],
    }


def build_document_export_tables(elements: List[Dict[str, Any]]) -> Dict[str, List[Any]]:
    """Aggregate parser elements into named parquet-style export tables."""
    tables: Dict[str, List[Any]] = {
        "canonical": [],
        "formal_logic": [],
        "proof_obligations": [],
        "knowledge_graph_triples": [],
        "clause_records": [],
        "reference_records": [],
        "procedure_event_records": [],
        "sanction_records": [],
        "ontology_entities": [],
        "repair_queue": [],
    }
    for element in elements or []:
        bundle = build_export_record_bundle(element)
        tables["canonical"].append(bundle["canonical"])
        for table_name in tables:
            if table_name == "canonical":
                continue
            tables[table_name].extend(bundle.get(table_name, []))
    return tables


def build_document_export_manifest(
    elements: List[Dict[str, Any]],
    tables: Optional[Dict[str, List[Any]]] = None,
) -> Dict[str, Any]:
    """Build deterministic metadata for a parsed document export."""
    tables = tables or build_document_export_tables(elements)
    source_ids = [element.get("source_id") or build_source_id(element) for element in elements or []]
    table_counts = {name: len(rows or []) for name, rows in tables.items()}
    identity = {
        "schema_version": PARSER_SCHEMA_VERSION,
        "source_ids": source_ids,
        "table_counts": table_counts,
    }
    manifest_hash = hashlib.sha256(
        json.dumps(identity, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    return {
        "manifest_id": f"manifest:{manifest_hash[:24]}",
        "schema_version": PARSER_SCHEMA_VERSION,
        "element_count": len(elements or []),
        "source_ids": source_ids,
        "table_counts": table_counts,
        "quality": {
            "proof_candidates": sum(1 for element in elements or [] if (element.get("export_readiness") or {}).get("proof_ready")),
            "repair_required": sum(1 for element in elements or [] if (element.get("llm_repair") or {}).get("required")),
            "schema_valid": sum(1 for element in elements or [] if element.get("schema_valid") is True),
        },
    }


def validate_document_export_tables(tables: Dict[str, List[Any]]) -> Dict[str, Any]:
    """Validate basic integrity constraints for deterministic export tables."""
    required_tables = set(EXPORT_TABLE_SPECS)
    missing_tables = sorted(required_tables - set((tables or {}).keys()))
    errors: List[str] = []
    warnings: List[str] = []
    if missing_tables:
        errors.extend([f"missing_table:{name}" for name in missing_tables])
    canonical = list((tables or {}).get("canonical") or [])
    canonical_source_ids = {row.get("source_id") for row in canonical if isinstance(row, dict)}
    if any(not source_id for source_id in canonical_source_ids) or len(canonical_source_ids) != len(canonical):
        errors.append("canonical_source_ids_missing_or_not_unique")
    for table_name, rows in (tables or {}).items():
        spec = EXPORT_TABLE_SPECS.get(table_name, {})
        primary_key = spec.get("primary_key", "")
        primary_values: List[Any] = []
        for index, row in enumerate(rows or []):
            if not isinstance(row, dict):
                errors.append(f"{table_name}[{index}]_row_not_dict")
                continue
            if primary_key:
                primary_value = row.get(primary_key)
                primary_values.append(primary_value)
                if not primary_value:
                    errors.append(f"{table_name}[{index}]_missing_{primary_key}")
            if spec.get("requires_source_id") and not row.get("source_id"):
                errors.append(f"{table_name}[{index}]_missing_source_id")
            if table_name != "canonical" and row.get("source_id") and row.get("source_id") not in canonical_source_ids:
                warnings.append(f"{table_name}[{index}]_source_id_not_in_canonical")
        if primary_key and len(set(primary_values)) != len(primary_values):
            errors.append(f"{table_name}_{primary_key}_not_unique")
    if len((tables or {}).get("formal_logic") or []) != len(canonical):
        errors.append("formal_logic_count_mismatch")
    if len((tables or {}).get("proof_obligations") or []) != len(canonical):
        errors.append("proof_obligations_count_mismatch")
    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "table_counts": {name: len(rows or []) for name, rows in (tables or {}).items()},
    }


def get_export_table_specs() -> Dict[str, Dict[str, Any]]:
    """Return the deterministic export table primary-key contract."""
    return {name: dict(spec) for name, spec in EXPORT_TABLE_SPECS.items()}


def serialize_export_tables_for_parquet(
    tables: Dict[str, List[Any]],
    *,
    stringify_nested: bool = True,
) -> Dict[str, List[Dict[str, Any]]]:
    """Make export tables deterministic and safe for simple parquet writers."""
    serialized: Dict[str, List[Dict[str, Any]]] = {}
    for table_name, rows in (tables or {}).items():
        serialized_rows: List[Dict[str, Any]] = []
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            serialized_rows.append(
                {
                    key: _parquet_cell(value, stringify_nested=stringify_nested)
                    for key, value in row.items()
                }
            )
        serialized[table_name] = serialized_rows
    return serialized


def write_document_export_parquet(
    elements: List[Dict[str, Any]],
    output_dir: str,
    *,
    stringify_nested: bool = True,
) -> Dict[str, Any]:
    """Write deterministic document export tables to parquet files using pandas."""
    try:
        import pandas as pd  # type: ignore
    except ImportError as exc:  # pragma: no cover - exercised only without pandas
        raise RuntimeError("pandas is required to write parquet export tables") from exc

    tables = build_document_export_tables(elements)
    validation = validate_document_export_tables(tables)
    if not validation["valid"]:
        raise ValueError(f"invalid export tables: {validation['errors']}")
    serialized = serialize_export_tables_for_parquet(tables, stringify_nested=stringify_nested)
    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    parquet_paths: Dict[str, str] = {}
    for table_name, rows in serialized.items():
        parquet_path = target_dir / f"{table_name}.parquet"
        pd.DataFrame(rows).to_parquet(parquet_path, index=False)
        parquet_paths[table_name] = str(parquet_path)
    manifest = build_document_export_manifest(elements, tables)
    manifest_path = target_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, sort_keys=True, indent=2), encoding="utf-8")
    return {
        "output_dir": str(target_dir),
        "parquet_paths": parquet_paths,
        "manifest_path": str(manifest_path),
        "manifest": manifest,
        "validation": validation,
    }


def _parquet_cell(value: Any, *, stringify_nested: bool) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if stringify_nested:
        return json.dumps(value, sort_keys=True, default=str)
    return value


def build_deontic_formula(element: Dict[str, Any]) -> str:
    from ipfs_datasets_py.logic.deontic.formula_builder import parser_element_to_formula

    return parser_element_to_formula(element)


def normalize_predicate_name(name: str) -> str:
    if not name:
        return "P"
    name = re.sub(r"[_\-]+", " ", name)
    name = re.sub(r"[^0-9A-Za-z\s]", "", name)
    words = name.strip().split()
    filtered_words = [
        w
        for w in words
        if w.lower() not in ["the", "a", "an", "of", "in", "on", "at", "to", "for", "with", "by"]
    ]
    if not filtered_words:
        return "P"
    return "".join(word.capitalize() for word in filtered_words)


def parser_elements_with_deterministic_ir_readiness(
    elements: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Project deterministic IR/formula readiness onto parser elements.

    ``extract_normative_elements`` intentionally returns the conservative raw
    parser view: parser theorem promotion and legacy repair audit fields stay
    stable for existing callers. Some parser-boundary consumers, however, need
    the same source-grounded repair clearance already used by exports, metrics,
    and converter metadata. This helper provides that explicit opt-in without
    reparsing text and without invoking any LLM repair lane.

    The returned dictionaries are copies. ``promotable_to_theorem`` remains the
    parser gate, while ``export_readiness`` and ``llm_repair`` reflect whether
    the typed IR/formula layer has deterministically resolved stale repair noise
    such as local applicability, substantive exceptions represented in the
    formula antecedent, or pure precedence overrides.
    """

    from ipfs_datasets_py.logic.deontic.exports import parser_elements_with_ir_export_readiness

    return parser_elements_with_ir_export_readiness(elements)


def identify_obligations(elements: List[Dict[str, Any]]) -> Dict[str, Any]:
    categorized: Dict[str, Any] = {
        "obligations": [],
        "permissions": [],
        "prohibitions": [],
        "conditional_norms": [],
        "temporal_norms": [],
    }

    for element in elements:
        norm_type = element.get("norm_type")
        if norm_type == "obligation":
            categorized["obligations"].append(element)
        elif norm_type == "permission":
            categorized["permissions"].append(element)
        elif norm_type == "prohibition":
            categorized["prohibitions"].append(element)

        if element.get("conditions"):
            categorized["conditional_norms"].append(element)
        if element.get("temporal_constraints"):
            categorized["temporal_norms"].append(element)

    return categorized


def detect_normative_conflicts(elements: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Detect conflicts between normative statements.
    
    This function identifies four types of conflicts:
    1. Direct conflicts: O(p) ∧ F(p) (obligation vs prohibition)
    2. Permission conflicts: P(p) ∧ F(p) (permission vs prohibition)
    3. Conditional conflicts: Conflicting norms with overlapping conditions
    4. Temporal conflicts: Conflicting norms with overlapping time periods
    
    Args:
        elements: List of normative elements extracted from legal text
        
    Returns:
        List of detected conflicts with type, severity, and resolution strategies
    """
    conflicts: List[Dict[str, Any]] = []
    
    # Check each pair of normative elements
    for i, elem1 in enumerate(elements):
        for j, elem2 in enumerate(elements[i+1:], i+1):
            conflict = _check_conflict_pair(elem1, elem2)
            if conflict:
                conflicts.append({
                    "type": conflict["type"],
                    "elements": [elem1, elem2],
                    "element_indices": [i, j],
                    "severity": conflict["severity"],
                    "description": conflict["description"],
                    "resolution_strategies": conflict["strategies"]
                })
    
    return conflicts


def _check_conflict_pair(elem1: Dict[str, Any], elem2: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Check if two normative elements conflict.
    
    Args:
        elem1: First normative element
        elem2: Second normative element
        
    Returns:
        Conflict details if conflict exists, None otherwise
    """
    # Extract relevant fields
    norm1_type = elem1.get("norm_type")
    norm2_type = elem2.get("norm_type")
    action1 = _first_text(elem1.get("action")).lower().strip()
    action2 = _first_text(elem2.get("action")).lower().strip()
    subject1 = _first_text(elem1.get("subject")).lower().strip()
    subject2 = _first_text(elem2.get("subject")).lower().strip()
    
    # Skip if missing critical information
    if not all([norm1_type, norm2_type, action1, action2]):
        return None
    
    # Check if actions are similar (exact match or high similarity)
    actions_match = _actions_similar(action1, action2)
    subjects_match = _subjects_similar(subject1, subject2)
    
    if not (actions_match and subjects_match):
        return None
    
    # Check for temporal conflicts first (more specific than direct conflicts)
    temporal_conflict = _check_temporal_conflict(elem1, elem2)
    if temporal_conflict:
        return temporal_conflict
    
    # Check for direct conflicts: O(p) ∧ F(p)
    if (norm1_type == "obligation" and norm2_type == "prohibition") or \
       (norm1_type == "prohibition" and norm2_type == "obligation"):
        return {
            "type": "direct_conflict",
            "severity": "high",
            "description": f"Direct conflict: {norm1_type} conflicts with {norm2_type} for same action",
            "strategies": ["lex_superior", "lex_specialis", "lex_posterior"]
        }
    
    # Check for permission conflicts: P(p) ∧ F(p)
    if (norm1_type == "permission" and norm2_type == "prohibition") or \
       (norm1_type == "prohibition" and norm2_type == "permission"):
        return {
            "type": "permission_conflict",
            "severity": "medium",
            "description": f"Permission conflict: {norm1_type} conflicts with {norm2_type} for same action",
            "strategies": ["prohibition_prevails", "context_dependent"]
        }
    
    # Check for conditional conflicts
    conditional_conflict = _check_conditional_conflict(elem1, elem2)
    if conditional_conflict:
        return conditional_conflict
    
    return None


def _actions_similar(action1: str, action2: str) -> bool:
    """Check if two actions are similar enough to conflict.
    
    Args:
        action1: First action string
        action2: Second action string
        
    Returns:
        True if actions are similar, False otherwise
    """
    if not action1 or not action2:
        return False
    
    # Exact match
    if action1 == action2:
        return True
    
    # Normalize and check for overlap
    words1 = set(action1.split())
    words2 = set(action2.split())
    
    # If there's significant word overlap (>50%), consider similar
    if words1 and words2:
        overlap = len(words1 & words2) / min(len(words1), len(words2))
        return overlap > 0.5
    
    return False


def _first_text(value: Any) -> str:
    if isinstance(value, list):
        return str(value[0]) if value else ""
    return str(value or "")


def _subjects_similar(subject1: str, subject2: str) -> bool:
    """Check if two subjects are similar enough to conflict.
    
    Args:
        subject1: First subject string
        subject2: Second subject string
        
    Returns:
        True if subjects are similar, False otherwise
    """
    if not subject1 or not subject2:
        # If either subject is empty, assume they refer to same general subject
        return True
    
    # Exact match
    if subject1 == subject2:
        return True
    
    # Check for subset relationship
    if subject1 in subject2 or subject2 in subject1:
        return True
    
    # Normalize and check for overlap
    words1 = set(subject1.split())
    words2 = set(subject2.split())
    
    if words1 and words2:
        overlap = len(words1 & words2) / min(len(words1), len(words2))
        return overlap > 0.5
    
    return False


def _check_temporal_conflict(elem1: Dict[str, Any], elem2: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Check for temporal conflicts between two normative elements.
    
    Args:
        elem1: First normative element
        elem2: Second normative element
        
    Returns:
        Conflict details if temporal conflict exists, None otherwise
    """
    temporal1 = elem1.get("temporal_constraints", [])
    temporal2 = elem2.get("temporal_constraints", [])
    
    # Only check if both have temporal constraints
    if not (temporal1 and temporal2):
        return None
    
    # Check if temporal periods overlap and norms conflict
    norm1_type = elem1.get("norm_type")
    norm2_type = elem2.get("norm_type")
    
    # If norms are conflicting types and have overlapping time periods
    conflicting_types = {
        ("obligation", "prohibition"),
        ("prohibition", "obligation"),
        ("permission", "prohibition"),
        ("prohibition", "permission")
    }
    
    if (norm1_type, norm2_type) in conflicting_types:
        # Simple check: if both have temporal constraints, assume potential overlap
        # A more sophisticated implementation would parse actual dates/times
        return {
            "type": "temporal_conflict",
            "severity": "medium",
            "description": "Conflicting norms with overlapping temporal constraints",
            "strategies": ["temporal_precedence", "latest_applies"]
        }
    
    return None


def _check_conditional_conflict(elem1: Dict[str, Any], elem2: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Check for conditional conflicts between two normative elements.
    
    Args:
        elem1: First normative element
        elem2: Second normative element
        
    Returns:
        Conflict details if conditional conflict exists, None otherwise
    """
    conditions1 = elem1.get("conditions", [])
    conditions2 = elem2.get("conditions", [])
    
    # Only check if both have conditions
    if not (conditions1 and conditions2):
        return None
    
    norm1_type = elem1.get("norm_type")
    norm2_type = elem2.get("norm_type")
    
    # Check if conditions overlap
    # Simple check: if conditions share words, they might overlap
    cond1_text = " ".join(str(c).lower() for c in conditions1)
    cond2_text = " ".join(str(c).lower() for c in conditions2)
    
    words1 = set(cond1_text.split())
    words2 = set(cond2_text.split())
    
    if words1 and words2:
        overlap = len(words1 & words2) / min(len(words1), len(words2))
        
        # If conditions overlap significantly and norms conflict
        if overlap > 0.3:
            conflicting_types = {
                ("obligation", "prohibition"),
                ("prohibition", "obligation"),
                ("permission", "prohibition"),
                ("prohibition", "permission")
            }
            
            if (norm1_type, norm2_type) in conflicting_types:
                return {
                    "type": "conditional_conflict",
                    "severity": "low",
                    "description": "Conflicting norms with overlapping conditions",
                    "strategies": ["specificity_analysis", "context_evaluation"]
                }
    
    return None
