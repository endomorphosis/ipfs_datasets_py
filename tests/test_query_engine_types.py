"""
Tests for query_engine TypedDict contracts.
"""

import pytest
from ipfs_datasets_py.processors.query_engine import (
    QueryAnalyticsDict,
)


class TestQueryAnalyticsDict:
    """Test QueryAnalyticsDict contract."""
    
    def test_query_analytics_structure(self):
        """Verify query analytics structure."""
        sample: QueryAnalyticsDict = {
            "total_queries": 100,
            "avg_response_time": 45.5,
            "unique_entities": 50,
            "total_relationships": 120,
            "query_types": {"semantic": 60, "keyword": 40},
            "performance_metrics": {"cache_hit_rate": 0.75},
            "timestamp": "2024-01-01T00:00:00"
        }
        assert isinstance(sample.get("total_queries"), (int, type(None)))
        assert isinstance(sample.get("avg_response_time"), (float, type(None)))
    
    def test_query_analytics_partial(self):
        """Verify partial field sets work."""
        minimal: QueryAnalyticsDict = {"total_queries": 10}
        assert "total_queries" in minimal
        assert isinstance(minimal["total_queries"], int)
    
    def test_query_analytics_types(self):
        """Verify field types."""
        sample: QueryAnalyticsDict = {
            "query_types": {"type1": 5, "type2": 3},
            "performance_metrics": {"metric": "value"}
        }
        assert isinstance(sample.get("query_types"), (dict, type(None)))
        assert isinstance(sample.get("performance_metrics"), (dict, type(None)))


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
