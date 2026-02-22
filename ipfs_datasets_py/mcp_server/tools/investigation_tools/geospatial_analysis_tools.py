#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Geospatial Analysis MCP Tools (thin wrapper)

Business logic lives in geospatial_analysis_engine.GeospatialAnalysisEngine.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

import anyio

from ..tool_wrapper import wrap_function_as_tool
from .geospatial_analysis_engine import GeospatialAnalysisEngine

logger = logging.getLogger(__name__)

_engine = GeospatialAnalysisEngine()


@wrap_function_as_tool(
    name="extract_geographic_entities",
    description="Extract and geocode location entities from corpus data for mapping",
    category="investigation"
)
async def extract_geographic_entities(
    corpus_data: str,
    confidence_threshold: float = 0.8,
    entity_types: Optional[List[str]] = None,
    include_coordinates: bool = True,
    geographic_scope: Optional[str] = None
) -> Dict[str, Any]:
    """Extract geographic entities from corpus and attempt to geocode them."""
    return _engine.extract_geographic_entities(
        corpus_data, confidence_threshold, entity_types,
        include_coordinates, geographic_scope
    )


@wrap_function_as_tool(
    name="map_spatiotemporal_events",
    description="Map events with both spatial and temporal dimensions for investigation analysis",
    category="investigation"
)
async def map_spatiotemporal_events(
    corpus_data: str,
    time_range: Optional[Dict[str, str]] = None,
    geographic_bounds: Optional[Dict[str, float]] = None,
    event_types: Optional[List[str]] = None,
    clustering_distance: float = 50.0,
    temporal_resolution: str = "day"
) -> Dict[str, Any]:
    """Map events with spatial and temporal dimensions for investigation analysis."""
    if isinstance(corpus_data, str):
        corpus = json.loads(corpus_data)
    else:
        corpus = corpus_data
    geo_result = _engine.extract_geographic_entities(
        corpus_data, confidence_threshold=0.7, include_coordinates=True
    )
    entities = geo_result.get("entities", [])
    return _engine.map_spatiotemporal_events(entities, time_range, temporal_resolution)


@wrap_function_as_tool(
    name="query_geographic_context",
    description="Query geographic context and relationships for investigation analysis",
    category="investigation"
)
async def query_geographic_context(
    query: str,
    corpus_data: str,
    radius_km: float = 100.0,
    center_location: Optional[str] = None,
    include_related_entities: bool = True,
    temporal_context: bool = True
) -> Dict[str, Any]:
    """Query geographic context and relationships for investigation analysis."""
    geo_result = _engine.extract_geographic_entities(
        corpus_data, confidence_threshold=0.6
    )
    entities = geo_result.get("entities", [])
    return _engine.query_geographic_context(query, entities, radius_km)


# Re-export helpers for backward compatibility
def _calculate_distance(lat1, lon1, lat2, lon2):
    return _engine._calculate_distance(lat1, lon1, lat2, lon2)
