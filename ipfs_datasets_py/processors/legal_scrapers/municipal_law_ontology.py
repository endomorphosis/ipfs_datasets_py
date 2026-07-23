"""Municipal-law ontology contract for KG, frame logic, and deontic logic.

The ontology is intentionally explicit and conservative. LLM-router output may
propose extensions, but graph generation should only accept extensions that fit
these classes/predicates and preserve deterministic IDs.
"""

from __future__ import annotations

from copy import deepcopy
import json
import re
from typing import Any, Dict, Iterable, List, Mapping, Optional

ONTOLOGY_VERSION = "municipal-law-kg-v3"


BASE_CLASSES: List[Dict[str, Any]] = [
    {"id": "Thing", "label": "Thing", "parent": None},
    {"id": "LegalArtifact", "label": "Legal artifact", "parent": "Thing"},
    {"id": "MunicipalCodeSection", "label": "Municipal code section", "parent": "LegalArtifact"},
    {"id": "MunicipalCodeChapter", "label": "Municipal code chapter", "parent": "LegalArtifact"},
    {"id": "MunicipalCodeTitle", "label": "Municipal code title", "parent": "LegalArtifact"},
    {"id": "LegalAuthority", "label": "Legal authority", "parent": "LegalArtifact"},
    {"id": "Ordinance", "label": "Ordinance", "parent": "LegalAuthority"},
    {"id": "StateStatute", "label": "State statute", "parent": "LegalAuthority"},
    {"id": "AdministrativeRule", "label": "Administrative rule", "parent": "LegalAuthority"},
    {"id": "DefinedTerm", "label": "Defined term", "parent": "LegalArtifact"},
    {"id": "LegalNorm", "label": "Legal norm", "parent": "Thing"},
    {"id": "Obligation", "label": "Obligation", "parent": "LegalNorm"},
    {"id": "Prohibition", "label": "Prohibition", "parent": "LegalNorm"},
    {"id": "Permission", "label": "Permission", "parent": "LegalNorm"},
    {"id": "AuthorityGrant", "label": "Authority grant", "parent": "LegalNorm"},
    {"id": "DefinitionNorm", "label": "Definition norm", "parent": "LegalNorm"},
    {"id": "LegalActor", "label": "Legal actor", "parent": "Thing"},
    {"id": "GovernmentActor", "label": "Government actor", "parent": "LegalActor"},
    {"id": "Municipality", "label": "Municipality", "parent": "GovernmentActor"},
    {"id": "MunicipalAgency", "label": "Municipal agency", "parent": "GovernmentActor"},
    {"id": "LegislativeBody", "label": "Legislative body", "parent": "GovernmentActor"},
    {"id": "MunicipalOfficial", "label": "Municipal official", "parent": "GovernmentActor"},
    {"id": "RegulatedActor", "label": "Regulated actor", "parent": "LegalActor"},
    {"id": "LegalPerson", "label": "Legal person", "parent": "RegulatedActor"},
    {"id": "BusinessEntity", "label": "Business entity", "parent": "RegulatedActor"},
    {"id": "PropertyActor", "label": "Property actor", "parent": "RegulatedActor"},
    {"id": "Worker", "label": "Worker", "parent": "RegulatedActor"},
    {"id": "Resident", "label": "Resident", "parent": "RegulatedActor"},
    {"id": "Process", "label": "Process", "parent": "Thing"},
    {"id": "AdministrativeProcess", "label": "Administrative process", "parent": "Process"},
    {"id": "PermitProcess", "label": "Permit process", "parent": "AdministrativeProcess"},
    {"id": "LicenseProcess", "label": "License process", "parent": "AdministrativeProcess"},
    {"id": "AppealProcess", "label": "Appeal process", "parent": "AdministrativeProcess"},
    {"id": "EnforcementProcess", "label": "Enforcement process", "parent": "AdministrativeProcess"},
    {"id": "InspectionProcess", "label": "Inspection process", "parent": "AdministrativeProcess"},
    {"id": "RegulatedSubject", "label": "Regulated subject", "parent": "Thing"},
    {"id": "RegulatedActivity", "label": "Regulated activity", "parent": "RegulatedSubject"},
    {"id": "RegulatedProperty", "label": "Regulated property", "parent": "RegulatedSubject"},
    {"id": "AuthorizationInstrument", "label": "Authorization instrument", "parent": "RegulatedSubject"},
    {"id": "Permit", "label": "Permit", "parent": "AuthorizationInstrument"},
    {"id": "License", "label": "License", "parent": "AuthorizationInstrument"},
    {"id": "FinancialObligation", "label": "Financial obligation", "parent": "RegulatedSubject"},
    {"id": "Sanction", "label": "Sanction", "parent": "RegulatedSubject"},
    {"id": "LegalViolation", "label": "Legal violation", "parent": "RegulatedSubject"},
    {"id": "PublicProperty", "label": "Public property", "parent": "RegulatedProperty"},
    {"id": "LandUseControl", "label": "Land use control", "parent": "RegulatedSubject"},
    {"id": "PublicSafetySubject", "label": "Public safety subject", "parent": "RegulatedSubject"},
    {"id": "MunicipalService", "label": "Municipal service", "parent": "RegulatedSubject"},
]


