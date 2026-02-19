"""
Logic Capabilities and Health MCP Tools.

Exposes logic module discovery and health information through the MCP
(Model Context Protocol) framework.

These tools replace the former FastAPI ``/capabilities`` and ``/health``
REST endpoints (``logic/api_server.py``) with native MCP tools that are
available to AI assistants without running a separate HTTP server.

Tools exposed:
    - ``logic_capabilities`` — List supported logics, conversions, rule counts.
    - ``logic_health``        — Check health/availability of each logic sub-module.

Both tools use ``ClaudeMCPTool`` and register automatically with the
``ToolRegistry``.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from ipfs_datasets_py.mcp_server.tool_registry import ClaudeMCPTool

logger = logging.getLogger(__name__)

TOOL_VERSION = "1.0.0"


# ---------------------------------------------------------------------------
# Module availability helpers
# ---------------------------------------------------------------------------

def _check_tdfol() -> bool:
    """Return True if the TDFOL prover is importable."""
    try:
        from ipfs_datasets_py.logic.TDFOL.tdfol_prover import TDFOLProver  # noqa: F401
        return True
    except ImportError:
        return False


def _check_cec() -> bool:
    """Return True if the CEC native module is importable."""
    try:
        from ipfs_datasets_py.logic.CEC.native.dcec_core import Formula  # noqa: F401
        return True
    except ImportError:
        return False


def _check_cec_inference_rules() -> int:
    """Return count of available CEC inference rules, or 0 on failure."""
    try:
        from ipfs_datasets_py.logic.CEC.native.inference_rules import __all__ as cec_all
        return len([
            n for n in cec_all
            if n not in ("ProofResult", "InferenceRule")
        ])
    except ImportError:
        return 0


def _check_zkp() -> bool:
    """Return True if ZKP module is importable (simulation-only)."""
    try:
        from ipfs_datasets_py.logic.zkp.zkp_prover import ZKPProver  # noqa: F401
        return True
    except ImportError:
        return False


def _check_tdfol_rule_count() -> int:
    """Return count of available TDFOL inference rules, or 0 on failure."""
    try:
        import ipfs_datasets_py.logic.TDFOL.inference_rules as ir
        return len([n for n in dir(ir) if not n.startswith("_") and isinstance(getattr(ir, n), type)])
    except ImportError:
        return 0


def _check_fol() -> bool:
    """Return True if FOL module is importable."""
    try:
        from ipfs_datasets_py.logic.fol import converter  # noqa: F401
        return True
    except ImportError:
        return False


def _check_validators() -> bool:
    """Return True if logic common validators are importable."""
    try:
        from ipfs_datasets_py.logic.common.validators import validate_formula_string  # noqa: F401
        return True
    except ImportError:
        return False


# ---------------------------------------------------------------------------
# Tool: logic_capabilities
# ---------------------------------------------------------------------------

class LogicCapabilitiesTool(ClaudeMCPTool):
    """
    MCP Tool: list all logic module capabilities.

    Returns the set of supported logics, available conversions, inference
    rule counts per system, and optional feature flags.
    """

    def __init__(self) -> None:
        super().__init__()
        self.name = "logic_capabilities"
        self.description = (
            "List available logic module capabilities: supported logics, "
            "conversions, inference rule counts, and feature flags."
        )
        self.category = "logic_tools"
        self.tags = ["logic", "capabilities", "discovery", "info"]
        self.version = TOOL_VERSION

        self.input_schema = {
            "type": "object",
            "properties": {
                "include_rule_counts": {
                    "type": "boolean",
                    "description": "Include per-system inference rule counts.",
                    "default": True,
                },
            },
            "required": [],
        }

    async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        List logic module capabilities.

        Args:
            parameters: Optional ``include_rule_counts`` flag.

        Returns:
            Dict with:
                - ``logics``: list of supported logic systems
                - ``conversions``: list of supported conversion paths
                - ``inference_rules``: dict mapping system → rule count
                - ``features``: list of available features
                - ``version``: tool version string

        Example:
            >>> result = await tool.execute({})
            >>> "tdfol" in result["logics"]
            True
        """
        start = time.monotonic()
        include_counts = parameters.get("include_rule_counts", True)

        rule_counts: Dict[str, int] = {}
        if include_counts:
            rule_counts["cec"] = _check_cec_inference_rules()
            rule_counts["tdfol"] = _check_tdfol_rule_count()

        features: List[str] = []
        if _check_tdfol():
            features += ["theorem_proving", "proof_caching", "modal_tableaux"]
        if _check_cec():
            features += ["cec_inference_rules", "dcec_parsing"]
        if _check_zkp():
            features += ["zkp_simulation"]
        if _check_fol():
            features += ["fol_conversion"]
        if _check_validators():
            features += ["input_validation"]
        # always available
        features += ["natural_language_conversion", "format_conversion"]
        features = sorted(set(features))

        logics: List[str] = ["tdfol", "cec", "fol", "deontic"]
        conversions: List[str] = [
            "tdfol→fol",
            "tdfol→dcec",
            "tdfol→tptp",
            "nl→tdfol",
            "nl→dcec",
        ]

        return {
            "success": True,
            "logics": logics,
            "conversions": conversions,
            "inference_rules": rule_counts,
            "features": features,
            "version": "1.0.0",
            "elapsed_ms": (time.monotonic() - start) * 1000,
            "tool_version": TOOL_VERSION,
        }


