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
from ._deontic_conflict_mixin import ConflictDetector, DeonticConflictMixin

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


class DeontologicalReasoningEngine(DeonticConflictMixin):
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
