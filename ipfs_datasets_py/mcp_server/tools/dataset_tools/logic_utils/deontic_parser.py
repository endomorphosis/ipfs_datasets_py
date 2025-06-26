# ipfs_datasets_py/mcp_server/tools/dataset_tools/logic_utils/deontic_parser.py
"""
Deontic logic parsing and formula generation utilities.
"""
import re
from typing import List, Dict, Tuple, Any, Optional
from datetime import datetime, timedelta

def extract_normative_elements(text: str, document_type: str = "statute") -> List[Dict[str, Any]]:
    """
    Extract normative elements from legal text.
    
    Args:
        text: Legal text input
        document_type: Type of legal document
        
    Returns:
        List of normative element dictionaries
    """
    elements = []
    
    # Split text into sentences for analysis
    sentences = re.split(r'[.!?]+', text)
    
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
            
        element = analyze_normative_sentence(sentence, document_type)
        if element:
            elements.append(element)
    
    return elements

def analyze_normative_sentence(sentence: str, document_type: str) -> Optional[Dict[str, Any]]:
    """
    Analyze a single sentence for normative content.
    
    Args:
        sentence: Input sentence
        document_type: Type of legal document
        
    Returns:
        Normative element dictionary or None
    """
    sentence_lower = sentence.lower()
    
    # Check for normative indicators
    obligation_indicators = ['must', 'shall', 'required to', 'obligated to', 'duty to']
    permission_indicators = ['may', 'can', 'allowed to', 'permitted to', 'entitled to']
    prohibition_indicators = ['must not', 'shall not', 'forbidden to', 'prohibited from', 'cannot']
    
    norm_type = None
    deontic_operator = None
    
    # Determine normative type
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
        return None  # Not a normative sentence
    
    # Extract components
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
        "document_type": document_type
    }

