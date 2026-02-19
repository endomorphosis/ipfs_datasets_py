"""
Tests for logic MCP tools (plain async function pattern).

All tools are now plain async functions in ``mcp_server/tools/logic_tools/``
that delegate to ``core_operations.LogicProcessor``.

Tests call functions directly — no ``ClaudeMCPTool.execute()`` indirection.
"""

from __future__ import annotations

import asyncio
import inspect
import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run(coro):
    """Run an async coroutine synchronously for pytest."""
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# LogicProcessor — core_operations integration
# ---------------------------------------------------------------------------

class TestLogicProcessorImport:
    """GIVEN core_operations WHEN importing LogicProcessor THEN it is available."""

    def test_import_logic_processor(self):
        from ipfs_datasets_py.core_operations import LogicProcessor
        assert LogicProcessor is not None

    def test_logic_processor_is_exported_from_core_operations(self):
        import ipfs_datasets_py.core_operations as co
        assert "LogicProcessor" in dir(co)

    def test_logic_processor_instantiates(self):
        from ipfs_datasets_py.core_operations import LogicProcessor
        lp = LogicProcessor()
        assert lp is not None


# ---------------------------------------------------------------------------
# Tool discovery — plain async functions only
# ---------------------------------------------------------------------------

class TestToolDiscovery:
    """GIVEN logic_tools WHEN discovering tools THEN all are plain async functions."""

    def _get_all_tools(self):
        from pathlib import Path
        import importlib
        tools_dir = Path(__file__).parent.parent.parent.parent / "ipfs_datasets_py" / "mcp_server" / "tools" / "logic_tools"
        discovered = []
        for tool_file in sorted(tools_dir.glob("*.py")):
            if tool_file.name.startswith("_") or tool_file.name == "__init__.py":
                continue
            mod = importlib.import_module(f"ipfs_datasets_py.mcp_server.tools.logic_tools.{tool_file.stem}")
            fns = [f for name, f in inspect.getmembers(mod)
                   if inspect.iscoroutinefunction(f) and not name.startswith("_")]
            discovered.extend(fns)
        return discovered

    def test_all_logic_tools_are_async_functions(self):
        """
        GIVEN all logic tool files
        WHEN scanning for callables
        THEN every exported tool is a plain async function (not a class).
        """
        tools = self._get_all_tools()
        for fn in tools:
            assert inspect.iscoroutinefunction(fn), f"{fn.__name__} is not async"
            assert not isinstance(fn, type), f"{fn.__name__} is a class, not a function"

    def test_no_claude_mcp_tool_classes_remain(self):
        """
        GIVEN logic_tools modules
        WHEN checking for ClaudeMCPTool subclasses
        THEN none should exist.
        """
        from pathlib import Path
        import importlib
        tools_dir = Path(__file__).parent.parent.parent.parent / "ipfs_datasets_py" / "mcp_server" / "tools" / "logic_tools"
        for tool_file in sorted(tools_dir.glob("*.py")):
            if tool_file.name.startswith("_") or tool_file.name == "__init__.py":
                continue
            mod = importlib.import_module(f"ipfs_datasets_py.mcp_server.tools.logic_tools.{tool_file.stem}")
            for name, obj in inspect.getmembers(mod):
                if isinstance(obj, type):
                    try:
                        from ipfs_datasets_py.mcp_server.tool_registry import ClaudeMCPTool
                        assert not issubclass(obj, ClaudeMCPTool), (
                            f"{name} in {tool_file.name} is still a ClaudeMCPTool subclass"
                        )
                    except ImportError:
                        pass

    def test_at_least_27_tools_discovered(self):
        """
        GIVEN all logic tool files
        WHEN counting async functions
        THEN at least 27 are discovered.
        """
        tools = self._get_all_tools()
        assert len(tools) >= 27, f"Expected >=27 tools, got {len(tools)}"

    def test_init_exports_27_known_tools(self):
        """
        GIVEN logic_tools/__init__.py
        WHEN checking __all__
        THEN all 27 expected tool names are present.
        """
        import ipfs_datasets_py.mcp_server.tools.logic_tools as lt
        expected = {
            "check_document_consistency", "query_theorems", "bulk_process_caselaw", "add_theorem",
            "tdfol_prove", "tdfol_batch_prove", "tdfol_parse", "tdfol_convert",
            "tdfol_kb_add_axiom", "tdfol_kb_add_theorem", "tdfol_kb_query", "tdfol_kb_export",
            "tdfol_visualize",
            "cec_list_rules", "cec_apply_rule", "cec_check_rule", "cec_rule_info",
            "cec_prove", "cec_check_theorem",
            "cec_parse", "cec_validate_formula",
            "cec_analyze_formula", "cec_formula_complexity",
            "logic_capabilities", "logic_health",
            "logic_build_knowledge_graph", "logic_verify_rag_output",
        }
        exported = set(lt.__all__)
        missing = expected - exported
        assert not missing, f"Missing from __all__: {missing}"


