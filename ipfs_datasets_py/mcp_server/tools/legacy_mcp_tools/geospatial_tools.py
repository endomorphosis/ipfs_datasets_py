"""
Geographic and geospatial analysis tools for the MCP server.
Implements the three MCP tools required for the Maps tab functionality.

.. deprecated::
    This legacy module is superseded by
    ``ipfs_datasets_py.mcp_server.tools.geospatial_tools``.
    See ``legacy_mcp_tools/MIGRATION_GUIDE.md`` for migration instructions.
"""
import warnings
warnings.warn(
    "legacy_mcp_tools.geospatial_tools is deprecated. "
    "Use ipfs_datasets_py.mcp_server.tools.geospatial_tools instead.",
    DeprecationWarning,
    stacklevel=2,
)

import json
from typing import Dict, Optional

from ipfs_datasets_py.processors.domains.geospatial.geospatial_analysis import (
    GeospatialAnalysisTools,  # noqa: F401 — re-exported for backward compat
    extract_geographic_entities as _extract_geographic_entities,
    map_spatiotemporal_events as _map_spatiotemporal_events,
    query_geographic_context as _query_geographic_context,
)

# Backward-compatible instance
geospatial_tools = GeospatialAnalysisTools()


def extract_geographic_entities(
    corpus_data: str,
    confidence_threshold: float = 0.7,
    include_coordinates: bool = True,
) -> str:
    """MCP tool: Extract geographic entities from corpus data."""
    result = _extract_geographic_entities(
        corpus_data, confidence_threshold, include_coordinates
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
        corpus_data, time_range, clustering_distance, temporal_resolution
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
        query, corpus_data, radius_km, center_location,
        include_related_entities, temporal_context,
    )
    return json.dumps(result)
