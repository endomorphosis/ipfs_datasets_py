"""
Deontic Conflict Mixin

Contains the ConflictDetector class and the DeonticConflictMixin with conflict
analysis/reporting methods extracted from DeontologicalReasoningEngine.
Extracted to keep deontological_reasoning.py under 600 lines.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .deontological_reasoning_types import (
    DeonticModality,
    ConflictType,
    DeonticStatement,
    DeonticConflict,
)

logger = logging.getLogger(__name__)


class ConflictDetector:
    """Detects conflicts between deontic statements."""

    def detect_conflicts(self, statements: List[DeonticStatement]) -> List[DeonticConflict]:
        """Detect all types of conflicts between statements.

        Args:
            statements: List of deontic statements to analyze for conflicts

        Returns:
            List of detected conflicts between statements

        Example:
            >>> detector = ConflictDetector()
            >>> conflicts = detector.detect_conflicts(statements)
            >>> len(conflicts)
            3
        """
        conflicts = []

        entity_groups = self._group_by_entity(statements)

        for entity, entity_statements in entity_groups.items():
            conflicts.extend(self._detect_entity_conflicts(entity_statements))

        return conflicts

    def _group_by_entity(self, statements: List[DeonticStatement]) -> Dict[str, List[DeonticStatement]]:
        """Group statements by the entity they refer to."""
        groups: Dict[str, List[DeonticStatement]] = {}
        for statement in statements:
            entity = statement.entity.lower()
            if entity not in groups:
                groups[entity] = []
            groups[entity].append(statement)
        return groups

    def _detect_entity_conflicts(self, statements: List[DeonticStatement]) -> List[DeonticConflict]:
        """Detect conflicts for statements about the same entity."""
        conflicts = []

        for i, stmt1 in enumerate(statements):
            for j, stmt2 in enumerate(statements[i+1:], i+1):
                conflict = self._check_statement_pair(stmt1, stmt2)
                if conflict:
                    conflicts.append(conflict)

        return conflicts

    def _check_statement_pair(self, stmt1: DeonticStatement, stmt2: DeonticStatement) -> Optional[DeonticConflict]:
        """Check if two statements conflict with each other."""
        if not self._actions_are_related(stmt1.action, stmt2.action):
            return None

        conflict_type = None
        severity = "medium"
        explanation = ""

        if (stmt1.modality == DeonticModality.OBLIGATION and
                stmt2.modality == DeonticModality.PROHIBITION):
            conflict_type = ConflictType.OBLIGATION_PROHIBITION
            severity = "high"
            explanation = f"Entity '{stmt1.entity}' has conflicting obligations: must {stmt1.action} but must not {stmt2.action}"

        elif (stmt1.modality == DeonticModality.PERMISSION and
              stmt2.modality == DeonticModality.PROHIBITION):
            conflict_type = ConflictType.PERMISSION_PROHIBITION
            severity = "high"
            explanation = f"Entity '{stmt1.entity}' has conflicting permissions: may {stmt1.action} but cannot {stmt2.action}"

        elif (stmt1.modality == DeonticModality.CONDITIONAL and
              stmt2.modality == DeonticModality.CONDITIONAL):
            if self._conditional_conflict_exists(stmt1, stmt2):
                conflict_type = ConflictType.CONDITIONAL_CONFLICT
                severity = "medium"
                explanation = f"Entity '{stmt1.entity}' has conflicting conditional obligations"

        elif stmt1.source_document != stmt2.source_document:
            if self._modalities_conflict(stmt1.modality, stmt2.modality):
                conflict_type = ConflictType.JURISDICTIONAL
                severity = "medium"
                explanation = f"Entity '{stmt1.entity}' has conflicting rules from different sources"

        if conflict_type:
            conflict_id = f"conflict_{stmt1.id}_{stmt2.id}"
            return DeonticConflict(
                id=conflict_id,
                conflict_type=conflict_type,
                statement1=stmt1,
                statement2=stmt2,
                severity=severity,
                explanation=explanation,
                resolution_suggestions=self._generate_resolution_suggestions(stmt1, stmt2, conflict_type)
            )

        return None

    def _actions_are_related(self, action1: str, action2: str) -> bool:
        """Check if two actions are related enough to potentially conflict."""
        words1 = set(action1.lower().split())
        words2 = set(action2.lower().split())

        shared_words = words1.intersection(words2)
        significant_shared = [w for w in shared_words if len(w) > 3]

        return len(significant_shared) > 0 or self._semantic_similarity(action1, action2) > 0.7

    def _semantic_similarity(self, text1: str, text2: str) -> float:
        """Calculate semantic similarity between two text strings."""
        words1 = set(text1.lower().split())
        words2 = set(text2.lower().split())

        if not words1 or not words2:
            return 0.0

        intersection = words1.intersection(words2)
        union = words1.union(words2)

        return len(intersection) / len(union) if union else 0.0

    def _conditional_conflict_exists(self, stmt1: DeonticStatement, stmt2: DeonticStatement) -> bool:
        """Check if two conditional statements conflict."""
        if not stmt1.conditions or not stmt2.conditions:
            return False

        for cond1 in stmt1.conditions:
            for cond2 in stmt2.conditions:
                if self._semantic_similarity(cond1, cond2) > 0.8:
                    return True

        return False

    def _modalities_conflict(self, mod1: DeonticModality, mod2: DeonticModality) -> bool:
        """Check if two modalities are in conflict."""
        conflicting_pairs = [
            (DeonticModality.OBLIGATION, DeonticModality.PROHIBITION),
            (DeonticModality.PERMISSION, DeonticModality.PROHIBITION),
            (DeonticModality.PROHIBITION, DeonticModality.OBLIGATION),
            (DeonticModality.PROHIBITION, DeonticModality.PERMISSION)
        ]

        return (mod1, mod2) in conflicting_pairs or (mod2, mod1) in conflicting_pairs

    def _generate_resolution_suggestions(
        self,
        stmt1: DeonticStatement,
        stmt2: DeonticStatement,
        conflict_type: ConflictType
    ) -> List[str]:
        """Generate suggestions for resolving conflicts."""
        suggestions = []

        if conflict_type == ConflictType.JURISDICTIONAL:
            suggestions.extend([
                "Determine which jurisdiction takes precedence",
                "Check if statements apply to different contexts or time periods",
                "Look for hierarchical authority relationships"
            ])
        elif conflict_type == ConflictType.OBLIGATION_PROHIBITION:
            suggestions.extend([
                "Check for exceptions or conditions that might resolve the conflict",
                "Determine if one statement supersedes the other",
                "Look for temporal ordering of the requirements"
            ])
        elif conflict_type == ConflictType.CONDITIONAL_CONFLICT:
            suggestions.extend([
                "Examine the specific conditions to see if they truly overlap",
                "Check for implicit priorities between conditions",
                "Look for exception clauses that might apply"
            ])

        return suggestions


class DeonticConflictMixin:
    """
    Mixin providing conflict analysis and reporting methods for
    DeontologicalReasoningEngine.
    """

    def _analyze_conflicts(self, conflicts: List[DeonticConflict]) -> Dict[str, Any]:
        """Analyze conflicts by type and severity."""
        by_type: Dict[str, int] = {}
        by_severity: Dict[str, int] = {}

        for conflict in conflicts:
            conflict_type = conflict.conflict_type.value
            by_type[conflict_type] = by_type.get(conflict_type, 0) + 1

            severity = conflict.severity
            by_severity[severity] = by_severity.get(severity, 0) + 1

        return {
            "by_type": by_type,
            "by_severity": by_severity
        }

    def _generate_entity_reports(
        self,
        statements: List[DeonticStatement],
        conflicts: List[DeonticConflict]
    ) -> Dict[str, Any]:
        """Generate conflict reports for each entity."""
        entity_reports: Dict[str, Any] = {}

        entity_statements: Dict[str, List[DeonticStatement]] = {}
        for stmt in statements:
            entity = stmt.entity
            if entity not in entity_statements:
                entity_statements[entity] = []
            entity_statements[entity].append(stmt)

        entity_conflicts: Dict[str, List[DeonticConflict]] = {}
        for conflict in conflicts:
            entity = conflict.statement1.entity
            if entity not in entity_conflicts:
                entity_conflicts[entity] = []
            entity_conflicts[entity].append(conflict)

        for entity in entity_statements.keys():
            entity_stmts = entity_statements.get(entity, [])
            entity_conf = entity_conflicts.get(entity, [])

            entity_reports[entity] = {
                "total_statements": len(entity_stmts),
                "statement_breakdown": {
                    modality.value: len([s for s in entity_stmts if s.modality == modality])
                    for modality in DeonticModality
                },
                "total_conflicts": len(entity_conf),
                "conflict_severity": {
                    "high": len([c for c in entity_conf if c.severity == "high"]),
                    "medium": len([c for c in entity_conf if c.severity == "medium"]),
                    "low": len([c for c in entity_conf if c.severity == "low"])
                },
                "top_conflicts": [
                    self._format_conflict_summary(c) for c in entity_conf[:3]
                ]
            }

        return entity_reports

    def _format_conflict_summary(self, conflict: DeonticConflict) -> Dict[str, Any]:
        """Format conflict for summary display."""
        return {
            "id": conflict.id,
            "type": conflict.conflict_type.value,
            "severity": conflict.severity,
            "entity": conflict.statement1.entity,
            "explanation": conflict.explanation,
            "statement1_text": conflict.statement1.source_text,
            "statement2_text": conflict.statement2.source_text,
            "sources": [conflict.statement1.source_document, conflict.statement2.source_document],
            "resolution_suggestions": conflict.resolution_suggestions[:2]
        }

    def _generate_analysis_recommendations(self, conflicts: List[DeonticConflict]) -> List[str]:
        """Generate high-level recommendations based on conflict analysis."""
        recommendations = []

        high_severity_count = len([c for c in conflicts if c.severity == "high"])
        if high_severity_count > 0:
            recommendations.append(
                f"Address {high_severity_count} high-severity conflicts that create direct contradictions"
            )

        jurisdictional_conflicts = len([c for c in conflicts if c.conflict_type == ConflictType.JURISDICTIONAL])
        if jurisdictional_conflicts > 0:
            recommendations.append(
                f"Review {jurisdictional_conflicts} jurisdictional conflicts for authority hierarchy"
            )

        conditional_conflicts = len([c for c in conflicts if c.conflict_type == ConflictType.CONDITIONAL_CONFLICT])
        if conditional_conflicts > 0:
            recommendations.append(
                f"Examine {conditional_conflicts} conditional conflicts for context specificity"
            )

        if not recommendations:
            recommendations.append("No major conflicts detected. Review extraction patterns for completeness.")

        return recommendations
