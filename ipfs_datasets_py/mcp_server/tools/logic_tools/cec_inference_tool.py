"""
CEC Inference Rule MCP Tool.

Exposes the CEC (Cognitive Event Calculus) native inference rules — including
the modal, resolution, and specialized modules — through the MCP (Model Context
Protocol) framework.

Tools exposed:
    - ``cec_list_rules``   — List available inference rules with metadata.
    - ``cec_apply_rule``   — Apply a single named inference rule to a set of formulas.
    - ``cec_check_rule``   — Check whether a rule can be applied (without applying it).
    - ``cec_rule_info``    — Return full documentation for a named rule.

All tools use ``ClaudeMCPTool`` so they register automatically with the
``ToolRegistry`` and are visible to AI assistants through the MCP server.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from ipfs_datasets_py.mcp_server.tool_registry import ClaudeMCPTool

logger = logging.getLogger(__name__)

TOOL_VERSION = "1.0.0"

# ---------------------------------------------------------------------------
# Helpers — lazy-load the inference rules package
# ---------------------------------------------------------------------------

def _get_rule_registry() -> Optional[Dict[str, Any]]:
    """
    Build a name→rule-class mapping from the CEC inference rules package.

    Returns:
        Dict mapping rule class names to their instances, or None on import failure.
    """
    try:
        import ipfs_datasets_py.logic.CEC.native.inference_rules as ir_pkg

        rule_registry: Dict[str, Any] = {}
        for name in getattr(ir_pkg, "__all__", []):
            obj = getattr(ir_pkg, name, None)
            if obj is None:
                continue
            # Only include concrete rule classes (not base classes or non-classes)
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
                        pass  # Skip rules that fail to instantiate
            except ImportError:
                # If base module not available, just check for execute/apply methods
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


def _parse_formula(formula_str: str) -> Any:
    """
    Parse a formula string into a CEC formula object.

    Note: This is a minimal parser that only supports atomic formulas
    (simple predicate names). Complex formulas with connectives (∧, ∨, →)
    or quantifiers (∀, ∃) are treated as atomic predicates. For full formula
    parsing, use the tdfol_parse or cec_parse MCP tools before applying rules.
    """
    from ipfs_datasets_py.logic.CEC.native.dcec_core import (
        AtomicFormula, Predicate,
    )
    # Minimal parser: treat bare strings as atomic formula predicates
    return AtomicFormula(Predicate(formula_str.strip(), []), [])


def _formula_to_str(formula: Any) -> str:
    """Convert a formula object back to string."""
    return str(formula)


# ---------------------------------------------------------------------------
# Tool: cec_list_rules
# ---------------------------------------------------------------------------

class CECListRulesTool(ClaudeMCPTool):
    """
    MCP Tool: list available CEC inference rules.

    Returns all inference rules available in the CEC native module, grouped
    by category (propositional, temporal, deontic, cognitive, modal,
    resolution, specialized).
    """

    def __init__(self) -> None:
        super().__init__()
        self.name = "cec_list_rules"
        self.description = (
            "List all available CEC (Cognitive Event Calculus) inference rules, "
            "optionally filtered by category."
        )
        self.category = "logic_tools"
        self.tags = ["logic", "cec", "inference", "rules", "discovery"]
        self.version = TOOL_VERSION

        self.input_schema = {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": (
                        "Filter rules by category: propositional, temporal, deontic, "
                        "cognitive, modal, resolution, specialized. Omit for all rules."
                    ),
                    "enum": [
                        "propositional", "temporal", "deontic", "cognitive",
                        "modal", "resolution", "specialized",
                    ],
                },
                "include_description": {
                    "type": "boolean",
                    "description": "Include rule docstrings in the response.",
                    "default": True,
                },
            },
            "required": [],
        }

    async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        List available CEC inference rules.

        Args:
            parameters: Optional ``category`` filter and ``include_description`` flag.

        Returns:
            Dict with ``rules`` list (name, category, description), ``total`` count.

        Example:
            >>> result = await tool.execute({"category": "modal"})
            >>> [r["name"] for r in result["rules"]]
            ['NecessityElimination', 'PossibilityIntroduction', ...]
        """
        start = time.monotonic()
        category_filter = parameters.get("category", "").lower()
        include_desc = parameters.get("include_description", True)

        registry = _get_rule_registry()
        if registry is None:
            return {
                "success": False,
                "error": "CEC inference rules module not available. Check installation.",
                "rules": [],
                "total": 0,
            }

        # Build per-module category map
        _CATEGORY_MODULES: Dict[str, str] = {
            "propositional": "propositional",
            "temporal": "temporal",
            "deontic": "deontic",
            "cognitive": "cognitive",
            "modal": "modal",
            "resolution": "resolution",
            "specialized": "specialized",
        }

        rules_list = []
        for name, instance in registry.items():
            module_name = type(instance).__module__.split(".")[-1]  # e.g. "modal"
            cat = module_name if module_name in _CATEGORY_MODULES else "other"

            if category_filter and cat != category_filter:
                continue

            entry: Dict[str, Any] = {"name": name, "category": cat}
            if include_desc:
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
            "tool_version": TOOL_VERSION,
        }