BASE_PREDICATES: List[Dict[str, Any]] = [
    {"id": "PART_OF_TITLE", "domain": "MunicipalCodeChapter|MunicipalCodeSection", "range": "MunicipalCodeTitle", "flogic": "partOfTitle"},
    {"id": "PART_OF_CHAPTER", "domain": "MunicipalCodeSection", "range": "MunicipalCodeChapter", "flogic": "partOfChapter"},
    {"id": "REFERENCES_LEGAL_AUTHORITY", "domain": "MunicipalCodeSection", "range": "LegalAuthority", "flogic": "referencesAuthority"},
    {"id": "REFERENCES_CODE_SECTION", "domain": "MunicipalCodeSection", "range": "LegalAuthority", "flogic": "referencesCodeSection"},
    {"id": "REFERENCES_SECTION_CID", "domain": "MunicipalCodeSection", "range": "MunicipalCodeSection", "flogic": "referencesSection"},
    {"id": "AMENDED_BY", "domain": "MunicipalCodeSection", "range": "Ordinance", "flogic": "amendedBy"},
    {"id": "DEFINES_TERM", "domain": "MunicipalCodeSection", "range": "DefinedTerm", "flogic": "definesTerm"},
    {"id": "MENTIONS_ACTOR", "domain": "MunicipalCodeSection", "range": "LegalActor", "flogic": "mentionsActor"},
    {"id": "REGULATES_SUBJECT", "domain": "MunicipalCodeSection", "range": "RegulatedSubject", "flogic": "regulatesSubject"},
    {"id": "GOVERNS_AUTHORIZATION", "domain": "MunicipalCodeSection", "range": "AuthorizationInstrument", "flogic": "governsAuthorization"},
    {"id": "IMPOSES_DUTY", "domain": "MunicipalCodeSection", "range": "Obligation", "deontic": "O(action)"},
    {"id": "IMPOSES_DUTY_ON", "domain": "MunicipalCodeSection", "range": "LegalActor", "deontic": "O(actor, action)"},
    {"id": "PROHIBITS", "domain": "MunicipalCodeSection", "range": "Prohibition", "deontic": "F(action)"},
    {"id": "GRANTS_AUTHORITY", "domain": "MunicipalCodeSection", "range": "AuthorityGrant", "deontic": "P(actor, action)"},
    {"id": "GRANTS_AUTHORITY_TO", "domain": "MunicipalCodeSection", "range": "GovernmentActor|LegalActor", "deontic": "P(actor, action)"},
    {"id": "CREATES_PROCESS", "domain": "MunicipalCodeSection", "range": "AdministrativeProcess", "flogic": "createsProcess"},
    {"id": "HAS_TRIGGER", "domain": "LegalNorm", "range": "Process|RegulatedSubject", "tdfol": "trigger(norm, condition)"},
    {"id": "HAS_EXCEPTION", "domain": "LegalNorm", "range": "LegalNorm|RegulatedSubject", "tdfol": "unless(norm, exception)"},
    {"id": "HAS_CONDITION", "domain": "LegalNorm", "range": "RegulatedSubject|Process", "tdfol": "condition(norm, condition)"},
    {"id": "HAS_DEADLINE", "domain": "LegalNorm|AdministrativeProcess", "range": "TemporalConstraint", "tdfol": "deadline(norm, time)"},
]


