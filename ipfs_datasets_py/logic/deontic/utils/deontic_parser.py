"""Deontic logic parsing and formula generation utilities.

This module is intentionally conservative.  It is a deterministic scaffold for
indexing, triage, and LLM prompting, not a substitute for an LLM/legal review
formalization pass.
"""

import re
from typing import Any, Dict, List, Optional


PARSER_SCHEMA_VERSION = "deterministic_deontic_v5"
PARSER_REQUIRED_FIELDS = [
    "schema_version",
    "text",
    "support_text",
    "support_span",
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
    "enumerated_items",
    "legal_frame",
    "kg_relationship_hints",
    "monetary_amounts",
    "monetary_amount_details",
    "penalty",
    "procedure",
    "section_context",
    "hierarchy_path",
    "document_type",
    "extraction_method",
    "confidence_floor",
    "slot_coverage",
    "scaffold_quality",
    "quality_label",
    "parser_warnings",
    "promotable_to_theorem",
]
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9(])")
_SECTION_HEADER_RE = re.compile(
    r"^\s*(?:(?:sec(?:tion)?\.?|§)\s*)?([0-9]+(?:\.[0-9]+)*(?:[A-Za-z])?)\.?\s*(.*)$",
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
    r"\b(?:a\s+)?(?:violation|offense|infraction)\s+(?:is|shall\s+be)\s+"
    r"(?:punishable\s+by|subject\s+to)\s+(.+?)(?:[.;:]|$)",
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
    ("deadline", "within_duration", r"\bwithin\s+(\d+\s+(?:days?|weeks?|months?|years?)(?:\s+after\s+.+?)?)(?=\s+(?:unless|except|without|absent|if|when|where|provided that|subject to)\b|[,.;]|$)"),
    ("deadline", "not_later_than", r"\bnot\s+later\s+than\s+(\d+\s+(?:days?|weeks?|months?|years?)(?:\s+after\s+.+?)?)(?=\s+(?:unless|except|without|absent|if|when|where|provided that|subject to)\b|[,.;]|$)"),
    ("deadline", "before_date", r"\bbefore\s+((?:january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{1,2})"),
    ("deadline", "after_date", r"\bafter\s+((?:january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{1,2})"),
    ("period", "annually", r"\b(annually)\b"),
    ("period", "monthly", r"\b(monthly)\b"),
    ("period", "weekly", r"\b(weekly)\b"),
    ("period", "daily", r"\b(daily)\b"),
    ("duration", "for_duration", r"\bfor\s+(\d+\s+(?:days?|weeks?|months?|years?))"),
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
    "mayor",
    "secretary",
    "state",
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
    "owner",
    "party",
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
    "license",
    "permit",
    "registration",
}
_LEGAL_EVENT_ENTITIES = {
    "appeal",
    "fee",
    "hearing",
    "notice",
    "offense",
    "penalty",
    "violation",
}
_PROPERTY_ENTITIES = {
    "building",
    "facility",
    "property",
    "sidewalk",
    "street",
    "vehicle",
}
_PROCEDURE_EVENT_ORDER = [
    "application",
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


def extract_normative_elements(text: str, document_type: str = "statute") -> List[Dict[str, Any]]:
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
            _finalize_element(element)
            elements.append(element)
    return elements


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
    cursor = 0

    for raw_line in source.splitlines() or [source]:
        line_start = cursor
        cursor += len(raw_line) + 1
        line = raw_line.strip()
        if not line:
            continue

        header = _SECTION_HEADER_RE.match(line)
        if header and _looks_like_section_header(line, header):
            section_context = {
                "section": header.group(1),
                "heading": header.group(2).strip(" ."),
            }
            hierarchy = [f"section:{section_context['section']}"]
            if section_context["heading"]:
                hierarchy.append(f"heading:{section_context['heading']}")
            continue

        for start, end, segment_text, label_path in _split_segment_fragments(line):
            absolute_start = line_start + raw_line.find(line) + start
            segment_hierarchy = [*hierarchy, *label_path]
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
            }
        ]
    return segments


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
                    extraction_method="deterministic_impersonal_norm_v3",
                )
            )
        )
    if elements:
        return elements

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
                    extraction_method="deterministic_penalty_clause_v4",
                )
            )
        ]

    if _DEFINITION_RE.search(sentence_lower):
        defined_term_match = _DEFINED_TERM_RE.search(sentence)
        defined_terms = [_clean_phrase(defined_term_match.group(1))] if defined_term_match else extract_legal_subject(sentence)
        return [
            _finalize_element(
                {
                "schema_version": PARSER_SCHEMA_VERSION,
                "text": sentence,
                "support_text": sentence,
                "support_span": [0, len(sentence)],
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
                "enumerated_items": extract_enumerated_items(sentence),
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
) -> Dict[str, Any]:
    enumerated_items = extract_enumerated_items(sentence)
    if enumerated_items and re.match(r"^\([A-Za-z0-9]+\)\s+", action_text or ""):
        action_text = enumerated_items[0]["text"]
    subject = [subject_text] if subject_text else extract_legal_subject(sentence)
    action = [action_text]
    return {
        "schema_version": PARSER_SCHEMA_VERSION,
        "text": sentence,
        "support_text": sentence[support_span[0] : support_span[1]].strip(),
        "support_span": list(support_span),
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
        "enumerated_items": enumerated_items,
        "legal_frame": {},
        "kg_relationship_hints": [],
        "monetary_amounts": extract_monetary_amounts(sentence),
        "monetary_amount_details": extract_monetary_amount_details(sentence),
        "penalty": {},
        "procedure": {},
        "section_context": {},
        "hierarchy_path": [],
        "document_type": document_type,
        "extraction_method": extraction_method,
        "confidence_floor": 0.35,
    }


def _finalize_element(element: Dict[str, Any]) -> Dict[str, Any]:
    element.setdefault("schema_version", PARSER_SCHEMA_VERSION)
    element.setdefault("section_context", {})
    element.setdefault("hierarchy_path", [])
    _enrich_legal_frame(element)
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
    return element


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
        "enumerated_items",
        "kg_relationship_hints",
        "monetary_amounts",
        "monetary_amount_details",
        "hierarchy_path",
        "parser_warnings",
    ]
    for field in list_fields:
        if field in element and not isinstance(element[field], list):
            type_errors.append(field)
    if "section_context" in element and not isinstance(element["section_context"], dict):
        type_errors.append("section_context")
    for field in ["legal_frame", "penalty", "procedure"]:
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


def _enrich_legal_frame(element: Dict[str, Any]) -> None:
    text = str(element.get("text") or "")
    action = (element.get("action") or [""])[0]
    subject = (element.get("subject") or [""])[0]
    category = classify_legal_frame(element)
    element["legal_frame"] = {
        "category": category,
        "actor": subject,
        "actor_type": element.get("actor_type", "unknown"),
        "action": action,
        "object": element.get("action_object", ""),
        "recipient": element.get("action_recipient", ""),
        "norm_type": element.get("norm_type", ""),
        "deontic_operator": element.get("deontic_operator", ""),
    }
    element["monetary_amounts"] = extract_monetary_amounts(text)
    element["monetary_amount_details"] = extract_monetary_amount_details(text)
    element["penalty"] = extract_penalty_details(text, action)
    element["procedure"] = extract_procedure_details(text, action)
    element["kg_relationship_hints"] = build_kg_relationship_hints(element)


def classify_legal_frame(element: Dict[str, Any]) -> str:
    text = str(element.get("text") or "").lower()
    action = " ".join(element.get("action", [])).lower()
    norm_type = element.get("norm_type")
    subject = " ".join(element.get("subject", [])).lower()
    if norm_type == "definition":
        return "definition"
    if norm_type == "penalty" or "punishable" in text or "fine" in text or "penalty" in text:
        return "penalty"
    if norm_type == "violation" or "violation" in text or "offense" in text or "infraction" in text:
        return "violation"
    if any(term in text for term in ["appeal", "hearing", "notice", "decision", "inspect", "revoke", "suspend"]):
        return "procedure"
    if subject in _LEGAL_INSTRUMENT_ENTITIES or any(term in text for term in ["permit", "license", "certificate", "registration"]):
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
    return {
        "raw_text": combined,
        "monetary_amounts": extract_monetary_amounts(combined),
        "has_imprisonment": bool(re.search(r"\b(?:jail|imprison|imprisonment|custody)\b", lower)),
        "has_fine": "fine" in lower or bool(extract_monetary_amounts(combined)),
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
    return {
        "events": events,
        "event_chain": [{"event": event, "order": index + 1} for index, event in enumerate(events)],
        "trigger_event": events[0],
        "terminal_event": events[-1],
        "raw_text": combined,
    }


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
        }.get(element.get("norm_type"), "regulates")
        relationships.append({"subject": "law", "predicate": predicate, "object": subject})
        relationships.append({"subject": subject, "predicate": "performsAction", "object": action})
    if category == "permit_or_license" and action:
        relationships.append({"subject": action, "predicate": "requiresLegalInstrument", "object": subject})
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
    for ref in element.get("cross_references", []):
        relationships.append({"subject": "law", "predicate": "references", "object": f"{ref.get('type')}:{ref.get('value')}"})
    for amount in element.get("monetary_amounts", []):
        relationships.append({"subject": "law", "predicate": "mentionsAmount", "object": amount.get("raw_text", "")})
    return relationships


def extract_legal_instrument_target(action: str) -> str:
    match = re.search(
        r"\b(?:permit|license|certificate|registration|approval)\b",
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
    if element.get("cross_references"):
        warnings.append("cross_reference_requires_resolution")
        score -= 0.04
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
        ("section", r"\bsection\s+([0-9][0-9A-Za-z.\-]*(?:\([a-z0-9]+\))*)"),
        ("subsection", r"\bsubsection\s+\(([a-z0-9]+)\)"),
        ("paragraph", r"\bparagraph\s+\(([a-z0-9]+)\)"),
        ("chapter", r"\bchapter\s+([0-9A-Za-z][0-9A-Za-z.\-]*)"),
        ("title", r"\btitle\s+([0-9A-Za-z]+)"),
        ("usc", r"\b(\d+)\s+u\.?s\.?c\.?\s+(?:§|sec(?:tion)?\.?)?\s*([0-9A-Za-z.\-]+)"),
    ]
    seen: set[tuple[str, str]] = set()
    for ref_type, pattern in patterns:
        for match in re.finditer(pattern, sentence, flags=re.IGNORECASE):
            if len(match.groups()) > 1:
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
    return refs


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
                    "raw_text": match.group(0).strip(),
                    "normalized_text": value,
                    "span": [match.start(), match.end()],
                }
            )
    return details


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


