"""
Performance Regression Tests for Logic Module.

These tests establish performance baselines and ensure that key operations
stay within acceptable time bounds. If a test fails with a timeout, it
indicates a performance regression.

Performance Targets:
    - Inference rule instantiation: < 1ms each
    - can_apply() check: < 0.5ms each
    - Formula creation: < 0.1ms
    - Package import: < 2s
    - REST API health check: < 50ms

Run with:
    pytest tests/unit_tests/logic/test_performance_baselines.py -v
"""

import time
import pytest


# ---------------------------------------------------------------------------
# CEC Inference Rules Performance
# ---------------------------------------------------------------------------

class TestCECInferenceRulePerformance:
    """Performance baselines for CEC inference rule operations."""

    @pytest.fixture(autouse=True)
    def _import_rules(self):
        """Import rules once per test class."""
        from ipfs_datasets_py.logic.CEC.native.inference_rules import (
            ModusPonens, BiconditionalIntroduction, BiconditionalElimination,
            ResolutionRule, UnitResolutionRule, FactoringRule,
            NecessityElimination, PossibilityIntroduction,
            ConstructiveDilemma, ExportationRule,
        )
        from ipfs_datasets_py.logic.CEC.native.dcec_core import (
            AtomicFormula, ConnectiveFormula, LogicalConnective, Predicate,
        )

        def make_atom(name):
            return AtomicFormula(Predicate(name, []), [])

        self.ModusPonens = ModusPonens
        self.BiconditionalIntroduction = BiconditionalIntroduction
        self.BiconditionalElimination = BiconditionalElimination
        self.ResolutionRule = ResolutionRule
        self.NecessityElimination = NecessityElimination
        self.ConstructiveDilemma = ConstructiveDilemma
        self.ExportationRule = ExportationRule
        self.ConnectiveFormula = ConnectiveFormula
        self.LogicalConnective = LogicalConnective
        self.p = make_atom("P")
        self.q = make_atom("Q")
        self.r = make_atom("R")

    def test_rule_instantiation_under_1ms(self):
        """
        GIVEN 100 rule instantiations
        WHEN timing them
        THEN average should be < 1ms each.
        """
        N = 100
        start = time.perf_counter()
        for _ in range(N):
            _ = self.ModusPonens()
        elapsed = (time.perf_counter() - start) * 1000  # ms
        avg_ms = elapsed / N
        assert avg_ms < 1.0, f"Rule instantiation took {avg_ms:.3f}ms (target: <1ms)"

    def test_can_apply_under_0_5ms(self):
        """
        GIVEN 100 can_apply() calls
        WHEN timing them
        THEN average should be < 0.5ms each.
        """
        rule = self.ModusPonens()
        impl = self.ConnectiveFormula(self.LogicalConnective.IMPLIES, [self.p, self.q])
        formulas = [self.p, impl]

        N = 100
        start = time.perf_counter()
        for _ in range(N):
            rule.can_apply(formulas)
        elapsed = (time.perf_counter() - start) * 1000
        avg_ms = elapsed / N
        assert avg_ms < 0.5, f"can_apply() took {avg_ms:.3f}ms (target: <0.5ms)"

    def test_apply_under_1ms(self):
        """
        GIVEN 100 apply() calls
        WHEN timing them
        THEN average should be < 1ms each.
        """
        rule = self.ModusPonens()
        impl = self.ConnectiveFormula(self.LogicalConnective.IMPLIES, [self.p, self.q])
        formulas = [self.p, impl]

        N = 100
        start = time.perf_counter()
        for _ in range(N):
            rule.apply(formulas)
        elapsed = (time.perf_counter() - start) * 1000
        avg_ms = elapsed / N
        assert avg_ms < 1.0, f"apply() took {avg_ms:.3f}ms (target: <1ms)"

    def test_biconditional_roundtrip_under_2ms(self):
        """
        GIVEN biconditional introduction then elimination
        WHEN timing 100 roundtrips
        THEN average should be < 2ms.
        """
        intro_rule = self.BiconditionalIntroduction()
        elim_rule = self.BiconditionalElimination()
        p_q = self.ConnectiveFormula(self.LogicalConnective.IMPLIES, [self.p, self.q])
        q_p = self.ConnectiveFormula(self.LogicalConnective.IMPLIES, [self.q, self.p])

        N = 100
        start = time.perf_counter()
        for _ in range(N):
            biconds = intro_rule.apply([p_q, q_p])
            if biconds:
                elim_rule.apply(biconds)
        elapsed = (time.perf_counter() - start) * 1000
        avg_ms = elapsed / N
        assert avg_ms < 2.0, f"Biconditional roundtrip took {avg_ms:.3f}ms (target: <2ms)"

    def test_new_modal_rule_instantiation(self):
        """
        GIVEN 100 instantiations of each new modal rule
        WHEN timing them
        THEN all should be < 1ms each.
        """
        from ipfs_datasets_py.logic.CEC.native.inference_rules.modal import (
            NecessityElimination, PossibilityIntroduction,
            NecessityDistribution, PossibilityDuality, NecessityConjunction,
        )
        rules = [
            NecessityElimination, PossibilityIntroduction,
            NecessityDistribution, PossibilityDuality, NecessityConjunction,
        ]
        N = 100
        for RuleClass in rules:
            start = time.perf_counter()
            for _ in range(N):
                _ = RuleClass()
            elapsed = (time.perf_counter() - start) * 1000
            avg_ms = elapsed / N
            assert avg_ms < 1.0, (
                f"{RuleClass.__name__} instantiation took {avg_ms:.3f}ms (target: <1ms)"
            )

    def test_new_resolution_rule_instantiation(self):
        """
        GIVEN 100 instantiations of each new resolution rule
        WHEN timing them
        THEN all should be < 1ms each.
        """
        from ipfs_datasets_py.logic.CEC.native.inference_rules.resolution import (
            ResolutionRule, UnitResolutionRule, FactoringRule,
            SubsumptionRule, CaseAnalysisRule, ProofByContradictionRule,
        )
        rules = [
            ResolutionRule, UnitResolutionRule, FactoringRule,
            SubsumptionRule, CaseAnalysisRule, ProofByContradictionRule,
        ]
        N = 100
        for RuleClass in rules:
            start = time.perf_counter()
            for _ in range(N):
                _ = RuleClass()
            elapsed = (time.perf_counter() - start) * 1000
            avg_ms = elapsed / N
            assert avg_ms < 1.0, (
                f"{RuleClass.__name__} instantiation took {avg_ms:.3f}ms (target: <1ms)"
            )


