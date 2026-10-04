"""HACC-specific legal-data processors and workflow bridges."""

from __future__ import annotations

from importlib import import_module
from typing import Any


__all__ = [
    "COMPLAINT_GENERATOR_ROOT",
    "REPO_ROOT",
    "HACCResearchEngine",
    "HACCCourtPDFScanResult",
    "analyze_pdf_for_court_case",
    "call_workspace_mcp",
    "call_workspace_tool",
    "complaint_manager_interfaces",
    "load_scan_manifest",
    "package_hacc_case_from_scan_manifest",
    "scan_hacc_pdfs_for_dockets",
    "summarize_scan_manifest",
    "create_workspace_service",
    "ensure_complaint_generator_on_path",
    "grounded_pipeline_main",
    "handle_workspace_mcp_message",
    "list_workspace_mcp_tools",
    "list_workspace_tools_via_cli",
    "list_workspace_tools_via_mcp",
    "list_workspace_tools_via_package",
    "run_hacc_grounded_pipeline",
    "run_workspace_cli",
]


def __getattr__(name: str) -> Any:
    if name in {
        "COMPLAINT_GENERATOR_ROOT",
        "REPO_ROOT",
        "call_workspace_mcp",
        "call_workspace_tool",
        "complaint_manager_interfaces",
        "create_workspace_service",
        "ensure_complaint_generator_on_path",
        "handle_workspace_mcp_message",
        "list_workspace_mcp_tools",
        "list_workspace_tools_via_cli",
        "list_workspace_tools_via_mcp",
        "list_workspace_tools_via_package",
        "run_workspace_cli",
    }:
        module = import_module(".complaint_manager", __name__)
        return getattr(module, name)
    if name in {"grounded_pipeline_main", "run_hacc_grounded_pipeline"}:
        module = import_module(".grounded_pipeline", __name__)
        if name == "grounded_pipeline_main":
            return getattr(module, "main")
        return getattr(module, name)
    if name == "HACCResearchEngine":
        module = import_module(".research_engine", __name__)
        return getattr(module, name)
    if name in {
        "HACCCourtPDFScanResult",
        "analyze_pdf_for_court_case",
        "load_scan_manifest",
        "package_hacc_case_from_scan_manifest",
        "scan_hacc_pdfs_for_dockets",
        "summarize_scan_manifest",
    }:
        module = import_module(".court_pdf_docket_scan", __name__)
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