# ---------------------------------------------------------------------------
# CEC Inference Tools
# ---------------------------------------------------------------------------

class TestCECListRules:
    """Tests for cec_list_rules."""

    def test_returns_success(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools import cec_list_rules
        result = run(cec_list_rules())
        assert result["success"] is True
        assert isinstance(result["rules"], list)
        assert result["total"] > 0

    def test_returns_at_least_60_rules(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools import cec_list_rules
        result = run(cec_list_rules())
        assert result["total"] >= 60, f"Expected >=60, got {result['total']}"

    def test_filter_by_modal_category(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools import cec_list_rules
        result = run(cec_list_rules(category="modal"))
        assert result["success"] is True
        assert all(r["category"] == "modal" for r in result["rules"])

    def test_filter_by_unknown_category_returns_empty(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools import cec_list_rules
        result = run(cec_list_rules(category="nonexistent_category"))
        assert result["success"] is True
        assert result["total"] == 0

    def test_no_description_flag(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools import cec_list_rules
        result = run(cec_list_rules(include_description=False))
        assert result["success"] is True
        if result["rules"]:
            assert "description" not in result["rules"][0]

    def test_rules_have_name_and_category(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools import cec_list_rules
        result = run(cec_list_rules())
        for rule in result["rules"]:
            assert "name" in rule
            assert "category" in rule

    def test_elapsed_ms_present(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools import cec_list_rules
        result = run(cec_list_rules())
        assert "elapsed_ms" in result
        assert result["elapsed_ms"] >= 0


class TestCECCheckRule:
    """Tests for cec_check_rule."""

    def test_returns_applicable_bool(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools import cec_check_rule
        result = run(cec_check_rule(rule="ModusPonens", formulas=["P", "Q"]))
        assert "applicable" in result
        assert isinstance(result["applicable"], bool)

    def test_missing_rule_returns_failure(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools import cec_check_rule
        result = run(cec_check_rule(rule="NonExistentRule9999", formulas=["P"]))
        assert result["success"] is False

    def test_empty_rule_returns_failure(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools import cec_check_rule
        result = run(cec_check_rule(rule="", formulas=["P"]))
        assert result["success"] is False


class TestCECApplyRule:
    """Tests for cec_apply_rule."""

    def test_returns_applicable_and_conclusions(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools import cec_apply_rule
        result = run(cec_apply_rule(rule="ModusPonens", formulas=["P", "Q"]))
        assert "applicable" in result
        assert "conclusions" in result
        assert isinstance(result["conclusions"], list)

    def test_missing_rule_name_returns_failure(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools import cec_apply_rule
        result = run(cec_apply_rule(rule="", formulas=["P"]))
        assert result["success"] is False


class TestCECRuleInfo:
    """Tests for cec_rule_info."""

    def test_known_rule_returns_info(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools import cec_list_rules, cec_rule_info
        # Get a known rule name first
        rules = run(cec_list_rules())
        if not rules["rules"]:
            pytest.skip("No CEC rules available")
        rule_name = rules["rules"][0]["name"]
        result = run(cec_rule_info(rule=rule_name))
        assert result["success"] is True
        assert result["name"] == rule_name
        assert "category" in result
        assert "docstring" in result
        assert "methods" in result

    def test_unknown_rule_returns_failure(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools import cec_rule_info
        result = run(cec_rule_info(rule="NonExistentRule9999"))
        assert result["success"] is False


# ---------------------------------------------------------------------------
# CEC Prove
# ---------------------------------------------------------------------------

class TestCECProve:
    """Tests for cec_prove."""

    def test_returns_proved_bool(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools import cec_prove
        result = run(cec_prove(goal="P(x) -> P(x)"))
        assert "proved" in result
        assert isinstance(result["proved"], bool)

    def test_empty_goal_returns_failure(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools import cec_prove
        result = run(cec_prove(goal=""))
        assert result["success"] is False

    def test_elapsed_ms_present(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools import cec_prove
        result = run(cec_prove(goal="P(x)"))
        assert "elapsed_ms" in result


class TestCECCheckTheorem:
    """Tests for cec_check_theorem."""

    def test_returns_is_theorem_bool(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools import cec_check_theorem
        result = run(cec_check_theorem(formula="P | ~P"))
        assert "is_theorem" in result
        assert isinstance(result["is_theorem"], bool)

    def test_empty_formula_returns_failure(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools import cec_check_theorem
        result = run(cec_check_theorem(formula=""))
        assert result["success"] is False


# ---------------------------------------------------------------------------
# CEC Parse & Validate
# ---------------------------------------------------------------------------

class TestCECParse:
    """Tests for cec_parse."""

    def test_returns_formula_string(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools import cec_parse
        result = run(cec_parse(text="The agent must comply"))
        assert result["success"] is True
        assert isinstance(result["formula"], str)
        assert len(result["formula"]) > 0

    def test_empty_text_returns_failure(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools import cec_parse
        result = run(cec_parse(text=""))
        assert result["success"] is False

    def test_confidence_is_float(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools import cec_parse
        result = run(cec_parse(text="The party is obligated to pay"))
        assert isinstance(result.get("confidence"), float)
        assert 0.0 <= result["confidence"] <= 1.0


class TestCECValidateFormula:
    """Tests for cec_validate_formula."""

    def test_returns_valid_bool(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools import cec_validate_formula
        result = run(cec_validate_formula(formula="O(pay_taxes(agent))"))
        assert result["success"] is True
        assert "valid" in result
        assert isinstance(result["valid"], bool)

    def test_empty_formula_returns_failure(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools import cec_validate_formula
        result = run(cec_validate_formula(formula=""))
        assert result["success"] is False


# ---------------------------------------------------------------------------
# CEC Analysis
# ---------------------------------------------------------------------------

class TestCECAnalyzeFormula:
    """Tests for cec_analyze_formula."""

    def test_returns_structural_metrics(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools import cec_analyze_formula
        result = run(cec_analyze_formula(formula="P -> Q"))
        assert result["success"] is True
        assert "depth" in result
        assert "size" in result
        assert "operators" in result

    def test_empty_formula_returns_failure(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools import cec_analyze_formula
        result = run(cec_analyze_formula(formula=""))
        assert result["success"] is False


class TestCECFormulaComplexity:
    """Tests for cec_formula_complexity."""

    def test_returns_complexity_level(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools import cec_formula_complexity
        result = run(cec_formula_complexity(formula="P -> Q"))
        assert result["success"] is True
        assert result["complexity"] in ("low", "medium", "high")

    def test_formula_complexity_returns_valid_level(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools import cec_formula_complexity
        # Any formula should return one of the three levels
        result = run(cec_formula_complexity(formula="P -> Q -> R"))
        assert result["success"] is True
        assert result["complexity"] in ("low", "medium", "high")

    def test_simple_formula_depth_and_size(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools import cec_formula_complexity
        result = run(cec_formula_complexity(formula="P"))
        assert result["success"] is True
        # A single atom is never high complexity
        assert result["complexity"] in ("low", "medium")
        assert "depth" in result and result["depth"] >= 1
        assert "size" in result and result["size"] >= 1


# ---------------------------------------------------------------------------
# Logic Capabilities & Health
# ---------------------------------------------------------------------------

class TestLogicCapabilities:
    """Tests for logic_capabilities."""

    def test_returns_logics_dict(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools import logic_capabilities
        result = run(logic_capabilities())
        assert result["success"] is True
        assert "logics" in result
        assert "tdfol" in result["logics"]
        assert "cec" in result["logics"]

    def test_returns_conversions_list(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools import logic_capabilities
        result = run(logic_capabilities())
        assert isinstance(result["conversions"], list)
        assert len(result["conversions"]) > 0

    def test_nl_languages_present(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools import logic_capabilities
        result = run(logic_capabilities())
        assert "nl_languages" in result
        assert "en" in result["nl_languages"]

    def test_elapsed_ms_present(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools import logic_capabilities
        result = run(logic_capabilities())
        assert "elapsed_ms" in result


class TestLogicHealth:
    """Tests for logic_health."""

    def test_returns_status_string(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools import logic_health
        result = run(logic_health())
        assert result["success"] is True
        assert result["status"] in ("healthy", "degraded", "unavailable")

    def test_returns_modules_dict(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools import logic_health
        result = run(logic_health())
        assert "modules" in result
        for name, status in result["modules"].items():
            assert status in ("ok", "unavailable"), f"{name}: unexpected status {status!r}"

    def test_healthy_and_total_counts(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools import logic_health
        result = run(logic_health())
        assert "healthy" in result
        assert "total" in result
        assert 0 <= result["healthy"] <= result["total"]


# ---------------------------------------------------------------------------
# TDFOL Tools
# ---------------------------------------------------------------------------

class TestTDFOLProve:
    """Tests for tdfol_prove."""

    def test_returns_success_dict(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools import tdfol_prove
        result = run(tdfol_prove(formula="∀x.P(x)"))
        assert isinstance(result, dict)
        assert "success" in result

    def test_empty_formula_returns_failure(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools import tdfol_prove
        result = run(tdfol_prove(formula=""))
        assert result["success"] is False


class TestTDFOLBatchProve:
    """Tests for tdfol_batch_prove."""

    def test_returns_results_list(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools import tdfol_batch_prove
        result = run(tdfol_batch_prove(formulas=["P", "Q"]))
        assert isinstance(result, dict)
        assert "results" in result
        assert len(result["results"]) <= 2

    def test_empty_formulas_returns_failure(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools import tdfol_batch_prove
        result = run(tdfol_batch_prove(formulas=[]))
        assert result["success"] is False


class TestTDFOLParse:
    """Tests for tdfol_parse."""

    def test_returns_formula_string(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools import tdfol_parse
        result = run(tdfol_parse(text="∀x.P(x)"))
        assert isinstance(result, dict)
        assert "success" in result

    def test_empty_text_returns_failure(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools import tdfol_parse
        result = run(tdfol_parse(text=""))
        assert result["success"] is False


class TestTDFOLConvert:
    """Tests for tdfol_convert."""

    def test_returns_converted_formula(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools import tdfol_convert
        result = run(tdfol_convert(formula="∀x.P(x)", target_format="fol"))
        assert isinstance(result, dict)
        assert "success" in result

    def test_empty_formula_returns_failure(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools import tdfol_convert
        result = run(tdfol_convert(formula=""))
        assert result["success"] is False


class TestTDFOLKB:
    """Tests for tdfol knowledge base tools."""

    def test_add_axiom_returns_success(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools import tdfol_kb_add_axiom
        result = run(tdfol_kb_add_axiom(formula="∀x.P(x)"))
        assert isinstance(result, dict)
        assert "success" in result

    def test_add_theorem_returns_success(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools import tdfol_kb_add_theorem
        result = run(tdfol_kb_add_theorem(formula="P(a)"))
        assert isinstance(result, dict)
        assert "success" in result

    def test_query_returns_dict(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools import tdfol_kb_query
        result = run(tdfol_kb_query())
        assert isinstance(result, dict)
        assert "success" in result

    def test_export_returns_dict(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools import tdfol_kb_export
        result = run(tdfol_kb_export())
        assert isinstance(result, dict)
        assert "success" in result

    def test_empty_formula_add_axiom_fails(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools import tdfol_kb_add_axiom
        result = run(tdfol_kb_add_axiom(formula=""))
        assert result["success"] is False


class TestTDFOLVisualize:
    """Tests for tdfol_visualize."""

    def test_returns_visualization_string(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools import tdfol_visualize
        result = run(tdfol_visualize(proof_data={"formula": "P"}, output_format="ascii"))
        assert isinstance(result, dict)
        assert "success" in result
        assert "visualization" in result

    def test_json_format(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools import tdfol_visualize
        result = run(tdfol_visualize(proof_data=None, output_format="json"))
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# GraphRAG Tools
# ---------------------------------------------------------------------------

class TestLogicBuildKnowledgeGraph:
    """Tests for logic_build_knowledge_graph."""

    def test_returns_nodes_and_edges(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools import logic_build_knowledge_graph
        result = run(logic_build_knowledge_graph(
            text_corpus="The agent must comply with regulations before the deadline."
        ))
        assert result["success"] is True
        assert "nodes" in result
        assert "edges" in result
        assert isinstance(result["nodes"], list)
        assert isinstance(result["edges"], list)

    def test_node_count_and_edge_count(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools import logic_build_knowledge_graph
        result = run(logic_build_knowledge_graph(
            text_corpus="The party shall not violate the agreement."
        ))
        assert result["node_count"] == len(result["nodes"])
        assert result["edge_count"] == len(result["edges"])

    def test_empty_corpus_returns_failure(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools import logic_build_knowledge_graph
        result = run(logic_build_knowledge_graph(text_corpus=""))
        assert result["success"] is False

    def test_max_entities_respected(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools import logic_build_knowledge_graph
        result = run(logic_build_knowledge_graph(
            text_corpus="must shall may prohibited required permitted " * 30,
            max_entities=5,
        ))
        assert result["node_count"] <= 5


class TestLogicVerifyRAGOutput:
    """Tests for logic_verify_rag_output."""

    def test_returns_consistent_bool(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools import logic_verify_rag_output
        result = run(logic_verify_rag_output(
            answer="The agent must pay taxes.",
            constraints=["O(pay_taxes(agent))"],
        ))
        assert result["success"] is True
        assert "consistent" in result
        assert isinstance(result["consistent"], bool)

    def test_no_constraints_returns_consistent(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools import logic_verify_rag_output
        result = run(logic_verify_rag_output(answer="P implies Q.", constraints=[]))
        assert result["success"] is True
        assert result["consistent"] is True

    def test_empty_answer_returns_failure(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools import logic_verify_rag_output
        result = run(logic_verify_rag_output(answer=""))
        assert result["success"] is False
