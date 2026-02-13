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
    
    # Check for temporal conflicts
    temporal_conflict = _check_temporal_conflict(elem1, elem2)
    if temporal_conflict:
        return temporal_conflict
    
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