def extract_legal_subject(sentence: str) -> List[str]:
    """Extract legal subjects (who the norm applies to)."""
    subjects = []
    
    # Common legal subject patterns
    subject_patterns = [
        r'\b(?:citizens?|residents?|persons?|individuals?|people)\b',
        r'\b(?:companies?|corporations?|businesses?|entities?)\b',
        r'\b(?:employees?|workers?|staff)\b',
        r'\b(?:drivers?|operators?|users?)\b',
        r'\b(?:owners?|lessees?|tenants?)\b',
        r'\b(?:students?|minors?|adults?)\b',
        r'\b(?:patients?|clients?|customers?)\b'
    ]
    
    for pattern in subject_patterns:
        matches = re.findall(pattern, sentence.lower())
        subjects.extend(matches)
    
    # Also look for specific named entities (would use NER in full implementation)
    capitalized_words = re.findall(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b', sentence)
    subjects.extend(capitalized_words[:2])  # Limit to avoid noise
    
    return list(set(subjects))

def extract_legal_action(sentence: str) -> List[str]:
    """Extract legal actions (what must/may/cannot be done)."""
    actions = []
    
    # Look for verbs after modal auxiliaries
    modal_verb_pattern = r'(?:must|shall|may|can|cannot|must not|shall not)\s+(?:not\s+)?(\w+(?:\s+\w+)*?)(?:\s+(?:by|before|after|until|unless|except)|\.|$)'
    matches = re.findall(modal_verb_pattern, sentence.lower())
    actions.extend([match.strip() for match in matches])
    
    # Look for specific legal action verbs
    legal_action_patterns = [
        r'\b(?:pay|file|submit|provide|deliver|execute|perform)\s+([^.]+?)(?:\s+(?:by|before|after)|\.|$)',
        r'\b(?:comply with|adhere to|follow|observe)\s+([^.]+?)(?:\s+(?:by|before|after)|\.|$)',
        r'\b(?:obtain|acquire|secure|maintain)\s+([^.]+?)(?:\s+(?:by|before|after)|\.|$)'
    ]
    
    for pattern in legal_action_patterns:
        matches = re.findall(pattern, sentence.lower())
        actions.extend([match.strip() for match in matches])
    
    return list(set(actions))

def extract_conditions(sentence: str) -> List[str]:
    """Extract conditions under which the norm applies."""
    conditions = []
    
    # Conditional patterns
    condition_patterns = [
        r'\bif\s+([^,]+?)(?:,|\s+then)',
        r'\bwhen\s+([^,]+?)(?:,|\.)',
        r'\bwhere\s+([^,]+?)(?:,|\.)',
        r'\bprovided that\s+([^,]+?)(?:,|\.)',
        r'\bin case\s+([^,]+?)(?:,|\.)'
    ]
    
    for pattern in condition_patterns:
        matches = re.findall(pattern, sentence.lower())
        conditions.extend([match.strip() for match in matches])
    
    return conditions

def extract_temporal_constraints(sentence: str) -> List[Dict[str, str]]:
    """Extract temporal constraints (deadlines, periods, etc.)."""
    constraints = []
    
    # Date patterns
    date_patterns = [
        r'\bby\s+((?:january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{1,2}(?:st|nd|rd|th)?(?:,?\s+\d{4})?)',
        r'\bby\s+(\d{1,2}/\d{1,2}/\d{2,4})',
        r'\bby\s+(\d{1,2}-\d{1,2}-\d{2,4})',
        r'\bwithin\s+(\d+\s+(?:days?|weeks?|months?|years?))',
        r'\bbefore\s+((?:january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{1,2})',
        r'\bafter\s+((?:january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{1,2})',
        r'\bannually\b',
        r'\bmonthly\b',
        r'\bweekly\b',
        r'\bdaily\b'
    ]
    
    for pattern in date_patterns:
        matches = re.findall(pattern, sentence.lower())
        for match in matches:
            if isinstance(match, str):
                constraints.append({
                    "type": "deadline" if "by" in pattern else "period",
                    "value": match.strip()
                })
    
    # Duration patterns
    duration_pattern = r'\bfor\s+(\d+\s+(?:days?|weeks?|months?|years?))'
    matches = re.findall(duration_pattern, sentence.lower())
    for match in matches:
        constraints.append({
            "type": "duration",
            "value": match.strip()
        })
    
    return constraints

def extract_exceptions(sentence: str) -> List[str]:
    """Extract exceptions and exemptions."""
    exceptions = []
    
    # Exception patterns
    exception_patterns = [
        r'\bunless\s+([^,]+?)(?:,|\.)',
        r'\bexcept\s+(?:for\s+)?([^,]+?)(?:,|\.)',
        r'\bwith the exception of\s+([^,]+?)(?:,|\.)',
        r'\bother than\s+([^,]+?)(?:,|\.)',
        r'\bexcluding\s+([^,]+?)(?:,|\.)'
    ]
    
    for pattern in exception_patterns:
        matches = re.findall(pattern, sentence.lower())
        exceptions.extend([match.strip() for match in matches])
    
    return exceptions

def build_deontic_formula(element: Dict[str, Any]) -> str:
    """
    Build a deontic logic formula from normative elements.
    
    Args:
        element: Normative element dictionary
        
    Returns:
        Deontic logic formula string
    """
    operator = element["deontic_operator"]
    subject = element.get("subject", ["X"])
    action = element.get("action", ["Action"])
    conditions = element.get("conditions", [])
    
    # Build predicate for action
    if action:
        action_pred = normalize_predicate_name(action[0])
    else:
        action_pred = "Action"
    
    # Build predicate for subject
    if subject:
        subject_pred = normalize_predicate_name(subject[0])
    else:
        subject_pred = "Agent"
    
    # Build basic formula
    if conditions:
        # With conditions: O(∀x (Citizen(x) ∧ Condition(x) → Action(x)))
        condition_pred = normalize_predicate_name(conditions[0])
        formula = f"{operator}(∀x ({subject_pred}(x) ∧ {condition_pred}(x) → {action_pred}(x)))"
    else:
        # Simple case: O(∀x (Citizen(x) → Action(x)))
        formula = f"{operator}(∀x ({subject_pred}(x) → {action_pred}(x)))"
    
    return formula

def normalize_predicate_name(name: str) -> str:
    """Normalize predicate names for deontic logic."""
    if not name:
        return "P"
    
    # Clean up the name
    name = re.sub(r'[^\w\s]', '', name)  # Remove punctuation
    words = name.strip().split()
    
    # Filter out common words
    filtered_words = [
        w for w in words 
        if w.lower() not in ['the', 'a', 'an', 'of', 'in', 'on', 'at', 'to', 'for', 'with', 'by']
    ]
    
    if not filtered_words:
        return "P"
    
    # Capitalize and join
    return ''.join(word.capitalize() for word in filtered_words)

def identify_obligations(elements: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Identify and categorize different types of obligations.
    
    Args:
        elements: List of normative elements
        
    Returns:
        Categorized obligations dictionary
    """
    categorized = {
        "obligations": [],
        "permissions": [],
        "prohibitions": [],
        "conditional_norms": [],
        "temporal_norms": []
    }
    
    for element in elements:
        norm_type = element.get("norm_type")
        
        if norm_type == "obligation":
            categorized["obligations"].append(element)
        elif norm_type == "permission":
            categorized["permissions"].append(element)
        elif norm_type == "prohibition":
            categorized["prohibitions"].append(element)
        
        # Check for conditions
        if element.get("conditions"):
            categorized["conditional_norms"].append(element)
        
        # Check for temporal constraints
        if element.get("temporal_constraints"):
            categorized["temporal_norms"].append(element)
    
    return categorized

def detect_normative_conflicts(elements: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Detect potential conflicts between normative statements.
    
    Args:
        elements: List of normative elements
        
    Returns:
        List of detected conflicts
    """
    conflicts = []
    
    for i, elem1 in enumerate(elements):
        for j, elem2 in enumerate(elements[i+1:], i+1):
            # Check for conflicting norms on same action
            if (elem1.get("action") == elem2.get("action") and 
                elem1.get("subject") == elem2.get("subject")):
                
                # Obligation vs Permission conflict
                if (elem1.get("norm_type") == "obligation" and 
                    elem2.get("norm_type") == "prohibition"):
                    conflicts.append({
                        "type": "obligation_prohibition_conflict",
                        "elements": [elem1, elem2],
                        "description": f"Obligation conflicts with prohibition for same action"
                    })
                
                # Permission vs Prohibition conflict  
                elif (elem1.get("norm_type") == "permission" and 
                      elem2.get("norm_type") == "prohibition"):
                    conflicts.append({
                        "type": "permission_prohibition_conflict", 
                        "elements": [elem1, elem2],
                        "description": f"Permission conflicts with prohibition for same action"
                    })
    
    return conflicts
