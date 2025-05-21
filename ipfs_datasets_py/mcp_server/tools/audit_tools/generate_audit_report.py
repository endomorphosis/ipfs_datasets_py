# ipfs_datasets_py/mcp_server/tools/audit_tools/generate_audit_report.py
"""
MCP tool for generating audit reports.

This tool handles generating reports based on audit logs.
"""
import asyncio
import datetime
from typing import Dict, Any, Optional, Union, List

from ipfs_datasets_py.mcp_server.logger import logger


async def generate_audit_report(
    report_type: str = "summary",
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    filters: Optional[Dict[str, Any]] = None,
    output_format: str = "json",
    output_path: Optional[str] = None,
    include_details: bool = True
) -> Dict[str, Any]:
    """
    Generate an audit report based on audit logs.

    Args:
        report_type: Type of report ('summary', 'detailed', 'security', 'compliance')
        start_time: Optional start time for the report period (ISO format)
        end_time: Optional end time for the report period (ISO format)
        filters: Optional filters to apply to the audit logs
        output_format: Format of the report ('json', 'csv', 'html', 'pdf')
        output_path: Optional path to save the report
        include_details: Whether to include detailed information in the report

    Returns:
        Dict containing information about the generated report
    """
    try:
        logger.info(f"Generating {report_type} audit report")
        
        # Import the audit reporter
        from ipfs_datasets_py.audit.reporting import AuditReporter
        
        # Create a reporter instance
        reporter = AuditReporter()
        
        # Prepare query parameters
        query_params = {}
        
        if start_time:
            query_params["start_time"] = datetime.datetime.fromisoformat(start_time)
            
        if end_time:
            query_params["end_time"] = datetime.datetime.fromisoformat(end_time)
            
        if filters:
            query_params.update(filters)
        
        # Generate the report
        report = reporter.generate_report(
            report_type=report_type,
            query_params=query_params,
            include_details=include_details
        )
        
        # Save the report if an output path is provided
        if output_path:
            reporter.save_report(report, output_path, format=output_format)
            
            # Return information about the saved report
            return {
                "status": "success",
                "report_type": report_type,
                "output_path": output_path,
                "output_format": output_format,
                "event_count": report.get("event_count", 0),
                "start_time": start_time,
                "end_time": end_time
            }
        else:
            # Return the report content
            return {
                "status": "success",
                "report_type": report_type,
                "output_format": output_format,
                "event_count": report.get("event_count", 0),
                "start_time": start_time,
                "end_time": end_time,
                "report": report
            }
    except Exception as e:
        logger.error(f"Error generating audit report: {e}")
        return {
            "status": "error",
            "message": str(e),
            "report_type": report_type
        }
