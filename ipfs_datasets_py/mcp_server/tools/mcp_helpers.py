"""Helpers for MCP-style tool I/O.

Some legacy/unit tests call MCP server tools as `await tool(json_string)` and
expect an MCP response envelope:

    {"content": [{"type": "text", "text": "{...json...}"}]}

These helpers provide small utilities for parsing JSON requests and wrapping
structured results into that envelope.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional, Tuple


def mcp_text_response(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(payload),
            }
        ]
    }


def mcp_error_response(message: str, *, error_type: str = "error", **extra: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"status": "error", "error": message, "error_type": error_type}
    payload.update(extra)
    return mcp_text_response(payload)


def parse_json_object(request_json: Any) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Parse a JSON string expected to be an object.

    Returns (data, error_response). Exactly one will be non-None.
    """

    if not isinstance(request_json, str):
        return None, mcp_error_response("Input must be a JSON string")

    if not request_json.strip():
        return None, mcp_error_response("Input JSON is empty", error_type="validation")

    try:
        data = json.loads(request_json)
    except json.JSONDecodeError as e:
        return None, mcp_error_response(f"Invalid JSON: {e.msg}", error_type="validation")

    if not isinstance(data, dict):
        return None, mcp_error_response("Input JSON must be an object", error_type="validation")

    return data, None
