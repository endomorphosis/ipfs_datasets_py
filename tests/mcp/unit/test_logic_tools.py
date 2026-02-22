"""Tests for logic_tools tool category."""
import asyncio
import pytest
from unittest.mock import patch, MagicMock


def _run(coro):
    """Run a coroutine using a fresh event loop (compatible with Python 3.12)."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# logic_tools — CEC analysis
# ---------------------------------------------------------------------------

class TestCecAnalyzeFormula:
    """Tests for cec_analyze_formula()."""

    def test_returns_dict(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools.cec_analysis_tool import cec_analyze_formula
        result = _run(
            cec_analyze_formula("P -> Q")
        )
        assert isinstance(result, dict)

    def test_has_expected_keys(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools.cec_analysis_tool import cec_analyze_formula
        result = _run(
            cec_analyze_formula("P -> Q")
        )
        # Must have at least one key
        assert len(result) > 0

    def test_complex_formula(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools.cec_analysis_tool import cec_analyze_formula
        result = _run(
            cec_analyze_formula("(A ∧ B) → (C ∨ D)")
        )
        assert isinstance(result, dict)


class TestAnalyzeFormulaSync:
    """Tests for analyze_formula() (sync variant)."""

    def test_returns_dict(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools.cec_analysis_tool import analyze_formula
        result = analyze_formula("P -> Q")
        assert isinstance(result, dict)

    def test_empty_formula(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools.cec_analysis_tool import analyze_formula
        result = analyze_formula("")
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# logic_tools — CEC parse
# ---------------------------------------------------------------------------

class TestCecParse:
    """Tests for cec_parse() async and parse_dcec() sync."""

    def test_cec_parse_returns_dict(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools.cec_parse_tool import cec_parse
        result = _run(
            cec_parse(text="It is obligatory that agents pay taxes")
        )
        assert isinstance(result, dict)

    def test_parse_dcec_returns_dict(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools.cec_parse_tool import parse_dcec
        result = parse_dcec("It is obligatory that agents pay taxes")
        assert isinstance(result, dict)

    def test_validate_formula_returns_dict(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools.cec_parse_tool import validate_formula
        result = validate_formula("P -> Q")
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# logic_tools — CEC inference rules
# ---------------------------------------------------------------------------

class TestCecListRules:
    """Tests for cec_list_rules()."""

    def test_returns_dict(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools.cec_inference_tool import cec_list_rules
        result = _run(cec_list_rules())
        assert isinstance(result, dict)

    def test_has_rules_or_categories(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools.cec_inference_tool import cec_list_rules
        result = _run(cec_list_rules())
        # Should have at least one key indicating rule groups
        assert len(result) > 0


class TestCecRuleInfo:
    """Tests for cec_rule_info()."""

    def test_returns_dict(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools.cec_inference_tool import cec_rule_info
        result = _run(cec_rule_info("modus_ponens"))
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# logic_tools — CEC prove
# ---------------------------------------------------------------------------

class TestCecProve:
    """Tests for cec_prove() async."""

    def test_returns_dict(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools.cec_prove_tool import cec_prove
        result = _run(cec_prove(goal="Q"))
        assert isinstance(result, dict)

    def test_prove_dcec_sync_returns_dict(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools.cec_prove_tool import prove_dcec
        result = prove_dcec(formula="P -> Q", goal="Q")
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# logic_tools — logic capabilities
# ---------------------------------------------------------------------------

class TestLogicCapabilities:
    """Tests for logic_capabilities_tool functions."""

    def test_logic_capabilities_importable(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools import logic_capabilities_tool  # noqa: F401

    def test_tdfol_tools_importable(self):
        """TDFOL tools exist in logic_tools package."""
        from ipfs_datasets_py.mcp_server.tools.logic_tools import tdfol_convert_tool  # noqa: F401
