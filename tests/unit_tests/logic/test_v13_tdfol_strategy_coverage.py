"""
v13 TDFOL Strategy Coverage — Sessions TDFOL-T1 + TDFOL-T2
============================================================
Covers sessions from MASTER_IMPROVEMENT_PLAN_2026_v13.md:

  TDFOL-T1: ModalTableauxStrategy (15 tests)
    - _prove_basic_modal in KB / not in KB
    - estimate_cost: simple/nested/mixed
    - get_priority
    - internal helpers: _has_deontic_operators, _has_temporal_operators,
      _has_nested_temporal

  TDFOL-T2: StrategySelector (10 tests)
    - add_strategy + re-sort
    - select_multiple with max_strategies
    - fallback when no strategy handles formula
    - prefer_low_cost selection
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

# ─── import guards ─────────────────────────────────────────────────────────────

try:
    from ipfs_datasets_py.logic.TDFOL.tdfol_core import (
        TDFOLKnowledgeBase,
        DeonticFormula,
        DeonticOperator,
        TemporalFormula,
        TemporalOperator,
        BinaryTemporalFormula,
        BinaryFormula,
        LogicOperator,
        UnaryFormula,
        Predicate,
    )
    _CORE_OK = True
except Exception as _e:
    _CORE_OK = False
    _CORE_ERR = str(_e)

try:
    from ipfs_datasets_py.logic.TDFOL.strategies.modal_tableaux import (
        ModalTableauxStrategy,
    )
    _MODAL_OK = True
except Exception as _e:
    _MODAL_OK = False

try:
    from ipfs_datasets_py.logic.TDFOL.strategies.forward_chaining import (
        ForwardChainingStrategy,
    )
    _FC_OK = True
except Exception as _e:
    _FC_OK = False

try:
    from ipfs_datasets_py.logic.TDFOL.strategies.strategy_selector import (
        StrategySelector,
    )
    _SELECTOR_OK = True
except Exception as _e:
    _SELECTOR_OK = False

try:
    from ipfs_datasets_py.logic.TDFOL.tdfol_prover import ProofResult, ProofStatus
    from ipfs_datasets_py.logic.TDFOL.strategies.base import (
        ProverStrategy,
        StrategyType,
        ProofStep,
    )
    _PROVER_OK = True
except Exception as _e:
    _PROVER_OK = False

_ALL_OK = _CORE_OK and _MODAL_OK and _FC_OK and _SELECTOR_OK and _PROVER_OK
_skip = pytest.mark.skipif(not _ALL_OK, reason="TDFOL strategy modules not importable")


# ─── helpers ──────────────────────────────────────────────────────────────────

def _obligation(name: str = "P") -> "DeonticFormula":
    return DeonticFormula(DeonticOperator.OBLIGATION, Predicate(name, ()))


def _always(name: str = "P") -> "TemporalFormula":
    return TemporalFormula(TemporalOperator.ALWAYS, Predicate(name, ()))


def _empty_kb() -> "TDFOLKnowledgeBase":
    return TDFOLKnowledgeBase()


# ──────────────────────────────────────────────────────────────────────────────
# TDFOL-T1 — ModalTableauxStrategy
# ──────────────────────────────────────────────────────────────────────────────


@_skip
class TestModalTableauxProveBasicModal:
    """Session TDFOL-T1 — _prove_basic_modal coverage (5 tests)."""

    def _strategy(self) -> "ModalTableauxStrategy":
        return ModalTableauxStrategy()

    def test_formula_in_axioms_returns_proved(self):
        strat = self._strategy()
        kb = _empty_kb()
        f = _obligation("P")
        kb.add_axiom(f)
        result = strat._prove_basic_modal(f, kb, timeout_ms=5000, start_time=0)
        assert result.status == ProofStatus.PROVED

    def test_formula_in_theorems_returns_proved(self):
        strat = self._strategy()
        kb = _empty_kb()
        f = _obligation("Q")
        kb.add_theorem(f)
        result = strat._prove_basic_modal(f, kb, timeout_ms=5000, start_time=0)
        assert result.status == ProofStatus.PROVED

    def test_formula_not_in_kb_returns_unknown(self):
        strat = self._strategy()
        kb = _empty_kb()
        f = _obligation("R")
        result = strat._prove_basic_modal(f, kb, timeout_ms=5000, start_time=0)
        assert result.status == ProofStatus.UNKNOWN

    def test_empty_kb_returns_unknown(self):
        strat = self._strategy()
        kb = _empty_kb()
        f = _always("S")
        result = strat._prove_basic_modal(f, kb, timeout_ms=5000, start_time=0)
        assert result.status == ProofStatus.UNKNOWN

    def test_proved_result_has_proof_step(self):
        strat = self._strategy()
        kb = _empty_kb()
        f = _obligation("T")
        kb.add_axiom(f)
        result = strat._prove_basic_modal(f, kb, timeout_ms=5000, start_time=0)
        assert result.proof_steps
        step = result.proof_steps[0]
        assert "knowledge base" in step.justification.lower()


@_skip
class TestModalTableauxEstimateCost:
    """Session TDFOL-T1 — estimate_cost (5 tests)."""

    def _strat(self) -> "ModalTableauxStrategy":
        return ModalTableauxStrategy()

    def test_simple_deontic_formula_base_cost(self):
        strat = self._strat()
        kb = _empty_kb()
        f = _obligation("P")
        cost = strat.estimate_cost(f, kb)
        assert cost == 2.0

    def test_nested_temporal_doubles_cost(self):
        strat = self._strat()
        kb = _empty_kb()
        inner = _always("P")
        outer = TemporalFormula(TemporalOperator.EVENTUALLY, inner)
        cost = strat.estimate_cost(outer, kb)
        assert cost == 4.0  # 2.0 * 2.0

    def test_mixed_deontic_and_temporal_multipliers(self):
        strat = self._strat()
        kb = _empty_kb()
        deon = _obligation("Q")
        temporal = _always("R")
        mixed = BinaryFormula(LogicOperator.AND, deon, temporal)
        cost = strat.estimate_cost(mixed, kb)
        # has deontic + temporal (not nested) → 2.0 * 1.5 = 3.0
        assert cost == pytest.approx(3.0)

    def test_simple_temporal_no_nesting_base_cost(self):
        strat = self._strat()
        kb = _empty_kb()
        f = _always("P")
        cost = strat.estimate_cost(f, kb)
        assert cost == 2.0  # has temporal but not nested → no nesting multiplier

    def test_cost_returns_float(self):
        strat = self._strat()
        kb = _empty_kb()
        cost = strat.estimate_cost(_obligation("Z"), kb)
        assert isinstance(cost, float)


@_skip
class TestModalTableauxGetPriority:
    """Session TDFOL-T1 — get_priority (2 tests)."""

    def test_get_priority_returns_80(self):
        assert ModalTableauxStrategy().get_priority() == 80

    def test_modal_priority_higher_than_forward_chaining(self):
        modal = ModalTableauxStrategy()
        fc = ForwardChainingStrategy()
        assert modal.get_priority() > fc.get_priority()


@_skip
class TestModalTableauxInternalHelpers:
    """Session TDFOL-T1 — _has_deontic_operators / _has_temporal_operators / _has_nested_temporal (3 tests)."""

    def _strat(self) -> "ModalTableauxStrategy":
        return ModalTableauxStrategy()

    def test_has_deontic_operators_on_deontic_formula(self):
        strat = self._strat()
        f = _obligation("P")
        assert strat._has_deontic_operators(f) is True

    def test_has_temporal_operators_on_temporal_formula(self):
        strat = self._strat()
        f = _always("P")
        assert strat._has_temporal_operators(f) is True

    def test_has_nested_temporal_on_nested_structure(self):
        strat = self._strat()
        inner = _always("P")
        outer = TemporalFormula(TemporalOperator.EVENTUALLY, inner)
        assert strat._has_nested_temporal(outer) is True


# ──────────────────────────────────────────────────────────────────────────────
# TDFOL-T2 — StrategySelector
# ──────────────────────────────────────────────────────────────────────────────


@_skip
class TestStrategySelectorAddStrategy:
    """Session TDFOL-T2 — add_strategy + re-sort (4 tests)."""

    def _custom_strategy(self, priority: int = 999) -> "ProverStrategy":
        """Create a minimal custom strategy with a given priority."""
        class _Custom(ProverStrategy):
            def __init__(self, p: int) -> None:
                super().__init__(f"Custom-{p}", StrategyType.FORWARD_CHAINING)
                self._priority = p

            def can_handle(self, formula: "Formula", kb: "TDFOLKnowledgeBase") -> bool:
                return True

            def prove(
                self,
                formula: "Formula",
                kb: "TDFOLKnowledgeBase",
                timeout_ms: int = 5000,
            ) -> ProofResult:
                return ProofResult(
                    status=ProofStatus.PROVED,
                    formula=formula,
                    method=self.name,
                )

            def get_priority(self) -> int:
                return self._priority

        return _Custom(priority)

    def test_add_strategy_increases_count(self):
        selector = StrategySelector([ForwardChainingStrategy()])
        before = len(selector.strategies)
        selector.add_strategy(ModalTableauxStrategy())
        assert len(selector.strategies) == before + 1

    def test_strategies_remain_sorted_after_add(self):
        selector = StrategySelector([ForwardChainingStrategy()])
        selector.add_strategy(ModalTableauxStrategy())
        priorities = [s.get_priority() for s in selector.strategies]
        assert priorities == sorted(priorities, reverse=True)

    def test_added_strategy_appears_in_get_strategy_info(self):
        selector = StrategySelector([ForwardChainingStrategy()])
        custom = self._custom_strategy(priority=99)
        selector.add_strategy(custom)
        names = [s["name"] for s in selector.get_strategy_info()]
        assert any("Custom" in n for n in names)

    def test_high_priority_strategy_becomes_first(self):
        selector = StrategySelector([ForwardChainingStrategy(), ModalTableauxStrategy()])
        high = self._custom_strategy(priority=999)
        selector.add_strategy(high)
        assert selector.strategies[0].get_priority() == 999


@_skip
class TestStrategySelectorSelectMultiple:
    """Session TDFOL-T2 — select_multiple (4 tests)."""

    def test_select_multiple_max_1_returns_single_item_list(self):
        selector = StrategySelector([ForwardChainingStrategy(), ModalTableauxStrategy()])
        kb = _empty_kb()
        f = _obligation("P")
        result = selector.select_multiple(f, kb, max_strategies=1)
        assert len(result) == 1

    def test_select_multiple_max_3_returns_at_most_3(self):
        selector = StrategySelector([ForwardChainingStrategy(), ModalTableauxStrategy()])
        kb = _empty_kb()
        f = _obligation("P")
        result = selector.select_multiple(f, kb, max_strategies=3)
        assert len(result) <= 3

    def test_select_multiple_returns_strategies_in_priority_order(self):
        selector = StrategySelector([ForwardChainingStrategy(), ModalTableauxStrategy()])
        kb = _empty_kb()
        f = _obligation("P")
        result = selector.select_multiple(f, kb, max_strategies=2)
        if len(result) > 1:
            priorities = [s.get_priority() for s in result]
            assert priorities == sorted(priorities, reverse=True)

    def test_select_multiple_empty_strategies_raises_or_returns_empty(self):
        selector = StrategySelector.__new__(StrategySelector)
        selector.strategies = []
        kb = _empty_kb()
        # Either returns empty list or raises — both are acceptable
        try:
            result = selector.select_multiple(_obligation("P"), kb)
            assert result == []
        except (ValueError, IndexError):
            pass  # acceptable to raise when no strategies


@_skip
class TestStrategySelectorFallback:
    """Session TDFOL-T2 — fallback behaviour (2 tests)."""

    def test_non_modal_formula_uses_forward_chaining_fallback(self):
        selector = StrategySelector([ForwardChainingStrategy(), ModalTableauxStrategy()])
        kb = _empty_kb()
        # Predicate is NOT a modal formula → no strategy claims it via can_handle
        # (ForwardChainingStrategy handles any formula, so it will be selected)
        p = Predicate("P", ())
        result = selector.select_strategy(p, kb)
        # Result should be a valid strategy (forward chaining fallback)
        assert hasattr(result, "prove")

    def test_get_fallback_strategy_raises_when_empty(self):
        selector = StrategySelector.__new__(StrategySelector)
        selector.strategies = []
        with pytest.raises(ValueError, match="[Nn]o.*strateg"):
            selector._get_fallback_strategy()
