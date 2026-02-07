"""Deontic logic parsing and formula generation utilities."""

import re
from typing import Any, Dict, List, Optional


def extract_normative_elements(text: str, document_type: str = "statute") -> List[Dict[str, Any]]:
    elements: List[Dict[str, Any]] = []
    sentences = re.split(r"[.!?]+", text)
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        element = analyze_normative_sentence(sentence, document_type)
        if element:
            elements.append(element)
    return elements


def analyze_normative_sentence(sentence: str, document_type: str) -> Optional[Dict[str, Any]]:
    sentence_lower = sentence.lower()

    obligation_indicators = ["must", "shall", "required to", "obligated to", "duty to"]
    permission_indicators = ["may", "can", "allowed to", "permitted to", "entitled to"]
    prohibition_indicators = ["must not", "shall not", "forbidden to", "prohibited from", "cannot"]

    norm_type = None
    deontic_operator = None

    if any(indicator in sentence_lower for indicator in obligation_indicators):
        norm_type = "obligation"
        deontic_operator = "O"
    elif any(indicator in sentence_lower for indicator in permission_indicators):
        norm_type = "permission"
        deontic_operator = "P"
    elif any(indicator in sentence_lower for indicator in prohibition_indicators):
        norm_type = "prohibition"
        deontic_operator = "F"
    else:
        return None

    subject = extract_legal_subject(sentence)
    action = extract_legal_action(sentence)
    conditions = extract_conditions(sentence)
    temporal_constraints = extract_temporal_constraints(sentence)
    exceptions = extract_exceptions(sentence)

    return {
        "text": sentence,
        "norm_type": norm_type,
        "deontic_operator": deontic_operator,
        "subject": subject,
        "action": action,
        "conditions": conditions,
        "temporal_constraints": temporal_constraints,
        "exceptions": exceptions,
        "document_type": document_type,
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
    conditions: List[str] = []
    condition_patterns = [
        r"\bif\s+([^,]+?)(?:,|\s+then)",
        r"\bwhen\s+([^,]+?)(?:,|\.)",
        r"\bwhere\s+([^,]+?)(?:,|\.)",
        r"\bprovided that\s+([^,]+?)(?:,|\.)",
        r"\bin case\s+([^,]+?)(?:,|\.)",
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
                constraints.append({"type": "deadline" if "by" in pattern else "period", "value": match.strip()})

    duration_pattern = r"\bfor\s+(\d+\s+(?:days?|weeks?|months?|years?))"
    for match in re.findall(duration_pattern, sentence.lower()):
        constraints.append({"type": "duration", "value": match.strip()})

    return constraints


def extract_exceptions(sentence: str) -> List[str]:
    exceptions: List[str] = []
    exception_patterns = [
        r"\bunless\s+([^,]+?)(?:,|\.)",
        r"\bexcept\s+(?:for\s+)?([^,]+?)(?:,|\.)",
        r"\bwith the exception of\s+([^,]+?)(?:,|\.)",
        r"\bother than\s+([^,]+?)(?:,|\.)",
        r"\bexcluding\s+([^,]+?)(?:,|\.)",
    ]
    for pattern in exception_patterns:
        exceptions.extend([m.strip() for m in re.findall(pattern, sentence.lower())])
    return exceptions


def build_deontic_formula(element: Dict[str, Any]) -> str:
    operator = element["deontic_operator"]
    subject = element.get("subject", ["X"])
    action = element.get("action", ["Action"])
    conditions = element.get("conditions", [])

    action_pred = normalize_predicate_name(action[0]) if action else "Action"
    subject_pred = normalize_predicate_name(subject[0]) if subject else "Agent"

    if conditions:
        condition_pred = normalize_predicate_name(conditions[0])
        return f"{operator}(∀x ({subject_pred}(x) ∧ {condition_pred}(x) → {action_pred}(x)))"

    return f"{operator}(∀x ({subject_pred}(x) → {action_pred}(x)))"


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
    # Placeholder conflict detection.
    # A real implementation would perform richer analysis.
    conflicts: List[Dict[str, Any]] = []
    for idx, element in enumerate(elements):
        _ = idx
        _ = element
    return conflicts
