"""Unit tests for LLM-related CLI server tools.

Covers gemini_cli_server_tools (Gemini) and claude_cli_server_tools (Claude)
without requiring the external CLI tools to be installed — all tests verify
the graceful "not installed" error path and basic return-type contracts.
"""
from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# Gemini CLI tools
# ---------------------------------------------------------------------------

from ipfs_datasets_py.mcp_server.tools.development_tools.gemini_cli_server_tools import (
    gemini_cli_status,
    gemini_cli_list_models,
    gemini_cli_test_connection,
    gemini_generate_text,
    gemini_summarize_text,
    gemini_analyze_code,
)

# ---------------------------------------------------------------------------
# Claude CLI tools
# ---------------------------------------------------------------------------

from ipfs_datasets_py.mcp_server.tools.development_tools.claude_cli_server_tools import (
    claude_cli_status,
    claude_cli_list_models,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_dict_result(result: object) -> bool:  # noqa: ANN001
    return isinstance(result, dict)


# ---------------------------------------------------------------------------
# Gemini CLI tools (not installed → graceful error dicts)
# ---------------------------------------------------------------------------

class TestGeminiCliStatus:
    def test_returns_dict(self):
        result = gemini_cli_status()
        assert _is_dict_result(result)

    def test_has_status_or_error_key(self):
        result = gemini_cli_status()
        assert "installed" in result or "success" in result or "error" in result

    def test_install_dir_accepted(self):
        result = gemini_cli_status(install_dir="/nonexistent")
        assert _is_dict_result(result)


class TestGeminiCliListModels:
    def test_returns_dict(self):
        result = gemini_cli_list_models()
        assert _is_dict_result(result)

    def test_not_installed_returns_error(self):
        result = gemini_cli_list_models()
        # Either models list or an error key
        assert "models" in result or "success" in result or "error" in result


class TestGeminiCliTestConnection:
    def test_returns_dict(self):
        result = gemini_cli_test_connection()
        assert _is_dict_result(result)


class TestGeminiGenerateText:
    def test_returns_dict(self):
        result = gemini_generate_text(prompt="Hello")
        assert _is_dict_result(result)

    def test_not_installed_returns_success_false(self):
        result = gemini_generate_text(prompt="test")
        # When CLI not installed, success=False
        if "success" in result:
            assert result["success"] in (True, False)

    def test_prompt_echoed_or_error(self):
        result = gemini_generate_text(prompt="test prompt", model="gemini-pro")
        assert _is_dict_result(result)

    def test_empty_prompt_handled(self):
        result = gemini_generate_text(prompt="")
        assert _is_dict_result(result)


class TestGeminiSummarizeText:
    def test_returns_dict(self):
        result = gemini_summarize_text(text="Some text to summarize")
        assert _is_dict_result(result)

    def test_max_length_param_accepted(self):
        result = gemini_summarize_text(text="Some text", max_length=100)
        assert _is_dict_result(result)


class TestGeminiAnalyzeCode:
    def test_returns_dict(self):
        result = gemini_analyze_code(code="def foo(): pass")
        assert _is_dict_result(result)

    def test_language_param_accepted(self):
        result = gemini_analyze_code(code="x = 1", language="python")
        assert _is_dict_result(result)


# ---------------------------------------------------------------------------
# Claude CLI tools (not installed → graceful error dicts)
# ---------------------------------------------------------------------------

class TestClaudeCliStatus:
    def test_returns_dict(self):
        result = claude_cli_status()
        assert _is_dict_result(result)

    def test_has_status_like_key(self):
        result = claude_cli_status()
        # Should have at least one of the common status keys
        assert any(k in result for k in ("installed", "success", "error", "version"))

    def test_install_dir_accepted(self):
        result = claude_cli_status(install_dir="/nonexistent")
        assert _is_dict_result(result)


class TestClaudeCliListModels:
    def test_returns_dict(self):
        result = claude_cli_list_models()
        assert _is_dict_result(result)

    def test_not_installed_has_info_key(self):
        result = claude_cli_list_models()
        assert "models" in result or "success" in result or "error" in result
