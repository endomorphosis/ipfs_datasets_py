#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Deontological Reasoning MCP Tools

Provides MCP tools for legal and ethical analysis using deontic logic.
"""
from __future__ import annotations

import anyio
import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
import re

from ..tool_wrapper import wrap_function_as_tool

logger = logging.getLogger(__name__)


@wrap_function_as_tool(
    name="analyze_deontological_conflicts",
    description="Analyze deontological conflicts in corpus using deontic logic",
    category="investigation"
)
async def analyze_deontological_conflicts(
    corpus_data: str,
    conflict_types: Optional[List[str]] = None,
    severity_threshold: str = "medium",
    entity_filter: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Analyze deontological conflicts in document corpus.
    
    Args:
        corpus_data: JSON string containing document corpus data
        conflict_types: Types of conflicts to detect (direct, conditional, jurisdictional, temporal)
        severity_threshold: Minimum severity level (low, medium, high)
        entity_filter: Filter conflicts by specific entities
        
    Returns:
        Dictionary containing conflict analysis results
    """
    try:
        # Parse corpus data
        if isinstance(corpus_data, str):
            corpus = json.loads(corpus_data)
        else:
            corpus = corpus_data
            
        # Initialize analysis results
        results = {
            "analysis_id": f"deontic_analysis_{datetime.now().isoformat()}",
            "conflict_types": conflict_types or ["direct", "conditional", "jurisdictional", "temporal"],
            "severity_threshold": severity_threshold,
            "entity_filter": entity_filter,
            "deontic_statements": [],
            "conflicts": [],
            "entities": {},
            "statistics": {},
            "timestamp": datetime.now().isoformat()
        }
        
        # Extract deontic statements from corpus
        deontic_statements = await _extract_deontic_statements(corpus, entity_filter)
        results["deontic_statements"] = deontic_statements
        
        # Detect conflicts between statements
        conflicts = await _detect_deontic_conflicts(deontic_statements, conflict_types)
        results["conflicts"] = conflicts
        
        # Organize by entities
        entity_analysis = _organize_by_entities(deontic_statements, conflicts)
        results["entities"] = entity_analysis
        
        # Calculate statistics
        results["statistics"] = _calculate_conflict_statistics(deontic_statements, conflicts)
        
        logger.info(f"Deontological analysis completed: {len(deontic_statements)} statements, {len(conflicts)} conflicts")
        return results
        
    except Exception as e:
        logger.error(f"Deontological analysis failed: {e}")
        return {
            "error": str(e),
            "analysis_id": None,
            "timestamp": datetime.now().isoformat()
        }


@wrap_function_as_tool(
    name="query_deontic_statements",
    description="Query deontic statements by entity, modality, or content",
    category="investigation"
)
async def query_deontic_statements(
    corpus_data: str,
    entity: Optional[str] = None,
    modality: Optional[str] = None,
    action_pattern: Optional[str] = None,
    confidence_min: float = 0.0
) -> Dict[str, Any]:
    """
    Query deontic statements in the corpus.
    
    Args:
        corpus_data: JSON string containing document corpus data
        entity: Filter by specific entity
        modality: Filter by deontic modality (obligation, permission, prohibition)
        action_pattern: Regex pattern to match actions
        confidence_min: Minimum confidence score
        
    Returns:
        Dictionary containing matching deontic statements
    """
    try:
        # Parse corpus data
        if isinstance(corpus_data, str):
            corpus = json.loads(corpus_data)
        else:
            corpus = corpus_data
            
        # Extract all deontic statements
        all_statements = await _extract_deontic_statements(corpus)
        
        # Apply filters
        filtered_statements = []
        for statement in all_statements:
            # Entity filter
            if entity and entity.lower() not in statement.get("entity", "").lower():
                continue
                
            # Modality filter
            if modality and statement.get("modality") != modality:
                continue
                
            # Action pattern filter
            if action_pattern:
                try:
                    if not re.search(action_pattern, statement.get("action", ""), re.IGNORECASE):
                        continue
                except re.error:
                    logger.warning(f"Invalid regex pattern: {action_pattern}")
                    continue
                    
            # Confidence filter
            if statement.get("confidence", 0) < confidence_min:
                continue
                
            filtered_statements.append(statement)
        
        results = {
            "query": {
                "entity": entity,
                "modality": modality,
                "action_pattern": action_pattern,
                "confidence_min": confidence_min
            },
            "total_statements": len(all_statements),
            "matching_statements": len(filtered_statements),
            "statements": filtered_statements,
            "timestamp": datetime.now().isoformat()
        }
        
        logger.info(f"Deontic query completed: {len(filtered_statements)} matching statements")
        return results
        
    except Exception as e:
        logger.error(f"Deontic query failed: {e}")
        return {
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }


@wrap_function_as_tool(
    name="query_deontic_conflicts",
    description="Query specific conflicts by type, severity, or entities",
    category="investigation"
)
async def query_deontic_conflicts(
    corpus_data: str,
    conflict_type: Optional[str] = None,
    severity: Optional[str] = None,
    entity: Optional[str] = None,
    resolved_only: bool = False
) -> Dict[str, Any]:
    """
    Query deontic conflicts in the corpus.
    
    Args:
        corpus_data: JSON string containing document corpus data
        conflict_type: Filter by conflict type
        severity: Filter by severity level
        entity: Filter by involved entity
        resolved_only: Only return conflicts with resolutions
        
    Returns:
        Dictionary containing matching conflicts
    """
    try:
        # Parse corpus data
        if isinstance(corpus_data, str):
            corpus = json.loads(corpus_data)
        else:
            corpus = corpus_data
            
        # Get all conflicts through full analysis
        analysis_result = await analyze_deontological_conflicts(corpus)
        if "error" in analysis_result:
            return analysis_result
            
        all_conflicts = analysis_result["conflicts"]
        
        # Apply filters
        filtered_conflicts = []
        for conflict in all_conflicts:
            # Conflict type filter
            if conflict_type and conflict.get("type") != conflict_type:
                continue
                
            # Severity filter
            if severity and conflict.get("severity") != severity:
                continue
                
            # Entity filter
            if entity:
                entities = conflict.get("entities", [])
                if not any(entity.lower() in ent.lower() for ent in entities):
                    continue
                    
            # Resolution filter
            if resolved_only and not conflict.get("resolution"):
                continue
                
            filtered_conflicts.append(conflict)
        
        results = {
            "query": {
                "conflict_type": conflict_type,
                "severity": severity,
                "entity": entity,
                "resolved_only": resolved_only
            },
            "total_conflicts": len(all_conflicts),
            "matching_conflicts": len(filtered_conflicts),
            "conflicts": filtered_conflicts,
            "timestamp": datetime.now().isoformat()
        }
        
        logger.info(f"Conflict query completed: {len(filtered_conflicts)} matching conflicts")
        return results
        
    except Exception as e:
        logger.error(f"Conflict query failed: {e}")
        return {
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }


# Helper functions for deontic analysis

