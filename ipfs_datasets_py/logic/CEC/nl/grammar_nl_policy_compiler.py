"""
Grammar-based Natural Language to Policy Clause Compiler.

This module provides a grammar-driven (rather than regex-driven) compiler
that converts natural language deontic statements directly into
``PolicyClause`` / ``PolicyObject`` structures using the
``DCECEnglishGrammar`` compositional semantics engine.

The grammar approach is complementary to, and more precise than, the
regex-pattern approach in ``nl_to_policy_compiler.py``.  Where the
pattern-based compiler handles most sentences quickly, the grammar-based
compiler handles compositional sentences such as:

    "Bob must read and Alice may write"
    "Every agent is required to log all access events"
    "Carol must not delete and must not modify records"

Usage::

    from ipfs_datasets_py.logic.CEC.nl.grammar_nl_policy_compiler import (
        GrammarNLPolicyCompiler,
        grammar_compile_nl_to_policy,
    )

    compiler = GrammarNLPolicyCompiler()
    result = compiler.compile("Alice must not delete records")
    print(result.policy_cid, result.clauses)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional import: DCECEnglishGrammar (only needed for grammar-based path)
# ---------------------------------------------------------------------------
try:
    from ..native.dcec_english_grammar import DCECEnglishGrammar, create_dcec_grammar
    _GRAMMAR_AVAILABLE = True
except Exception:  # pragma: no cover — grammar may have optional deps
    _GRAMMAR_AVAILABLE = False

# Optional import: DeonticFormula/DeonticOperator from dcec_core
try:
    from ..native.dcec_core import DeonticFormula, DeonticOperator
    _DCEC_AVAILABLE = True
except Exception:  # pragma: no cover
    _DCEC_AVAILABLE = False

# Optional import: policy layer (temporal_policy in mcp_server)
try:
    from ....mcp_server.temporal_policy import (
        PolicyClause,
        PolicyObject,
        PolicyEvaluator,
        make_simple_permission_policy,
    )
    _POLICY_AVAILABLE = True
except Exception:
    try:
        # Fallback: try relative import from mcp_server at package root
        import importlib
        _tp = importlib.import_module("ipfs_datasets_py.mcp_server.temporal_policy")
        PolicyClause = _tp.PolicyClause
        PolicyObject = _tp.PolicyObject
        make_simple_permission_policy = _tp.make_simple_permission_policy
        _POLICY_AVAILABLE = True
    except Exception:
        _POLICY_AVAILABLE = False

# Clause-type constants (mirrors nl_to_policy_compiler.py)
CLAUSE_TYPE_OBLIGATION = "obligation"
CLAUSE_TYPE_PERMISSION = "permission"
CLAUSE_TYPE_PROHIBITION = "prohibition"

# DeonticOperator → clause type map (populated only when dcec is available)
_OP_TO_CLAUSE_TYPE: dict = {}
if _DCEC_AVAILABLE:
    _OP_TO_CLAUSE_TYPE = {
        DeonticOperator.OBLIGATION:     CLAUSE_TYPE_OBLIGATION,
        DeonticOperator.PERMISSION:     CLAUSE_TYPE_PERMISSION,
        DeonticOperator.PROHIBITION:    CLAUSE_TYPE_PROHIBITION,
    }
    # Add aliases present in some DCEC builds
    for _name, _ct in [
        ("OBLIGATORY",      CLAUSE_TYPE_OBLIGATION),
        ("FORBIDDEN",       CLAUSE_TYPE_PROHIBITION),
        ("IMPERMISSIBLE",   CLAUSE_TYPE_PROHIBITION),
        ("RIGHT",           CLAUSE_TYPE_PERMISSION),
        ("LIBERTY",         CLAUSE_TYPE_PERMISSION),
        ("POWER",           CLAUSE_TYPE_PERMISSION),
        ("IMMUNITY",        CLAUSE_TYPE_PERMISSION),
        ("SUPEREROGATION",  CLAUSE_TYPE_PERMISSION),
    ]:
        _op = getattr(DeonticOperator, _name, None)
        if _op is not None:
            _OP_TO_CLAUSE_TYPE[_op] = _ct


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class GrammarCompilationResult:
    """Result of a grammar-based NL→PolicyClause compilation."""

    text: str
    clauses: List[dict] = field(default_factory=list)
    policy_cid: str = ""
    warnings: List[str] = field(default_factory=list)
    parse_method: str = "grammar"

    # Raw parsed formulas (list of (actor, action, clause_type) triples)
    formula_triples: List[Tuple[str, str, str]] = field(default_factory=list)

    @property
    def success(self) -> bool:
        """Return True if at least one clause was compiled."""
        return bool(self.clauses)

    @property
    def prohibition_clauses(self) -> List[dict]:
        return [c for c in self.clauses if c.get("clause_type") == CLAUSE_TYPE_PROHIBITION]

    @property
    def permission_clauses(self) -> List[dict]:
        return [c for c in self.clauses if c.get("clause_type") == CLAUSE_TYPE_PERMISSION]

    @property
    def obligation_clauses(self) -> List[dict]:
        return [c for c in self.clauses if c.get("clause_type") == CLAUSE_TYPE_OBLIGATION]

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "clauses": self.clauses,
            "policy_cid": self.policy_cid,
            "warnings": self.warnings,
            "parse_method": self.parse_method,
            "success": self.success,
        }


# ---------------------------------------------------------------------------
# Main compiler class
# ---------------------------------------------------------------------------

class GrammarNLPolicyCompiler:
    """
    Grammar-based NL → PolicyClause compiler.

    Unlike the pattern-based ``NLToDCECCompiler``, this class delegates
    tokenisation and semantic composition to ``DCECEnglishGrammar``, which
    uses a proper EBNF grammar and compositional lambda-calculus semantics.

    When ``DCECEnglishGrammar`` is unavailable (optional dependency not
    installed), the compiler transparently falls back to a lightweight
    heuristic splitter so that callers always receive a valid result.

    Parameters
    ----------
    use_grammar:
        If *True* (default) and ``DCECEnglishGrammar`` is available, the
        full grammar engine is used.  Set to *False* to force the
        lightweight fallback for testing.
    default_actor:
        Actor name substituted when the grammar cannot identify an agent
        (default ``"agent"``).
    """

    def __init__(
        self,
        use_grammar: bool = True,
        default_actor: str = "agent",
    ) -> None:
        self._default_actor = default_actor
        self._grammar: Optional[object] = None
        self._grammar_failed = False

        if use_grammar and _GRAMMAR_AVAILABLE:
            try:
                self._grammar = create_dcec_grammar()
            except Exception as exc:  # pragma: no cover
                logger.warning("DCECEnglishGrammar init failed: %s — using fallback", exc)
                self._grammar_failed = True
        elif use_grammar and not _GRAMMAR_AVAILABLE:
            logger.debug("DCECEnglishGrammar not available; using fallback compiler")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compile(self, text: str) -> GrammarCompilationResult:
        """
        Compile a natural language deontic statement into policy clauses.

        Parameters
        ----------
        text:
            One or more English sentences describing obligations,
            permissions, and prohibitions.

        Returns
        -------
        GrammarCompilationResult
            Contains ``clauses`` (list of dicts) and metadata.
        """
        result = GrammarCompilationResult(text=text)

        # Split into sentences for individual parsing
        sentences = self._split_sentences(text)

        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue

            triple = self._parse_sentence(sentence, result.warnings)
            if triple is not None:
                actor, action, clause_type = triple
                result.formula_triples.append(triple)
                result.clauses.append({
                    "actor": actor,
                    "action": action,
                    "clause_type": clause_type,
                    "resource": f"logic/{action}",
                    "source_sentence": sentence,
                })

        if not result.clauses:
            result.warnings.append(
                "No deontic clauses compiled from input text; "
                "check that sentences contain obligation/permission/prohibition patterns"
            )
            result.parse_method = "fallback"
        else:
            result.parse_method = (
                "grammar" if (self._grammar and not self._grammar_failed) else "fallback"
            )

        # Optionally attach a policy_cid from the PolicyObject
        if _POLICY_AVAILABLE and result.clauses:
            try:
                po = self._build_policy_object(result.clauses)
                result.policy_cid = po.policy_cid
            except Exception as exc:  # pragma: no cover
                result.warnings.append(f"PolicyObject construction failed: {exc}")

        return result

    def compile_multi(self, texts: List[str]) -> List[GrammarCompilationResult]:
        """Compile multiple NL texts, returning one result per input."""
        return [self.compile(t) for t in texts]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _split_sentences(self, text: str) -> List[str]:
        """Split text into individual sentences on sentence-ending punctuation."""
        import re
        # Split on period, semicolon, exclamation, question mark, or newline
        # but avoid splitting on abbreviations (simplistic)
        parts = re.split(r"(?<=[.!?;])\s+|[\n]+", text)
        return [p.strip().rstrip(".!?;") for p in parts if p.strip()]

    def _parse_sentence(
        self,
        sentence: str,
        warnings: List[str],
    ) -> Optional[Tuple[str, str, str]]:
        """
        Parse a single sentence, returning (actor, action, clause_type) or None.

        Tries grammar engine first; falls back to lightweight heuristics.
        """
        if self._grammar and not self._grammar_failed and _DCEC_AVAILABLE:
            triple = self._parse_with_grammar(sentence, warnings)
            if triple is not None:
                return triple
            # Grammar gave no result — fall through to heuristic

        return self._parse_with_heuristic(sentence)

    def _parse_with_grammar(
        self,
        sentence: str,
        warnings: List[str],
    ) -> Optional[Tuple[str, str, str]]:
        """Use DCECEnglishGrammar to parse, then extract (actor, action, clause_type)."""
        try:
            formula = self._grammar.parse_to_dcec(sentence)  # type: ignore[union-attr]
        except Exception as exc:
            warnings.append(f"Grammar parse error for '{sentence}': {exc}")
            return None

        if formula is None:
            return None

        return self._formula_to_triple(formula)

    def _formula_to_triple(self, formula: object) -> Optional[Tuple[str, str, str]]:
        """
        Extract (actor, action, clause_type) from a DeonticFormula.

        Non-deontic formulas (e.g. plain atomic) are ignored.
        """
        if not _DCEC_AVAILABLE:
            return None  # pragma: no cover

        if not isinstance(formula, DeonticFormula):
            return None

        clause_type = _OP_TO_CLAUSE_TYPE.get(formula.operator, None)
        if clause_type is None:
            return None

        # Extract predicate name and optional agent from inner formula
        inner = formula.formula
        action = self._extract_action(inner)
        actor = self._extract_actor(inner) or self._default_actor

        return (actor, action, clause_type)

    def _extract_action(self, formula: object) -> str:
        """Return a string action name from a DCEC formula node."""
        if hasattr(formula, "predicate"):
            pred = formula.predicate
            if hasattr(pred, "name"):
                return str(pred.name)
            return str(pred)
        if hasattr(formula, "formula"):
            return self._extract_action(formula.formula)
        return str(formula)

    def _extract_actor(self, formula: object) -> Optional[str]:
        """Return actor name from the first argument of a predicate, if present."""
        if hasattr(formula, "arguments") and formula.arguments:  # type: ignore[union-attr]
            arg = formula.arguments[0]  # type: ignore[index]
            if hasattr(arg, "name"):
                return str(arg.name)
            return str(arg)
        return None

    # ------------------------------------------------------------------
    # Lightweight heuristic fallback (no grammar engine needed)
    # ------------------------------------------------------------------

    _PROHIBITION_PATTERNS = [
        "must not", "should not", "cannot", "can not",
        "is forbidden to", "is prohibited from", "may not",
        "is not permitted to", "is not allowed to",
    ]
    _OBLIGATION_PATTERNS = [
        "must", "should", "is required to", "is obligated to",
        "ought to", "has to", "needs to", "is expected to",
    ]
    _PERMISSION_PATTERNS = [
        "may", "can", "is permitted to", "is allowed to",
        "has the right to", "is entitled to",
    ]

    def _parse_with_heuristic(self, sentence: str) -> Optional[Tuple[str, str, str]]:
        """
        Lightweight keyword-based fallback.

        Returns (actor, action, clause_type) or None.
        """
        lower = sentence.lower()
        clause_type: Optional[str] = None

        # Order matters: check prohibition before obligation
        for pat in self._PROHIBITION_PATTERNS:
            if pat in lower:
                clause_type = CLAUSE_TYPE_PROHIBITION
                break
        if clause_type is None:
            for pat in self._OBLIGATION_PATTERNS:
                if pat in lower:
                    clause_type = CLAUSE_TYPE_OBLIGATION
                    break
        if clause_type is None:
            for pat in self._PERMISSION_PATTERNS:
                if pat in lower:
                    clause_type = CLAUSE_TYPE_PERMISSION
                    break

        if clause_type is None:
            return None

        actor, action = self._heuristic_extract_actor_action(sentence)
        return (actor, action, clause_type)

    def _heuristic_extract_actor_action(self, sentence: str) -> Tuple[str, str]:
        """
        Very simple actor/action extraction by word position.

        Heuristic: first capitalised word is the actor; last significant
        word is the action.
        """
        import re
        words = re.findall(r"\b[A-Za-z]\w*\b", sentence)
        if not words:
            return (self._default_actor, "action")

        # Actor: first capitalised word (proper noun)
        actor = self._default_actor
        for w in words:
            if w[0].isupper():
                actor = w.lower()
                break

        # Action: last word that is not a stop-word or modal
        _stop = {
            "must", "should", "may", "can", "not", "to", "the", "a", "an",
            "is", "are", "be", "has", "have", "it", "they", "he", "she",
            "all", "and", "or", "of", "in", "on", "at", "for", "by",
        }
        action_words = [w.lower() for w in words if w.lower() not in _stop]
        action = action_words[-1] if action_words else "action"

        return (actor, action)

    # ------------------------------------------------------------------
    # PolicyObject builder
    # ------------------------------------------------------------------

    def _build_policy_object(self, clauses: List[dict]) -> object:
        """
        Build a ``PolicyObject`` from a list of clause dicts.

        Only called when _POLICY_AVAILABLE is True.
        """
        # Use the first non-wildcard permission if any, else create from scratch
        permissions = [c for c in clauses if c["clause_type"] == CLAUSE_TYPE_PERMISSION]

        if permissions and len(clauses) == 1:
            c = permissions[0]
            return make_simple_permission_policy(
                actor=c["actor"],
                resource=c["resource"],
                action=c["action"],
            )

        # General case: build PolicyObject directly
        policy_clauses = []
        for c in clauses:
            pc = PolicyClause(
                clause_type=c["clause_type"],
                actor=c["actor"],
                action=c["action"],
                resource=c["resource"],
            )
            policy_clauses.append(pc)

        return PolicyObject(clauses=policy_clauses)


# ---------------------------------------------------------------------------
# Module-level convenience function
# ---------------------------------------------------------------------------

def grammar_compile_nl_to_policy(
    text: str,
    *,
    use_grammar: bool = True,
    default_actor: str = "agent",
) -> GrammarCompilationResult:
    """
    One-shot grammar-based NL → policy compilation.

    Parameters
    ----------
    text:
        Plain English deontic statement(s).
    use_grammar:
        Use DCECEnglishGrammar if available (default True).
    default_actor:
        Fallback actor name when none can be extracted.

    Returns
    -------
    GrammarCompilationResult
    """
    compiler = GrammarNLPolicyCompiler(use_grammar=use_grammar, default_actor=default_actor)
    return compiler.compile(text)