def build_deontic_formula(element: Dict[str, Any]) -> str:
    operator = element["deontic_operator"]
    if operator == "DEF":
        subject = normalize_predicate_name((element.get("subject") or ["DefinedTerm"])[0])
        return f"Definition({subject})"
    subject = element.get("subject", ["X"])
    action = element.get("action", ["Action"])
    conditions = element.get("conditions", [])

    action_text = _action_without_mental_state(action[0]) if action else "Action"
    action_pred = normalize_predicate_name(action_text) if action_text else "Action"
    subject_pred = normalize_predicate_name(subject[0]) if subject else "Agent"
    exception_preds = [normalize_predicate_name(item) for item in element.get("exceptions", [])[:3]]
    override_preds = [normalize_predicate_name(item) for item in element.get("override_clauses", [])[:3]]
    mental_state_pred = normalize_predicate_name(element.get("mental_state", ""))
    temporal_preds = [
        normalize_predicate_name(f"{item.get('type', 'Temporal')} {item.get('value', '')}")
        for item in element.get("temporal_constraints", [])[:3]
        if isinstance(item, dict)
    ]
    modifiers = temporal_preds
    if mental_state_pred and mental_state_pred != "P":
        modifiers.append(mental_state_pred)
    modifiers.extend(override_preds)

    if conditions:
        condition_pred = normalize_predicate_name(conditions[0])
        inner = f"{subject_pred}(x) ∧ {condition_pred}(x)"
        if modifiers:
            inner += " ∧ " + " ∧ ".join(f"{pred}(x)" for pred in modifiers)
        if exception_preds:
            inner += " ∧ " + " ∧ ".join(f"¬{pred}(x)" for pred in exception_preds)
        return f"{operator}(∀x ({inner} → {action_pred}(x)))"

    inner = f"{subject_pred}(x)"
    if modifiers:
        inner += " ∧ " + " ∧ ".join(f"{pred}(x)" for pred in modifiers)
    if exception_preds:
        inner += " ∧ " + " ∧ ".join(f"¬{pred}(x)" for pred in exception_preds)
    return f"{operator}(∀x ({inner} → {action_pred}(x)))"


def normalize_predicate_name(name: str) -> str:
    if not name:
        return "P"
    name = re.sub(r"[^\w\s]", "", name)
    words = name.strip().split()
    filtered_words = [
        w
        for w in words
        if w.lower() not in ["the", "a", "an", "of", "in", "on", "at", "to", "for", "with", "by"]
    ]
    if not filtered_words:
        return "P"
    return "".join(word.capitalize() for word in filtered_words)


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
    action1 = elem1.get("action", "").lower().strip()
    action2 = elem2.get("action", "").lower().strip()
    subject1 = elem1.get("subject", "").lower().strip()
    subject2 = elem2.get("subject", "").lower().strip()
    
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
