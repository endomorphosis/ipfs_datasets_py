"""
Legal Report Generation MCP Tool — thin wrapper.

Business logic: ipfs_datasets_py.processors.legal_scrapers.legal_report_generator
Core implementation: LegalSearchReportGenerator
"""

import logging
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)

try:
    from ipfs_datasets_py.processors.legal_scrapers import LegalSearchReportGenerator
    _GENERATOR_AVAILABLE = True
except ImportError:
    _GENERATOR_AVAILABLE = False


def _unavailable(tool_name: str) -> Dict[str, Any]:
    return {
        "status": "error",
        "message": "LegalSearchReportGenerator not available. Install with: pip install ipfs-datasets-py[legal]",
        "tool": tool_name,
    }


async def generate_legal_report(
    search_results: List[Dict[str, Any]],
    template: str = "research",
    title: Optional[str] = None,
    include_summary: bool = True,
    include_citations: bool = True,
    include_statistics: bool = True,
    max_results: Optional[int] = None,
    use_llm_summary: bool = False,
) -> Dict[str, Any]:
    """Generate a formatted legal research report from search results.

    Thin wrapper around LegalSearchReportGenerator.generate_report().
    All business logic is in ipfs_datasets_py.processors.legal_scrapers.legal_report_generator
    """
    if not _GENERATOR_AVAILABLE:
        return _unavailable("generate_legal_report")
    try:
        if not search_results or not isinstance(search_results, list):
            return {"status": "error", "message": "search_results must be a non-empty list"}
        if template not in ("compliance", "research", "monitoring"):
            return {"status": "error", "message": "template must be 'compliance', 'research', or 'monitoring'"}
        if max_results is not None and (max_results < 1 or max_results > 1000):
            return {"status": "error", "message": "max_results must be between 1 and 1000"}

        if max_results and len(search_results) > max_results:
            search_results = search_results[:max_results]

        generator = LegalSearchReportGenerator()
        report = generator.generate_report(
            results=search_results,
            template=template,
            title=title,
            include_summary=include_summary,
            include_citations=include_citations,
            include_statistics=include_statistics,
            use_llm_summary=use_llm_summary,
        )

        sections = [
            {
                "title": section.title,
                "content": section.content,
                "metadata": section.metadata,
                "has_subsections": len(section.subsections) > 0,
                "subsection_count": len(section.subsections),
            }
            for section in report.sections
        ]

        return {
            "status": "success",
            "report": {
                "title": report.title,
                "generated_at": report.generated_at.isoformat(),
                "metadata": report.metadata,
            },
            "title": report.title,
            "generated_at": report.generated_at.isoformat(),
            "total_results": len(search_results),
            "template_used": template,
            "sections": sections,
            "section_count": len(sections),
            "mcp_tool": "generate_legal_report",
        }
    except Exception as exc:
        logger.error(f"Error in generate_legal_report: {exc}")
        return {"status": "error", "message": str(exc), "total_results": len(search_results) if search_results else 0}


async def export_legal_report(
    report_data: Dict[str, Any],
    format: str = "markdown",
    output_path: Optional[str] = None,
    include_toc: bool = True,
) -> Dict[str, Any]:
    """Export a legal report to various formats.

    Thin wrapper around LegalSearchReportGenerator.export_report().
    """
    if not _GENERATOR_AVAILABLE:
        return _unavailable("export_legal_report")
    try:
        if not report_data or not isinstance(report_data, dict):
            return {"status": "error", "message": "report_data must be a non-empty dictionary"}
        if format not in ("markdown", "html", "pdf", "docx", "json"):
            return {"status": "error", "message": "format must be 'markdown', 'html', 'pdf', 'docx', or 'json'"}

        generator = LegalSearchReportGenerator()
        export_result = generator.export_report(
            report_data=report_data,
            format=format,
            output_path=output_path,
            include_toc=include_toc,
        )

        result: Dict[str, Any] = {"status": "success", "format": format, "include_toc": include_toc}
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
    except Exception as exc:
        logger.error(f"Error in export_legal_report: {exc}")
        return {"status": "error", "message": str(exc)}


async def generate_compliance_checklist(
    search_results: List[Dict[str, Any]],
    jurisdiction: str = "federal",
    effective_date: Optional[str] = None,
    include_deadlines: bool = True,
) -> Dict[str, Any]:
    """Generate a compliance checklist from legal search results.

    Thin wrapper around LegalSearchReportGenerator.generate_compliance_checklist().
    """
    if not _GENERATOR_AVAILABLE:
        return _unavailable("generate_compliance_checklist")
    try:
        if not search_results or not isinstance(search_results, list):
            return {"status": "error", "message": "search_results must be a non-empty list"}
        valid_j = ("federal", "state", "local", "international")
        if jurisdiction not in valid_j:
            return {"status": "error", "message": f"jurisdiction must be one of: {list(valid_j)}"}

        generator = LegalSearchReportGenerator()
        checklist_result = generator.generate_compliance_checklist(
            results=search_results,
            jurisdiction=jurisdiction,
            effective_date=effective_date,
            include_deadlines=include_deadlines,
        )

        priority_dist: Dict[str, int] = {}
        for item in checklist_result["items"]:
            p = item.get("priority", "medium")
            priority_dist[p] = priority_dist.get(p, 0) + 1

        return {
            "status": "success",
            "checklist": checklist_result["items"],
            "total_items": len(checklist_result["items"]),
            "jurisdiction": jurisdiction,
            "priority_distribution": priority_dist,
            "deadlines": checklist_result.get("deadlines", []) if include_deadlines else [],
            "effective_date": effective_date,
            "mcp_tool": "generate_compliance_checklist",
        }
    except Exception as exc:
        logger.error(f"Error in generate_compliance_checklist: {exc}")
        return {"status": "error", "message": str(exc)}


async def schedule_report_generation(
    report_config: Dict[str, Any],
    schedule: str,
    output_directory: str,
    notification_email: Optional[str] = None,
) -> Dict[str, Any]:
    """Schedule automated report generation on a recurring basis.

    Thin wrapper around LegalSearchReportGenerator.schedule_report().
    """
    if not _GENERATOR_AVAILABLE:
        return _unavailable("schedule_report_generation")
    try:
        if not report_config or not isinstance(report_config, dict):
            return {"status": "error", "message": "report_config must be a non-empty dictionary"}
        if not schedule:
            return {"status": "error", "message": "schedule is required (daily, weekly, monthly, or cron expression)"}
        if not output_directory:
            return {"status": "error", "message": "output_directory is required"}

        generator = LegalSearchReportGenerator()
        schedule_result = generator.schedule_report(
            report_config=report_config,
            schedule=schedule,
            output_directory=output_directory,
            notification_email=notification_email,
        )

        return {
            "status": "success",
            "schedule_id": schedule_result["schedule_id"],
            "schedule": schedule,
            "next_run": schedule_result["next_run"],
            "output_directory": output_directory,
            "notification_email": notification_email,
            "message": f"Report scheduled successfully (ID: {schedule_result['schedule_id']})",
            "mcp_tool": "schedule_report_generation",
        }
    except Exception as exc:
        logger.error(f"Error in schedule_report_generation: {exc}")
        return {"status": "error", "message": str(exc)}
