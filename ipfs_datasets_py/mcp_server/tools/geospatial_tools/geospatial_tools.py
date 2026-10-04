"""Geographic and geospatial analysis tools for MCP (thin wrapper).

Core implementation lives in
``ipfs_datasets_py.processors.domains.geospatial.geospatial_analysis``.
"""

import json
from typing import Dict, Optional

from ipfs_datasets_py.processors.domains.geospatial.geospatial_analysis import (
    extract_geographic_entities as _extract_geographic_entities,
    map_spatiotemporal_events as _map_spatiotemporal_events,
    query_geographic_context as _query_geographic_context,
)


def extract_geographic_entities(
    corpus_data: str,
    confidence_threshold: float = 0.7,
    include_coordinates: bool = True,
) -> str:
    """MCP tool: Extract geographic entities from corpus data."""
    result = _extract_geographic_entities(
        corpus_data,
        confidence_threshold=confidence_threshold,
        include_coordinates=include_coordinates,
    )
    return json.dumps(result)


def map_spatiotemporal_events(
    corpus_data: str,
    time_range: Optional[Dict] = None,
    clustering_distance: float = 50.0,
    temporal_resolution: str = "day",
) -> str:
    """MCP tool: Map events with spatial-temporal clustering analysis."""
    result = _map_spatiotemporal_events(
        corpus_data,
        time_range=time_range,
        clustering_distance=clustering_distance,
        temporal_resolution=temporal_resolution,
    )
    return json.dumps(result)


def query_geographic_context(
    query: str,
    corpus_data: str,
    radius_km: float = 100.0,
    center_location: Optional[str] = None,
    include_related_entities: bool = True,
    temporal_context: bool = True,
) -> str:
    """MCP tool: Perform natural language geographic queries."""
    result = _query_geographic_context(
        query,
        corpus_data,
        radius_km=radius_km,
        center_location=center_location,
        include_related_entities=include_related_entities,
        temporal_context=temporal_context,
    )
    return json.dumps(result)
