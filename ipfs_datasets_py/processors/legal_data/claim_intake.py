"""Claim-type intake requirements for structured legal intake coverage."""

from __future__ import annotations

from typing import Any, Dict, List


CLAIM_INTAKE_REQUIREMENTS: Dict[str, Dict[str, Any]] = {
    "employment_discrimination": {
        "label": "Employment Discrimination",
        "actor_roles": ["complainant", "employer", "supervisor", "hr"],
        "evidence_classes": [
            "email",
            "text_message",
            "hr_complaint",
            "termination_notice",
            "discipline_record",
            "witness_statement",
            "comparator_record",
        ],
        "elements": [
            {
                "element_id": "protected_trait",
                "label": "Protected trait or class",
                "blocking": True,
                "keywords": ["race", "sex", "gender", "disability", "religion", "pregnan", "national origin", "age"],
                "fact_types": [],
                "actor_roles": ["complainant"],
                "evidence_classes": ["testimony", "personnel_record"],
            },
            {
                "element_id": "employment_relationship",
                "label": "Employment relationship or workplace context",
                "blocking": True,
                "keywords": ["employer", "job", "workplace", "supervisor", "manager", "hr", "company"],
                "fact_types": ["responsible_party"],
                "actor_roles": ["employer", "supervisor", "hr"],
                "evidence_classes": ["offer_letter", "org_chart", "pay_stub", "witness_statement"],
            },
            {
                "element_id": "adverse_action",
                "label": "Adverse employment action or harassment",
                "blocking": True,
                "keywords": ["fired", "terminated", "demoted", "harass", "disciplined", "suspended"],
                "fact_types": ["impact"],
                "actor_roles": ["employer", "supervisor"],
                "evidence_classes": ["termination_notice", "discipline_record", "witness_statement"],
            },
            {
                "element_id": "discriminatory_motive",
                "label": "Facts suggesting discriminatory motive",
                "blocking": True,
                "keywords": ["because of", "discrimination", "treated differently", "bias", "slur"],
                "fact_types": [],
                "actor_roles": ["supervisor", "coworker", "comparator"],
                "evidence_classes": ["email", "text_message", "witness_statement", "comparator_record"],
            },
        ],
    },
    "housing_discrimination": {
        "label": "Housing Discrimination",
        "actor_roles": ["complainant", "landlord", "property_manager", "housing_provider"],
        "evidence_classes": ["lease", "denial_notice", "accommodation_request", "landlord_message", "inspection_record"],
        "elements": [
            {
                "element_id": "protected_trait",
                "label": "Protected trait or class",
                "blocking": True,
                "keywords": ["race", "sex", "gender", "disability", "religion", "familial status", "national origin"],
                "fact_types": [],
            },
            {
                "element_id": "housing_context",
                "label": "Housing relationship or tenancy context",
                "blocking": True,
                "keywords": ["landlord", "tenant", "lease", "apartment", "housing", "rent", "property manager"],
                "fact_types": ["responsible_party"],
            },
            {
                "element_id": "adverse_action",
                "label": "Discriminatory housing action",
                "blocking": True,
                "keywords": ["denied", "refused", "evict", "raised rent", "steered", "harass", "failed to repair"],
                "fact_types": ["impact"],
            },
            {
                "element_id": "discriminatory_motive",
                "label": "Facts suggesting discriminatory motive",
                "blocking": True,
                "keywords": ["because of", "discrimination", "treated differently", "bias", "slur"],
                "fact_types": [],
            },
        ],
    },
    "retaliation": {
        "label": "Retaliation",
        "actor_roles": ["complainant", "decision_maker", "report_recipient"],
        "evidence_classes": ["complaint_record", "timeline_record", "email", "witness_statement"],
        "elements": [
            {
                "element_id": "protected_activity",
                "label": "Protected activity",
                "blocking": True,
                "keywords": ["complained", "reported", "requested accommodation", "opposed", "grievance", "hr"],
                "fact_types": [],
            },
            {
                "element_id": "adverse_action",
                "label": "Adverse action",
                "blocking": True,
                "keywords": ["fired", "terminated", "suspended", "cut hours", "evict", "retaliat"],
                "fact_types": ["impact"],
            },
            {
                "element_id": "causation",
                "label": "Timing or facts connecting activity to retaliation",
                "blocking": True,
                "keywords": ["after i complained", "after i reported", "shortly after", "because i reported"],
                "fact_types": ["timeline"],
            },
        ],
    },
    "termination": {
        "label": "Termination",
        "actor_roles": ["complainant", "employer", "decision_maker"],
        "evidence_classes": ["termination_notice", "personnel_record", "email", "witness_statement"],
        "elements": [
            {
                "element_id": "termination_event",
                "label": "Termination event",
                "blocking": True,
                "keywords": ["fired", "terminated", "let go", "dismissed"],
                "fact_types": ["impact"],
            },
            {
                "element_id": "responsible_actor",
                "label": "Responsible actor or employer",
                "blocking": True,
                "keywords": ["employer", "manager", "supervisor", "company", "landlord"],
                "fact_types": ["responsible_party"],
            },
            {
                "element_id": "timing_or_reason",
                "label": "Timing or stated reason",
                "blocking": False,
                "keywords": ["after", "because", "on", "date", "timeline"],
                "fact_types": ["timeline"],
            },
        ],
    },
}