BASE_ACTOR_LEXICON: Dict[str, str] = {
    "applicant": "LegalActor",
    "auditor": "MunicipalOfficial",
    "bureau": "MunicipalAgency",
    "business": "BusinessEntity",
    "city": "Municipality",
    "city administrator": "MunicipalOfficial",
    "city attorney": "MunicipalOfficial",
    "city council": "LegislativeBody",
    "city official": "MunicipalOfficial",
    "contractor": "BusinessEntity",
    "director": "MunicipalOfficial",
    "employee": "Worker",
    "employer": "BusinessEntity",
    "enforcement officer": "MunicipalOfficial",
    "fire marshal": "MunicipalOfficial",
    "inspector": "MunicipalOfficial",
    "landlord": "PropertyActor",
    "licensee": "BusinessEntity",
    "manager": "MunicipalOfficial",
    "officer": "MunicipalOfficial",
    "owner": "PropertyActor",
    "permittee": "BusinessEntity",
    "person": "LegalPerson",
    "property owner": "PropertyActor",
    "tenant": "Resident",
    "worker": "Worker",
}


BASE_SUBJECT_LEXICON: Dict[str, str] = {
    "appeal": "AppealProcess",
    "application": "AdministrativeProcess",
    "building": "RegulatedProperty",
    "business license": "License",
    "city code": "LegalArtifact",
    "construction": "RegulatedActivity",
    "demolition": "RegulatedActivity",
    "development": "RegulatedActivity",
    "emergency": "PublicSafetySubject",
    "fee": "FinancialObligation",
    "hearing": "AdministrativeProcess",
    "inspection": "InspectionProcess",
    "license": "License",
    "nuisance": "RegulatedSubject",
    "penalty": "Sanction",
    "permit": "Permit",
    "property": "RegulatedProperty",
    "public works": "MunicipalService",
    "right-of-way": "PublicProperty",
    "tax": "FinancialObligation",
    "violation": "LegalViolation",
    "zoning": "LandUseControl",
}


NORM_PATTERNS: List[Dict[str, str]] = [
    {"id": "prohibition", "regex": r"\bshall\s+not\b|\bmust\s+not\b|\bmay\s+not\b|\bis\s+prohibited\b|\bare\s+prohibited\b", "class": "Prohibition", "predicate": "PROHIBITS"},
    {"id": "obligation", "regex": r"\bshall\b|\bmust\b|\bis\s+required\b|\bare\s+required\b", "class": "Obligation", "predicate": "IMPOSES_DUTY"},
    {"id": "authority_grant", "regex": r"\bmay\b|\bis\s+authorized\b|\bare\s+authorized\b|\bhas\s+authority\b", "class": "AuthorityGrant", "predicate": "GRANTS_AUTHORITY"},
    {"id": "definition", "regex": r"\bmeans\b|\bis defined as\b", "class": "DefinitionNorm", "predicate": "DEFINES"},
]


LOGIC_MAPPINGS: Dict[str, Any] = {
    "frame_logic": {
        "MunicipalCodeSection": "?Section:MunicipalCodeSection[sectionNumber => ?N, regulatesSubject => ?Subject].",
        "LegalActor": "?Actor:LegalActor[actorRole => ?Role].",
        "IMPOSES_DUTY_ON": "duty_applies(?Actor, ?Section) :- ?Section[imposesDutyOn -> ?Actor].",
        "GRANTS_AUTHORITY_TO": "authority_granted(?Actor, ?Section) :- ?Section[grantsAuthorityTo -> ?Actor].",
        "REFERENCES_SECTION_CID": "depends_on(?Section, ?Other) :- ?Section[referencesSection -> ?Other].",
    },
    "deontic": {
        "IMPOSES_DUTY_ON": "O(actor, comply_with(section))",
        "PROHIBITS": "F(actor, prohibited_action(section))",
        "GRANTS_AUTHORITY_TO": "P(actor, authorized_action(section))",
    },
    "tdfol": {
        "deadline": "G(trigger(norm) -> F_before(deadline, satisfied(norm)))",
        "exception": "G(exception(norm) -> not active(norm))",
    },
}


