"""Lightweight neurosymbolic matching across case, dependency, and legal graphs."""

from __future__ import annotations

from typing import Any, Dict, List

from .dependency_graph import DependencyGraph, NodeType
from .requirements_graph import LegalElement, LegalRequirementsGraph
from ..protocol import KnowledgeGraph


class NeurosymbolicMatcher:
    """Match case facts and dependency satisfaction to legal requirements."""

    def __init__(self) -> None:
        self.matching_results: List[Dict[str, Any]] = []

    def match_claims_to_law(
        self,
        knowledge_graph: KnowledgeGraph,
        dependency_graph: DependencyGraph,
        legal_graph: LegalRequirementsGraph,
    ) -> Dict[str, Any]:
        results = {
            "claims": [],
            "matched_requirements": [],
            "overall_satisfaction": 0.0,
            "satisfied_claims": 0,
            "total_claims": 0,
            "gaps": [],
        }

        claim_nodes = dependency_graph.get_nodes_by_type(NodeType.CLAIM)
        results["total_claims"] = len(claim_nodes)

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
                        "confidence": requirement.get("confidence", 0.0),
                    }
                )
            if claim_result["satisfied"]:
                results["satisfied_claims"] += 1
            results["gaps"].extend(claim_result.get("missing_requirements", []))

        if results["total_claims"]:
            results["overall_satisfaction"] = results["satisfied_claims"] / results["total_claims"]

        self.matching_results.append(results)
        return results

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
        result = {
            "claim_id": claim_id,
            "claim_name": claim_name,
            "claim_type": claim_type,
            "legal_requirements": len(legal_requirements),
            "satisfied_requirements": 0,
            "missing_requirements": [],
            "requirements": [],
            "satisfied": False,
            "confidence": 0.0,
        }

        for legal_requirement in legal_requirements:
            match = self._check_requirement_satisfied(
                legal_requirement,
                claim_id,
                claim_name,
                knowledge_graph,
                dependency_graph,
            )
            result["requirements"].append(
                {
                    "requirement_name": legal_requirement.name,
                    "requirement_description": legal_requirement.description,
                    "citation": legal_requirement.citation,
                    "satisfied": match.get("satisfied", False),
                    "confidence": match.get("confidence", 0.0),
                }
            )
            if match["satisfied"]:
                result["satisfied_requirements"] += 1
            else:
                result["missing_requirements"].append(
                    {
                        "requirement_name": legal_requirement.name,
                        "requirement_description": legal_requirement.description,
                        "citation": legal_requirement.citation,
                        "suggested_action": match.get("suggested_action", "Gather more information"),
                    }
                )

        if legal_requirements:
            satisfaction_ratio = result["satisfied_requirements"] / len(legal_requirements)
            result["satisfied"] = satisfaction_ratio >= 1.0
            result["confidence"] = satisfaction_ratio
        else:
            result["satisfied"] = True
            result["confidence"] = 1.0
        return result

    def _check_requirement_satisfied(
        self,
        legal_requirement: LegalElement,
        claim_id: str,
        claim_name: str,
        knowledge_graph: KnowledgeGraph,
        dependency_graph: DependencyGraph,
    ) -> Dict[str, Any]:
        result = {
            "requirement_name": legal_requirement.name,
            "satisfied": False,
            "confidence": 0.0,
            "evidence": [],
        }

        dependencies = dependency_graph.get_dependencies_for_node(claim_id, direction="incoming")
        for dependency in dependencies:
            requirement_node = dependency_graph.get_node(dependency.source_id)
            if requirement_node and self._requirement_matches(legal_requirement.name, requirement_node.name):
                if requirement_node.satisfied:
                    result["satisfied"] = True
                    result["confidence"] = max(requirement_node.confidence, 0.8)
                    result["evidence"].append(f"Requirement node '{requirement_node.name}' is satisfied")
                    return result

        semantic_match = self._semantic_requirement_check(legal_requirement.name, claim_name, knowledge_graph)
        if semantic_match["satisfied"]:
            result["satisfied"] = True
            result["confidence"] = semantic_match["confidence"]
            result["evidence"].extend(semantic_match["evidence"])
        else:
            result["suggested_action"] = semantic_match.get("suggested_action", "")
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
        result = {
            "satisfied": False,
            "confidence": 0.0,
            "evidence": [],
            "suggested_action": f"Gather evidence for: {legal_requirement_name}",
        }
        claim_entities = [
            entity
            for entity in knowledge_graph.entities
            if entity.type == "claim" and entity.label in {claim_name, claim_name.replace("_", " ").title()}
        ]
        if not claim_entities:
            result["suggested_action"] = f"Provide more information about {claim_name}"
            return result

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


__all__ = ["NeurosymbolicMatcher"]