# ---------------------------------------------------------------------------
# Input Validation Performance
# ---------------------------------------------------------------------------

class TestValidatorPerformance:
    """Performance baselines for input validation."""

    def test_formula_validation_under_0_1ms(self):
        """
        GIVEN 1000 formula string validations
        WHEN timing them
        THEN average should be < 0.1ms each.
        """
        from ipfs_datasets_py.logic.common.validators import validate_formula_string
        formula = "P ∧ Q → R ∨ S ↔ T"

        N = 1000
        start = time.perf_counter()
        for _ in range(N):
            validate_formula_string(formula)
        elapsed = (time.perf_counter() - start) * 1000
        avg_ms = elapsed / N
        assert avg_ms < 0.1, f"Formula validation took {avg_ms:.4f}ms (target: <0.1ms)"

    def test_axiom_list_validation_under_1ms_for_10_axioms(self):
        """
        GIVEN an axiom list of 10 formulas
        WHEN validating 100 times
        THEN average should be < 1ms.
        """
        from ipfs_datasets_py.logic.common.validators import validate_axiom_list
        axioms = ["P → Q", "Q → R", "R → S"] * 3 + ["A", "B"]

        N = 100
        start = time.perf_counter()
        for _ in range(N):
            validate_axiom_list(axioms)
        elapsed = (time.perf_counter() - start) * 1000
        avg_ms = elapsed / N
        assert avg_ms < 1.0, f"Axiom list validation took {avg_ms:.3f}ms (target: <1ms)"

    def test_logic_system_validation_under_0_1ms(self):
        """
        GIVEN 1000 logic system validations
        WHEN timing them
        THEN average should be < 0.1ms each.
        """
        from ipfs_datasets_py.logic.common.validators import validate_logic_system

        N = 1000
        start = time.perf_counter()
        for _ in range(N):
            validate_logic_system("tdfol")
        elapsed = (time.perf_counter() - start) * 1000
        avg_ms = elapsed / N
        assert avg_ms < 0.1, f"Logic validation took {avg_ms:.4f}ms (target: <0.1ms)"


