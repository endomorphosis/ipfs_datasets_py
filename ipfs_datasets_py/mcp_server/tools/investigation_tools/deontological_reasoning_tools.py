#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Deontological Reasoning MCP Tools (Thin Wrapper)

Provides MCP tools for legal and ethical analysis using deontic logic.
This is a thin wrapper around the DeonticAnalyzer core module.
"""
from __future__ import annotations

import anyio
import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from ipfs_datasets_py.logic.deontic import DeonticAnalyzer
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
        
        # Initialize analyzer
        analyzer = DeonticAnalyzer()
        
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
        deontic_statements = await analyzer.extract_deontic_statements(corpus, entity_filter)
        results["deontic_statements"] = deontic_statements
        
        # Detect conflicts between statements
        conflicts = await analyzer.detect_deontic_conflicts(deontic_statements, results["conflict_types"])
        results["conflicts"] = conflicts
        
        # Organize by entities
        entity_analysis = analyzer.organize_by_entities(deontic_statements, conflicts)
        results["entities"] = entity_analysis
        
        # Calculate statistics
        results["statistics"] = analyzer.calculate_conflict_statistics(deontic_statements, conflicts)
        
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
    action_pattern: Optional[str] = None
) -> Dict[str, Any]:
    """
    Query and filter deontic statements from a corpus.
    
    Args:
        corpus_data: JSON string containing document corpus data
        entity: Filter by entity name (partial match)
        modality: Filter by modality (obligation, permission, prohibition)
        action_pattern: Filter by action pattern (partial match)
        
    Returns:
        Dictionary containing filtered statements
    """
    try:
        # Parse corpus data
        if isinstance(corpus_data, str):
            corpus = json.loads(corpus_data)
        else:
            corpus = corpus_data
        
        # Initialize analyzer
        analyzer = DeonticAnalyzer()
        
        # Extract all deontic statements
        all_statements = await analyzer.extract_deontic_statements(corpus)
        
        # Apply filters
        filtered_statements = all_statements
        
        if entity:
            filtered_statements = [
                stmt for stmt in filtered_statements
                if entity.lower() in stmt["entity"].lower()
            ]
        
        if modality:
            filtered_statements = [
                stmt for stmt in filtered_statements
                if stmt["modality"] == modality.lower()
            ]
        
        if action_pattern:
            filtered_statements = [
                stmt for stmt in filtered_statements
                if action_pattern.lower() in stmt["action"].lower()
            ]
        
        # Calculate statistics
        statistics = analyzer.calculate_conflict_statistics(filtered_statements, [])
        
        return {
            "query": {
                "entity": entity,
                "modality": modality,
                "action_pattern": action_pattern
            },
            "total_found": len(filtered_statements),
            "statements": filtered_statements,
            "statistics": statistics,
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Deontic statement query failed: {e}")
        return {
            "error": str(e),
            "total_found": 0,
            "statements": [],
            "timestamp": datetime.now().isoformat()
        }


@wrap_function_as_tool(
    name="query_deontic_conflicts",
    description="Query conflicts by type, severity, or entity",
    category="investigation"
)
async def query_deontic_conflicts(
    corpus_data: str,
    conflict_type: Optional[str] = None,
    severity: Optional[str] = None,
    entity: Optional[str] = None
) -> Dict[str, Any]:
    """
    Query and filter deontic conflicts from a corpus.
    
    Args:
        corpus_data: JSON string containing document corpus data
        conflict_type: Filter by conflict type
        severity: Filter by severity (high, medium, low)
        entity: Filter by entity involved
        
    Returns:
        Dictionary containing filtered conflicts
    """
    try:
        # Parse corpus data
        if isinstance(corpus_data, str):
            corpus = json.loads(corpus_data)
        else:
            corpus = corpus_data
        
        # Initialize analyzer
        analyzer = DeonticAnalyzer()
        
        # Extract statements and detect all conflicts
        all_statements = await analyzer.extract_deontic_statements(corpus)
        all_conflict_types = ["direct", "conditional", "jurisdictional", "temporal"]
        all_conflicts = await analyzer.detect_deontic_conflicts(all_statements, all_conflict_types)
        
        # Apply filters
        filtered_conflicts = all_conflicts
        
        if conflict_type:
            filtered_conflicts = [
                conf for conf in filtered_conflicts
                if conf["type"] == conflict_type.lower()
            ]
        
        if severity:
            filtered_conflicts = [
                conf for conf in filtered_conflicts
                if conf["severity"] == severity.lower()
            ]
        
        if entity:
            filtered_conflicts = [
                conf for conf in filtered_conflicts
                if any(entity.lower() in ent.lower() for ent in conf["entities"])
            ]
        
        return {
            "query": {
                "conflict_type": conflict_type,
                "severity": severity,
                "entity": entity
            },
            "total_found": len(filtered_conflicts),
            "conflicts": filtered_conflicts,
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Deontic conflict query failed: {e}")
        return {
            "error": str(e),
            "total_found": 0,
            "conflicts": [],
            "timestamp": datetime.now().isoformat()
        }
