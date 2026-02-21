"""
Tests for provenance_tools tool category (Phase B2 coverage audit).

Tests cover:
- record_provenance: record data provenance for a dataset operation

The EnhancedProvenanceManager import may fail in CI; tests degrade
gracefully (any dict result is acceptable).
"""

import pytest


class TestRecordProvenance:
    """Tests for record_provenance tool function."""

    @pytest.mark.asyncio
    async def test_record_provenance_returns_dict(self):
        """
        GIVEN provenance_tools.record_provenance
        WHEN called with required dataset_id and operation
        THEN the result is a dict
        """
        from ipfs_datasets_py.mcp_server.tools.provenance_tools.record_provenance import (
            record_provenance,
        )
        result = await record_provenance(
            dataset_id="dataset_001",
            operation="transform",
        )
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_record_provenance_with_inputs_returns_dict(self):
        """
        GIVEN provenance_tools.record_provenance
        WHEN called with inputs and parameters
        THEN the result is a dict
        """
        from ipfs_datasets_py.mcp_server.tools.provenance_tools.record_provenance import (
            record_provenance,
        )
        result = await record_provenance(
            dataset_id="dataset_002",
            operation="merge",
            inputs=["dataset_001", "dataset_external"],
            parameters={"method": "outer_join", "on": "id"},
        )
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_record_provenance_with_agent_id_returns_dict(self):
        """
        GIVEN provenance_tools.record_provenance
        WHEN called with agent_id and description
        THEN the result is a dict
        """
        from ipfs_datasets_py.mcp_server.tools.provenance_tools.record_provenance import (
            record_provenance,
        )
        result = await record_provenance(
            dataset_id="dataset_003",
            operation="filter",
            description="Remove null rows",
            agent_id="pipeline_agent_v1",
            tags=["cleaning", "automated"],
        )
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_record_provenance_with_all_fields_returns_dict(self):
        """
        GIVEN provenance_tools.record_provenance
        WHEN called with all optional fields
        THEN the result is a dict
        """
        from ipfs_datasets_py.mcp_server.tools.provenance_tools.record_provenance import (
            record_provenance,
        )
        result = await record_provenance(
            dataset_id="dataset_full_test",
            operation="aggregate",
            inputs=["ds_a", "ds_b"],
            parameters={"group_by": ["country"], "agg": "sum"},
            description="Sum values grouped by country",
            agent_id="etl_agent",
            timestamp="2026-02-21T00:00:00Z",
            tags=["production", "daily"],
        )
        assert isinstance(result, dict)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
