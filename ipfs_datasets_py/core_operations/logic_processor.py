"""
Logic Processor — core business logic for all logic operations.

This module provides the :class:`LogicProcessor` class that implements
the business logic for TDFOL, CEC/DCEC, and ZKP operations.  It is the
**single source of truth** used by:

- ``mcp_server/tools/logic_tools/*.py``  — thin async wrapper functions
- ``ipfs_datasets_cli.py``               — CLI tool discovery (via the wrappers)
- Direct Python imports                  — ``from ipfs_datasets_py.core_operations import LogicProcessor``

Usage::

    from ipfs_datasets_py.core_operations import LogicProcessor

    lp = LogicProcessor()
    result = await lp.prove_tdfol("∀x.P(x) → P(a)", axioms=["∀x.P(x)"])
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

TOOL_VERSION = "1.0.0"

# ---------------------------------------------------------------------------
# Supported constants (shared across parse / validate helpers)
# ---------------------------------------------------------------------------

_SUPPORTED_NL_LANGUAGES = ["en", "es", "fr", "de", "auto"]
_SUPPORTED_TARGET_FORMATS = ["tptp", "json", "dcec", "smt2", "fol"]
_SUPPORTED_TDFOL_STRATEGIES = ["auto", "forward", "backward", "modal_tableaux", "hybrid"]
_SUPPORTED_DCEC_STRATEGIES = ["auto", "z3", "vampire", "e_prover"]


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _get_cec_rule_registry() -> Optional[Dict[str, Any]]:
    """Build a name→rule-instance mapping from the CEC inference rules package."""
    try:
        import ipfs_datasets_py.logic.CEC.native.inference_rules as ir_pkg

        rule_registry: Dict[str, Any] = {}
        for name in getattr(ir_pkg, "__all__", []):
            obj = getattr(ir_pkg, name, None)
            if obj is None:
                continue
            try:
                from ipfs_datasets_py.logic.CEC.native.inference_rules.base import InferenceRule
                if (
                    isinstance(obj, type)
                    and issubclass(obj, InferenceRule)
                    and obj is not InferenceRule
                ):
                    try:
                        rule_registry[name] = obj()
                    except Exception:
                        pass
            except ImportError:
                if isinstance(obj, type) and (
                    hasattr(obj, "apply") or hasattr(obj, "can_apply")
                ):
                    try:
                        rule_registry[name] = obj()
                    except Exception:
                        pass
        return rule_registry
    except ImportError:
        return None


def _cec_parse_formula(formula_str: str) -> Any:
    """Parse a formula string into a minimal CEC formula object."""
    try:
        from ipfs_datasets_py.logic.CEC.native.dcec_core import AtomicFormula, Predicate
        return AtomicFormula(Predicate(formula_str.strip(), []), [])
    except ImportError:
        return formula_str


def _cec_formula_to_str(formula: Any) -> str:
    return str(formula)


def _nl_to_dcec(text: str, language: str) -> Dict[str, Any]:
    """Convert natural language text to a DCEC formula string."""
    try:
        from ipfs_datasets_py.logic.CEC.native.dcec_nlp import DCECNLConverter
        converter = DCECNLConverter()
        result = converter.convert(text, language=language)
        return {
            "formula": str(result.formula),
            "confidence": getattr(result, "confidence", 0.75),
            "language_used": language,
        }
    except ImportError:
        pass
    except Exception as exc:
        logger.debug("DCECNLConverter failed: %s", exc)

    safe = text.replace('"', "'").strip()
    return {"formula": f'NL("{safe}")', "confidence": 0.3, "language_used": language}


def _try_dcec_prove(goal: str, axioms: List[str], strategy: str, timeout: int) -> Dict[str, Any]:
    """Attempt to prove a DCEC goal; falls back gracefully."""
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
        return {
            "proved": False,
            "prover_used": "unavailable",
            "proof_steps": 0,
            "execution_time": 0.0,
            "note": "CEC prover stack not installed (optional dependency).",
        }
    except Exception as exc:
        logger.warning("DCEC prover error for goal=%r: %s", goal, exc)
        return {
            "proved": False,
            "prover_used": "error",
            "proof_steps": 0,
            "execution_time": 0.0,
            "error": str(exc),
        }


def _structural_analysis(formula_str: str) -> Dict[str, Any]:
    """Compute structural metrics for a formula string."""
    try:
        from ipfs_datasets_py.logic.CEC.native import parse_dcec_string

        formula_obj = parse_dcec_string(formula_str)

        def _depth(f: Any) -> int:
            children = getattr(f, "subformulas", []) or []
            return 1 + max((_depth(c) for c in children), default=0)

        def _size(f: Any) -> int:
            children = getattr(f, "subformulas", []) or []
            return 1 + sum(_size(c) for c in children)

        def _operators(f: Any) -> List[str]:
            ops: List[str] = []
            if hasattr(f, "operator"):
                ops.append(str(f.operator))
            for c in getattr(f, "subformulas", []) or []:
                ops.extend(_operators(c))
            return ops

        return {
            "depth": _depth(formula_obj),
            "size": _size(formula_obj),
            "operators": list(set(_operators(formula_obj))),
            "parsed_ok": True,
        }
    except Exception:
        pass

    # Text-level fallback
    text = formula_str
    depth = max(min(text.count("("), text.count(")")), 1)
    size = len(text.split())
    ops = [c for c in ["∧", "∨", "→", "↔", "¬", "∀", "∃", "O", "P", "F"] if c in text]
    return {"depth": depth, "size": size, "operators": ops, "parsed_ok": False}


def _check_module_available(import_path: str) -> bool:
    """Return True if ``import_path`` can be imported."""
    import importlib
    try:
        importlib.import_module(import_path)
        return True
    except ImportError:
        return False


def _count_cec_rules() -> int:
    registry = _get_cec_rule_registry()
    return len(registry) if registry else 0


def _count_tdfol_rules() -> int:
    try:
        from ipfs_datasets_py.logic.TDFOL import inference_rules as tdfol_ir
        return len(getattr(tdfol_ir, "__all__", []))
    except ImportError:
        return 60  # documented default


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class LogicProcessor:
    """
    Core business logic for logic module operations.

    All methods are ``async`` for consistency with the rest of the
    ``core_operations`` layer.  Pure computation methods are synchronous
    internally but wrapped in async signatures for the caller.

    Methods are grouped by sub-system:

    CEC / DCEC
        :meth:`list_cec_rules`, :meth:`apply_cec_rule`,
        :meth:`check_cec_rule`, :meth:`get_cec_rule_info`,
        :meth:`prove_dcec`, :meth:`check_dcec_theorem`,
        :meth:`parse_dcec`, :meth:`validate_formula`,
        :meth:`analyze_formula`, :meth:`get_formula_complexity`

    TDFOL
        :meth:`prove_tdfol`, :meth:`batch_prove_tdfol`,
        :meth:`parse_tdfol`, :meth:`convert_formula`,
        :meth:`manage_kb`, :meth:`visualize_proof`

    Discovery
        :meth:`get_capabilities`, :meth:`check_health`

    GraphRAG
        :meth:`build_knowledge_graph`, :meth:`verify_rag_output`
    """

    def __init__(self) -> None:
        self.logger = logging.getLogger(__name__ + ".LogicProcessor")

    # ------------------------------------------------------------------
    # CEC / DCEC — inference rules
    # ------------------------------------------------------------------

    async def list_cec_rules(
        self,
        category: str = "",
        include_description: bool = True,
    ) -> Dict[str, Any]:
        """List available CEC inference rules, optionally filtered by category."""
        start = time.monotonic()
        registry = _get_cec_rule_registry()
        if registry is None:
            return {
                "success": False,
                "error": "CEC inference rules module not available.",
                "rules": [],
                "total": 0,
            }

        _KNOWN_CATEGORIES = {
            "propositional", "temporal", "deontic", "cognitive",
            "modal", "resolution", "specialized",
        }
        category_filter = category.lower()
        rules_list = []
        for name, instance in registry.items():
            module_name = type(instance).__module__.split(".")[-1]
            cat = module_name if module_name in _KNOWN_CATEGORIES else "other"
            if category_filter and cat != category_filter:
                continue
            entry: Dict[str, Any] = {"name": name, "category": cat}
            if include_description:
                entry["description"] = (
                    (type(instance).__doc__ or "").strip().split("\n")[0]
                )
            rules_list.append(entry)
        rules_list.sort(key=lambda r: (r["category"], r["name"]))
        return {
            "success": True,
            "rules": rules_list,
            "total": len(rules_list),
            "elapsed_ms": (time.monotonic() - start) * 1000,
        }

    async def apply_cec_rule(
        self,
        rule_name: str,
        formulas: List[str],
    ) -> Dict[str, Any]:
        """Apply a named CEC inference rule to a list of formula strings."""
        start = time.monotonic()
        registry = _get_cec_rule_registry()
        if registry is None:
            return {"success": False, "error": "CEC module not available.", "applicable": False}
        rule_instance = registry.get(rule_name)
        if rule_instance is None:
            return {
                "success": False,
                "error": f"Rule '{rule_name}' not found.",
                "applicable": False,
                "available": sorted(registry.keys())[:20],
            }
        try:
            parsed = [_cec_parse_formula(f) for f in formulas]
        except Exception as exc:
            return {"success": False, "error": f"Formula parse error: {exc}", "applicable": False}
        try:
            applicable = bool(rule_instance.can_apply(parsed))
        except Exception:
            applicable = False
        conclusions: List[str] = []
        if applicable:
            try:
                result = rule_instance.apply(parsed)
                if result is not None:
                    conclusions = (
                        [_cec_formula_to_str(f) for f in result if f is not None]
                        if isinstance(result, list)
                        else [_cec_formula_to_str(result)]
                    )
            except Exception as exc:
                logger.warning("Rule application error for %s: %s", rule_name, exc)
        return {
            "success": True,
            "rule": rule_name,
            "applicable": applicable,
            "conclusions": conclusions,
            "input_formulas": formulas,
            "elapsed_ms": (time.monotonic() - start) * 1000,
        }

    async def check_cec_rule(
        self,
        rule_name: str,
        formulas: List[str],
    ) -> Dict[str, Any]:
        """Check whether a CEC rule can be applied without applying it."""
        start = time.monotonic()
        registry = _get_cec_rule_registry()
        if registry is None:
            return {"success": False, "error": "CEC module not available.", "applicable": False}
        rule_instance = registry.get(rule_name)
        if rule_instance is None:
            return {"success": False, "error": f"Rule '{rule_name}' not found.", "applicable": False}
        try:
            parsed = [_cec_parse_formula(f) for f in formulas]
            applicable = bool(rule_instance.can_apply(parsed))
        except Exception:
            applicable = False
        return {
            "success": True,
            "rule": rule_name,
            "applicable": applicable,
            "elapsed_ms": (time.monotonic() - start) * 1000,
        }

    async def get_cec_rule_info(self, rule_name: str) -> Dict[str, Any]:
        """Return documentation and metadata for a named CEC inference rule."""
        start = time.monotonic()
        registry = _get_cec_rule_registry()
        if registry is None:
            return {"success": False, "error": "CEC module not available."}
        instance = registry.get(rule_name)
        if instance is None:
            return {
                "success": False,
                "error": f"Rule '{rule_name}' not found.",
                "available_rules": sorted(registry.keys()),
            }
        cls = type(instance)
        methods = [
            m for m in ("can_apply", "apply", "get_name", "get_description")
            if callable(getattr(instance, m, None))
        ]
        return {
            "success": True,
            "name": rule_name,
            "category": cls.__module__.split(".")[-1],
            "module": cls.__module__,
            "docstring": (cls.__doc__ or "").strip(),
            "methods": methods,
            "elapsed_ms": (time.monotonic() - start) * 1000,
        }

    # ------------------------------------------------------------------
    # CEC / DCEC — proving and parsing
    # ------------------------------------------------------------------

    async def prove_dcec(
        self,
        goal: str,
        axioms: Optional[List[str]] = None,
        strategy: str = "auto",
        timeout: int = 30,
    ) -> Dict[str, Any]:
        """Prove a DCEC theorem."""
        start = time.monotonic()
        axioms = axioms or []
        prover_result = _try_dcec_prove(goal, axioms, strategy, timeout)
        prover_result["success"] = "error" not in prover_result
        prover_result["elapsed_ms"] = (time.monotonic() - start) * 1000
        return prover_result

    async def check_dcec_theorem(
        self,
        formula: str,
        axioms: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Check whether a DCEC formula is a tautology."""
        start = time.monotonic()
        axioms = axioms or []
        prover_result = _try_dcec_prove(formula, axioms, "auto", 30)
        return {
            "success": "error" not in prover_result,
            "is_theorem": prover_result.get("proved", False),
            "elapsed_ms": (time.monotonic() - start) * 1000,
        }

    async def parse_dcec(
        self,
        text: str,
        language: str = "en",
    ) -> Dict[str, Any]:
        """Parse natural language text into a DCEC formula."""
        start = time.monotonic()
        if not text or len(text) > 4096:
            return {
                "success": False,
                "error": "'text' must be non-empty and ≤ 4096 characters.",
                "formula": None,
            }
        lang = language if language in _SUPPORTED_NL_LANGUAGES else "en"
        result = _nl_to_dcec(text, lang if lang != "auto" else "en")
        result["success"] = True
        result["elapsed_ms"] = (time.monotonic() - start) * 1000
        return result

    async def validate_formula(
        self,
        formula_str: str,
        logic_system: str = "dcec",
    ) -> Dict[str, Any]:
        """Validate a formula for syntactic correctness."""
        start = time.monotonic()
        if not formula_str:
            return {"success": False, "valid": False, "errors": ["Formula must be non-empty."], "warnings": []}

        errors: List[str] = []
        warnings: List[str] = []

        # Generic injection check
        try:
            from ipfs_datasets_py.logic.common.validators import validate_formula_string
            validate_formula_string(formula_str)
        except Exception as exc:
            return {
                "success": True,
                "valid": False,
                "errors": [str(exc)],
                "warnings": [],
                "elapsed_ms": (time.monotonic() - start) * 1000,
            }

        # Logic-system–specific check
        if logic_system in ("dcec", "cec"):
            try:
                from ipfs_datasets_py.logic.CEC.native import validate_formula as _cv
                is_valid, errs = _cv(formula_str)
                if errs:
                    errors.extend(errs if isinstance(errs, list) else [str(errs)])
            except ImportError:
                warnings.append("CEC native validator not available; basic check only.")
                is_valid = True
            except Exception as exc:
                errors.append(str(exc))
                is_valid = False
        else:
            is_valid = True  # No validator for other systems yet

        return {
            "success": True,
            "valid": is_valid and not errors,
            "errors": errors,
            "warnings": warnings,
            "elapsed_ms": (time.monotonic() - start) * 1000,
        }

    async def analyze_formula(self, formula_str: str) -> Dict[str, Any]:
        """Return structural analysis of a formula string."""
        start = time.monotonic()
        if not formula_str:
            return {"success": False, "error": "Formula must be non-empty."}
        analysis = _structural_analysis(formula_str)
        analysis["success"] = True
        analysis["formula"] = formula_str
        analysis["elapsed_ms"] = (time.monotonic() - start) * 1000
        return analysis

    async def get_formula_complexity(self, formula_str: str) -> Dict[str, Any]:
        """Return a low/medium/high complexity classification for a formula."""
        start = time.monotonic()
        if not formula_str:
            return {"success": False, "error": "Formula must be non-empty."}
        a = _structural_analysis(formula_str)
        depth = a.get("depth", 1)
        size = a.get("size", 1)
        if depth <= 2 and size <= 5:
            level = "low"
        elif depth <= 5 and size <= 20:
            level = "medium"
        else:
            level = "high"
        return {
            "success": True,
            "formula": formula_str,
            "complexity": level,
            "depth": depth,
            "size": size,
            "elapsed_ms": (time.monotonic() - start) * 1000,
        }

    # ------------------------------------------------------------------
    # TDFOL — proving
    # ------------------------------------------------------------------

    async def prove_tdfol(
        self,
        formula: str,
        axioms: Optional[List[str]] = None,
        strategy: str = "auto",
        timeout_ms: int = 5000,
        max_depth: int = 10,
        include_proof_steps: bool = True,
    ) -> Dict[str, Any]:
        """Prove a TDFOL formula."""
        start = time.monotonic()
        axioms = axioms or []
        try:
            from ipfs_datasets_py.logic.TDFOL.tdfol_parser import parse_tdfol_safe
            from ipfs_datasets_py.logic.TDFOL.tdfol_prover import TDFOLProver
            from ipfs_datasets_py.logic.TDFOL.tdfol_core import TDFOLKnowledgeBase

            parsed_formula = parse_tdfol_safe(formula)
            if parsed_formula is None:
                return {
                    "success": False,
                    "error": "Failed to parse formula",
                    "formula": formula,
                    "elapsed_ms": (time.monotonic() - start) * 1000,
                }

            kb = TDFOLKnowledgeBase()
            for axiom_str in axioms:
                axiom = parse_tdfol_safe(axiom_str)
                if axiom:
                    kb.add_axiom(axiom)

            prover = TDFOLProver(kb)
            proof_result = prover.prove(parsed_formula, timeout_ms=timeout_ms)

            result: Dict[str, Any] = {
                "success": True,
                "proved": proof_result.is_proved(),
                "status": proof_result.status.value,
                "formula": formula,
                "method": proof_result.method,
                "elapsed_ms": (time.monotonic() - start) * 1000,
                "from_cache": getattr(proof_result, "from_cache", False),
            }
            if include_proof_steps and getattr(proof_result, "proof_steps", None):
                result["proof_steps"] = [
                    {
                        "formula": str(step.formula),
                        "justification": step.justification,
                        "rule_name": step.rule_name,
                    }
                    for step in proof_result.proof_steps
                ]
            return result

        except ImportError:
            return {
                "success": False,
                "error": "TDFOL prover module not available",
                "formula": formula,
                "elapsed_ms": (time.monotonic() - start) * 1000,
            }
        except Exception as exc:
            return {
                "success": False,
                "error": str(exc),
                "formula": formula,
                "elapsed_ms": (time.monotonic() - start) * 1000,
            }

    async def batch_prove_tdfol(
        self,
        formulas: List[str],
        shared_axioms: Optional[List[str]] = None,
        strategy: str = "auto",
        timeout_per_formula_ms: int = 5000,
        stop_on_first_failure: bool = False,
    ) -> Dict[str, Any]:
        """Prove multiple TDFOL formulas sequentially."""
        start = time.monotonic()
        shared_axioms = shared_axioms or []
        results = []
        total_proved = 0
        total_failed = 0
        for formula in formulas:
            r = await self.prove_tdfol(
                formula, axioms=shared_axioms,
                strategy=strategy, timeout_ms=timeout_per_formula_ms,
                include_proof_steps=False,
            )
            results.append(r)
            if r.get("proved"):
                total_proved += 1
            else:
                total_failed += 1
                if stop_on_first_failure:
                    break
        return {
            "success": True,
            "results": results,
            "total_formulas": len(formulas),
            "total_proved": total_proved,
            "total_failed": total_failed,
            "elapsed_ms": (time.monotonic() - start) * 1000,
        }

    # ------------------------------------------------------------------
    # TDFOL — parsing and conversion
    # ------------------------------------------------------------------

    async def parse_tdfol(
        self,
        text: str,
        format: str = "symbolic",
        language: str = "en",
    ) -> Dict[str, Any]:
        """Parse text into a TDFOL formula."""
        start = time.monotonic()
        if not text:
            return {"success": False, "error": "Input text must be non-empty."}
        try:
            if format in ("symbolic", "json"):
                from ipfs_datasets_py.logic.TDFOL.tdfol_parser import parse_tdfol_safe
                parsed = parse_tdfol_safe(text)
                if parsed is None:
                    return {"success": False, "error": "Failed to parse formula."}
                return {
                    "success": True,
                    "formula": str(parsed),
                    "format": format,
                    "elapsed_ms": (time.monotonic() - start) * 1000,
                }
            else:  # natural language
                from ipfs_datasets_py.logic.TDFOL.nl.llm_nl_converter import TDFOLNLConverter
                converter = TDFOLNLConverter()
                result = converter.convert(text)
                return {
                    "success": True,
                    "formula": str(result.formula) if result else f"NL({text!r})",
                    "format": "natural_language",
                    "language": language,
                    "elapsed_ms": (time.monotonic() - start) * 1000,
                }
        except ImportError as exc:
            return {"success": False, "error": f"Parser not available: {exc}"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    async def convert_formula(
        self,
        formula: str,
        source_format: str = "tdfol",
        target_format: str = "fol",
    ) -> Dict[str, Any]:
        """Convert a formula between logic representations."""
        start = time.monotonic()
        if not formula:
            return {"success": False, "error": "Formula must be non-empty."}
        try:
            from ipfs_datasets_py.logic.TDFOL.tdfol_converter import TDFOLConverter
            converter = TDFOLConverter()
            result = converter.convert(formula, source=source_format, target=target_format)
            return {
                "success": True,
                "formula": formula,
                "source_format": source_format,
                "target_format": target_format,
                "converted": str(result),
                "elapsed_ms": (time.monotonic() - start) * 1000,
            }
        except ImportError:
            # Lightweight stub conversion
            note = f"[{source_format.upper()}→{target_format.upper()}] {formula}"
            return {
                "success": True,
                "formula": formula,
                "source_format": source_format,
                "target_format": target_format,
                "converted": note,
                "note": "Converter not available; stub output returned.",
                "elapsed_ms": (time.monotonic() - start) * 1000,
            }
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    # ------------------------------------------------------------------
    # TDFOL — knowledge base management
    # ------------------------------------------------------------------

    async def manage_kb(
        self,
        operation: str,
        formula: Optional[str] = None,
        axioms: Optional[List[str]] = None,
        export_format: str = "json",
    ) -> Dict[str, Any]:
        """Perform a knowledge base operation (add_axiom, add_theorem, query, export)."""
        start = time.monotonic()
        try:
            from ipfs_datasets_py.logic.TDFOL.tdfol_core import TDFOLKnowledgeBase
            from ipfs_datasets_py.logic.TDFOL.tdfol_parser import parse_tdfol_safe

            kb = TDFOLKnowledgeBase()

            if operation == "add_axiom":
                if not formula:
                    return {"success": False, "error": "Formula required for add_axiom."}
                parsed = parse_tdfol_safe(formula)
                if parsed is None:
                    return {"success": False, "error": "Failed to parse axiom."}
                kb.add_axiom(parsed)
                return {"success": True, "operation": operation, "formula": formula,
                        "elapsed_ms": (time.monotonic() - start) * 1000}

            if operation == "add_theorem":
                if not formula:
                    return {"success": False, "error": "Formula required for add_theorem."}
                parsed = parse_tdfol_safe(formula)
                if parsed is None:
                    return {"success": False, "error": "Failed to parse theorem."}
                kb.add_theorem(parsed)
                return {"success": True, "operation": operation, "formula": formula,
                        "elapsed_ms": (time.monotonic() - start) * 1000}

            if operation == "query":
                stats = kb.get_statistics() if hasattr(kb, "get_statistics") else {}
                return {"success": True, "operation": operation, "stats": stats,
                        "elapsed_ms": (time.monotonic() - start) * 1000}

            if operation == "export":
                exported = kb.export(format=export_format) if hasattr(kb, "export") else {}
                return {"success": True, "operation": operation, "data": exported,
                        "format": export_format,
                        "elapsed_ms": (time.monotonic() - start) * 1000}

            return {"success": False, "error": f"Unknown operation: {operation}"}

        except ImportError as exc:
            return {"success": False, "error": f"TDFOL modules not available: {exc}"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    # ------------------------------------------------------------------
    # TDFOL — visualization
    # ------------------------------------------------------------------

    async def visualize_proof(
        self,
        proof_data: Optional[Dict[str, Any]] = None,
        output_format: str = "ascii",
        visualization_type: str = "proof_tree",
    ) -> Dict[str, Any]:
        """Visualize a proof tree, countermodel, or formula dependency graph."""
        start = time.monotonic()
        try:
            if visualization_type == "proof_tree":
                from ipfs_datasets_py.logic.TDFOL.visualization.proof_tree_visualizer import (
                    ProofTreeVisualizer,
                )
                viz = ProofTreeVisualizer()
                output = viz.visualize(proof_data or {}, format=output_format)
            elif visualization_type == "countermodel":
                from ipfs_datasets_py.logic.TDFOL.visualization.countermodel_visualizer import (
                    CountermodelVisualizer,
                )
                viz = CountermodelVisualizer()
                output = viz.visualize(proof_data or {}, format=output_format)
            elif visualization_type == "dependency":
                from ipfs_datasets_py.logic.TDFOL.visualization.formula_dependency_graph import (
                    FormulaDependencyGraph,
                )
                fdg = FormulaDependencyGraph()
                output = fdg.build(proof_data or {})
            else:
                output = str(proof_data)
            return {
                "success": True,
                "visualization": output,
                "format": output_format,
                "type": visualization_type,
                "elapsed_ms": (time.monotonic() - start) * 1000,
            }
        except ImportError:
            # ASCII stub
            return {
                "success": True,
                "visualization": f"[{visualization_type}]\n{proof_data}",
                "format": "ascii",
                "type": visualization_type,
                "note": "Visualization modules not available; stub output returned.",
                "elapsed_ms": (time.monotonic() - start) * 1000,
            }
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    async def get_capabilities(self) -> Dict[str, Any]:
        """Return capabilities of all logic sub-modules."""
        start = time.monotonic()
        cec_rules = _count_cec_rules()
        tdfol_rules = _count_tdfol_rules()
        return {
            "success": True,
            "logics": {
                "tdfol": {
                    "name": "Temporal Deontic First-Order Logic",
                    "available": _check_module_available("ipfs_datasets_py.logic.TDFOL.tdfol_prover"),
                    "inference_rules": tdfol_rules,
                    "features": ["prove", "parse", "convert", "visualize", "knowledge_base"],
                },
                "cec": {
                    "name": "Cognitive Event Calculus (DCEC)",
                    "available": _check_module_available("ipfs_datasets_py.logic.CEC.native.dcec_core"),
                    "inference_rules": cec_rules,
                    "features": ["prove", "parse", "validate", "analyze", "inference_rules"],
                },
                "fol": {
                    "name": "First-Order Logic",
                    "available": _check_module_available("ipfs_datasets_py.logic.fol"),
                    "features": ["convert_from_tdfol"],
                },
                "zkp": {
                    "name": "Zero-Knowledge Proofs",
                    "available": _check_module_available("ipfs_datasets_py.logic.zkp"),
                    "features": ["prove", "verify"],
                },
            },
            "conversions": ["tdfol→fol", "tdfol→tptp", "tdfol→smt2", "tdfol↔dcec", "nl→tdfol", "nl→dcec"],
            "nl_languages": _SUPPORTED_NL_LANGUAGES,
            "elapsed_ms": (time.monotonic() - start) * 1000,
        }

    async def check_health(self) -> Dict[str, Any]:
        """Check health/availability of all logic sub-modules."""
        start = time.monotonic()
        modules = {
            "tdfol": "ipfs_datasets_py.logic.TDFOL.tdfol_prover",
            "cec": "ipfs_datasets_py.logic.CEC.native.dcec_core",
            "cec_inference_rules": "ipfs_datasets_py.logic.CEC.native.inference_rules",
            "fol": "ipfs_datasets_py.logic.fol",
            "zkp": "ipfs_datasets_py.logic.zkp",
            "validators": "ipfs_datasets_py.logic.common.validators",
        }
        statuses = {name: _check_module_available(path) for name, path in modules.items()}
        healthy = sum(statuses.values())
        total = len(statuses)
        return {
            "success": True,
            "status": "healthy" if healthy == total else ("degraded" if healthy > 0 else "unavailable"),
            "modules": {name: ("ok" if ok else "unavailable") for name, ok in statuses.items()},
            "healthy": healthy,
            "total": total,
            "elapsed_ms": (time.monotonic() - start) * 1000,
        }

    # ------------------------------------------------------------------
    # GraphRAG integration
    # ------------------------------------------------------------------

    async def build_knowledge_graph(
        self,
        text_corpus: str,
        include_temporal: bool = True,
        include_deontic: bool = True,
        max_entities: int = 100,
    ) -> Dict[str, Any]:
        """Extract logical entities from text and build an annotated knowledge graph."""
        start = time.monotonic()
        if not text_corpus or len(text_corpus) > 1_000_000:
            return {"success": False, "error": "text_corpus must be non-empty and ≤ 1,000,000 characters."}

        entities: List[Dict[str, str]] = []
        edges: List[Dict[str, str]] = []

        # Try TDFOL NL converter first
        try:
            from ipfs_datasets_py.logic.TDFOL.nl.llm_nl_converter import TDFOLNLConverter
            converter = TDFOLNLConverter()
            result = converter.convert(text_corpus[:4096])
            if result and hasattr(result, "entities"):
                for ent in result.entities:
                    entities.append({
                        "name": str(ent.name),
                        "type": str(ent.entity_type),
                        "source_text": text_corpus[:100],
                    })
        except Exception:
            pass

        # Heuristic fallback
        if not entities:
            patterns = {
                "temporal": ["before", "after", "during", "always", "eventually"],
                "deontic": ["must", "shall", "may", "prohibited", "required", "permitted"],
                "agent": ["the party", "the agent", "the principal", "the authority"],
            }
            words = text_corpus.lower().split()
            for i, word in enumerate(words[:max_entities]):
                for ent_type, markers in patterns.items():
                    if word in markers:
                        context = " ".join(words[max(0, i - 2):i + 3])
                        entities.append({"name": context, "type": ent_type, "source_text": context})
                        break

        entities = entities[:max_entities]
        if len(entities) > 1:
            edges = [{"from": entities[i]["name"], "to": entities[i + 1]["name"], "relation": "precedes"}
                     for i in range(len(entities) - 1)]

        return {
            "success": True,
            "nodes": entities,
            "edges": edges,
            "node_count": len(entities),
            "edge_count": len(edges),
            "include_temporal": include_temporal,
            "include_deontic": include_deontic,
            "elapsed_ms": (time.monotonic() - start) * 1000,
        }

    async def verify_rag_output(
        self,
        answer: str,
        constraints: Optional[List[str]] = None,
        logic_system: str = "tdfol",
        strict_mode: bool = False,
    ) -> Dict[str, Any]:
        """Verify that a RAG-generated answer is consistent with logical constraints."""
        start = time.monotonic()
        constraints = constraints or []
        if not answer:
            return {"success": False, "error": "answer must be non-empty."}
        if len(constraints) > 50:
            return {"success": False, "error": "Max 50 constraints allowed."}

        violations: List[Dict[str, Any]] = []
        verified: List[str] = []

        for constraint in constraints:
            result = await self.prove_tdfol(
                formula=f"({answer}) → ({constraint})",
                axioms=[answer],
                strategy="auto",
                timeout_ms=5000,
                include_proof_steps=False,
            )
            if result.get("proved"):
                verified.append(constraint)
            else:
                violations.append({"constraint": constraint, "reason": result.get("error", "Not provable")})

        total = len(constraints)
        is_consistent = len(violations) == 0 or (not strict_mode and len(violations) < total)

        return {
            "success": True,
            "consistent": is_consistent,
            "verified_count": len(verified),
            "violation_count": len(violations),
            "violations": violations,
            "total_constraints": total,
            "logic_system": logic_system,
            "strict_mode": strict_mode,
            "elapsed_ms": (time.monotonic() - start) * 1000,
        }
