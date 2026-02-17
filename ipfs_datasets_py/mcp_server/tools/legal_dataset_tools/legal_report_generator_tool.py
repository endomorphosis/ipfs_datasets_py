"""
Legal Report Generation MCP Tool.

This tool exposes the LegalSearchReportGenerator which provides automated
report generation from legal search results with multiple formats, templates,
and LLM-based summaries.

Core implementation: ipfs_datasets_py.processors.legal_scrapers.legal_report_generator
"""

import logging
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)


async def generate_legal_report(
    search_results: List[Dict[str, Any]],
    template: str = "research",
    title: Optional[str] = None,
    include_summary: bool = True,
    include_citations: bool = True,
    include_statistics: bool = True,
    max_results: Optional[int] = None,
    use_llm_summary: bool = False
) -> Dict[str, Any]:
    """
    Generate a formatted legal research report from search results.
    
    This is a thin wrapper around LegalSearchReportGenerator.generate_report().
    All business logic is in ipfs_datasets_py.processors.legal_scrapers.legal_report_generator
    
    Features:
    - Multiple report templates (compliance, research, monitoring)
    - Automatic summary generation
    - Citation and reference sections
    - Statistics and metrics
    - LLM-based summaries (optional)
    
    Templates:
    - compliance: Focus on regulatory compliance requirements
    - research: Comprehensive legal research report
    - monitoring: Ongoing monitoring and updates report
    
    Args:
        search_results: List of search result dictionaries (from legal search tools)
        template: Report template - "compliance", "research", or "monitoring" (default: "research")
        title: Optional report title (auto-generated if not provided)
        include_summary: Include executive summary section (default: True)
        include_citations: Include citation section (default: True)
        include_statistics: Include statistics section (default: True)
        max_results: Limit number of results in report (default: all)
        use_llm_summary: Use LLM for summary generation (default: False)
    
    Returns:
        Dictionary containing:
        - status: "success" or "error"
        - report: Generated report object with sections
        - title: Report title
        - generated_at: Timestamp of generation
        - total_results: Number of results included
        - template_used: Template that was used
        - sections: List of report sections with content
    
    Example:
        >>> report = await generate_legal_report(
        ...     search_results=results,
        ...     template="compliance",
        ...     title="EPA Water Regulations Compliance Report",
        ...     include_summary=True
        ... )
        >>> print(f"Generated report with {len(report['sections'])} sections")
    """
    try:
        from ipfs_datasets_py.processors.legal_scrapers import LegalSearchReportGenerator
        
        # Validate input
        if not search_results or not isinstance(search_results, list):
            return {
                "status": "error",
                "message": "search_results must be a non-empty list"
            }
        
        if template not in ["compliance", "research", "monitoring"]:
            return {
                "status": "error",
                "message": "template must be 'compliance', 'research', or 'monitoring'"
            }
        
        if max_results and (max_results < 1 or max_results > 1000):
            return {
                "status": "error",
                "message": "max_results must be between 1 and 1000"
            }
        
        # Limit results if requested
        if max_results and len(search_results) > max_results:
            search_results = search_results[:max_results]
        
        # Initialize report generator
        generator = LegalSearchReportGenerator()
        
        # Generate report
        report = generator.generate_report(
            results=search_results,
            template=template,
            title=title,
            include_summary=include_summary,
            include_citations=include_citations,
            include_statistics=include_statistics,
            use_llm_summary=use_llm_summary
        )
        
        # Extract sections
        sections = [
            {
                "title": section.title,
                "content": section.content,
                "metadata": section.metadata,
                "has_subsections": len(section.subsections) > 0,
                "subsection_count": len(section.subsections)
            }
            for section in report.sections
        ]
        
        return {
            "status": "success",
            "report": {
                "title": report.title,
                "generated_at": report.generated_at.isoformat(),
                "metadata": report.metadata
            },
            "title": report.title,
            "generated_at": report.generated_at.isoformat(),
            "total_results": len(search_results),
            "template_used": template,
            "sections": sections,
            "section_count": len(sections),
            "mcp_tool": "generate_legal_report"
        }
        
    except ImportError as e:
        logger.error(f"Import error in generate_legal_report: {e}")
        return {
            "status": "error",
            "message": f"Required module not found: {str(e)}. Install with: pip install ipfs-datasets-py[legal]"
        }
    except Exception as e:
        logger.error(f"Error in generate_legal_report MCP tool: {e}")
        return {
            "status": "error",
            "message": str(e),
            "total_results": len(search_results) if search_results else 0
        }


