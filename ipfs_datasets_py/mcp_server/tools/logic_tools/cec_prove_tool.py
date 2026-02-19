"""
CEC Prove Tool — Theorem proving for DCEC formulas via MCP.

Exposes two MCP tools:

    - ``cec_prove``          — Prove a DCEC theorem given a goal and optional axioms.
    - ``cec_check_theorem``  — Quickly check whether a formula is a tautology.

These replace the former ``prove_dcec`` and ``check_theorem`` plain functions
(originally registered through the legacy ``TOOLS`` dict) with proper
``ClaudeMCPTool`` subclasses that integrate directly with the ToolRegistry.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from ipfs_datasets_py.mcp_server.tool_registry import ClaudeMCPTool

logger = logging.getLogger(__name__)

TOOL_VERSION = "1.0.0"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _try_prove(goal: str, axioms: List[str], strategy: str, timeout: int) -> Dict[str, Any]:
    """
    Attempt to prove *goal* using the CEC prover stack.

    Falls back gracefully when optional prover dependencies are missing.
    """
    try:
        from ipfs_datasets_py.logic.CEC.provers import ProverManager, ProverStrategy
        from ipfs_datasets_py.logic.CEC.native import parse_dcec_string

        goal_formula = parse_dcec_string(goal)
        axiom_formulas = [parse_dcec_string(a) for a in axioms]

        strategy_map = {
            "auto": ProverStrategy.AUTO,
            "z3": ProverStrategy.Z3,
            "vampire": ProverStrategy.VAMPIRE,
            "e_prover": ProverStrategy.E_PROVER,
        }
        prover_strategy = strategy_map.get(strategy, ProverStrategy.AUTO)

        manager = ProverManager()
        result = manager.prove(
            formula=goal_formula,
            axioms=axiom_formulas,
            strategy=prover_strategy,
            timeout=timeout,
        )
        return {
            "proved": result.success,
            "prover_used": result.prover_name,
            "proof_steps": result.steps,
            "execution_time": result.time_taken,
        }
    except ImportError:
        # Prover stack not available — return inconclusive
        return {
            "proved": False,
            "prover_used": "unavailable",
            "proof_steps": 0,
            "execution_time": 0.0,
            "note": "CEC prover stack not installed (optional dependency).",
        }
    except Exception as exc:
        logger.warning("Prover error for goal=%r: %s", goal, exc)
        return {
            "proved": False,
            "prover_used": "error",
            "proof_steps": 0,
            "execution_time": 0.0,
            "error": str(exc),
        }


# ---------------------------------------------------------------------------
# Tool: cec_prove
# ---------------------------------------------------------------------------

class CECProveTool(ClaudeMCPTool):
    """
    MCP Tool: prove a DCEC theorem given a goal and optional axioms.

    Attempts proof using the CEC prover stack (Z3, Vampire, or E-Prover).
    Returns gracefully when the optional prover dependencies are not installed.
    """

    def __init__(self) -> None:
        super().__init__()
        self.name = "cec_prove"
        self.description = (
            "Prove a DCEC (Deontic Cognitive Event Calculus) theorem given a goal "
            "formula and optional axioms. Returns proof status, prover used, and "
            "step count."
        )
        self.category = "logic_tools"
        self.tags = ["logic", "cec", "dcec", "prove", "theorem", "prover"]
        self.version = TOOL_VERSION

        self.input_schema = {
            "type": "object",
            "properties": {
                "goal": {
                    "type": "string",
                    "description": "Goal formula to prove (DCEC notation).",
                },
                "axioms": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional axiom formulas.",
                    "default": [],
                    "maxItems": 50,
                },
                "strategy": {
                    "type": "string",
                    "description": "Proving strategy.",
                    "enum": ["auto", "z3", "vampire", "e_prover"],
                    "default": "auto",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds (1–300).",
                    "default": 30,
                    "minimum": 1,
                    "maximum": 300,
                },
            },
            "required": ["goal"],
        }

    async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Prove a DCEC formula.

        Args:
            parameters: ``goal``, optional ``axioms``, ``strategy``, ``timeout``.

        Returns:
            Dict with ``proved`` bool, ``prover_used``, ``proof_steps``,
            ``execution_time``, and timing.

        Example:
            >>> result = await tool.execute({"goal": "P(x) -> P(x)"})
            >>> isinstance(result["proved"], bool)
            True
        """
        from ipfs_datasets_py.logic.common.validators import (
            validate_formula_string, validate_axiom_list,
        )
        start = time.monotonic()

        goal = parameters.get("goal", "")
        axioms: List[str] = parameters.get("axioms", [])
        strategy: str = parameters.get("strategy", "auto")
        timeout: int = int(parameters.get("timeout", 30))

        # Validate inputs
        try:
            validate_formula_string(goal)
            validate_axiom_list(axioms)
        except Exception as exc:
            return {"success": False, "error": str(exc), "proved": False}

        prover_result = _try_prove(goal, axioms, strategy, timeout)
        prover_result["success"] = "error" not in prover_result
        prover_result["elapsed_ms"] = (time.monotonic() - start) * 1000
        prover_result["tool_version"] = TOOL_VERSION
        return prover_result


