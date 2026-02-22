"""
NL-to-Policy Compiler: Natural Language → DCEC Formulas → PolicyClauses

This module bridges the CEC natural language layer and the MCP server's
temporal policy system, allowing natural language text to be compiled into
rigorous ``PolicyClause`` / ``PolicyObject`` structures.

Pipeline::

    NL text
      │
      ▼  NaturalLanguageConverter  (logic/CEC/native/nl_converter.py)
    DCEC formula (DeonticFormula / CognitiveFormula / …)
      │
      ▼  _dcec_formula_to_clause()
    PolicyClause  (mcp_server/temporal_policy.py)
      │
      ▼  NLToDCECCompiler.compile()
    PolicyObject  (tagged with provenance metadata)

Supported deontic mappings
--------------------------
- OBLIGATION / OBLIGATORY  → clause_type="obligation"  (actor *must* do X)
- PERMISSION               → clause_type="permission"
- PROHIBITION              → clause_type="prohibition"
- SUPEREROGATION           → clause_type="permission"   (going beyond duty)
- RIGHT / LIBERTY / POWER / IMMUNITY → clause_type="permission"

Agent extraction
----------------
The first VariableTerm of the inner AtomicFormula is treated as the actor.
The predicate name is used as the action.

No external dependencies beyond stdlib + sibling logic modules.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── lazy imports so this module stays import-quiet ───────────────────────────
def _get_nl_converter():
    from ..native.nl_converter import NaturalLanguageConverter, ConversionResult
    return NaturalLanguageConverter, ConversionResult


def _get_dcec_types():
    from ..native.dcec_core import (
        DeonticFormula, DeonticOperator,
        CognitiveFormula, AtomicFormula, ConnectiveFormula,
        TemporalFormula,
    )
    return (
        DeonticFormula, DeonticOperator,
        CognitiveFormula, AtomicFormula, ConnectiveFormula,
        TemporalFormula,
    )


def _get_policy_types():
    from ipfs_datasets_py.mcp_server.temporal_policy import (
        PolicyClause, PolicyObject, PolicyEvaluator,
    )
    return PolicyClause, PolicyObject, PolicyEvaluator


# ── deontic → clause type mapping ────────────────────────────────────────────
_OBLIGATION_OPS = {
    "OBLIGATION", "OBLIGATORY",
    "SUPEREROGATION", "RIGHT", "LIBERTY", "POWER", "IMMUNITY",
}
_PROHIBITION_OPS = {"PROHIBITION", "FORBIDDEN"}
_PERMISSION_OPS = {"PERMISSION", "PERMITTED"}

# Clause type constants (match PolicyClauseType in mcp_server/temporal_policy.py)
CLAUSE_TYPE_OBLIGATION = "obligation"
CLAUSE_TYPE_PERMISSION = "permission"
CLAUSE_TYPE_PROHIBITION = "prohibition"


@dataclass
class CompilationResult:
    """Result returned by :class:`NLToDCECCompiler`."""

    input_text: str
    success: bool = False
    policy: Any = None           # PolicyObject | None
    clauses: List[Any] = field(default_factory=list)   # List[PolicyClause]
    dcec_formulas: List[Any] = field(default_factory=list)  # List[Formula]
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def add_error(self, msg: str) -> None:
        self.errors.append(msg)
        self.success = False

    def add_warning(self, msg: str) -> None:
        self.warnings.append(msg)


# ── helper: extract actor from DCEC formula ──────────────────────────────────

def _extract_actor(formula) -> Optional[str]:
    """Return the first VariableTerm name from *formula*'s inner AtomicFormula."""
    AtomicFormula = None
    try:
        from ..native.dcec_core import AtomicFormula as _AF
        AtomicFormula = _AF
    except ImportError:
        return None

    # Unwrap deontic / cognitive wrapper
    inner = getattr(formula, "formula", formula)

    if isinstance(inner, AtomicFormula):
        args = getattr(inner, "arguments", [])
        if args:
            # Variable term's variable name
            var = getattr(args[0], "variable", None)
            if var is not None:
                return str(getattr(var, "name", var)).split(":")[0]
    return None


def _extract_action(formula) -> Optional[str]:
    """Return the predicate name from *formula*'s inner AtomicFormula."""
    AtomicFormula = None
    try:
        from ..native.dcec_core import AtomicFormula as _AF
        AtomicFormula = _AF
    except ImportError:
        return None

    inner = getattr(formula, "formula", formula)
    if isinstance(inner, AtomicFormula):
        pred = getattr(inner, "predicate", None)
        if pred is not None:
            name = getattr(pred, "name", None)
            if name:
                return str(name)
    return None


# ── core helper: DCEC formula → PolicyClause ─────────────────────────────────

def _dcec_formula_to_clause(
    formula,
    default_actor: Optional[str] = None,
    valid_until: Optional[float] = None,
) -> Optional[Any]:
    """Convert a single DCEC *formula* to a PolicyClause, or None."""
    PolicyClause, _, __ = _get_policy_types()
    DeonticFormula, DeonticOperator, *_ = _get_dcec_types()

    if not isinstance(formula, DeonticFormula):
        # Non-deontic formulas (cognitive, temporal) are not directly
        # representable as policy clauses.
        return None

    op_name = formula.operator.name if hasattr(formula.operator, "name") else str(formula.operator)

    if op_name in _PROHIBITION_OPS:
        clause_type = CLAUSE_TYPE_PROHIBITION
    elif op_name in _OBLIGATION_OPS:
        clause_type = CLAUSE_TYPE_OBLIGATION
    elif op_name in _PERMISSION_OPS:
        clause_type = CLAUSE_TYPE_PERMISSION
    else:
        clause_type = CLAUSE_TYPE_PERMISSION  # default to permissive for unknown

    actor = _extract_actor(formula) or default_actor
    action = _extract_action(formula) or "*"

    return PolicyClause(
        clause_type=clause_type,
        actor=actor,
        action=action,
        valid_until=valid_until,
    )


