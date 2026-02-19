"""
Tests for the new CEC MCP tools (Phase 2-4 MCP integration):
  - cec_prove_tool      : CECProveTool, CECCheckTheoremTool
  - cec_parse_tool      : CECParseTool, CECValidateFormulaTool
  - cec_analysis_tool   : CECAnalyzeFormulaTool, CECFormulaComplexityTool
  - logic_graphrag_tool : LogicBuildKnowledgeGraphTool, LogicVerifyRAGOutputTool

All tests use direct async execution (no HTTP server needed).
"""

import asyncio
import pytest


def run(coro):
    """Run an async coroutine synchronously for pytest."""
    return asyncio.run(coro)


# ============================================================
# CEC Prove Tool
# ============================================================

class TestCECProveTool:
    """Tests for the cec_prove MCP tool."""

    @pytest.fixture
    def tool(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools.cec_prove_tool import CECProveTool
        return CECProveTool()

    def test_tool_metadata(self, tool):
        """
        GIVEN a CECProveTool instance
        WHEN checking metadata
        THEN name, category, tags, and input_schema are set correctly.
        """
        assert tool.name == "cec_prove"
        assert tool.category == "logic_tools"
        assert "cec" in tool.tags
        assert "prove" in tool.tags
        assert tool.input_schema is not None

    def test_execute_requires_goal(self, tool):
        """
        GIVEN no 'goal' parameter
        WHEN cec_prove.execute is called
        THEN returns success=False with an error.
        """
        result = run(tool.execute({}))
        assert result["success"] is False
        assert "error" in result

    def test_execute_with_valid_goal(self, tool):
        """
        GIVEN a valid goal formula
        WHEN cec_prove.execute is called
        THEN returns a dict with 'proved' bool key.
        """
        result = run(tool.execute({"goal": "P(x)"}))
        assert "proved" in result
        assert isinstance(result["proved"], bool)

    def test_execute_with_axioms(self, tool):
        """
        GIVEN a goal and a list of axioms
        WHEN cec_prove.execute is called
        THEN returns a result without raising exceptions.
        """
        result = run(tool.execute({
            "goal": "Q(x)",
            "axioms": ["P(x)", "P_implies_Q"],
        }))
        assert "proved" in result

    def test_execute_with_strategy(self, tool):
        """
        GIVEN a valid strategy enum value
        WHEN cec_prove.execute is called
        THEN does not error out.
        """
        result = run(tool.execute({"goal": "P(x)", "strategy": "auto"}))
        assert "proved" in result

    def test_execute_with_timeout(self, tool):
        """
        GIVEN a timeout parameter
        WHEN cec_prove.execute is called
        THEN returns timing info.
        """
        result = run(tool.execute({"goal": "P(x)", "timeout": 5}))
        assert "elapsed_ms" in result

    def test_execute_injection_rejected(self, tool):
        """
        GIVEN a formula containing an injection pattern (exec, os.system)
        WHEN cec_prove.execute is called
        THEN returns success=False.
        """
        result = run(tool.execute({"goal": "__import__('os').system('id')"}))
        assert result["success"] is False

    def test_execute_tool_version_present(self, tool):
        """
        GIVEN a valid goal
        WHEN cec_prove.execute is called
        THEN tool_version is present in the result.
        """
        result = run(tool.execute({"goal": "A(x)"}))
        assert result.get("tool_version") == "1.0.0"


class TestCECCheckTheoremTool:
    """Tests for the cec_check_theorem MCP tool."""

    @pytest.fixture
    def tool(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools.cec_prove_tool import CECCheckTheoremTool
        return CECCheckTheoremTool()

    def test_tool_metadata(self, tool):
        assert tool.name == "cec_check_theorem"
        assert tool.category == "logic_tools"
        assert "tautology" in tool.tags

    def test_execute_requires_formula(self, tool):
        result = run(tool.execute({}))
        assert result["success"] is False

    def test_execute_returns_is_theorem(self, tool):
        """
        GIVEN a formula string
        WHEN cec_check_theorem.execute is called
        THEN is_theorem bool is present.
        """
        result = run(tool.execute({"formula": "P(x)"}))
        assert "is_theorem" in result
        assert isinstance(result["is_theorem"], bool)

    def test_counterexample_key_present(self, tool):
        """
        GIVEN a formula
        WHEN cec_check_theorem.execute is called
        THEN counterexample key is present in the result.
        """
        result = run(tool.execute({"formula": "P(x)"}))
        assert "counterexample" in result

    def test_tool_version_present(self, tool):
        result = run(tool.execute({"formula": "P(x)"}))
        assert result.get("tool_version") == "1.0.0"


# ============================================================
# CEC Parse Tool
# ============================================================

class TestCECParseTool:
    """Tests for the cec_parse MCP tool."""

    @pytest.fixture
    def tool(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools.cec_parse_tool import CECParseTool
        return CECParseTool()

    def test_tool_metadata(self, tool):
        assert tool.name == "cec_parse"
        assert tool.category == "logic_tools"
        assert "nl" in tool.tags
        assert "parse" in tool.tags

    def test_execute_requires_text(self, tool):
        result = run(tool.execute({}))
        assert result["success"] is False

    def test_execute_returns_formula(self, tool):
        """
        GIVEN a natural-language obligation sentence
        WHEN cec_parse.execute is called
        THEN formula is a non-empty string.
        """
        result = run(tool.execute({"text": "The agent must comply with the law."}))
        assert result["success"] is True
        assert isinstance(result["formula"], str)
        assert len(result["formula"]) > 0

    def test_execute_confidence_in_range(self, tool):
        """
        GIVEN a text input
        WHEN cec_parse.execute is called
        THEN confidence is a float in [0, 1].
        """
        result = run(tool.execute({"text": "The agent must comply."}))
        assert 0.0 <= result["confidence"] <= 1.0

    def test_execute_with_language_en(self, tool):
        result = run(tool.execute({"text": "The agent must act.", "language": "en"}))
        assert result["success"] is True
        assert result["language_used"] == "en"

    def test_execute_rejects_oversized_text(self, tool):
        big_text = "x" * 5000
        result = run(tool.execute({"text": big_text}))
        assert result["success"] is False

    def test_execute_tool_version(self, tool):
        result = run(tool.execute({"text": "Agents shall report."}))
        assert result.get("tool_version") == "1.0.0"

    def test_execute_timing_present(self, tool):
        result = run(tool.execute({"text": "The party must pay."}))
        assert "elapsed_ms" in result


class TestCECValidateFormulaTool:
    """Tests for the cec_validate_formula MCP tool."""

    @pytest.fixture
    def tool(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools.cec_parse_tool import CECValidateFormulaTool
        return CECValidateFormulaTool()

    def test_tool_metadata(self, tool):
        assert tool.name == "cec_validate_formula"
        assert tool.category == "logic_tools"
        assert "validate" in tool.tags

    def test_execute_requires_formula(self, tool):
        result = run(tool.execute({}))
        assert result["success"] is False

    def test_execute_returns_valid_bool(self, tool):
        """
        GIVEN a formula string
        WHEN cec_validate_formula.execute is called
        THEN 'valid' bool is present.
        """
        result = run(tool.execute({"formula": "O(pay_taxes(agent))"}))
        assert "valid" in result
        assert isinstance(result["valid"], bool)

    def test_execute_errors_is_list(self, tool):
        result = run(tool.execute({"formula": "O(P(x))"}))
        assert isinstance(result["errors"], list)

    def test_execute_warnings_is_list(self, tool):
        result = run(tool.execute({"formula": "O(P(x))"}))
        assert isinstance(result["warnings"], list)

    def test_injection_rejected(self, tool):
        result = run(tool.execute({"formula": "__import__('os').system('id')"}))
        assert result["valid"] is False

    def test_tool_version_present(self, tool):
        result = run(tool.execute({"formula": "O(P(x))"}))
        assert result.get("tool_version") == "1.0.0"


# ============================================================
# CEC Analysis Tool
# ============================================================

class TestCECAnalyzeFormulaTool:
    """Tests for the cec_analyze_formula MCP tool."""

    @pytest.fixture
    def tool(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools.cec_analysis_tool import CECAnalyzeFormulaTool
        return CECAnalyzeFormulaTool()

    def test_tool_metadata(self, tool):
        assert tool.name == "cec_analyze_formula"
        assert tool.category == "logic_tools"
        assert "analysis" in tool.tags

    def test_execute_requires_formula(self, tool):
        result = run(tool.execute({}))
        assert result["success"] is False

    def test_execute_returns_depth(self, tool):
        """
        GIVEN a formula
        WHEN cec_analyze_formula.execute is called
        THEN 'depth' is a non-negative integer.
        """
        result = run(tool.execute({"formula": "O(P(x)) & K(agent, Q(y))"}))
        assert result["success"] is True
        assert isinstance(result["depth"], int)
        assert result["depth"] >= 0

    def test_execute_returns_size(self, tool):
        result = run(tool.execute({"formula": "O(P(x))"}))
        assert isinstance(result["size"], int)
        assert result["size"] >= 1

    def test_execute_returns_operators_list(self, tool):
        result = run(tool.execute({"formula": "P(x) -> Q(x)"}))
        assert isinstance(result["operators"], list)

    def test_execute_include_complexity_true(self, tool):
        """
        GIVEN include_complexity=True
        WHEN cec_analyze_formula.execute is called
        THEN 'complexity' key is present.
        """
        result = run(tool.execute({"formula": "O(P(x))", "include_complexity": True}))
        assert "complexity" in result
        assert result["complexity"] in ("low", "medium", "high")

    def test_execute_include_complexity_false(self, tool):
        """
        GIVEN include_complexity=False
        WHEN cec_analyze_formula.execute is called
        THEN 'complexity' key is absent.
        """
        result = run(tool.execute({"formula": "O(P(x))", "include_complexity": False}))
        assert "complexity" not in result

    def test_execute_timing_present(self, tool):
        result = run(tool.execute({"formula": "O(P(x))"}))
        assert "elapsed_ms" in result

    def test_execute_tool_version(self, tool):
        result = run(tool.execute({"formula": "O(P(x))"}))
        assert result.get("tool_version") == "1.0.0"

    def test_injection_rejected(self, tool):
        result = run(tool.execute({"formula": "__import__('os').system('id')"}))
        assert result["success"] is False


class TestCECFormulaComplexityTool:
    """Tests for the cec_formula_complexity MCP tool."""

    @pytest.fixture
    def tool(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools.cec_analysis_tool import CECFormulaComplexityTool
        return CECFormulaComplexityTool()

    def test_tool_metadata(self, tool):
        assert tool.name == "cec_formula_complexity"
        assert tool.category == "logic_tools"
        assert "complexity" in tool.tags

    def test_execute_requires_formula(self, tool):
        result = run(tool.execute({}))
        assert result["success"] is False

    def test_execute_returns_classification(self, tool):
        """
        GIVEN a simple formula
        WHEN cec_formula_complexity.execute is called
        THEN 'overall_complexity' is one of low/medium/high.
        """
        result = run(tool.execute({"formula": "O(P(x))"}))
        assert result["success"] is True
        assert result["overall_complexity"] in ("low", "medium", "high")

    def test_simple_formula_is_low(self, tool):
        """
        GIVEN a very short formula
        WHEN cec_formula_complexity.execute is called
        THEN complexity is 'low'.
        """
        result = run(tool.execute({"formula": "P(x)"}))
        assert result["overall_complexity"] == "low"

    def test_execute_returns_scalar_metrics(self, tool):
        result = run(tool.execute({"formula": "O(P(x)) -> K(agent, Q(y))"}))
        assert "modal_depth" in result
        assert "connective_count" in result
        assert "formula_length" in result
        assert isinstance(result["modal_depth"], int)

    def test_execute_tool_version(self, tool):
        result = run(tool.execute({"formula": "O(P(x))"}))
        assert result.get("tool_version") == "1.0.0"

    def test_execute_timing_present(self, tool):
        result = run(tool.execute({"formula": "O(P(x))"}))
        assert "elapsed_ms" in result


# ============================================================
# Logic GraphRAG Tool
# ============================================================

class TestLogicBuildKnowledgeGraphTool:
    """Tests for the logic_build_knowledge_graph MCP tool."""

    @pytest.fixture
    def tool(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools.logic_graphrag_tool import (
            LogicBuildKnowledgeGraphTool,
        )
        return LogicBuildKnowledgeGraphTool()

    def test_tool_metadata(self, tool):
        assert tool.name == "logic_build_knowledge_graph"
        assert tool.category == "logic_tools"
        assert "graphrag" in tool.tags
        assert "knowledge-graph" in tool.tags

    def test_execute_requires_text(self, tool):
        result = run(tool.execute({}))
        assert result["success"] is False

    def test_execute_returns_nodes_and_edges(self, tool):
        """
        GIVEN a text with obligation language
        WHEN logic_build_knowledge_graph.execute is called
        THEN returns lists for 'nodes' and 'edges'.
        """
        result = run(tool.execute({
            "text": "The company must file its annual report by March 31. "
                    "Employees must complete compliance training. "
                    "Contractors must not share confidential information.",
        }))
        assert result["success"] is True
        assert isinstance(result["nodes"], list)
        assert isinstance(result["edges"], list)

    def test_execute_extracts_obligations(self, tool):
        """
        GIVEN text with obligation words
        WHEN logic_build_knowledge_graph.execute is called
        THEN at least one node of type 'obligation' is extracted.
        """
        result = run(tool.execute({
            "text": "The agent must comply with all applicable laws.",
        }))
        obligation_nodes = [n for n in result["nodes"] if n.get("type") == "obligation"]
        assert len(obligation_nodes) >= 1

    def test_execute_nodes_have_required_fields(self, tool):
        """
        GIVEN any text
        WHEN logic_build_knowledge_graph.execute is called
        THEN every node has id, label, type, and source_text.
        """
        result = run(tool.execute({
            "text": "The contractor must not share confidential data.",
        }))
        for node in result["nodes"]:
            assert "id" in node
            assert "label" in node
            assert "type" in node

    def test_execute_include_formulas_true(self, tool):
        """
        GIVEN include_formulas=True
        WHEN logic_build_knowledge_graph.execute is called
        THEN obligation nodes have a 'formula' annotation.
        """
        result = run(tool.execute({
            "text": "The party must pay taxes.",
            "include_formulas": True,
        }))
        obligation_nodes = [n for n in result["nodes"] if n.get("type") == "obligation"]
        if obligation_nodes:
            assert "formula" in obligation_nodes[0]

    def test_execute_max_entities_respected(self, tool):
        """
        GIVEN max_entities=3
        WHEN logic_build_knowledge_graph.execute is called with many obligations
        THEN at most 3 nodes are returned.
        """
        long_text = ". ".join(
            f"The agent_{i} must perform action_{i}" for i in range(20)
        )
        result = run(tool.execute({"text": long_text, "max_entities": 3}))
        assert result["success"] is True
        assert len(result["nodes"]) <= 3

    def test_execute_entity_count_matches_nodes(self, tool):
        result = run(tool.execute({"text": "The agent must comply."}))
        assert result["entity_count"] == len(result["nodes"])

    def test_execute_timing_present(self, tool):
        result = run(tool.execute({"text": "Agent must act."}))
        assert "elapsed_ms" in result

    def test_execute_tool_version(self, tool):
        result = run(tool.execute({"text": "Agent must act."}))
        assert result.get("tool_version") == "1.0.0"

    def test_execute_rejects_oversized_text(self, tool):
        huge = "x " * 20000
        result = run(tool.execute({"text": huge}))
        assert result["success"] is False


class TestLogicVerifyRAGOutputTool:
    """Tests for the logic_verify_rag_output MCP tool."""

    @pytest.fixture
    def tool(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools.logic_graphrag_tool import (
            LogicVerifyRAGOutputTool,
        )
        return LogicVerifyRAGOutputTool()

    def test_tool_metadata(self, tool):
        assert tool.name == "logic_verify_rag_output"
        assert tool.category == "logic_tools"
        assert "rag" in tool.tags
        assert "verify" in tool.tags

    def test_execute_requires_claim(self, tool):
        result = run(tool.execute({"constraints": ["O(P(x))"]}))
        assert result["success"] is False

    def test_execute_requires_constraints(self, tool):
        result = run(tool.execute({"claim": "The tax was filed."}))
        assert result["success"] is False

    def test_execute_returns_consistent_bool(self, tool):
        """
        GIVEN a claim and constraints
        WHEN logic_verify_rag_output.execute is called
        THEN 'consistent' is a bool.
        """
        result = run(tool.execute({
            "claim": "The company filed its taxes.",
            "constraints": ["O(file_taxes(company))", "T(deadline, April_15)"],
        }))
        assert result["success"] is True
        assert isinstance(result["consistent"], bool)

    def test_execute_violations_is_list(self, tool):
        result = run(tool.execute({
            "claim": "The company did not pay.",
            "constraints": ["O(pay(company))"],
        }))
        assert isinstance(result["violations"], list)

    def test_execute_verification_score_in_range(self, tool):
        """
        GIVEN claim and constraints
        WHEN logic_verify_rag_output.execute is called
        THEN verification_score is in [0.0, 1.0].
        """
        result = run(tool.execute({
            "claim": "The agent complied.",
            "constraints": ["O(comply(agent))"],
        }))
        assert 0.0 <= result["verification_score"] <= 1.0

    def test_execute_constraints_checked_count(self, tool):
        constraints = ["O(A)", "O(B)", "O(C)"]
        result = run(tool.execute({
            "claim": "All done.",
            "constraints": constraints,
        }))
        assert result["constraints_checked"] == len(constraints)

    def test_execute_prover_used_present(self, tool):
        result = run(tool.execute({
            "claim": "Agent complied.",
            "constraints": ["O(comply(agent))"],
        }))
        assert "prover_used" in result

    def test_execute_timing_present(self, tool):
        result = run(tool.execute({
            "claim": "Agent acted.",
            "constraints": ["O(act(agent))"],
        }))
        assert "elapsed_ms" in result

    def test_execute_tool_version(self, tool):
        result = run(tool.execute({
            "claim": "Agent acted.",
            "constraints": ["O(act(agent))"],
        }))
        assert result.get("tool_version") == "1.0.0"

    def test_too_many_constraints_rejected(self, tool):
        constraints = [f"O(action_{i})" for i in range(60)]
        result = run(tool.execute({
            "claim": "Something happened.",
            "constraints": constraints,
        }))
        assert result["success"] is False