def build_base_municipal_ontology() -> Dict[str, Any]:
    """Return a deep copy of the municipal ontology contract."""

    return {
        "schema_version": "municipal-law-ontology-v1",
        "ontology_version": ONTOLOGY_VERSION,
        "description": "Municipal code ontology for KG extraction, frame logic, deontic logic, TDFOL, DCEC, and permit/workflow reasoning.",
        "classes": deepcopy(BASE_CLASSES),
        "predicates": deepcopy(BASE_PREDICATES),
        "actor_lexicon": deepcopy(BASE_ACTOR_LEXICON),
        "subject_lexicon": deepcopy(BASE_SUBJECT_LEXICON),
        "norm_patterns": deepcopy(NORM_PATTERNS),
        "logic_mappings": deepcopy(LOGIC_MAPPINGS),
    }


def _normalize_term(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def merge_llm_ontology_extensions(base: Mapping[str, Any], extension: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """Merge validated LLM-router ontology suggestions into *base*.

    Accepted extension keys:
    - actor_lexicon: term -> existing class id
    - subject_lexicon: term -> existing class id
    - classes: [{"id", "label", "parent"}], parent must already exist or be in extension
    - predicates: [{"id", "domain", "range"}]
    """

    merged = deepcopy(dict(base))
    if not extension:
        merged["llm_extension"] = {"accepted": False, "reason": "no_extension"}
        return merged

    class_ids = {str(item.get("id") or "") for item in list(merged.get("classes") or []) if isinstance(item, Mapping)}
    pending_classes = [dict(item) for item in list(extension.get("classes") or []) if isinstance(item, Mapping)]
    accepted_classes: List[Dict[str, Any]] = []
    for item in pending_classes:
        class_id = re.sub(r"[^A-Za-z0-9_]", "", str(item.get("id") or ""))
        parent = re.sub(r"[^A-Za-z0-9_]", "", str(item.get("parent") or "Thing"))
        if not class_id or class_id in class_ids or parent not in class_ids:
            continue
        accepted = {"id": class_id, "label": str(item.get("label") or class_id), "parent": parent, "source": "llm_router"}
        merged.setdefault("classes", []).append(accepted)
        class_ids.add(class_id)
        accepted_classes.append(accepted)

    accepted_actor_terms: Dict[str, str] = {}
    for term, class_id in dict(extension.get("actor_lexicon") or {}).items():
        normalized = _normalize_term(term)
        class_id = re.sub(r"[^A-Za-z0-9_]", "", str(class_id or ""))
        if normalized and class_id in class_ids:
            merged.setdefault("actor_lexicon", {})[normalized] = class_id
            accepted_actor_terms[normalized] = class_id

    accepted_subject_terms: Dict[str, str] = {}
    for term, class_id in dict(extension.get("subject_lexicon") or {}).items():
        normalized = _normalize_term(term)
        class_id = re.sub(r"[^A-Za-z0-9_]", "", str(class_id or ""))
        if normalized and class_id in class_ids:
            merged.setdefault("subject_lexicon", {})[normalized] = class_id
            accepted_subject_terms[normalized] = class_id

    predicate_ids = {str(item.get("id") or "") for item in list(merged.get("predicates") or []) if isinstance(item, Mapping)}
    accepted_predicates: List[Dict[str, Any]] = []
    for item in list(extension.get("predicates") or []):
        if not isinstance(item, Mapping):
            continue
        predicate_id = re.sub(r"[^A-Z0-9_]", "", str(item.get("id") or "").upper())
        if not predicate_id or predicate_id in predicate_ids:
            continue
        accepted = {
            "id": predicate_id,
            "domain": str(item.get("domain") or "Thing"),
            "range": str(item.get("range") or "Thing"),
            "flogic": str(item.get("flogic") or "").strip(),
            "source": "llm_router",
        }
        merged.setdefault("predicates", []).append(accepted)
        predicate_ids.add(predicate_id)
        accepted_predicates.append(accepted)

    merged["llm_extension"] = {
        "accepted": True,
        "accepted_class_count": len(accepted_classes),
        "accepted_actor_term_count": len(accepted_actor_terms),
        "accepted_subject_term_count": len(accepted_subject_terms),
        "accepted_predicate_count": len(accepted_predicates),
        "accepted_actor_terms": accepted_actor_terms,
        "accepted_subject_terms": accepted_subject_terms,
    }
    return merged


def extract_json_object(text: str) -> Optional[Dict[str, Any]]:
    """Extract the first JSON object from a router response."""

    raw = str(text or "").strip()
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        pass
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        return None


__all__ = [
    "ONTOLOGY_VERSION",
    "build_base_municipal_ontology",
    "merge_llm_ontology_extensions",
    "extract_json_object",
]
