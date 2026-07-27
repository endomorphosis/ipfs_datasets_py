"""Deterministic natural-language realization of canonical rule IR.

This adapter is intentionally a leaf of the semantic round-trip benchmark.
It consumes the public :class:`~benchmarks.semantic_roundtrip.RealizerRequest`
and does not import a constructor, a native logic representation, or any
source-bearing service.  Its small, fixed grammar makes the polarity and every
scored canonical facet visible in the resulting text.
"""

from __future__ import annotations

from typing import Final

from benchmarks.semantic_roundtrip.contracts import (
    CanonicalRule,
    ComponentStatus,
    ContractError,
    FailureReason,
    RealizerRequest,
    RealizerResult,
    RoundTripRealizer,
)


CANONICAL_DETERMINISTIC_REALIZER_INTERFACE: Final = (
    "CanonicalDeterministicRealizer@1"
)

_MODAL_PHRASES: Final = {
    "O": "shall",
    "P": "may",
    "F": "shall not",
}


def _readable_atom(atom: str) -> str:
    """Turn a closed-vocabulary atom into a stable readable phrase."""

    return " ".join(atom.replace("_", " ").split())


def _join_atoms(atoms: tuple[str, ...], conjunction: str) -> str:
    """Render a canonically ordered atom tuple without adding semantics."""

    return f" {conjunction} ".join(_readable_atom(atom) for atom in atoms)


def realize_rule(rule: CanonicalRule) -> str:
    """Render one canonical rule with a fixed, polarity-safe grammar.

    Temporal facets precede activation conditions so common atoms such as
    ``within_10_days`` and ``annually`` retain their ordinary adverbial form.
    Conditions and exceptions use distinct fixed connectors; this prevents an
    exception from being accidentally rendered as a condition.
    """

    if not isinstance(rule, CanonicalRule):
        raise ContractError("rule must be CanonicalRule")

    parts = [
        _readable_atom(rule.actor),
        _MODAL_PHRASES[rule.modality],
        _readable_atom(rule.action),
    ]
    if rule.object:
        parts.append(_readable_atom(rule.object))

    sentence = " ".join(parts)
    if rule.temporal:
        sentence += " " + _join_atoms(rule.temporal, "and")
    if rule.conditions:
        sentence += " if " + _join_atoms(rule.conditions, "and")
    if rule.exceptions:
        sentence += " unless " + _join_atoms(rule.exceptions, "or")

    # Actor and action are nonempty after RealizerRequest vocabulary
    # validation, so this branch is safe and avoids locale-sensitive title()
    # transformations of the remainder of the closed-vocabulary atom.
    return sentence[0].upper() + sentence[1:] + "."


class CanonicalDeterministicRealizer:
    """Source-withheld, stateless implementation of ``RoundTripRealizer``."""

    __slots__ = ()

    @property
    def identity(self) -> str:
        return CANONICAL_DETERMINISTIC_REALIZER_INTERFACE

    def realize(self, request: RealizerRequest) -> RealizerResult:
        """Realize only the canonical IR carried by ``request``.

        The allowed vocabulary has already been enforced by
        :class:`RealizerRequest`.  Public configuration is intentionally not
        consulted: this adapter has no tunable decoding behavior and therefore
        cannot use configuration as a source, native-record, or cache channel.
        """

        if not isinstance(request, RealizerRequest):
            return RealizerResult(
                status=ComponentStatus.FAILED,
                failure_reason=FailureReason.INVALID_OUTPUT,
                failure_detail="request must be RealizerRequest",
            )
        if request.canonical_ir.is_empty:
            return RealizerResult(
                status=ComponentStatus.FAILED,
                failure_reason=FailureReason.EMPTY_L1,
                failure_detail="canonical IR contains no rules",
            )

        text = " ".join(realize_rule(rule) for rule in request.canonical_ir.rules)
        return RealizerResult(status=ComponentStatus.SUCCESS, text=text)


assert isinstance(CanonicalDeterministicRealizer(), RoundTripRealizer)


# Concise aliases make the implementation easy to register while retaining the
# interface's canonical class name above.
DeterministicCanonicalRealizer = CanonicalDeterministicRealizer
DeterministicRealizer = CanonicalDeterministicRealizer


__all__ = [
    "CANONICAL_DETERMINISTIC_REALIZER_INTERFACE",
    "CanonicalDeterministicRealizer",
    "DeterministicCanonicalRealizer",
    "DeterministicRealizer",
    "realize_rule",
]
