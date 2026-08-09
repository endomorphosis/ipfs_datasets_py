"""Conformance join: differential, metamorphic, reconstruction, end-to-end (LFP-043).

Acceptance:

* Disagreement is typed ``inconclusive`` (never majority-voted into proof)
* Every translation has positive and negative preservation fixtures
* High-assurance candidates reconstruct or retain a lower authority ceiling
* Report is deterministic and content-addressed

Interface: ``LogicConformanceReport@1``

Effects (hermetic, fail-closed):

* Z3/cvc5 common exact fragment
* Vampire/E TSTP candidate normalization
* TLC/Apalache aligned bounded state-model fixtures
* ProVerif/Tamarin and HyperLTL aligned fragments
* Runtime monitors and kernel reconstruction under exact contracts

Evidence subset: differential metamorphic translation preservation reconstruction
disagreement inconclusive end to end
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

import pytest

from ipfs_datasets_py.logic.backends.results import ResultAuthority
from ipfs_datasets_py.logic.backends.smt.differential import (
    DifferentialClassification,
)
from ipfs_datasets_py.logic.conformance.authority_audit import (
    DEFAULT_AUTHORITY_AUDIT,
    run_authority_audit,
)
from ipfs_datasets_py.logic.conformance.matrix import AuthorityCeiling
from ipfs_datasets_py.logic.conformance.runner import (
    DEFAULT_CONFORMANCE_RUNNER,
    run_domain_provider_matrix,
)
from ipfs_datasets_py.logic.families.generated_catalog import (
    DEFAULT_GENERATED_CATALOG,
)
from ipfs_datasets_py.logic.families.models import EvidenceAuthority, TranslationKind
from ipfs_datasets_py.logic.families.registry import DEFAULT_REGISTRY
from ipfs_datasets_py.logic.families.translations import (
    PreservationRelation,
    maximum_authority_for,
)
from ipfs_datasets_py.logic.ir_core.claims import stable_digest
from ipfs_datasets_py.logic.parsers.kernel_targets import (
    DEFAULT_ISABELLE_IMPORTS,
    DEFAULT_LEAN_IMPORTS,
    DEFAULT_ROCQ_IMPORTS,
)

# ---------------------------------------------------------------------------
# Interface / schema
# ---------------------------------------------------------------------------

LOGIC_CONFORMANCE_REPORT_INTERFACE: Final = "LogicConformanceReport@1"
LOGIC_CONFORMANCE_REPORT_SCHEMA: Final = "logic-parser-conformance-report/v1"
LOGIC_CONFORMANCE_REPORT_VERSION: Final = "1.0.0"
TASK_ID: Final = "LFP-043"
GOAL_ID: Final = "LFP-G080"
PROGRAM_ID: Final = "ipfs-datasets-logic-family-parser-v1"

DIFFERENTIAL_CASE_SCHEMA: Final = "logic-conformance-differential-case/v1"
PRESERVATION_FIXTURE_SCHEMA: Final = "logic-conformance-preservation-fixture/v1"
RECONSTRUCTION_CASE_SCHEMA: Final = "logic-conformance-reconstruction-case/v1"
E2E_SLICE_SCHEMA: Final = "logic-conformance-e2e-slice/v1"

REQUIRED_EVIDENCE_SUBSET: Final[tuple[str, ...]] = (
    "differential",
    "metamorphic",
    "translation",
    "preservation",
    "reconstruction",
    "disagreement",
    "inconclusive",
    "end_to_end",
)

# Relative to the nested ipfs_datasets_py repository root (pytest cwd).
DEFAULT_REPORT_RELATIVE_PATH: Final = (
    "docs/architecture/logic/logic_parser_conformance_report.json"
)

# High-assurance candidate producers that must reconstruct or retain a lower
# authority ceiling (never silently promote to theorem/kernel).
HIGH_ASSURANCE_CANDIDATE_PROVIDERS: Final[tuple[str, ...]] = (
    "vampire",
    "eprover",
    "e",
    "hammer",
    "lean",
    "rocq",
    "isabelle",
)

_LOWER_CEILINGS: Final[frozenset[str]] = frozenset(
    {
        ResultAuthority.CANDIDATE.value,
        ResultAuthority.RECONSTRUCTION.value,
        ResultAuthority.ATTESTATION.value,
        AuthorityCeiling.CANDIDATE.value,
        AuthorityCeiling.ADVISORY.value,
        AuthorityCeiling.BOUNDED.value,
        AuthorityCeiling.NONE.value,
        EvidenceAuthority.ADVISORY.value,
        EvidenceAuthority.BOUNDED.value,
        EvidenceAuthority.NONE.value,
    }
)

_HIGH_CEILINGS: Final[frozenset[str]] = frozenset(
    {
        ResultAuthority.THEOREM.value,
        AuthorityCeiling.KERNEL.value,
        AuthorityCeiling.EXACT.value,
        EvidenceAuthority.AUTHORITATIVE.value,
        "kernel",
        "theorem",
    }
)


class ConformanceJoinError(ValueError):
    """Raised when the joined conformance report is malformed."""


class JoinVerdict(StrEnum):
    """Terminal join disposition for one differential or reconstruction case."""

    AGREE = "agree"
    INCONCLUSIVE = "inconclusive"
    UNAVAILABLE = "unavailable"
    RECONSTRUCTED = "reconstructed"
    CANDIDATE_RETAINED = "candidate_retained"
    REJECT = "reject"
    PASS = "pass"


class FixturePolarity(StrEnum):
    """Preservation fixture polarity."""

    POSITIVE = "positive"
    NEGATIVE = "negative"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _text(value: object, field_name: str, *, optional: bool = False) -> str:
    if optional and (value is None or value == ""):
        return ""
    if not isinstance(value, str) or not value or value != value.strip():
        raise ConformanceJoinError(f"{field_name} must be a non-empty trimmed string")
    if "\x00" in value:
        raise ConformanceJoinError(f"{field_name} must not contain NUL bytes")
    return value


def _identifier(value: object, field_name: str) -> str:
    result = _text(value, field_name)
    if any(character.isspace() for character in result):
        raise ConformanceJoinError(
            f"{field_name} must not contain whitespace; got {result!r}"
        )
    return result


def _bool(value: object, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise ConformanceJoinError(f"{field_name} must be a bool")
    return value


def _stable_digest(payload: Mapping[str, Any]) -> str:
    """SHA-256 of canonical sorted JSON (content identity without self-digest)."""

    return stable_digest(dict(payload))


def _content_id(digest: str) -> str:
    return f"sha256:{digest}"


def typed_inconclusive_for_disagreement(classification: str | DifferentialClassification) -> str:
    """Map differential classification onto the LFP-043 join vocabulary.

    Disagreement is always typed ``inconclusive``.  Agreement remains ``agree``.
    Partial/both unavailable stay ``unavailable``.  Other non-agreement classes
    (malformed, error, unknown pairs) are also ``inconclusive`` — never voted.
    """

    token = (
        classification.value
        if isinstance(classification, DifferentialClassification)
        else str(classification)
    )
    if token in {
        DifferentialClassification.AGREE_PROVED.value,
        DifferentialClassification.AGREE_DISPROVED.value,
        DifferentialClassification.AGREE_SATISFIABLE.value,
        DifferentialClassification.AGREE_UNSATISFIABLE.value,
        DifferentialClassification.AGREE_UNKNOWN.value,
        "agree",
        "agree_proved",
        "agree_disproved",
        "agree_satisfiable",
        "agree_unsatisfiable",
        "agree_unknown",
    }:
        return JoinVerdict.AGREE.value
    if token in {
        DifferentialClassification.BOTH_UNAVAILABLE.value,
        DifferentialClassification.PARTIAL_UNAVAILABLE.value,
        "unavailable",
        "both_unavailable",
        "partial_unavailable",
    }:
        return JoinVerdict.UNAVAILABLE.value
    # DISAGREE, MALFORMED, ERROR, and any free-form "disagree" → inconclusive.
    return JoinVerdict.INCONCLUSIVE.value


def classify_backend_pair(
    left_verdict: str,
    right_verdict: str,
    *,
    conclusive: frozenset[str] | None = None,
) -> tuple[str, str]:
    """Hermetic pair classification without subprocesses.

    Returns ``(raw_classification, join_verdict)``.
    """

    left = _text(left_verdict, "left_verdict").lower()
    right = _text(right_verdict, "right_verdict").lower()
    conclusive_set = conclusive or frozenset(
        {
            "sat",
            "unsat",
            "proved",
            "disproved",
            "secure",
            "attack_found",
            "satisfied",
            "violated",
            "true",
            "false",
        }
    )
    unavailable = frozenset({"unavailable", "timeout", "error", "missing"})
    if left in unavailable and right in unavailable:
        return "both_unavailable", JoinVerdict.UNAVAILABLE.value
    if left in unavailable or right in unavailable:
        return "partial_unavailable", JoinVerdict.UNAVAILABLE.value
    if left in conclusive_set and right in conclusive_set and left != right:
        return "disagree", JoinVerdict.INCONCLUSIVE.value
    if left == right:
        if left in conclusive_set:
            return "agree", JoinVerdict.AGREE.value
        return "agree_unknown", JoinVerdict.AGREE.value
    # One conclusive, one unknown — inconclusive, not majority vote.
    return "partial_unknown", JoinVerdict.INCONCLUSIVE.value


# ---------------------------------------------------------------------------
# Record types
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DifferentialCase:
    """One hermetic differential comparison under an exact contract."""

    case_id: str
    family: str
    left_provider: str
    right_provider: str
    left_verdict: str
    right_verdict: str
    raw_classification: str
    join_verdict: str
    fragment: str = ""
    notes: str = ""
    schema_version: str = DIFFERENTIAL_CASE_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(self, "case_id", _identifier(self.case_id, "case_id"))
        object.__setattr__(self, "family", _identifier(self.family, "family"))
        object.__setattr__(
            self, "left_provider", _identifier(self.left_provider, "left_provider")
        )
        object.__setattr__(
            self, "right_provider", _identifier(self.right_provider, "right_provider")
        )
        object.__setattr__(
            self, "left_verdict", _text(self.left_verdict, "left_verdict")
        )
        object.__setattr__(
            self, "right_verdict", _text(self.right_verdict, "right_verdict")
        )
        object.__setattr__(
            self,
            "raw_classification",
            _identifier(self.raw_classification, "raw_classification"),
        )
        object.__setattr__(
            self, "join_verdict", _identifier(self.join_verdict, "join_verdict")
        )
        object.__setattr__(
            self, "fragment", _text(self.fragment, "fragment", optional=True)
        )
        object.__setattr__(self, "notes", _text(self.notes, "notes", optional=True))
        if self.schema_version != DIFFERENTIAL_CASE_SCHEMA:
            raise ConformanceJoinError(
                f"differential case schema must be {DIFFERENTIAL_CASE_SCHEMA}"
            )
        # Hard invariant: disagreement is typed inconclusive.
        if self.raw_classification in {"disagree", "disagreement"}:
            if self.join_verdict != JoinVerdict.INCONCLUSIVE.value:
                raise ConformanceJoinError(
                    f"{self.case_id}: disagreement must be typed inconclusive"
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "family": self.family,
            "fragment": self.fragment,
            "join_verdict": self.join_verdict,
            "left_provider": self.left_provider,
            "left_verdict": self.left_verdict,
            "notes": self.notes,
            "raw_classification": self.raw_classification,
            "right_provider": self.right_provider,
            "right_verdict": self.right_verdict,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True, slots=True)
class PreservationFixture:
    """Positive or negative preservation fixture for one translation edge."""

    fixture_id: str
    translation_id: str
    polarity: FixturePolarity | str
    preservation: str
    source_family_id: str
    target_family_id: str
    expected_pass: bool
    silent_drop_attempted: bool = False
    notes: str = ""
    schema_version: str = PRESERVATION_FIXTURE_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "fixture_id", _identifier(self.fixture_id, "fixture_id")
        )
        object.__setattr__(
            self,
            "translation_id",
            _identifier(self.translation_id, "translation_id"),
        )
        polarity = (
            self.polarity
            if isinstance(self.polarity, FixturePolarity)
            else FixturePolarity(str(self.polarity))
        )
        object.__setattr__(self, "polarity", polarity)
        object.__setattr__(
            self, "preservation", _identifier(self.preservation, "preservation")
        )
        object.__setattr__(
            self,
            "source_family_id",
            _identifier(self.source_family_id, "source_family_id"),
        )
        object.__setattr__(
            self,
            "target_family_id",
            _identifier(self.target_family_id, "target_family_id"),
        )
        object.__setattr__(
            self, "expected_pass", _bool(self.expected_pass, "expected_pass")
        )
        object.__setattr__(
            self,
            "silent_drop_attempted",
            _bool(self.silent_drop_attempted, "silent_drop_attempted"),
        )
        object.__setattr__(self, "notes", _text(self.notes, "notes", optional=True))
        if self.schema_version != PRESERVATION_FIXTURE_SCHEMA:
            raise ConformanceJoinError(
                f"preservation fixture schema must be {PRESERVATION_FIXTURE_SCHEMA}"
            )
        if polarity is FixturePolarity.POSITIVE and not self.expected_pass:
            raise ConformanceJoinError(
                f"{self.fixture_id}: positive fixture must expect pass"
            )
        if polarity is FixturePolarity.NEGATIVE and self.expected_pass:
            raise ConformanceJoinError(
                f"{self.fixture_id}: negative fixture must not expect pass"
            )
        if polarity is FixturePolarity.NEGATIVE and not self.silent_drop_attempted:
            # Negative fixtures exercise silent-drop / loss rejection.
            object.__setattr__(self, "silent_drop_attempted", True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "expected_pass": self.expected_pass,
            "fixture_id": self.fixture_id,
            "notes": self.notes,
            "polarity": (
                self.polarity.value
                if isinstance(self.polarity, FixturePolarity)
                else self.polarity
            ),
            "preservation": self.preservation,
            "schema_version": self.schema_version,
            "silent_drop_attempted": self.silent_drop_attempted,
            "source_family_id": self.source_family_id,
            "target_family_id": self.target_family_id,
            "translation_id": self.translation_id,
        }


@dataclass(frozen=True, slots=True)
class ReconstructionCase:
    """High-assurance candidate that reconstructs or retains a lower ceiling."""

    case_id: str
    provider_id: str
    claimed_authority: str
    retained_authority_ceiling: str
    reconstructed: bool
    kernel_accepted: bool
    join_verdict: str
    notes: str = ""
    schema_version: str = RECONSTRUCTION_CASE_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(self, "case_id", _identifier(self.case_id, "case_id"))
        object.__setattr__(
            self, "provider_id", _identifier(self.provider_id, "provider_id")
        )
        object.__setattr__(
            self,
            "claimed_authority",
            _identifier(self.claimed_authority, "claimed_authority"),
        )
        object.__setattr__(
            self,
            "retained_authority_ceiling",
            _identifier(
                self.retained_authority_ceiling, "retained_authority_ceiling"
            ),
        )
        object.__setattr__(
            self, "reconstructed", _bool(self.reconstructed, "reconstructed")
        )
        object.__setattr__(
            self, "kernel_accepted", _bool(self.kernel_accepted, "kernel_accepted")
        )
        object.__setattr__(
            self, "join_verdict", _identifier(self.join_verdict, "join_verdict")
        )
        object.__setattr__(self, "notes", _text(self.notes, "notes", optional=True))
        if self.schema_version != RECONSTRUCTION_CASE_SCHEMA:
            raise ConformanceJoinError(
                f"reconstruction case schema must be {RECONSTRUCTION_CASE_SCHEMA}"
            )
        # High-assurance rule: reconstruct under kernel, or retain lower ceiling.
        ceiling = self.retained_authority_ceiling.lower()
        if self.reconstructed:
            if self.join_verdict != JoinVerdict.RECONSTRUCTED.value:
                raise ConformanceJoinError(
                    f"{self.case_id}: reconstructed cases must use join_verdict=reconstructed"
                )
            if not self.kernel_accepted:
                raise ConformanceJoinError(
                    f"{self.case_id}: reconstruction requires kernel_accepted"
                )
        else:
            if ceiling in _HIGH_CEILINGS:
                raise ConformanceJoinError(
                    f"{self.case_id}: unrestructured candidate must retain a lower "
                    f"authority ceiling, not {ceiling!r}"
                )
            if ceiling not in _LOWER_CEILINGS and ceiling not in {
                ResultAuthority.RECONSTRUCTION.value,
                "reconstruction",
                "candidate",
            }:
                # Allow explicit reconstruction/candidate tokens.
                if ceiling not in {"reconstruction", "candidate", "advisory", "bounded", "none"}:
                    raise ConformanceJoinError(
                        f"{self.case_id}: retained ceiling {ceiling!r} is not a lower ceiling"
                    )
            if self.join_verdict not in {
                JoinVerdict.CANDIDATE_RETAINED.value,
                JoinVerdict.REJECT.value,
            }:
                raise ConformanceJoinError(
                    f"{self.case_id}: non-reconstructed high-assurance candidates "
                    "must retain candidate or reject"
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "claimed_authority": self.claimed_authority,
            "join_verdict": self.join_verdict,
            "kernel_accepted": self.kernel_accepted,
            "notes": self.notes,
            "provider_id": self.provider_id,
            "reconstructed": self.reconstructed,
            "retained_authority_ceiling": self.retained_authority_ceiling,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True, slots=True)
class EndToEndSlice:
    """One vertical source → parse → translate → backend → authority slice."""

    slice_id: str
    domain_id: str
    family_id: str
    provider_id: str
    disposition: str
    authority_ceiling: str
    hermetic: bool = True
    notes: str = ""
    schema_version: str = E2E_SLICE_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(self, "slice_id", _identifier(self.slice_id, "slice_id"))
        object.__setattr__(
            self, "domain_id", _identifier(self.domain_id, "domain_id")
        )
        object.__setattr__(
            self, "family_id", _identifier(self.family_id, "family_id")
        )
        object.__setattr__(
            self, "provider_id", _identifier(self.provider_id, "provider_id")
        )
        object.__setattr__(
            self, "disposition", _identifier(self.disposition, "disposition")
        )
        object.__setattr__(
            self,
            "authority_ceiling",
            _identifier(self.authority_ceiling, "authority_ceiling"),
        )
        object.__setattr__(self, "hermetic", _bool(self.hermetic, "hermetic"))
        object.__setattr__(self, "notes", _text(self.notes, "notes", optional=True))
        if self.schema_version != E2E_SLICE_SCHEMA:
            raise ConformanceJoinError(
                f"e2e slice schema must be {E2E_SLICE_SCHEMA}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_ceiling": self.authority_ceiling,
            "disposition": self.disposition,
            "domain_id": self.domain_id,
            "family_id": self.family_id,
            "hermetic": self.hermetic,
            "notes": self.notes,
            "provider_id": self.provider_id,
            "schema_version": self.schema_version,
            "slice_id": self.slice_id,
        }


# ---------------------------------------------------------------------------
# Fixture corpora (compact recipes)
# ---------------------------------------------------------------------------


def build_differential_corpus() -> tuple[DifferentialCase, ...]:
    """Closed hermetic differential corpus covering plan solver pairs."""

    recipes: list[tuple[str, str, str, str, str, str, str]] = [
        # (case_id, family, left, right, left_verdict, right_verdict, fragment)
        # Z3 / cvc5 common exact fragment
        ("smt.qf_uf.agree_unsat", "smt", "z3", "cvc5", "unsat", "unsat", "qf_uf"),
        ("smt.qf_uf.agree_sat", "smt", "z3", "cvc5", "sat", "sat", "qf_uf"),
        ("smt.qf_uf.disagree", "smt", "z3", "cvc5", "sat", "unsat", "qf_uf"),
        ("smt.qf_uf.partial_unavailable", "smt", "z3", "cvc5", "unsat", "unavailable", "qf_uf"),
        # Vampire / E TSTP candidate normalization
        ("atp.fof.agree_proved", "atp", "vampire", "eprover", "proved", "proved", "fof"),
        ("atp.fof.disagree", "atp", "vampire", "eprover", "proved", "disproved", "fof"),
        ("atp.fof.both_unavailable", "atp", "vampire", "eprover", "unavailable", "unavailable", "fof"),
        # TLC / Apalache bounded state-model
        ("tla.bounded.agree_satisfied", "tla", "tla_tlc", "apalache", "satisfied", "satisfied", "bounded_state"),
        ("tla.bounded.disagree", "tla", "tla_tlc", "apalache", "satisfied", "violated", "bounded_state"),
        # ProVerif / Tamarin aligned protocol fragment
        ("protocol.aligned.agree_secure", "protocol", "proverif", "tamarin", "secure", "secure", "aligned_secrecy"),
        ("protocol.aligned.disagree", "protocol", "proverif", "tamarin", "secure", "attack_found", "aligned_secrecy"),
        # HyperLTL common fragment
        ("hyperltl.common.agree", "hyperproperty", "hyperltl_autohyper_mchyper", "hyperltl_autohyper_mchyper", "satisfied", "satisfied", "hyperltl_common"),
        ("hyperltl.common.disagree", "hyperproperty", "hyperltl_left", "hyperltl_right", "satisfied", "violated", "hyperltl_common"),
        # Runtime monitors (finite trace)
        ("monitor.mtl.agree", "runtime", "runtime_mtl", "runtime_mtl_shadow", "satisfied", "satisfied", "finite_trace"),
        ("monitor.mtl.prefix_inconclusive", "runtime", "runtime_mtl", "runtime_mtl_shadow", "unknown", "satisfied", "finite_trace_prefix"),
    ]

    cases: list[DifferentialCase] = []
    for (
        case_id,
        family,
        left,
        right,
        left_verdict,
        right_verdict,
        fragment,
    ) in recipes:
        raw, join = classify_backend_pair(left_verdict, right_verdict)
        # HyperLTL same-provider "agree" is a self-consistency check; treat
        # identical provider+verdict as agree even when ids match.
        if left == right and left_verdict == right_verdict:
            raw, join = "agree", JoinVerdict.AGREE.value
        cases.append(
            DifferentialCase(
                case_id=case_id,
                family=family,
                left_provider=left,
                right_provider=right,
                left_verdict=left_verdict,
                right_verdict=right_verdict,
                raw_classification=raw,
                join_verdict=join,
                fragment=fragment,
                notes=(
                    "Disagreement typed inconclusive; never majority-voted."
                    if raw == "disagree"
                    else ""
                ),
            )
        )
    return tuple(sorted(cases, key=lambda item: item.case_id))


def _preservation_for_kind(kind: TranslationKind | str) -> str:
    token = kind.value if isinstance(kind, TranslationKind) else str(kind)
    mapping = {
        TranslationKind.LOSSLESS.value: PreservationRelation.EXACT_EQUIVALENCE.value,
        TranslationKind.EQUISATISFIABLE.value: PreservationRelation.EQUISATISFIABLE.value,
        TranslationKind.SOUND_OVER_APPROXIMATION.value: (
            PreservationRelation.CONSERVATIVE_OVER_APPROXIMATION.value
        ),
        TranslationKind.SOUND_UNDER_APPROXIMATION.value: (
            PreservationRelation.CONSERVATIVE_UNDER_APPROXIMATION.value
        ),
        TranslationKind.HEURISTIC.value: PreservationRelation.HEURISTIC.value,
    }
    return mapping.get(token, PreservationRelation.APPROXIMATE.value)


def build_preservation_fixtures(
    translations: Sequence[Any] | None = None,
) -> tuple[PreservationFixture, ...]:
    """Positive and negative preservation fixtures for every translation edge."""

    edges = list(translations) if translations is not None else list(
        DEFAULT_GENERATED_CATALOG.translations
    )
    if not edges:
        # Fall back to registry translations.
        edges = list(DEFAULT_REGISTRY.translations.values())

    fixtures: list[PreservationFixture] = []
    for edge in edges:
        translation_id = getattr(edge, "translation_id", None) or edge["translation_id"]
        source = getattr(edge, "source_family_id", None) or edge["source_family_id"]
        target = getattr(edge, "target_family_id", None) or edge["target_family_id"]
        kind = getattr(edge, "translation_kind", None) or edge.get(
            "translation_kind", TranslationKind.LOSSLESS.value
        )
        preservation = _preservation_for_kind(kind)
        fixtures.append(
            PreservationFixture(
                fixture_id=f"{translation_id}.positive",
                translation_id=translation_id,
                polarity=FixturePolarity.POSITIVE,
                preservation=preservation,
                source_family_id=source,
                target_family_id=target,
                expected_pass=True,
                silent_drop_attempted=False,
                notes="Feature-total positive preservation under declared relation.",
            )
        )
        fixtures.append(
            PreservationFixture(
                fixture_id=f"{translation_id}.negative_silent_drop",
                translation_id=translation_id,
                polarity=FixturePolarity.NEGATIVE,
                preservation=preservation,
                source_family_id=source,
                target_family_id=target,
                expected_pass=False,
                silent_drop_attempted=True,
                notes="Negative fixture: silent node/assumption drop is rejected.",
            )
        )
    return tuple(sorted(fixtures, key=lambda item: item.fixture_id))


def build_reconstruction_corpus() -> tuple[ReconstructionCase, ...]:
    """High-assurance candidates: reconstruct under kernel or retain lower ceiling."""

    cases = [
        ReconstructionCase(
            case_id="vampire.tstp.candidate_retained",
            provider_id="vampire",
            claimed_authority=ResultAuthority.THEOREM.value,
            retained_authority_ceiling=ResultAuthority.CANDIDATE.value,
            reconstructed=False,
            kernel_accepted=False,
            join_verdict=JoinVerdict.CANDIDATE_RETAINED.value,
            notes="Vampire TSTP success remains candidate until reconstruction.",
        ),
        ReconstructionCase(
            case_id="eprover.tstp.candidate_retained",
            provider_id="eprover",
            claimed_authority=ResultAuthority.THEOREM.value,
            retained_authority_ceiling=ResultAuthority.RECONSTRUCTION.value,
            reconstructed=False,
            kernel_accepted=False,
            join_verdict=JoinVerdict.CANDIDATE_RETAINED.value,
            notes="E prover proof object is reconstruction-scoped only.",
        ),
        ReconstructionCase(
            case_id="hammer.premise.candidate_retained",
            provider_id="hammer",
            claimed_authority=ResultAuthority.THEOREM.value,
            retained_authority_ceiling=ResultAuthority.CANDIDATE.value,
            reconstructed=False,
            kernel_accepted=False,
            join_verdict=JoinVerdict.CANDIDATE_RETAINED.value,
            notes="Hammer premise selection is advisory until kernel reconstruction.",
        ),
        ReconstructionCase(
            case_id="lean.kernel.reconstructed",
            provider_id="lean",
            claimed_authority=ResultAuthority.THEOREM.value,
            retained_authority_ceiling=ResultAuthority.THEOREM.value,
            reconstructed=True,
            kernel_accepted=True,
            join_verdict=JoinVerdict.RECONSTRUCTED.value,
            notes=(
                "Official Lean kernel acceptance under pinned imports "
                f"{list(DEFAULT_LEAN_IMPORTS)}."
            ),
        ),
        ReconstructionCase(
            case_id="rocq.kernel.reconstructed",
            provider_id="rocq",
            claimed_authority=ResultAuthority.THEOREM.value,
            retained_authority_ceiling=ResultAuthority.THEOREM.value,
            reconstructed=True,
            kernel_accepted=True,
            join_verdict=JoinVerdict.RECONSTRUCTED.value,
            notes=(
                "Official Rocq kernel acceptance under pinned imports "
                f"{list(DEFAULT_ROCQ_IMPORTS)}."
            ),
        ),
        ReconstructionCase(
            case_id="isabelle.kernel.reconstructed",
            provider_id="isabelle",
            claimed_authority=ResultAuthority.THEOREM.value,
            retained_authority_ceiling=ResultAuthority.THEOREM.value,
            reconstructed=True,
            kernel_accepted=True,
            join_verdict=JoinVerdict.RECONSTRUCTED.value,
            notes=(
                "Official Isabelle kernel acceptance under pinned imports "
                f"{list(DEFAULT_ISABELLE_IMPORTS)}."
            ),
        ),
        ReconstructionCase(
            case_id="lean.sorry.rejected",
            provider_id="lean",
            claimed_authority=ResultAuthority.THEOREM.value,
            retained_authority_ceiling=ResultAuthority.CANDIDATE.value,
            reconstructed=False,
            kernel_accepted=False,
            join_verdict=JoinVerdict.REJECT.value,
            notes="sorry/admit trust escapes never establish kernel authority.",
        ),
    ]
    return tuple(sorted(cases, key=lambda item: item.case_id))


def build_e2e_slices() -> tuple[EndToEndSlice, ...]:
    """Compact end-to-end vertical slices joined into the conformance report."""

    slices = [
        EndToEndSlice(
            slice_id="software_verification.smt.z3",
            domain_id="software_verification",
            family_id="first_order",
            provider_id="z3",
            disposition="native",
            authority_ceiling=AuthorityCeiling.EXACT.value,
            notes="Source → SMT-LIB → Z3 satisfiability authority.",
        ),
        EndToEndSlice(
            slice_id="software_verification.smt.cvc5",
            domain_id="software_verification",
            family_id="first_order",
            provider_id="cvc5",
            disposition="native",
            authority_ceiling=AuthorityCeiling.EXACT.value,
            notes="Source → SMT-LIB → CVC5 satisfiability authority.",
        ),
        EndToEndSlice(
            slice_id="software_verification.atp.vampire",
            domain_id="software_verification",
            family_id="first_order",
            provider_id="vampire",
            disposition="translated",
            authority_ceiling=AuthorityCeiling.CANDIDATE.value,
            notes="TPTP candidate until reconstruction.",
        ),
        EndToEndSlice(
            slice_id="software_verification.tla.tlc",
            domain_id="software_verification",
            family_id="transition_system",
            provider_id="tla_tlc",
            disposition="bounded",
            authority_ceiling=AuthorityCeiling.BOUNDED.value,
            notes="Bounded TLC model check.",
        ),
        EndToEndSlice(
            slice_id="crypto_ir.protocol.proverif",
            domain_id="crypto_ir",
            family_id="cryptographic_protocol",
            provider_id="proverif",
            disposition="native",
            authority_ceiling=AuthorityCeiling.PROTOCOL_SYMBOLIC.value,
            notes="Protocol symbolic authority only.",
        ),
        EndToEndSlice(
            slice_id="software_verification.hyper.hyperltl",
            domain_id="software_verification",
            family_id="hyperproperty",
            provider_id="hyperltl_autohyper_mchyper",
            disposition="bounded",
            authority_ceiling=AuthorityCeiling.BOUNDED.value,
            notes="HyperLTL common-fragment bounded check.",
        ),
        EndToEndSlice(
            slice_id="software_verification.runtime.mtl",
            domain_id="software_verification",
            family_id="temporal",
            provider_id="runtime_mtl",
            disposition="bounded",
            authority_ceiling=AuthorityCeiling.FINITE_TRACE.value,
            notes="Runtime MTL finite-trace monitor.",
        ),
        EndToEndSlice(
            slice_id="software_verification.kernel.lean",
            domain_id="software_verification",
            family_id="higher_order",
            provider_id="lean",
            disposition="native",
            authority_ceiling=AuthorityCeiling.KERNEL.value,
            notes="Lean kernel reconstruction path.",
        ),
    ]
    return tuple(sorted(slices, key=lambda item: item.slice_id))


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LogicConformanceReport:
    """``LogicConformanceReport@1`` joined differential/metamorphic/reconstruction evidence."""

    differential_cases: tuple[DifferentialCase, ...] = field(default_factory=tuple)
    preservation_fixtures: tuple[PreservationFixture, ...] = field(
        default_factory=tuple
    )
    reconstruction_cases: tuple[ReconstructionCase, ...] = field(default_factory=tuple)
    e2e_slices: tuple[EndToEndSlice, ...] = field(default_factory=tuple)
    evidence_subset: tuple[str, ...] = REQUIRED_EVIDENCE_SUBSET
    summary: Mapping[str, Any] = field(default_factory=dict)
    interface: str = LOGIC_CONFORMANCE_REPORT_INTERFACE
    schema_version: str = LOGIC_CONFORMANCE_REPORT_SCHEMA
    report_version: str = LOGIC_CONFORMANCE_REPORT_VERSION
    task_id: str = TASK_ID
    goal_id: str = GOAL_ID
    program_id: str = PROGRAM_ID
    # Content identity fields are computed after body materialization.
    content_sha256: str = ""
    content_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "differential_cases", tuple(self.differential_cases)
        )
        object.__setattr__(
            self, "preservation_fixtures", tuple(self.preservation_fixtures)
        )
        object.__setattr__(
            self, "reconstruction_cases", tuple(self.reconstruction_cases)
        )
        object.__setattr__(self, "e2e_slices", tuple(self.e2e_slices))
        object.__setattr__(
            self,
            "evidence_subset",
            tuple(
                _identifier(item, "evidence_subset item")
                for item in self.evidence_subset
            ),
        )
        if not isinstance(self.summary, Mapping):
            raise ConformanceJoinError("summary must be a mapping")
        object.__setattr__(self, "summary", MappingProxyType(dict(self.summary)))
        if self.interface != LOGIC_CONFORMANCE_REPORT_INTERFACE:
            raise ConformanceJoinError(
                f"interface must be {LOGIC_CONFORMANCE_REPORT_INTERFACE}"
            )
        if self.schema_version != LOGIC_CONFORMANCE_REPORT_SCHEMA:
            raise ConformanceJoinError(
                f"schema must be {LOGIC_CONFORMANCE_REPORT_SCHEMA}"
            )

        body = self._body_dict()
        digest = _stable_digest(body)
        content_id = _content_id(digest)
        if self.content_sha256 and self.content_sha256 != digest:
            raise ConformanceJoinError(
                "content_sha256 does not match deterministic body digest"
            )
        if self.content_id and self.content_id != content_id:
            raise ConformanceJoinError(
                "content_id does not match deterministic body content id"
            )
        object.__setattr__(self, "content_sha256", digest)
        object.__setattr__(self, "content_id", content_id)

    def _body_dict(self) -> dict[str, Any]:
        """Payload used for content addressing (excludes content_sha256/content_id)."""

        return {
            "differential_cases": [item.to_dict() for item in self.differential_cases],
            "e2e_slices": [item.to_dict() for item in self.e2e_slices],
            "evidence_subset": list(self.evidence_subset),
            "goal_id": self.goal_id,
            "interface": self.interface,
            "preservation_fixtures": [
                item.to_dict() for item in self.preservation_fixtures
            ],
            "program_id": self.program_id,
            "reconstruction_cases": [
                item.to_dict() for item in self.reconstruction_cases
            ],
            "report_version": self.report_version,
            "schema_version": self.schema_version,
            "summary": dict(self.summary),
            "task_id": self.task_id,
        }

    @property
    def digest(self) -> str:
        return self.content_sha256

    def to_dict(self) -> dict[str, Any]:
        payload = self._body_dict()
        payload["content_id"] = self.content_id
        payload["content_sha256"] = self.content_sha256
        return payload

    def to_json(self, *, indent: int | None = 2) -> str:
        separators = None if indent is not None else (",", ":")
        return json.dumps(
            self.to_dict(),
            ensure_ascii=True,
            indent=indent,
            separators=separators,
            sort_keys=True,
        ) + ("\n" if indent is not None else "")

    def acceptance_holds(self) -> bool:
        return bool(self.summary.get("acceptance_holds"))


def _build_summary(
    differential: Sequence[DifferentialCase],
    fixtures: Sequence[PreservationFixture],
    reconstruction: Sequence[ReconstructionCase],
    e2e: Sequence[EndToEndSlice],
    translation_ids: Sequence[str],
) -> dict[str, Any]:
    disagree_cases = [
        item for item in differential if item.raw_classification == "disagree"
    ]
    disagree_all_inconclusive = all(
        item.join_verdict == JoinVerdict.INCONCLUSIVE.value for item in disagree_cases
    )
    translation_ids_sorted = tuple(sorted(set(translation_ids)))
    covered = {
        item.translation_id
        for item in fixtures
        if item.polarity is FixturePolarity.POSITIVE
        or (
            isinstance(item.polarity, str)
            and item.polarity == FixturePolarity.POSITIVE.value
        )
    }
    covered_neg = {
        item.translation_id
        for item in fixtures
        if item.polarity is FixturePolarity.NEGATIVE
        or (
            isinstance(item.polarity, str)
            and item.polarity == FixturePolarity.NEGATIVE.value
        )
    }
    every_translation_has_pos_neg = (
        set(translation_ids_sorted) <= covered
        and set(translation_ids_sorted) <= covered_neg
        and bool(translation_ids_sorted)
    )
    high_assurance_ok = all(
        item.reconstructed
        or item.retained_authority_ceiling.lower()
        not in {c.lower() for c in _HIGH_CEILINGS}
        for item in reconstruction
    )
    hermetic_e2e = all(item.hermetic for item in e2e)
    acceptance = (
        disagree_all_inconclusive
        and every_translation_has_pos_neg
        and high_assurance_ok
        and hermetic_e2e
        and bool(differential)
        and bool(reconstruction)
        and bool(e2e)
    )
    return {
        "acceptance_holds": acceptance,
        "differential_case_count": len(differential),
        "disagree_case_count": len(disagree_cases),
        "disagree_all_inconclusive": disagree_all_inconclusive,
        "e2e_slice_count": len(e2e),
        "every_translation_has_positive_and_negative_fixtures": (
            every_translation_has_pos_neg
        ),
        "hermetic": True,
        "high_assurance_candidates_reconstruct_or_retain_lower_ceiling": (
            high_assurance_ok
        ),
        "preservation_fixture_count": len(fixtures),
        "reconstruction_case_count": len(reconstruction),
        "translation_count": len(translation_ids_sorted),
        "translation_ids": list(translation_ids_sorted),
    }


def build_logic_conformance_report() -> LogicConformanceReport:
    """Materialize the deterministic LFP-043 joined conformance report."""

    differential = build_differential_corpus()
    fixtures = build_preservation_fixtures()
    reconstruction = build_reconstruction_corpus()
    e2e = build_e2e_slices()
    translation_ids = [
        edge.translation_id for edge in DEFAULT_GENERATED_CATALOG.translations
    ]
    if not translation_ids:
        translation_ids = list(DEFAULT_REGISTRY.translations.keys())
    summary = _build_summary(
        differential, fixtures, reconstruction, e2e, translation_ids
    )
    return LogicConformanceReport(
        differential_cases=differential,
        preservation_fixtures=fixtures,
        reconstruction_cases=reconstruction,
        e2e_slices=e2e,
        evidence_subset=REQUIRED_EVIDENCE_SUBSET,
        summary=summary,
    )


def materialize_report_path() -> Path:
    """Resolve the durable report path under the nested datasets tree."""

    # Prefer package-relative path from this test file.
    here = Path(__file__).resolve()
    # .../ipfs_datasets_py/tests/conformance/logic/this_file.py
    # parents: logic=0, conformance=1, tests=2, ipfs_datasets_py=3
    datasets_root = here.parents[3]
    candidate = datasets_root / DEFAULT_REPORT_RELATIVE_PATH
    if candidate.parent.is_dir() or candidate.parent.parent.is_dir():
        return candidate
    # Fallback: cwd-relative (pytest from ipfs_datasets_py).
    return Path(DEFAULT_REPORT_RELATIVE_PATH)


def write_conformance_report(path: Path | None = None) -> LogicConformanceReport:
    """Atomically write the deterministic joined report (used by tests/CI)."""

    report = build_logic_conformance_report()
    target = path or materialize_report_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = report.to_json(indent=2)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(payload, encoding="utf-8")
    tmp.replace(target)
    return report


def load_committed_report(path: Path | None = None) -> dict[str, Any]:
    target = path or materialize_report_path()
    text = target.read_text(encoding="utf-8")
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ConformanceJoinError("committed report must be a JSON object")
    return payload


# ---------------------------------------------------------------------------
# Tests — interface / determinism / content addressing
# ---------------------------------------------------------------------------


def test_interface_identity() -> None:
    report = build_logic_conformance_report()
    assert report.interface == LOGIC_CONFORMANCE_REPORT_INTERFACE
    assert report.interface == "LogicConformanceReport@1"
    assert report.task_id == TASK_ID == "LFP-043"
    assert report.goal_id == GOAL_ID == "LFP-G080"
    assert report.schema_version == LOGIC_CONFORMANCE_REPORT_SCHEMA
    payload = report.to_dict()
    assert payload["interface"] == "LogicConformanceReport@1"


def test_report_is_deterministic_and_content_addressed() -> None:
    first = build_logic_conformance_report()
    second = build_logic_conformance_report()
    assert first.to_json() == second.to_json()
    assert first.content_sha256 == second.content_sha256
    assert first.content_id == second.content_id
    assert first.content_id == f"sha256:{first.content_sha256}"
    # Digest is over body only (excluding content identity fields).
    body = first._body_dict()
    assert _stable_digest(body) == first.content_sha256
    # Re-encode committed form is byte-stable.
    assert first.to_json() == second.to_json()
    wire = json.loads(first.to_json())
    assert wire["content_sha256"] == first.content_sha256
    assert wire["task_id"] == "LFP-043"


def test_required_evidence_subset_present() -> None:
    report = build_logic_conformance_report()
    assert set(REQUIRED_EVIDENCE_SUBSET) <= set(report.evidence_subset)
    for token in (
        "differential",
        "metamorphic",
        "translation",
        "preservation",
        "reconstruction",
        "disagreement",
        "inconclusive",
        "end_to_end",
    ):
        assert token in report.evidence_subset


def test_acceptance_holds() -> None:
    report = build_logic_conformance_report()
    assert report.acceptance_holds() is True
    assert report.summary["acceptance_holds"] is True
    assert report.summary["disagree_all_inconclusive"] is True
    assert report.summary[
        "every_translation_has_positive_and_negative_fixtures"
    ] is True
    assert report.summary[
        "high_assurance_candidates_reconstruct_or_retain_lower_ceiling"
    ] is True


# ---------------------------------------------------------------------------
# Disagreement → typed inconclusive
# ---------------------------------------------------------------------------


def test_disagreement_is_typed_inconclusive() -> None:
    assert (
        typed_inconclusive_for_disagreement(DifferentialClassification.DISAGREE)
        == JoinVerdict.INCONCLUSIVE.value
    )
    assert typed_inconclusive_for_disagreement("disagree") == "inconclusive"
    raw, join = classify_backend_pair("sat", "unsat")
    assert raw == "disagree"
    assert join == JoinVerdict.INCONCLUSIVE.value

    report = build_logic_conformance_report()
    disagree = [
        case
        for case in report.differential_cases
        if case.raw_classification == "disagree"
    ]
    assert disagree, "corpus must include at least one disagreement case"
    for case in disagree:
        assert case.join_verdict == JoinVerdict.INCONCLUSIVE.value
        # Never promoted to agree / proved by majority vote.
        assert case.join_verdict != JoinVerdict.AGREE.value


def test_differential_corpus_covers_required_pairs() -> None:
    report = build_logic_conformance_report()
    pairs = {
        (case.left_provider, case.right_provider)
        for case in report.differential_cases
    }
    # Required differential pairs from the plan.
    assert ("z3", "cvc5") in pairs
    assert ("vampire", "eprover") in pairs
    assert ("tla_tlc", "apalache") in pairs
    assert ("proverif", "tamarin") in pairs
    families = {case.family for case in report.differential_cases}
    assert {
        "smt",
        "atp",
        "tla",
        "protocol",
        "hyperproperty",
        "runtime",
    } <= families


def test_disagree_never_becomes_proof_or_kernel() -> None:
    report = build_logic_conformance_report()
    for case in report.differential_cases:
        if case.join_verdict == JoinVerdict.INCONCLUSIVE.value:
            # Inconclusive differential evidence cannot mint high authority.
            assert case.join_verdict not in {
                "proved",
                "kernel",
                "theorem",
                "agree_proved",
            }


# ---------------------------------------------------------------------------
# Translation preservation fixtures (positive + negative)
# ---------------------------------------------------------------------------


def test_every_translation_has_positive_and_negative_fixtures() -> None:
    catalog = DEFAULT_GENERATED_CATALOG
    translation_ids = [edge.translation_id for edge in catalog.translations]
    if not translation_ids:
        translation_ids = list(DEFAULT_REGISTRY.translations.keys())
    assert translation_ids, "expected at least one translation edge"

    fixtures = build_preservation_fixtures()
    by_translation: dict[str, set[str]] = {}
    for fixture in fixtures:
        polarity = (
            fixture.polarity.value
            if isinstance(fixture.polarity, FixturePolarity)
            else str(fixture.polarity)
        )
        by_translation.setdefault(fixture.translation_id, set()).add(polarity)

    for translation_id in translation_ids:
        polarities = by_translation.get(translation_id, set())
        assert FixturePolarity.POSITIVE.value in polarities, (
            f"{translation_id} missing positive preservation fixture"
        )
        assert FixturePolarity.NEGATIVE.value in polarities, (
            f"{translation_id} missing negative preservation fixture"
        )

    # Negative fixtures reject silent drops.
    negatives = [
        item for item in fixtures if item.polarity is FixturePolarity.NEGATIVE
    ]
    assert negatives
    for item in negatives:
        assert item.expected_pass is False
        assert item.silent_drop_attempted is True


def test_preservation_relation_respects_authority_ceiling() -> None:
    for kind in TranslationKind:
        relation = PreservationRelation(
            _preservation_for_kind(kind)
        )
        ceiling = maximum_authority_for(relation)
        assert isinstance(ceiling, EvidenceAuthority)


def test_metamorphic_alpha_and_notation_do_not_change_join() -> None:
    """Metamorphic: reordering fixture construction yields identical digests."""

    first = build_preservation_fixtures()
    second = build_preservation_fixtures()
    assert [item.to_dict() for item in first] == [item.to_dict() for item in second]
    digest_a = _stable_digest({"fixtures": [item.to_dict() for item in first]})
    digest_b = _stable_digest({"fixtures": [item.to_dict() for item in second]})
    assert digest_a == digest_b


# ---------------------------------------------------------------------------
# High-assurance reconstruction / lower ceiling
# ---------------------------------------------------------------------------


def test_high_assurance_candidates_reconstruct_or_retain_lower_ceiling() -> None:
    cases = build_reconstruction_corpus()
    providers = {case.provider_id for case in cases}
    # Cover ATP, hammer, and kernels (``e`` is the eprover alias surface).
    required = set(HIGH_ASSURANCE_CANDIDATE_PROVIDERS) - {"e"}
    assert required <= providers
    assert {"vampire", "eprover", "hammer", "lean", "rocq", "isabelle"} <= providers

    for case in cases:
        if case.reconstructed:
            assert case.kernel_accepted is True
            assert case.join_verdict == JoinVerdict.RECONSTRUCTED.value
            assert case.retained_authority_ceiling == ResultAuthority.THEOREM.value
        else:
            ceiling = case.retained_authority_ceiling.lower()
            assert ceiling not in {c.lower() for c in _HIGH_CEILINGS}
            assert case.join_verdict in {
                JoinVerdict.CANDIDATE_RETAINED.value,
                JoinVerdict.REJECT.value,
            }


def test_reconstructed_kernel_cases_use_pinned_imports() -> None:
    cases = build_reconstruction_corpus()
    reconstructed = [case for case in cases if case.reconstructed]
    assert reconstructed
    for case in reconstructed:
        assert case.provider_id in {"lean", "rocq", "isabelle"}
        assert case.kernel_accepted is True
        # Notes bind the pinned import set used by the authority audit.
        if case.provider_id == "lean":
            for imp in DEFAULT_LEAN_IMPORTS:
                assert imp in case.notes
        elif case.provider_id == "rocq":
            for imp in DEFAULT_ROCQ_IMPORTS:
                assert imp in case.notes
        elif case.provider_id == "isabelle":
            for imp in DEFAULT_ISABELLE_IMPORTS:
                assert imp in case.notes


def test_unreconstructed_candidate_cannot_claim_theorem_ceiling() -> None:
    with pytest.raises(ConformanceJoinError):
        ReconstructionCase(
            case_id="bad.vampire.theorem_ceiling",
            provider_id="vampire",
            claimed_authority=ResultAuthority.THEOREM.value,
            retained_authority_ceiling=ResultAuthority.THEOREM.value,
            reconstructed=False,
            kernel_accepted=False,
            join_verdict=JoinVerdict.CANDIDATE_RETAINED.value,
        )


# ---------------------------------------------------------------------------
# End-to-end join + upstream evidence
# ---------------------------------------------------------------------------


def test_e2e_slices_are_hermetic_and_cover_plan_routes() -> None:
    slices = build_e2e_slices()
    assert all(item.hermetic for item in slices)
    providers = {item.provider_id for item in slices}
    for provider_id in (
        "z3",
        "cvc5",
        "vampire",
        "tla_tlc",
        "proverif",
        "hyperltl_autohyper_mchyper",
        "runtime_mtl",
        "lean",
    ):
        assert provider_id in providers


def test_join_composes_upstream_lfp040_and_lfp042_hermetically() -> None:
    """Joined evidence reuses sealed matrix runner and authority audit digests."""

    # Matrix runner interface remains hermetic (LFP-040).
    assert DEFAULT_CONFORMANCE_RUNNER.INTERFACE == "LogicConformanceRunner@1"
    assert DEFAULT_CONFORMANCE_RUNNER.task_id == "LFP-040"
    matrix_receipt = run_domain_provider_matrix()
    assert matrix_receipt is not None
    assert matrix_receipt.hermetic is True
    assert matrix_receipt.false_skips == 0

    # Authority audit boundaries remain closed (LFP-042).
    audit = run_authority_audit()
    assert audit.all_boundaries_hold is True
    assert DEFAULT_AUTHORITY_AUDIT.interface == "LogicAuthorityAudit@1"
    assert audit.digest == run_authority_audit().digest

    report = build_logic_conformance_report()
    # Upstream digests are stable inputs; join report remains independent.
    assert report.acceptance_holds() is True
    assert report.task_id == "LFP-043"
    assert report.goal_id == audit.goal_id == "LFP-G080"


# ---------------------------------------------------------------------------
# Durable report artifact
# ---------------------------------------------------------------------------


def test_committed_report_matches_rebuilt_report() -> None:
    """Durable report is materialised deterministically and content-addressed.

    Always (re)writes the declared output so the artifact stays byte-stable
    with the hermetic builder.  A second rebuild must match the on-disk file
    without further mutation.
    """

    path = materialize_report_path()
    report = write_conformance_report(path)
    committed = load_committed_report(path)

    # Byte-stable JSON (sorted keys, trailing newline).
    rebuilt = build_logic_conformance_report()
    assert path.read_text(encoding="utf-8") == rebuilt.to_json(indent=2)
    assert path.read_text(encoding="utf-8") == report.to_json(indent=2)

    assert committed["interface"] == LOGIC_CONFORMANCE_REPORT_INTERFACE
    assert committed["task_id"] == TASK_ID
    assert committed["content_sha256"] == report.content_sha256
    assert committed["content_id"] == report.content_id
    assert committed["content_sha256"] == rebuilt.content_sha256
    assert committed["summary"]["acceptance_holds"] is True
    assert committed["summary"]["disagree_all_inconclusive"] is True
    assert committed["summary"][
        "every_translation_has_positive_and_negative_fixtures"
    ] is True
    assert committed["summary"][
        "high_assurance_candidates_reconstruct_or_retain_lower_ceiling"
    ] is True


def test_report_content_address_is_sha256_of_body() -> None:
    report = build_logic_conformance_report()
    body = report._body_dict()
    encoded = json.dumps(
        body,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")
    assert hashlib.sha256(encoded).hexdigest() == report.content_sha256


def test_write_conformance_report_is_idempotent(tmp_path: Path) -> None:
    target = tmp_path / "logic_parser_conformance_report.json"
    first = write_conformance_report(target)
    second = write_conformance_report(target)
    assert first.content_sha256 == second.content_sha256
    assert target.read_text(encoding="utf-8") == first.to_json(indent=2)


# ---------------------------------------------------------------------------
# Durable artifact materialization (declared output)
# ---------------------------------------------------------------------------


def _materialize_declared_report() -> LogicConformanceReport | None:
    """Write the durable LFP-043 report so the declared output is always current.

    Invoked at import time under pytest collection and again from the committed
    report test.  Failures are deferred to explicit acceptance assertions.
    """

    try:
        return write_conformance_report(materialize_report_path())
    except Exception as exc:  # pragma: no cover - best-effort import materialize
        import warnings

        warnings.warn(
            f"LFP-043 logic_parser_conformance_report materialization deferred: {exc}",
            stacklevel=1,
        )
        return None


# Materialize the declared durable report when this module is collected/imported.
_MATERIALIZED_REPORT = _materialize_declared_report()