async def export_legal_report(
    report_data: Dict[str, Any],
    format: str = "markdown",
    output_path: Optional[str] = None,
    include_toc: bool = True
) -> Dict[str, Any]:
    """
    Export a legal report to various formats.
    
    This is a thin wrapper around LegalSearchReportGenerator.export_report().
    All business logic is in ipfs_datasets_py.processors.legal_scrapers.legal_report_generator
    
    Supported formats:
    - markdown: Markdown format (.md)
    - html: HTML format (.html)
    - pdf: PDF format (.pdf) - requires additional dependencies
    - docx: Microsoft Word format (.docx) - requires additional dependencies
    - json: JSON format (.json)
    
    Args:
        report_data: Report data from generate_legal_report()
        format: Export format - "markdown", "html", "pdf", "docx", or "json" (default: "markdown")
        output_path: Optional file path to save export (if not provided, returns content)
        include_toc: Include table of contents (default: True)
    
    Returns:
        Dictionary containing:
        - status: "success" or "error"
        - format: Export format used
        - output_path: Path where file was saved (if output_path provided)
        - content: Exported content (if output_path not provided)
        - size: Size of exported content in bytes
    
    Example:
        >>> exported = await export_legal_report(
        ...     report_data=report,
        ...     format="markdown",
        ...     output_path="/tmp/report.md"
        ... )
        >>> print(f"Report exported to {exported['output_path']}")
    """
    try:
        from ipfs_datasets_py.processors.legal_scrapers import LegalSearchReportGenerator
        
        if not report_data or not isinstance(report_data, dict):
            return {
                "status": "error",
                "message": "report_data must be a non-empty dictionary"
            }
        
        if format not in ["markdown", "html", "pdf", "docx", "json"]:
            return {
                "status": "error",
                "message": "format must be 'markdown', 'html', 'pdf', 'docx', or 'json'"
            }
        
        # Initialize generator
        generator = LegalSearchReportGenerator()
        
        # Export report
        export_result = generator.export_report(
            report_data=report_data,
            format=format,
            output_path=output_path,
            include_toc=include_toc
        )
        
        result = {
            "status": "success",
            "format": format,
            "include_toc": include_toc
        }
        
        if output_path:
            result["output_path"] = output_path
            result["message"] = f"Report exported to {output_path}"
            if "size" in export_result:
                result["size"] = export_result["size"]
        else:
            result["content"] = export_result["content"]
            result["size"] = len(export_result["content"])
            result["message"] = "Report content generated successfully"
        
        return result
        
    except ImportError as e:
        logger.error(f"Import error in export_legal_report: {e}")
        return {
            "status": "error",
            "message": f"Required module not found: {str(e)}. For PDF/DOCX export, install additional dependencies."
        }
    except Exception as e:
        logger.error(f"Error in export_legal_report MCP tool: {e}")
        return {
            "status": "error",
            "message": str(e)
        }


