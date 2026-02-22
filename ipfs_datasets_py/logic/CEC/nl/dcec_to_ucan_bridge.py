"""
DCEC-to-UCAN Bridge: DCEC DeonticFormulas → UCAN Capability / DelegationToken

This module maps parsed DCEC formulas (produced by the CEC NL pipeline) to
UCAN delegation primitives (Profile C from the MCP++ specification).

Mapping rules
-------------
- ``DeonticOperator.OBLIGATION / OBLIGATORY``  → Capability with ability
  ``"<action>/execute"`` — the actor *must* do X, so the system must
  grant them the capability.
- ``DeonticOperator.PERMISSION``               → Capability with ability
  ``"<action>/read"`` (permissive read-like capability).
- ``DeonticOperator.PROHIBITION``              → *no* Capability emitted;
  a ``DenyCapability`` marker dataclass is returned instead so callers can
  insert explicit deny rules.
- Other deontic operators                      → Capability with ability
  ``"<action>/invoke"`` (default).

The bridge also provides :func:`build_delegation_from_nl` which chains
NL compilation + UCAN token assembly in one call.

No external dependencies.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ── marker for prohibited capabilities ───────────────────────────────────────

@dataclass
class DenyCapability:
    """Represents an *explicit denial* derived from a PROHIBITION formula."""
    resource: str
    ability: str
    actor: Optional[str] = None
    reason: Optional[str] = None


# ── capability builder ────────────────────────────────────────────────────────

def _ability_for_operator(op_name: str, action: str) -> Tuple[str, str]:
    """Return ``(ability, resource)`` for a deontic operator name and action."""
    OBLIGATION_OPS = {"OBLIGATION", "OBLIGATORY", "RIGHT", "LIBERTY", "POWER", "IMMUNITY"}
    PERMISSION_OPS = {"PERMISSION", "PERMITTED", "SUPEREROGATION"}
    PROHIBITION_OPS = {"PROHIBITION", "FORBIDDEN"}

    resource = f"logic/{action}"
    if op_name in OBLIGATION_OPS:
        return f"{action}/execute", resource
    elif op_name in PERMISSION_OPS:
        return f"{action}/invoke", resource
    elif op_name in PROHIBITION_OPS:
        return f"{action}/deny", resource
    else:
        return f"{action}/invoke", resource


def _extract_actor_from_formula(formula) -> Optional[str]:
    """Extract actor string from a DCEC formula."""
    try:
        from ipfs_datasets_py.logic.CEC.native.dcec_core import AtomicFormula
    except ImportError:
        return None
    inner = getattr(formula, "formula", formula)
    if isinstance(inner, AtomicFormula):
        args = getattr(inner, "arguments", [])
        if args:
            var = getattr(args[0], "variable", None)
            if var is not None:
                return str(getattr(var, "name", var)).split(":")[0]
    return None


def _extract_action_from_formula(formula) -> str:
    """Extract action/predicate name from a DCEC formula."""
    try:
        from ipfs_datasets_py.logic.CEC.native.dcec_core import AtomicFormula
    except ImportError:
        return "unknown"
    inner = getattr(formula, "formula", formula)
    if isinstance(inner, AtomicFormula):
        pred = getattr(inner, "predicate", None)
        if pred is not None:
            name = getattr(pred, "name", None)
            if name:
                return str(name)
    return "unknown"


# ── core bridge class ─────────────────────────────────────────────────────────

@dataclass
class DCECToUCANMapping:
    """Result of mapping a single DCEC formula to UCAN primitives."""
    formula: Any  # original DCEC formula
    capability: Any = None    # Capability | DenyCapability | None
    actor: Optional[str] = None
    action: Optional[str] = None
    operator: Optional[str] = None
    error: Optional[str] = None


class DCECToUCANBridge:
    """
    Convert DCEC formulas to UCAN ``Capability`` objects.

    Parameters
    ----------
    issuer_did:
        DID of the delegating entity (root of chain).  Defaults to
        ``"did:key:root"``.
    expiry_offset:
        Seconds from *now* until the generated tokens expire.
        If *None* the tokens do not expire.

    Example
    -------
    >>> from ipfs_datasets_py.logic.CEC.native.nl_converter import NaturalLanguageConverter
    >>> conv = NaturalLanguageConverter()
    >>> result = conv.convert_to_dcec("Alice may read files")
    >>> bridge = DCECToUCANBridge(issuer_did="did:key:root")
    >>> mapping = bridge.map_formula(result.dcec_formula)
    >>> mapping.capability.ability
    'read/invoke'
    """

    def __init__(
        self,
        issuer_did: str = "did:key:root",
        expiry_offset: Optional[float] = None,
    ) -> None:
        self.issuer_did = issuer_did
        self.expiry_offset = expiry_offset

    def _get_ucan_types(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import (
            Capability, DelegationToken, DelegationChain, DelegationEvaluator
        )
        return Capability, DelegationToken, DelegationChain, DelegationEvaluator

    def map_formula(self, formula) -> DCECToUCANMapping:
        """Map a single DCEC *formula* to a UCAN Capability or DenyCapability."""
        try:
            from ipfs_datasets_py.logic.CEC.native.dcec_core import DeonticFormula
        except ImportError as exc:
            return DCECToUCANMapping(formula=formula, error=f"Import error: {exc}")

        if not isinstance(formula, DeonticFormula):
            return DCECToUCANMapping(
                formula=formula,
                error=f"Not a DeonticFormula: {type(formula).__name__}",
            )

        op_name = formula.operator.name if hasattr(formula.operator, "name") else str(formula.operator)
        actor = _extract_actor_from_formula(formula)
        action = _extract_action_from_formula(formula)
        ability, resource = _ability_for_operator(op_name, action)

        if op_name in {"PROHIBITION", "FORBIDDEN"}:
            cap = DenyCapability(resource=resource, ability=ability, actor=actor)
        else:
            Capability, *_ = self._get_ucan_types()
            cap = Capability(resource=resource, ability=ability)

        return DCECToUCANMapping(
            formula=formula,
            capability=cap,
            actor=actor,
            action=action,
            operator=op_name,
        )

    def build_delegation_token(
        self,
        mapping: DCECToUCANMapping,
        audience_did: Optional[str] = None,
        proof_cid: Optional[str] = None,
    ):
        """
        Build a :class:`DelegationToken` for a successful *mapping*.

        If the mapping contains a :class:`DenyCapability`, returns *None*
        (denials are recorded in the policy, not as positive delegations).
        """
        if mapping.error or mapping.capability is None:
            return None
        if isinstance(mapping.capability, DenyCapability):
            return None

        Capability, DelegationToken, *_ = self._get_ucan_types()

        audience = audience_did or (
            f"did:key:{mapping.actor}" if mapping.actor else "did:key:anonymous"
        )
        expiry = (
            time.time() + self.expiry_offset
            if self.expiry_offset is not None
            else None
        )
        return DelegationToken(
            issuer=self.issuer_did,
            audience=audience,
            capabilities=[mapping.capability],
            expiry=expiry,
            proof_cid=proof_cid,
        )

    def map_formulas(
        self,
        formulas: List[Any],
        audience_did: Optional[str] = None,
    ) -> "BridgeResult":
        """
        Map a list of DCEC formulas to UCAN tokens.

        Returns a :class:`BridgeResult` containing all produced tokens,
        deny-capabilities, and any errors.
        """
        result = BridgeResult()
        for f in formulas:
            mapping = self.map_formula(f)
            result.mappings.append(mapping)
            if mapping.error:
                result.errors.append(mapping.error)
                continue
            if isinstance(mapping.capability, DenyCapability):
                result.denials.append(mapping.capability)
                continue
            token = self.build_delegation_token(mapping, audience_did=audience_did)
            if token is not None:
                result.tokens.append(token)
        result.success = bool(result.tokens or result.denials)
        return result


@dataclass
class BridgeResult:
    """Result of bridging a set of DCEC formulas to UCAN tokens."""
    tokens: List[Any] = field(default_factory=list)    # List[DelegationToken]
    denials: List[DenyCapability] = field(default_factory=list)
    mappings: List[DCECToUCANMapping] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    success: bool = False

    def build_chain(self):
        """Return a :class:`DelegationChain` from all non-deny tokens."""
        if not self.tokens:
            return None
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationChain
        return DelegationChain(self.tokens)
