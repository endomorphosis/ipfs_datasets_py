"""Minimal, deterministic semantics for "legal theorems" (P7).

This module intentionally stays dependency-free and conservative:

- It defines a *tiny* fragment of logic for `TDFOL_v1` suitable for testing and
  for pinning down what "theorem holds" means in a deterministic way.
- It does NOT attempt to be a full first-order logic prover.

Current supported fragment (TDFOL_v1, MVP semantics):

- Atoms: identifiers matching `[A-Za-z][A-Za-z0-9_]*`
- Axioms:
  - Fact: `P`
  - Implication: `P -> Q`
- Theorem: `Q`

Semantics (forward chaining / modus ponens):

- Let `known` start as all facts.
- Repeatedly apply: if `P` is known and there is an axiom `P -> Q`, then add `Q`.
- The theorem holds iff the theorem atom is in `known` at fixpoint.

This is a pragmatic stepping stone toward P7.2 (compiling semantics to an R1CS).
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable, Optional, Set, Tuple


_ATOM_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


class LegalTheoremSyntaxError(ValueError):
    """Raised when an axiom/theorem string is outside the supported fragment."""


@dataclass(frozen=True)
class HornAxiom:
    """Axiom in a Horn-like propositional fragment.

    If `antecedent` is None, the axiom is a fact: consequent.
    Otherwise it is an implication: antecedent -> consequent.
    """

    antecedent: Optional[str]
    consequent: str


def _parse_atom(atom: str, *, label: str) -> str:
    atom = atom.strip()
    if not atom or not _ATOM_RE.match(atom):
        raise LegalTheoremSyntaxError(
            f"{label} must be an atom matching [A-Za-z][A-Za-z0-9_]*"
        )
    return atom


def parse_tdfol_v1_axiom(text: str) -> HornAxiom:
    """Parse a single axiom in the supported `TDFOL_v1` fragment."""

    if text is None:
        raise LegalTheoremSyntaxError("axiom must be a string")

    s = str(text).strip()
    if not s:
        raise LegalTheoremSyntaxError("axiom cannot be empty")

    if "->" in s:
        parts = s.split("->")
        if len(parts) != 2:
            raise LegalTheoremSyntaxError("axiom may contain at most one '->'")
        left, right = parts
        antecedent = _parse_atom(left, label="axiom antecedent")
        consequent = _parse_atom(right, label="axiom consequent")
        return HornAxiom(antecedent=antecedent, consequent=consequent)

    # Fact
    consequent = _parse_atom(s, label="axiom")
    return HornAxiom(antecedent=None, consequent=consequent)


def parse_tdfol_v1_theorem(text: str) -> str:
    """Parse a theorem atom for the supported `TDFOL_v1` fragment."""

    if text is None:
        raise LegalTheoremSyntaxError("theorem must be a string")
    return _parse_atom(str(text), label="theorem")


def evaluate_tdfol_v1_holds(private_axioms: Iterable[str], theorem: str) -> bool:
    """Return True if `theorem` is derivable from `private_axioms` under TDFOL_v1.

    This is deterministic and total over the supported syntax.
    """

    axioms = [parse_tdfol_v1_axiom(a) for a in private_axioms]
    goal = parse_tdfol_v1_theorem(theorem)

    known: Set[str] = {a.consequent for a in axioms if a.antecedent is None}

    implications: Tuple[HornAxiom, ...] = tuple(a for a in axioms if a.antecedent is not None)

    # Forward chaining to fixpoint.
    changed = True
    while changed:
        changed = False
        for ax in implications:
            assert ax.antecedent is not None
            if ax.antecedent in known and ax.consequent not in known:
                known.add(ax.consequent)
                changed = True

    return goal in known