async def generate_compliance_checklist(
    search_results: List[Dict[str, Any]],
    jurisdiction: str = "federal",
    effective_date: Optional[str] = None,
    include_deadlines: bool = True
) -> Dict[str, Any]:
    """
    Generate a compliance checklist from legal search results.
    
    Features:
    - Extract compliance requirements
    - Identify key deadlines
    - Organize by jurisdiction
    - Priority ranking
    
    Args:
        search_results: List of search result dictionaries
        jurisdiction: Jurisdiction scope - "federal", "state", "local", or "international"
        effective_date: Optional effective date filter (ISO format: "YYYY-MM-DD")
        include_deadlines: Include compliance deadlines (default: True)
    
    Returns:
        Dictionary containing:
        - status: "success" or "error"
        - checklist: List of compliance items
        - total_items: Number of compliance items
        - jurisdiction: Jurisdiction scope
        - priority_distribution: Distribution of priorities (high, medium, low)
        - deadlines: List of upcoming deadlines (if include_deadlines=True)
    
    Example:
        >>> checklist = await generate_compliance_checklist(
        ...     search_results=results,
        ...     jurisdiction="federal",
        ...     include_deadlines=True
        ... )
        >>> print(f"Generated checklist with {checklist['total_items']} items")
    """
    try:
        from ipfs_datasets_py.processors.legal_scrapers import LegalSearchReportGenerator
        
        if not search_results or not isinstance(search_results, list):
            return {
                "status": "error",
                "message": "search_results must be a non-empty list"
            }
        
        valid_jurisdictions = ["federal", "state", "local", "international"]
        if jurisdiction not in valid_jurisdictions:
            return {
                "status": "error",
                "message": f"jurisdiction must be one of: {valid_jurisdictions}"
            }
        
        # Initialize generator
        generator = LegalSearchReportGenerator()
        
        # Generate compliance checklist
        checklist_result = generator.generate_compliance_checklist(
            results=search_results,
            jurisdiction=jurisdiction,
            effective_date=effective_date,
            include_deadlines=include_deadlines
        )
        
        # Calculate priority distribution
        priority_dist = {}
        for item in checklist_result["items"]:
            priority = item.get("priority", "medium")
            priority_dist[priority] = priority_dist.get(priority, 0) + 1
        
        return {
            "status": "success",
            "checklist": checklist_result["items"],
            "total_items": len(checklist_result["items"]),
            "jurisdiction": jurisdiction,
            "priority_distribution": priority_dist,
            "deadlines": checklist_result.get("deadlines", []) if include_deadlines else [],
            "effective_date": effective_date,
            "mcp_tool": "generate_compliance_checklist"
        }
        
    except Exception as e:
        logger.error(f"Error in generate_compliance_checklist MCP tool: {e}")
        return {
            "status": "error",
            "message": str(e)
        }


async def schedule_report_generation(
    report_config: Dict[str, Any],
    schedule: str,
    output_directory: str,
    notification_email: Optional[str] = None
) -> Dict[str, Any]:
    """
    Schedule automated report generation on a recurring basis.
    
    Features:
    - Schedule recurring report generation
    - Email notifications on completion
    - Automatic archiving
    - Change detection alerts
    
    Args:
        report_config: Configuration for report generation (template, filters, etc.)
        schedule: Schedule specification - "daily", "weekly", "monthly", or cron expression
        output_directory: Directory for saving generated reports
        notification_email: Optional email for notifications
    
    Returns:
        Dictionary containing:
        - status: "success" or "error"
        - schedule_id: Unique identifier for scheduled job
        - schedule: Schedule specification
        - next_run: Next scheduled run time
        - output_directory: Output directory path
    
    Example:
        >>> scheduled = await schedule_report_generation(
        ...     report_config={"template": "monitoring", "query": "EPA regulations"},
        ...     schedule="weekly",
        ...     output_directory="/reports/weekly",
        ...     notification_email="admin@example.com"
        ... )
        >>> print(f"Scheduled job: {scheduled['schedule_id']}")
    """
    try:
        from ipfs_datasets_py.processors.legal_scrapers import LegalSearchReportGenerator
        
        if not report_config or not isinstance(report_config, dict):
            return {
                "status": "error",
                "message": "report_config must be a non-empty dictionary"
            }
        
        if not schedule:
            return {
                "status": "error",
                "message": "schedule is required (daily, weekly, monthly, or cron expression)"
            }
        
        if not output_directory:
            return {
                "status": "error",
                "message": "output_directory is required"
            }
        
        # Initialize generator
        generator = LegalSearchReportGenerator()
        
        # Schedule report
        schedule_result = generator.schedule_report(
            report_config=report_config,
            schedule=schedule,
            output_directory=output_directory,
            notification_email=notification_email
        )
        
        return {
            "status": "success",
            "schedule_id": schedule_result["schedule_id"],
            "schedule": schedule,
            "next_run": schedule_result["next_run"],
            "output_directory": output_directory,
            "notification_email": notification_email,
            "message": f"Report scheduled successfully (ID: {schedule_result['schedule_id']})",
            "mcp_tool": "schedule_report_generation"
        }
        
    except Exception as e:
        logger.error(f"Error in schedule_report_generation MCP tool: {e}")
        return {
            "status": "error",
            "message": str(e)
        }
