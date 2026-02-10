# ipfs_datasets_py/mcp_server/tools/audit_tools/generate_audit_report.py
"""
MCP tool for generating audit reports.

This tool handles generating reports based on audit logs.
"""
import anyio
import datetime
import json
from typing import Dict, Any, Optional, Union, List

import logging

logger = logging.getLogger(__name__)
from ipfs_datasets_py.audit.audit_visualization import AuditMetricsAggregator
from ipfs_datasets_py.audit.audit_reporting import AuditReportGenerator

try:
    from ipfs_datasets_py import ipfs_datasets as ipfs_datasets  # type: ignore
except Exception:
    ipfs_datasets = None  # type: ignore

from ipfs_datasets_py.mcp_server.tools.mcp_helpers import (
    mcp_error_response,
    mcp_text_response,
    parse_json_object,
)


async def generate_audit_report(
    report_type: str = "comprehensive", # Changed default to comprehensive
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    filters: Optional[Dict[str, Any]] = None,
    output_format: str = "json",
    output_path: Optional[str] = None,
    include_details: bool = True # This parameter is not directly used by AuditReportGenerator's public methods
) -> Dict[str, Any]:
    """
    Generate an audit report based on audit logs.

    Args:
        report_type: Type of report ('security', 'compliance', 'operational', 'comprehensive')
        start_time: Optional start time for the report period (ISO format)
        end_time: Optional end time for the report period (ISO format)
        filters: Optional filters to apply to the audit logs
        output_format: Format of the report ('json', 'html', 'pdf')
        output_path: Optional path to save the report

    Returns:
        Dict containing information about the generated report
    """
    # MCP JSON-string entrypoint (used by unit tests)
    if (
        isinstance(report_type, str)
        and start_time is None
        and end_time is None
        and filters is None
        and output_format == "json"
        and output_path is None
        and include_details is True
        and (report_type.lstrip().startswith("{") or report_type.lstrip().startswith("[") or any(ch.isspace() for ch in report_type) or not report_type.strip())
    ):
        data, error = parse_json_object(report_type)
        if error is not None:
            return error

        if ipfs_datasets is None:
            return mcp_error_response("ipfs_datasets backend is not available")

        try:
            result = ipfs_datasets.generate_audit_report(
                report_type=data.get("report_type", "comprehensive"),
                start_time=data.get("start_time"),
                end_time=data.get("end_time"),
                filters=data.get("filters"),
                output_format=data.get("output_format", "json"),
                output_path=data.get("output_path"),
            )
            payload: Dict[str, Any] = {"status": "success"}
            if isinstance(result, dict):
                payload.update(result)
            else:
                payload["result"] = result
            return mcp_text_response(payload)
        except Exception as e:
            return mcp_text_response({"status": "error", "error": str(e)})

    try:
        logger.info(f"Generating {report_type} audit report")

        # Create a basic metrics aggregator for the reporter.
        # In a real scenario, this would be populated with actual audit data.
        metrics_aggregator = AuditMetricsAggregator()

        # Create a reporter instance
        reporter = AuditReportGenerator(metrics_aggregator=metrics_aggregator)

        # Generate the specific report type
        report = {}
        if report_type == "security":
            report = reporter.generate_security_report()
        elif report_type == "compliance":
            report = reporter.generate_compliance_report()
        elif report_type == "operational":
            report = reporter.generate_operational_report()
        elif report_type == "comprehensive":
            report = reporter.generate_comprehensive_report()
        else:
            raise ValueError(f"Unsupported report_type: {report_type}")

        # Export the report if an output path is provided
        if output_path:
            exported_path = reporter.export_report(
                report=report,
                format=output_format,
                output_file=output_path
            )

            # Return information about the saved report
            return {
                "status": "success",
                "report_type": report_type,
                "output_path": exported_path,
                "output_format": output_format,
                "report_id": report.get("report_id"),
                "timestamp": report.get("timestamp")
            }
        else:
            # Return the report content directly
            return {
                "status": "success",
                "report_type": report_type,
                "output_format": output_format,
                "report": report
            }
    except Exception as e:
        logger.error(f"Error generating audit report: {e}")
        return {
            "status": "error",
            "message": str(e),
            "report_type": report_type
        }
