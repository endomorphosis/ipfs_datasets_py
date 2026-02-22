"""
Phase B2 unit tests — functions/execute_python_snippet tool.

The tool intentionally does NOT execute arbitrary code for security reasons.
It returns a dict with status='success' and a message noting the code length.
"""
from __future__ import annotations

import asyncio
import pytest


def _run(coro):  # type: ignore[no-untyped-def]
    return asyncio.run(coro)


class TestExecutePythonSnippet:
    """Tests for functions.execute_python_snippet.execute_python_snippet()."""

    def setup_method(self) -> None:
        from ipfs_datasets_py.mcp_server.tools.functions.execute_python_snippet import (
            execute_python_snippet,
        )
        self.fn = execute_python_snippet

    def test_returns_dict(self) -> None:
        result = _run(self.fn("print('hello')"))
        assert isinstance(result, dict)

    def test_has_status_key(self) -> None:
        result = _run(self.fn("x = 1 + 1"))
        assert "status" in result

    def test_status_is_success(self) -> None:
        result = _run(self.fn("pass"))
        assert result["status"] == "success"

    def test_has_message_key(self) -> None:
        result = _run(self.fn("print(42)"))
        assert "message" in result

    def test_has_execution_time_key(self) -> None:
        result = _run(self.fn("1+1"))
        assert "execution_time_ms" in result

    def test_empty_code(self) -> None:
        result = _run(self.fn(""))
        assert isinstance(result, dict)

    def test_timeout_seconds_param(self) -> None:
        result = _run(self.fn("pass", timeout_seconds=5))
        assert isinstance(result, dict)

    def test_context_param(self) -> None:
        result = _run(self.fn("result = x + 1", context={"x": 10}))
        assert isinstance(result, dict)