async def _extract_deontic_statements(corpus: Dict[str, Any], entity_filter: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """Extract deontic statements from corpus documents."""
    statements = []
    
    if "documents" not in corpus:
        return statements
        
    # Deontic patterns for different modalities
    patterns = {
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
    
    for doc_id, document in enumerate(corpus["documents"]):
        content = document.get("content", "") + " " + document.get("title", "")
        source = document.get("source", "unknown")
        date = document.get("date", datetime.now().isoformat())
        
        for modality, pattern_list in patterns.items():
            for pattern in pattern_list:
                matches = re.finditer(pattern, content, re.IGNORECASE)
                for match in matches:
                    entity = match.group(1).strip()
                    action = match.group(2).strip()
                    
                    # Apply entity filter if provided
                    if entity_filter and not any(filter_ent.lower() in entity.lower() for filter_ent in entity_filter):
                        continue
                    
                    statement = {
                        "id": f"stmt_{doc_id}_{len(statements)}",
                        "entity": entity,
                        "modality": modality,
                        "action": action,
                        "document_id": doc_id,
                        "document_source": source,
                        "document_date": date,
                        "context": _get_sentence_context(content, match.start(), match.end()),
                        "confidence": _calculate_statement_confidence(entity, action, modality),
                        "conditions": _extract_conditions(content, match.start(), match.end()),
                        "exceptions": _extract_exceptions(content, match.start(), match.end())
                    }
                    statements.append(statement)
    
    return statements


async def _detect_deontic_conflicts(statements: List[Dict[str, Any]], conflict_types: List[str]) -> List[Dict[str, Any]]:
    """Detect conflicts between deontic statements."""
    conflicts = []
    
    for i, stmt1 in enumerate(statements):
        for j, stmt2 in enumerate(statements[i+1:], i+1):
            conflict = _check_statement_conflict(stmt1, stmt2, conflict_types)
            if conflict:
                conflicts.append(conflict)
    
    return conflicts


def _check_statement_conflict(stmt1: Dict[str, Any], stmt2: Dict[str, Any], conflict_types: List[str]) -> Optional[Dict[str, Any]]:
    """Check if two statements conflict."""
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
        if _actions_are_similar(action1, action2):
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
                    "resolution": _suggest_conflict_resolution(stmt1, stmt2, "direct")
                }
    
    # Conditional conflicts
    if "conditional" in conflict_types:
        conditions1 = stmt1.get("conditions", [])
        conditions2 = stmt2.get("conditions", [])
        if conditions1 and conditions2 and _conditions_overlap(conditions1, conditions2):
            if mod1 != mod2 and _actions_are_similar(action1, action2):
                return {
                    "id": f"conflict_{stmt1['id']}_{stmt2['id']}",
                    "type": "conditional",
                    "severity": "medium",
                    "entities": [entity],
                    "statement1": stmt1,
                    "statement2": stmt2,
                    "description": f"Conditional conflict: {entity} under overlapping conditions",
                    "resolution": _suggest_conflict_resolution(stmt1, stmt2, "conditional")
                }
    
    # Jurisdictional conflicts (different sources with conflicting rules)
    if "jurisdictional" in conflict_types:
        if stmt1["document_source"] != stmt2["document_source"]:
            if _actions_are_similar(action1, action2) and mod1 != mod2:
                return {
                    "id": f"conflict_{stmt1['id']}_{stmt2['id']}",
                    "type": "jurisdictional",
                    "severity": "medium",
                    "entities": [entity],
                    "statement1": stmt1,
                    "statement2": stmt2,
                    "description": f"Jurisdictional conflict between {stmt1['document_source']} and {stmt2['document_source']}",
                    "resolution": _suggest_conflict_resolution(stmt1, stmt2, "jurisdictional")
                }
    
    # Temporal conflicts (rules changing over time)
    if "temporal" in conflict_types:
        date1 = stmt1.get("document_date", "")
        date2 = stmt2.get("document_date", "")
        if date1 and date2 and date1 != date2:
            if _actions_are_similar(action1, action2) and mod1 != mod2:
                return {
                    "id": f"conflict_{stmt1['id']}_{stmt2['id']}",
                    "type": "temporal",
                    "severity": "low",
                    "entities": [entity],
                    "statement1": stmt1,
                    "statement2": stmt2,
                    "description": f"Temporal conflict: rule changed between {date1} and {date2}",
                    "resolution": _suggest_conflict_resolution(stmt1, stmt2, "temporal")
                }
    
    return None


def _actions_are_similar(action1: str, action2: str, threshold: float = 0.7) -> bool:
    """Check if two actions are similar enough to potentially conflict."""
    # Simple word overlap similarity
    words1 = set(action1.lower().split())
    words2 = set(action2.lower().split())
    
    if not words1 or not words2:
        return False
        
    intersection = words1.intersection(words2)
    union = words1.union(words2)
    
    similarity = len(intersection) / len(union) if union else 0
    return similarity >= threshold


def _organize_by_entities(statements: List[Dict[str, Any]], conflicts: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Organize statements and conflicts by entity."""
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


def _calculate_conflict_statistics(statements: List[Dict[str, Any]], conflicts: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Calculate statistics about conflicts."""
    return {
        "total_statements": len(statements),
        "total_conflicts": len(conflicts),
        "modality_distribution": _count_by_modality(statements),
        "conflict_type_distribution": _count_by_conflict_type(conflicts),
        "severity_distribution": _count_by_severity(conflicts),
        "entities_with_conflicts": len(set(entity for conflict in conflicts for entity in conflict["entities"])),
        "conflict_rate": len(conflicts) / len(statements) if statements else 0
    }


def _count_by_modality(statements: List[Dict[str, Any]]) -> Dict[str, int]:
    """Count statements by modality."""
    counts = {"obligation": 0, "permission": 0, "prohibition": 0}
    for stmt in statements:
        counts[stmt["modality"]] = counts.get(stmt["modality"], 0) + 1
    return counts


def _count_by_conflict_type(conflicts: List[Dict[str, Any]]) -> Dict[str, int]:
    """Count conflicts by type."""
    counts = {}
    for conflict in conflicts:
        conflict_type = conflict["type"]
        counts[conflict_type] = counts.get(conflict_type, 0) + 1
    return counts


def _count_by_severity(conflicts: List[Dict[str, Any]]) -> Dict[str, int]:
    """Count conflicts by severity."""
    counts = {"high": 0, "medium": 0, "low": 0}
    for conflict in conflicts:
        counts[conflict["severity"]] = counts.get(conflict["severity"], 0) + 1
    return counts


def _get_sentence_context(text: str, start: int, end: int, window: int = 100) -> str:
    """Get sentence context around a match."""
    context_start = max(0, start - window)
    context_end = min(len(text), end + window)
    return text[context_start:context_end].strip()


def _calculate_statement_confidence(entity: str, action: str, modality: str) -> float:
    """Calculate confidence score for a deontic statement."""
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


def _extract_conditions(text: str, start: int, end: int, window: int = 200) -> List[str]:
    """Extract conditional clauses around a statement."""
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


def _extract_exceptions(text: str, start: int, end: int, window: int = 200) -> List[str]:
    """Extract exception clauses around a statement."""
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


def _conditions_overlap(conditions1: List[str], conditions2: List[str]) -> bool:
    """Check if two sets of conditions overlap."""
    for cond1 in conditions1:
        for cond2 in conditions2:
            if _actions_are_similar(cond1, cond2, threshold=0.6):
                return True
    return False


def _suggest_conflict_resolution(stmt1: Dict[str, Any], stmt2: Dict[str, Any], conflict_type: str) -> str:
    """Suggest resolution for a conflict."""
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