# ── main compiler ─────────────────────────────────────────────────────────────

class NLToDCECCompiler:
    """
    Compile natural language sentences into a :class:`PolicyObject`.

    Each sentence is individually converted by :class:`NaturalLanguageConverter`
    to a DCEC formula, then mapped to a :class:`PolicyClause`.  All clauses
    are assembled into a single :class:`PolicyObject`.

    Parameters
    ----------
    policy_id:
        Identifier for the produced policy.  Defaults to a hash of the input.
    default_actor:
        Actor name to use when NL extraction fails to identify one.
    valid_until:
        Optional Unix timestamp marking policy expiry.
    strict:
        If *True*, raise on any conversion failure.  If *False* (default),
        collect errors and continue.

    Example
    -------
    >>> compiler = NLToDCECCompiler(policy_id="my-policy")
    >>> result = compiler.compile([
    ...     "Alice must not access the database",
    ...     "Bob is permitted to read files",
    ... ])
    >>> result.success
    True
    >>> len(result.clauses)
    2
    >>> result.policy.evaluate("alice", "access")
    False
    """

    def __init__(
        self,
        policy_id: Optional[str] = None,
        default_actor: Optional[str] = None,
        valid_until: Optional[float] = None,
        strict: bool = False,
    ) -> None:
        self.policy_id = policy_id
        self.default_actor = default_actor
        self.valid_until = valid_until
        self.strict = strict
        self._converter = None  # lazy

    def _get_converter(self):
        if self._converter is None:
            NaturalLanguageConverter, _ = _get_nl_converter()
            self._converter = NaturalLanguageConverter()
        return self._converter

    def compile_sentence(self, text: str) -> CompilationResult:
        """Compile a single natural language *sentence* into a CompilationResult."""
        result = CompilationResult(input_text=text)
        try:
            converter = self._get_converter()
            conv_result = converter.convert_to_dcec(text)
        except Exception as exc:
            result.add_error(f"NL conversion error: {exc}")
            if self.strict:
                raise
            return result

        if not conv_result.success or conv_result.dcec_formula is None:
            msg = conv_result.error_message or "NL conversion returned no formula"
            result.add_error(msg)
            if self.strict:
                raise ValueError(msg)
            return result

        formula = conv_result.dcec_formula
        result.dcec_formulas.append(formula)

        clause = _dcec_formula_to_clause(
            formula,
            default_actor=self.default_actor,
            valid_until=self.valid_until,
        )

        if clause is None:
            result.add_warning(
                f"Formula {type(formula).__name__} cannot be mapped to a PolicyClause; skipped."
            )
        else:
            result.clauses.append(clause)
            result.success = True

        return result

    def compile(
        self,
        sentences: List[str],
        policy_id: Optional[str] = None,
    ) -> CompilationResult:
        """
        Compile a list of natural language *sentences* into a PolicyObject.

        Parameters
        ----------
        sentences:
            List of plain-English policy statements.
        policy_id:
            Override the instance-level ``policy_id``.

        Returns
        -------
        CompilationResult
            ``.success`` is True if at least one clause was produced without
            a fatal error.  ``.policy`` holds the resulting
            :class:`PolicyObject`.
        """
        pid = policy_id or self.policy_id or _make_policy_id(sentences)
        overall = CompilationResult(input_text="\n".join(sentences))
        overall.metadata["policy_id"] = pid
        overall.metadata["sentence_count"] = len(sentences)

        for i, sentence in enumerate(sentences):
            sentence = sentence.strip()
            if not sentence:
                continue
            single = self.compile_sentence(sentence)
            overall.dcec_formulas.extend(single.dcec_formulas)
            overall.clauses.extend(single.clauses)
            overall.errors.extend(single.errors)
            overall.warnings.extend(single.warnings)
            overall.metadata[f"sentence_{i}"] = {
                "text": sentence,
                "success": single.success,
                "formula_type": (
                    type(single.dcec_formulas[0]).__name__
                    if single.dcec_formulas
                    else None
                ),
            }

        if not overall.clauses:
            overall.add_error("No PolicyClauses produced from input text.")
            if self.strict:
                raise ValueError("\n".join(overall.errors))
            return overall

        # Assemble PolicyObject
        try:
            _, PolicyObject, _ = _get_policy_types()
            policy = PolicyObject(
                policy_id=pid,
                clauses=list(overall.clauses),
            )
            overall.policy = policy
            overall.success = True
        except Exception as exc:
            overall.add_error(f"Failed to create PolicyObject: {exc}")
            if self.strict:
                raise

        return overall


# ── convenience helper ────────────────────────────────────────────────────────

def compile_nl_to_policy(
    sentences: List[str],
    *,
    policy_id: Optional[str] = None,
    default_actor: Optional[str] = None,
    valid_until: Optional[float] = None,
) -> CompilationResult:
    """
    One-shot convenience wrapper: compile *sentences* to a PolicyObject.

    Example
    -------
    >>> result = compile_nl_to_policy(
    ...     ["Alice must not delete records", "Bob may read files"],
    ...     policy_id="acl-001",
    ... )
    >>> result.success
    True
    """
    compiler = NLToDCECCompiler(
        policy_id=policy_id,
        default_actor=default_actor,
        valid_until=valid_until,
    )
    return compiler.compile(sentences, policy_id=policy_id)


def _make_policy_id(sentences: List[str]) -> str:
    """Derive a short policy id from input sentences."""
    import hashlib
    digest = hashlib.sha256("\n".join(sentences).encode()).hexdigest()[:12]
    return f"nl-policy-{digest}"
