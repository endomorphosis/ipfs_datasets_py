"""Modal logic registry for deterministic legal parsing.

The registry is deliberately data-oriented: parser code can ask for a profile
by family or system without hard-coding modal cue words throughout the pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Iterable, Mapping, Optional, Tuple


class ModalLogicFamily(Enum):
    """Modal logic families planned for deterministic legal parsing."""

    ALETHIC = "alethic"
    DEONTIC = "deontic"
    TEMPORAL = "temporal"
    EPISTEMIC = "epistemic"
    DOXASTIC = "doxastic"
    DYNAMIC = "dynamic"
    CONDITIONAL_NORMATIVE = "conditional_normative"
    FRAME = "frame"
    HYBRID = "hybrid"


NORMATIVE_MODAL_FAMILIES: Tuple[ModalLogicFamily, ...] = (
    ModalLogicFamily.DEONTIC,
    ModalLogicFamily.CONDITIONAL_NORMATIVE,
)

COMPILER_AMBIGUITY_CORE_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
)

COMPILER_REQUIRED_ADAPTIVE_AMBIGUITY_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.ALETHIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.ALETHIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.ALETHIC.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.ALETHIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.ALETHIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DYNAMIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.DYNAMIC.value,
        ModalLogicFamily.DYNAMIC.value,
    ),
    (
        ModalLogicFamily.DYNAMIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.EPISTEMIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.EPISTEMIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.EPISTEMIC.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.EPISTEMIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.ALETHIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DOXASTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    *COMPILER_AMBIGUITY_CORE_FAMILY_PAIRS,
)

COMPILER_AMBIGUITY_POLICY_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.ALETHIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.ALETHIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.ALETHIC.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DYNAMIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.DYNAMIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.EPISTEMIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.ALETHIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.EPISTEMIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.ALETHIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DYNAMIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DOXASTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.HYBRID.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.ALETHIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    *COMPILER_AMBIGUITY_CORE_FAMILY_PAIRS,
)

ZERO_MARGIN_CONTESTED_ADAPTIVE_AMBIGUITY_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.EPISTEMIC.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
)

SIGNAL_FREE_ADAPTIVE_AMBIGUITY_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.ALETHIC.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.ALETHIC.value,
        ModalLogicFamily.DYNAMIC.value,
    ),
    (
        ModalLogicFamily.ALETHIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.ALETHIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.ALETHIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.ALETHIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DYNAMIC.value,
    ),
    (
        ModalLogicFamily.DYNAMIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.DYNAMIC.value,
    ),
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.EPISTEMIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.EPISTEMIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.EPISTEMIC.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.ALETHIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.HYBRID.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.ALETHIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.ALETHIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DYNAMIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DOXASTIC.value,
    ),
    *COMPILER_REQUIRED_ADAPTIVE_AMBIGUITY_FAMILY_PAIRS,
)


def _ordered_unique_adaptive_ambiguity_family_pairs(
    pairs: Iterable[Tuple[str, str]],
) -> Tuple[Tuple[str, str], ...]:
    """Return a stable pair table with duplicates removed and order preserved."""
    unique_pairs: list[Tuple[str, str]] = []
    seen_pairs: set[Tuple[str, str]] = set()
    for pair in pairs:
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        unique_pairs.append(pair)
    return tuple(unique_pairs)


COMPILER_REQUIRED_ADAPTIVE_AMBIGUITY_FAMILY_PAIRS = (
    _ordered_unique_adaptive_ambiguity_family_pairs(
        COMPILER_REQUIRED_ADAPTIVE_AMBIGUITY_FAMILY_PAIRS
    )
)

COMPILER_AMBIGUITY_POLICY_FAMILY_PAIRS = (
    _ordered_unique_adaptive_ambiguity_family_pairs(
        COMPILER_AMBIGUITY_POLICY_FAMILY_PAIRS
    )
)

SIGNAL_FREE_ADAPTIVE_AMBIGUITY_FAMILY_PAIRS = (
    _ordered_unique_adaptive_ambiguity_family_pairs(
        SIGNAL_FREE_ADAPTIVE_AMBIGUITY_FAMILY_PAIRS
    )
)

PRIORITY_SIGNAL_FREE_ADAPTIVE_AMBIGUITY_FAMILY_PAIRS: Tuple[Tuple[str, str], ...] = (
    (
        ModalLogicFamily.ALETHIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.ALETHIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.ALETHIC.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.ALETHIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.ALETHIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.EPISTEMIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.EPISTEMIC.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DYNAMIC.value,
    ),
    (
        ModalLogicFamily.DYNAMIC.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.ALETHIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.HYBRID.value,
        ModalLogicFamily.FRAME.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.EPISTEMIC.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.TEMPORAL.value,
    ),
    (
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DOXASTIC.value,
    ),
)

PRIORITY_SIGNAL_FREE_ADAPTIVE_AMBIGUITY_FAMILY_PAIRS = (
    _ordered_unique_adaptive_ambiguity_family_pairs(
        PRIORITY_SIGNAL_FREE_ADAPTIVE_AMBIGUITY_FAMILY_PAIRS
    )
)


class ModalSystem(Enum):
    """Common modal systems and legal-parser profiles."""

    K = "K"
    T = "T"
    D = "D"
    K4 = "K4"
    S4 = "S4"
    S5 = "S5"
    KD = "KD"
    KD45 = "KD45"
    LTL = "LTL"
    CTL = "CTL"
    PDL = "PDL"
    STIT = "STIT"
    FRAME_BM25 = "FRAME_BM25"
    HYBRID = "HYBRID"


@dataclass(frozen=True)
class ModalOperatorSpec:
    """Description of an operator and its deterministic text cues."""

    symbol: str
    aliases: Tuple[str, ...]
    arity: int = 1
    cue_terms: Tuple[str, ...] = ()
    allowed_systems: Tuple[ModalSystem, ...] = ()


@dataclass(frozen=True)
class ModalSemanticsSpec:
    """Frame constraints for a modal profile."""

    reflexive: bool = False
    transitive: bool = False
    serial: bool = False
    symmetric: bool = False
    euclidean: bool = False
    tree_time: bool = False
    action_transition: bool = False
    ontology_frame_grounded: bool = False

    def to_dict(self) -> Dict[str, bool]:
        """Return a stable JSON-ready mapping."""
        return {
            "action_transition": self.action_transition,
            "euclidean": self.euclidean,
            "ontology_frame_grounded": self.ontology_frame_grounded,
            "reflexive": self.reflexive,
            "serial": self.serial,
            "symmetric": self.symmetric,
            "transitive": self.transitive,
            "tree_time": self.tree_time,
        }


@dataclass(frozen=True)
class ModalParseProfile:
    """Registry entry for one modal parsing profile."""

    family: ModalLogicFamily
    system: ModalSystem
    operators: Tuple[ModalOperatorSpec, ...]
    semantics: ModalSemanticsSpec = field(default_factory=ModalSemanticsSpec)
    description: str = ""

    @property
    def profile_id(self) -> str:
        """Stable profile identifier."""
        return f"{self.family.value}:{self.system.value}"

    def to_dict(self) -> Dict[str, object]:
        """Return a stable JSON-ready mapping."""
        return {
            "description": self.description,
            "family": self.family.value,
            "operators": [
                {
                    "aliases": list(operator.aliases),
                    "allowed_systems": [system.value for system in operator.allowed_systems],
                    "arity": operator.arity,
                    "cue_terms": list(operator.cue_terms),
                    "symbol": operator.symbol,
                }
                for operator in self.operators
            ],
            "profile_id": self.profile_id,
            "semantics": self.semantics.to_dict(),
            "system": self.system.value,
        }


def _op(
    symbol: str,
    aliases: Iterable[str],
    cue_terms: Iterable[str],
    systems: Iterable[ModalSystem],
) -> ModalOperatorSpec:
    return ModalOperatorSpec(
        symbol=symbol,
        aliases=tuple(aliases),
        cue_terms=tuple(cue_terms),
        allowed_systems=tuple(systems),
    )


DEFAULT_MODAL_PROFILES: Tuple[ModalParseProfile, ...] = (
    ModalParseProfile(
        family=ModalLogicFamily.ALETHIC,
        system=ModalSystem.S5,
        operators=(
            _op("□", ("necessary", "must_be"), ("necessary", "impossible", "cannot"), (ModalSystem.K, ModalSystem.T, ModalSystem.S4, ModalSystem.S5)),
            _op("◇", ("possible",), ("possible", "can be"), (ModalSystem.K, ModalSystem.T, ModalSystem.S4, ModalSystem.S5)),
        ),
        semantics=ModalSemanticsSpec(reflexive=True, transitive=True, symmetric=True, euclidean=True),
        description="Alethic necessity and possibility.",
    ),
    ModalParseProfile(
        family=ModalLogicFamily.DEONTIC,
        system=ModalSystem.D,
        operators=(
            _op(
                "O",
                ("obligation", "obligatory"),
                (
                    "shall",
                    "shall issue",
                    "must",
                    "required",
                    "obligated",
                    "has a duty to",
                    "have a duty to",
                    "under an obligation to",
                    "is entitled to",
                    "shall be entitled to",
                ),
                (ModalSystem.D, ModalSystem.KD),
            ),
            _op("P", ("permission", "permitted"), ("may", "permitted", "authorized", "allowed"), (ModalSystem.D, ModalSystem.KD)),
            _op("F", ("prohibition", "forbidden"), ("may not", "must not", "prohibited", "forbidden"), (ModalSystem.D, ModalSystem.KD)),
        ),
        semantics=ModalSemanticsSpec(serial=True),
        description="Legal obligations, permissions, and prohibitions.",
    ),
    ModalParseProfile(
        family=ModalLogicFamily.TEMPORAL,
        system=ModalSystem.LTL,
        operators=(
            _op("G", ("always",), ("always", "throughout", "until"), (ModalSystem.LTL, ModalSystem.CTL)),
            _op(
                "F",
                ("eventually",),
                (
                    "eventually",
                    "within",
                    "by",
                    "effective date",
                    "effective on first day",
                    "fiscal year",
                    "fiscal years",
                    "calendar year",
                    "calendar years",
                    "for each fiscal year",
                    "for each of fiscal years",
                    "for fiscal years",
                    "for each calendar year",
                    "for calendar years",
                    "from time to time",
                    "on or after",
                    "beginning on or after",
                    "no earlier than",
                    "no later than",
                    "not earlier than",
                    "not later than",
                ),
                (ModalSystem.LTL, ModalSystem.CTL),
            ),
            _op(
                "X",
                ("next",),
                (
                    "next",
                    "after",
                    "following",
                    "after notice and hearing",
                    "after notice and opportunity for hearing",
                ),
                (ModalSystem.LTL, ModalSystem.CTL),
            ),
        ),
        semantics=ModalSemanticsSpec(tree_time=True),
        description="Deadlines, effective dates, and temporal scopes.",
    ),
    ModalParseProfile(
        family=ModalLogicFamily.EPISTEMIC,
        system=ModalSystem.S5,
        operators=(
            _op(
                "K",
                ("knows", "knowledge"),
                (
                    "knows",
                    "finds",
                    "determines",
                    "has reason to know",
                    "has reason to believe",
                    "knowledge of",
                    "knowingly",
                    "reason to believe",
                ),
                (ModalSystem.S4, ModalSystem.S5),
            ),
        ),
        semantics=ModalSemanticsSpec(reflexive=True, transitive=True, symmetric=True, euclidean=True),
        description="Knowledge, findings, and determinations.",
    ),
    ModalParseProfile(
        family=ModalLogicFamily.DOXASTIC,
        system=ModalSystem.KD45,
        operators=(
            _op(
                "B",
                ("believes", "belief"),
                (
                    "believe",
                    "believed",
                    "belief",
                    "believes",
                    "intend",
                    "intended",
                    "intends",
                    "intent to",
                    "with intent to",
                    "with the intent to",
                    "reasonably believes",
                    "suspect",
                    "suspected",
                    "suspects",
                ),
                (ModalSystem.KD45,),
            ),
        ),
        semantics=ModalSemanticsSpec(serial=True, transitive=True, euclidean=True),
        description="Belief and intent-style legal states.",
    ),
    ModalParseProfile(
        family=ModalLogicFamily.DYNAMIC,
        system=ModalSystem.PDL,
        operators=(
            _op("[a]", ("after_action",), ("files", "serves", "transfers", "terminates", "enforces"), (ModalSystem.PDL, ModalSystem.STIT)),
        ),
        semantics=ModalSemanticsSpec(action_transition=True),
        description="Action transitions and pre/postconditions.",
    ),
    ModalParseProfile(
        family=ModalLogicFamily.CONDITIONAL_NORMATIVE,
        system=ModalSystem.KD,
        operators=(
            _op(
                "O|",
                ("conditional_obligation",),
                (
                    "if",
                    "unless",
                    "except",
                    "provided that",
                    "subject to",
                    "as provided by",
                    "as otherwise provided in",
                    "as otherwise provided by",
                    "as otherwise provided under",
                    "except as otherwise provided",
                    "except as provided in",
                    "except as provided by",
                    "does not affect",
                    "except to the extent",
                    "to the extent provided",
                    "to the extent that",
                    "in the event that",
                    "in the case of",
                    "provided, however, that",
                    "only if",
                    "for purposes of",
                    "for the purposes of",
                    "in accordance with",
                    "notwithstanding",
                    "pursuant to",
                    "under terms and conditions",
                    "under such terms and conditions",
                    "on such terms and conditions",
                    "upon terms and conditions",
                    "upon such terms and conditions",
                    "subject to terms and conditions",
                    "subject to such terms and conditions",
                    "subject to the terms and conditions",
                    "subject only to",
                    "subject, however, to",
                    "subject however to",
                    "with respect to",
                    "insofar as",
                    "insofar as practicable",
                ),
                (ModalSystem.KD,),
            ),
        ),
        semantics=ModalSemanticsSpec(serial=True),
        description="Conditions, exceptions, provisos, and scoped norms.",
    ),
    ModalParseProfile(
        family=ModalLogicFamily.FRAME,
        system=ModalSystem.FRAME_BM25,
        operators=(
            _op("Frame", ("ontology_frame",), ("is a", "part of", "administered by", "jurisdiction", "authority"), (ModalSystem.FRAME_BM25,)),
        ),
        semantics=ModalSemanticsSpec(ontology_frame_grounded=True),
        description="Ontology-grounded frame logic selected with BM25.",
    ),
    ModalParseProfile(
        family=ModalLogicFamily.HYBRID,
        system=ModalSystem.HYBRID,
        operators=(),
        description="Composed profiles for statutory clauses with mixed modal content.",
    ),
)


class ModalRegistry:
    """Lookup table for modal parse profiles."""

    def __init__(self, profiles: Iterable[ModalParseProfile] = DEFAULT_MODAL_PROFILES) -> None:
        self._profiles: Dict[str, ModalParseProfile] = {
            profile.profile_id: profile for profile in profiles
        }
        self._by_family: Dict[ModalLogicFamily, ModalParseProfile] = {
            profile.family: profile for profile in profiles
        }

    def get_profile(
        self,
        family: ModalLogicFamily | str,
        system: Optional[ModalSystem | str] = None,
    ) -> ModalParseProfile:
        """Get a profile by family, optionally constrained by system."""
        resolved_family = family if isinstance(family, ModalLogicFamily) else ModalLogicFamily(str(family))
        if system is None:
            return self._by_family[resolved_family]
        resolved_system = system if isinstance(system, ModalSystem) else ModalSystem(str(system))
        return self._profiles[f"{resolved_family.value}:{resolved_system.value}"]

    def all_profiles(self) -> Tuple[ModalParseProfile, ...]:
        """Return all profiles in deterministic order."""
        return tuple(sorted(self._profiles.values(), key=lambda profile: profile.profile_id))

    def to_dict(self) -> Mapping[str, object]:
        """Return a stable JSON-ready registry mapping."""
        return {profile.profile_id: profile.to_dict() for profile in self.all_profiles()}


def is_normative_modal_family(family: ModalLogicFamily | str) -> bool:
    """Return whether a modal family encodes normative legal force."""
    if isinstance(family, ModalLogicFamily):
        resolved = family
    else:
        try:
            resolved = ModalLogicFamily(str(family))
        except ValueError:
            return False
    return resolved in NORMATIVE_MODAL_FAMILIES


def supports_signal_free_adaptive_ambiguity_pair(
    predicted_family: ModalLogicFamily | str,
    target_family: ModalLogicFamily | str,
) -> bool:
    """Return whether an adaptive pair should emit ambiguity without target cues."""
    resolved_target_family = _resolve_modal_family_name(target_family)
    return (
        resolved_target_family in compiler_ambiguity_policy_targets(predicted_family)
        or is_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            resolved_target_family,
        )
        or resolved_target_family in compiler_required_adaptive_ambiguity_targets(
            predicted_family
        )
    )


def compiler_ambiguity_policy_targets(
    predicted_family: ModalLogicFamily | str,
) -> Tuple[str, ...]:
    """Return ordered targets covered by the compiler_ambiguity policy bundle."""
    resolved_predicted_family = _resolve_modal_family_name(predicted_family)
    return tuple(
        target_family
        for source_family, target_family in COMPILER_AMBIGUITY_POLICY_FAMILY_PAIRS
        if source_family == resolved_predicted_family
    )


def signal_free_adaptive_ambiguity_targets(
    predicted_family: ModalLogicFamily | str,
) -> Tuple[str, ...]:
    """Return ordered adaptive-ambiguity targets requiring signal-free handling."""
    resolved_predicted_family = _resolve_modal_family_name(predicted_family)
    return tuple(
        target_family
        for source_family, target_family in SIGNAL_FREE_ADAPTIVE_AMBIGUITY_FAMILY_PAIRS
        if source_family == resolved_predicted_family
    )


def is_signal_free_adaptive_ambiguity_pair(
    predicted_family: ModalLogicFamily | str,
    target_family: ModalLogicFamily | str,
) -> bool:
    """Return whether a pair is in the signal-free adaptive ambiguity policy."""
    resolved_predicted_family = _resolve_modal_family_name(predicted_family)
    resolved_target_family = _resolve_modal_family_name(target_family)
    return (
        resolved_predicted_family,
        resolved_target_family,
    ) in SIGNAL_FREE_ADAPTIVE_AMBIGUITY_FAMILY_PAIRS


def priority_signal_free_adaptive_ambiguity_targets(
    predicted_family: ModalLogicFamily | str,
) -> Tuple[str, ...]:
    """Return ordered high-priority adaptive-ambiguity targets."""
    resolved_predicted_family = _resolve_modal_family_name(predicted_family)
    return tuple(
        target_family
        for source_family, target_family in PRIORITY_SIGNAL_FREE_ADAPTIVE_AMBIGUITY_FAMILY_PAIRS
        if source_family == resolved_predicted_family
    )


def compiler_required_adaptive_ambiguity_targets(
    predicted_family: ModalLogicFamily | str,
) -> Tuple[str, ...]:
    """Return ordered compiler-required adaptive ambiguity targets."""
    resolved_predicted_family = _resolve_modal_family_name(predicted_family)
    return tuple(
        target_family
        for source_family, target_family in COMPILER_REQUIRED_ADAPTIVE_AMBIGUITY_FAMILY_PAIRS
        if source_family == resolved_predicted_family
    )


def is_compiler_required_adaptive_ambiguity_pair(
    predicted_family: ModalLogicFamily | str,
    target_family: ModalLogicFamily | str,
) -> bool:
    """Return whether a pair is in the compiler-required ambiguity policy bundle."""
    resolved_predicted_family = _resolve_modal_family_name(predicted_family)
    resolved_target_family = _resolve_modal_family_name(target_family)
    return (
        resolved_predicted_family,
        resolved_target_family,
    ) in COMPILER_REQUIRED_ADAPTIVE_AMBIGUITY_FAMILY_PAIRS


def is_compiler_ambiguity_policy_pair(
    predicted_family: ModalLogicFamily | str,
    target_family: ModalLogicFamily | str,
) -> bool:
    """Return whether a pair is part of the compiler_ambiguity synthesis bundle."""
    resolved_predicted_family = _resolve_modal_family_name(predicted_family)
    resolved_target_family = _resolve_modal_family_name(target_family)
    return (
        resolved_predicted_family,
        resolved_target_family,
    ) in COMPILER_AMBIGUITY_POLICY_FAMILY_PAIRS


def is_priority_signal_free_adaptive_ambiguity_pair(
    predicted_family: ModalLogicFamily | str,
    target_family: ModalLogicFamily | str,
) -> bool:
    """Return whether a pair is part of the highest-priority adaptive ambiguity policy."""
    resolved_predicted_family = _resolve_modal_family_name(predicted_family)
    resolved_target_family = _resolve_modal_family_name(target_family)
    return (
        resolved_predicted_family,
        resolved_target_family,
    ) in PRIORITY_SIGNAL_FREE_ADAPTIVE_AMBIGUITY_FAMILY_PAIRS


def prefers_contested_zero_margin_adaptive_ambiguity_pair(
    predicted_family: ModalLogicFamily | str,
    target_family: ModalLogicFamily | str,
) -> bool:
    """Return whether a zero-margin adaptive pair should be contested, not outvoted."""
    resolved_predicted_family = _resolve_modal_family_name(predicted_family)
    resolved_target_family = _resolve_modal_family_name(target_family)
    return (
        resolved_predicted_family,
        resolved_target_family,
    ) in ZERO_MARGIN_CONTESTED_ADAPTIVE_AMBIGUITY_FAMILY_PAIRS


def _resolve_modal_family_name(family: ModalLogicFamily | str) -> str:
    if isinstance(family, ModalLogicFamily):
        return family.value
    resolved = str(family).strip()
    if not resolved:
        return ""
    candidate_tokens: list[str] = []
    seen_tokens: set[str] = set()

    def _remember(token: str) -> None:
        normalized = str(token).strip()
        if not normalized or normalized in seen_tokens:
            return
        seen_tokens.add(normalized)
        candidate_tokens.append(normalized)

    leaf_dot = resolved.rsplit(".", maxsplit=1)[-1].strip()
    leaf_colon = leaf_dot.rsplit(":", maxsplit=1)[-1].strip()
    leaf_slash = leaf_colon.rsplit("/", maxsplit=1)[-1].strip()
    leaf_pipe = leaf_slash.rsplit("|", maxsplit=1)[-1].strip()
    split_tokens: list[str] = []
    delimiters = ("->", ".", ":", "/", "|")
    for delimiter in delimiters:
        if delimiter not in resolved:
            continue
        split_tokens.extend(
            part.strip()
            for part in resolved.split(delimiter)
            if str(part).strip()
        )
    for token in (
        resolved,
        leaf_dot,
        leaf_colon,
        leaf_slash,
        leaf_pipe,
        *split_tokens,
    ):
        _remember(token)
        lowered = token.lower()
        _remember(lowered)
        _remember(lowered.replace("-", "_").replace(" ", "_"))

    for token in candidate_tokens:
        try:
            return ModalLogicFamily(token).value
        except ValueError:
            continue
    return resolved.lower()


DEFAULT_MODAL_REGISTRY = ModalRegistry()


__all__ = [
    "DEFAULT_MODAL_PROFILES",
    "DEFAULT_MODAL_REGISTRY",
    "COMPILER_AMBIGUITY_POLICY_FAMILY_PAIRS",
    "COMPILER_AMBIGUITY_CORE_FAMILY_PAIRS",
    "COMPILER_REQUIRED_ADAPTIVE_AMBIGUITY_FAMILY_PAIRS",
    "compiler_ambiguity_policy_targets",
    "is_compiler_ambiguity_policy_pair",
    "ZERO_MARGIN_CONTESTED_ADAPTIVE_AMBIGUITY_FAMILY_PAIRS",
    "compiler_required_adaptive_ambiguity_targets",
    "is_compiler_required_adaptive_ambiguity_pair",
    "NORMATIVE_MODAL_FAMILIES",
    "PRIORITY_SIGNAL_FREE_ADAPTIVE_AMBIGUITY_FAMILY_PAIRS",
    "SIGNAL_FREE_ADAPTIVE_AMBIGUITY_FAMILY_PAIRS",
    "is_priority_signal_free_adaptive_ambiguity_pair",
    "ModalLogicFamily",
    "ModalOperatorSpec",
    "ModalParseProfile",
    "ModalRegistry",
    "ModalSemanticsSpec",
    "ModalSystem",
    "is_normative_modal_family",
    "is_signal_free_adaptive_ambiguity_pair",
    "prefers_contested_zero_margin_adaptive_ambiguity_pair",
    "priority_signal_free_adaptive_ambiguity_targets",
    "signal_free_adaptive_ambiguity_targets",
    "supports_signal_free_adaptive_ambiguity_pair",
]
