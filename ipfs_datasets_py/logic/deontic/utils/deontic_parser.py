"""Deontic logic parsing and formula generation utilities.

This module is intentionally conservative.  It is a deterministic scaffold for
indexing, triage, and LLM prompting, not a substitute for an LLM/legal review
formalization pass.
"""

import re
from typing import Any, Dict, List, Optional


_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9(])")
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
    r"\s+(?:in accordance with|pursuant to|under|as provided in)\s+.+$",
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


def extract_normative_elements(text: str, document_type: str = "statute") -> List[Dict[str, Any]]:
    elements: List[Dict[str, Any]] = []
    sentences = _split_legal_sentences(text)
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        elements.extend(analyze_normative_sentence(sentence, document_type))
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


def analyze_normative_sentence(sentence: str, document_type: str) -> List[Dict[str, Any]]:
    sentence = sentence.strip()
    sentence_lower = sentence.lower()
    elements: List[Dict[str, Any]] = []

    for match in _MODAL_RE.finditer(sentence):
        modal = re.sub(r"\s+", " ", match.group("modal").lower()).strip()
        norm_type, deontic_operator = classify_modal(modal)
        raw_subject = match.group("subject")
        if deontic_operator == "O" and re.match(r"\s*(?:no|none)\b", raw_subject or "", flags=re.IGNORECASE):
            norm_type, deontic_operator = "prohibition", "F"
        subject_text = _clean_phrase(raw_subject)
        if subject_text.lower() in {"and", "or"}:
            continue
        action_text = _clean_action(match.group("action"))
        subject_text, action_text = _normalize_passive_clause(subject_text, action_text)
        if not action_text:
            continue
        elements.append(
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
        return elements

    if _DEFINITION_RE.search(sentence_lower):
        defined_term_match = _DEFINED_TERM_RE.search(sentence)
        defined_terms = [_clean_phrase(defined_term_match.group(1))] if defined_term_match else extract_legal_subject(sentence)
        return [
            {
                "text": sentence,
                "support_text": sentence,
                "support_span": [0, len(sentence)],
                "norm_type": "definition",
                "deontic_operator": "DEF",
                "modal": "definition",
                "subject": defined_terms,
                "action": [sentence],
                "conditions": extract_conditions(sentence),
                "temporal_constraints": extract_temporal_constraints(sentence),
                "exceptions": extract_exceptions(sentence),
                "document_type": document_type,
                "extraction_method": "deterministic_definition_v2",
                "confidence_floor": 0.25,
            }
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
    return {
        "text": sentence,
        "support_text": sentence[support_span[0] : support_span[1]].strip(),
        "support_span": list(support_span),
        "norm_type": norm_type,
        "deontic_operator": deontic_operator,
        "modal": modal,
        "subject": [subject_text] if subject_text else extract_legal_subject(sentence),
                "action": [action_text],
                "mental_state": _mental_state(action_text),
                "action_verb": _first_verb(action_text),
                "action_object": _action_object(action_text),
        "conditions": extract_conditions(sentence),
        "temporal_constraints": extract_temporal_constraints(sentence),
        "exceptions": extract_exceptions(sentence),
        "document_type": document_type,
        "extraction_method": extraction_method,
        "confidence_floor": 0.35,
    }


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
    conditions: List[str] = []
    condition_patterns = [
        r"\bif\s+([^,]+?)(?:,|\s+then|$)",
        r"\bwhen\s+([^,]+?)(?:,|\.|$)",
        r"\bwhere\s+([^,]+?)(?:,|\.|$)",
        r"\bprovided that\s+([^,]+?)(?:,|\.|$)",
        r"\bsubject to\s+([^,]+?)(?:,|\.|$)",
        r"\bin case\s+([^,]+?)(?:,|\.|$)",
    ]
    for pattern in condition_patterns:
        conditions.extend([m.strip() for m in re.findall(pattern, sentence.lower())])
    return conditions


def extract_temporal_constraints(sentence: str) -> List[Dict[str, str]]:
    constraints: List[Dict[str, str]] = []

    date_patterns = [
        r"\bby\s+((?:january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{1,2}(?:st|nd|rd|th)?(?:,?\s+\d{4})?)",
        r"\bby\s+(\d{1,2}/\d{1,2}/\d{2,4})",
        r"\bby\s+(\d{1,2}-\d{1,2}-\d{2,4})",
        r"\bwithin\s+(\d+\s+(?:days?|weeks?|months?|years?))",
        r"\bnot\s+later\s+than\s+(\d+\s+(?:days?|weeks?|months?|years?)(?:\s+after\s+[^,.;]+)?)",
        r"\bbefore\s+((?:january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{1,2})",
        r"\bafter\s+((?:january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{1,2})",
        r"\bannually\b",
        r"\bmonthly\b",
        r"\bweekly\b",
        r"\bdaily\b",
    ]

    for pattern in date_patterns:
        for match in re.findall(pattern, sentence.lower()):
            if isinstance(match, str):
                if "\\bwithin" in pattern:
                    constraint_type = "deadline"
                elif "\\bby" in pattern or "\\bbefore" in pattern or "not\\s+later\\s+than" in pattern:
                    constraint_type = "deadline"
                else:
                    constraint_type = "period"
                constraints.append({"type": constraint_type, "value": match.strip()})

    duration_pattern = r"\bfor\s+(\d+\s+(?:days?|weeks?|months?|years?))"
    for match in re.findall(duration_pattern, sentence.lower()):
        constraints.append({"type": "duration", "value": match.strip()})

    return constraints


def extract_exceptions(sentence: str) -> List[str]:
    exceptions: List[str] = []
    exception_patterns = [
        r"\bunless\s+([^,]+?)(?:,|\.|$)",
        r"\bexcept\s+(?:for\s+)?([^,]+?)(?:,|\.|$)",
        r"\bwithout\s+([^,]+?)(?:,|\.|$)",
        r"\babsent\s+([^,]+?)(?:,|\.|$)",
        r"\bwith the exception of\s+([^,]+?)(?:,|\.|$)",
        r"\bother than\s+([^,]+?)(?:,|\.|$)",
        r"\bexcluding\s+([^,]+?)(?:,|\.|$)",
    ]
    for pattern in exception_patterns:
        exceptions.extend([m.strip() for m in re.findall(pattern, sentence.lower())])
    return exceptions


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
    mental_state_pred = normalize_predicate_name(element.get("mental_state", ""))
    temporal_preds = [
        normalize_predicate_name(f"{item.get('type', 'Temporal')} {item.get('value', '')}")
        for item in element.get("temporal_constraints", [])[:3]
        if isinstance(item, dict)
    ]
    modifiers = temporal_preds
    if mental_state_pred and mental_state_pred != "P":
        modifiers.append(mental_state_pred)

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