# ---------------------------------------------------------------------------
# Tool: cec_apply_rule
# ---------------------------------------------------------------------------

class CECApplyRuleTool(ClaudeMCPTool):
    """
    MCP Tool: apply a named CEC inference rule to a set of formulas.

    Given a rule name and a list of input formula strings, attempts to apply
    the rule and returns the derived formulas.
    """

    def __init__(self) -> None:
        super().__init__()
        self.name = "cec_apply_rule"
        self.description = (
            "Apply a named CEC inference rule to a set of formula strings. "
            "Returns the derived conclusions. "
            "Note: accepts atomic predicate names as formula strings; "
            "use tdfol_parse or cec_parse for complex formulas first."
        )
        self.category = "logic_tools"
        self.tags = ["logic", "cec", "inference", "apply", "derive"]
        self.version = TOOL_VERSION

        self.input_schema = {
            "type": "object",
            "properties": {
                "rule": {
                    "type": "string",
                    "description": "Name of the inference rule to apply (e.g. 'ModusPonens').",
                },
                "formulas": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of input formula strings.",
                    "minItems": 1,
                    "maxItems": 20,
                },
            },
            "required": ["rule", "formulas"],
        }

    async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Apply a CEC inference rule.

        Args:
            parameters: ``rule`` (str) and ``formulas`` (list[str]).

        Returns:
            Dict with ``conclusions`` (list of derived formula strings),
            ``applicable`` bool, and timing.

        Example:
            >>> result = await tool.execute({
            ...     "rule": "ModusPonens",
            ...     "formulas": ["P", "P_IMPLIES_Q"],
            ... })
            >>> result["applicable"]
            True
        """
        from ipfs_datasets_py.logic.common.validators import (
            validate_formula_string, validate_axiom_list,
        )
        start = time.monotonic()

        rule_name = parameters.get("rule", "")
        formula_strs = parameters.get("formulas", [])

        # Input validation
        try:
            if not rule_name or not isinstance(rule_name, str):
                return {
                    "success": False,
                    "error": "'rule' must be a non-empty string.",
                    "applicable": False,
                }
            validate_axiom_list(formula_strs)
        except Exception as exc:
            return {"success": False, "error": str(exc), "applicable": False}

        registry = _get_rule_registry()
        if registry is None:
            return {
                "success": False,
                "error": "CEC inference rules module not available.",
                "applicable": False,
            }

        rule_instance = registry.get(rule_name)
        if rule_instance is None:
            available = sorted(registry.keys())
            return {
                "success": False,
                "error": f"Rule '{rule_name}' not found. Available: {available[:20]}...",
                "applicable": False,
            }

        # Parse formulas
        try:
            parsed_formulas = [_parse_formula(f) for f in formula_strs]
        except Exception as exc:
            return {
                "success": False,
                "error": f"Formula parsing failed: {exc}",
                "applicable": False,
            }

        # Check applicability
        try:
            applicable = bool(rule_instance.can_apply(parsed_formulas))
        except Exception as exc:
            applicable = False
            logger.debug("can_apply raised: %s", exc)

        # Apply the rule
        conclusions: List[str] = []
        if applicable:
            try:
                result = rule_instance.apply(parsed_formulas)
                if result is not None:
                    if isinstance(result, list):
                        conclusions = [_formula_to_str(f) for f in result if f is not None]
                    else:
                        conclusions = [_formula_to_str(result)]
            except Exception as exc:
                logger.warning("Rule application error for %s: %s", rule_name, exc)

        return {
            "success": True,
            "rule": rule_name,
            "applicable": applicable,
            "conclusions": conclusions,
            "input_formulas": formula_strs,
            "elapsed_ms": (time.monotonic() - start) * 1000,
            "tool_version": TOOL_VERSION,
        }


# ---------------------------------------------------------------------------
# Tool: cec_check_rule
# ---------------------------------------------------------------------------

class CECCheckRuleTool(ClaudeMCPTool):
    """
    MCP Tool: check whether a CEC inference rule can be applied.

    Like ``cec_apply_rule`` but performs only the applicability check
    without deriving conclusions. Useful for large formula sets where
    derivation cost is undesirable.
    """

    def __init__(self) -> None:
        super().__init__()
        self.name = "cec_check_rule"
        self.description = (
            "Check whether a named CEC inference rule can be applied to a set of "
            "formula strings, without actually applying it."
        )
        self.category = "logic_tools"
        self.tags = ["logic", "cec", "inference", "check", "applicability"]
        self.version = TOOL_VERSION

        self.input_schema = {
            "type": "object",
            "properties": {
                "rule": {
                    "type": "string",
                    "description": "Name of the inference rule to check.",
                },
                "formulas": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of formula strings to check against.",
                    "minItems": 1,
                    "maxItems": 20,
                },
            },
            "required": ["rule", "formulas"],
        }

    async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Check rule applicability.

        Args:
            parameters: ``rule`` (str) and ``formulas`` (list[str]).

        Returns:
            Dict with ``applicable`` bool and timing.
        """
        start = time.monotonic()

        rule_name = parameters.get("rule", "")
        formula_strs = parameters.get("formulas", [])

        if not rule_name or not isinstance(rule_name, str):
            return {"success": False, "error": "'rule' must be a non-empty string.", "applicable": False}

        registry = _get_rule_registry()
        if registry is None:
            return {"success": False, "error": "CEC module not available.", "applicable": False}

        rule_instance = registry.get(rule_name)
        if rule_instance is None:
            return {
                "success": False,
                "error": f"Rule '{rule_name}' not found.",
                "applicable": False,
            }

        try:
            parsed_formulas = [_parse_formula(f) for f in formula_strs]
            applicable = bool(rule_instance.can_apply(parsed_formulas))
        except Exception as exc:
            applicable = False
            logger.debug("can_apply raised: %s", exc)

        return {
            "success": True,
            "rule": rule_name,
            "applicable": applicable,
            "elapsed_ms": (time.monotonic() - start) * 1000,
            "tool_version": TOOL_VERSION,
        }