CLAIM_TYPE_ALIASES = {
    "wrongful_termination": "termination",
    "fair_housing_discrimination": "housing_discrimination",
}


def normalize_claim_type(claim_type: Any) -> str:
    normalized = "".join(ch.lower() if str(ch).isalnum() else "_" for ch in str(claim_type or "")).strip("_")
    return CLAIM_TYPE_ALIASES.get(normalized, normalized or "unknown")


def registry_for_claim_type(claim_type: Any) -> Dict[str, Any]:
    normalized = normalize_claim_type(claim_type)
    return CLAIM_INTAKE_REQUIREMENTS.get(normalized, {"label": normalized.replace("_", " ").title(), "elements": []})


def registry_element_for_claim_type(claim_type: Any, element_id: Any) -> Dict[str, Any]:
    registry = registry_for_claim_type(claim_type)
    normalized_element_id = str(element_id or "").strip().lower()
    for element in registry.get("elements", []):
        if str(element.get("element_id") or "").strip().lower() == normalized_element_id:
            return element
    return {}


def _unique_strings(values: List[Any]) -> List[str]:
    seen = set()
    result: List[str] = []
    for value in values:
        normalized = str(value or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _combined_case_text(candidate_claim: Dict[str, Any], canonical_facts: List[Dict[str, Any]], source_text: str) -> str:
    parts = [str(source_text or ""), str(candidate_claim.get("description") or ""), str(candidate_claim.get("label") or "")]
    for fact in canonical_facts:
        if isinstance(fact, dict):
            parts.append(str(fact.get("text") or ""))
    return " ".join(part for part in parts if part).lower()


def _has_fact_type(canonical_facts: List[Dict[str, Any]], fact_types: List[str]) -> bool:
    normalized_fact_types = {str(item or "").strip().lower() for item in fact_types if item}
    if not normalized_fact_types:
        return False
    for fact in canonical_facts:
        if not isinstance(fact, dict):
            continue
        if str(fact.get("fact_type") or "").strip().lower() in normalized_fact_types:
            return True
    return False


def refresh_required_elements(
    candidate_claim: Dict[str, Any],
    canonical_facts: List[Dict[str, Any]],
    source_text: str,
) -> List[Dict[str, Any]]:
    registry = registry_for_claim_type(candidate_claim.get("claim_type"))
    combined_text = _combined_case_text(candidate_claim, canonical_facts, source_text)
    required_elements: List[Dict[str, Any]] = []
    for element in registry.get("elements", []):
        keywords = [str(keyword).lower() for keyword in (element.get("keywords") or []) if keyword]
        fact_types = [str(fact_type).lower() for fact_type in (element.get("fact_types") or []) if fact_type]
        tagged_present = any(
            str(element.get("element_id") or "").strip().lower()
            in {str(tag).strip().lower() for tag in (fact.get("element_tags") or [])}
            for fact in canonical_facts
            if isinstance(fact, dict)
        )
        present = tagged_present or any(keyword in combined_text for keyword in keywords) or _has_fact_type(canonical_facts, fact_types)
        required_elements.append(
            {
                "element_id": element.get("element_id"),
                "label": element.get("label"),
                "blocking": bool(element.get("blocking", False)),
                "status": "present" if present else "missing",
            }
        )
    return required_elements


def match_required_element_id(claim_type: Any, text: Any) -> str:
    registry = registry_for_claim_type(claim_type)
    normalized_text = str(text or "").strip().lower()
    if not normalized_text:
        return ""
    for element in registry.get("elements", []):
        element_id = str(element.get("element_id") or "").strip()
        label = str(element.get("label") or "").strip().lower()
        if not element_id:
            continue
        if element_id.lower() in normalized_text or label in normalized_text:
            return element_id
        label_terms = [term for term in label.replace("/", " ").split() if len(term) > 3]
        if label_terms and any(term in normalized_text for term in label_terms):
            return element_id
    return ""


def build_claim_element_question_text(claim_type: Any, claim_label: Any, element_id: Any, element_label: Any) -> str:
    intent = build_claim_element_question_intent(
        claim_type,
        claim_label,
        {"element_id": element_id, "label": element_label},
    )
    return render_question_text_from_intent(intent)


def build_claim_element_question_intent(claim_type: Any, claim_label: Any, element: Dict[str, Any]) -> Dict[str, Any]:
    normalized_claim_type = normalize_claim_type(claim_type)
    normalized_claim_label = str(claim_label or normalized_claim_type or "this claim").strip() or "this claim"
    normalized_element_id = str(element.get("element_id") or "").strip().lower()
    normalized_element_label = str(element.get("label") or normalized_element_id or "this missing element").strip()
    registry = registry_for_claim_type(normalized_claim_type)
    registry_element = registry_element_for_claim_type(normalized_claim_type, normalized_element_id)
    return {
        "intent_type": "claim_element_question",
        "question_goal": "establish_element",
        "claim_type": normalized_claim_type,
        "claim_label": normalized_claim_label,
        "target_element_id": normalized_element_id,
        "target_element_label": normalized_element_label or str(registry_element.get("label") or normalized_element_id),
        "blocking": bool(element.get("blocking", registry_element.get("blocking", False))),
        "actor_roles": _unique_strings(
            list(element.get("actor_roles", []) or [])
            + list(registry_element.get("actor_roles", []) or [])
            + list(registry.get("actor_roles", []) or [])
        ),
        "evidence_classes": _unique_strings(
            list(element.get("evidence_classes", []) or [])
            + list(registry_element.get("evidence_classes", []) or [])
            + list(registry.get("evidence_classes", []) or [])
        ),
        "question_strategy": "ontology_guided_element_probe",
    }


def build_proof_lead_question_text(claim_type: Any, claim_label: Any) -> str:
    return render_question_text_from_intent(build_proof_lead_question_intent(claim_type, claim_label))


def build_proof_lead_question_intent(claim_type: Any, claim_label: Any) -> Dict[str, Any]:
    normalized_claim_type = normalize_claim_type(claim_type)
    normalized_claim_label = str(claim_label or normalized_claim_type or "this claim").strip() or "this claim"
    registry = registry_for_claim_type(normalized_claim_type)
    return {
        "intent_type": "proof_lead_question",
        "question_goal": "identify_supporting_proof",
        "claim_type": normalized_claim_type,
        "claim_label": normalized_claim_label,
        "actor_roles": _unique_strings(list(registry.get("actor_roles", []) or [])),
        "evidence_classes": _unique_strings(list(registry.get("evidence_classes", []) or [])),
        "question_strategy": "ontology_guided_proof_probe",
    }


def render_question_text_from_intent(intent: Dict[str, Any]) -> str:
    normalized_intent = intent if isinstance(intent, dict) else {}
    intent_type = str(normalized_intent.get("intent_type") or "").strip().lower()
    claim_label = str(normalized_intent.get("claim_label") or normalized_intent.get("claim_type") or "this claim").strip() or "this claim"
    claim_type = normalize_claim_type(normalized_intent.get("claim_type"))
    actor_roles = [str(role).replace("_", " ") for role in (normalized_intent.get("actor_roles") or []) if role]
    evidence_classes = [str(kind) for kind in (normalized_intent.get("evidence_classes") or []) if kind]
    target_element_id = str(normalized_intent.get("target_element_id") or "").strip().lower()
    target_element_label = str(normalized_intent.get("target_element_label") or target_element_id or "this missing element").strip()

    if intent_type == "claim_element_question":
        prompt_map = {
            ("employment_discrimination", "protected_trait"): "For {claim_label}, what protected trait or class applies here, and how do you want it described?",
            ("employment_discrimination", "employment_relationship"): "For {claim_label}, who was the employer or supervisor involved, and what was your workplace relationship to them?",
            ("employment_discrimination", "adverse_action"): "For {claim_label}, what adverse job action or workplace harassment happened to you?",
            ("housing_discrimination", "housing_context"): "For {claim_label}, who was the landlord, property manager, or housing provider, and what was your housing or tenancy situation?",
            ("retaliation", "causation"): "For {claim_label}, what facts or timing connect your protected activity to the retaliation?",
        }
        template = prompt_map.get((claim_type, target_element_id))
        if template:
            return template.format(claim_label=claim_label)
        if actor_roles:
            return f"For {claim_label}, what facts involving {', '.join(actor_roles[:3])} show {target_element_label.lower()}?"
        return f"For {claim_label}, what facts show {target_element_label.lower()}?"

    if intent_type == "proof_lead_question":
        if evidence_classes:
            rendered_classes = ", ".join(_render_evidence_classes_for_prompt(evidence_classes))
            return f"For {claim_label}, what proof do you have, such as {rendered_classes}, or other sources that support your account?"
        return f"For {claim_label}, what documents, messages, witnesses, or other proof leads support your account?"

    return f"For {claim_label}, what additional details would help support your account?"


def _render_evidence_classes_for_prompt(evidence_classes: List[str]) -> List[str]:
    values = {str(item or "").strip().lower() for item in evidence_classes if item}
    rendered: List[str] = []
    label_map = {
        "email": "emails",
        "text_message": "texts",
        "hr_complaint": "HR complaint",
        "witness_statement": "witness names",
        "comparator_record": "comparator records",
        "lease": "lease",
        "denial_notice": "denial notice",
        "accommodation_request": "accommodation request",
        "landlord_message": "landlord messages",
        "inspection_record": "inspection records",
        "complaint_record": "complaint records",
        "timeline_record": "timing records",
        "personnel_record": "personnel records",
        "termination_notice": "termination notice",
    }
    for item in evidence_classes:
        normalized = str(item or "").strip().lower()
        if normalized not in values:
            continue
        rendered.append(label_map.get(normalized, normalized.replace("_", " ")))
        values.discard(normalized)
        if len(rendered) >= 5:
            break
    return rendered[:5]


__all__ = [
    "CLAIM_INTAKE_REQUIREMENTS",
    "build_claim_element_question_intent",
    "build_claim_element_question_text",
    "build_proof_lead_question_intent",
    "build_proof_lead_question_text",
    "match_required_element_id",
    "normalize_claim_type",
    "refresh_required_elements",
    "registry_element_for_claim_type",
    "registry_for_claim_type",
    "render_question_text_from_intent",
]
