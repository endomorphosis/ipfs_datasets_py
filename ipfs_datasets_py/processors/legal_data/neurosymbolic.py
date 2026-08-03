"""Lightweight neurosymbolic matching across case, dependency, and legal graphs.

Fail-closed semantics
---------------------
Matching never reports a vacuous overall pass. Empty claim sets, absent legal
requirement catalogs, incomplete evidence, and unsupported checks surface as
``unknown`` or ``review_required``. ``overall_pass`` is True only when every
claim has a non-empty applicable requirement set and every requirement is
explicitly satisfied with evidence.
"""

from __future__ import annotations

from typing import Any, Dict, List

from .dependency_graph import DependencyGraph, NodeType
from .requirements_graph import LegalElement, LegalRequirementsGraph
from ..protocol import KnowledgeGraph

STATUS_SATISFIED = "satisfied"
STATUS_UNSATISFIED = "unsatisfied"
STATUS_UNKNOWN = "unknown"
STATUS_REVIEW_REQUIRED = "review_required"


class NeurosymbolicMatcher:
    """Match case facts and dependency satisfaction to legal requirements.

    Results always include fail-closed aggregation fields:

    - ``overall_pass``: True only when all claims are fully satisfied with evidence
    - ``review_required``: True when any claim/requirement is unknown or needs review
    - ``overall_status``: ``satisfied`` | ``unsatisfied`` | ``unknown`` | ``review_required``
    """

    def __init__(self) -> None:
        self.matching_results: List[Dict[str, Any]] = []

    def match_claims_to_law(
        self,
        knowledge_graph: KnowledgeGraph,
        dependency_graph: DependencyGraph,
        legal_graph: LegalRequirementsGraph,
    ) -> Dict[str, Any]:
        results: Dict[str, Any] = {
            "claims": [],
            "matched_requirements": [],
            "overall_satisfaction": 0.0,
            "satisfied_claims": 0,
            "total_claims": 0,
            "gaps": [],
            "overall_pass": False,
            "review_required": False,
            "overall_status": STATUS_UNKNOWN,
            "unknown_claims": 0,
            "unsatisfied_claims": 0,
            "fail_closed_reasons": [],
        }

        claim_nodes = dependency_graph.get_nodes_by_type(NodeType.CLAIM)
        results["total_claims"] = len(claim_nodes)

        if not claim_nodes:
            results["review_required"] = True
            results["overall_status"] = STATUS_REVIEW_REQUIRED
            results["overall_pass"] = False
            results["fail_closed_reasons"].append("empty_claims")
            self.matching_results.append(results)
            return results

        for claim_node in claim_nodes:
            claim_result = self._match_single_claim(
                claim_node.id,
                claim_node.name,
                claim_node.attributes.get("claim_type", "unknown"),
                knowledge_graph,
                dependency_graph,
                legal_graph,
            )
            results["claims"].append(claim_result)
            for requirement in claim_result.get("requirements", []):
                results["matched_requirements"].append(
                    {
                        "claim_id": claim_node.id,
                        "claim_type": claim_result["claim_type"],
                        "requirement_name": requirement.get("requirement_name"),
                        "requirement_description": requirement.get("requirement_description", ""),
                        "citation": requirement.get("citation", ""),
                        "satisfied": requirement.get("satisfied", False),
                        "status": requirement.get("status", STATUS_UNSATISFIED),
                        "confidence": requirement.get("confidence", 0.0),
                    }
                )
            if claim_result.get("status") == STATUS_SATISFIED and claim_result.get("satisfied"):
                results["satisfied_claims"] += 1
            elif claim_result.get("status") in (STATUS_UNKNOWN, STATUS_REVIEW_REQUIRED):
                results["unknown_claims"] += 1
            else:
                results["unsatisfied_claims"] += 1
            results["gaps"].extend(claim_result.get("missing_requirements", []))

        results["overall_satisfaction"] = (
            results["satisfied_claims"] / results["total_claims"]
            if results["total_claims"]
            else 0.0
        )

        overall_pass, review_required, overall_status, reasons = self._aggregate_fail_closed(
            results["claims"],
            total_claims=results["total_claims"],
        )
        results["overall_pass"] = overall_pass
        results["review_required"] = review_required
        results["overall_status"] = overall_status
        results["fail_closed_reasons"] = reasons

        self.matching_results.append(results)
        return results

    def _aggregate_fail_closed(
        self,
        claim_results: List[Dict[str, Any]],
        *,
        total_claims: int,
    ) -> tuple[bool, bool, str, List[str]]:
        """Aggregate claim-level outcomes under fail-closed rules."""
        reasons: List[str] = []
        if total_claims <= 0 or not claim_results:
            return False, True, STATUS_REVIEW_REQUIRED, ["empty_claims"]

        any_unsatisfied = False
        any_unknown = False
        any_review = False

        for claim in claim_results:
            status = claim.get("status") or STATUS_UNKNOWN
            claim_id = claim.get("claim_id", "")
            if claim.get("review_required"):
                any_review = True
            if status == STATUS_SATISFIED and claim.get("satisfied"):
                continue
            if status == STATUS_UNSATISFIED or (
                status == STATUS_SATISFIED and not claim.get("satisfied")
            ):
                any_unsatisfied = True
                reasons.append(f"unsatisfied:{claim_id}")
            elif status == STATUS_REVIEW_REQUIRED:
                any_review = True
                reasons.append(f"review_required:{claim_id}")
            else:
                any_unknown = True
                reasons.append(f"unknown:{claim_id}")

        if any_review or any_unknown:
            return False, True, STATUS_REVIEW_REQUIRED if any_review else STATUS_UNKNOWN, reasons
        if any_unsatisfied:
            return False, False, STATUS_UNSATISFIED, reasons
        # All claims satisfied with evidence.
        return True, False, STATUS_SATISFIED, reasons

    def _match_single_claim(
        self,
        claim_id: str,
        claim_name: str,
        claim_type: str,
        knowledge_graph: KnowledgeGraph,
        dependency_graph: DependencyGraph,
        legal_graph: LegalRequirementsGraph,
    ) -> Dict[str, Any]:
        legal_requirements = legal_graph.get_requirements_for_claim_type(claim_type)
        result: Dict[str, Any] = {
            "claim_id": claim_id,
            "claim_name": claim_name,
            "claim_type": claim_type,
            "legal_requirements": len(legal_requirements),
            "satisfied_requirements": 0,
            "missing_requirements": [],
            "requirements": [],
            "satisfied": False,
            "confidence": 0.0,
            "status": STATUS_UNKNOWN,
            "review_required": False,
        }

        # Absent catalog for this claim type is not a vacuous pass.
        if not legal_requirements:
            result["status"] = STATUS_UNKNOWN
            result["review_required"] = True
            result["satisfied"] = False
            result["confidence"] = 0.0
            result["missing_requirements"].append(
                {
                    "requirement_name": "__absent_requirement_catalog__",
                    "requirement_description": (
                        f"No legal requirements registered for claim type '{claim_type}'"
                    ),
                    "citation": "",
                    "suggested_action": (
                        "Provide or load applicable legal requirements before asserting compliance"
                    ),
                    "status": STATUS_UNKNOWN,
                }
            )
            return result

        unknown_requirement = False
        for legal_requirement in legal_requirements:
            match = self._check_requirement_satisfied(
                legal_requirement,
                claim_id,
                claim_name,
                knowledge_graph,
                dependency_graph,
            )
            req_status = match.get("status") or (
                STATUS_SATISFIED if match.get("satisfied") else STATUS_UNSATISFIED
            )
            result["requirements"].append(
                {
                    "requirement_name": legal_requirement.name,
                    "requirement_description": legal_requirement.description,
                    "citation": legal_requirement.citation,
                    "satisfied": match.get("satisfied", False),
                    "status": req_status,
                    "confidence": match.get("confidence", 0.0),
                }
            )
            if match.get("satisfied") and req_status == STATUS_SATISFIED:
                result["satisfied_requirements"] += 1
            elif req_status in (STATUS_UNKNOWN, STATUS_REVIEW_REQUIRED):
                unknown_requirement = True
                result["missing_requirements"].append(
                    {
                        "requirement_name": legal_requirement.name,
                        "requirement_description": legal_requirement.description,
                        "citation": legal_requirement.citation,
                        "suggested_action": match.get(
                            "suggested_action", "Gather more information"
                        ),
                        "status": req_status,
                    }
                )
            else:
                result["missing_requirements"].append(
                    {
                        "requirement_name": legal_requirement.name,
                        "requirement_description": legal_requirement.description,
                        "citation": legal_requirement.citation,
                        "suggested_action": match.get(
                            "suggested_action", "Gather more information"
                        ),
                        "status": STATUS_UNSATISFIED,
                    }
                )

        satisfaction_ratio = result["satisfied_requirements"] / len(legal_requirements)
        result["confidence"] = satisfaction_ratio
        if unknown_requirement:
            result["satisfied"] = False
            result["status"] = STATUS_UNKNOWN
            result["review_required"] = True
        elif satisfaction_ratio >= 1.0:
            result["satisfied"] = True
            result["status"] = STATUS_SATISFIED
            result["review_required"] = False
        else:
            result["satisfied"] = False
            result["status"] = STATUS_UNSATISFIED
            result["review_required"] = False
        return result

    def _check_requirement_satisfied(
        self,
        legal_requirement: LegalElement,
        claim_id: str,
        claim_name: str,
        knowledge_graph: KnowledgeGraph,
        dependency_graph: DependencyGraph,
    ) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "requirement_name": legal_requirement.name,
            "satisfied": False,
            "status": STATUS_UNSATISFIED,
            "confidence": 0.0,
            "evidence": [],
        }

        dependencies = dependency_graph.get_dependencies_for_node(claim_id, direction="incoming")
        matched_nodes = 0
        for dependency in dependencies:
            requirement_node = dependency_graph.get_node(dependency.source_id)
            if requirement_node and self._requirement_matches(legal_requirement.name, requirement_node.name):
                matched_nodes += 1
                if requirement_node.satisfied:
                    result["satisfied"] = True
                    result["status"] = STATUS_SATISFIED
                    result["confidence"] = max(requirement_node.confidence, 0.8)
                    result["evidence"].append(f"Requirement node '{requirement_node.name}' is satisfied")
                    return result
                # Matched dependency node exists but is not satisfied — definitive gap.
                result["status"] = STATUS_UNSATISFIED
                result["suggested_action"] = (
                    f"Satisfy dependency node '{requirement_node.name}' for "
                    f"{legal_requirement.name}"
                )

        semantic_match = self._semantic_requirement_check(
            legal_requirement.name, claim_name, knowledge_graph
        )
        if semantic_match["satisfied"]:
            result["satisfied"] = True
            result["status"] = STATUS_SATISFIED
            result["confidence"] = semantic_match["confidence"]
            result["evidence"].extend(semantic_match["evidence"])
            return result

        # No dependency match and no semantic support: incomplete evidence → unknown
        # when we never found a related requirement node; unsatisfied when we did.
        if matched_nodes == 0 and not semantic_match.get("claim_entities_found"):
            result["status"] = STATUS_UNKNOWN
            result["suggested_action"] = semantic_match.get(
                "suggested_action", f"Gather evidence for: {legal_requirement.name}"
            )
        else:
            result["status"] = STATUS_UNSATISFIED
            result["suggested_action"] = semantic_match.get(
                "suggested_action", f"Gather evidence for: {legal_requirement.name}"
            )
        return result

    def _requirement_matches(self, legal_name: str, node_name: str) -> bool:
        legal_words = set(legal_name.lower().split())
        node_words = set(node_name.lower().split())
        overlap = legal_words & node_words
        return len(overlap) >= 1

    def _semantic_requirement_check(
        self,
        legal_requirement_name: str,
        claim_name: str,
        knowledge_graph: KnowledgeGraph,
    ) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "satisfied": False,
            "confidence": 0.0,
            "evidence": [],
            "suggested_action": f"Gather evidence for: {legal_requirement_name}",
            "claim_entities_found": False,
        }
        claim_entities = [
            entity
            for entity in knowledge_graph.entities
            if entity.type == "claim" and entity.label in {claim_name, claim_name.replace("_", " ").title()}
        ]
        if not claim_entities:
            result["suggested_action"] = f"Provide more information about {claim_name}"
            return result

        result["claim_entities_found"] = True
        for claim_entity in claim_entities:
            supporting_relationships = [
                relationship
                for relationship in knowledge_graph.relationships
                if relationship.source == claim_entity.id and relationship.type.lower() == "supported_by"
            ]
            if supporting_relationships:
                result["satisfied"] = True
                result["confidence"] = 0.7
                result["evidence"].append(f"Found {len(supporting_relationships)} supporting relationships")
                return result
        return result


__all__ = [
    "NeurosymbolicMatcher",
    "STATUS_REVIEW_REQUIRED",
    "STATUS_SATISFIED",
    "STATUS_UNKNOWN",
    "STATUS_UNSATISFIED",
]
