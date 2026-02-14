#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Deontological Reasoning Module for Legal and Ethical Analysis.

This module implements deontic logic frameworks to detect conflicts between
what entities can/cannot, should/should not, must/must not do or be across
large unstructured corpuses. It provides legal and ethical reasoning capabilities
for analyzing obligations, permissions, and prohibitions.

Note: Refactored from 911 LOC to <600 LOC. Types and utilities extracted to
separate modules for better maintainability.
"""
from __future__ import annotations

import re
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple, Union
from datetime import datetime

# Import types from refactored modules
from .deontological_reasoning_types import (
    DeonticModality,
    ConflictType,
    DeonticStatement,
    DeonticConflict,
)
from .deontological_reasoning_utils import (
    DeonticPatterns,
)

logger = logging.getLogger(__name__)


class DeonticExtractor:
    """Extracts deontic statements from text using pattern matching and NLP."""

    def __init__(self):
        """Initialize the deontic statement extractor.

        Attributes set:
            patterns
            statement_counter

        """
        self.patterns = DeonticPatterns()
        self.statement_counter = 0

    def extract_statements(self, text: str, document_id: str) -> List[DeonticStatement]:
        """Extract all deontic statements from text.

        Args:
            text: The text to analyze for deontic statements
            document_id: Unique identifier for the source document

        Returns:
            List of extracted deontic statements

        Example:
            >>> extractor = DeonticExtractor()
            >>> statements = extractor.extract_statements(
            ...     "Citizens must pay taxes. Citizens may vote.", "doc1"
            ... )
            >>> len(statements)
            2
        """
        statements = []

        # Extract obligations
        statements.extend(self._extract_modality_statements(
            text, document_id, self.patterns.OBLIGATION_PATTERNS, DeonticModality.OBLIGATION
        ))

        # Extract permissions
        statements.extend(self._extract_modality_statements(
            text, document_id, self.patterns.PERMISSION_PATTERNS, DeonticModality.PERMISSION
        ))

        # Extract prohibitions
        statements.extend(self._extract_modality_statements(
            text, document_id, self.patterns.PROHIBITION_PATTERNS, DeonticModality.PROHIBITION
        ))

        # Extract conditional statements
        statements.extend(self._extract_conditional_statements(text, document_id))

        # Extract statements with exceptions
        statements.extend(self._extract_exception_statements(text, document_id))

        return statements

    def _extract_modality_statements(
        self,
        text: str,
        document_id: str,
        patterns: List[str],
        modality: DeonticModality
    ) -> List[DeonticStatement]:
        """Extract statements for a specific deontic modality."""
        statements = []

        for pattern in patterns:
            matches = re.finditer(pattern, text, re.IGNORECASE | re.MULTILINE)
            for match in matches:
                try:
                    entity = match.group(1).strip()
                    action = match.group(2).strip()

                    # Skip if entity or action is too generic
                    if self._is_valid_entity_action(entity, action):
                        self.statement_counter += 1

                        statement = DeonticStatement(
                            id=f"stmt_{self.statement_counter}",
                            entity=entity,
                            action=action,
                            modality=modality,
                            source_document=document_id,
                            source_text=match.group(0),
                            confidence=self._calculate_confidence(match.group(0), modality),
                            context=self._extract_context(text, match.start(), match.end())
                        )
                        statements.append(statement)

                except IndexError:
                    continue

        return statements

    def _extract_conditional_statements(self, text: str, document_id: str) -> List[DeonticStatement]:
        """Extract conditional deontic statements."""
        statements = []

        for pattern in self.patterns.CONDITIONAL_PATTERNS:
            matches = re.finditer(pattern, text, re.IGNORECASE | re.MULTILINE)
            for match in matches:
                try:
                    condition = match.group(1).strip()
                    entity = match.group(2).strip()
                    modal_word = match.group(3).strip().lower()
                    action = match.group(4).strip()

                    # Determine modality from modal word
                    if modal_word in ['must', 'shall']:
                        modality = DeonticModality.OBLIGATION
                    elif modal_word in ['may', 'can']:
                        modality = DeonticModality.PERMISSION
                    elif modal_word in ['cannot', 'must not']:
                        modality = DeonticModality.PROHIBITION
                    else:
                        continue

                    if self._is_valid_entity_action(entity, action):
                        self.statement_counter += 1

                        statement = DeonticStatement(
                            id=f"cond_stmt_{self.statement_counter}",
                            entity=entity,
                            action=action,
                            modality=DeonticModality.CONDITIONAL,
                            source_document=document_id,
                            source_text=match.group(0),
                            confidence=self._calculate_confidence(match.group(0), modality),
                            context=self._extract_context(text, match.start(), match.end()),
                            conditions=[condition]
                        )
                        statements.append(statement)

                except IndexError:
                    continue

        return statements

    def _extract_exception_statements(self, text: str, document_id: str) -> List[DeonticStatement]:
        """Extract statements with exceptions."""
        statements = []

        for pattern in self.patterns.EXCEPTION_PATTERNS:
            matches = re.finditer(pattern, text, re.IGNORECASE | re.MULTILINE)
            for match in matches:
                try:
                    entity = match.group(1).strip()
                    modal_word = match.group(2).strip().lower()
                    action = match.group(3).strip()
                    exception = match.group(4).strip()

                    # Determine modality from modal word
                    if modal_word in ['must', 'shall']:
                        modality = DeonticModality.OBLIGATION
                    elif modal_word in ['may', 'can']:
                        modality = DeonticModality.PERMISSION
                    elif modal_word in ['cannot', 'must not']:
                        modality = DeonticModality.PROHIBITION
                    else:
                        continue

                    if self._is_valid_entity_action(entity, action):
                        self.statement_counter += 1

                        statement = DeonticStatement(
                            id=f"exc_stmt_{self.statement_counter}",
                            entity=entity,
                            action=action,
                            modality=DeonticModality.EXCEPTION,
                            source_document=document_id,
                            source_text=match.group(0),
                            confidence=self._calculate_confidence(match.group(0), modality),
                            context=self._extract_context(text, match.start(), match.end()),
                            exceptions=[exception]
                        )
                        statements.append(statement)

                except IndexError:
                    continue

        return statements

    def _is_valid_entity_action(self, entity: str, action: str) -> bool:
        """Check if entity and action are valid (not too generic)."""
        # Filter out overly generic entities
        generic_entities = {'it', 'this', 'that', 'they', 'one', 'someone', 'anyone'}
        if entity.lower() in generic_entities:
            return False

        # Filter out very short actions
        if len(action.strip()) < 3:
            return False

        return True

    def _calculate_confidence(self, text: str, modality: DeonticModality) -> float:
        """Calculate confidence score for extracted statement."""
        base_confidence = 0.7

        # Higher confidence for explicit modal words
        if any(word in text.lower() for word in ['must', 'shall', 'required', 'mandatory']):
            base_confidence += 0.2

        # Lower confidence for weaker modal words
        if any(word in text.lower() for word in ['should', 'ought', 'recommend']):
            base_confidence -= 0.1

        return min(1.0, base_confidence)

    def _extract_context(self, text: str, start: int, end: int) -> Dict[str, Any]:
        """Extract context around the matched statement."""
        # Get surrounding sentences for context
        context_start = max(0, start - 200)
        context_end = min(len(text), end + 200)
        context_text = text[context_start:context_end]

        return {
            "surrounding_text": context_text,
            "position": {"start": start, "end": end},
            "extracted_at": datetime.now().isoformat()
        }


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

        # Group statements by entity for more efficient comparison
        entity_groups = self._group_by_entity(statements)

        for entity, entity_statements in entity_groups.items():
            conflicts.extend(self._detect_entity_conflicts(entity_statements))

        return conflicts

    def _group_by_entity(self, statements: List[DeonticStatement]) -> Dict[str, List[DeonticStatement]]:
        """Group statements by the entity they refer to."""
        groups = {}
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
        # Check if actions are similar/related
        if not self._actions_are_related(stmt1.action, stmt2.action):
            return None

        # Check for different types of conflicts
        conflict_type = None
        severity = "medium"
        explanation = ""

        # Direct contradiction: must vs must not
        if (stmt1.modality == DeonticModality.OBLIGATION and
            stmt2.modality == DeonticModality.PROHIBITION):
            conflict_type = ConflictType.OBLIGATION_PROHIBITION
            severity = "high"
            explanation = f"Entity '{stmt1.entity}' has conflicting obligations: must {stmt1.action} but must not {stmt2.action}"

        # Permission vs prohibition
        elif (stmt1.modality == DeonticModality.PERMISSION and
              stmt2.modality == DeonticModality.PROHIBITION):
            conflict_type = ConflictType.PERMISSION_PROHIBITION
            severity = "high"
            explanation = f"Entity '{stmt1.entity}' has conflicting permissions: may {stmt1.action} but cannot {stmt2.action}"

        # Conditional conflicts
        elif (stmt1.modality == DeonticModality.CONDITIONAL and
              stmt2.modality == DeonticModality.CONDITIONAL):
            if self._conditional_conflict_exists(stmt1, stmt2):
                conflict_type = ConflictType.CONDITIONAL_CONFLICT
                severity = "medium"
                explanation = f"Entity '{stmt1.entity}' has conflicting conditional obligations"

        # Check for jurisdictional conflicts (different sources)
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
        # Simple keyword overlap check
        words1 = set(action1.lower().split())
        words2 = set(action2.lower().split())

        # If they share at least 1 significant word (>3 chars), consider them related
        shared_words = words1.intersection(words2)
        significant_shared = [w for w in shared_words if len(w) > 3]

        return len(significant_shared) > 0 or self._semantic_similarity(action1, action2) > 0.7

    def _semantic_similarity(self, text1: str, text2: str) -> float:
        """Calculate semantic similarity between two text strings."""
        # Simple implementation - could be enhanced with embeddings
        words1 = set(text1.lower().split())
        words2 = set(text2.lower().split())

        if not words1 or not words2:
            return 0.0

        intersection = words1.intersection(words2)
        union = words1.union(words2)

        return len(intersection) / len(union) if union else 0.0

    def _conditional_conflict_exists(self, stmt1: DeonticStatement, stmt2: DeonticStatement) -> bool:
        """Check if two conditional statements conflict."""
        # Check if they have overlapping conditions but opposite outcomes
        if not stmt1.conditions or not stmt2.conditions:
            return False

        # Simple check: if conditions are similar but actions are opposite
        for cond1 in stmt1.conditions:
            for cond2 in stmt2.conditions:
                if self._semantic_similarity(cond1, cond2) > 0.8:
                    # Same condition but potentially different modalities
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


class DeontologicalReasoningEngine:
    """Main engine for legal/deontological reasoning over text corpora."""

    def __init__(self, mcp_dashboard=None):
        """Initialize the deontological reasoning engine.

        Args:
            mcp_dashboard: Optional MCP dashboard instance for integration

        Example:
            >>> engine = DeontologicalReasoningEngine()
            >>> engine.extractor is not None
            True
        """
        self.dashboard = mcp_dashboard
        self.extractor = DeonticExtractor()
        self.conflict_detector = ConflictDetector()
        self.statement_database = {}
        self.conflict_database = {}

    async def analyze_corpus_for_deontic_conflicts(
        self,
        documents: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Analyze a corpus of documents for deontic conflicts.

        Args:
            documents: List of documents to analyze, each with 'id' and 'content'/'text'

        Returns:
            Dictionary containing analysis results including:
            - processing_stats: Statistics about document processing
            - statements_summary: Summary of extracted statements
            - conflicts_summary: Summary of detected conflicts
            - entity_reports: Per-entity conflict reports
            - high_priority_conflicts: Most critical conflicts found
            - recommendations: Suggested actions based on analysis

        Raises:
            Exception: If analysis fails due to processing errors

        Example:
            >>> engine = DeontologicalReasoningEngine()
            >>> docs = [{'id': 'doc1', 'content': 'Citizens must vote. Citizens cannot vote.'}]
            >>> result = await engine.analyze_corpus_for_deontic_conflicts(docs)
            >>> result['conflicts_summary']['total_conflicts']
            1
        """
        try:
            logger.info(f"Starting deontological analysis of {len(documents)} documents")

            all_statements = []
            processing_stats = {
                "documents_processed": 0,
                "statements_extracted": 0,
                "extraction_errors": 0
            }

            # Extract statements from all documents
            for doc in documents:
                try:
                    doc_id = doc.get('id', str(len(all_statements)))
                    content = doc.get('content', '') or doc.get('text', '')

                    if content:
                        statements = self.extractor.extract_statements(content, doc_id)
                        all_statements.extend(statements)
                        processing_stats["statements_extracted"] += len(statements)

                    processing_stats["documents_processed"] += 1

                except Exception as e:
                    logger.error(f"Error processing document {doc.get('id', 'unknown')}: {e}")
                    processing_stats["extraction_errors"] += 1

            # Store statements in database
            for stmt in all_statements:
                self.statement_database[stmt.id] = stmt

            # Detect conflicts
            conflicts = self.conflict_detector.detect_conflicts(all_statements)

            # Store conflicts in database
            for conflict in conflicts:
                self.conflict_database[conflict.id] = conflict

            # Analyze conflicts by type and severity
            conflict_analysis = self._analyze_conflicts(conflicts)

            # Generate entity-specific conflict reports
            entity_reports = self._generate_entity_reports(all_statements, conflicts)

            result = {
                "analysis_id": f"deontic_analysis_{int(datetime.now().timestamp())}",
                "timestamp": datetime.now().isoformat(),
                "processing_stats": processing_stats,
                "statements_summary": {
                    "total_statements": len(all_statements),
                    "by_modality": self._count_by_modality(all_statements),
                    "by_entity": self._count_by_entity(all_statements)
                },
                "conflicts_summary": {
                    "total_conflicts": len(conflicts),
                    "by_type": conflict_analysis["by_type"],
                    "by_severity": conflict_analysis["by_severity"]
                },
                "entity_reports": entity_reports,
                "high_priority_conflicts": [
                    self._format_conflict_summary(c) for c in conflicts
                    if c.severity == "high"
                ][:10],  # Top 10 high priority conflicts
                "recommendations": self._generate_analysis_recommendations(conflicts)
            }

            logger.info(
                f"Deontological analysis complete: {len(all_statements)} statements, {len(conflicts)} conflicts"
            )
            return result

        except Exception as e:
            logger.error(f"Deontological analysis failed: {e}")
            return {
                "error": str(e),
                "analysis_id": f"failed_analysis_{int(datetime.now().timestamp())}",
                "timestamp": datetime.now().isoformat()
            }

    def _count_by_modality(self, statements: List[DeonticStatement]) -> Dict[str, int]:
        """Count statements by deontic modality."""
        counts = {}
        for stmt in statements:
            modality = stmt.modality.value
            counts[modality] = counts.get(modality, 0) + 1
        return counts

    def _count_by_entity(self, statements: List[DeonticStatement]) -> Dict[str, int]:
        """Count statements by entity."""
        counts = {}
        for stmt in statements:
            entity = stmt.entity
            counts[entity] = counts.get(entity, 0) + 1
        return counts

    def _analyze_conflicts(self, conflicts: List[DeonticConflict]) -> Dict[str, Any]:
        """Analyze conflicts by type and severity."""
        by_type = {}
        by_severity = {}

        for conflict in conflicts:
            # Count by type
            conflict_type = conflict.conflict_type.value
            by_type[conflict_type] = by_type.get(conflict_type, 0) + 1

            # Count by severity
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
        entity_reports = {}

        # Group statements by entity
        entity_statements = {}
        for stmt in statements:
            entity = stmt.entity
            if entity not in entity_statements:
                entity_statements[entity] = []
            entity_statements[entity].append(stmt)

        # Group conflicts by entity
        entity_conflicts = {}
        for conflict in conflicts:
            entity = conflict.statement1.entity  # Both statements should have same entity
            if entity not in entity_conflicts:
                entity_conflicts[entity] = []
            entity_conflicts[entity].append(conflict)

        # Generate report for each entity
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
            "resolution_suggestions": conflict.resolution_suggestions[:2]  # Top 2 suggestions
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

    async def query_deontic_statements(
        self,
        entity: Optional[str] = None,
        modality: Optional[DeonticModality] = None,
        action_keywords: Optional[List[str]] = None
    ) -> List[DeonticStatement]:
        """Query extracted deontic statements by various criteria.

        Args:
            entity: Filter by entity name (case-insensitive partial match)
            modality: Filter by specific deontic modality
            action_keywords: Filter by keywords in the action text

        Returns:
            List of deontic statements matching the specified criteria

        Example:
            >>> statements = await engine.query_deontic_statements(
            ...     entity="citizen",
            ...     modality=DeonticModality.OBLIGATION
            ... )
            >>> len(statements)
            5
        """
        results = list(self.statement_database.values())

        if entity:
            results = [s for s in results if entity.lower() in s.entity.lower()]

        if modality:
            results = [s for s in results if s.modality == modality]

        if action_keywords:
            results = [
                s for s in results
                if any(keyword.lower() in s.action.lower() for keyword in action_keywords)
            ]

        return results

    async def query_conflicts(
        self,
        entity: Optional[str] = None,
        conflict_type: Optional[ConflictType] = None,
        min_severity: Optional[str] = None
    ) -> List[DeonticConflict]:
        """Query detected conflicts by various criteria.

        Args:
            entity: Filter by entity name (case-insensitive partial match)
            conflict_type: Filter by specific type of conflict
            min_severity: Filter by minimum severity level (low, medium, high)

        Returns:
            List of conflicts matching the specified criteria

        Example:
            >>> conflicts = await engine.query_conflicts(
            ...     entity="citizen",
            ...     min_severity="high"
            ... )
            >>> all(c.severity == "high" for c in conflicts)
            True
        """
        results = list(self.conflict_database.values())

        if entity:
            results = [c for c in results if entity.lower() in c.statement1.entity.lower()]

        if conflict_type:
            results = [c for c in results if c.conflict_type == conflict_type]

        if min_severity:
            severity_order = {"low": 0, "medium": 1, "high": 2}
            min_level = severity_order.get(min_severity, 0)
            results = [c for c in results if severity_order.get(c.severity, 0) >= min_level]

        return results
