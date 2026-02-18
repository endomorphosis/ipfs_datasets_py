#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Deontic Logic Analyzer

Core business logic for analyzing deontological conflicts and deontic statements
in legal and ethical documents. This module provides reusable functionality
for CLI, API, and MCP tools.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple


class DeonticAnalyzer:
    """
    Analyzes deontic statements and conflicts in document corpora.
    
    Provides methods for:
    - Extracting deontic statements (obligations, permissions, prohibitions)
    - Detecting conflicts between statements
    - Organizing results by entities
    - Calculating statistics
    
    Example:
        >>> analyzer = DeonticAnalyzer()
        >>> statements = await analyzer.extract_deontic_statements(corpus)
        >>> conflicts = await analyzer.detect_deontic_conflicts(statements)
    """
    
    # Deontic patterns for different modalities
    DEONTIC_PATTERNS = {
        "obligation": [
            r"(\w+(?:\s+\w+)*)\s+(?:must|shall|should|is required to|has to|ought to)\s+([^.!?]+)",
            r"(\w+(?:\s+\w+)*)\s+(?:has an obligation to|is obligated to)\s+([^.!?]+)",
            r"it is (?:mandatory|required|necessary) (?:for\s+)?(\w+(?:\s+\w+)*)\s+to\s+([^.!?]+)"
        ],
        "permission": [
            r"(\w+(?:\s+\w+)*)\s+(?:may|can|might|is allowed to|is permitted to)\s+([^.!?]+)",
            r"(\w+(?:\s+\w+)*)\s+(?:has the right to|is entitled to)\s+([^.!?]+)",
            r"it is (?:permissible|acceptable) (?:for\s+)?(\w+(?:\s+\w+)*)\s+to\s+([^.!?]+)"
        ],
        "prohibition": [
            r"(\w+(?:\s+\w+)*)\s+(?:must not|shall not|should not|cannot|may not|is not allowed to|is prohibited from)\s+([^.!?]+)",
            r"(\w+(?:\s+\w+)*)\s+(?:is forbidden to|is banned from)\s+([^.!?]+)",
            r"it is (?:forbidden|prohibited|illegal) (?:for\s+)?(\w+(?:\s+\w+)*)\s+to\s+([^.!?]+)"
        ]
    }
    
    def __init__(self):
        """Initialize the DeonticAnalyzer."""
        pass
    
    async def extract_deontic_statements(
        self,
        corpus: Dict[str, Any],
        entity_filter: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        Extract deontic statements from corpus documents.
        
        Args:
            corpus: Dictionary containing document corpus data with 'documents' key
            entity_filter: Optional list of entities to filter by
            
        Returns:
            List of deontic statement dictionaries
        """
        statements = []
        
        if "documents" not in corpus:
            return statements
            
        for doc_id, document in enumerate(corpus["documents"]):
            content = document.get("content", "") + " " + document.get("title", "")
            source = document.get("source", "unknown")
            date = document.get("date", datetime.now().isoformat())
            
            for modality, pattern_list in self.DEONTIC_PATTERNS.items():
                for pattern in pattern_list:
                    matches = re.finditer(pattern, content, re.IGNORECASE)
                    for match in matches:
                        entity = match.group(1).strip()
                        action = match.group(2).strip()
                        
                        # Apply entity filter if provided
                        if entity_filter and not any(
                            filter_ent.lower() in entity.lower()
                            for filter_ent in entity_filter
                        ):
                            continue
                        
                        statement = {
                            "id": f"stmt_{doc_id}_{len(statements)}",
                            "entity": entity,
                            "modality": modality,
                            "action": action,
                            "document_id": doc_id,
                            "document_source": source,
                            "document_date": date,
                            "context": self.get_sentence_context(content, match.start(), match.end()),
                            "confidence": self.calculate_statement_confidence(entity, action, modality),
                            "conditions": self.extract_conditions(content, match.start(), match.end()),
                            "exceptions": self.extract_exceptions(content, match.start(), match.end())
                        }
                        statements.append(statement)
        
        return statements
    
    async def detect_deontic_conflicts(
        self,
        statements: List[Dict[str, Any]],
        conflict_types: List[str]
    ) -> List[Dict[str, Any]]:
        """
        Detect conflicts between deontic statements.
        
        Args:
            statements: List of deontic statements
            conflict_types: Types of conflicts to detect
                          (direct, conditional, jurisdictional, temporal)
                          
        Returns:
            List of conflict dictionaries
        """
        conflicts = []
        
        for i, stmt1 in enumerate(statements):
            for j, stmt2 in enumerate(statements[i+1:], i+1):
                conflict = self.check_statement_conflict(stmt1, stmt2, conflict_types)
                if conflict:
                    conflicts.append(conflict)
        
        return conflicts
    
    def check_statement_conflict(
        self,
        stmt1: Dict[str, Any],
        stmt2: Dict[str, Any],
        conflict_types: List[str]
    ) -> Optional[Dict[str, Any]]:
        """
        Check if two statements conflict.
        
        Args:
            stmt1: First deontic statement
            stmt2: Second deontic statement
            conflict_types: Types of conflicts to check for
            
        Returns:
            Conflict dictionary if conflict exists, None otherwise
        """
        # Only check conflicts for same entity
        if stmt1["entity"].lower() != stmt2["entity"].lower():
            return None
            
        entity = stmt1["entity"]
        action1 = stmt1["action"].lower()
        action2 = stmt2["action"].lower()
        mod1 = stmt1["modality"]
        mod2 = stmt2["modality"]
        
        # Direct contradictions
        if "direct" in conflict_types:
            if self.actions_are_similar(action1, action2):
                if (mod1 == "obligation" and mod2 == "prohibition") or \
                   (mod1 == "prohibition" and mod2 == "obligation") or \
                   (mod1 == "permission" and mod2 == "prohibition") or \
                   (mod1 == "prohibition" and mod2 == "permission"):
                    return {
                        "id": f"conflict_{stmt1['id']}_{stmt2['id']}",
                        "type": "direct",
                        "severity": "high",
                        "entities": [entity],
                        "statement1": stmt1,
                        "statement2": stmt2,
                        "description": f"Direct conflict: {entity} {mod1} vs {mod2} {action1}",
                        "resolution": self.suggest_conflict_resolution(stmt1, stmt2, "direct")
                    }
        
        # Conditional conflicts
        if "conditional" in conflict_types:
            conditions1 = stmt1.get("conditions", [])
            conditions2 = stmt2.get("conditions", [])
            if conditions1 and conditions2 and self.conditions_overlap(conditions1, conditions2):
                if mod1 != mod2 and self.actions_are_similar(action1, action2):
                    return {
                        "id": f"conflict_{stmt1['id']}_{stmt2['id']}",
                        "type": "conditional",
                        "severity": "medium",
                        "entities": [entity],
                        "statement1": stmt1,
                        "statement2": stmt2,
                        "description": f"Conditional conflict: {entity} under overlapping conditions",
                        "resolution": self.suggest_conflict_resolution(stmt1, stmt2, "conditional")
                    }
        
        # Jurisdictional conflicts (different sources with conflicting rules)
        if "jurisdictional" in conflict_types:
            if stmt1["document_source"] != stmt2["document_source"]:
                if self.actions_are_similar(action1, action2) and mod1 != mod2:
                    return {
                        "id": f"conflict_{stmt1['id']}_{stmt2['id']}",
                        "type": "jurisdictional",
                        "severity": "medium",
                        "entities": [entity],
                        "statement1": stmt1,
                        "statement2": stmt2,
                        "description": f"Jurisdictional conflict between {stmt1['document_source']} and {stmt2['document_source']}",
                        "resolution": self.suggest_conflict_resolution(stmt1, stmt2, "jurisdictional")
                    }
        
        # Temporal conflicts (rules changing over time)
        if "temporal" in conflict_types:
            date1 = stmt1.get("document_date", "")
            date2 = stmt2.get("document_date", "")
            if date1 and date2 and date1 != date2:
                if self.actions_are_similar(action1, action2) and mod1 != mod2:
                    return {
                        "id": f"conflict_{stmt1['id']}_{stmt2['id']}",
                        "type": "temporal",
                        "severity": "low",
                        "entities": [entity],
                        "statement1": stmt1,
                        "statement2": stmt2,
                        "description": f"Temporal conflict: rule changed between {date1} and {date2}",
                        "resolution": self.suggest_conflict_resolution(stmt1, stmt2, "temporal")
                    }
        
        return None
    
    def actions_are_similar(self, action1: str, action2: str, threshold: float = 0.7) -> bool:
        """
        Check if two actions are similar enough to potentially conflict.
        
        Args:
            action1: First action text
            action2: Second action text
            threshold: Similarity threshold (0.0-1.0)
            
        Returns:
            True if actions are similar, False otherwise
        """
        # Simple word overlap similarity
        words1 = set(action1.lower().split())
        words2 = set(action2.lower().split())
        
        if not words1 or not words2:
            return False
            
        intersection = words1.intersection(words2)
        union = words1.union(words2)
        
        similarity = len(intersection) / len(union) if union else 0
        return similarity >= threshold
    
    def organize_by_entities(
        self,
        statements: List[Dict[str, Any]],
        conflicts: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Organize statements and conflicts by entity.
        
        Args:
            statements: List of deontic statements
            conflicts: List of conflicts
            
        Returns:
            Dictionary mapping entity names to their statements and conflicts
        """
        entities = {}
        
        # Group statements by entity
        for stmt in statements:
            entity = stmt["entity"]
            if entity not in entities:
                entities[entity] = {
                    "name": entity,
                    "statements": [],
                    "conflicts": [],
                    "modality_counts": {"obligation": 0, "permission": 0, "prohibition": 0},
                    "conflict_severity": {"high": 0, "medium": 0, "low": 0}
                }
            
            entities[entity]["statements"].append(stmt)
            entities[entity]["modality_counts"][stmt["modality"]] += 1
        
        # Add conflicts to entities
        for conflict in conflicts:
            for entity_name in conflict["entities"]:
                if entity_name in entities:
                    entities[entity_name]["conflicts"].append(conflict)
                    entities[entity_name]["conflict_severity"][conflict["severity"]] += 1
        
        return entities
    
    def calculate_conflict_statistics(
        self,
        statements: List[Dict[str, Any]],
        conflicts: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Calculate statistics about conflicts.
        
        Args:
            statements: List of deontic statements
            conflicts: List of conflicts
            
        Returns:
            Dictionary with conflict statistics
        """
        return {
            "total_statements": len(statements),
            "total_conflicts": len(conflicts),
            "modality_distribution": self.count_by_modality(statements),
            "conflict_type_distribution": self.count_by_conflict_type(conflicts),
            "severity_distribution": self.count_by_severity(conflicts),
            "entities_with_conflicts": len(set(
                entity for conflict in conflicts for entity in conflict["entities"]
            )),
            "conflict_rate": len(conflicts) / len(statements) if statements else 0
        }
    
    def count_by_modality(self, statements: List[Dict[str, Any]]) -> Dict[str, int]:
        """Count statements by modality."""
        counts = {"obligation": 0, "permission": 0, "prohibition": 0}
        for stmt in statements:
            counts[stmt["modality"]] = counts.get(stmt["modality"], 0) + 1
        return counts
    
    def count_by_conflict_type(self, conflicts: List[Dict[str, Any]]) -> Dict[str, int]:
        """Count conflicts by type."""
        counts = {}
        for conflict in conflicts:
            conflict_type = conflict["type"]
            counts[conflict_type] = counts.get(conflict_type, 0) + 1
        return counts
    
    def count_by_severity(self, conflicts: List[Dict[str, Any]]) -> Dict[str, int]:
        """Count conflicts by severity."""
        counts = {"high": 0, "medium": 0, "low": 0}
        for conflict in conflicts:
            counts[conflict["severity"]] = counts.get(conflict["severity"], 0) + 1
        return counts
    
    def get_sentence_context(self, text: str, start: int, end: int, window: int = 100) -> str:
        """
        Get sentence context around a match.
        
        Args:
            text: Full text
            start: Start position of match
            end: End position of match
            window: Context window size
            
        Returns:
            Context text around the match
        """
        context_start = max(0, start - window)
        context_end = min(len(text), end + window)
        return text[context_start:context_end].strip()
    
    def calculate_statement_confidence(self, entity: str, action: str, modality: str) -> float:
        """
        Calculate confidence score for a deontic statement.
        
        Args:
            entity: Entity performing the action
            action: Action being performed
            modality: Deontic modality
            
        Returns:
            Confidence score (0.0-1.0)
        """
        # Simple heuristic based on entity and action specificity
        base_confidence = 0.7
        
        # More specific entities get higher confidence
        if len(entity.split()) > 1:
            base_confidence += 0.1
        
        # More specific actions get higher confidence
        if len(action.split()) > 3:
            base_confidence += 0.1
        
        # Obligations tend to be more explicit
        if modality == "obligation":
            base_confidence += 0.05
        
        return min(0.95, base_confidence)
    
    def extract_conditions(self, text: str, start: int, end: int, window: int = 200) -> List[str]:
        """
        Extract conditional clauses around a statement.
        
        Args:
            text: Full text
            start: Start position of statement
            end: End position of statement
            window: Context window size
            
        Returns:
            List of condition strings
        """
        context = text[max(0, start - window):min(len(text), end + window)]
        
        # Look for conditional patterns
        condition_patterns = [
            r"(?:if|when|where|provided that|unless|except when)\s+([^,.]+)",
            r"([^,.]+)\s+(?:if|when|where|provided that)"
        ]
        
        conditions = []
        for pattern in condition_patterns:
            matches = re.finditer(pattern, context, re.IGNORECASE)
            for match in matches:
                conditions.append(match.group(1).strip())
        
        return conditions
    
    def extract_exceptions(self, text: str, start: int, end: int, window: int = 200) -> List[str]:
        """
        Extract exception clauses around a statement.
        
        Args:
            text: Full text
            start: Start position of statement
            end: End position of statement
            window: Context window size
            
        Returns:
            List of exception strings
        """
        context = text[max(0, start - window):min(len(text), end + window)]
        
        # Look for exception patterns
        exception_patterns = [
            r"(?:except|unless|save for|excluding)\s+([^,.]+)",
            r"([^,.]+)\s+(?:except|unless|save for)"
        ]
        
        exceptions = []
        for pattern in exception_patterns:
            matches = re.finditer(pattern, context, re.IGNORECASE)
            for match in matches:
                exceptions.append(match.group(1).strip())
        
        return exceptions
    
    def conditions_overlap(self, conditions1: List[str], conditions2: List[str]) -> bool:
        """
        Check if two sets of conditions overlap.
        
        Args:
            conditions1: First set of conditions
            conditions2: Second set of conditions
            
        Returns:
            True if conditions overlap, False otherwise
        """
        for cond1 in conditions1:
            for cond2 in conditions2:
                if self.actions_are_similar(cond1, cond2, threshold=0.6):
                    return True
        return False
    
    def suggest_conflict_resolution(
        self,
        stmt1: Dict[str, Any],
        stmt2: Dict[str, Any],
        conflict_type: str
    ) -> str:
        """
        Suggest resolution for a conflict.
        
        Args:
            stmt1: First statement
            stmt2: Second statement
            conflict_type: Type of conflict
            
        Returns:
            Suggested resolution strategy
        """
        resolutions = {
            "direct": "Review source authority and temporal precedence. Consider if exceptions apply.",
            "conditional": "Examine condition specificity and determine if conditions are mutually exclusive.",
            "jurisdictional": "Identify governing jurisdiction and applicable legal hierarchy.",
            "temporal": "Apply most recent rule unless explicitly stated otherwise."
        }
        
        base_resolution = resolutions.get(conflict_type, "Manual review required.")
        
        # Add specific context
        if stmt1.get("document_date") and stmt2.get("document_date"):
            if stmt1["document_date"] > stmt2["document_date"]:
                base_resolution += f" Statement from {stmt1['document_date']} is more recent."
            else:
                base_resolution += f" Statement from {stmt2['document_date']} is more recent."
        
        return base_resolution
