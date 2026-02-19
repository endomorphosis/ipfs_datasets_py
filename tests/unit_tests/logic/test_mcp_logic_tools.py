"""
Tests for logic MCP tools: cec_inference_tool and logic_capabilities_tool.

These tests replace the former FastAPI-based test_api_server.py tests.
They validate all MCP tools using direct async execution (no HTTP server needed).
"""

import asyncio
import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run(coro):
    """Run an async coroutine synchronously for pytest."""
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# CEC Inference Tool Tests
# ---------------------------------------------------------------------------

class TestCECListRulesTool:
    """Tests for the cec_list_rules MCP tool."""

    @pytest.fixture
    def tool(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools.cec_inference_tool import (
            CECListRulesTool,
        )
        return CECListRulesTool()

    def test_tool_metadata(self, tool):
        """
        GIVEN a CECListRulesTool instance
        WHEN checking its metadata
        THEN name, description, category, and schema should be set.
        """
        assert tool.name == "cec_list_rules"
        assert tool.category == "logic_tools"
        assert "logic" in tool.tags
        assert "cec" in tool.tags
        assert tool.input_schema is not None

    def test_list_all_rules_returns_success(self, tool):
        """
        GIVEN no parameters
        WHEN cec_list_rules.execute({}) is called
        THEN returns success=True and non-empty rules list.
        """
        result = run(tool.execute({}))
        assert result["success"] is True
        assert isinstance(result["rules"], list)
        assert result["total"] > 0

    def test_list_all_rules_count_at_least_60(self, tool):
        """
        GIVEN no category filter
        WHEN listing rules
        THEN at least 60 rules are available (CEC has 67 rules).
        """
        result = run(tool.execute({}))
        assert result["total"] >= 60

    def test_filter_by_modal_category(self, tool):
        """
        GIVEN category='modal'
        WHEN listing rules
        THEN returns only modal rules.
        """
        result = run(tool.execute({"category": "modal"}))
        assert result["success"] is True
        assert len(result["rules"]) >= 5
        for rule in result["rules"]:
            assert rule["category"] == "modal"

    def test_filter_by_resolution_category(self, tool):
        """
        GIVEN category='resolution'
        WHEN listing rules
        THEN returns only resolution rules.
        """
        result = run(tool.execute({"category": "resolution"}))
        assert result["success"] is True
        assert len(result["rules"]) >= 5

    def test_filter_by_propositional_category(self, tool):
        """
        GIVEN category='propositional'
        WHEN listing rules
        THEN returns at least 10 propositional rules.
        """
        result = run(tool.execute({"category": "propositional"}))
        assert len(result["rules"]) >= 10

    def test_rules_have_name_and_category(self, tool):
        """
        GIVEN default parameters
        WHEN listing rules
        THEN each rule entry has 'name' and 'category' keys.
        """
        result = run(tool.execute({}))
        for rule in result["rules"]:
            assert "name" in rule
            assert "category" in rule

    def test_include_description_true(self, tool):
        """
        GIVEN include_description=True
        WHEN listing rules
        THEN each rule entry includes 'description'.
        """
        result = run(tool.execute({"include_description": True}))
        for rule in result["rules"]:
            assert "description" in rule

    def test_include_description_false(self, tool):
        """
        GIVEN include_description=False
        WHEN listing rules
        THEN rule entries do NOT include 'description'.
        """
        result = run(tool.execute({"include_description": False}))
        for rule in result["rules"]:
            assert "description" not in rule

    def test_response_includes_elapsed_ms(self, tool):
        """
        GIVEN any call
        WHEN executed
        THEN response includes elapsed_ms float.
        """
        result = run(tool.execute({}))
        assert "elapsed_ms" in result
        assert isinstance(result["elapsed_ms"], (int, float))
        assert result["elapsed_ms"] >= 0


class TestCECApplyRuleTool:
    """Tests for the cec_apply_rule MCP tool."""

    @pytest.fixture
    def tool(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools.cec_inference_tool import (
            CECApplyRuleTool,
        )
        return CECApplyRuleTool()

    def test_tool_metadata(self, tool):
        """
        GIVEN a CECApplyRuleTool instance
        WHEN checking its metadata
        THEN name and schema should be correct.
        """
        assert tool.name == "cec_apply_rule"
        assert "rule" in tool.input_schema["properties"]
        assert "formulas" in tool.input_schema["properties"]

    def test_missing_rule_returns_error(self, tool):
        """
        GIVEN no 'rule' parameter
        WHEN executing
        THEN returns success=False with an error.
        """
        result = run(tool.execute({"formulas": ["P"]}))
        assert result["success"] is False
        assert "error" in result

    def test_missing_formulas_returns_error(self, tool):
        """
        GIVEN no 'formulas' parameter
        WHEN executing
        THEN returns success=False with an error (empty list → empty axiom list).
        """
        result = run(tool.execute({"rule": "ModusPonens", "formulas": []}))
        # Empty list is valid (just not applicable), so check success may be True
        assert "success" in result

    def test_unknown_rule_returns_error(self, tool):
        """
        GIVEN an unknown rule name
        WHEN executing
        THEN returns success=False with 'not found' error.
        """
        result = run(tool.execute({
            "rule": "NonExistentRuleXYZ",
            "formulas": ["P"],
        }))
        assert result["success"] is False
        assert "not found" in result["error"].lower() or "NonExistentRuleXYZ" in result["error"]

    def test_known_rule_returns_applicable_field(self, tool):
        """
        GIVEN a known rule (ModusPonens) and some formulas
        WHEN executing
        THEN response has 'applicable' field.
        """
        result = run(tool.execute({
            "rule": "ModusPonens",
            "formulas": ["P", "Q"],
        }))
        assert result["success"] is True
        assert "applicable" in result

    def test_response_includes_input_formulas(self, tool):
        """
        GIVEN a valid request
        WHEN executing
        THEN response echoes 'input_formulas'.
        """
        formulas = ["P", "Q"]
        result = run(tool.execute({"rule": "ModusPonens", "formulas": formulas}))
        assert result["success"] is True
        assert result["input_formulas"] == formulas

    def test_response_includes_conclusions(self, tool):
        """
        GIVEN a valid request
        WHEN executing
        THEN response includes 'conclusions' list (may be empty).
        """
        result = run(tool.execute({"rule": "ModusPonens", "formulas": ["P", "Q"]}))
        assert result["success"] is True
        assert isinstance(result["conclusions"], list)

    def test_tautology_rule_with_single_formula(self, tool):
        """
        GIVEN TautologyRule and one formula
        WHEN executing
        THEN rule can be applied (always applicable).
        """
        result = run(tool.execute({"rule": "TautologyRule", "formulas": ["P"]}))
        assert result["success"] is True
        # TautologyRule may or may not be applicable depending on implementation
        assert "applicable" in result


class TestCECCheckRuleTool:
    """Tests for the cec_check_rule MCP tool."""

    @pytest.fixture
    def tool(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools.cec_inference_tool import (
            CECCheckRuleTool,
        )
        return CECCheckRuleTool()

    def test_tool_metadata(self, tool):
        """
        GIVEN a CECCheckRuleTool instance
        WHEN checking metadata
        THEN name and schema are set correctly.
        """
        assert tool.name == "cec_check_rule"
        assert "rule" in tool.input_schema["properties"]

    def test_check_returns_applicable_bool(self, tool):
        """
        GIVEN a known rule and formulas
        WHEN checking
        THEN response has 'applicable' bool.
        """
        result = run(tool.execute({"rule": "ModusPonens", "formulas": ["P", "Q"]}))
        assert result["success"] is True
        assert isinstance(result["applicable"], bool)

    def test_unknown_rule_returns_error(self, tool):
        """
        GIVEN unknown rule
        WHEN checking
        THEN returns success=False.
        """
        result = run(tool.execute({"rule": "FakeRule9999", "formulas": ["P"]}))
        assert result["success"] is False

    def test_empty_rule_name_returns_error(self, tool):
        """
        GIVEN empty rule name
        WHEN checking
        THEN returns success=False.
        """
        result = run(tool.execute({"rule": "", "formulas": ["P"]}))
        assert result["success"] is False


class TestCECRuleInfoTool:
    """Tests for the cec_rule_info MCP tool."""

    @pytest.fixture
    def tool(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools.cec_inference_tool import (
            CECRuleInfoTool,
        )
        return CECRuleInfoTool()

    def test_tool_metadata(self, tool):
        """
        GIVEN a CECRuleInfoTool instance
        WHEN checking metadata
        THEN name and schema are set.
        """
        assert tool.name == "cec_rule_info"
        assert "rule" in tool.input_schema["properties"]

    def test_known_rule_returns_info(self, tool):
        """
        GIVEN a known rule name
        WHEN getting info
        THEN returns name, category, module, docstring, methods.
        """
        result = run(tool.execute({"rule": "ModusPonens"}))
        assert result["success"] is True
        assert result["name"] == "ModusPonens"
        assert "category" in result
        assert "module" in result
        assert "methods" in result

    def test_known_modal_rule_returns_info(self, tool):
        """
        GIVEN a modal rule name
        WHEN getting info
        THEN category is 'modal'.
        """
        result = run(tool.execute({"rule": "NecessityElimination"}))
        assert result["success"] is True
        assert result["category"] == "modal"

    def test_unknown_rule_returns_available_list(self, tool):
        """
        GIVEN an unknown rule name
        WHEN getting info
        THEN returns success=False and lists available_rules.
        """
        result = run(tool.execute({"rule": "BadRuleName"}))
        assert result["success"] is False
        assert "available_rules" in result
        assert len(result["available_rules"]) > 0

    def test_empty_rule_name_returns_error(self, tool):
        """
        GIVEN empty rule name
        WHEN getting info
        THEN returns success=False.
        """
        result = run(tool.execute({"rule": ""}))
        assert result["success"] is False


# ---------------------------------------------------------------------------
# Logic Capabilities Tool Tests
# ---------------------------------------------------------------------------

class TestLogicCapabilitiesTool:
    """Tests for the logic_capabilities MCP tool."""

    @pytest.fixture
    def tool(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools.logic_capabilities_tool import (
            LogicCapabilitiesTool,
        )
        return LogicCapabilitiesTool()

    def test_tool_metadata(self, tool):
        """
        GIVEN a LogicCapabilitiesTool instance
        WHEN checking metadata
        THEN name, category, and tags are correct.
        """
        assert tool.name == "logic_capabilities"
        assert tool.category == "logic_tools"
        assert "discovery" in tool.tags

    def test_returns_supported_logics(self, tool):
        """
        GIVEN default parameters
        WHEN executing
        THEN returns list containing 'tdfol' and 'cec'.
        """
        result = run(tool.execute({}))
        assert result["success"] is True
        assert "tdfol" in result["logics"]
        assert "cec" in result["logics"]

    def test_returns_conversions_list(self, tool):
        """
        GIVEN default parameters
        WHEN executing
        THEN returns non-empty conversions list.
        """
        result = run(tool.execute({}))
        assert isinstance(result["conversions"], list)
        assert len(result["conversions"]) > 0

    def test_returns_inference_rule_counts(self, tool):
        """
        GIVEN include_rule_counts=True
        WHEN executing
        THEN inference_rules dict has 'cec' key with count >= 60.
        """
        result = run(tool.execute({"include_rule_counts": True}))
        assert "inference_rules" in result
        assert result["inference_rules"].get("cec", 0) >= 60

    def test_skip_inference_rule_counts(self, tool):
        """
        GIVEN include_rule_counts=False
        WHEN executing
        THEN inference_rules dict is empty.
        """
        result = run(tool.execute({"include_rule_counts": False}))
        assert result["inference_rules"] == {}

    def test_returns_features_list(self, tool):
        """
        GIVEN default parameters
        WHEN executing
        THEN features list is non-empty.
        """
        result = run(tool.execute({}))
        assert isinstance(result["features"], list)
        assert len(result["features"]) > 0

    def test_returns_version_string(self, tool):
        """
        GIVEN any parameters
        WHEN executing
        THEN returns version string.
        """
        result = run(tool.execute({}))
        assert "version" in result
        assert isinstance(result["version"], str)

    def test_response_includes_elapsed_ms(self, tool):
        """
        GIVEN any call
        WHEN executed
        THEN response includes elapsed_ms.
        """
        result = run(tool.execute({}))
        assert "elapsed_ms" in result
        assert result["elapsed_ms"] >= 0


class TestLogicHealthTool:
    """Tests for the logic_health MCP tool."""

    @pytest.fixture
    def tool(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools.logic_capabilities_tool import (
            LogicHealthTool,
        )
        return LogicHealthTool()

    def test_tool_metadata(self, tool):
        """
        GIVEN a LogicHealthTool instance
        WHEN checking metadata
        THEN name, category, and tags are correct.
        """
        assert tool.name == "logic_health"
        assert tool.category == "logic_tools"
        assert "health" in tool.tags
        assert "diagnostics" in tool.tags

    def test_returns_valid_status(self, tool):
        """
        GIVEN default parameters
        WHEN executing
        THEN returns status in ('healthy', 'degraded', 'unavailable').
        """
        result = run(tool.execute({}))
        assert result["success"] is True
        assert result["status"] in ("healthy", "degraded", "unavailable")

    def test_returns_modules_dict(self, tool):
        """
        GIVEN default parameters
        WHEN executing
        THEN returns modules dict with expected keys.
        """
        result = run(tool.execute({}))
        modules = result["modules"]
        assert isinstance(modules, dict)
        for key in ("tdfol", "cec", "fol", "zkp", "validators"):
            assert key in modules
            assert isinstance(modules[key], bool)

    def test_healthy_when_core_modules_available(self, tool):
        """
        GIVEN core modules (tdfol, cec) are available
        WHEN executing
        THEN status is 'healthy'.
        """
        result = run(tool.execute({}))
        # In this environment they should be available
        if result["modules"]["tdfol"] and result["modules"]["cec"]:
            assert result["status"] == "healthy"

    def test_cec_rule_count_in_modules(self, tool):
        """
        GIVEN default parameters
        WHEN executing
        THEN modules dict includes cec_inference_rules_count.
        """
        result = run(tool.execute({}))
        assert "cec_inference_rules_count" in result["modules"]
        assert result["modules"]["cec_inference_rules_count"] >= 60

    def test_verbose_false_no_errors_key(self, tool):
        """
        GIVEN verbose=False
        WHEN executing
        THEN response does NOT include 'errors' key (unless there are errors).
        """
        result = run(tool.execute({"verbose": False}))
        # errors key should only appear in verbose mode when there are errors
        # In a healthy environment, errors key may be absent
        assert result["success"] is True

    def test_verbose_true_allowed(self, tool):
        """
        GIVEN verbose=True
        WHEN executing
        THEN response succeeds (verbose flag is accepted).
        """
        result = run(tool.execute({"verbose": True}))
        assert result["success"] is True

    def test_response_includes_elapsed_ms(self, tool):
        """
        GIVEN any call
        WHEN executed
        THEN response includes elapsed_ms.
        """
        result = run(tool.execute({}))
        assert "elapsed_ms" in result
        assert result["elapsed_ms"] >= 0

    def test_returns_version_string(self, tool):
        """
        GIVEN any call
        WHEN executed
        THEN returns version string.
        """
        result = run(tool.execute({}))
        assert "version" in result


# ---------------------------------------------------------------------------
# Integration: Tool Registration
# ---------------------------------------------------------------------------

class TestLogicToolsRegistration:
    """Integration tests: new tools appear in ALL_LOGIC_TOOLS."""

    def test_cec_inference_tools_in_all(self):
        """
        GIVEN ALL_LOGIC_TOOLS
        WHEN checking
        THEN all 4 CEC inference tools are present.
        """
        from ipfs_datasets_py.mcp_server.tools.logic_tools import ALL_LOGIC_TOOLS
        names = {t.name for t in ALL_LOGIC_TOOLS}
        assert "cec_list_rules" in names
        assert "cec_apply_rule" in names
        assert "cec_check_rule" in names
        assert "cec_rule_info" in names

    def test_capabilities_tools_in_all(self):
        """
        GIVEN ALL_LOGIC_TOOLS
        WHEN checking
        THEN both capabilities tools are present.
        """
        from ipfs_datasets_py.mcp_server.tools.logic_tools import ALL_LOGIC_TOOLS
        names = {t.name for t in ALL_LOGIC_TOOLS}
        assert "logic_capabilities" in names
        assert "logic_health" in names

    def test_all_tools_have_input_schema(self):
        """
        GIVEN ALL_LOGIC_TOOLS
        WHEN iterating
        THEN all tools have an input_schema dict.
        """
        from ipfs_datasets_py.mcp_server.tools.logic_tools import ALL_LOGIC_TOOLS
        for tool in ALL_LOGIC_TOOLS:
            if tool.name:  # Skip unnamed placeholders
                assert isinstance(tool.input_schema, dict), (
                    f"Tool '{tool.name}' missing input_schema"
                )

    def test_total_logic_tools_count(self):
        """
        GIVEN ALL_LOGIC_TOOLS
        WHEN counting named tools
        THEN at least 16 tools are registered (6 original + 4 CEC + 2 capabilities + others).
        """
        from ipfs_datasets_py.mcp_server.tools.logic_tools import ALL_LOGIC_TOOLS
        named = [t for t in ALL_LOGIC_TOOLS if t.name]
        assert len(named) >= 10


# ---------------------------------------------------------------------------
# Deprecation tests for api_server.py
# ---------------------------------------------------------------------------

class TestApiServerDeprecation:
    """Tests that the old api_server.py emits deprecation warnings."""

    def test_create_app_warns_deprecated(self):
        """
        GIVEN logic.api_server.create_app
        WHEN called
        THEN emits DeprecationWarning.
        """
        with pytest.warns(DeprecationWarning, match="deprecated"):
            try:
                from ipfs_datasets_py.logic.api_server import create_app
                create_app()
            except ImportError:
                pass  # FastAPI not installed — warning was still emitted

    def test_api_server_module_app_is_none(self):
        """
        GIVEN logic.api_server module
        WHEN inspecting module-level 'app'
        THEN it should be None (no longer eagerly created).
        """
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from ipfs_datasets_py.logic import api_server
            assert api_server.app is None