# ---------------------------------------------------------------------------
# Tool: logic_health
# ---------------------------------------------------------------------------

class LogicHealthTool(ClaudeMCPTool):
    """
    MCP Tool: check health and availability of logic sub-modules.

    Returns the import status of each logic sub-system so AI assistants
    can determine which capabilities are usable in the current environment.
    """

    def __init__(self) -> None:
        super().__init__()
        self.name = "logic_health"
        self.description = (
            "Check availability and health of logic module sub-systems. "
            "Returns import status for each logic component."
        )
        self.category = "logic_tools"
        self.tags = ["logic", "health", "status", "availability", "diagnostics"]
        self.version = TOOL_VERSION

        self.input_schema = {
            "type": "object",
            "properties": {
                "verbose": {
                    "type": "boolean",
                    "description": "Include detailed import error messages.",
                    "default": False,
                },
            },
            "required": [],
        }

    async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Check logic module health.

        Args:
            parameters: Optional ``verbose`` flag.

        Returns:
            Dict with:
                - ``status``: "healthy" | "degraded" | "unavailable"
                - ``modules``: dict mapping module name → availability bool
                - ``version``: module version string
                - ``uptime_seconds``: time since process start

        Example:
            >>> result = await tool.execute({})
            >>> result["status"] in ("healthy", "degraded", "unavailable")
            True
        """
        import os
        start = time.monotonic()
        verbose = parameters.get("verbose", False)

        modules: Dict[str, Any] = {}
        errors: Dict[str, str] = {}

        # Check each sub-module
        checks = {
            "tdfol": _check_tdfol,
            "cec": _check_cec,
            "fol": _check_fol,
            "zkp": _check_zkp,
            "validators": _check_validators,
        }

        for module_name, check_fn in checks.items():
            try:
                modules[module_name] = check_fn()
            except Exception as exc:
                modules[module_name] = False
                errors[module_name] = str(exc)

        # CEC rule count
        cec_rule_count = _check_cec_inference_rules()
        modules["cec_inference_rules_count"] = cec_rule_count

        # Compute overall status
        core_modules = ["tdfol", "cec"]
        all_core_ok = all(modules.get(m) for m in core_modules)
        any_core_ok = any(modules.get(m) for m in core_modules)

        if all_core_ok:
            status = "healthy"
        elif any_core_ok:
            status = "degraded"
        else:
            status = "unavailable"

        result: Dict[str, Any] = {
            "success": True,
            "status": status,
            "modules": modules,
            "version": "1.0.0",
            "elapsed_ms": (time.monotonic() - start) * 1000,
            "tool_version": TOOL_VERSION,
        }

        if verbose and errors:
            result["errors"] = errors

        return result


# ---------------------------------------------------------------------------
# Tool instances (registered in __init__.py)
# ---------------------------------------------------------------------------

LOGIC_CAPABILITIES_TOOLS = [
    LogicCapabilitiesTool(),
    LogicHealthTool(),
]

__all__ = [
    "TOOL_VERSION",
    "LogicCapabilitiesTool",
    "LogicHealthTool",
    "LOGIC_CAPABILITIES_TOOLS",
]
