#!/usr/bin/env python3
"""Shared accessors for the current complaint manager interfaces."""

from __future__ import annotations

import os
import json
import sys
import subprocess
from pathlib import Path
from typing import Any, Dict


REPO_ROOT = Path(__file__).resolve().parents[5]
COMPLAINT_GENERATOR_ROOT = Path(__file__).resolve().parents[4]
COMPLAINT_GENERATOR_PACKAGE = "complaint_generator"
COMPLAINT_CLI_IMPLEMENTATION_MODULE = f"{COMPLAINT_GENERATOR_PACKAGE}.cli"
COMPLAINT_MCP_IMPLEMENTATION_MODULE = f"{COMPLAINT_GENERATOR_PACKAGE}.mcp_server"
COMPLAINT_CLI_COMPATIBILITY_MODULE = "applications.complaint_cli"
COMPLAINT_MCP_COMPATIBILITY_MODULE = "applications.complaint_mcp_server"
COMPLAINT_WORKSPACE_SCRIPT = "complaint-workspace"
COMPLAINT_WORKSPACE_ALIASES = ["complaint-generator-workspace"]
COMPLAINT_MCP_SERVER_SCRIPT = "complaint-mcp-server"
COMPLAINT_MCP_SERVER_ALIASES = ["complaint-generator-mcp"]
COMPLAINT_MCP_SERVER_INFO_NAME = "complaint-workspace-mcp"


def ensure_complaint_generator_on_path() -> None:
    root = str(COMPLAINT_GENERATOR_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)


def complaint_manager_interfaces() -> Dict[str, Any]:
    return {
        "package": {
            "module": COMPLAINT_GENERATOR_PACKAGE,
            "service_class": "ComplaintWorkspaceService",
            "lazy_exports": [
                "ComplaintWorkspaceService",
                "complaint_cli_main",
                "complaint_mcp_server_main",
                "handle_jsonrpc_message",
                "tool_list_payload",
            ],
            "mcp_handler_module": f"{COMPLAINT_GENERATOR_PACKAGE}.mcp",
            "mcp_handler": "handle_jsonrpc_message",
            "mcp_tool_list": "tool_list_payload",
            "workspace_module": f"{COMPLAINT_GENERATOR_PACKAGE}.workspace",
            "workspace_helpers": [
                "start_session",
                "submit_intake_answers",
                "save_evidence",
                "generate_complaint",
                "list_mcp_tools",
            ],
        },
        "cli": {
            "module": COMPLAINT_CLI_IMPLEMENTATION_MODULE,
            "module_entrypoint": f"{COMPLAINT_CLI_IMPLEMENTATION_MODULE}:main",
            "module_command": "python -m complaint_generator.cli --help",
            "compatibility_module": COMPLAINT_CLI_COMPATIBILITY_MODULE,
            "script_name": COMPLAINT_WORKSPACE_SCRIPT,
            "script_aliases": list(COMPLAINT_WORKSPACE_ALIASES),
            "entrypoint": "main",
            "example_commands": [
                "complaint-workspace tools",
                "complaint-workspace mediator-prompt --user-id demo-user",
                "complaint-workspace export-packet --user-id demo-user",
            ],
        },
        "mcp": {
            "module": COMPLAINT_MCP_IMPLEMENTATION_MODULE,
            "module_entrypoint": f"{COMPLAINT_MCP_IMPLEMENTATION_MODULE}:main",
            "module_command": "python -m complaint_generator.mcp_server",
            "compatibility_module": COMPLAINT_MCP_COMPATIBILITY_MODULE,
            "protocol_module": f"{COMPLAINT_GENERATOR_PACKAGE}.mcp",
            "entrypoint": "main",
            "transport": "stdio-jsonrpc",
            "script_name": COMPLAINT_MCP_SERVER_SCRIPT,
            "launcher_alias": COMPLAINT_MCP_SERVER_ALIASES[0],
            "launcher_aliases": list(COMPLAINT_MCP_SERVER_ALIASES),
            "server_info_name": COMPLAINT_MCP_SERVER_INFO_NAME,
            "request_handler": "handle_jsonrpc_message",
            "tool_list_function": "tool_list_payload",
        },
    }


def create_workspace_service() -> Any:
    ensure_complaint_generator_on_path()
    from complaint_generator import ComplaintWorkspaceService

    return ComplaintWorkspaceService()


def list_workspace_mcp_tools() -> Dict[str, Any]:
    ensure_complaint_generator_on_path()
    from complaint_generator.mcp import tool_list_payload

    return tool_list_payload(create_workspace_service())


def list_workspace_tools_via_package() -> Dict[str, Any]:
    service = create_workspace_service()
    return service.list_mcp_tools()


def call_workspace_tool(tool_name: str, arguments: Dict[str, Any] | None = None) -> Dict[str, Any]:
    service = create_workspace_service()
    return service.call_mcp_tool(tool_name, arguments or {})


def call_workspace_mcp(tool_name: str, arguments: Dict[str, Any] | None = None, request_id: int = 1) -> Dict[str, Any]:
    ensure_complaint_generator_on_path()
    from complaint_generator.mcp import handle_jsonrpc_message

    service = create_workspace_service()
    request = {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "tools/call",
        "params": {
            "name": tool_name,
            "arguments": arguments or {},
        },
    }
    response = handle_jsonrpc_message(service, request)
    return dict(response or {})


def list_workspace_tools_via_mcp(request_id: int = 1) -> Dict[str, Any]:
    ensure_complaint_generator_on_path()
    from complaint_generator.mcp import handle_jsonrpc_message

    service = create_workspace_service()
    request = {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "tools/list",
        "params": {},
    }
    response = handle_jsonrpc_message(service, request)
    if not isinstance(response, dict):
        return {}
    return dict(response.get("result") or {})


def run_workspace_cli(args: list[str]) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    existing_pythonpath = env.get("PYTHONPATH", "")
    root = str(COMPLAINT_GENERATOR_ROOT)
    env["PYTHONPATH"] = root if not existing_pythonpath else f"{root}:{existing_pythonpath}"
    command = [sys.executable, "-m", COMPLAINT_CLI_IMPLEMENTATION_MODULE, *args]
    return subprocess.run(command, check=False, capture_output=True, text=True, cwd=str(COMPLAINT_GENERATOR_ROOT), env=env)


def _extract_json_object_from_text(raw: str) -> Dict[str, Any]:
    text = str(raw or "").strip()
    if not text:
        return {}
    decoder = json.JSONDecoder()
    last_payload: Dict[str, Any] = {}
    last_tools_payload: Dict[str, Any] = {}
    for index, char in enumerate(text):
        if char not in "[{":
            continue
        try:
            payload, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            last_payload = payload
            if "tools" in payload:
                last_tools_payload = payload
    return last_tools_payload or last_payload


def list_workspace_tools_via_cli() -> Dict[str, Any]:
    result = run_workspace_cli(["tools"])
    return _extract_json_object_from_text(result.stdout)


def handle_workspace_mcp_message(request: Dict[str, Any]) -> Dict[str, Any] | None:
    ensure_complaint_generator_on_path()
    from complaint_generator.mcp import handle_jsonrpc_message

    return handle_jsonrpc_message(create_workspace_service(), request)
