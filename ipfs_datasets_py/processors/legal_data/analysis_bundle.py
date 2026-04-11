"""High-level legal analysis orchestration helpers."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from ...logic.deontic import DeonticGraphBuilder
from .case_knowledge import analyze_case_graph_gaps, build_case_knowledge_graph, summarize_case_graph
from .claim_intake import normalize_claim_type, refresh_required_elements
from .dependency_graph import DependencyGraphBuilder
from .document_structure import parse_legal_document, summarize_formal_document
from .neurosymbolic import NeurosymbolicMatcher
from .requirements_graph import LegalRequirementsGraphBuilder
from .support_map import SupportMapBuilder


def build_legal_analysis_bundle(
    *,
    claim_type: Any,
    claim_label: Any = "",
    source_text: str = "",
    canonical_facts: Optional[List[Dict[str, Any]]] = None,
    document_text: str = "",
    case_entities: Optional[Sequence[Dict[str, Any]]] = None,
    case_relationships: Optional[Sequence[Dict[str, Any]]] = None,
    deontic_statements: Optional[Sequence[Dict[str, Any]]] = None,
    statutes: Optional[Sequence[Dict[str, Any]]] = None,
    fact_catalog: Optional[Dict[str, Dict[str, Any]]] = None,
    filing_map: Optional[Dict[str, Sequence[Dict[str, Any]]]] = None,
) -> Dict[str, Any]:
    """Build a normalized multi-graph legal analysis bundle."""

    normalized_claim_type = normalize_claim_type(claim_type)
    normalized_claim_label = str(claim_label or normalized_claim_type.replace("_", " ").title()).strip()
    facts = list(canonical_facts or [])

    required_elements = refresh_required_elements(
        {"claim_type": normalized_claim_type, "label": normalized_claim_label, "description": source_text},
        facts,
        source_text,
    )

    dependency_graph = DependencyGraphBuilder().build_for_claim(
        normalized_claim_type,
        claim_id="claim_1",
        claim_name=normalized_claim_label,
    )
    dependency_graph = DependencyGraphBuilder().apply_element_statuses(
        dependency_graph,
        required_elements=required_elements,
        claim_type=normalized_claim_type,
    )

    case_graph = build_case_knowledge_graph(
        entities=list(case_entities or []),
        relationships=list(case_relationships or []),
        source="case_bundle",
    )
    case_graph_summary = summarize_case_graph(case_graph)
    case_graph_gaps = analyze_case_graph_gaps(case_graph)

    parsed_document = parse_legal_document(document_text) if document_text else None
    document_summary = summarize_formal_document(document_text) if document_text else None

    legal_graph_builder = LegalRequirementsGraphBuilder()
    if statutes:
        legal_graph = legal_graph_builder.build_from_statutes(list(statutes), [normalized_claim_type])
    else:
        legal_graph = legal_graph_builder.build_rules_of_procedure("federal")
        for element in legal_graph.elements.values():
            if element.element_type in {"requirement", "procedural_requirement"}:
                element.attributes.setdefault("applicable_claim_types", [normalized_claim_type])

    deontic_graph = DeonticGraphBuilder().build_from_statements(list(deontic_statements or []))
    support_map = SupportMapBuilder().build_from_deontic_graph(
        deontic_graph,
        fact_catalog=dict(fact_catalog or {}),
        filing_map=dict(filing_map or {}),
        only_active=False,
    )

    neurosymbolic_result = NeurosymbolicMatcher().match_claims_to_law(
        case_graph,
        dependency_graph,
        legal_graph,
    )

    return {
        "claim_type": normalized_claim_type,
        "claim_label": normalized_claim_label,
        "required_elements": required_elements,
        "dependency_graph": dependency_graph.to_dict(),
        "dependency_readiness": dependency_graph.get_claim_readiness(),
        "case_graph": case_graph.to_dict(),
        "case_graph_summary": case_graph_summary,
        "case_graph_gaps": case_graph_gaps,
        "document_structure": parsed_document.to_dict() if parsed_document else None,
        "document_summary": document_summary,
        "legal_requirements_graph": legal_graph.to_dict(),
        "deontic_graph": deontic_graph.to_dict(),
        "support_map": support_map.to_dict(),
        "support_map_graph": support_map.to_knowledge_graph(source="support_map_bundle").to_dict(),
        "neurosymbolic_match": neurosymbolic_result,
    }


__all__ = ["build_legal_analysis_bundle"]
