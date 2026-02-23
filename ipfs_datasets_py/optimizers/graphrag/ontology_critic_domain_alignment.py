"""Domain alignment evaluation for OntologyCritic."""

from __future__ import annotations

from typing import Any, Dict


_DOMAIN_VOCAB: dict[str, set[str]] = {
    "legal": {
        "obligation", "party", "contract", "clause", "breach", "liability",
        "penalty", "jurisdiction", "provision", "agreement",
    },
    "medical": {
        "patient", "diagnosis", "treatment", "symptom", "medication",
        "procedure", "physician", "condition", "dosage", "outcome",
    },
    "technical": {
        "component", "service", "api", "endpoint", "module", "interface",
        "dependency", "version", "protocol", "event",
    },
    "financial": {
        "asset", "liability", "transaction", "account", "balance", "payment",
        "interest", "principal", "collateral", "risk",
    },
    "general": {
        "person", "organization", "location", "date", "event", "concept",
        "action", "property", "relation", "category",
    },
}


def evaluate_domain_alignment(ontology: Dict[str, Any], context: Any) -> float:
    """Evaluate how well entity types and relationship types align with domain vocabulary."""
    domain = (getattr(context, "domain", None) or ontology.get("domain", "general")).lower()
    vocab = _DOMAIN_VOCAB.get(domain, _DOMAIN_VOCAB["general"])

    entities = ontology.get("entities", [])
    relationships = ontology.get("relationships", [])

    if not entities:
        return 0.5

    # Check what fraction of entity types / rel types are in domain vocab
    ent_types = [e.get("type", "").lower() for e in entities if isinstance(e, dict)]
    rel_types = [r.get("type", "").lower() for r in relationships if isinstance(r, dict)]
    all_terms = ent_types + rel_types

    if not all_terms:
        return 0.5

    hits = sum(
        1 for t in all_terms
        if any(v in t or t in v for v in vocab)
    )
    score = hits / len(all_terms)
    return round(min(max(score, 0.0), 1.0), 4)