# ---------------------------------------------------------------------------
# Package Import Performance
# ---------------------------------------------------------------------------

class TestImportPerformance:
    """Performance baselines for module imports."""

    def test_inference_rules_package_imports_under_2s(self):
        """
        GIVEN a fresh import of the inference_rules package
        WHEN timing the import
        THEN should complete in < 2s.

        Note: Import caching means this test is primarily useful in fresh environments.
        """
        import importlib
        import sys

        # Remove from cache to force re-import
        modules_to_remove = [
            k for k in sys.modules
            if 'inference_rules' in k
        ]
        for mod in modules_to_remove:
            del sys.modules[mod]

        start = time.perf_counter()
        import ipfs_datasets_py.logic.CEC.native.inference_rules  # noqa: F401
        elapsed = (time.perf_counter() - start) * 1000
        assert elapsed < 2000, f"Package import took {elapsed:.0f}ms (target: <2000ms)"

    def test_validators_import_under_0_5s(self):
        """
        GIVEN importing the validators module
        WHEN timing the import (from cache)
        THEN should be fast.
        """
        start = time.perf_counter()
        from ipfs_datasets_py.logic.common.validators import validate_formula_string  # noqa: F401
        elapsed = (time.perf_counter() - start) * 1000
        # From cache should be near-instant
        assert elapsed < 500, f"Validator import took {elapsed:.0f}ms (target: <500ms)"


# ---------------------------------------------------------------------------
# REST API Performance
# ---------------------------------------------------------------------------

class TestMCPToolPerformance:
    """Performance baselines for MCP logic tool execution."""

    def test_logic_health_tool_under_50ms(self):
        """
        GIVEN the logic_health MCP tool
        WHEN calling it 10 times
        THEN average execution time should be < 50ms.
        """
        import asyncio
        from ipfs_datasets_py.mcp_server.tools.logic_tools.logic_capabilities_tool import (
            LogicHealthTool,
        )
        tool = LogicHealthTool()
        N = 10
        start = time.perf_counter()
        for _ in range(N):
            asyncio.run(tool.execute({}))
        elapsed = (time.perf_counter() - start) * 1000
        avg_ms = elapsed / N
        assert avg_ms < 50, f"logic_health MCP tool took {avg_ms:.1f}ms (target: <50ms)"

    def test_logic_capabilities_tool_under_100ms(self):
        """
        GIVEN the logic_capabilities MCP tool
        WHEN calling it 10 times
        THEN average execution time should be < 100ms.
        """
        import asyncio
        from ipfs_datasets_py.mcp_server.tools.logic_tools.logic_capabilities_tool import (
            LogicCapabilitiesTool,
        )
        tool = LogicCapabilitiesTool()
        N = 10
        start = time.perf_counter()
        for _ in range(N):
            asyncio.run(tool.execute({}))
        elapsed = (time.perf_counter() - start) * 1000
        avg_ms = elapsed / N
        assert avg_ms < 100, f"logic_capabilities MCP tool took {avg_ms:.1f}ms (target: <100ms)"
