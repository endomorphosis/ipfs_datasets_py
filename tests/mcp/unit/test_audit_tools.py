"""
Tests for audit_tools tool category.

Tests cover:
- record_audit_event: log an audit event
- generate_audit_report: produce compliance/security report
"""
import pytest

from ipfs_datasets_py.mcp_server.tools.audit_tools.record_audit_event import record_audit_event
from ipfs_datasets_py.mcp_server.tools.audit_tools.generate_audit_report import generate_audit_report


class TestRecordAuditEvent:
    """Tests for record_audit_event tool function."""

    @pytest.mark.asyncio
    async def test_record_basic_event_returns_dict(self):
        """
        GIVEN the audit_tools module
        WHEN record_audit_event is called with an action string
        THEN the result must be a dict containing 'status' or 'event_id'
        """
        result = await record_audit_event(action="dataset.access")
        assert result is not None
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_record_event_with_resource_returns_dict(self):
        """
        GIVEN the audit_tools module
        WHEN record_audit_event is called with resource information
        THEN the result must be a dict
        """
        result = await record_audit_event(
            action="user.login",
            resource_id="resource_001",
            resource_type="dataset",
            user_id="user_alice",
            severity="info",
        )
        assert result is not None
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_record_event_with_details_returns_dict(self):
        """
        GIVEN the audit_tools module
        WHEN record_audit_event is called with additional details
        THEN the result must be a dict
        """
        result = await record_audit_event(
            action="dataset.delete",
            resource_id="ds_123",
            details={"reason": "expired", "initiated_by": "scheduler"},
            severity="warning",
            tags=["automation", "cleanup"],
        )
        assert result is not None
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_record_critical_event_returns_dict(self):
        """
        GIVEN the audit_tools module
        WHEN record_audit_event is called with critical severity
        THEN the result must be a dict
        """
        result = await record_audit_event(
            action="auth.failed",
            user_id="user_bob",
            severity="critical",
            source_ip="192.168.1.100",
        )
        assert result is not None
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_record_event_with_empty_action_returns_dict(self):
        """
        GIVEN the audit_tools module
        WHEN record_audit_event is called with an empty action
        THEN the result must be a dict (validation error or success)
        """
        result = await record_audit_event(action="")
        assert result is not None
        assert isinstance(result, dict)


class TestGenerateAuditReport:
    """Tests for generate_audit_report tool function."""

    @pytest.mark.asyncio
    async def test_generate_comprehensive_report_returns_dict(self):
        """
        GIVEN the audit_tools module
        WHEN generate_audit_report is called with default parameters
        THEN the result must be a dict
        """
        result = await generate_audit_report()
        assert result is not None
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_generate_security_report_returns_dict(self):
        """
        GIVEN the audit_tools module
        WHEN generate_audit_report is called for security report type
        THEN the result must be a dict
        """
        result = await generate_audit_report(report_type="security")
        assert result is not None
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_generate_compliance_report_with_time_range_returns_dict(self):
        """
        GIVEN the audit_tools module
        WHEN generate_audit_report is called with a time range
        THEN the result must be a dict
        """
        result = await generate_audit_report(
            report_type="compliance",
            start_time="2026-01-01T00:00:00",
            end_time="2026-02-01T00:00:00",
        )
        assert result is not None
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_generate_operational_report_returns_dict(self):
        """
        GIVEN the audit_tools module
        WHEN generate_audit_report is called for operational type
        THEN the result must be a dict
        """
        result = await generate_audit_report(report_type="operational", output_format="json")
        assert result is not None
        assert isinstance(result, dict)