# ---------------------------------------------------------------------------
# Tool: cec_check_theorem
# ---------------------------------------------------------------------------

class CECCheckTheoremTool(ClaudeMCPTool):
    """
    MCP Tool: quickly check whether a DCEC formula is a tautology.

    A lighter-weight alternative to ``cec_prove`` when only a boolean
    is needed (no proof steps or prover metadata required).
    """

    def __init__(self) -> None:
        super().__init__()
        self.name = "cec_check_theorem"
        self.description = (
            "Check whether a DCEC formula is a tautology (theorem). "
            "Returns a boolean result without detailed proof metadata."
        )
        self.category = "logic_tools"
        self.tags = ["logic", "cec", "dcec", "theorem", "tautology", "check"]
        self.version = TOOL_VERSION

        self.input_schema = {
            "type": "object",
            "properties": {
                "formula": {
                    "type": "string",
                    "description": "Formula to check.",
                },
                "axioms": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional axioms to assume.",
                    "default": [],
                    "maxItems": 50,
                },
            },
            "required": ["formula"],
        }

    async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Check if formula is a theorem.

        Args:
            parameters: ``formula`` and optional ``axioms``.

        Returns:
            Dict with ``is_theorem`` bool, optional ``counterexample``, and timing.

        Example:
            >>> result = await tool.execute({"formula": "P(x) | ~P(x)"})
            >>> isinstance(result["is_theorem"], bool)
            True
        """
        from ipfs_datasets_py.logic.common.validators import validate_formula_string
        start = time.monotonic()

        formula: str = parameters.get("formula", "")
        axioms: List[str] = parameters.get("axioms", [])

        try:
            validate_formula_string(formula)
        except Exception as exc:
            return {"success": False, "error": str(exc), "is_theorem": False}

        prover_result = _try_prove(formula, axioms, "auto", 30)
        is_theorem = prover_result.get("proved", False)

        return {
            "success": "error" not in prover_result,
            "is_theorem": is_theorem,
            "counterexample": None,  # Extended in future when prover supports it
            "elapsed_ms": (time.monotonic() - start) * 1000,
            "tool_version": TOOL_VERSION,
        }


# ---------------------------------------------------------------------------
# Tool instances (registered in __init__.py)
# ---------------------------------------------------------------------------

CEC_PROVE_TOOLS = [
    CECProveTool(),
    CECCheckTheoremTool(),
]

__all__ = [
    "TOOL_VERSION",
    "CECProveTool",
    "CECCheckTheoremTool",
    "CEC_PROVE_TOOLS",
]
