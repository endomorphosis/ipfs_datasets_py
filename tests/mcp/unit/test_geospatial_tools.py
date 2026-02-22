"""
Phase B2 (session 30): Unit tests for geospatial_tools tool category.

Tests cover:
- extract_geographic_entities: entity extraction from corpus
- map_spatiotemporal_events: spatial-temporal clustering
- query_geographic_context: natural language geographic queries
"""
from __future__ import annotations

import json
import pytest


class TestExtractGeographicEntities:
    """Tests for extract_geographic_entities tool function."""

    def test_returns_json_string(self):
        """
        GIVEN valid corpus data text
        WHEN extract_geographic_entities is called
        THEN result must be a JSON-parseable string.
        """
        from ipfs_datasets_py.mcp_server.tools.geospatial_tools.geospatial_tools import (
            extract_geographic_entities,
        )
        result = extract_geographic_entities("The earthquake struck Tokyo, Japan.")
        parsed = json.loads(result)
        assert isinstance(parsed, dict)

    def test_returns_entities_key(self):
        """
        GIVEN valid corpus data
        WHEN extract_geographic_entities is called
        THEN result dict must contain 'entities' key.
        """
        from ipfs_datasets_py.mcp_server.tools.geospatial_tools.geospatial_tools import (
            extract_geographic_entities,
        )
        result = json.loads(
            extract_geographic_entities("Floods hit Paris, France and Berlin, Germany.")
        )
        assert "entities" in result

    def test_low_confidence_threshold(self):
        """
        GIVEN confidence_threshold=0.0 (accept all)
        WHEN extract_geographic_entities is called
        THEN result must be a dict (entities may be empty but should not raise).
        """
        from ipfs_datasets_py.mcp_server.tools.geospatial_tools.geospatial_tools import (
            extract_geographic_entities,
        )
        result = json.loads(
            extract_geographic_entities("Some text", confidence_threshold=0.0)
        )
        assert isinstance(result, dict)

    def test_include_coordinates_false(self):
        """
        GIVEN include_coordinates=False
        WHEN extract_geographic_entities is called
        THEN result must still be a valid dict without raising.
        """
        from ipfs_datasets_py.mcp_server.tools.geospatial_tools.geospatial_tools import (
            extract_geographic_entities,
        )
        result = json.loads(
            extract_geographic_entities("London, UK", include_coordinates=False)
        )
        assert isinstance(result, dict)


class TestMapSpatiotemporalEvents:
    """Tests for map_spatiotemporal_events tool function."""

    def test_returns_json_string(self):
        """
        GIVEN corpus text
        WHEN map_spatiotemporal_events is called
        THEN result must be a JSON-parseable string.
        """
        from ipfs_datasets_py.mcp_server.tools.geospatial_tools.geospatial_tools import (
            map_spatiotemporal_events,
        )
        result = map_spatiotemporal_events("Events in New York on 2024-01-15.")
        parsed = json.loads(result)
        assert isinstance(parsed, dict)

    def test_with_time_range(self):
        """
        GIVEN explicit time_range dict
        WHEN map_spatiotemporal_events is called
        THEN result must be a dict without raising.
        """
        from ipfs_datasets_py.mcp_server.tools.geospatial_tools.geospatial_tools import (
            map_spatiotemporal_events,
        )
        result = json.loads(
            map_spatiotemporal_events(
                "Storms across the US",
                time_range={"start": "2024-01-01", "end": "2024-12-31"},
            )
        )
        assert isinstance(result, dict)

    def test_custom_clustering_distance(self):
        """
        GIVEN clustering_distance=200.0 km
        WHEN map_spatiotemporal_events is called
        THEN result must be a dict.
        """
        from ipfs_datasets_py.mcp_server.tools.geospatial_tools.geospatial_tools import (
            map_spatiotemporal_events,
        )
        result = json.loads(
            map_spatiotemporal_events("Wildfire in California", clustering_distance=200.0)
        )
        assert isinstance(result, dict)


class TestQueryGeographicContext:
    """Tests for query_geographic_context tool function."""

    def test_returns_json_string(self):
        """
        GIVEN a natural language query and corpus
        WHEN query_geographic_context is called
        THEN result must be a JSON-parseable string.
        """
        from ipfs_datasets_py.mcp_server.tools.geospatial_tools.geospatial_tools import (
            query_geographic_context,
        )
        result = query_geographic_context(
            "What events happened in Europe?",
            "Protests in Berlin and Paris last month.",
        )
        parsed = json.loads(result)
        assert isinstance(parsed, dict)

    def test_with_center_location(self):
        """
        GIVEN center_location parameter
        WHEN query_geographic_context is called
        THEN result must be a dict without raising.
        """
        from ipfs_datasets_py.mcp_server.tools.geospatial_tools.geospatial_tools import (
            query_geographic_context,
        )
        result = json.loads(
            query_geographic_context(
                "Floods near the coast?",
                "Heavy rains in Miami and Tampa.",
                center_location="Miami, FL",
                radius_km=50.0,
            )
        )
        assert isinstance(result, dict)

    def test_no_temporal_context(self):
        """
        GIVEN temporal_context=False
        WHEN query_geographic_context is called
        THEN result must still be a valid dict.
        """
        from ipfs_datasets_py.mcp_server.tools.geospatial_tools.geospatial_tools import (
            query_geographic_context,
        )
        result = json.loads(
            query_geographic_context(
                "Cities in Asia?",
                "Tokyo, Beijing, Singapore.",
                temporal_context=False,
            )
        )
        assert isinstance(result, dict)