# ---------------------------------------------------------------------------
# Tool: cec_rule_info
# ---------------------------------------------------------------------------

class CECRuleInfoTool(ClaudeMCPTool):
    """
    MCP Tool: return full documentation for a named CEC inference rule.

    Provides the rule's docstring, module, category, and method signatures.
    """

    def __init__(self) -> None:
        super().__init__()
        self.name = "cec_rule_info"
        self.description = (
            "Return documentation and metadata for a named CEC inference rule."
        )
        self.category = "logic_tools"
        self.tags = ["logic", "cec", "inference", "documentation", "info"]
        self.version = TOOL_VERSION

        self.input_schema = {
            "type": "object",
            "properties": {
                "rule": {
                    "type": "string",
                    "description": "Name of the CEC inference rule.",
                },
            },
            "required": ["rule"],
        }

    async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Get rule documentation.

        Args:
            parameters: ``rule`` (str) name.

        Returns:
            Dict with ``name``, ``category``, ``module``, ``docstring``, ``methods``.
        """
        start = time.monotonic()
        rule_name = parameters.get("rule", "")

        if not rule_name:
            return {"success": False, "error": "'rule' is required."}

        registry = _get_rule_registry()
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
        module_name = cls.__module__.split(".")[-1]

        methods: List[str] = []
        for method in ("can_apply", "apply", "get_name", "get_description"):
            if hasattr(instance, method) and callable(getattr(instance, method)):
                methods.append(method)

        return {
            "success": True,
            "name": rule_name,
            "category": module_name,
            "module": cls.__module__,
            "docstring": (cls.__doc__ or "").strip(),
            "methods": methods,
            "elapsed_ms": (time.monotonic() - start) * 1000,
            "tool_version": TOOL_VERSION,
        }


# ---------------------------------------------------------------------------
# Tool instances (registered in __init__.py)
# ---------------------------------------------------------------------------

CEC_INFERENCE_TOOLS = [
    CECListRulesTool(),
    CECApplyRuleTool(),
    CECCheckRuleTool(),
    CECRuleInfoTool(),
]

__all__ = [
    "TOOL_VERSION",
    "CECListRulesTool",
    "CECApplyRuleTool",
    "CECCheckRuleTool",
    "CECRuleInfoTool",
    "CEC_INFERENCE_TOOLS",
]
